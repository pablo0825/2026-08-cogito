"""Small, non-mutating field checks shared by executable JSON contracts.

These functions validate; they never coerce, insert defaults, remove extension
fields, or reorder data. Callers can therefore validate immutable artifacts
without changing their content hashes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from cogito_common import ID_RE, CogitoError


RUN_ID_RE = re.compile(r"^(?:DEV|MNT)-[A-Za-z0-9._-]+$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{7,64}$")
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def require_object(value: Any, name: str, *fields: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CogitoError(f"{name} must be an object")
    missing = set(fields) - value.keys()
    if missing:
        raise CogitoError(f"{name} is missing fields: {sorted(missing)}")
    return value


def require_string(value: Any, name: str, pattern: re.Pattern[str] | None = None) -> None:
    if not isinstance(value, str) or not value or "\0" in value:
        raise CogitoError(f"{name} must be a non-empty string without NUL bytes")
    if pattern is not None and not pattern.fullmatch(value):
        raise CogitoError(f"{name} has an invalid format")


def require_id(value: Any, name: str) -> None:
    require_string(value, name, ID_RE)


def require_choice(value: Any, name: str, choices: Iterable[str]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise CogitoError(f"{name} must be one of {sorted(choices)}")


def require_boolean(value: Any, name: str) -> None:
    if type(value) is not bool:
        raise CogitoError(f"{name} must be a boolean")


def require_integer(value: Any, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CogitoError(f"{name} must be an integer from {minimum} through {maximum}")


def require_array(value: Any, name: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise CogitoError(f"{name} must be a{' non-empty' if nonempty else ''} array")
    return value


def require_strings(value: Any, name: str, *, nonempty: bool = False) -> None:
    for index, item in enumerate(require_array(value, name, nonempty=nonempty)):
        require_string(item, f"{name}[{index}]")


def safe_repo_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        return False
    candidate = Path(value)
    return not candidate.is_absolute() and ".." not in candidate.parts


def require_path(value: Any, name: str) -> None:
    if not safe_repo_path(value):
        raise CogitoError(f"{name} must be a safe repository-relative path")


def require_paths(value: Any, name: str, *, nonempty: bool = False) -> None:
    for index, item in enumerate(require_array(value, name, nonempty=nonempty)):
        require_path(item, f"{name}[{index}]")


def validate_document(value: Any, name: str) -> None:
    document = require_object(value, name, "path", "hash")
    require_path(document["path"], f"{name}.path")
    require_string(document["hash"], f"{name}.hash", CONTENT_HASH_RE)
