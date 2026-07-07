"""Filesystem primitives shared by every writer: atomic replace, exclusive
create, and a per-journal lock.

Multiple MCP sessions (each its own process) and the CLI can touch the same
journal at once. Markdown stays safe under concurrency by construction:
finished bytes appear atomically (never a half-written file), new files are
claimed exclusively (never two writers on one path), and read-modify-write
sequences are serialized by an flock on the journal root.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover — Windows has no flock; see docs
    fcntl = None  # type: ignore[assignment]


def _tmp_for(path: Path) -> Path:
    return path.parent / f".{path.name}.{os.getpid()}.tmp"


def write_text_atomic(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` atomically — readers see old or new
    bytes, never a truncated file, even across a crash mid-write."""
    tmp = _tmp_for(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def create_text_exclusive(path: Path, text: str) -> bool:
    """Create ``path`` with ``text`` atomically, failing (False) if it already
    exists. Unlike open("x") + write, the file appears fully written or not at
    all; unlike an exists()-check, two processes can't both claim the path.

    On filesystems without hard links (exFAT, some network mounts) this falls
    back to O_EXCL creation — still exclusive, just not atomic-content."""
    tmp = _tmp_for(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
        except OSError:
            try:
                with open(path, "x", encoding="utf-8") as fh:
                    fh.write(text)
            except FileExistsError:
                return False
        return True
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def journal_lock(root: Path) -> Iterator[None]:
    """Serialize mutating operations on a journal across processes.

    Guards read-modify-write sequences (task updates, view regeneration) that
    atomic writes alone can't protect — without it, two sessions updating the
    same task would silently drop one side's changes. No-op where flock is
    unavailable (Windows) or the journal doesn't exist yet — a typo'd path
    must stay a no-op, not materialize a directory tree with a .lock in it."""
    if fcntl is None or not root.is_dir():
        yield
        return
    with open(root / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
