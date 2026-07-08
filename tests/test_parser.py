"""Parser format tests — fixture-driven.

Each `tests/fixtures/parser/*.md` is a real-world journal format; its sibling
`*.expected.json` declares the expected parse. Adding a format is a two-file
drop (see fixtures/parser/README.md), no code change here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ai_journal_mcp.model import Entry
from ai_journal_mcp.parser import parse_markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "parser"
# Every input *.md paired with its *.expected.json (skips README.md and any
# stray markdown without an expectation file).
PARSER_FIXTURES = sorted(p for p in FIXTURES_DIR.glob("*.md") if p.with_suffix(".expected.json").exists())


def _assert_entry(entry: Entry, expected: dict) -> None:
    assert entry.date.isoformat() == expected["date"]
    if "time" in expected:
        assert entry.time == expected["time"]
    if "title" in expected:
        assert entry.title == expected["title"]
    if "header_level" in expected:
        assert entry.header_level == expected["header_level"]
    if "body" in expected:
        assert entry.body == expected["body"]
    for needle in expected.get("body_contains", []):
        assert needle in entry.body
    if "body_endswith" in expected:
        assert entry.body.endswith(expected["body_endswith"])


@pytest.mark.parametrize("fixture_path", PARSER_FIXTURES, ids=[f.stem for f in PARSER_FIXTURES])
def test_parser_format(fixture_path: Path) -> None:
    expected = json.loads(fixture_path.with_suffix(".expected.json").read_text(encoding="utf-8"))
    # a fixture may declare the extraction-spec header regex / date format it
    # needs, exercising foreign formats through the same harness
    kwargs: dict = {}
    if "header" in expected:
        kwargs["header_re"] = re.compile(expected["header"])
    if "date_format" in expected:
        kwargs["date_format"] = expected["date_format"]
    entries = parse_markdown(fixture_path.read_text(encoding="utf-8"), fixture_path, **kwargs)

    assert len(entries) == len(expected["entries"]), expected.get("description", fixture_path.stem)
    for entry, exp in zip(entries, expected["entries"], strict=True):
        _assert_entry(entry, exp)


def test_fixtures_present() -> None:
    """Guard against an empty glob silently passing the suite."""
    assert PARSER_FIXTURES, f"no parser fixtures found in {FIXTURES_DIR}"
