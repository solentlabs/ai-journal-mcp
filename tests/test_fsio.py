"""Concurrency/durability primitives: atomic replace, exclusive create, journal lock."""

import subprocess
import sys

import pytest

from ai_journal_mcp.fsio import create_text_exclusive, journal_lock, write_text_atomic

TRY_LOCK = (
    "import fcntl, sys\n"
    "fh = open(sys.argv[1] + '/.lock', 'w')\n"
    "try:\n"
    "    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
    "    print('acquired')\n"
    "except BlockingIOError:\n"
    "    print('excluded')\n"
)


def _probe_lock(root) -> str:
    out = subprocess.run(
        [sys.executable, "-c", TRY_LOCK, str(root)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return out.stdout.strip()


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "f.md"
    write_text_atomic(target, "one")
    write_text_atomic(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert list(tmp_path.iterdir()) == [target]  # no temp litter


def test_atomic_write_failure_leaves_target_intact(tmp_path, monkeypatch):
    import os as _os

    target = tmp_path / "f.md"
    write_text_atomic(target, "original")

    def boom(src, dst):
        raise OSError("simulated crash at replace")

    monkeypatch.setattr(_os, "replace", boom)
    with pytest.raises(OSError):
        write_text_atomic(target, "half-written")
    assert target.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [target]  # temp cleaned up on failure


def test_exclusive_create_claims_once(tmp_path):
    target = tmp_path / "f.md"
    assert create_text_exclusive(target, "first") is True
    assert create_text_exclusive(target, "second") is False
    assert target.read_text(encoding="utf-8") == "first"  # loser never overwrites
    assert list(tmp_path.iterdir()) == [target]


def test_journal_lock_excludes_other_processes(tmp_path):
    with journal_lock(tmp_path):
        assert _probe_lock(tmp_path) == "excluded"  # held: second process blocked
    assert _probe_lock(tmp_path) == "acquired"  # released: free to claim


UPDATE_TASK = (
    "import sys\n"
    "from pathlib import Path\n"
    "from ai_journal_mcp.tasks import update_task\n"
    "update_task(Path(sys.argv[1]), sys.argv[2], **{sys.argv[3]: sys.argv[4]})\n"
)

WRITE_ENTRY = (
    "import sys\n"
    "from datetime import date\n"
    "from pathlib import Path\n"
    "from ai_journal_mcp.store import write_entry\n"
    "write_entry(Path(sys.argv[1]), date(2026, 7, 1), 'Standup', sys.argv[2])\n"
)


def test_concurrent_task_updates_lose_no_fields(tmp_path):
    # two sessions updating different fields of the same task: without the
    # journal lock this is read-modify-write, last write silently wins
    from ai_journal_mcp.tasks import create_task, get_task

    t = create_task(tmp_path, "Shared")
    procs = [
        subprocess.Popen([sys.executable, "-c", UPDATE_TASK, str(tmp_path), t.id, kw, val])
        for kw, val in (("priority", "high"), ("body", "notes from the other session"))
    ]
    assert [p.wait(timeout=30) for p in procs] == [0, 0]
    got = get_task(tmp_path, t.id)
    assert got.priority == "high"
    assert got.body == "notes from the other session"


def test_concurrent_same_title_entries_both_survive(tmp_path):
    # two sessions journaling the same date+title at once: exclusive create
    # must land two files, never one overwriting the other
    from ai_journal_mcp.store import load_managed

    procs = [
        subprocess.Popen([sys.executable, "-c", WRITE_ENTRY, str(tmp_path), body])
        for body in ("first session's text", "second session's text")
    ]
    assert [p.wait(timeout=30) for p in procs] == [0, 0]
    bodies = {e.body for e in load_managed(tmp_path)}
    assert bodies == {"first session's text", "second session's text"}


def test_exclusive_create_falls_back_without_hardlinks(tmp_path, monkeypatch):
    # exFAT / network mounts have no os.link — fall back to O_EXCL create
    import os as _os

    def no_links(src, dst):
        raise PermissionError("Operation not permitted (no hard links here)")

    monkeypatch.setattr(_os, "link", no_links)
    target = tmp_path / "f.md"
    assert create_text_exclusive(target, "first") is True
    assert target.read_text(encoding="utf-8") == "first"
    assert create_text_exclusive(target, "second") is False
    assert target.read_text(encoding="utf-8") == "first"


def test_journal_lock_never_materializes_missing_paths(tmp_path):
    ghost = tmp_path / "jurnals" / "dev"  # typo'd path
    with journal_lock(ghost):
        pass
    assert not ghost.exists()
    assert not (tmp_path / "jurnals").exists()
