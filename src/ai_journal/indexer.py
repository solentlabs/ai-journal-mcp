"""SQLite + FTS5 index over journal entries.

The index is disposable: markdown is the source of truth and the database
can be regenerated from it at any time.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

from .model import Entry

_FTS_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
_FTS_TOKEN = re.compile(r'"[^"]*"|[()]|[^\s()]+')
_OR_WORD = re.compile(r"[A-Za-z0-9]{3,}")


def _sanitize_fts_query(query: str) -> str:
    """Make a user query safe for FTS5 MATCH without losing its operators.

    Quoted phrases, parentheses, and the boolean operators are passed through
    untouched; any other bareword containing FTS5-special characters (e.g. the
    hyphen in "fleet-relative") is wrapped as a phrase so it matches literally
    instead of being parsed as syntax and crashing the query.
    """
    out: list[str] = []
    for match in _FTS_TOKEN.finditer(query):
        token = match.group(0)
        if (
            token.startswith('"')
            or token in ("(", ")")
            or token in _FTS_OPERATORS
            or re.fullmatch(r"[A-Za-z0-9_]+\*?", token)
        ):
            out.append(token)
        else:
            out.append('"' + token.replace('"', '""') + '"')
    return " ".join(out)


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    journal TEXT NOT NULL,
    date TEXT NOT NULL,
    title TEXT,
    theme TEXT,
    source TEXT NOT NULL,
    line INTEGER NOT NULL,
    body TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, body, content='entries', content_rowid='id'
);
"""


def build_index(db_path: Path, entries: list[tuple[str, Entry]]) -> int:
    """(journal_name, entry) pairs -> fresh index. Returns row count."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        for journal, entry in entries:
            theme = entry.themes[0] if entry.themes else None
            cur = conn.execute(
                "INSERT INTO entries (journal, date, title, theme, source, line, body) VALUES (?,?,?,?,?,?,?)",
                (
                    journal,
                    entry.date.isoformat(),
                    entry.title,
                    theme,
                    str(entry.source_file),
                    entry.source_line,
                    entry.body,
                ),
            )
            conn.execute(
                "INSERT INTO entries_fts (rowid, title, body) VALUES (?,?,?)",
                (cur.lastrowid, entry.title or "", entry.body),
            )
        conn.commit()
        return conn.execute("SELECT count(*) FROM entries").fetchone()[0]
    finally:
        conn.close()


def search(
    db_path: Path,
    query: str,
    limit: int = 10,
    journal: str | None = None,
    theme: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = """
            SELECT e.journal, e.date, e.title, e.theme, e.source, e.line,
                   snippet(entries_fts, 1, '**', '**', ' … ', 12) AS snippet,
                   bm25(entries_fts) AS rank
            FROM entries_fts
            JOIN entries e ON e.id = entries_fts.rowid
            WHERE entries_fts MATCH ?
        """
        params: list = [_sanitize_fts_query(query)]
        for column, value in (("journal", journal), ("theme", theme)):
            if value:
                sql += f" AND e.{column} = ?"
                params.append(value)
        if since:
            sql += " AND e.date >= ?"
            params.append(since)
        if until:
            sql += " AND e.date <= ?"
            params.append(until)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _fts_or_query(text: str) -> str:
    """Build an FTS5 OR-query from a blob of text, for similarity matching.

    FTS5 ANDs bare terms by default, which over-constrains "find similar"; we
    want any-term overlap. Terms are alphanumeric (>=3 chars), deduped, and
    capped. bm25 down-weights common words by idf, so a stopword list isn't
    needed.
    """
    seen: list[str] = []
    for word in _OR_WORD.findall(text.lower()):
        if word not in seen:
            seen.append(word)
    return " OR ".join(seen[:40])


def suggest_themes(db_path: Path, text: str, limit: int = 5, hits: int = 20) -> list[str]:
    """Suggest existing themes for new entry text, by FTS similarity.

    Finds entries similar to ``text``, tallies the themes of the top ``hits``
    matches, and returns the most common existing themes, most-frequent first.
    Returns [] when nothing matches. Suggestion only — writes nothing; the
    caller proposes the results for confirmation. (The index stores one theme
    per entry, so suggestions come from primary themes of similar entries.)
    """
    query = _fts_or_query(text)
    if not query:
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT e.theme AS theme FROM entries_fts "
            "JOIN entries e ON e.id = entries_fts.rowid "
            "WHERE entries_fts MATCH ? AND e.theme IS NOT NULL "
            "ORDER BY bm25(entries_fts) LIMIT ?",
            (query, hits),
        ).fetchall()
    finally:
        conn.close()
    counts = Counter(row["theme"] for row in rows)
    return [theme for theme, _ in counts.most_common(limit)]


def list_themes(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT coalesce(theme, '(unthemed)') AS theme, journal, count(*) AS entries "
                "FROM entries GROUP BY theme, journal ORDER BY entries DESC"
            )
        ]
    finally:
        conn.close()


def entries_over_time(db_path: Path, theme: str | None = None, journal: str | None = None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT substr(date,1,7) AS month, count(*) AS entries FROM entries WHERE 1=1"
        params: list = []
        if theme:
            sql += " AND theme = ?"
            params.append(theme)
        if journal:
            sql += " AND journal = ?"
            params.append(journal)
        sql += " GROUP BY month ORDER BY month"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
