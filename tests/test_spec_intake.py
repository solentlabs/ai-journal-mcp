"""Spec-driven intake end to end: the work-journal shape that motivated
extraction specs — bracketed timestamp headers inside daily files under
entries/, plus filename-dated receipts — scans and migrates losslessly."""

from __future__ import annotations

import pytest

from ai_journal_mcp.intake import format_report, scan_journal
from ai_journal_mcp.migrate import apply_migration
from ai_journal_mcp.spec import parse_spec
from ai_journal_mcp.store import load_managed

WORK_SPEC = r"""
[[source]]
paths = ["entries/**/*.md"]
header = '^###\s+\[(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\]\s*(?P<title>.*?)\s*$'

[[source]]
paths = ["receipts/*.md"]
filename_date = '(?P<date>\d{4}-\d{2}-\d{2})'
"""

WORK_FILES = {
    "entries/2026-01/2026-01-23.md": (
        "# 2026-01-23\n\n"
        "### [2026-01-23 10:42] Fixed the build pipeline\n\nCI cache key was stale.\n\n"
        "### [2026-01-23 15:07] Standup notes\n\nSecond body of the day.\n"
    ),
    "entries/2026-01/2026-01-24.md": "### [2026-01-24 09:00] Next day\n\nDay two body.\n",
    "receipts/2026-01-23-coffee-meeting.md": "# Coffee with vendor\n\nReceipt details body.\n",
    "README.md": "# My journal\n\nHow I log things.\n",
}


def test_scan_with_spec_finds_everything(make_journal):
    root = make_journal(WORK_FILES)
    assert not scan_journal(root).all_entries  # the default parser is blind to this layout
    report = scan_journal(root, spec=parse_spec(WORK_SPEC))
    assert len(report.all_entries) == 4
    assert [s.path.name for s in report.orphans] == ["README.md"]
    times = {e.title: e.time for e in report.all_entries}
    assert times["Fixed the build pipeline"] == "10:42"
    assert times["Coffee with vendor"] is None  # filename-dated: no time to capture


def test_spec_report_mentions_spec_and_orphan_excerpts(make_journal):
    root = make_journal(WORK_FILES)
    out = format_report(scan_journal(root, spec=parse_spec(WORK_SPEC)))
    assert "extraction spec (2 source rules)" in out
    assert "README.md — # My journal · How I log things." in out  # excerpt for triage


def test_migrate_with_spec_end_to_end(make_journal):
    root = make_journal(WORK_FILES)
    report = scan_journal(root, spec=parse_spec(WORK_SPEC))
    before = {rel: (root / rel).read_bytes() for rel in WORK_FILES}
    result = apply_migration(report)

    assert len(result.written) == 4
    canonical = root / "entries" / "2026-01" / "23-fixed-the-build-pipeline.md"
    text = canonical.read_text(encoding="utf-8")
    assert "time: '10:42'" in text  # header time survives into frontmatter
    assert text.endswith("\nCI cache key was stale.\n")  # body sliced verbatim

    # originals byte-for-byte in attic, foreign layout fully cleared out
    for rel, data in before.items():
        assert (root / "attic" / rel).read_bytes() == data, rel
    assert not (root / "receipts").exists()
    assert not (root / "entries" / "2026-01" / "2026-01-23.md").exists()

    # the throwaway spec is recorded in the migration report
    migration_report = (root / "migration-report.md").read_text(encoding="utf-8")
    assert "## Extraction spec used" in migration_report
    assert "filename_date" in migration_report

    loaded = load_managed(root)
    assert len(loaded) == 4
    assert {e.body for e in report.all_entries} == {e.body for e in loaded}


def test_migrate_survives_canonical_name_collision(make_journal):
    # a foreign file whose path equals the canonical name the migration will
    # choose: attic-first ordering must preserve the original, not overwrite it
    files = {"entries/2026-01/23-note.md": "### [2026-01-23 10:42] Note\n\nCollision body.\n"}
    root = make_journal(files)
    apply_migration(scan_journal(root, spec=parse_spec(WORK_SPEC)))
    assert (root / "attic" / "entries" / "2026-01" / "23-note.md").read_bytes() == files[
        "entries/2026-01/23-note.md"
    ].encode()
    canonical = (root / "entries" / "2026-01" / "23-note.md").read_text(encoding="utf-8")
    assert canonical.startswith("---\n")
    assert "Collision body." in canonical


def test_apply_refuses_when_scan_found_nothing(make_journal):
    # a scan that understood no files must not strip the journal into attic
    root = make_journal({"README.md": "# My journal\n\nno dated entries\n"})
    with pytest.raises(ValueError, match="no entries"):
        apply_migration(scan_journal(root))
    assert not (root / "attic").exists()
    assert (root / "README.md").exists()


def test_spec_scan_reports_uncovered_markdown_as_orphans(make_journal):
    # markdown no glob matches must surface for triage, not silently vanish
    root = make_journal(
        {
            "entries/2026-01/2026-01-23.md": "### [2026-01-23 10:42] Entry\n\nbody\n",
            "elsewhere/stray.md": "# stray notes\n",
        }
    )
    report = scan_journal(root, spec=parse_spec(WORK_SPEC))
    assert [str(s.path.relative_to(root)) for s in report.orphans] == ["elsewhere/stray.md"]
