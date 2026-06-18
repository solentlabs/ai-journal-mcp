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
    meta = {
        "date": entry.date.isoformat(),
        "title": entry.title,
        "themes": entry.themes,
        "source": source,
    }
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


def _generate_views(entries: list[Entry], root: Path, paths: dict[int, Path]) -> None:
    today = max(e.date for e in entries)
    recent_cutoff = today - timedelta(days=7)
    by_month: dict[str, int] = defaultdict(int)
    for entry in entries:
        by_month[entry.date.strftime("%Y-%m")] += 1

    lines = [
        "# Development Journal",
        "",
        "Managed by ai-journal. New entries go in `entries/YYYY-MM/`; this index is generated.",
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
    (root / "JOURNAL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    themes_dir = root / "themes"
    themes_dir.mkdir(exist_ok=True)
    by_theme: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        for theme in entry.themes:
            by_theme[theme].append(entry)
    for theme, theme_entries in by_theme.items():
        tlines = [f"# Theme: {theme}", "", "Generated view — do not edit by hand.", ""]
        for entry in sorted(theme_entries, key=lambda e: e.date, reverse=True):
            tlines.append(f"- {entry.date} — [{entry.title or '(untitled)'}](../{paths[id(entry)]})")
        (themes_dir / f"{theme}.md").write_text("\n".join(tlines) + "\n", encoding="utf-8")


def _write_report(result: MigrationResult, root: Path) -> None:
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
    (root / "migration-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _rescue_strays(root: Path) -> int:
    """Save hand-added JOURNAL.md entries into the store before regeneration.

    JOURNAL.md is a generated view, but an agent following stale instructions
    may append a dated entry to it directly. Regenerating would silently
    destroy that text, so any dated entry found there that isn't already in
    the managed store is written out as a canonical entry first.
    """
    from .model import slugify
    from .parser import parse_file
    from .store import load_managed, write_entry

    journal_md = root / "JOURNAL.md"
    if not journal_md.exists():
        return 0
    strays = [e for e in parse_file(journal_md) if e.body.strip()]
    if not strays:
        return 0
    existing = {e.identity for e in load_managed(root)}
    rescued = 0
    for stray in strays:
        if (stray.date.isoformat(), slugify(stray.title or "")[:40]) not in existing:
            write_entry(root, stray.date, stray.title or "Untitled", stray.body)
            rescued += 1
    return rescued


def refresh_views(root: Path) -> tuple[int, int]:
    """Regenerate JOURNAL.md and themes/ from the managed store.

    Returns (entry_count, rescued_count)."""
    from .store import load_managed

    rescued = _rescue_strays(root)
    entries = load_managed(root)
    if not entries:
        return 0, rescued
    paths = {id(e): e.source_file.relative_to(root) for e in entries}
    for old in (root / "themes").glob("*.md") if (root / "themes").is_dir() else []:
        old.unlink()
    _generate_views(entries, root, paths)
    return len(entries), rescued


def apply_migration(report: IntakeReport) -> MigrationResult:
    root = report.root
    result = MigrationResult()
    entries, dropped = _dedup(report.all_entries)
    result.dropped_duplicates = dropped
    paths, result.written, result.unthemed_count = _write_entries(
        entries, root, lambda e: f"{e.source_file.relative_to(root)}:{e.source_line}"
    )
    _attic_originals(report, root, result)
    _generate_views(entries, root, paths)
    _write_report(result, root)
    return result
