from datetime import date
from pathlib import Path

import pytest

from ai_journal_mcp import server
from ai_journal_mcp.config import JournalSource
from ai_journal_mcp.store import write_entry


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
    from ai_journal_mcp.migrate import refresh_views

    refresh_views(journals)
    future = time.time() + 5
    os.utime(journals / "JOURNAL.md", (future, future))
    assert server.search_journal("latecomer")[0]["title"] == "Latecomer Entry"


def test_hand_edited_entry_goes_stale(journals):
    # markdown is the source of truth however it got there: an edit made
    # directly to a file under entries/ (no tool, no refresh) must be picked
    # up by the next search, not served stale forever
    server.reindex()
    [entry_file] = (journals / "entries").rglob("*.md")
    entry_file.write_text(entry_file.read_text(encoding="utf-8") + "\nhand-edited addendum\n", encoding="utf-8")
    assert server.search_journal("addendum")[0]["title"] == "Seed Entry"


def test_corrupt_index_self_heals(journals):
    # regression: garbage in index.db raised sqlite3.DatabaseError on every
    # tool call instead of reading as stale and triggering a rebuild
    server.reindex()
    server.DEFAULT_DB.write_bytes(b"garbage, not sqlite")
    assert server.search_journal("hnap")[0]["title"] == "Seed Entry"


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


def test_update_task_with_reflection_graduates_into_searchable_entry(journals):
    created = server.add_task("technical", "Write up the migration audit", body="audit notes")
    res = server.update_task(
        "technical",
        created["id"],
        status="done",
        reflection="The migration guarantee held on live data.",
        themes=["process"],
    )
    assert res["status"] == "done"
    # the entry path is relative to the journal root; it exists and is searchable
    assert res["entry"] and (journals / res["entry"]).exists()
    assert server.search_journal("guarantee")[0]["title"] == "Write up the migration audit"
    fetched = server.get_task("technical", created["id"])
    assert fetched["status"] == "done"
    assert any("write-up-the-migration-audit" in e for e in fetched["entries"])


def test_add_entry_rejects_bad_targets(journals):
    with pytest.raises(ValueError, match="read-only"):
        server.add_entry("deals", "Nope", "body")
    with pytest.raises(ValueError, match="Unknown journal"):
        server.add_entry("ghost", "Nope", "body")


def test_refresh_rescues_hand_added_journal_entry(journals):
    from ai_journal_mcp.migrate import refresh_views

    # an old session appends a dated entry directly to the generated view
    journal_md = journals / "JOURNAL.md"
    refresh_views(journals)
    journal_md.write_text(journal_md.read_text() + "\n### 2026-06-12: Stray Insight\n\nWritten by a stale session.\n")
    count, rescued = refresh_views(journals)
    assert rescued == 1
    [saved] = [
        e
        for e in __import__("ai_journal_mcp.store", fromlist=["load_managed"]).load_managed(journals)
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


def test_tasks_are_searchable_and_tagged_words_match(journals):
    # a task in a managed journal must be findable by search_journal, by its
    # body AND by a tag word, and must carry kind='task'
    server.add_task("technical", "Write the staleness post", body="signature based detection", tags=["blog"])
    # found by body text
    hit = server.search_journal("signature")
    assert hit and hit[0]["title"] == "Write the staleness post"
    assert hit[0]["kind"] == "task"
    # found by the tag word "blog" even though it's not in the title/body prose
    assert any(h["title"] == "Write the staleness post" for h in server.search_journal("blog"))
    # entry-only views are not polluted by the task
    assert all(t["theme"] != "blog" for t in server.list_themes())
    assert server.entries_over_time(journal="technical") == [{"month": "2026-06", "entries": 1}]


def test_suggest_themes_surfaces_existing_theme(journals):
    server.reindex()
    # the seed entry is themed "modems"; similar text should suggest it
    assert "modems" in server.suggest_themes("hnap discovery notes")


def test_list_tasks_skips_readonly_and_applies_filters(journals):
    high = server.add_task("technical", "High work", priority="high")
    server.add_task("technical", "Low work", priority="low")
    # the indexed "deals" source is read-only and must never appear
    listed = server.list_tasks()
    assert {t["journal"] for t in listed} == {"technical"}
    assert len(listed) == 2
    # status filter excludes the open tasks (none are done)
    assert server.list_tasks(status="done") == []
    # priority filter narrows to the one high-priority task
    assert [t["id"] for t in server.list_tasks(priority="high")] == [high["id"]]
    # an unknown journal filter yields nothing
    assert server.list_tasks(journal="ghost") == []
    # a tag filter that matches no task's tags yields nothing
    assert server.list_tasks(tag="absent") == []


def test_update_task_without_reflection_returns_fields_only(journals):
    created = server.add_task("technical", "Tweak priority", priority="medium")
    res = server.update_task("technical", created["id"], priority="high")
    assert res["priority"] == "high"
    assert "entry" not in res  # no reflection -> no graduated entry


def test_add_task_error_becomes_value_error(journals):
    with pytest.raises(ValueError, match="priority"):
        server.add_task("technical", "Bad priority", priority="bogus")


def test_task_lookup_errors_become_value_errors(journals):
    with pytest.raises(ValueError, match="no task"):
        server.get_task("technical", "missing-id")
    with pytest.raises(ValueError, match="no task"):
        server.update_task("technical", "missing-id", status="done")


def test_main_runs_the_mcp_server(monkeypatch):
    ran = {}
    monkeypatch.setattr(server.mcp, "run", lambda: ran.setdefault("ran", True))
    server.main()
    assert ran["ran"] is True


def test_new_task_makes_index_stale_and_self_heals(journals):
    from ai_journal_mcp.migrate import refresh_views

    # give the managed journal a JOURNAL.md (real-world state): now the signature
    # is JOURNAL.md-based, and a task add touches only tasks/ — the tasks/ hash
    # folded into the signature is what must trigger the rebuild
    refresh_views(journals)
    server.reindex()
    assert server.search_journal("xylophone") == []
    server.add_task("technical", "Buy a xylophone", body="odd instrument")
    assert server.search_journal("xylophone")[0]["kind"] == "task"


def test_index_is_disposable_rebuild_is_identical(journals):
    # delete the DB outright: every tool must return identical results from
    # the auto-rebuilt index (markdown is the source of truth)
    server.reindex()
    before = (
        server.search_journal("hnap"),
        server.list_themes(),
        server.entries_over_time(),
    )
    server.DEFAULT_DB.unlink()
    after = (
        server.search_journal("hnap"),
        server.list_themes(),
        server.entries_over_time(),
    )
    assert after == before


def test_entries_over_time_by_tag(journals):
    server.add_entry("technical", "Meeting overran", "again, by 40 minutes", tags=["receipt"], entry_date="2026-06-15")
    assert server.entries_over_time(tag="receipt") == [{"month": "2026-06", "entries": 1}]


def test_add_entry_surfaces_skipped_malformed_files(journals):
    # regression: a malformed entry silently vanished from views/search; the
    # skip must reach the tool result, not just the server's stderr
    (journals / "entries" / "2026-06" / "broken.md").write_text("---\ntitle: unclosed\n", encoding="utf-8")
    result = server.add_entry("technical", "New One", "body text", entry_date="2026-06-20")
    assert "WARNING" in result and "broken.md" in result
    assert "Indexed" not in result  # path is still the first line
    assert "WARNING" in server.reindex()


def test_list_tasks_surfaces_broken_task_files(journals):
    server.add_task("technical", "Fine Task")
    (journals / "tasks" / "mangled.md").write_text("---\ntitle: unclosed\n", encoding="utf-8")
    listed = server.list_tasks()
    assert [t["title"] for t in listed if "title" in t] == ["Fine Task"]
    [warning] = [t["warning"] for t in listed if "warning" in t]
    assert "mangled.md" in warning


def test_indexed_dir_with_entries_subfolder_stays_fresh(tmp_path, monkeypatch):
    # regression: source_signature keyed "managed" off the entries/ dir alone,
    # so an indexed-mode tree containing entries/ was fingerprinted over files
    # the scanner ignores — edits outside entries/ never read as stale
    src = tmp_path / "notes"
    (src / "entries").mkdir(parents=True)  # formerly-managed leftovers
    (src / "scratch.md").write_text("## 2026-06-01\n\nalpha note\n")
    monkeypatch.setattr(server, "load_config", lambda: [JournalSource("notes", src, "indexed")])
    monkeypatch.setattr(server, "DEFAULT_DB", tmp_path / "idx.db")

    assert server.search_journal("alpha")
    (src / "scratch.md").write_text("## 2026-06-01\n\nalpha note, now about beta too\n")
    assert server.search_journal("beta")  # edit outside entries/ detected


def test_old_schema_index_rebuilds_instead_of_crashing(journals):
    # regression: a 0.2.0-era index (no entry_tags table) passed the signature
    # check and crashed the tag filter; the schema stamp must force a rebuild
    import sqlite3

    server.add_entry("technical", "Tagged", "receipt body", tags=["receipt"], entry_date="2026-06-21")
    conn = sqlite3.connect(server.DEFAULT_DB)
    conn.execute("DROP TABLE entry_tags")
    conn.execute("PRAGMA user_version = 0")  # what an older release wrote
    conn.commit()
    conn.close()
    assert server.entries_over_time(tag="receipt") == [{"month": "2026-06", "entries": 1}]


def test_discover_journal_and_scan_source_tools(make_journal):
    # the MCP side of the intake loop: evidence + spec dry-run, both read-only
    from test_spec_intake import WORK_FILES, WORK_SPEC

    root = make_journal(WORK_FILES)
    evidence = server.discover_journal(str(root))
    assert "entries/YYYY-MM/YYYY-MM-DD.md" in evidence
    assert "## Next steps" in evidence

    plain = server.scan_source(str(root))
    assert "0 entries" in plain  # default parser is blind to this layout
    with_spec = server.scan_source(str(root), spec_toml=WORK_SPEC)
    assert "4 entries" in with_spec
    assert "README.md" in with_spec  # orphan surfaced for triage
    assert not (root / "attic").exists()  # nothing written


def test_scan_source_rejects_bad_spec_and_bad_path(make_journal, tmp_path):
    root = make_journal({"log.md": "## 2026-06-01: A\n\nbody\n"})
    with pytest.raises(ValueError, match="bad extraction spec"):
        server.scan_source(str(root), spec_toml='[[source]]\npaths = ["*.md"]\n')
    with pytest.raises(ValueError, match="not a directory"):
        server.discover_journal(str(tmp_path / "nope"))


def test_server_instructions_steer_session_knowledge_to_journal():
    # the journal/memory division of labor ships in the MCP initialize
    # handshake so it reaches every agent on every client — losing it would
    # silently regress agents back into redundant memory files
    text = server.mcp.instructions or ""
    assert "add_entry" in text
    assert "memory" in text
    assert "standing instructions" in text
    assert "session knowledge" in server.add_entry.__doc__
