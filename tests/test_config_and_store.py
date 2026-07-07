from datetime import date

import pytest

from ai_journal_mcp.config import JournalSource, load_config
from ai_journal_mcp.store import is_managed, load_managed, load_source, write_entry


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


def test_add_journal_escapes_quotes_and_backslashes(tmp_path):
    # regression: a quote in the name produced invalid TOML, breaking every
    # subsequent load_config until journals.toml was repaired by hand
    from ai_journal_mcp.config import add_journal

    cfg = tmp_path / "journals.toml"
    target = tmp_path / 'dir with " quote and \\ backslash'
    assert add_journal('my "work" journal', target, "managed", cfg) is True
    [src] = load_config(cfg)
    assert src.name == 'my "work" journal'
    assert src.path == target


@pytest.mark.parametrize(
    "bad_text",
    [
        "---\ntitle: no closing fence\n",  # unclosed frontmatter
        "---\n- just\n- a list\n---\n\nbody\n",  # frontmatter not a mapping
        "---\ndate: [not, a, date]\n---\n\nbody\n",  # unparseable date
        "---\ndate: 2026-13-45\n---\n\nbody\n",  # invalid date value
    ],
)
def test_one_malformed_file_does_not_wedge_the_journal(tmp_path, caplog, bad_text):
    # regression: any of these raised (ValueError/AttributeError) out of
    # load_managed, breaking every add/refresh/reindex for the whole journal
    write_entry(tmp_path, date(2026, 7, 1), "Good Entry", "good body")
    (tmp_path / "entries" / "2026-07" / "bad.md").write_text(bad_text, encoding="utf-8")
    with caplog.at_level("WARNING"):
        entries = load_managed(tmp_path)
    assert [e.title for e in entries] == ["Good Entry"]
    assert "bad.md" in caplog.text  # the warning names the offending file


def test_add_journal_rejects_control_characters(tmp_path):
    # regression: a newline in the name wrote invalid TOML, breaking every
    # subsequent load_config until hand-repaired
    from ai_journal_mcp.config import add_journal

    cfg = tmp_path / "journals.toml"
    with pytest.raises(ValueError, match="control characters"):
        add_journal("work\nnotes", tmp_path / "j", "managed", cfg)
    assert not cfg.exists()


def test_load_managed_reports_skips_to_caller(tmp_path):
    write_entry(tmp_path, date(2026, 7, 1), "Good", "fine")
    (tmp_path / "entries" / "2026-07" / "bad.md").write_text("---\ndate: 2026-13-45\n---\n\nx\n", encoding="utf-8")
    skipped = []
    entries = load_managed(tmp_path, skipped=skipped)
    assert [e.title for e in entries] == ["Good"]
    assert len(skipped) == 1 and "bad.md" in skipped[0]
