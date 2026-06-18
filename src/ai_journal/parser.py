"""Extract dated entries from heterogeneous markdown journals.

Handles the formats found in real journals:
- ``### 2026-06-11: Title`` (index-style entries)
- ``## 2026-06-11: Title`` (themed-file entries)
- ``## 2026-06-11`` (date-only session logs)
- internal section headers (``### The Situation``) that must NOT split entries
- date-like headers inside fenced code blocks, which must be ignored
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from .model import Entry

ENTRY_HEADER_RE = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<date>\d{4}-\d{2}-\d{2})\s*:?\s*(?P<title>.*?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
TRAILING_RULE_RE = re.compile(r"^(---|\*\*\*|___)\s*$")


def parse_markdown(text: str, source_file: Path) -> list[Entry]:
    """Parse all dated entries out of a markdown document.

    Content before the first dated header (titles, usage notes) is ignored.
    An entry's body runs to the next dated header at any heading level.
    """
    entries: list[Entry] = []
    current: Entry | None = None
    body_lines: list[str] = []
    in_fence = False

    def close_current() -> None:
        nonlocal current
        if current is None:
            return
        while body_lines and (not body_lines[-1].strip() or TRAILING_RULE_RE.match(body_lines[-1])):
            body_lines.pop()
        current.body = "\n".join(body_lines).strip("\n")
        entries.append(current)
        current = None
        body_lines.clear()

    for lineno, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence

        match = None if in_fence else ENTRY_HEADER_RE.match(line)
        if match:
            try:
                entry_date = date.fromisoformat(match.group("date"))
            except ValueError:
                match = None
            if match:
                close_current()
                current = Entry(
                    date=entry_date,
                    title=match.group("title") or None,
                    body="",
                    source_file=source_file,
                    source_line=lineno,
                    header_level=len(match.group("hashes")),
                )
                continue

        if current is not None:
            body_lines.append(line)

    close_current()
    return entries


def parse_file(path: Path) -> list[Entry]:
    return parse_markdown(path.read_text(encoding="utf-8", errors="replace"), path)


ARCHIVE_DIR_RE = re.compile(r"^\d{4}-\d{2}$")
ARCHIVE_FILE_RE = re.compile(r"^(?P<day>\d{2})-")
TITLE_LINE_RE = re.compile(r"^#{1,4}\s+(?P<title>\S.*?)\s*$")


def parse_file_with_fallback(path: Path) -> list[Entry]:
    """Parse a file; if it has no dated headers but sits in a YYYY-MM archive
    directory with a DD- filename prefix, recover the date from its location.

    Some archive eras wrote per-entry files whose only date is in the path
    (e.g. ``2026-01/13-wsl2-migration.md``). The whole file becomes one entry.
    """
    entries = parse_file(path)
    if entries:
        return entries

    dir_match = ARCHIVE_DIR_RE.match(path.parent.name)
    file_match = ARCHIVE_FILE_RE.match(path.name)
    if not (dir_match and file_match):
        return []
    try:
        entry_date = date.fromisoformat(f"{path.parent.name}-{file_match.group('day')}")
    except ValueError:
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    title = None
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        title_match = TITLE_LINE_RE.match(line)
        if title_match:
            title = title_match.group("title")
            body_start = i + 1
        break
    return [
        Entry(
            date=entry_date,
            title=title,
            body="\n".join(lines[body_start:]).strip("\n"),
            source_file=path,
            source_line=1,
            header_level=0,
        )
    ]
