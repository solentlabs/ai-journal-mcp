"""MCP stdio server exposing the journal tool surface.

Markdown is the source of truth; the SQLite index is rebuilt on demand.
Journals come from ~/.config/ai-journal/journals.toml.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import indexer
from .config import DEFAULT_DB, load_config
from .migrate import refresh_views
from .model import Entry
from .store import load_source, write_entry

mcp = FastMCP("ai-journal")


def _sources():
    return {src.name: src for src in load_config()}


def _sources_mtime() -> float:
    """Cheap freshness signal: managed journals touch JOURNAL.md on every
    write; file sources are stat'd directly. Directory-indexed sources are
    not deep-scanned — use the reindex tool after bulk-editing those."""
    newest = 0.0
    for src in _sources().values():
        probe = src.path if src.path.is_file() else src.path / "JOURNAL.md"
        if probe.exists():
            newest = max(newest, probe.stat().st_mtime)
    return newest


def _ensure_index() -> Path:
    if not DEFAULT_DB.exists() or _sources_mtime() > DEFAULT_DB.stat().st_mtime:
        _reindex()
    return DEFAULT_DB


def _reindex() -> int:
    pairs: list[tuple[str, Entry]] = []
    for src in _sources().values():
        pairs.extend((src.name, entry) for entry in load_source(src))
    return indexer.build_index(DEFAULT_DB, pairs)


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
    source path usable with get_entry.
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
    defaults to today (YYYY-MM-DD). Returns the path of the new entry file.
    """
    src = _sources().get(journal)
    if src is None:
        raise ValueError(f"Unknown journal '{journal}'. Configured: {list(_sources())}")
    if src.mode != "managed":
        raise ValueError(f"Journal '{journal}' is read-only (mode={src.mode})")
    when = date.fromisoformat(entry_date) if entry_date else date.today()
    path = write_entry(src.path, when, title, body, themes=themes, tags=tags, blog_angles=blog_angles)
    refresh_views(src.path)
    _reindex()
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
def entries_over_time(theme: str | None = None, journal: str | None = None) -> list[dict]:
    """Entries per month, optionally filtered by theme or journal — activity over time."""
    return indexer.entries_over_time(_ensure_index(), theme=theme, journal=journal)


@mcp.tool()
def reindex() -> str:
    """Rebuild the search index from the markdown sources."""
    count = _reindex()
    return f"Indexed {count} entries from {len(_sources())} journals"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
