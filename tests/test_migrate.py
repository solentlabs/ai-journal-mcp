from ai_journal.intake import scan_journal
from ai_journal.migrate import apply_migration
from ai_journal.parser import parse_file_with_fallback
from ai_journal.store import load_managed

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
