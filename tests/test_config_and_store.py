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


def _task_linking(root, rel):
    tasks_dir = root / "tasks"
    tasks_dir.mkdir(exist_ok=True)
    (tasks_dir / "t.md").write_text(
        f"---\ntitle: T\nstatus: open\npriority: medium\nblocked_by: []\nentries:\n- {rel}\n"
        "tags: []\ncreated: '2026-06-11'\nupdated: '2026-06-11'\n---\n\nbody\n"
    )


def test_update_entry_fields_replace_and_preserve(tmp_path):
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "Title", "Body.", themes=["a"], tags=["x"])
    out = update_entry(root, path, tags=["x", "y"], themes="b, c")
    assert out == path
    [entry] = load_managed(root)
    assert (entry.tags, entry.themes, entry.title, entry.body) == (["x", "y"], ["b", "c"], "Title", "Body.")
    assert entry.date == date(2026, 6, 11)
    update_entry(root, path, body="New body.", tags=[])
    [entry] = load_managed(root)
    assert (entry.body, entry.tags) == ("New body.", [])


def test_update_entry_title_renames_and_rewrites_task_links(tmp_path):
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "Old Title", "Body.")
    _task_linking(root, str(path.relative_to(root)))
    new = update_entry(root, path, title="Brand New Title")
    assert new.name == "11-brand-new-title.md"
    assert new.exists() and not path.exists()
    [entry] = load_managed(root)
    assert entry.title == "Brand New Title" and entry.body == "Body."
    assert str(new.relative_to(root)) in (root / "tasks" / "t.md").read_text()
    assert "old-title" not in (root / "tasks" / "t.md").read_text()


def test_update_entry_rename_collision_gets_suffix(tmp_path):
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    write_entry(root, date(2026, 6, 11), "Taken", "one")
    other = write_entry(root, date(2026, 6, 11), "Other", "two")
    assert update_entry(root, other, title="Taken").name == "11-taken-2.md"
    assert len(load_managed(root)) == 2


def test_update_entry_same_slug_keeps_name(tmp_path):
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "Same Title", "one")
    assert update_entry(root, path, title="SAME title!").name == path.name


@pytest.mark.parametrize("bad", ["../outside.md", "tasks/t.md", "entries/2026-06/missing.md", "entries"])
def test_update_entry_rejects_bad_paths(tmp_path, bad):
    from ai_journal_mcp.store import EntryError, update_entry

    root = tmp_path / "journal"
    write_entry(root, date(2026, 6, 11), "T", "b")
    (root / "tasks").mkdir()
    (root / "tasks" / "t.md").write_text("x")
    (tmp_path / "outside.md").write_text("x")
    with pytest.raises(EntryError):
        update_entry(root, bad, tags=["z"])


def test_update_entry_rejects_empty_title_and_malformed(tmp_path):
    from ai_journal_mcp.store import EntryError, update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "T", "b")
    with pytest.raises(EntryError, match="empty"):
        update_entry(root, path, title="  ")
    bad = root / "entries" / "2026-06" / "stray.md"
    bad.write_text("no frontmatter")
    with pytest.raises(EntryError, match="frontmatter"):
        update_entry(root, bad, tags=["z"])


def test_update_entry_snapshots_old_text_and_prunes_stale(tmp_path):
    import os
    import time

    from ai_journal_mcp import store
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "Old Title", "Original body.")
    original = path.read_text()
    update_entry(root, path, body="Oops, wrong body.")
    new = update_entry(root, path, title="New Title")  # rename keeps the earlier snapshots
    folder = root / "attic" / "edits" / "2026-06" / "11-old-title"
    snaps = sorted(folder.glob("*.md"))
    assert len(snaps) == 2
    assert snaps[0].read_text() == original  # the very first text is recoverable
    assert "Oops" in snaps[1].read_text()
    assert not path.exists() and new.exists()
    # attic never feeds the loader
    assert len(load_managed(root)) == 1
    # stale snapshots are pruned on the next edit; a fresh one survives
    stale = time.time() - (store.EDIT_SNAPSHOT_DAYS + 1) * 86400
    os.utime(snaps[0], (stale, stale))
    update_entry(root, new, tags=["z"])
    assert not snaps[0].exists() and snaps[1].exists()


def test_update_entry_noop_writes_no_snapshot(tmp_path):
    from ai_journal_mcp.store import update_entry

    root = tmp_path / "journal"
    path = write_entry(root, date(2026, 6, 11), "T", "b", tags=["x"])
    update_entry(root, path, tags=["x"])
    assert not (root / "attic").exists()
