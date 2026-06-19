"""SQLite + FTS5 index over journal entries.

The index is disposable: markdown is the source of truth and the database
can be regenerated from it at any time.
"""

from __future__ import annotations

import hashlib
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
CREATE TABLE IF NOT EXISTS entry_themes (
    entry_id INTEGER NOT NULL,
    theme TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_themes_theme ON entry_themes (theme);
CREATE TABLE IF NOT EXISTS source_meta (
    name TEXT PRIMARY KEY,
    signature TEXT NOT NULL
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
            conn.executemany(
                "INSERT INTO entry_themes (entry_id, theme) VALUES (?,?)",
                [(cur.lastrowid, t) for t in entry.themes],
            )
        conn.commit()
        return conn.execute("SELECT count(*) FROM entries").fetchone()[0]
    finally:
        conn.close()


def source_signature(path: Path) -> str:
    """A content fingerprint of a source — changes on any add, edit, or remove.

    Per source, the cheapest *correct* signal: a single file is its mtime+size;
    a managed journal is its ``JOURNAL.md`` (touched by every managed write or
    refresh — correct by contract, no walk); a raw indexed directory is a hash
    over every ``.md`` (path + mtime + size), which catches edits *and*
    deletions that a max-mtime heuristic would miss.
    """
    if path.is_file():
        st = path.stat()
        return f"f:{st.st_mtime_ns}:{st.st_size}"
    journal_md = path / "JOURNAL.md"
    if journal_md.exists():
        st = journal_md.stat()
        return f"m:{st.st_mtime_ns}:{st.st_size}"
    h = hashlib.sha256()
    for f in sorted(path.rglob("*.md")):
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f}\0{st.st_mtime_ns}\0{st.st_size}\0".encode())
    return "d:" + h.hexdigest()[:16]


def write_signatures(db_path: Path, signatures: dict[str, str]) -> None:
    """Record each source's signature in the index (call right after build)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO source_meta (name, signature) VALUES (?, ?)",
            list(signatures.items()),
        )
        conn.commit()
    finally:
        conn.close()


def read_signatures(db_path: Path) -> dict[str, str]:
    """Source signatures stored at last build. {} for a pre-signature/foreign
    DB (which then reads as stale and triggers a rebuild)."""
    conn = sqlite3.connect(db_path)
    try:
        return {name: sig for name, sig in conn.execute("SELECT name, signature FROM source_meta")}
    except sqlite3.OperationalError:
        return {}
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
        if journal:
            sql += " AND e.journal = ?"
            params.append(journal)
        if theme:
            sql += " AND e.id IN (SELECT entry_id FROM entry_themes WHERE theme = ?)"
            params.append(theme)
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
    caller proposes the results for confirmation.
    """
    query = _fts_or_query(text)
    if not query:
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT t.theme AS theme FROM "
            "(SELECT entries_fts.rowid AS id, bm25(entries_fts) AS rank FROM entries_fts "
            " WHERE entries_fts MATCH ? ORDER BY rank LIMIT ?) hit "
            "JOIN entry_themes t ON t.entry_id = hit.id",
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
                "SELECT t.theme AS theme, e.journal AS journal, count(*) AS entries "
                "FROM entry_themes t JOIN entries e ON e.id = t.entry_id "
                "GROUP BY t.theme, e.journal "
                "UNION ALL "
                "SELECT '(unthemed)' AS theme, journal, count(*) AS entries "
                "FROM entries WHERE id NOT IN (SELECT entry_id FROM entry_themes) "
                "GROUP BY journal "
                "ORDER BY entries DESC"
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
            sql += " AND id IN (SELECT entry_id FROM entry_themes WHERE theme = ?)"
            params.append(theme)
        if journal:
            sql += " AND journal = ?"
            params.append(journal)
        sql += " GROUP BY month ORDER BY month"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
