"""Load entries from a managed journal (entries/YYYY-MM/*.md with frontmatter)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from .model import Entry


def _as_list(value: list[str] | str | None) -> list[str]:
    """Normalize a list, a comma-separated string, or None into a list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return list(value)


def is_managed(root: Path) -> bool:
    return (root / "entries").is_dir()


def load_source(source) -> list[Entry]:
    """Load entries for a configured JournalSource (managed dir, plain dir, or file)."""
    from .intake import scan_journal
    from .parser import parse_file_with_fallback

    path = source.path
    if path.is_file():
        return parse_file_with_fallback(path)
    if source.mode == "managed" and is_managed(path):
        return load_managed(path)
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
    base = f"{entry_date.strftime('%d')}-{slugify(title)}"
    path = month_dir / f"{base}.md"
    suffix = 2
    while path.exists():
        path = month_dir / f"{base}-{suffix}.md"
        suffix += 1
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
    path.write_text(frontmatter + "\n" + body.strip("\n") + "\n", encoding="utf-8")
    return path


def load_managed(root: Path) -> list[Entry]:
    entries: list[Entry] = []
    for path in sorted((root / "entries").rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        meta: dict = {}
        body = text
        if text.startswith("---\n"):
            _, fm, body = text.split("---\n", 2)
            meta = yaml.safe_load(fm) or {}
        entry_date = meta.get("date")
        if entry_date is None:
            continue  # not an entry file
        if not isinstance(entry_date, date):
            entry_date = date.fromisoformat(str(entry_date))
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
