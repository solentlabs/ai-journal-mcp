from datetime import date
from pathlib import Path

from ai_journal_mcp.indexer import build_index, entries_over_time, list_themes, search, suggest_themes
from ai_journal_mcp.model import Entry


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


def test_suggest_themes_from_similar_entries(tmp_path):
    # new entry text overlaps the "Modem Fix" (modems) entry; the theme-less
    # deals entry also matches but contributes no theme.
    assert suggest_themes(make_db(tmp_path), "hnap auth bug in the modem") == ["modems"]


def test_suggest_themes_empty_on_no_match(tmp_path):
    assert suggest_themes(make_db(tmp_path), "xylophone zucchini") == []


def test_all_themes_indexed_not_just_primary(tmp_path):
    # An entry with several themes is findable and counted under every one,
    # not only its first (regression: the index once stored themes[0] only).
    db = tmp_path / "idx.db"
    build_index(
        db, [("tech", make_entry(date(2026, 1, 1), "Dual", "parser notes worth a blog post", ["parser", "blog"]))]
    )
    listed = {(r["theme"], r["entries"]) for r in list_themes(db)}
    assert ("parser", 1) in listed and ("blog", 1) in listed
    # filter by the SECONDARY theme finds it
    assert [r["title"] for r in search(db, "parser OR blog", theme="blog")] == ["Dual"]
    # suggestions surface both themes
    assert set(suggest_themes(db, "parser blog")) == {"parser", "blog"}


def test_entry_tags_are_searchable(tmp_path):
    # Tags live only in frontmatter, never in the title/body. They must still be
    # findable by search — symmetric with how a task's tags are folded into its
    # searchable body (regression: entry tags were parsed but dropped from the
    # index, so tag-based retrieval silently failed for entries).
    db = tmp_path / "idx.db"
    entry = Entry(
        date=date(2026, 1, 1),
        title="Dependency currency check",
        body="floors sit at HA's pins",
        source_file=Path("x.md"),
        source_line=1,
        header_level=2,
        tags=["ai-drift", "home-assistant"],
    )
    build_index(db, [("tech", entry)])
    # the tag words appear nowhere in title/body, yet search finds the entry
    # (hyphenated tags also exercise the FTS-query sanitizer)
    assert [r["title"] for r in search(db, "ai-drift")] == ["Dependency currency check"]
    assert [r["title"] for r in search(db, "home-assistant")] == ["Dependency currency check"]
    # a tag that was never applied still must not match
    assert search(db, "unused-tag") == []


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
