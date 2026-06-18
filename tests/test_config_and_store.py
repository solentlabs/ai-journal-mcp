from datetime import date

import pytest

from ai_journal.config import JournalSource, load_config
from ai_journal.store import is_managed, load_managed, load_source, write_entry


def test_load_config(tmp_path):
    cfg = tmp_path / "journals.toml"
    cfg.write_text(
        '[[journal]]\nname = "tech"\npath = "/tmp/j"\nmode = "managed"\n\n'
        '[[journal]]\nname = "deals"\npath = "/tmp/deals.md"\n'
    )
    sources = load_config(cfg)
    assert [s.name for s in sources] == ["tech", "deals"]
    assert sources[0].mode == "managed"
    assert sources[1].mode == "indexed"  # default


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="journal"):
        load_config(tmp_path / "nope.toml")


def test_write_entry_roundtrip(tmp_path):
    root = tmp_path / "journal"
    path = write_entry(
        root,
        date(2026, 6, 11),
        "A New Insight",
        "The body.",
        themes=["development-practices"],
        tags=["testing"],
        blog_angles=["A Catchy Title"],
    )
    assert path == root / "entries" / "2026-06" / "11-a-new-insight.md"
    assert is_managed(root)
    [entry] = load_managed(root)
    assert entry.title == "A New Insight"
    assert entry.body == "The body."
    assert entry.themes == ["development-practices"]
    assert entry.tags == ["testing"]
    assert entry.blog_angles == ["A Catchy Title"]


def test_write_entry_collision_suffix(tmp_path):
    root = tmp_path / "journal"
    first = write_entry(root, date(2026, 6, 11), "Same Title", "one")
    second = write_entry(root, date(2026, 6, 11), "Same Title", "two")
    assert first.name == "11-same-title.md"
    assert second.name == "11-same-title-2.md"
    assert len(load_managed(root)) == 2


def test_load_managed_skips_non_entry_files(tmp_path):
    root = tmp_path / "journal"
    write_entry(root, date(2026, 1, 1), "Real", "body")
    (root / "entries" / "stray.md").write_text("no frontmatter")
    (root / "entries" / "meta.md").write_text("---\ntitle: no date\n---\nbody")
    assert [e.title for e in load_managed(root)] == ["Real"]


def test_write_entry_accepts_comma_separated_strings(tmp_path):
    # themes/tags passed as a single comma-separated string are normalized
    # into a list rather than stored as one blob.
    root = tmp_path / "journal"
    write_entry(root, date(2026, 6, 16), "Comma Lists", "body", themes="alpha, beta", tags="x,y, z")
    [entry] = load_managed(root)
    assert entry.themes == ["alpha", "beta"]
    assert entry.tags == ["x", "y", "z"]


def test_load_source_dispatch(tmp_path):
    managed_root = tmp_path / "managed"
    write_entry(managed_root, date(2026, 2, 2), "Managed Entry", "body")
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    (plain_dir / "log.md").write_text("## 2026-03-03: Plain Entry\n\nbody\n")
    single = tmp_path / "single.md"
    single.write_text("## 2026-04-04\n\nsession notes\n")

    assert [e.title for e in load_source(JournalSource("m", managed_root, "managed"))] == ["Managed Entry"]
    assert [e.title for e in load_source(JournalSource("p", plain_dir, "indexed"))] == ["Plain Entry"]
    assert [e.date for e in load_source(JournalSource("s", single, "indexed"))] == [date(2026, 4, 4)]
