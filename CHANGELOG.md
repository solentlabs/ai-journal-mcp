# Changelog

Notable changes per release. Format follows [Keep a Changelog](https://keepachangelog.com/);
versions follow [SemVer](https://semver.org/) (0.x: minor may break).

## 0.3.0 — 2026-07-07

### Fixed

- **Task ids are validated before touching the filesystem.** A path-like id
  (`../entries/…`) could previously escape `tasks/` and rewrite an arbitrary
  `.md` file — including journal entries — via `update_task`.
- **Stray rescue now compares bodies.** A hand-added JOURNAL.md entry sharing
  an existing entry's date and title but carrying new text was silently
  dropped on refresh; it is now rescued under a suffixed filename.
- **Malformed search queries raise a clear `ValueError`** (empty query,
  unbalanced quotes/parens, trailing operators) instead of crashing
  `search_journal` with a raw sqlite error.
- **A corrupt index file self-heals.** Garbage in `index.db` now reads as
  stale and triggers a rebuild instead of wedging every tool call.
- **One malformed entry or task file no longer wedges the journal** — it is
  skipped with a warning naming the file; everything else keeps loading.
- **A rejected `update_task` no longer writes an orphaned reflection entry**
  (validation now runs before the entry write).
- **`init` escapes quotes/backslashes** when writing `journals.toml`, and
  rejects control characters (a newline in a name would corrupt the config).
- **Skipped malformed files are reported in-band**, not just to stderr:
  `add_entry`/`reindex` append a WARNING naming the file, `list_tasks`
  appends a warning row, and CLI `refresh`/`reindex` print them — a broken
  file must never read as a deleted entry or task.
- **A 0.2.0-era index rebuilds on upgrade** (schema version stamp) instead of
  crashing the new tag filter with "no such table".
- **Indexed-mode staleness is mode-aware:** a read-only journal whose tree
  happens to contain an `entries/` folder is fingerprinted over everything it
  actually indexes, not just `entries/`.
- **Hand-made task ids stay reachable:** ids may start with `_` or `-`
  (anything `list_tasks` shows can be fetched and updated).
- **Entry writes work on filesystems without hard links** (exFAT, some
  network mounts) via an exclusive-create fallback.
- **`serve` error messages tell the truth:** "install the [server] extra"
  only when `mcp` is actually absent; an incompatible installed `mcp` is
  named as such; anything else keeps its real traceback.
- **CLI `reindex` loads tasks only from managed journals**, and intake scans
  skip `tasks/` — no double-indexed task files from raw directories.
- **`refresh` on a nonexistent path is a true no-op** — it no longer
  materializes the typo'd directory tree.

### Changed

- **Concurrency-safe by construction** (multiple MCP sessions + CLI on one
  journal): all writes are atomic (temp file + rename), new entry files are
  claimed exclusively (same-title races land in two files), task updates and
  view regeneration serialize on a per-journal lock, and index rebuilds are
  built aside and swapped in so concurrent readers never see a partial
  database.
- **Hand edits under `entries/` are picked up.** The managed-journal
  staleness signature now hashes `entries/` and `tasks/` directly instead of
  trusting `JOURNAL.md`'s mtime.
- **CLI `reindex` indexes tasks** for managed roots, matching the server.

### Added

- `entries_over_time(tag=…)` — frequency-over-time for tag-labelled entries
  (the "receipts" workflow, UC8).
- Entry tags are searchable (`search_journal` matches an entry's tags even
  when the word is absent from the prose).
- `py.typed` marker — the package's annotations are visible to mypy/pyright
  downstream.

## 0.2.0 — 2026-06-29

### Added

- **Task graduation:** `update_task(status="done", reflection=…)` also writes
  a dated journal entry from the task and links the two — the bridge from
  planned-future to completed-past.
- **Tasks are indexed:** `search_journal` spans entries *and* tasks (each row
  carries `kind`); a task's tags and status are searchable.
- PyPI badges and a pip-install quickstart in the README.

## 0.1.0 — 2026-06-27

Initial release: journal engine, MCP stdio server, and CLI.

- Managed and indexed journal modes over plain markdown
  (`entries/YYYY-MM/`, YAML frontmatter, generated `JOURNAL.md` +
  `themes/*.md` views).
- Capture (`add_entry`), recall (`search_journal`, `get_entry`,
  `list_themes`, `entries_over_time`, `suggest_themes`), and intake
  (`scan` / `migrate --apply` with attic preservation; multi-source
  `consolidate` with verified archives).
- Mutable task kind (`add_task` / `update_task` / `list_tasks` /
  `get_task`) with priorities, blockers, and entry links.
- SQLite FTS5 disposable index with content-signature staleness detection;
  `init` scaffolding; bundled capture/maintenance skills.
- Published as `ai-journal-mcp` (PyPI rejected `ai-journal` as too similar
  to an existing project).
