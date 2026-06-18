from datetime import date
from pathlib import Path

from ai_journal.indexer import build_index, entries_over_time, list_themes, search
from ai_journal.model import Entry


def make_entry(d, title, body, themes=None):
    return Entry(
        date=d, title=title, body=body, source_file=Path("x.md"), source_line=1, header_level=2, themes=themes or []
    )


def make_db(tmp_path):
    db = tmp_path / "idx.db"
    pairs = [
        ("tech", make_entry(date(2026, 1, 5), "Modem Fix", "hnap auth repaired", ["modems"])),
        ("tech", make_entry(date(2026, 2, 5), "Test Habits", "pytest discipline", ["practices"])),
        ("deals", make_entry(date(2026, 2, 9), None, "diligence on hnap vendor", [])),
    ]
    build_index(db, pairs)
    return db


def test_search_filters(tmp_path):
    db = make_db(tmp_path)
    assert len(search(db, "hnap")) == 2
    assert [r["journal"] for r in search(db, "hnap", journal="deals")] == ["deals"]
    assert [r["title"] for r in search(db, "hnap", theme="modems")] == ["Modem Fix"]
    assert search(db, "hnap", until="2026-01-31")[0]["title"] == "Modem Fix"
    assert search(db, "hnap", since="2026-02-01")[0]["journal"] == "deals"


def test_list_themes(tmp_path):
    rows = list_themes(make_db(tmp_path))
    themes = {(r["theme"], r["journal"]): r["entries"] for r in rows}
    assert themes[("modems", "tech")] == 1
    assert themes[("(unthemed)", "deals")] == 1


def test_entries_over_time(tmp_path):
    db = make_db(tmp_path)
    assert entries_over_time(db) == [
        {"month": "2026-01", "entries": 1},
        {"month": "2026-02", "entries": 2},
    ]
    assert entries_over_time(db, journal="tech", theme="practices") == [
        {"month": "2026-02", "entries": 1},
    ]


def test_rebuild_replaces_existing(tmp_path):
    db = make_db(tmp_path)
    count = build_index(db, [("only", make_entry(date(2026, 3, 1), "Solo", "alone"))])
    assert count == 1
    assert search(db, "hnap") == []


def test_search_handles_hyphenated_terms(tmp_path):
    # A hyphenated bareword (e.g. "fleet-relative") must not leak a raw
    # FTS5/SQLite error, and must still match the entry that contains it.
    db = tmp_path / "idx.db"
    build_index(
        db,
        [
            ("tech", make_entry(date(2026, 6, 16), "Moat Note", "the only moat is fleet-relative interpretation")),
            ("tech", make_entry(date(2026, 6, 1), "Other", "unrelated body")),
        ],
    )
    assert [r["title"] for r in search(db, "fleet-relative")] == ["Moat Note"]
    # ...and the same term must survive inside a boolean expression.
    assert "Moat Note" in [r["title"] for r in search(db, "moat OR fleet-relative")]
