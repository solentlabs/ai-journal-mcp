"""Tasks: a mutable kind alongside append-only journal entries.

Journal entries record what happened and never change. Tasks track what to do
next — their status, priority, and dependencies change over time — and link
back to the entries that give them context, so picking a task up later surfaces
the thinking behind it.

Stored as one markdown file per task under ``<journal>/tasks/``, rewritten in
place on update. Markdown stays the source of truth; tasks are simply the
mutable kind, kept separate from the append-only ``entries/`` so neither breaks
the other's rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from .model import slugify

STATUSES = ("open", "blocked", "done")
PRIORITIES = ("high", "medium", "low")
_PRIORITY_RANK = {p: i for i, p in enumerate(PRIORITIES)}


class TaskError(ValueError):
    """Invalid task field (unknown status/priority) or missing task."""


@dataclass
class Task:
    id: str
    title: str
    status: str
    priority: str
    blocked_by: list[str] = field(default_factory=list)
    entries: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    body: str = ""
    created: str = ""  # ISO date
    updated: str = ""  # ISO date
    path: Path | None = None


def _tasks_dir(root: Path) -> Path:
    return root / "tasks"


def _validate(status: str, priority: str) -> None:
    if status not in STATUSES:
        raise TaskError(f"status must be one of {STATUSES}, got {status!r}")
    if priority not in PRIORITIES:
        raise TaskError(f"priority must be one of {PRIORITIES}, got {priority!r}")


def _write(task: Task) -> None:
    meta = {
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "blocked_by": task.blocked_by,
        "entries": task.entries,
        "tags": task.tags,
        "created": task.created,
        "updated": task.updated,
    }
    frontmatter = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n"
    assert task.path is not None
    task.path.write_text(frontmatter + "\n" + task.body.strip("\n") + "\n", encoding="utf-8")


def create_task(
    root: Path,
    title: str,
    body: str = "",
    priority: str = "medium",
    blocked_by: list[str] | None = None,
    entries: list[str] | None = None,
    tags: list[str] | None = None,
) -> Task:
    """Create a new task (status ``open``) under ``<root>/tasks/``."""
    _validate("open", priority)
    tasks_dir = _tasks_dir(root)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    base = slugify(title)
    task_id, suffix = base, 2
    while (tasks_dir / f"{task_id}.md").exists():
        task_id = f"{base}-{suffix}"
        suffix += 1
    today = date.today().isoformat()
    task = Task(
        id=task_id,
        title=title,
        status="open",
        priority=priority,
        blocked_by=list(blocked_by or []),
        entries=list(entries or []),
        tags=list(tags or []),
        body=body,
        created=today,
        updated=today,
        path=tasks_dir / f"{task_id}.md",
    )
    _write(task)
    return task


def _load_one(path: Path) -> Task:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict = {}
    body = text
    if text.startswith("---\n"):
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm) or {}
    return Task(
        id=path.stem,
        title=meta.get("title") or path.stem,
        status=meta.get("status") or "open",
        priority=meta.get("priority") or "medium",
        blocked_by=list(meta.get("blocked_by") or []),
        entries=list(meta.get("entries") or []),
        tags=list(meta.get("tags") or []),
        body=body.strip("\n"),
        created=str(meta.get("created") or ""),
        updated=str(meta.get("updated") or ""),
        path=path,
    )


def load_tasks(root: Path) -> list[Task]:
    tasks_dir = _tasks_dir(root)
    if not tasks_dir.is_dir():
        return []
    return [_load_one(p) for p in sorted(tasks_dir.glob("*.md"))]


def get_task(root: Path, task_id: str) -> Task:
    path = _tasks_dir(root) / f"{task_id}.md"
    if not path.exists():
        raise TaskError(f"no task {task_id!r} in {root}")
    return _load_one(path)


def update_task(
    root: Path,
    task_id: str,
    status: str | None = None,
    priority: str | None = None,
    blocked_by: list[str] | None = None,
    entries: list[str] | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
) -> Task:
    """Mutate a task in place; only the fields passed are changed."""
    task = get_task(root, task_id)
    if status is not None:
        task.status = status
    if priority is not None:
        task.priority = priority
    if blocked_by is not None:
        task.blocked_by = list(blocked_by)
    if entries is not None:
        task.entries = list(entries)
    if body is not None:
        task.body = body
    if tags is not None:
        task.tags = list(tags)
    _validate(task.status, task.priority)
    task.updated = date.today().isoformat()
    _write(task)
    return task


def is_ready(task: Task, by_id: dict[str, Task]) -> bool:
    """A task is ready to pick up when it isn't done and every blocker is done.

    Unknown blocker ids count as not-done (conservative — don't mark ready)."""
    if task.status == "done":
        return False
    for blocker_id in task.blocked_by:
        blocker = by_id.get(blocker_id)
        if blocker is None or blocker.status != "done":
            return False
    return True


def sorted_tasks(tasks: list[Task]) -> list[Task]:
    """Open/blocked before done; then by priority (high first); then title."""
    return sorted(
        tasks,
        key=lambda t: (t.status == "done", _PRIORITY_RANK.get(t.priority, len(PRIORITIES)), t.title.lower()),
    )
