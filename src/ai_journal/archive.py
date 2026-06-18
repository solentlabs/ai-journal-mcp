"""Safely retire a directory or file into a verified ``.tar.gz``.

A small, journal-agnostic capability: compress a path into ``<path>.tar.gz``
preserving its original tree, **verify** the archive contains every original
file, and only then remove the original. Verification is a separate pure
function so the no-data-loss guarantee can be tested directly — nothing is ever
deleted unless the archive provably holds it.
"""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path


class ArchiveError(RuntimeError):
    """Raised when a path cannot be archived safely (so nothing is removed)."""


def _expected_members(path: Path) -> set[str]:
    """Relative names (under ``path.parent``) of every regular file to preserve."""
    base = path.parent
    files = [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    return {str(p.relative_to(base)) for p in files}


def verify_archive(archive: Path, expected: set[str]) -> set[str]:
    """Return the expected member names *missing* from the archive (empty = OK).

    Pure and side-effect-free: open the archive, compare its regular-file
    members against ``expected``. The caller decides what a non-empty result
    means — for ``archive_and_remove`` it means "do not delete".
    """
    with tarfile.open(archive, "r:gz") as tar:
        present = {m.name for m in tar.getmembers() if m.isfile()}
    return expected - present


def archive_and_remove(path: Path) -> Path:
    """Compress ``path`` into ``<path>.tar.gz``, verify it, then remove ``path``.

    Raises ``ArchiveError`` *without deleting anything* if the archive already
    exists or fails verification. Returns the archive path on success.
    """
    archive = path.with_name(path.name + ".tar.gz")
    if archive.exists():
        raise ArchiveError(f"archive already exists, refusing to overwrite: {archive}")

    expected = _expected_members(path)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(path, arcname=path.name)  # preserves the original tree under path.name

    missing = verify_archive(archive, expected)
    if missing:
        raise ArchiveError(f"{archive} is missing {len(missing)} file(s); original left in place")

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return archive
