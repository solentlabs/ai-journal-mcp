import ai_journal_mcp.config as config
from ai_journal_mcp.cli import main

# A minimal indexed journal: one dated entry plus an undated orphan.
CLI_FILES = {
    "JOURNAL.md": "# J\n\n### 2026-06-01: Indexed Insight\n\nSearchable body text.\n",
    "notes.md": "# undated planning doc\n",
}


def test_scan_command(make_journal, capsys):
    assert main(["scan", str(make_journal(CLI_FILES))]) == 0
    out = capsys.readouterr().out
    assert "1 entries" in out
    assert "notes.md" in out  # orphan reported


def test_migrate_dry_run_then_apply(make_journal, capsys):
    root = make_journal(CLI_FILES)
    assert main(["migrate", str(root)]) == 0
    assert "dry run" in capsys.readouterr().out
    assert not (root / "entries").exists()

    assert main(["migrate", str(root), "--apply"]) == 0
    out = capsys.readouterr().out
    assert "Wrote 1 entries" in out
    assert (root / "entries" / "2026-06" / "01-indexed-insight.md").exists()

    # refuses to migrate twice
    assert main(["migrate", str(root), "--apply"]) == 1
    assert "refusing" in capsys.readouterr().out


def test_reindex_search_refresh(make_journal, tmp_path, capsys):
    root = make_journal(CLI_FILES)
    db = tmp_path / "idx.db"
    main(["migrate", str(root), "--apply"])
    capsys.readouterr()

    assert main(["reindex", str(root), "--db", str(db)]) == 0
    assert "Indexed 1 entries" in capsys.readouterr().out

    assert main(["search", "searchable", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "Indexed Insight" in out

    assert main(["search", "absentterm", "--db", str(db)]) == 0
    assert "No matches" in capsys.readouterr().out

    assert main(["refresh", str(root)]) == 0
    assert "Regenerated views for 1" in capsys.readouterr().out


def test_reindex_plain_dir_and_file(make_journal, tmp_path, capsys):
    # Two distinct source types: a plain directory of logs and a single file.
    plain = make_journal({"log.md": "## 2026-05-05: Plain\n\nbody\n"}, name="plain")
    single = tmp_path / "single.md"
    single.write_text("## 2026-05-06\n\nnotes\n")
    db = tmp_path / "idx.db"
    assert main(["reindex", str(plain), str(single), "--db", str(db)]) == 0
    assert "Indexed 2 entries" in capsys.readouterr().out


def test_cli_refresh_rescues_hand_added_entry(make_journal, capsys):
    root = make_journal(CLI_FILES)
    assert main(["migrate", str(root), "--apply"]) == 0
    assert main(["refresh", str(root)]) == 0  # generate JOURNAL.md
    capsys.readouterr()
    # a stale session hand-appends a dated entry to the generated view
    jm = root / "JOURNAL.md"
    jm.write_text(jm.read_text() + "\n### 2026-06-15: Stray Insight\n\nHand added.\n")
    assert main(["refresh", str(root)]) == 0
    assert "Rescued 1 hand-added" in capsys.readouterr().out


def test_cli_init_refuses_existing_then_keeps_duplicate_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DEFAULT_CONFIG", tmp_path / "journals.toml")
    # init the same managed root twice -> the second is refused (exit 1)
    root = tmp_path / "journal"
    assert main(["init", str(root)]) == 0
    capsys.readouterr()
    assert main(["init", str(root)]) == 1
    assert "already a managed journal" in capsys.readouterr().out
    # a *new* path but an already-registered name -> created, config left alone
    assert main(["init", str(tmp_path / "other"), "--name", "journal"]) == 0
    assert "already configured" in capsys.readouterr().out


def test_cli_consolidate_dedupes_source_names(tmp_path, capsys):
    # two sources sharing a basename: the second must be suffixed, not collide
    one = tmp_path / "one" / "log.md"
    one.parent.mkdir()
    one.write_text("## 2026-06-01: A\n\nbody a\n")
    two = tmp_path / "two" / "log.md"
    two.parent.mkdir()
    two.write_text("## 2026-06-02: B\n\nbody b\n")
    assert main(["consolidate", str(tmp_path / "dest"), "--from", str(one), "--from", str(two)]) == 0
    assert "dry run" in capsys.readouterr().out


def test_cli_consolidate_aborts_on_error(make_journal, capsys):
    a = make_journal({"a.md": "## 2026-06-01\n\nbody\n"}, name="srcA")
    dest = make_journal({"x.md": "## 2026-01-01\n\nexisting\n"}, name="dest")  # non-empty dest
    assert main(["consolidate", str(dest), "--from", str(a), "--apply"]) == 1
    assert "Consolidation aborted" in capsys.readouterr().out


def test_cli_serve_invokes_server_main(monkeypatch):
    import ai_journal_mcp.server as server

    called = {}
    monkeypatch.setattr(server, "main", lambda: called.setdefault("ran", True))
    assert main(["serve"]) == 0
    assert called["ran"] is True


def test_cli_reindex_includes_tasks(make_journal, tmp_path, capsys):
    # regression: the CLI built a task-less index while the server's included
    # them — spec §7 says both kinds are indexed, whoever builds it
    from ai_journal_mcp.indexer import search
    from ai_journal_mcp.tasks import create_task

    root = make_journal({"entries/2026-06/01-note.md": "---\ndate: '2026-06-01'\ntitle: Note\n---\n\nentry body\n"})
    create_task(root, "Write the blog post", body="draft the staleness story")
    db = tmp_path / "idx.db"
    assert main(["reindex", str(root), "--db", str(db)]) == 0
    assert "Indexed 2 entries" in capsys.readouterr().out
    rows = search(db, "staleness")
    assert rows and rows[0]["kind"] == "task"


def test_cli_serve_without_server_extra_gives_hint(monkeypatch, capsys):
    # a CLI-only install (no [server] extra) must say how to fix it, not
    # die with a raw ModuleNotFoundError from inside the import
    import sys as _sys

    class _NoMcp:
        # faithful "pip install ai-journal-mcp" (no extra): mcp is absent
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "mcp" or fullname.startswith("mcp."):
                raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
            return

    for mod in [m for m in _sys.modules if m == "mcp" or m.startswith("mcp.") or m == "ai_journal_mcp.server"]:
        monkeypatch.delitem(_sys.modules, mod)
    monkeypatch.setattr(_sys, "meta_path", [_NoMcp(), *_sys.meta_path])
    assert main(["serve"]) == 1
    assert "ai-journal-mcp[server]" in capsys.readouterr().out


def test_cli_reindex_ignores_tasks_in_raw_directories(make_journal, tmp_path, capsys):
    # regression: task loading had no is_managed guard and scan didn't skip
    # tasks/, so a raw directory's task files could be indexed twice
    from ai_journal_mcp.indexer import search

    root = make_journal(
        {
            "log.md": "## 2026-06-01: Real Entry\n\nsearchable prose\n",
            "tasks/note.md": "---\ntitle: Not an entry\n---\n\n## 2026-06-02: Sneaky\n\ntask body text\n",
        }
    )
    db = tmp_path / "idx.db"
    assert main(["reindex", str(root), "--db", str(db)]) == 0
    assert "Indexed 1 entries" in capsys.readouterr().out
    assert search(db, "sneaky OR task") == []  # raw-dir tasks/ is tool-owned, not content


def test_cli_serve_incompatible_mcp_names_the_real_problem(monkeypatch, capsys):
    # an installed-but-wrong mcp (missing the fastmcp path) must not be
    # blamed on the [server] extra being absent
    import sys as _sys
    import types

    for mod in [m for m in _sys.modules if m == "mcp" or m.startswith("mcp.") or m == "ai_journal_mcp.server"]:
        monkeypatch.delitem(_sys.modules, mod)
    fake_mcp = types.ModuleType("mcp")  # no server attribute, not a package
    monkeypatch.setitem(_sys.modules, "mcp", fake_mcp)
    assert main(["serve"]) == 1
    out = capsys.readouterr().out
    assert "incompatible" in out
    assert "[server] extra" not in out


def test_cli_init_rejects_control_character_names(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DEFAULT_CONFIG", tmp_path / "journals.toml")
    assert main(["init", str(tmp_path / "j"), "--name", "bad\nname"]) == 1
    assert "control characters" in capsys.readouterr().out


def test_cli_search_malformed_query_prints_message_not_traceback(make_journal, tmp_path, capsys):
    root = make_journal(CLI_FILES)
    db = tmp_path / "idx.db"
    main(["reindex", str(root), "--db", str(db)])
    capsys.readouterr()
    assert main(["search", "(", "--db", str(db)]) == 1
    assert "invalid search query" in capsys.readouterr().out
