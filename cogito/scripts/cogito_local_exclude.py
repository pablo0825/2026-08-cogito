"""Install repository-local runtime defaults without replacing user rules."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from cogito_common import CogitoError
from cogito_git import GitRepository


def ensure_local_excludes(root: Path) -> None:
    # Unstaged runtime-only runs also support plain directories. A Git marker
    # means validation must succeed: never silently skip a broken repository.
    root = root.resolve()
    markers = [directory / '.git' for directory in (root, *root.parents)]
    if not (any(os.path.lexists(marker) for marker in markers)
            or os.environ.get('GIT_DIR')
            or ((root / 'HEAD').exists() and (root / 'objects').is_dir())):
        return
    git = GitRepository(root)
    path = Path(git.run('rev-parse', '--git-path', 'info/exclude'))
    if not path.is_absolute():
        path = root / path
    if path.is_symlink() or path.parent.is_symlink():
        raise CogitoError('local exclude must not be a symlink')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
        with os.fdopen(descriptor, 'r+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            original = handle.read()
            missing = [rule for rule in (b'/.cogito/runs/', b'/.cogito/worktrees/')
                       if rule not in original.splitlines()]
            if missing:
                # Lower precedence than the existing user's rules, including
                # explicit exceptions. Preserve their original bytes verbatim.
                handle.seek(0)
                handle.write(b'\n'.join(missing) + b'\n' + original)
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        raise CogitoError(f'cannot install local runtime excludes: {exc}') from exc
