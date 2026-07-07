from datetime import date

from ai_journal_mcp.intake import scan_journal
from ai_journal_mcp.migrate import apply_migration, refresh_views
from ai_journal_mcp.parser import parse_file_with_fallback
from ai_journal_mcp.store import load_managed, write_entry

# A messy pre-migration journal: an index file with two entries (one of which
# is duplicated, with a longer body, in a per-theme file), a filename-dated
# archive entry, an undated planning note, and a non-markdown file that must
# survive into attic/.
MESSY_FILES = {
    "JOURNAL.md": (
        "# Journal\n\n"
        "### 2026-06-01: Auth Bug\n\nShort body.\n\n---\n\n"
        "### 2026-05-20: Solo Entry\n\nOnly in the index.\n"
    ),
    "modems.md": "## 2026-06-01: Auth Bug\n\nShort body but longer than the index copy.\n",
    "2026-01/13-filename-dated.md": "# Recovered Title\n\nBody from filename era.\n",
    "planning/notes.md": "# No dates here\n",
    "planning/keep.sh": "echo hi\n",
}


def test_filename_date_fallback(make_journal):
    root = make_journal(MESSY_FILES)
    entries = parse_file_with_fallback(root / "2026-01" / "13-filename-dated.md")
    assert len(entries) == 1
    assert entries[0].date.isoformat() == "2026-01-13"
    assert entries[0].title == "Recovered Title"
    assert entries[0].body == "Body from filename era."


def test_apply_migration(make_journal):
    root = make_journal(MESSY_FILES)
    result = apply_migration(scan_journal(root))

    # 4 raw entries, 1 dedup pair -> 3 written
    assert len(result.written) == 3
    assert len(result.dropped_duplicates) == 1
    kept, dropped = result.dropped_duplicates[0]
    assert kept.source_file.name == "modems.md"  # longest body wins
    assert kept.themes == ["modems"]  # theme merged from themed copy

    # canonical layout + originals preserved in attic
    assert (root / "entries" / "2026-06" / "01-auth-bug.md").exists()
    assert (root / "entries" / "2026-01" / "13-recovered-title.md").exists()
    assert (root / "attic" / "modems.md").exists()
    assert (root / "attic" / "2026-01" / "13-filename-dated.md").exists()
    assert (root / "attic" / "planning" / "notes.md").exists()
    assert not (root / "2026-01").exists()  # emptied and swept
    assert not (root / "planning").exists()  # fully relocated and swept
    assert (root / "attic" / "planning" / "keep.sh").exists()  # non-md preserved in attic

    # generated views
    journal = (root / "JOURNAL.md").read_text()
    assert "entries/2026-06/01-auth-bug.md" in journal
    assert (root / "themes" / "modems.md").exists()
    assert (root / "migration-report.md").exists()

    # managed loader round-trip
    loaded = load_managed(root)
    assert len(loaded) == 3
    auth = next(e for e in loaded if e.title == "Auth Bug")
    assert auth.themes == ["modems"]
    assert "longer than the index copy" in auth.body


def test_migration_no_text_loss(make_journal):
    """Every non-duplicate body survives verbatim in the managed store."""
    root = make_journal(MESSY_FILES)
    before = {e.body_hash for e in scan_journal(root).all_entries}
    apply_migration(scan_journal(root))
    after = {e.body_hash for e in load_managed(root)}
    # dropped duplicate bodies are the only ones allowed to be missing,
    # and their originals still exist in attic/
    assert after <= before
    assert len(before - after) == 1


def test_untitled_same_date_entries_both_survive(make_journal):
    # Two distinct date-only logs on the same day must NOT be merged just
    # because neither has a title (regression: _dedup once keyed every
    # title-less entry to (date, "untitled") and collapsed them).
    root = make_journal(
        {
            "log.md": (
                "## 2026-07-01\n\nFirst session — auth spike.\n"
                "\n## 2026-07-01\n\nSecond session — totally different work.\n"
            ),
        }
    )
    result = apply_migration(scan_journal(root))
    assert len(result.written) == 2
    assert result.dropped_duplicates == []
    bodies = [p.read_text(encoding="utf-8") for p in result.written]
    assert any("auth spike" in b for b in bodies)
    assert any("totally different work" in b for b in bodies)


def test_refresh_rescues_stray_sharing_date_and_title(make_journal):
    # regression: rescue matched on date+title only, so a hand-added JOURNAL.md
    # entry colliding with a stored one was dropped and refresh erased its text
    root = make_journal({})
    write_entry(root, date(2026, 7, 1), "Standup", "original text")
    refresh_views(root)
    jm = root / "JOURNAL.md"
    jm.write_text(
        jm.read_text(encoding="utf-8") + "\n### 2026-07-01: Standup\n\nNew thinking, same title.\n", encoding="utf-8"
    )
    _, rescued = refresh_views(root)
    assert rescued == 1
    bodies = {e.body for e in load_managed(root)}
    assert {"original text", "New thinking, same title."} <= bodies


def test_refresh_skips_stray_already_stored_verbatim(make_journal):
    root = make_journal({})
    write_entry(root, date(2026, 7, 1), "Standup", "same text")
    refresh_views(root)
    jm = root / "JOURNAL.md"
    jm.write_text(jm.read_text(encoding="utf-8") + "\n### 2026-07-01: Standup\n\nsame text\n", encoding="utf-8")
    _, rescued = refresh_views(root)
    assert rescued == 0
    assert len(load_managed(root)) == 1


def test_attic_preserves_original_bytes(make_journal):
    # the no-data-loss invariant, byte-for-byte: every original file must
    # survive in attic/ exactly as it was, not merely exist there
    root = make_journal(MESSY_FILES)
    before = {rel: (root / rel).read_bytes() for rel in MESSY_FILES}
    apply_migration(scan_journal(root))
    for rel, data in before.items():
        assert (root / "attic" / rel).read_bytes() == data, rel


def test_stale_theme_views_removed_on_refresh(make_journal):
    root = make_journal({})
    path = write_entry(root, date(2026, 7, 1), "Note", "body", themes=["alpha"])
    refresh_views(root)
    assert (root / "themes" / "alpha.md").exists()
    # retheme the entry: the old theme's view must disappear, not linger
    path.write_text(path.read_text(encoding="utf-8").replace("alpha", "beta"), encoding="utf-8")
    refresh_views(root)
    assert not (root / "themes" / "alpha.md").exists()
    assert (root / "themes" / "beta.md").exists()


def test_refresh_on_missing_path_is_a_true_noop(tmp_path):
    # regression: journal_lock's mkdir materialized a typo'd path plus .lock
    ghost = tmp_path / "jurnals" / "dev"
    assert refresh_views(ghost) == (0, 0)
    assert not ghost.exists()


def test_refresh_reports_skipped_malformed_files(make_journal):
    # regression: a malformed entry silently vanished from regenerated views;
    # the skip must be surfaced to the caller, not just logged to stderr
    root = make_journal({})
    write_entry(root, date(2026, 7, 1), "Good", "fine body")
    (root / "entries" / "2026-07" / "broken.md").write_text("---\ntitle: unclosed\n", encoding="utf-8")
    skipped = []
    count, _ = refresh_views(root, skipped=skipped)
    assert count == 1
    assert len(skipped) == 1 and "broken.md" in skipped[0]
