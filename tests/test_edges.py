from pathlib import Path

from ai_journal.intake import FileScan, format_report, scan_journal
from ai_journal.model import slugify
from ai_journal.parser import parse_file_with_fallback


def test_slugify_truncates_on_word_boundary():
    long_title = "word " * 30
    slug = slugify(long_title)
    assert len(slug) <= 60
    assert not slug.endswith("-")


def test_date_range_empty_scan():
    assert FileScan(path=Path("x.md"), entries=[], line_count=0).date_range is None


def test_format_report_lists_duplicates(make_journal):
    root = make_journal(
        {
            "a.md": "## 2026-01-01: Same Thing\n\nidentical body\n",
            "b.md": "## 2026-01-01: Same Thing\n\nidentical body\n",
            "c.md": "## 2026-01-01: Same Thing\n\ndifferent body entirely\n",
        }
    )
    report = format_report(scan_journal(root))
    assert "Exact duplicates (1 groups)" in report
    assert "different body entirely" not in report  # locations listed, not body content
    assert "human review" in report
    assert "a.md:1, c.md:1" in report


def test_fallback_rejects_invalid_locations(make_journal):
    # dir matches YYYY-MM but day part makes an impossible date; and a file
    # outside an archive-shaped directory gets no fallback at all.
    root = make_journal(
        {
            "2026-02/31-impossible-date.md": "# Title\n\nbody\n",
            "10-not-in-archive.md": "# Title\n\nbody\n",
        }
    )
    assert parse_file_with_fallback(root / "2026-02" / "31-impossible-date.md") == []
    assert parse_file_with_fallback(root / "10-not-in-archive.md") == []


def test_fallback_untitled_file(make_journal):
    root = make_journal({"2026-03/05-raw-notes.md": "just body text, no heading\n"})
    [entry] = parse_file_with_fallback(root / "2026-03" / "05-raw-notes.md")
    assert entry.title is None
    assert entry.body == "just body text, no heading"
