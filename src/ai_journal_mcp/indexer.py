"""SQLite + FTS5 index over journal entries.

The index is disposable: markdown is the source of truth and the database
can be regenerated from it at any time.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path

from .model import Entry
from .tasks import Task

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


def _checked_fts_query(query: str) -> str:
    """Sanitize a user query and reject invalid FTS5 syntax with a ValueError.

    FTS5 only reports syntax errors (unbalanced parens, trailing AND, empty
    string) at MATCH time, as sqlite3.OperationalError. Probe a scratch table
    with the live schema's columns so the caller gets a clear error naming the
    query instead of a raw exception from the middle of a search.
    """
    sanitized = _sanitize_fts_query(query)
    if not sanitized:
        raise ValueError("search query is empty")
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE q USING fts5(title, body)")
        probe.execute("SELECT 1 FROM q WHERE q MATCH ?", (sanitized,))
    except sqlite3.OperationalError as exc:
        raise ValueError(f"invalid search query {query!r}: {exc}") from None
    finally:
        probe.close()
    return sanitized


# Bumped whenever SCHEMA changes shape. Stored as PRAGMA user_version at build
# time; read_signatures treats any other value as "no signatures", so an index
# built by an older release reads as stale and rebuilds instead of crashing the
# first query that touches a table it doesn't have.
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    journal TEXT NOT NULL,
    date TEXT NOT NULL,
    title TEXT,
    theme TEXT,
    source TEXT NOT NULL,
    line INTEGER NOT NULL,
    body TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'entry'
);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, body, content='entries', content_rowid='id'
);
CREATE TABLE IF NOT EXISTS entry_themes (
    entry_id INTEGER NOT NULL,
    theme TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_themes_theme ON entry_themes (theme);
CREATE TABLE IF NOT EXISTS entry_tags (
    entry_id INTEGER NOT NULL,
    tag TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_tags_tag ON entry_tags (tag);
CREATE TABLE IF NOT EXISTS source_meta (
    name TEXT PRIMARY KEY,
    signature TEXT NOT NULL
);
"""


def build_index(
    db_path: Path,
    entries: list[tuple[str, Entry]],
    tasks: list[tuple[str, Task]] | None = None,
    signatures: dict[str, str] | None = None,
) -> int:
    """(journal_name, entry) pairs + optional (journal_name, task) pairs -> fresh
    index. Tasks are indexed alongside entries so they are searchable; their
    tags and status are folded into the FTS body so a query like "blog" surfaces
    a task tagged ``blog``. Returns total row count.

    The index is built in a temp file and swapped in with os.replace, so a
    concurrent reader always sees a complete database — never a missing table
    mid-rebuild. Pass ``signatures`` (computed *before* loading the sources, so
    a write racing the build reads as stale, not fresh) to store them in the
    same transaction."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.parent / f".{db_path.name}.{os.getpid()}.tmp"
    try:
        count = _populate(tmp_path, entries, tasks, signatures)
        os.replace(tmp_path, db_path)  # success only — a failed build never replaces the live index
        return count
    finally:
        tmp_path.unlink(missing_ok=True)


def _populate(
    tmp_path: Path,
    entries: list[tuple[str, Entry]],
    tasks: list[tuple[str, Task]] | None,
    signatures: dict[str, str] | None,
) -> int:
    tmp_path.unlink(missing_ok=True)
    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        for journal, entry in entries:
            theme = entry.themes[0] if entry.themes else None
            cur = conn.execute(
                "INSERT INTO entries (journal, date, title, theme, source, line, body, kind) "
                "VALUES (?,?,?,?,?,?,?, 'entry')",
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
            # tags folded into the searchable body (the entries table keeps the
            # raw body) so "ai-drift" finds an entry tagged ai-drift — symmetric
            # with tasks below
            fts_body = "\n".join(filter(None, [entry.body, " ".join(entry.tags)]))
            conn.execute(
                "INSERT INTO entries_fts (rowid, title, body) VALUES (?,?,?)",
                (cur.lastrowid, entry.title or "", fts_body),
            )
            conn.executemany(
                "INSERT INTO entry_themes (entry_id, theme) VALUES (?,?)",
                [(cur.lastrowid, t) for t in entry.themes],
            )
            conn.executemany(
                "INSERT INTO entry_tags (entry_id, tag) VALUES (?,?)",
                [(cur.lastrowid, t) for t in entry.tags],
            )
        for journal, task in tasks or []:
            # tags + status folded into the searchable body so they're findable
            fts_body = "\n".join(filter(None, [task.body, " ".join(task.tags), task.status]))
            cur = conn.execute(
                "INSERT INTO entries (journal, date, title, theme, source, line, body, kind) "
                "VALUES (?,?,?,?,?,?,?, 'task')",
                (
                    journal,
                    task.updated or task.created or "",
                    task.title,
                    None,
                    str(task.path),
                    0,
                    task.body,
                ),
            )
            conn.execute(
                "INSERT INTO entries_fts (rowid, title, body) VALUES (?,?,?)",
                (cur.lastrowid, task.title or "", fts_body),
            )
        conn.executemany(
            "INSERT OR REPLACE INTO source_meta (name, signature) VALUES (?, ?)",
            list((signatures or {}).items()),
        )
        conn.commit()
        return conn.execute("SELECT count(*) FROM entries").fetchone()[0]
    finally:
        conn.close()


def source_signature(path: Path, mode: str = "managed") -> str:
    """A content fingerprint of a source — changes on any add, edit, or remove.

    A single file is its mtime+size. A ``managed`` journal hashes what is
    actually indexed — every ``.md`` under ``entries/`` and ``tasks/`` (path +
    mtime + size) — so a hand edit, add, or delete under ``entries/`` reads as
    stale just like a write that went through the tool (markdown is the source
    of truth, however it got there). Any other directory hashes every ``.md``
    recursively — an *indexed* source is scanned wholesale, so its signature
    must cover the whole tree even when an ``entries/`` folder happens to
    exist inside it. A stat walk costs ~1ms per thousand files.
    """
    if path.is_file():
        st = path.stat()
        return f"f:{st.st_mtime_ns}:{st.st_size}"

    def _hash(files: list[Path]) -> str:
        h = hashlib.sha256()
        for f in files:
            try:
                st = f.stat()
            except OSError:
                continue
            h.update(f"{f}\0{st.st_mtime_ns}\0{st.st_size}\0".encode())
        return h.hexdigest()[:16]

    entries_dir, tasks_dir = path / "entries", path / "tasks"
    if mode == "managed" and entries_dir.is_dir():
        files = sorted(entries_dir.rglob("*.md"))
        if tasks_dir.is_dir():
            files += sorted(tasks_dir.glob("*.md"))
        return "m:" + _hash(files)
    return "d:" + _hash(sorted(path.rglob("*.md")))


def read_signatures(db_path: Path) -> dict[str, str]:
    """Source signatures stored at last build. {} for a pre-signature, foreign,
    corrupt, or older-schema DB (which then reads as stale and triggers a
    rebuild — the index is disposable, so a stale or truncated file must heal
    itself, not wedge the server or crash on a table it doesn't have)."""
    conn = sqlite3.connect(db_path)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            return {}
        return {name: sig for name, sig in conn.execute("SELECT name, signature FROM source_meta")}
    except sqlite3.DatabaseError:
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
            SELECT e.journal, e.date, e.title, e.theme, e.source, e.line, e.kind,
                   snippet(entries_fts, 1, '**', '**', ' … ', 12) AS snippet,
                   bm25(entries_fts) AS rank
            FROM entries_fts
            JOIN entries e ON e.id = entries_fts.rowid
            WHERE entries_fts MATCH ?
        """
        params: list = [_checked_fts_query(query)]
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
                "FROM entries WHERE kind = 'entry' AND id NOT IN (SELECT entry_id FROM entry_themes) "
                "GROUP BY journal "
                "ORDER BY entries DESC"
            )
        ]
    finally:
        conn.close()


def entries_over_time(
    db_path: Path, theme: str | None = None, journal: str | None = None, tag: str | None = None
) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT substr(date,1,7) AS month, count(*) AS entries FROM entries WHERE kind = 'entry'"
        params: list = []
        if theme:
            sql += " AND id IN (SELECT entry_id FROM entry_themes WHERE theme = ?)"
            params.append(theme)
        if tag:
            sql += " AND id IN (SELECT entry_id FROM entry_tags WHERE tag = ?)"
            params.append(tag)
        if journal:
            sql += " AND journal = ?"
            params.append(journal)
        sql += " GROUP BY month ORDER BY month"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
