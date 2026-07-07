"""Load entries from a managed journal (entries/YYYY-MM/*.md with frontmatter)."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml

from .fsio import create_text_exclusive
from .model import Entry

log = logging.getLogger(__name__)


def _as_list(value: list[str] | str | None) -> list[str]:
    """Normalize a list, a comma-separated string, or None into a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return list(value)


def is_managed(root: Path) -> bool:
    return (root / "entries").is_dir()


def init_journal(root: Path, name: str | None = None, config_path: Path | None = None) -> tuple[Path, bool]:
    """Scaffold a new managed journal and register it in journals.toml.

    Creates ``root/entries/`` (the marker of a managed journal) and appends a
    ``[[journal]]`` stanza. Returns ``(resolved_root, registered)``, where
    ``registered`` is False if a journal of that name was already configured.
    Raises ``FileExistsError`` if ``root`` is already a managed journal — never
    clobbers an existing one.
    """
    from .config import add_journal

    root = root.expanduser().resolve()
    if is_managed(root):
        raise FileExistsError(f"{root} is already a managed journal (has entries/)")
    (root / "entries").mkdir(parents=True, exist_ok=True)
    registered = add_journal(name or root.name, root, "managed", config_path)
    return root, registered


def load_source(source, skipped: list[str] | None = None) -> list[Entry]:
    """Load entries for a configured JournalSource (managed dir, plain dir, or file)."""
    from .intake import scan_journal
    from .parser import parse_file_with_fallback

    path = source.path
    if path.is_file():
        return parse_file_with_fallback(path)
    if source.mode == "managed" and is_managed(path):
        return load_managed(path, skipped=skipped)
    return scan_journal(path).all_entries


def write_entry(
    root: Path,
    entry_date: date,
    title: str,
    body: str,
    themes: list[str] | str | None = None,
    tags: list[str] | str | None = None,
    blog_angles: list[str] | str | None = None,
) -> Path:
    """Write a new canonical entry into a managed journal; returns the path."""
    from .model import slugify

    month_dir = root / "entries" / entry_date.strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "date": entry_date.isoformat(),
        "title": title,
        "themes": _as_list(themes),
        "tags": _as_list(tags),
    }
    blog = _as_list(blog_angles)
    if blog:
        meta["blog_angles"] = blog
    frontmatter = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n"
    text = frontmatter + "\n" + body.strip("\n") + "\n"
    # exclusive create: two sessions writing the same date+title must land in
    # two files, not silently overwrite each other
    base = f"{entry_date.strftime('%d')}-{slugify(title)}"
    path = month_dir / f"{base}.md"
    suffix = 2
    while not create_text_exclusive(path, text):
        path = month_dir / f"{base}-{suffix}.md"
        suffix += 1
    return path


def load_managed(root: Path, skipped: list[str] | None = None) -> list[Entry]:
    """Load a managed journal's entries. One malformed file (unclosed
    frontmatter, bad YAML, junk date) must not wedge the whole journal: it is
    skipped, and the reason is appended to ``skipped`` (if given) so callers
    can put the warning in front of the user — a stderr log alone reads as
    silent deletion from an MCP client."""

    def _skip(path: Path, reason: str) -> None:
        log.warning("skipping entry file %s: %s", path, reason)
        if skipped is not None:
            skipped.append(f"{path} ({reason})")

    entries: list[Entry] = []
    for path in sorted((root / "entries").rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta: dict = {}
        body = text
        if text.startswith("---\n"):
            try:
                _, fm, body = text.split("---\n", 2)
                meta = yaml.safe_load(fm) or {}
            except (ValueError, yaml.YAMLError) as exc:
                _skip(path, f"malformed frontmatter: {exc}")
                continue
            if not isinstance(meta, dict):
                _skip(path, "frontmatter is not a mapping")
                continue
        entry_date = meta.get("date")
        if entry_date is None:
            continue  # not an entry file
        if not isinstance(entry_date, date):
            try:
                entry_date = date.fromisoformat(str(entry_date))
            except ValueError:
                _skip(path, f"bad date {entry_date!r}")
                continue
        entries.append(
            Entry(
                date=entry_date,
                title=meta.get("title"),
                body=body.strip("\n"),
                source_file=path,
                source_line=1,
                header_level=0,
                themes=list(meta.get("themes") or []),
                tags=list(meta.get("tags") or []),
                blog_angles=list(meta.get("blog_angles") or []),
            )
        )
    return entries
