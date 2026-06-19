from datetime import date
from pathlib import Path

import pytest

from ai_journal import server
from ai_journal.config import JournalSource
from ai_journal.store import write_entry


@pytest.fixture
def journals(tmp_path, monkeypatch):
    managed = tmp_path / "managed"
    write_entry(managed, date(2026, 6, 1), "Seed Entry", "hnap discovery notes", themes=["modems"])
    readonly = tmp_path / "log.md"
    readonly.write_text("## 2026-06-02\n\nread-only diligence session\n")

    sources = [
        JournalSource("technical", managed, "managed"),
        JournalSource("deals", readonly, "indexed"),
    ]
    monkeypatch.setattr(server, "load_config", lambda: sources)
    monkeypatch.setattr(server, "DEFAULT_DB", tmp_path / "index.db")
    return managed


def test_reindex_and_search(journals):
    assert "Indexed 2 entries" in server.reindex()
    hits = server.search_journal("hnap")
    assert hits[0]["title"] == "Seed Entry"
    assert server.search_journal("diligence")[0]["journal"] == "deals"


def test_index_built_lazily(journals):
    # no explicit reindex — _ensure_index builds on first query
    assert server.search_journal("discovery")


def test_stale_index_self_heals(journals):
    import os
    import time

    server.reindex()
    assert server.search_journal("latecomer") == []
    # out-of-band write (the skill fallback path): file + refreshed views,
    # no reindex — JOURNAL.md's newer mtime must trigger a rebuild on search
    write_entry(journals, date(2026, 6, 12), "Latecomer Entry", "latecomer body")
    from ai_journal.migrate import refresh_views

    refresh_views(journals)
    future = time.time() + 5
    os.utime(journals / "JOURNAL.md", (future, future))
    assert server.search_journal("latecomer")[0]["title"] == "Latecomer Entry"


def test_get_entry_inside_and_outside(journals, tmp_path):
    hit = server.search_journal("hnap")[0]
    assert "hnap discovery notes" in server.get_entry(hit["source"])
    outside = tmp_path.parent / "secrets.txt"
    with pytest.raises(ValueError, match="not inside"):
        server.get_entry(str(outside))


def test_add_entry_full_cycle(journals):
    path = server.add_entry(
        "technical", "Fresh Capture", "captured wisdom", themes=["practices"], entry_date="2026-06-11"
    )
    assert Path(path).exists()
    # views regenerated and index refreshed in the same call
    assert (journals / "JOURNAL.md").exists()
    assert (journals / "themes" / "practices.md").exists()
    assert server.search_journal("captured wisdom")[0]["title"] == "Fresh Capture"


def test_add_entry_rejects_bad_targets(journals):
    with pytest.raises(ValueError, match="read-only"):
        server.add_entry("deals", "Nope", "body")
    with pytest.raises(ValueError, match="Unknown journal"):
        server.add_entry("ghost", "Nope", "body")


def test_refresh_rescues_hand_added_journal_entry(journals):
    from ai_journal.migrate import refresh_views

    # an old session appends a dated entry directly to the generated view
    journal_md = journals / "JOURNAL.md"
    refresh_views(journals)
    journal_md.write_text(journal_md.read_text() + "\n### 2026-06-12: Stray Insight\n\nWritten by a stale session.\n")
    count, rescued = refresh_views(journals)
    assert rescued == 1
    [saved] = [
        e
        for e in __import__("ai_journal.store", fromlist=["load_managed"]).load_managed(journals)
        if e.title == "Stray Insight"
    ]
    assert "stale session" in saved.body
    # idempotent: a second refresh does not duplicate the rescue
    assert refresh_views(journals)[1] == 0


def test_indexed_directory_staleness(tmp_path, monkeypatch):
    # A raw indexed directory must go stale on add AND delete — the case the
    # old max-mtime heuristic missed (a delete lowers the max mtime).
    src = tmp_path / "logs"
    src.mkdir()
    (src / "a.md").write_text("## 2026-06-01\n\nfirst note about alpha\n")
    monkeypatch.setattr(server, "load_config", lambda: [JournalSource("logs", src, "indexed")])
    monkeypatch.setattr(server, "DEFAULT_DB", tmp_path / "idx.db")

    assert server.search_journal("alpha")  # builds, finds
    assert server.search_journal("beta") == []

    (src / "b.md").write_text("## 2026-06-02\n\nsecond note about beta\n")
    assert server.search_journal("beta")  # add detected -> rebuilt

    (src / "a.md").unlink()
    assert server.search_journal("alpha") == []  # delete detected -> rebuilt


def test_list_themes_and_over_time(journals):
    server.reindex()
    themes = {t["theme"] for t in server.list_themes()}
    assert {"modems", "(unthemed)"} <= themes
    months = server.entries_over_time(journal="technical")
    assert months == [{"month": "2026-06", "entries": 1}]
