"""MCP stdio server exposing the journal tool surface.

Markdown is the source of truth; the SQLite index is rebuilt on demand.
Journals come from ~/.config/ai-journal-mcp/journals.toml.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import indexer, tasks
from .config import DEFAULT_DB, load_config
from .discover import discover, format_discovery
from .intake import format_report, scan_journal
from .migrate import refresh_views
from .model import Entry
from .spec import SpecError, parse_spec
from .store import load_source, write_entry

mcp = FastMCP("ai-journal-mcp")


def _sources():
    return {src.name: src for src in load_config()}


def _managed_root(journal: str) -> Path:
    """Resolve a configured managed journal's path, or raise a clear error."""
    src = _sources().get(journal)
    if src is None:
        raise ValueError(f"Unknown journal '{journal}'. Configured: {list(_sources())}")
    if src.mode != "managed":
        raise ValueError(f"Journal '{journal}' is read-only (mode={src.mode})")
    return src.path


def _signatures_for(sources: dict) -> dict[str, str]:
    """Live content signature per source (add/edit/delete-sensitive)."""
    return {src.name: indexer.source_signature(src.path, src.mode) for src in sources.values()}


def _current_signatures() -> dict[str, str]:
    return _signatures_for(_sources())


def _ensure_index() -> Path:
    # Rebuild when the index is missing, or when any source's signature differs
    # from what it was built with — which also covers a source added to or
    # removed from the config.
    if not DEFAULT_DB.exists() or indexer.read_signatures(DEFAULT_DB) != _current_signatures():
        _reindex()
    return DEFAULT_DB


def _reindex(skipped: list[str] | None = None) -> int:
    sources = _sources()
    # signatures are taken BEFORE loading: a write racing the build then reads
    # as stale on the next call instead of being missed forever
    signatures = _signatures_for(sources)
    pairs: list[tuple[str, Entry]] = []
    task_pairs: list[tuple[str, tasks.Task]] = []
    for src in sources.values():
        pairs.extend((src.name, entry) for entry in load_source(src, skipped=skipped))
        if src.mode == "managed":
            task_pairs.extend((src.name, t) for t in tasks.load_tasks(src.path, skipped=skipped))
    return indexer.build_index(DEFAULT_DB, pairs, task_pairs, signatures=signatures)


def _warning(skipped: list[str]) -> str:
    return "WARNING: skipped malformed files (fix or remove them): " + "; ".join(skipped)


@mcp.tool()
def search_journal(
    query: str,
    journal: str | None = None,
    theme: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """Full-text search across all configured journals.

    query uses SQLite FTS5 syntax (words, "exact phrases", AND/OR/NOT).
    journal/theme filter to one journal or theme; since/until are
    YYYY-MM-DD inclusive bounds. Results are ranked, with snippets and a
    source path usable with get_entry. Spans both journal entries and tasks —
    each result carries `kind` ('entry' or 'task'); a task's tags and status are
    searchable too (so "blog" surfaces a task tagged blog).
    """
    return indexer.search(_ensure_index(), query, limit=limit, journal=journal, theme=theme, since=since, until=until)


@mcp.tool()
def get_entry(source: str) -> str:
    """Read the full text of an entry, given the source path from a search result."""
    path = Path(source).expanduser()
    roots = [src.path if src.path.is_dir() else src.path.parent for src in _sources().values()]
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise ValueError(f"{source} is not inside a configured journal")
    return path.read_text(encoding="utf-8", errors="replace")


@mcp.tool()
def add_entry(
    journal: str,
    title: str,
    body: str,
    themes: list[str] | str | None = None,
    tags: list[str] | str | None = None,
    blog_angles: list[str] | str | None = None,
    entry_date: str | None = None,
) -> str:
    """Write a new entry to a managed journal and refresh its index/views.

    journal must be a configured source with mode='managed'. entry_date
    defaults to today (YYYY-MM-DD). Returns the path of the new entry file
    (plus a WARNING line if malformed files had to be skipped).
    """
    root = _managed_root(journal)
    when = date.fromisoformat(entry_date) if entry_date else date.today()
    path = write_entry(root, when, title, body, themes=themes, tags=tags, blog_angles=blog_angles)
    skipped: list[str] = []
    refresh_views(root, skipped=skipped)
    _reindex()
    if skipped:
        return f"{path}\n{_warning(skipped)}"
    return str(path)


@mcp.tool()
def list_themes() -> list[dict]:
    """Theme and journal entry counts across the whole index."""
    return indexer.list_themes(_ensure_index())


@mcp.tool()
def suggest_themes(text: str, limit: int = 5) -> list[str]:
    """Suggest existing themes for a new entry, ranked by full-text similarity
    to past entries. Use before add_entry when no themes were given: propose
    these to the user, then pass the chosen ones to add_entry. Suggests only
    existing themes and writes nothing."""
    return indexer.suggest_themes(_ensure_index(), text, limit=limit)


@mcp.tool()
def entries_over_time(theme: str | None = None, journal: str | None = None, tag: str | None = None) -> list[dict]:
    """Entries per month, optionally filtered by theme, tag, or journal — activity
    over time. Filtering by a recurring label answers "how often does this
    keep happening?" — the frequency evidence behind a pattern."""
    return indexer.entries_over_time(_ensure_index(), theme=theme, journal=journal, tag=tag)


@mcp.tool()
def add_task(
    journal: str,
    title: str,
    body: str = "",
    priority: str = "medium",
    blocked_by: list[str] | None = None,
    entries: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a task in a managed journal. Status starts 'open'; priority is
    high|medium|low; blocked_by lists task ids it waits on; entries are journal
    entry paths giving it context; tags are free-form labels for grouping and
    filtering (a topic backlog, a project, a context — "blog" is just one).
    Tasks are mutable — unlike entries."""
    try:
        task = tasks.create_task(
            _managed_root(journal),
            title,
            body=body,
            priority=priority,
            blocked_by=blocked_by,
            entries=entries,
            tags=tags,
        )
    except tasks.TaskError as exc:
        raise ValueError(str(exc)) from exc
    return {"id": task.id, "status": task.status, "priority": task.priority}


@mcp.tool()
def update_task(
    journal: str,
    task_id: str,
    status: str | None = None,
    priority: str | None = None,
    blocked_by: list[str] | None = None,
    entries: list[str] | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    reflection: str | None = None,
    themes: list[str] | str | None = None,
    entry_date: str | None = None,
) -> dict:
    """Change a task in place — only the fields you pass. status: open|blocked|
    done; priority: high|medium|low; tags are free-form grouping labels. Pass
    `reflection` to graduate the task into a journal entry as you complete it
    (title from the task, body = reflection, optional `themes`) — the
    planned-future to completed-past bridge; the entry is written, linked, and
    indexed. Omit it to just update fields."""
    root = _managed_root(journal)
    when = date.fromisoformat(entry_date) if entry_date else None
    try:
        task = tasks.update_task(
            root,
            task_id,
            status=status,
            priority=priority,
            blocked_by=blocked_by,
            entries=entries,
            body=body,
            tags=tags,
            reflection=reflection,
            themes=themes,
            when=when,
        )
    except tasks.TaskError as exc:
        raise ValueError(str(exc)) from exc
    result: dict[str, object] = {"id": task.id, "status": task.status, "priority": task.priority, "tags": task.tags}
    if reflection is not None:
        skipped: list[str] = []
        refresh_views(root, skipped=skipped)
        _reindex()
        result["entry"] = task.entries[-1] if task.entries else None
        if skipped:
            result["warning"] = _warning(skipped)
    return result


@mcp.tool()
def list_tasks(
    journal: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """Tasks across managed journals, open/high-priority first. Filter by
    journal/status/priority/tag. `tag` is any free-form label — e.g. a topic
    backlog ("blog"), a project, a context. Each task carries `ready` (every
    blocker done), `tags`, and `entries` (paths to pull context with get_entry)."""
    out: list[dict] = []
    skipped: list[str] = []
    for src in _sources().values():
        if src.mode != "managed" or (journal and src.name != journal):
            continue
        loaded = tasks.load_tasks(src.path, skipped=skipped)
        by_id = {t.id: t for t in loaded}
        for task in tasks.sorted_tasks(loaded):
            if (status and task.status != status) or (priority and task.priority != priority):
                continue
            if tag and tag not in task.tags:
                continue
            out.append(
                {
                    "journal": src.name,
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "priority": task.priority,
                    "tags": task.tags,
                    "blocked_by": task.blocked_by,
                    "entries": task.entries,
                    "ready": tasks.is_ready(task, by_id),
                }
            )
    if skipped:
        # a broken task file must not read as a deleted task — say so in-band
        out.append({"warning": _warning(skipped)})
    return out


@mcp.tool()
def get_task(journal: str, task_id: str) -> dict:
    """Full task detail, including `entries` — read those with get_entry to pull
    the context behind the task."""
    try:
        task = tasks.get_task(_managed_root(journal), task_id)
    except tasks.TaskError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "tags": task.tags,
        "blocked_by": task.blocked_by,
        "entries": task.entries,
        "body": task.body,
    }


def _source_dir(path: str) -> Path:
    root = Path(path).expanduser()
    if not root.is_dir():
        raise ValueError(f"{path} is not a directory")
    return root


@mcp.tool()
def discover_journal(path: str) -> str:
    """Evidence report about an unfamiliar journal directory (read-only): file
    name patterns, heading shapes, frontmatter keys, and excerpts — no parsing
    decisions. Use it when intake of an existing journal finds 0 entries or an
    unknown layout: read the evidence, propose an extraction spec (TOML schema
    is in the report's Next steps), validate with scan_source, and iterate
    until the dry-run accounts for every file. Applying the migration is
    CLI-only, run by the user: `ai-journal-mcp migrate ROOT --spec SPEC --apply`."""
    return format_discovery(discover(_source_dir(path)))


@mcp.tool()
def scan_source(path: str, spec_toml: str | None = None) -> str:
    """Dry-run intake report for a journal directory (read-only): entries per
    file, date ranges, duplicates, and files with no dated entries (with
    excerpts, for triage). Pass spec_toml — an extraction spec from the
    discover_journal loop — to parse foreign formats instead of the default
    headers. Nothing is written; use it to prove a spec extracts everything
    before the user applies the migration."""
    spec = None
    if spec_toml:
        try:
            spec = parse_spec(spec_toml)
        except SpecError as exc:
            raise ValueError(f"bad extraction spec: {exc}") from exc
    return format_report(scan_journal(_source_dir(path), spec=spec))


@mcp.tool()
def reindex() -> str:
    """Rebuild the search index from the markdown sources."""
    skipped: list[str] = []
    count = _reindex(skipped=skipped)
    message = f"Indexed {count} entries from {len(_sources())} journals"
    if skipped:
        message += f"\n{_warning(skipped)}"
    return message


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
