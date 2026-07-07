from datetime import date

import pytest

from ai_journal_mcp import server
from ai_journal_mcp.config import JournalSource
from ai_journal_mcp.store import write_entry
from ai_journal_mcp.tasks import (
    TaskError,
    create_task,
    get_task,
    is_ready,
    load_tasks,
    sorted_tasks,
    update_task,
)


def test_create_and_load(tmp_path):
    t = create_task(tmp_path, "Ship 0.1.0", body="tag and publish", priority="high")
    assert t.id == "ship-0-1-0"
    assert t.status == "open" and t.priority == "high"
    assert t.path.exists()
    [loaded] = load_tasks(tmp_path)
    assert loaded.title == "Ship 0.1.0"
    assert loaded.body == "tag and publish"


def test_update_is_mutable_and_partial(tmp_path):
    t = create_task(tmp_path, "Wire CI", priority="medium")
    upd = update_task(tmp_path, t.id, status="done")
    assert upd.status == "done"
    assert upd.priority == "medium"  # untouched fields stay
    assert get_task(tmp_path, t.id).status == "done"  # persisted to disk


def test_invalid_fields_rejected(tmp_path):
    with pytest.raises(TaskError):
        create_task(tmp_path, "x", priority="urgent")
    t = create_task(tmp_path, "y")
    with pytest.raises(TaskError):
        update_task(tmp_path, t.id, status="wip")


def test_missing_task(tmp_path):
    with pytest.raises(TaskError):
        get_task(tmp_path, "nope")


@pytest.mark.parametrize(
    "bad_id",
    ["../entries/2026-07/01-note", "/tmp/evil", "sub/task", "a\\b", "..", ".hidden", ""],
)
def test_path_like_task_ids_rejected(tmp_path, bad_id):
    with pytest.raises(TaskError, match="invalid task id"):
        get_task(tmp_path, bad_id)


def test_update_task_cannot_rewrite_entry_files(tmp_path):
    # regression: a path-like id escaped tasks/ and rewrote the entry file in
    # place, replacing its frontmatter and dropping it from views and index
    path = write_entry(tmp_path, date(2026, 7, 1), "My Note", "precious text")
    before = path.read_text(encoding="utf-8")
    stem = str(path.relative_to(tmp_path))[:-3]
    with pytest.raises(TaskError, match="invalid task id"):
        update_task(tmp_path, f"../{stem}", status="done")
    assert path.read_text(encoding="utf-8") == before


def test_ready_depends_on_blockers(tmp_path):
    a = create_task(tmp_path, "Blocker")
    b = create_task(tmp_path, "Dependent", blocked_by=[a.id])
    by_id = {t.id: t for t in load_tasks(tmp_path)}
    assert is_ready(by_id[b.id], by_id) is False  # blocker still open
    update_task(tmp_path, a.id, status="done")
    by_id = {t.id: t for t in load_tasks(tmp_path)}
    assert is_ready(by_id[b.id], by_id) is True  # blocker done -> ready
    assert is_ready(by_id[a.id], by_id) is False  # a done task is not "ready"


def test_sorted_open_high_first(tmp_path):
    create_task(tmp_path, "low open", priority="low")
    create_task(tmp_path, "high open", priority="high")
    done = create_task(tmp_path, "high done", priority="high")
    update_task(tmp_path, done.id, status="done")
    titles = [t.title for t in sorted_tasks(load_tasks(tmp_path))]
    assert titles[0] == "high open"
    assert titles[-1] == "high done"  # done last, regardless of priority


def test_update_blocked_by_entries_body(tmp_path):
    t = create_task(tmp_path, "Z")
    upd = update_task(tmp_path, t.id, blocked_by=["x"], entries=["entries/a.md"], body="new notes", tags=["blog"])
    assert upd.blocked_by == ["x"]
    assert upd.entries == ["entries/a.md"]
    assert upd.tags == ["blog"]
    reloaded = get_task(tmp_path, t.id)
    assert reloaded.body == "new notes"
    assert reloaded.entries == ["entries/a.md"]
    assert reloaded.tags == ["blog"]


def test_update_with_reflection_graduates_to_entry(tmp_path):
    from datetime import date

    from ai_journal_mcp.store import load_managed

    t = create_task(tmp_path, "Ship the staleness writeup", body="rough notes", tags=["blog"])
    done = update_task(
        tmp_path,
        t.id,
        status="done",
        reflection="What shipping it taught me.",
        themes=["writing"],
        when=date(2026, 6, 20),
    )
    # completing is an update; the reflection graduates it into a linked entry
    assert done.status == "done"
    assert any("ship-the-staleness-writeup" in e for e in done.entries)
    # a real, immutable journal entry now exists carrying the reflection + theme
    [entry] = load_managed(tmp_path)
    assert entry.title == "Ship the staleness writeup"
    assert "What shipping it taught me." in entry.body
    assert "writing" in entry.themes


def test_update_without_reflection_writes_no_entry(tmp_path):
    from ai_journal_mcp.store import load_managed

    t = create_task(tmp_path, "Fix CI flake")
    update_task(tmp_path, t.id, status="done")  # quiet close — trivial task, no entry
    assert load_managed(tmp_path) == []


@pytest.fixture
def managed(tmp_path, monkeypatch):
    root = tmp_path / "tech"
    monkeypatch.setattr(server, "load_config", lambda: [JournalSource("tech", root, "managed")])
    return root


def test_tools_add_update_list_get(managed):
    created = server.add_task("tech", "Cut release", priority="high", entries=["entries/2026-06/01-foo.md"])
    tid = created["id"]
    assert created["status"] == "open"
    assert any(t["id"] == tid and t["ready"] is True for t in server.list_tasks(status="open"))
    server.update_task("tech", tid, status="done")
    fetched = server.get_task("tech", tid)
    assert fetched["status"] == "done"
    assert fetched["entries"] == ["entries/2026-06/01-foo.md"]


def test_tools_reject_readonly_journal(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "load_config", lambda: [JournalSource("ro", tmp_path / "ro", "indexed")])
    with pytest.raises(ValueError, match="read-only"):
        server.add_task("ro", "nope")


def test_blog_topics_are_tagged_tasks(managed):
    # A blog topic = a task tagged "blog": title + the entry link, sortable and
    # checkable; list_tasks(tag="blog") is the backlog.
    server.add_task("tech", "Write up signature-based staleness", tags=["blog"], entries=["entries/2026-06/19-x.md"])
    server.add_task("tech", "Fix a CI flake", tags=["ops"])
    blog = server.list_tasks(tag="blog")
    assert [t["title"] for t in blog] == ["Write up signature-based staleness"]
    assert blog[0]["tags"] == ["blog"]
    assert blog[0]["entries"] == ["entries/2026-06/19-x.md"]


def test_tool_surfaces_task_error_as_valueerror(managed):
    # tasks.TaskError (bad priority) is surfaced to the caller as ValueError.
    with pytest.raises(ValueError, match="priority"):
        server.add_task("tech", "bad", priority="urgent")


def test_one_malformed_task_does_not_wedge_listing(tmp_path, caplog):
    create_task(tmp_path, "Good Task")
    (tmp_path / "tasks" / "broken.md").write_text("---\ntitle: unclosed\n", encoding="utf-8")
    with caplog.at_level("WARNING"):
        tasks = load_tasks(tmp_path)
    assert [t.title for t in tasks] == ["Good Task"]
    assert "broken.md" in caplog.text
    with pytest.raises(TaskError, match="broken.md"):
        get_task(tmp_path, "broken")


def test_rejected_update_writes_no_orphan_entry(tmp_path):
    # regression: the reflection entry was written before validation, so a
    # rejected update left an entry on disk outside views and index
    t = create_task(tmp_path, "Audit")
    with pytest.raises(TaskError, match="status"):
        update_task(tmp_path, t.id, status="bogus", reflection="orphan text")
    entries_dir = tmp_path / "entries"
    assert not entries_dir.exists() or list(entries_dir.rglob("*.md")) == []
    assert get_task(tmp_path, t.id).status == "open"  # untouched


def test_task_writes_leave_no_temp_files(tmp_path):
    t = create_task(tmp_path, "Tidy")
    update_task(tmp_path, t.id, status="done")
    leftovers = [p for p in (tmp_path / "tasks").iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


@pytest.mark.parametrize("edge_id", ["_inbox", "-lead", "v1.2-upgrade"])
def test_hand_made_task_ids_stay_reachable(tmp_path, edge_id):
    # regression: ids listed by load_tasks must be addressable by get_task —
    # the first-char rule locked out hand-made files like tasks/_inbox.md
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / f"{edge_id}.md").write_text("---\ntitle: Edge\nstatus: open\npriority: low\n---\n\nbody\n")
    assert [t.id for t in load_tasks(tmp_path)] == [edge_id]
    assert get_task(tmp_path, edge_id).title == "Edge"
    assert update_task(tmp_path, edge_id, status="done").status == "done"
