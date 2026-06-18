# Architecture

ai-journal turns plain-markdown work journals into a queryable system without
taking ownership of the data away from the user. This document describes the
components and how data flows through them. For the rationale behind these
choices, see `ARCHITECTURE_DECISIONS.md`; for exact formats, see
`SPECIFICATION.md`.

## System Overview

```text
                 journals.toml (config: name, path, mode)
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  managed journal   indexed journal    indexed journal
  (entries/YYYY-MM) (file or dir,      (file or dir,
        │            read-only)         read-only)
        │ store.load_managed  │ parser/intake (in place)
        └────────┬────────────┴──────────┘
                 ▼
          indexer (SQLite + FTS5, disposable)
                 ▼
        ┌────────┴────────┐
        ▼                 ▼
   MCP server (stdio)   CLI (ai-journal)
   search/get/add/...   scan/migrate/reindex/search/refresh/serve
```

## Components

| Module | Responsibility |
|--------|----------------|
| `model.py` | `Entry` dataclass, slugs, duplicate-identity hashing |
| `parser.py` | Extract dated entries from heterogeneous markdown; filename-date fallback for archive eras |
| `intake.py` | Read-only scan of an existing journal: counts, date ranges, duplicates, orphans (`IntakeReport`) |
| `migrate.py` | Apply a migration (messy → managed layout); regenerate views (`refresh_views`) |
| `store.py` | Managed-journal I/O: load entries with frontmatter, write new entries, `load_source` dispatch |
| `indexer.py` | Build/query the SQLite FTS5 index: `search`, `list_themes`, `entries_over_time` |
| `config.py` | `journals.toml` loading; default config/db paths |
| `server.py` | MCP stdio server — thin layer over the library |
| `cli.py` | Command-line entry points — thin layer over the library |

Dependency direction: `server.py` and `cli.py` depend on everything;
library modules depend only downward (`store`/`intake`/`migrate` → `parser` →
`model`). Nothing imports `server.py` or `cli.py`.

## Journal Modes

- **managed** — ai-journal owns the layout: one entry per file under
  `entries/YYYY-MM/`, YAML frontmatter, generated index (`JOURNAL.md`) and
  per-theme views (`themes/*.md`). Writes happen only through
  `store.write_entry` (or migration).
- **indexed** — read-only. Entries are parsed in place (any of the supported
  header formats) and appear in cross-journal queries. The files are never
  modified or restructured. For journals with their own working conventions.

## Data Flow: the Three Paths

**Capture** (`add_entry` tool → `store.write_entry`): writes a canonical entry
file, then `migrate.refresh_views()` regenerates the index/theme views, then
the search index is rebuilt. One call leaves everything consistent.

**Query** (`search_journal` etc. → `indexer`): tools hit only the SQLite
index. If the index is missing it is rebuilt from sources on first use; it
can be deleted at any time without losing anything.

**Intake** (`scan` → report; `migrate --apply` → managed layout): scan is
always read-only and produces the dry-run report. Apply writes canonical
entries, deduplicates (longest body wins, themes merged), moves every original
file into `attic/` preserving relative paths, sweeps emptied directories, and
writes `migration-report.md` recording every dedup decision.

## Trust Boundaries

- The index database lives outside the journals
  (`~/.local/share/ai-journal/index.db`) and is never the source of truth.
- `get_entry` refuses paths outside configured journal roots.
- Indexed sources are opened read-only by convention; no code path writes to
  them.
