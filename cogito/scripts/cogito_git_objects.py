"""Closed, read-only access to immutable Git objects used by Start Gate."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cogito_common import CogitoError


ObjectType = Literal["blob", "tree", "commit"]
_OBJECT_TYPES = {"blob", "tree", "commit"}
_FILE_MODES = {b"100644", b"100755"}
_TREE_MODE = b"40000"
_WINDOWS_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                  *(f"lpt{i}" for i in range(1, 10))}


@dataclass(frozen=True)
class ObjectInfo:
    oid: str
    type: ObjectType
    size: int


@dataclass(frozen=True)
class TreeEntry:
    path: bytes
    mode: str
    type: Literal["blob", "tree"]
    oid: str


class HardenedObjectReader:
    """Read Git objects without worktree, index, network, or ambient Git authority."""

    def __init__(self, root: str | Path, *, max_blob_bytes: int = 16 * 1024 * 1024,
                 max_tree_entries: int = 100_000, max_tree_depth: int = 128,
                 timeout: int = 20):
        self.root = Path(root).resolve()
        self.max_blob_bytes = max_blob_bytes
        self.max_tree_entries = max_tree_entries
        self.max_tree_depth = max_tree_depth
        self.timeout = timeout
        value = self._run_text("rev-parse", "--show-object-format").strip()
        if value not in {"sha1", "sha256"}:
            raise CogitoError(f"unsupported Git object format: {value}")
        self.object_format: Literal["sha1", "sha256"] = value  # type: ignore[assignment]
        self.oid_bytes = 20 if value == "sha1" else 32
        self.oid_chars = self.oid_bytes * 2
        self._object_cache: dict[tuple[str, str], bytes] = {}
        self._tree_cache: dict[str, tuple[tuple[bytes, bytes, str], ...]] = {}
        self.assert_closed_repository()

    def _environment(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update({
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        })
        return env

    def _argv(self, *args: str) -> list[str]:
        return ["git", "--no-pager", "--no-replace-objects", "--literal-pathspecs",
                "-c", "core.hooksPath=/dev/null", "-c", "protocol.allow=never",
                "-c", "gc.auto=0", "-C", str(self.root), *args]

    def _run(self, *args: str, data: bytes | None = None,
             allowed_codes: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[bytes]:
        try:
            result = subprocess.run(
                self._argv(*args), input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self._environment(), timeout=self.timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CogitoError(f"Git object validation failed: {exc}") from exc
        if result.returncode not in allowed_codes:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise CogitoError(f"Git object validation failed: {detail or 'Git command failed'}")
        return result

    def _run_text(self, *args: str, allowed_codes: tuple[int, ...] = (0,)) -> str:
        return self._run(*args, allowed_codes=allowed_codes).stdout.decode("utf-8", errors="strict")

    def require_full_oid(self, value: object, name: str = "object id") -> str:
        if not isinstance(value, str) or not re.fullmatch(
                rf"[0-9a-f]{{{self.oid_chars}}}", value):
            raise CogitoError(f"{name} must be a full lowercase {self.object_format} object id")
        return value

    def assert_closed_repository(self) -> None:
        common_value = self._run_text("rev-parse", "--git-common-dir").strip()
        common = Path(common_value)
        if not common.is_absolute():
            common = self.root / common
        common = common.resolve()
        risky_files = [
            common / "objects/info/alternates",
            common / "objects/info/http-alternates",
            common / "shallow",
            common / "info/grafts",
        ]
        objects = common / "objects"
        try:
            if objects.is_symlink() or objects.resolve().parent != common:
                raise CogitoError("closed Git object validation rejects external object storage")
        except OSError as exc:
            raise CogitoError(f"cannot inspect Git object storage: {exc}") from exc
        for path in risky_files:
            try:
                if path.is_file() and path.stat().st_size:
                    raise CogitoError(f"closed Git object validation rejects {path.name}")
            except OSError as exc:
                raise CogitoError(f"cannot inspect Git object storage: {exc}") from exc
        if any((common / "objects/pack").glob("*.promisor")):
            raise CogitoError("closed Git object validation rejects promisor packs")
        replace_dir = common / "refs/replace"
        if replace_dir.exists() and any(path.is_file() for path in replace_dir.rglob("*")):
            raise CogitoError("closed Git object validation rejects replace refs")
        packed_refs = common / "packed-refs"
        if packed_refs.is_file():
            try:
                if b" refs/replace/" in packed_refs.read_bytes():
                    raise CogitoError("closed Git object validation rejects packed replace refs")
            except OSError as exc:
                raise CogitoError(f"cannot inspect replace refs: {exc}") from exc
        config = self._run_text(
            "config", "--local", "--no-includes", "--get-regexp",
            r"^(extensions\.|remote\.|include\.|includeIf\.)",
            allowed_codes=(0, 1),
        )
        risky_keys = {line.split(None, 1)[0].casefold() for line in config.splitlines() if line}
        if (any(key.startswith(("include.", "includeif.")) for key in risky_keys) or
                "extensions.partialclone" in risky_keys or any(
                key.startswith("remote.") and key.rsplit(".", 1)[-1] in {
                    "promisor", "partialclonefilter"} for key in risky_keys)):
            raise CogitoError("closed Git object validation rejects includes or partial-clone configuration")

    def _object_infos(self, oids: list[str]) -> dict[str, ObjectInfo]:
        if not oids:
            return {}
        unique = list(dict.fromkeys(self.require_full_oid(oid) for oid in oids))
        result = self._run("cat-file", "--batch-check", data=("\n".join(unique) + "\n").encode("ascii"))
        lines = result.stdout.splitlines()
        if len(lines) != len(unique):
            raise CogitoError("Git returned an incomplete object inventory")
        infos: dict[str, ObjectInfo] = {}
        for expected, line in zip(unique, lines):
            fields = line.split(b" ")
            if len(fields) == 2 and fields[1] == b"missing":
                raise CogitoError(f"required Git object is missing: {expected}")
            if len(fields) != 3:
                raise CogitoError("Git returned a malformed object inventory")
            try:
                actual = fields[0].decode("ascii")
                kind = fields[1].decode("ascii")
                size = int(fields[2])
            except (UnicodeDecodeError, ValueError) as exc:
                raise CogitoError("Git returned a malformed object inventory") from exc
            if actual != expected or kind not in _OBJECT_TYPES or size < 0:
                raise CogitoError("Git returned an unexpected object inventory")
            infos[expected] = ObjectInfo(actual, kind, size)  # type: ignore[arg-type]
        return infos

    def read_object(self, oid: object, expected_type: ObjectType,
                    *, max_bytes: int | None = None) -> bytes:
        full_oid = self.require_full_oid(oid)
        if expected_type not in _OBJECT_TYPES:
            raise CogitoError(f"unsupported expected object type: {expected_type}")
        cached = self._object_cache.get((full_oid, expected_type))
        if cached is not None:
            return cached
        limit = self.max_blob_bytes if max_bytes is None and expected_type == "blob" else max_bytes
        info = self._object_infos([full_oid])[full_oid]
        if info.type != expected_type:
            raise CogitoError("Git returned an unexpected object type")
        if limit is not None and info.size > limit:
            raise CogitoError(f"Git {expected_type} exceeds the validation size limit")
        result = self._run("cat-file", "--batch", data=(full_oid + "\n").encode("ascii"))
        header, separator, remainder = result.stdout.partition(b"\n")
        if not separator:
            raise CogitoError("Git returned a malformed object header")
        fields = header.split(b" ")
        if len(fields) == 2 and fields[1] == b"missing":
            raise CogitoError(f"required Git object is missing: {full_oid}")
        if len(fields) != 3:
            raise CogitoError("Git returned a malformed object header")
        try:
            actual_oid, actual_type = fields[0].decode("ascii"), fields[1].decode("ascii")
            size = int(fields[2])
        except (UnicodeDecodeError, ValueError) as exc:
            raise CogitoError("Git returned a malformed object header") from exc
        if actual_oid != full_oid or actual_type != expected_type or size < 0:
            raise CogitoError("Git returned an unexpected object identity or type")
        if size != info.size:
            raise CogitoError("Git object changed during validation")
        if len(remainder) != size + 1 or remainder[-1:] != b"\n":
            raise CogitoError("Git returned a truncated or overlong object")
        data = remainder[:-1]
        identity = hashlib.new(
            self.object_format, f"{expected_type} {size}\0".encode("ascii") + data,
        ).hexdigest()
        if identity != full_oid:
            raise CogitoError("Git object content does not match its object id")
        self._object_cache[(full_oid, expected_type)] = data
        return data

    def commit_tree(self, commit_oid: object) -> str:
        data = self.read_object(commit_oid, "commit", max_bytes=4 * 1024 * 1024)
        headers = data.split(b"\n\n", 1)[0].splitlines()
        trees = [line[5:] for line in headers if line.startswith(b"tree ")]
        if len(trees) != 1 or headers[:1] != [b"tree " + trees[0]]:
            raise CogitoError("commit must contain one leading tree header")
        try:
            tree = self.require_full_oid(trees[0].decode("ascii"), "commit tree")
        except UnicodeDecodeError as exc:
            raise CogitoError("commit tree must be an ASCII object id") from exc
        self.read_object(tree, "tree", max_bytes=self.max_blob_bytes)
        return tree

    def _component(self, raw: bytes) -> str:
        try:
            value = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CogitoError("tree paths must be valid UTF-8") from exc
        if (not value or value in {".", ".."} or "\\" in value or
                any(ord(char) < 32 or ord(char) == 127 for char in value) or
                any(char in '<>:"|?*' for char in value) or
                unicodedata.normalize("NFC", value) != value or
                value.endswith((" ", "."))):
            raise CogitoError("tree contains an unsafe or non-canonical path component")
        stem = value.casefold().split(".", 1)[0]
        if value.casefold() == ".git" or stem in _WINDOWS_NAMES:
            raise CogitoError("tree contains a reserved path component")
        return value

    def _direct_tree_entries(self, tree_oid: str) -> tuple[tuple[bytes, bytes, str], ...]:
        cached = self._tree_cache.get(tree_oid)
        if cached is not None:
            return cached
        raw = self.read_object(tree_oid, "tree", max_bytes=self.max_blob_bytes)
        cursor = 0
        result: list[tuple[bytes, bytes, str]] = []
        names: set[bytes] = set()
        folded: set[str] = set()
        while cursor < len(raw):
            space = raw.find(b" ", cursor)
            nul = raw.find(b"\0", space + 1)
            if space <= cursor or nul < 0 or nul + 1 + self.oid_bytes > len(raw):
                raise CogitoError("tree object contains a malformed entry")
            mode, name = raw[cursor:space], raw[space + 1:nul]
            oid_raw = raw[nul + 1:nul + 1 + self.oid_bytes]
            cursor = nul + 1 + self.oid_bytes
            text = self._component(name)
            collision = text.casefold()
            if name in names or collision in folded:
                raise CogitoError("tree contains a duplicate or colliding path")
            names.add(name)
            folded.add(collision)
            oid = oid_raw.hex()
            if mode not in {_TREE_MODE, *_FILE_MODES}:
                raise CogitoError("tree contains a symlink, gitlink, or unsupported mode")
            result.append((mode, name, oid))
        saved = tuple(result)
        self._tree_cache[tree_oid] = saved
        return saved

    def walk_tree(self, tree_oid: object) -> tuple[TreeEntry, ...]:
        root = self.require_full_oid(tree_oid, "tree object id")
        deadline = time.monotonic() + self.timeout
        entries: list[TreeEntry] = []
        pending = [(root, b"", 0)]
        while pending:
            if time.monotonic() > deadline:
                raise CogitoError("tree validation exceeded its time limit")
            current, prefix, depth = pending.pop()
            if depth > self.max_tree_depth:
                raise CogitoError("tree exceeds the validation depth limit")
            for mode, name, oid in self._direct_tree_entries(current):
                path = prefix + name
                if mode == _TREE_MODE:
                    entries.append(TreeEntry(path, "040000", "tree", oid))
                    pending.append((oid, path + b"/", depth + 1))
                else:
                    entries.append(TreeEntry(path, mode.decode("ascii"), "blob", oid))
                if len(entries) > self.max_tree_entries:
                    raise CogitoError("tree exceeds the validation entry limit")
        infos = self._object_infos([entry.oid for entry in entries])
        if any(infos[entry.oid].type != entry.type for entry in entries):
            raise CogitoError("tree entry points to an object of the wrong type")
        return tuple(sorted(entries, key=lambda entry: entry.path))

    def blob_at(self, tree_oid: object, path: str) -> tuple[TreeEntry, bytes]:
        try:
            wanted = path.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CogitoError("manifest paths must be valid UTF-8") from exc
        matches = [entry for entry in self.walk_tree(tree_oid)
                   if entry.path == wanted and entry.type == "blob"]
        if len(matches) != 1:
            raise CogitoError(f"required blob is missing from tree: {path}")
        return matches[0], self.read_object(matches[0].oid, "blob")

    def require_ref(self, ref: str, expected_oid: object) -> None:
        if not re.fullmatch(r"refs/cogito/start-artifacts/[0-9a-f]{64}", ref):
            raise CogitoError("Start artifact ref is not content-addressed")
        expected = self.require_full_oid(expected_oid, "Start artifact ref target")
        actual = self._run_text("show-ref", "--verify", "--hash", ref).strip()
        if actual != expected:
            raise CogitoError("Start artifact ref does not retain the approved result tree")
