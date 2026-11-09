"""Load entries from a managed journal (entries/YYYY-MM/*.md with frontmatter)."""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, date
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


class EntryError(ValueError):
    """An entry edit that cannot be applied (bad path, malformed file, empty title)."""


def _resolve_entry(root: Path, path: str | Path) -> Path:
    """Resolve ``path`` (absolute, or relative to the journal root) to an
    existing ``.md`` file under ``<root>/entries/``."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to((root / "entries").resolve()) or resolved.suffix != ".md":
        raise EntryError(f"{path} is not an entry file under {root / 'entries'}")
    if not resolved.is_file():
        raise EntryError(f"no entry at {path}")
    return resolved


def _relink_tasks(root: Path, old: Path, new: Path) -> None:
    """Point task ``entries:`` links at an entry's new path (caller holds the lock)."""
    from . import tasks

    old_rel, new_rel = str(old.relative_to(root)), str(new.relative_to(root))
    for task in tasks.load_tasks(root):
        if any(link in (old_rel, str(old)) for link in task.entries):
            task.entries = [new_rel if link in (old_rel, str(old)) else link for link in task.entries]
            tasks._write(task)


EDIT_SNAPSHOT_DAYS = 90


def _snapshot_before_edit(root: Path, target: Path, text: str) -> None:
    """Save the pre-edit text under ``attic/edits/`` (keeps the entry's relative
    path as a directory, one timestamped file per edit) and prune snapshots older
    than ``EDIT_SNAPSHOT_DAYS``. Runs before any write, so a failure here aborts
    the edit rather than losing the original."""
    from datetime import datetime

    edits = root / "attic" / "edits"
    folder = edits / target.relative_to(root / "entries").with_suffix("")
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    (folder / f"{stamp}.md").write_text(text, encoding="utf-8")
    cutoff = time.time() - EDIT_SNAPSHOT_DAYS * 86400
    for old in edits.rglob("*.md"):
        if old.stat().st_mtime < cutoff:
            old.unlink()
            for parent in old.parents:  # drop emptied per-entry directories
                if parent == edits or any(parent.iterdir()):
                    break
                parent.rmdir()


def _split_frontmatter(text: str, path: str | Path) -> tuple[dict, str]:
    try:
        if not text.startswith("---\n"):
            raise ValueError("no frontmatter")
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm)
        if not isinstance(meta, dict):
            raise ValueError("frontmatter is not a mapping")
    except (ValueError, yaml.YAMLError) as exc:
        raise EntryError(f"{path} has malformed frontmatter: {exc}") from exc
    return meta, body


def _apply_fields(meta: dict, title, themes, tags, blog_angles) -> None:
    if title is not None:
        meta["title"] = title
    if themes is not None:
        meta["themes"] = _as_list(themes)
    if tags is not None:
        meta["tags"] = _as_list(tags)
    if blog_angles is not None:
        blog = _as_list(blog_angles)
        if blog:
            meta["blog_angles"] = blog
        else:
            meta.pop("blog_angles", None)


def update_entry(
    root: Path,
    path: str | Path,
    title: str | None = None,
    body: str | None = None,
    themes: list[str] | str | None = None,
    tags: list[str] | str | None = None,
    blog_angles: list[str] | str | None = None,
) -> Path:
    """Edit an existing entry in place — only the fields passed change.

    ``themes``/``tags``/``blog_angles`` *replace* the stored list (pass ``[]``
    to clear). Other frontmatter (date, time, source) is preserved. The
    pre-edit text is first saved under ``attic/edits/`` (snapshots older than
    ``EDIT_SNAPSHOT_DAYS`` are pruned on each edit). A changed
    ``title`` renames the file to match its new slug (same day prefix, collision
    suffix if needed), the old file is removed, and task links to it are
    rewritten. Returns the entry's current path, which differs from the input
    path after a rename."""
    from .fsio import journal_lock, write_text_atomic
    from .model import slugify

    if title is not None and not title.strip():
        raise EntryError("title must not be empty or whitespace-only")
    root = root.resolve()
    with journal_lock(root):
        target = _resolve_entry(root, path)
        text = target.read_text(encoding="utf-8", errors="replace")
        meta, old_body = _split_frontmatter(text, path)
        _apply_fields(meta, title, themes, tags, blog_angles)
        new_body = old_body.strip("\n") if body is None else body.strip("\n")
        new_text = "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + new_body + "\n"

        if new_text == text:
            return target  # nothing would change — no snapshot, no rewrite
        _snapshot_before_edit(root, target, text)
        if title is None or title == _stored_title(text):
            write_text_atomic(target, new_text)
            return target

        base = f"{target.name[:2]}-{slugify(title)}"
        if re.fullmatch(rf"{re.escape(base)}(-\d+)?\.md", target.name):
            write_text_atomic(target, new_text)  # slug unchanged — keep the name
            return target
        new_path = target.with_name(f"{base}.md")
        suffix = 2
        while not create_text_exclusive(new_path, new_text):
            new_path = target.with_name(f"{base}-{suffix}.md")
            suffix += 1
        target.unlink()
        _relink_tasks(root, target, new_path)
        return new_path


def _stored_title(text: str) -> str | None:
    try:
        meta = yaml.safe_load(text.split("---\n", 2)[1]) or {}
    except (IndexError, yaml.YAMLError):
        return None
    return meta.get("title") if isinstance(meta, dict) else None


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
