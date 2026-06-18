"""Shared test fixtures.

Testing taxonomy (mirrors the sibling Cable Modem Monitor repo):

* **Format/parse cases → fixture files.** Real-world inputs live under
  ``tests/fixtures/`` and are driven through ``parametrize`` so each sample is
  its own named test. Adding a newly-seen journal format is a two-file drop, no
  test code. See ``test_parser.py``.
* **Pure logic → table-driven** (`@pytest.mark.parametrize` over inline cases).
* **Filesystem behavior → factory fixtures** like ``make_journal`` below,
  rather than ad-hoc inline file-writing duplicated across tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Absolute path to ``tests/fixtures``."""
    return FIXTURES


@pytest.fixture
def make_journal(tmp_path: Path):
    """Factory that writes a mapping of ``relative_path -> markdown`` into a
    fresh journal directory and returns its root.

    Keeps journal-shaped test data declarative and in one place instead of
    repeating ``mkdir`` / ``write_text`` boilerplate in every test.
    """

    def _make(files: dict[str, str], name: str = "journal") -> Path:
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        for rel, text in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        return root

    return _make
