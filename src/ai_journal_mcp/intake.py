"""Scan existing journals and report what a migration would do.

The scan is read-only. It walks a journal directory, parses every markdown
file, and produces an IntakeReport: entry counts, date ranges, duplicates,
and files that contain no dated entries (orphans needing human triage).

With an extraction spec (``spec.py``), the walk is driven by the spec's
globs instead of the default layout assumptions — the path for foreign
formats found by ``discover``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .model import Entry
from .parser import parse_file_with_fallback
from .spec import ExtractionSpec, SourceRule, parse_file_with_rule

SKIP_DIRS = {".git", ".claude", "attic", "entries", "tasks", "themes", "node_modules"}
# A spec names its own paths, so only tool- and VCS-owned directories are off
# limits; entries/tasks/themes may well be where a foreign journal keeps data.
SPEC_SKIP_DIRS = {".git", ".claude", "attic", "node_modules"}


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
    spec: ExtractionSpec | None = None

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


def _skipped(path: Path, root: Path, skip_dirs: set[str]) -> bool:
    return any(part in skip_dirs for part in path.relative_to(root).parts)


def _file_scan(path: Path, entries: list[Entry], root: Path) -> FileScan:
    for entry in entries:
        entry.themes = infer_themes(path, root)
    return FileScan(
        path=path,
        entries=entries,
        line_count=len(path.read_text(encoding="utf-8", errors="replace").splitlines()),
    )


def scan_journal(root: Path, spec: ExtractionSpec | None = None) -> IntakeReport:
    if spec is not None:
        return _scan_with_spec(root, spec)
    report = IntakeReport(root=root)
    for path in sorted(root.rglob("*.md")):
        if _skipped(path, root, SKIP_DIRS):
            continue
        scan = _file_scan(path, parse_file_with_fallback(path), root)
        (report.scans if scan.entries else report.orphans).append(scan)
    return report


def _scan_with_spec(root: Path, spec: ExtractionSpec) -> IntakeReport:
    report = IntakeReport(root=root, spec=spec)
    assigned: dict[Path, SourceRule] = {}
    for rule in spec.rules:
        for pattern in rule.paths:
            for path in root.glob(pattern):
                if path.is_file() and not _skipped(path, root, SPEC_SKIP_DIRS):
                    assigned.setdefault(path, rule)  # first matching rule wins
    # markdown the spec does not cover still needs triage — surface it as
    # orphans rather than silently leaving it behind
    candidates = set(assigned)
    candidates.update(p for p in root.rglob("*.md") if not _skipped(p, root, SPEC_SKIP_DIRS))
    for path in sorted(candidates):
        matched = assigned.get(path)
        entries = parse_file_with_rule(path, matched) if matched else []
        scan = _file_scan(path, entries, root)
        (report.scans if entries else report.orphans).append(scan)
    return report


def _excerpt(path: Path, max_chars: int = 110) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    first = [line.strip() for line in text.splitlines() if line.strip()][:2]
    joined = " · ".join(first) or "(empty)"
    return joined[: max_chars - 1] + "…" if len(joined) > max_chars else joined


def format_report(report: IntakeReport) -> str:
    lines = [f"# Intake dry-run: {report.root}", ""]
    total = len(report.all_entries)
    lines.append(
        f"**{total} entries** across {len(report.scans)} files; {len(report.orphans)} files with no dated entries."
    )
    if report.spec is not None:
        lines.append(f"Parsed with an extraction spec ({len(report.spec.rules)} source rules).")
    lines.append("")
    lines.append("| File | Entries | Date range | Lines |")
    lines.append("|---|---|---|---|")
    for scan in sorted(report.scans, key=lambda s: -len(s.entries)):
        rel = scan.path.relative_to(report.root)
        lo, hi = scan.date_range or ("—", "—")
        lines.append(f"| {rel} | {len(scan.entries)} | {lo} → {hi} | {scan.line_count} |")
    if report.orphans:
        max_shown = 20
        lines.append("")
        lines.append(f"**No dated entries ({len(report.orphans)} files, need triage):**")
        for scan in report.orphans[:max_shown]:
            lines.append(f"- {scan.path.relative_to(report.root)} — {_excerpt(scan.path)}")
        if len(report.orphans) > max_shown:
            lines.append(f"- … and {len(report.orphans) - max_shown} more")
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
