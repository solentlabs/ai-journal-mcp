"""Extraction spec parsing and per-file rule execution."""

from __future__ import annotations

import pytest

from ai_journal_mcp.spec import SpecError, parse_file_with_rule, parse_spec

VALID_SPEC = r"""
[[source]]
paths = ["entries/**/*.md"]
header = '^###\s+\[(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\]\s*(?P<title>.*?)\s*$'

[[source]]
paths = ["receipts/*.md"]
filename_date = '(?P<date>\d{4}-\d{2}-\d{2})'
"""


def test_parse_spec_valid():
    spec = parse_spec(VALID_SPEC)
    assert len(spec.rules) == 2
    assert spec.rules[0].header is not None and spec.rules[0].filename_date is None
    assert spec.rules[1].filename_date is not None
    assert spec.rules[1].date_format == "%Y-%m-%d"  # default
    assert spec.text == VALID_SPEC  # verbatim, for the migration report


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("[[source", "not valid TOML"),
        ("", "no [[source]] tables"),
        ("[other]\nx = 1", "unknown top-level keys"),
        ("[[source]]\npaths = [\"*.md\"]\nheader = '(?P<date>\\d+)'\nfoo = 1", "unknown keys"),
        ("[[source]]\nheader = '(?P<date>\\d+)'", "'paths' must be a non-empty list"),
        ("[[source]]\npaths = []\nheader = '(?P<date>\\d+)'", "'paths' must be a non-empty list"),
        ("[[source]]\npaths = [\"/etc/*.md\"]\nheader = '(?P<date>\\d+)'", "relative to the journal root"),
        ("[[source]]\npaths = [\"../*.md\"]\nheader = '(?P<date>\\d+)'", "relative to the journal root"),
        ("[[source]]\npaths = [\"*.md\"]\nheader = '('", "not a valid regex"),
        ("[[source]]\npaths = [\"*.md\"]\nheader = '^# (?P<title>.*)'", "named group (?P<date>...)"),
        ('[[source]]\npaths = ["*.md"]', "needs 'header' and/or 'filename_date'"),
        ("[[source]]\npaths = [\"*.md\"]\nheader = '(?P<date>\\d+)'\ndate_format = 'nope'", "strptime format"),
        ("[[source]]\npaths = [\"*.md\"]\nheader = '(?P<date>\\d+)'\ndate_format = 3", "strptime format"),
    ],
    ids=[
        "bad-toml",
        "no-tables",
        "unknown-top-level",
        "unknown-rule-key",
        "paths-missing",
        "paths-empty",
        "absolute-glob",
        "dotdot-glob",
        "bad-regex",
        "missing-date-group",
        "no-extractor",
        "bad-date-format",
        "nonstring-date-format",
    ],
)
def test_parse_spec_rejects(text, error):
    with pytest.raises(SpecError) as exc_info:
        parse_spec(text)
    assert error in str(exc_info.value)


def test_rule_header_extracts_entries_with_time(make_journal):
    root = make_journal(
        {
            "entries/2026-01/2026-01-23.md": (
                "### [2026-01-23 10:42] First\n\nbody one\n\n### [2026-01-23] Second\n\nbody two\n"
            )
        }
    )
    spec = parse_spec(VALID_SPEC)
    entries = parse_file_with_rule(root / "entries" / "2026-01" / "2026-01-23.md", spec.rules[0])
    assert [(e.title, e.time) for e in entries] == [("First", "10:42"), ("Second", None)]
    assert entries[0].body == "body one"


def test_rule_filename_date_makes_whole_file_entry(make_journal):
    root = make_journal({"receipts/2026-01-23-coffee.md": "# Coffee with vendor\n\nreceipt body\n"})
    spec = parse_spec(VALID_SPEC)
    (entry,) = parse_file_with_rule(root / "receipts" / "2026-01-23-coffee.md", spec.rules[1])
    assert entry.date.isoformat() == "2026-01-23"
    assert entry.title == "Coffee with vendor"
    assert entry.body == "receipt body"


def test_rule_with_no_match_yields_orphan(make_journal):
    root = make_journal(
        {
            "entries/2026-01/undated.md": "# no dated headers here\n",
            "receipts/undated-note.md": "no date in this name either\n",
        }
    )
    spec = parse_spec(VALID_SPEC)
    assert parse_file_with_rule(root / "entries" / "2026-01" / "undated.md", spec.rules[0]) == []
    assert parse_file_with_rule(root / "receipts" / "undated-note.md", spec.rules[1]) == []


def test_rule_invalid_date_in_filename_yields_orphan(make_journal):
    # a name that matches the regex but is not a real date must not crash or guess
    root = make_journal({"receipts/2026-13-99-bogus.md": "# Bogus\n\nbody\n"})
    spec = parse_spec(VALID_SPEC)
    assert parse_file_with_rule(root / "receipts" / "2026-13-99-bogus.md", spec.rules[1]) == []
