from ai_journal.cli import main

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
