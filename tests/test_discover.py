"""Discovery evidence report: shapes, patterns, frontmatter, excerpts."""

from __future__ import annotations

import pytest

from ai_journal_mcp.discover import dir_shape, discover, filename_shape, format_discovery, heading_shape
from test_spec_intake import WORK_FILES  # the motivating real-world layout


@pytest.mark.parametrize(
    ("line", "shape"),
    [
        ("### [2026-01-23 10:42] Fixed the build", "### [YYYY-MM-DD HH:MM] Title"),
        ("### 2026-06-11: Auth Bug", "### YYYY-MM-DD: Title"),
        ("## 2026-06-11", "## YYYY-MM-DD"),
        ("# Notes from the field", "# Title"),
        ("## Week 23 retro", "## Title N Title"),
    ],
)
def test_heading_shape(line, shape):
    assert heading_shape(line) == shape


@pytest.mark.parametrize(
    ("name", "shape"),
    [
        ("2026-01-23.md", "YYYY-MM-DD.md"),
        ("2026-01-23-coffee-meeting.md", "YYYY-MM-DD-slug.md"),
        ("13-wsl2-migration.md", "N-slug.md"),
        ("README.md", "slug.md"),
    ],
)
def test_filename_shape(name, shape):
    assert filename_shape(name) == shape


def test_dir_shape(tmp_path):
    from pathlib import PurePath

    assert dir_shape(PurePath("entries/2026-01")) == "entries/YYYY-MM"
    assert dir_shape(PurePath(".")) == "."


def test_discover_collects_evidence(make_journal):
    root = make_journal({**WORK_FILES, "meta/2026-06-01-note.md": "---\ndate: 2026-06-01\ntags: [a]\n---\n\nbody\n"})
    report = discover(root)
    patterns = {p: (count, examples) for p, count, examples in report.name_patterns}
    assert patterns["entries/YYYY-MM/YYYY-MM-DD.md"][0] == 2
    assert patterns["receipts/YYYY-MM-DD-slug.md"][1] == ["receipts/2026-01-23-coffee-meeting.md"]
    shapes = {s: count for s, count, _ in report.heading_shapes}
    assert shapes["### [YYYY-MM-DD HH:MM] Title"] == 3
    assert report.frontmatter_files == 1
    assert dict(report.frontmatter_keys) == {"date": 1, "tags": 1}
    assert any("[2026-01-23 10:42]" in text for _, text in report.excerpts)


def test_format_discovery_is_actionable(make_journal):
    out = format_discovery(discover(make_journal(WORK_FILES)))
    assert "## File name patterns" in out
    assert "`entries/YYYY-MM/YYYY-MM-DD.md` | 2 |" in out
    assert "### [2026-01-23 10:42] Fixed the build pipeline" in out  # raw example beside the shape
    assert "## Next steps" in out  # the spec schema and loop instructions
    assert "[[source]]" in out
    assert "migrate ROOT --spec SPEC --apply" in out


def test_discover_skips_tool_owned_dirs(make_journal):
    root = make_journal(
        {
            "log.md": "## 2026-06-01: Real\n\nbody\n",
            "attic/old.md": "### [2026-01-01 09:00] Pre-migration copy\n\nold\n",
            ".git/config.md": "# not content\n",
        }
    )
    report = discover(root)
    assert report.md_count == 1
    assert all("attic" not in p for p, _, _ in report.name_patterns)
