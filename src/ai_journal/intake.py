"""Scan existing journals and report what a migration would do.

The scan is read-only. It walks a journal directory, parses every markdown
file, and produces an IntakeReport: entry counts, date ranges, duplicates,
and files that contain no dated entries (orphans needing human triage).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .model import Entry
from .parser import parse_file_with_fallback

SKIP_DIRS = {".git", ".claude", "attic", "entries", "themes", "node_modules"}


# Source-file stem -> theme. Files not listed (JOURNAL.md, monthly archives)
# carry no theme; the migration merges themes from deduplicated copies.
def infer_themes(path: Path, root: Path) -> list[str]:
    rel = path.relative_to(root)
    if len(rel.parts) > 1 or path.stem.upper() == "JOURNAL":
        return []
    return [path.stem]


@dataclass
class FileScan:
    path: Path
    entries: list[Entry]
    line_count: int

    @property
    def date_range(self) -> tuple[str, str] | None:
        if not self.entries:
            return None
        dates = sorted(e.date for e in self.entries)
        return (dates[0].isoformat(), dates[-1].isoformat())


@dataclass
class IntakeReport:
    root: Path
    scans: list[FileScan] = field(default_factory=list)
    orphans: list[FileScan] = field(default_factory=list)

    @property
    def all_entries(self) -> list[Entry]:
        return [e for scan in self.scans for e in scan.entries]

    @property
    def exact_duplicates(self) -> list[list[Entry]]:
        """Groups of entries whose normalized bodies are identical."""
        by_hash: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        for entry in self.all_entries:
            by_hash[(entry.date.isoformat(), entry.body_hash)].append(entry)
        return [group for group in by_hash.values() if len(group) > 1]

    @property
    def near_duplicates(self) -> list[list[Entry]]:
        """Same date + same title slug but different body (needs human review)."""
        exact_keys = {id(e) for group in self.exact_duplicates for e in group[1:]}
        by_identity: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        for entry in self.all_entries:
            if entry.title and id(entry) not in exact_keys:
                by_identity[entry.identity].append(entry)
        return [group for group in by_identity.values() if len(group) > 1]


def scan_journal(root: Path) -> IntakeReport:
    report = IntakeReport(root=root)
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        entries = parse_file_with_fallback(path)
        for entry in entries:
            entry.themes = infer_themes(path, root)
        scan = FileScan(
            path=path,
            entries=entries,
            line_count=len(path.read_text(encoding="utf-8", errors="replace").splitlines()),
        )
        if entries:
            report.scans.append(scan)
        else:
            report.orphans.append(scan)
    return report


def format_report(report: IntakeReport) -> str:
    lines = [f"# Intake dry-run: {report.root}", ""]
    total = len(report.all_entries)
    lines.append(
        f"**{total} entries** across {len(report.scans)} files; {len(report.orphans)} files with no dated entries."
    )
    lines.append("")
    lines.append("| File | Entries | Date range | Lines |")
    lines.append("|---|---|---|---|")
    for scan in sorted(report.scans, key=lambda s: -len(s.entries)):
        rel = scan.path.relative_to(report.root)
        lo, hi = scan.date_range or ("—", "—")
        lines.append(f"| {rel} | {len(scan.entries)} | {lo} → {hi} | {scan.line_count} |")
    if report.orphans:
        lines.append("")
        lines.append(
            "**No dated entries (need triage):** "
            + ", ".join(str(s.path.relative_to(report.root)) for s in report.orphans)
        )
    exact = report.exact_duplicates
    if exact:
        lines.append("")
        lines.append(f"**Exact duplicates ({len(exact)} groups):**")
        for group in exact:
            locs = ", ".join(f"{e.source_file.relative_to(report.root)}:{e.source_line}" for e in group)
            lines.append(f"- {group[0].date} `{group[0].title or '(untitled)'}` — {locs}")
    near = report.near_duplicates
    if near:
        lines.append("")
        lines.append(f"**Same date+title, different body ({len(near)} groups, human review):**")
        for group in near:
            locs = ", ".join(f"{e.source_file.relative_to(report.root)}:{e.source_line}" for e in group)
            lines.append(f"- {group[0].date} `{group[0].title}` — {locs}")
    return "\n".join(lines)
