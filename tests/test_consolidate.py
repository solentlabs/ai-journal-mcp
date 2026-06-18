import tarfile

import pytest

from ai_journal.cli import main
from ai_journal.consolidate import (
    ConsolidationError,
    apply_consolidation,
    format_report,
    scan_sources,
)
from ai_journal.store import load_managed

# Two sources that share one titled entry (identical body -> a cross-source
# duplicate) plus a distinct date-only log each.
SRC_A = {"log.md": "## 2026-06-01: Shared Insight\n\nThe shared body.\n\n## 2026-06-02\n\nDate-only session in A.\n"}
SRC_B = {"notes.md": "## 2026-06-01: Shared Insight\n\nThe shared body.\n\n## 2026-06-03\n\nUnique to B.\n"}


def _two_sources(make_journal):
    return make_journal(SRC_A, name="srcA"), make_journal(SRC_B, name="srcB")


def test_dry_run_writes_nothing(make_journal, tmp_path):
    a, b = _two_sources(make_journal)
    report = scan_sources([("srcA", a), ("srcB", b)])
    text = format_report(report, tmp_path / "managed")
    assert "4 entries" in text
    assert "3 after dedup" in text
    assert not (tmp_path / "managed").exists()  # nothing written
    assert a.exists() and b.exists()  # sources untouched
    assert not (tmp_path / "srcA.tar.gz").exists()


def test_apply_dedups_unions_themes_and_archives(make_journal, tmp_path):
    a, b = _two_sources(make_journal)
    dest = tmp_path / "managed"
    report = scan_sources([("srcA", a), ("srcB", b)])
    before = {e.body_hash for e in report.all_entries}

    result = apply_consolidation(report, dest)

    # 4 raw entries -> 3 written, 1 cross-source duplicate merged
    assert len(result.written) == 3
    assert len(result.dropped_duplicates) == 1

    managed = load_managed(dest)
    assert {e.title for e in managed} == {"Shared Insight", None}
    shared = next(e for e in managed if e.title == "Shared Insight")
    assert shared.themes == ["log", "notes"]  # themes unioned across sources

    # sources archived in place and removed
    assert not a.exists() and not b.exists()
    assert (tmp_path / "srcA.tar.gz").exists()
    assert (tmp_path / "srcB.tar.gz").exists()

    # no data loss: every source body survives in the managed store
    assert before <= {e.body_hash for e in managed}


def test_archive_preserves_original_tree(make_journal, tmp_path):
    a, b = _two_sources(make_journal)
    apply_consolidation(scan_sources([("srcA", a), ("srcB", b)]), tmp_path / "managed")
    with tarfile.open(tmp_path / "srcA.tar.gz", "r:gz") as tar:
        assert "srcA/log.md" in tar.getnames()  # relative tree preserved


def test_provenance_in_frontmatter(make_journal, tmp_path):
    a, b = _two_sources(make_journal)
    apply_consolidation(scan_sources([("srcA", a), ("srcB", b)]), tmp_path / "managed")
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "managed" / "entries").rglob("*.md"))
    assert "srcA::log.md:" in text
    assert "srcB::notes.md:" in text


def test_rejects_dest_overlapping_a_source(make_journal, tmp_path):
    a, _ = _two_sources(make_journal)
    with pytest.raises(ConsolidationError, match="overlaps"):
        apply_consolidation(scan_sources([("srcA", a)]), a / "inside")


def test_rejects_nonempty_dest(make_journal, tmp_path):
    a, b = _two_sources(make_journal)
    dest = make_journal({"x.md": "## 2026-01-01\n\nbody\n"}, name="dest")
    with pytest.raises(ConsolidationError, match="empty"):
        apply_consolidation(scan_sources([("srcA", a), ("srcB", b)]), dest)


def test_single_file_source(tmp_path):
    f = tmp_path / "session.md"
    f.write_text("## 2026-07-01\n\nA single-file session log.\n")
    dest = tmp_path / "managed"
    result = apply_consolidation(scan_sources([("session", f)]), dest)
    assert len(result.written) == 1
    assert not f.exists()
    assert (tmp_path / "session.md.tar.gz").exists()


def test_conflict_reported_in_dry_run(make_journal, tmp_path):
    a = make_journal({"a.md": "## 2026-06-01: Same Title\n\nBody from A.\n"}, name="srcA")
    b = make_journal({"b.md": "## 2026-06-01: Same Title\n\nA different body from B.\n"}, name="srcB")
    text = format_report(scan_sources([("srcA", a), ("srcB", b)]), tmp_path / "managed")
    assert "Conflicts" in text
    assert "Same Title" in text


def test_cli_dry_run_then_apply(make_journal, tmp_path, capsys):
    a, b = _two_sources(make_journal)
    dest = tmp_path / "managed"

    assert main(["consolidate", str(dest), "--from", str(a), "--from", str(b)]) == 0
    assert "dry run" in capsys.readouterr().out
    assert not dest.exists()

    assert main(["consolidate", str(dest), "--from", str(a), "--from", str(b), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "Wrote 3 entries" in out
    assert (dest / "entries").exists()
    assert (dest / "consolidation-report.md").exists()
    assert not a.exists()
    assert (tmp_path / "srcA.tar.gz").exists()
