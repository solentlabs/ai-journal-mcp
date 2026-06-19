import pytest

from ai_journal import server
from ai_journal.config import JournalSource
from ai_journal.tasks import (
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
