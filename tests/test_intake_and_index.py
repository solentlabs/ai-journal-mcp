from ai_journal.indexer import build_index, search
from ai_journal.intake import scan_journal
from ai_journal.model import slugify

# A small journal exercising the intake paths: a managed-style index file, a
# per-theme file that repeats an entry (exact duplicate), an orphan with no
# dated entries, and a dated archive file in a YYYY-MM subdirectory.
JOURNAL_FILES = {
    "JOURNAL.md": "# Journal\n\n### 2026-06-01: Modem Auth Bug\n\nThe HNAP private key was lost between calls.\n",
    "themed.md": (
        "## 2026-05-01: Indexing Lessons\n\nFTS5 makes search trivial.\n"
        "\n## 2026-06-01: Modem Auth Bug\n\nThe HNAP private key was lost between calls.\n"
    ),
    "orphan.md": "# Planning doc\n\nNo dated entries here.\n",
    "2026-04/15-old-entry.md": "### 2026-04-15: Old Entry\n\nArchived body.\n",
}


def test_scan_counts_and_orphans(make_journal):
    report = scan_journal(make_journal(JOURNAL_FILES))
    assert len(report.all_entries) == 4
    assert [s.path.name for s in report.orphans] == ["orphan.md"]


def test_exact_duplicate_detection(make_journal):
    report = scan_journal(make_journal(JOURNAL_FILES))
    dupes = report.exact_duplicates
    assert len(dupes) == 1
    assert dupes[0][0].title == "Modem Auth Bug"
    assert len(dupes[0]) == 2


def test_index_and_search(make_journal, tmp_path):
    report = scan_journal(make_journal(JOURNAL_FILES))
    db = tmp_path / "index.db"
    count = build_index(db, [("test", e) for e in report.all_entries])
    assert count == 4
    hits = search(db, "private key")
    assert hits
    assert hits[0]["title"] == "Modem Auth Bug"
    assert hits[0]["journal"] == "test"
    assert search(db, "nonexistentterm") == []
    assert search(db, "FTS5", since="2026-06-01") == []
    assert search(db, "private key", journal="other") == []


def test_slugify():
    assert slugify("The Private Key Bug (State Management)") == "the-private-key-bug-state-management"
    assert slugify("") == "untitled"
