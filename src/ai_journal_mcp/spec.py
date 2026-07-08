"""Extraction specs: LLM-proposed rules for one-time intake of foreign journals.

Existing journals arrive in arbitrary layouts. The ``discover`` report gives
an LLM (or a human) the evidence to write a spec — which paths hold entries
and how dates, times, and titles are encoded — and scan/migrate execute it
deterministically: original text is sliced verbatim, never re-generated. The
spec is throwaway: used for one migration, recorded verbatim in the migration
report, never persistent config.

Spec format (TOML)::

    [[source]]
    paths = ["entries/**/*.md"]  # globs relative to the journal root
    header = "^###\\s+\\[(?P<date>\\d{4}-\\d{2}-\\d{2})(?:\\s+(?P<time>\\d{2}:\\d{2}))?\\]\\s*(?P<title>.*?)\\s*$"

    [[source]]
    paths = ["receipts/*.md"]
    filename_date = "(?P<date>\\d{4}-\\d{2}-\\d{2})"
    date_format = "%Y-%m-%d"  # strptime format, this is the default

Per file, the first ``[[source]]`` whose glob matches wins. ``header`` splits
the file into entries exactly like the default parser (same fence and body
rules); if it yields nothing and ``filename_date`` finds a date in the file
name, the whole file becomes one entry titled by its first heading. Files a
rule matches but cannot date stay orphans in the dry-run report — nothing is
guessed.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .model import Entry
from .parser import DEFAULT_DATE_FORMAT, parse_markdown, whole_file_entry


class SpecError(ValueError):
    """An extraction spec that cannot be executed as written."""


_ALLOWED_KEYS = {"paths", "header", "filename_date", "date_format"}


@dataclass
class SourceRule:
    paths: list[str]
    header: re.Pattern[str] | None
    filename_date: re.Pattern[str] | None
    date_format: str


@dataclass
class ExtractionSpec:
    rules: list[SourceRule]
    text: str  # the verbatim TOML, recorded in the migration report


def parse_spec(text: str) -> ExtractionSpec:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SpecError(f"not valid TOML: {exc}") from exc
    unknown_top = set(data) - {"source"}
    if unknown_top:
        raise SpecError(f"unknown top-level keys {sorted(unknown_top)}; a spec is a list of [[source]] tables")
    tables = data.get("source")
    if not isinstance(tables, list) or not tables:
        raise SpecError("no [[source]] tables — a spec needs at least one")
    return ExtractionSpec(rules=[_parse_rule(i, t) for i, t in enumerate(tables, start=1)], text=text)


def load_spec(path: Path) -> ExtractionSpec:
    return parse_spec(path.read_text(encoding="utf-8"))


def _parse_rule(n: int, table: object) -> SourceRule:
    where = f"[[source]] #{n}"
    if not isinstance(table, dict):
        raise SpecError(f"{where} is not a table")
    unknown = set(table) - _ALLOWED_KEYS
    if unknown:
        raise SpecError(f"{where}: unknown keys {sorted(unknown)} (allowed: {sorted(_ALLOWED_KEYS)})")
    paths = table.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise SpecError(f"{where}: 'paths' must be a non-empty list of glob strings")
    for glob in paths:
        if Path(glob).is_absolute() or ".." in Path(glob).parts:
            raise SpecError(f"{where}: glob {glob!r} must be relative to the journal root, without '..'")
    header = _compile(where, "header", table.get("header"))
    filename_date = _compile(where, "filename_date", table.get("filename_date"))
    if header is None and filename_date is None:
        raise SpecError(f"{where}: needs 'header' and/or 'filename_date'")
    date_format = table.get("date_format", DEFAULT_DATE_FORMAT)
    if not isinstance(date_format, str) or "%" not in date_format:
        raise SpecError(f"{where}: 'date_format' must be a strptime format string like '%Y-%m-%d'")
    return SourceRule(paths=paths, header=header, filename_date=filename_date, date_format=date_format)


def _compile(where: str, key: str, raw: object) -> re.Pattern[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise SpecError(f"{where}: '{key}' must be a regex string")
    try:
        pattern = re.compile(raw)
    except re.error as exc:
        raise SpecError(f"{where}: '{key}' is not a valid regex: {exc}") from exc
    if "date" not in pattern.groupindex:
        raise SpecError(f"{where}: '{key}' must capture a named group (?P<date>...)")
    return pattern


def parse_file_with_rule(path: Path, rule: SourceRule) -> list[Entry]:
    """Extract a file's entries per the rule; empty list means orphan."""
    if rule.header is not None:
        text = path.read_text(encoding="utf-8", errors="replace")
        entries = parse_markdown(text, path, header_re=rule.header, date_format=rule.date_format)
        if entries:
            return entries
    if rule.filename_date is not None:
        match = rule.filename_date.search(path.name)
        if match:
            try:
                entry_date = datetime.strptime(match.group("date"), rule.date_format).date()
            except ValueError:
                return []
            return [whole_file_entry(path, entry_date)]
    return []
