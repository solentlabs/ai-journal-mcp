"""Consolidate one or more sources into a new managed journal.

Reads every entry across the named sources, removes duplicates across them,
writes the canonical managed layout to a fresh destination, then compresses
each source in place into a verified ``<source>.tar.gz`` and removes the
originals. Nothing is ever deleted until its archive is written and verified to
contain every original file — the no-data-loss guarantee, checked not assumed.

See docs/proposals/multi-source-consolidation.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .archive import ArchiveError, archive_and_remove
from .intake import scan_journal
from .migrate import _dedup, _generate_views, _write_entries
from .model import Entry
from .parser import parse_file_with_fallback


class ConsolidationError(RuntimeError):
    """Raised when consolidation cannot proceed safely (e.g. archive verify failed)."""


@dataclass
class SourceScan:
    name: str
    path: Path
    entries: list[Entry]


@dataclass
class ConsolidationReport:
    sources: list[SourceScan]
    origin: dict[int, tuple[str, Path]]  # id(entry) -> (source name, source root)

    @property
    def all_entries(self) -> list[Entry]:
        return [e for s in self.sources for e in s.entries]


@dataclass
class ConsolidationResult:
    written: list[Path] = field(default_factory=list)
    dropped_duplicates: list[tuple[Entry, Entry]] = field(default_factory=list)  # (kept, dropped)
    archives: list[Path] = field(default_factory=list)
    sources_removed: list[Path] = field(default_factory=list)


def scan_sources(specs: list[tuple[str, Path]]) -> ConsolidationReport:
    """Read entries from each named source (directory or single file).

    Read-only: parses, tags each entry with its source, writes nothing.
    """
    sources: list[SourceScan] = []
    origin: dict[int, tuple[str, Path]] = {}
    for name, path in specs:
        if path.is_dir():
            entries = scan_journal(path).all_entries
            root = path
        elif path.is_file():
            entries = parse_file_with_fallback(path)
            root = path.parent
        else:
            raise ConsolidationError(f"source not found: {path}")
        for entry in entries:
            origin[id(entry)] = (name, root)
        sources.append(SourceScan(name=name, path=path, entries=entries))
    return ConsolidationReport(sources=sources, origin=origin)


def _provenance(entry: Entry, origin: dict[int, tuple[str, Path]]) -> str:
    """Frontmatter ``source`` for a consolidated entry: ``name::relpath:line``."""
    name, root = origin[id(entry)]
    try:
        rel = entry.source_file.relative_to(root)
    except ValueError:
        rel = Path(entry.source_file.name)
    return f"{name}::{rel}:{entry.source_line}"


def _conflicts(entries: list[Entry]) -> list[list[Entry]]:
    """Same date+title but different body across sources — flagged for review."""
    groups: dict[tuple[str, str], list[Entry]] = defaultdict(list)
    for entry in entries:
        if entry.title:
            groups[entry.identity].append(entry)
    return [g for g in groups.values() if len({e.body_hash for e in g}) > 1]


def format_report(report: ConsolidationReport, dest: Path) -> str:
    """Dry-run report: what consolidation would do. Writes nothing."""
    entries = report.all_entries
    kept, dropped = _dedup(entries)
    lines = [
        f"# Consolidation dry-run: {dest}",
        "",
        f"**{len(entries)} entries** across {len(report.sources)} source(s); "
        f"{len(kept)} after dedup, {len(dropped)} duplicate(s) merged.",
        "",
        "| Source | Path | Entries |",
        "|---|---|---|",
    ]
    for scan in report.sources:
        lines.append(f"| {scan.name} | {scan.path} | {len(scan.entries)} |")
    conflicts = _conflicts(entries)
    if conflicts:
        lines += ["", f"**Conflicts — same date+title, different body ({len(conflicts)} group(s), review):**"]
        for group in conflicts:
            locs = ", ".join(_provenance(e, report.origin) for e in group)
            lines.append(f"- {group[0].date} `{group[0].title}` — {locs}")
    lines += ["", "Nothing written. Re-run with --apply to consolidate and archive the sources."]
    return "\n".join(lines)


def _write_report(report: ConsolidationReport, result: ConsolidationResult, dest: Path) -> None:
    lines = [
        "# Consolidation report",
        "",
        f"- Sources consolidated: {len(report.sources)}",
        f"- Entries written: {len(result.written)}",
        f"- Duplicates merged (kept longest body, themes unioned): {len(result.dropped_duplicates)}",
        f"- Sources archived and removed: {len(result.archives)}",
        "",
        "## Sources",
        "",
    ]
    for scan, archive in zip(report.sources, result.archives, strict=False):
        lines.append(f"- `{scan.name}`: {scan.path} → {archive}")
    if result.dropped_duplicates:
        lines += ["", "## Merged duplicates", "", "| Date | Title | Kept | Dropped |", "|---|---|---|---|"]
        for kept, dropped in result.dropped_duplicates:
            lines.append(
                f"| {kept.date} | {kept.title or '(untitled)'} "
                f"| {_provenance(kept, report.origin)} | {_provenance(dropped, report.origin)} |"
            )
    (dest / "consolidation-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _check_disjoint(report: ConsolidationReport, dest: Path) -> None:
    if dest.exists() and any(dest.iterdir()):
        raise ConsolidationError(f"destination must be empty or new: {dest}")
    d = dest.resolve()
    for scan in report.sources:
        s = scan.path.resolve()
        if d == s or d in s.parents or s in d.parents:
            raise ConsolidationError(f"destination {dest} overlaps source {scan.path}")


def apply_consolidation(report: ConsolidationReport, dest: Path) -> ConsolidationResult:
    """Write the managed journal to ``dest``, then archive + remove each source.

    Order matters for safety: the destination is fully written *before* any
    source is touched, and each source is archived and verified *before* its
    originals are removed.
    """
    _check_disjoint(report, dest)
    result = ConsolidationResult()
    entries, dropped = _dedup(report.all_entries)
    result.dropped_duplicates = dropped

    paths, written, _unthemed = _write_entries(entries, dest, lambda e: _provenance(e, report.origin))
    result.written = written
    _generate_views(entries, dest, paths)

    try:
        for scan in report.sources:
            result.archives.append(archive_and_remove(scan.path))
            result.sources_removed.append(scan.path)
    except ArchiveError as exc:
        raise ConsolidationError(str(exc)) from exc

    _write_report(report, result, dest)
    return result
