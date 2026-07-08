"""Apply a migration: messy journal -> managed layout.

Nothing is deleted. Original files move to ``attic/`` preserving their
relative paths; canonical entries are written to ``entries/YYYY-MM/``;
a migration report records every dedup decision.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import yaml

from .fsio import journal_lock, write_text_atomic
from .intake import SKIP_DIRS, IntakeReport
from .model import Entry


@dataclass
class MigrationResult:
    written: list[Path] = field(default_factory=list)
    dropped_duplicates: list[tuple[Entry, Entry]] = field(default_factory=list)  # (kept, dropped)
    moved_to_attic: list[Path] = field(default_factory=list)
    unthemed_count: int = 0


def _dedup(entries: list[Entry]) -> tuple[list[Entry], list[tuple[Entry, Entry]]]:
    """Group duplicates, keep the longest body, merge themes.

    Titled entries group by loose identity (date + title-slug). Title-less
    entries (date-only session logs) have nothing but their text to tell them
    apart, so they group only on an exact body match — otherwise two different
    sessions logged on the same day would wrongly collapse into one.
    """
    groups: dict[tuple[str, str], list[Entry]] = defaultdict(list)
    for entry in entries:
        key = entry.identity if entry.title else (entry.date.isoformat(), entry.body_hash)
        groups[key].append(entry)

    kept: list[Entry] = []
    dropped: list[tuple[Entry, Entry]] = []
    for group in groups.values():
        winner = max(group, key=lambda e: len(e.body))
        themes = sorted({t for e in group for t in e.themes})
        winner.themes = themes
        kept.append(winner)
        dropped.extend((winner, loser) for loser in group if loser is not winner)
    return kept, dropped


def _frontmatter(entry: Entry, source: str) -> str:
    meta: dict[str, object] = {"date": entry.date.isoformat()}
    if entry.time:
        meta["time"] = entry.time
    meta.update({"title": entry.title, "themes": entry.themes, "source": source})
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n"


def _write_entries(
    entries: list[Entry], root: Path, source_for: Callable[[Entry], str]
) -> tuple[dict[int, Path], list[Path], int]:
    """Write canonical entry files under ``root/entries/``.

    Returns ``(entry-id -> path-relative-to-root, written paths, unthemed
    count)``. ``source_for`` supplies each entry's frontmatter ``source``
    string, so the same writer serves single-journal migration (relative path)
    and multi-source consolidation (``name::relpath:line`` provenance).
    """
    used: set[Path] = set()
    paths: dict[int, Path] = {}
    written: list[Path] = []
    unthemed = 0
    for entry in sorted(entries, key=lambda e: (e.date, e.source_line)):
        month_dir = root / "entries" / entry.date.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)
        base = f"{entry.date.strftime('%d')}-{entry.slug}"
        path = month_dir / f"{base}.md"
        suffix = 2
        while path in used:
            path = month_dir / f"{base}-{suffix}.md"
            suffix += 1
        used.add(path)
        path.write_text(_frontmatter(entry, source_for(entry)) + "\n" + entry.body + "\n", encoding="utf-8")
        written.append(path)
        paths[id(entry)] = path.relative_to(root)
        if not entry.themes:
            unthemed += 1
    return paths, written, unthemed


def _attic_originals(report: IntakeReport, root: Path, result: MigrationResult) -> None:
    attic = root / "attic"
    for scan in report.scans + report.orphans:
        src = scan.path
        if not src.exists():  # already moved with a parent directory
            continue
        rel = src.relative_to(root)
        dest = attic / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        result.moved_to_attic.append(rel)
    # relocate any remaining files (scripts, configs) so they stay next to the
    # docs they arrived with, then sweep the emptied directories bottom-up —
    # the journal root ends up purely managed
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in SKIP_DIRS:
            for leftover in sorted(p for p in child.rglob("*") if p.is_file()):
                rel = leftover.relative_to(root)
                dest = attic / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(leftover), str(dest))
                result.moved_to_attic.append(rel)
            subdirs = sorted(
                (p for p in child.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            )
            for d in subdirs:
                d.rmdir()
            child.rmdir()
    # spec-driven intake may have emptied original month dirs under entries/
    # (a foreign journal that already used that name); sweep those too so the
    # managed store starts clean
    store = root / "entries"
    if store.is_dir():
        for d in sorted((p for p in store.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()


def _generate_views(entries: list[Entry], root: Path, paths: dict[int, Path]) -> set[str]:
    today = max(e.date for e in entries)
    recent_cutoff = today - timedelta(days=7)
    by_month: dict[str, int] = defaultdict(int)
    for entry in entries:
        by_month[entry.date.strftime("%Y-%m")] += 1

    lines = [
        "# Development Journal",
        "",
        "Managed by ai-journal-mcp. New entries go in `entries/YYYY-MM/`; this index is generated.",
        "",
        "## Recent Entries (last 7 days)",
        "",
    ]
    recent = sorted((e for e in entries if e.date >= recent_cutoff), key=lambda e: e.date, reverse=True)
    for entry in recent:
        lines.append(f"- {entry.date} — [{entry.title or '(untitled)'}]({paths[id(entry)]})")
    lines += ["", "## Archive", ""]
    for month in sorted(by_month, reverse=True):
        lines.append(f"- [{month}](entries/{month}/) — {by_month[month]} entries")
    write_text_atomic(root / "JOURNAL.md", "\n".join(lines) + "\n")

    themes_dir = root / "themes"
    themes_dir.mkdir(exist_ok=True)
    by_theme: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        for theme in entry.themes:
            by_theme[theme].append(entry)
    written: set[str] = set()
    for theme, theme_entries in by_theme.items():
        tlines = [f"# Theme: {theme}", "", "Generated view — do not edit by hand.", ""]
        for entry in sorted(theme_entries, key=lambda e: e.date, reverse=True):
            tlines.append(f"- {entry.date} — [{entry.title or '(untitled)'}](../{paths[id(entry)]})")
        write_text_atomic(themes_dir / f"{theme}.md", "\n".join(tlines) + "\n")
        written.add(f"{theme}.md")
    return written


def _write_report(result: MigrationResult, root: Path, spec_text: str | None = None) -> None:
    lines = [
        "# Migration report",
        "",
        f"- Entries written: {len(result.written)}",
        f"- Duplicates dropped (kept longest body, merged themes): {len(result.dropped_duplicates)}",
        f"- Entries without a theme (lived only in JOURNAL.md/archives): {result.unthemed_count}",
        f"- Original files moved to attic/: {len(result.moved_to_attic)}",
        "",
        "## Dedup decisions",
        "",
        "| Date | Title | Kept (longest) | Dropped |",
        "|---|---|---|---|",
    ]
    for kept, dropped in result.dropped_duplicates:
        lines.append(
            f"| {kept.date} | {kept.title or '(untitled)'} "
            f"| {kept.source_file.relative_to(root)}:{kept.source_line} "
            f"| {dropped.source_file.relative_to(root)}:{dropped.source_line} |"
        )
    if spec_text is not None:
        # the spec is throwaway, so the report is its one durable record —
        # everything needed to audit (or redo) the extraction
        lines += ["", "## Extraction spec used", "", "```toml", spec_text.rstrip("\n"), "```"]
    (root / "migration-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rescue_strays(root: Path) -> int:
    """Save hand-added JOURNAL.md entries into the store before regeneration.

    JOURNAL.md is a generated view, but an agent following stale instructions
    may append a dated entry to it directly. Regenerating would silently
    destroy that text, so any dated entry found there that isn't already in
    the managed store is written out as a canonical entry first. Identity is
    date+title *and* body: a stray sharing a stored entry's date and title but
    saying something new is still new text and must be rescued, not dropped
    (write_entry suffixes the filename on collision).
    """
    from .parser import parse_file
    from .store import load_managed, write_entry

    journal_md = root / "JOURNAL.md"
    if not journal_md.exists():
        return 0
    strays = [e for e in parse_file(journal_md) if e.body.strip()]
    if not strays:
        return 0
    existing_bodies: dict[tuple[str, str], set[str]] = {}
    for e in load_managed(root):
        existing_bodies.setdefault(e.identity, set()).add(e.body_hash)
    rescued = 0
    for stray in strays:
        if stray.body_hash in existing_bodies.get(stray.identity, set()):
            continue  # already stored verbatim
        write_entry(root, stray.date, stray.title or "Untitled", stray.body)
        rescued += 1
    return rescued


def refresh_views(root: Path, skipped: list[str] | None = None) -> tuple[int, int]:
    """Regenerate JOURNAL.md and themes/ from the managed store.

    Returns (entry_count, rescued_count). Malformed entry files are skipped
    (reasons appended to ``skipped``) — their files stay untouched on disk,
    but the regenerated views won't reference them until they're fixed."""
    from .store import load_managed

    with journal_lock(root):  # rescue-then-regenerate must not interleave across sessions
        rescued = _rescue_strays(root)
        entries = load_managed(root, skipped=skipped)
        if not entries:
            return 0, rescued
        paths = {id(e): e.source_file.relative_to(root) for e in entries}
        # write the fresh views first (atomic overwrite), then remove only the
        # stale ones — a lock-free reader never sees an empty themes/ window
        written = _generate_views(entries, root, paths)
        themes_dir = root / "themes"
        if themes_dir.is_dir():
            for old in themes_dir.glob("*.md"):
                if old.name not in written:
                    old.unlink(missing_ok=True)
    return len(entries), rescued


def apply_migration(report: IntakeReport) -> MigrationResult:
    root = report.root
    if not report.all_entries:
        # applying would move every file to attic and write nothing back —
        # a scan that found no entries means the format wasn't understood
        raise ValueError("scan found no entries — refusing to migrate (fix the extraction spec and re-run the scan)")
    result = MigrationResult()
    entries, dropped = _dedup(report.all_entries)
    result.dropped_duplicates = dropped
    # attic first: with spec-driven intake a canonical filename can equal an
    # original's (e.g. a foreign entries/2026-01/23-note.md); writing first
    # would overwrite the original before it was preserved
    _attic_originals(report, root, result)
    paths, result.written, result.unthemed_count = _write_entries(
        entries, root, lambda e: f"{e.source_file.relative_to(root)}:{e.source_line}"
    )
    _generate_views(entries, root, paths)
    _write_report(result, root, spec_text=report.spec.text if report.spec else None)
    return result
