# Specification

Exact formats and contracts. Architecture is in `ARCHITECTURE.md`; rationale
in `ARCHITECTURE_DECISIONS.md`.

## 1. Canonical Entry File (managed journals)

Path: `<root>/entries/YYYY-MM/DD-<slug>.md`

- `slug` = lowercased title, non-alphanumerics collapsed to `-`, max 60 chars
  (word-boundary truncated). Collisions get `-2`, `-3`, … suffixes.

```markdown
---
date: 'YYYY-MM-DD'
title: The Title            # may be null for date-only entries
themes:                     # zero or more; metadata, not storage location
- development-practices
tags: []                    # free-form keywords; always written (may be empty)
blog_angles:                # optional, only when present
- "Candidate Blog Title"
source: JOURNAL.md:123      # migration provenance only; absent on new entries
---

<markdown body>
```

Frontmatter is YAML between `---` fences, always first in the file. A file
under `entries/` without a `date` key is ignored by the loader.

## 1a. Task File (managed journals)

Path: `<root>/tasks/<id>.md`, where `id` is the slug of the title (same slug
rules; collisions get `-2`, … suffixes). Unlike entries, tasks are **mutable** —
the file is rewritten in place on update.

```markdown
---
title: Cut the 0.1.0 release
status: open                 # open | blocked | done
priority: high               # high | medium | low
blocked_by:                  # task ids this one waits on
- configure-pypi
entries:                     # entry paths giving this task its context
- entries/2026-06/19-release-design.md
tags:                        # optional free-form labels for grouping/filtering
- release                    # e.g. a topic backlog ("blog"), a project, a context
created: '2026-06-19'
updated: '2026-06-19'
---

<notes>
```

A task is *ready* when its status isn't `done` and every `blocked_by` task is
`done`. Tasks reference entries for context; entries never reference tasks.

## 2. journals.toml

Default location: `~/.config/ai-journal-mcp/journals.toml`.

```toml
[[journal]]
name = "technical"        # unique; used in tool calls and index rows
path = "~/projects/personal/journal"   # dir (managed/indexed) or file (indexed)
mode = "managed"          # "managed" | "indexed" (default "indexed")
```

Only `managed` journals accept `add_entry`. A `managed` path must contain an
`entries/` directory (created by migration or first write).

## 3. Parser Rules (intake / indexed sources)

An entry header is a markdown heading whose text starts with an ISO date:

- `## YYYY-MM-DD` … `#### YYYY-MM-DD`, 1–4 hashes
- optional `:` then optional title: `### 2026-06-11: Title`
- date-only headers (`## 2026-06-11`) produce `title = null`

Body = everything until the next dated header at any level. Internal
headings that don't start with a date (`### The Situation`) do not split
entries. Lines inside ``` or ~~~ fences are never headers. Trailing
horizontal rules and blank lines are stripped. Invalid dates
(`2026-13-45`) are not headers. Content before the first dated header is
ignored. (Known limitation, accepted until seen in real data: fences of
four-plus backticks, or a `~~~` line inside a backtick fence, can mis-toggle
the fence state and split an entry — if encountered, the fix ships with a
fixture per the parser rule in `CLAUDE.md`.)

**Filename-date fallback:** a file with no dated headers, located at
`YYYY-MM/DD-*.md`, becomes a single entry dated from its path; its title is
the first heading line if present, else null; body is the remainder.

## 3a. Extraction Spec (foreign formats)

Existing journals arrive in arbitrary layouts the default rules can't know.
An **extraction spec** is a TOML file of `[[source]]` rules that tells
scan/migrate where entries live and how dates, times, and titles are encoded.
It is typically proposed by an LLM from the `discover` evidence report, then
executed deterministically — original text is sliced verbatim, never
re-generated. The spec is **throwaway**: used for one migration, recorded
verbatim in `migration-report.md`, never persistent config.

```toml
[[source]]
paths = ["entries/**/*.md"]      # globs relative to the journal root
header = '^###\s+\[(?P<date>\d{4}-\d{2}-\d{2})(?:\s+(?P<time>\d{2}:\d{2}))?\]\s*(?P<title>.*?)\s*$'

[[source]]
paths = ["receipts/*.md"]
filename_date = '(?P<date>\d{4}-\d{2}-\d{2})'   # searched in the file name
date_format = "%Y-%m-%d"         # strptime format; this is the default
```

Contract:

- Per file, the first `[[source]]` whose glob matches wins. Globs must be
  relative, without `..`.
- `header` is a per-line regex with named groups — `date` required, `time`
  and `title` optional. It replaces the default header pattern; every other
  parser rule of §3 (body extent, fences, internal headings, invalid dates)
  applies unchanged. A captured `time` survives into the canonical entry's
  frontmatter.
- If `header` yields nothing and `filename_date` finds a date in the file
  name, the whole file becomes one entry (title from its first heading, as
  in the filename-date fallback). A rule needs `header` and/or
  `filename_date`.
- Files a rule matches but cannot date, and markdown no glob covers, stay
  **orphans** in the dry-run report — nothing is guessed.
- Unknown keys, bad regexes, a missing `(?P<date>…)` group, or a bad
  `date_format` are `SpecError`s reported before anything runs.

**Discovery.** `discover` (CLI) / `discover_journal` (MCP) produce the
read-only evidence report the spec is written from: file-name patterns,
heading shapes (normalized to tokens like `### [YYYY-MM-DD HH:MM] Title`,
with counts and raw examples), frontmatter keys, and excerpts — plus the
spec schema and loop instructions. It makes no parsing decisions.

## 4. Intake Scan (read-only)

`scan_journal(root)` walks `*.md` recursively, skipping
`.git`, `.claude`, `attic`, `entries`, `tasks`, `themes`, `node_modules`.
With an extraction spec (`scan_journal(root, spec)`), the walk is driven by
the spec's globs instead, and only `.git`, `.claude`, `attic`,
`node_modules` are off limits — a foreign journal may keep data under
`entries/`. Produces:

- per-file entry counts, date ranges, line counts
- **orphans**: files with no extractable entries — listed with a one-line
  excerpt for triage (capped at 20 shown; the remainder is counted, never
  silently dropped)
- **exact duplicates**: same date + identical normalized body (sha256 of
  rstripped lines)
- **near duplicates**: same date + same 40-char title slug, different body

Root-level themed files contribute their stem as the entry's theme;
`JOURNAL.md` and archive-directory entries carry no theme.

## 5. Migration Apply

1. Dedup **titled** entries by `(date, title-slug[:40])`: longest body wins,
   themes are the union of the group's themes, every drop is recorded.
   **Title-less** entries dedup by `(date, exact normalized-body hash)` —
   two different date-only session logs on the same day are never merged.
2. Move original files (markdown and not) to `attic/<original relative
   path>`; sweep emptied directories bottom-up. (A non-markdown file sitting
   at the journal root is left in place — only scanned markdown and files
   inside swept subdirectories move.) Originals move **before** canonical
   files are written: with a spec, a canonical filename can equal an
   original's path, and the original must already be safe in `attic/`.
3. Write canonical entry files (§1) with `source` provenance; a captured
   header `time` lands in frontmatter.
4. Generate views (§6) and `migration-report.md` (counts + dedup table +
   the extraction spec verbatim, when one was used — its one durable record).

Invariant (tested): every non-duplicate body hash present before migration
exists in the managed store after; dropped duplicates remain in `attic/`.
Refusals: if `entries/` already exists (unless a spec is given — an explicit
statement that `entries/` is a foreign layout), and if the scan found zero
entries (applying would strip the journal into `attic/` and write nothing).

## 6. Generated Views (managed journals)

Regenerated by `refresh_views(root)` after any write — never hand-edited:

- `JOURNAL.md`: entries from the last 7 days (relative to the newest entry,
  not the wall clock) as links, plus per-month archive links with counts.
- `themes/<theme>.md`: one dated link per entry carrying that theme,
  newest first. Stale theme files are deleted on refresh.

**Stray rescue:** before regenerating, `refresh_views` parses JOURNAL.md for
hand-added dated entries (an agent following stale instructions may append
there). Any with a non-empty body not already in the store — matched by
(date, title-slug, **body hash**), so a stray that shares a stored entry's
date and title but says something new is still rescued — is written to
`entries/` first (filename suffixed on collision). Regeneration never
destroys text; rescue is idempotent.

## 7. Search Index

SQLite at `~/.local/share/ai-journal-mcp/index.db` (CLI accepts `--db`).
Tables: `entries` (journal, date, title, theme, source, line, body, `kind`),
`entries_fts` (FTS5, external content), `entry_themes` and `entry_tags`
(one row per label — the `theme=`/`tag=` filters and `list_themes` query
these, so *every* theme/tag on an entry is filterable, not just the first),
and `source_meta` (staleness signatures). Rebuilt from scratch on `reindex` —
built as a temp file and atomically swapped in; deleting or corrupting the
file is always safe (it reads as stale and rebuilds). `entries.theme` is the
entry's first theme. An entry's `tags` are folded into its searchable body
(the `entries.body` column keeps the raw body), so "ai-drift" matches an
entry tagged `ai-drift` even when the word is absent from the prose.

**Query sanitization.** `search` accepts FTS5 syntax (words, `"exact
phrases"`, `AND`/`OR`/`NOT`, parens). A bareword containing FTS5-special
characters (e.g. the hyphen in `fleet-relative`) is auto-quoted to match
literally rather than parse as syntax. An empty or syntactically invalid
query raises `ValueError` naming the query — never a raw sqlite error.

**Both kinds are indexed** — by the server *and* by CLI `reindex`. `kind` is
`entry` or `task`. Tasks from managed journals are indexed alongside entries
so `search_journal` spans them; a task's `tags` and `status` are folded into
its searchable body (so "blog" matches a task tagged `blog`), its `source` is
the task file, and its `date` is the task's `updated` (falling back to
`created`). Entry-only views (`list_themes`, `entries_over_time`) ignore tasks.

**Staleness self-healing (server only):** before serving a query, the server
compares each source's stored content signature against its current one,
rebuilding if any differs. A managed journal's signature is a hash over every
`.md` under `entries/` and `tasks/` (path + mtime + size), so a hand edit,
add, or delete is picked up exactly like a write that went through the tool;
a file source is its mtime+size; a raw indexed directory is a hash over its
`.md` files. Signatures are computed before sources are loaded and stored in
the same transaction as the build. A CLI-built index carries no signatures,
so the server treats it as stale and rebuilds on first use.

## 8. MCP Tool Surface

| Tool | Contract |
|------|----------|
| `search_journal(query, journal?, theme?, since?, until?, limit=10)` | FTS5 query syntax; date bounds inclusive `YYYY-MM-DD`; spans entries *and* tasks. Rows carry `journal`, `date`, `title`, `theme`, `source`, `line`, `kind` (`entry`/`task`), `snippet`, `rank` |
| `get_entry(source)` | Full file text; rejects paths outside configured journals |
| `add_entry(journal, title, body, themes?, tags?, blog_angles?, entry_date?)` | Managed journals only; writes entry, refreshes views, reindexes; returns the new path |
| `list_themes()` | Rows of `theme`, `journal`, `entries` (count); unthemed shown as `(unthemed)` |
| `suggest_themes(text, limit=5)` | Existing themes ranked by FTS similarity to `text`; suggestion only, writes nothing |
| `entries_over_time(theme?, journal?, tag?)` | Rows of `month`, `entries` (count), ascending; filter by theme, tag, or journal — the frequency evidence behind a recurring pattern (UC8) |
| `add_task(journal, title, body?, priority=medium, blocked_by?, entries?, tags?)` | Create a task (status `open`) in a managed journal; returns its id |
| `update_task(journal, task_id, status?, priority?, blocked_by?, entries?, body?, tags?, reflection?, themes?, entry_date?)` | Mutate a task in place (only passed fields change). Pass `reflection` to also graduate it into a dated journal entry — the planned-future → completed-past bridge: writes an entry (title from the task, body = `reflection`, optional `themes`) and links it back |
| `list_tasks(journal?, status?, priority?, tag?)` | Tasks, open/high-priority first; each carries `ready`, `tags`, and `entries` |
| `get_task(journal, task_id)` | Full task detail incl. `entries` to pull context via `get_entry` |
| `discover_journal(path)` | Read-only evidence report (§3a) about any directory — need not be configured. The LLM-side start of the intake loop |
| `scan_source(path, spec_toml?)` | Dry-run intake report (§4) for any directory; `spec_toml` is extraction-spec text (§3a). Read-only — applying a migration stays CLI-only |
| `reindex()` | Full rebuild from sources |

`body` is freeform: a whole-session dump, a single lesson, or a tidied-up
hand-written list are all valid — the tool imposes structure (path, frontmatter,
views), not a writing style. `title`, `themes`, `tags`, and `blog_angles` are
the only structured fields.

**Errors.** Every tool failure is a `ValueError` with an actionable message:

- unknown `journal` → names the configured journals; a non-`managed` journal
  passed to a write tool → "read-only"
- invalid task `status`/`priority` → lists the valid values; unknown
  `task_id` → "no task"; a path-like `task_id` (`../…`, separators) →
  "invalid task id"
- `get_entry` outside every configured journal root → "not inside a
  configured journal"
- empty or syntactically invalid FTS `query` → names the query
- invalid `entry_date` → the underlying ISO-format error

A missing `journals.toml` raises `FileNotFoundError` telling the user what to
create. In `journals.toml`, a duplicated `name` silently shadows (last wins)
and unknown keys are ignored.

**Malformed files.** A malformed entry or task file (unclosed frontmatter,
bad YAML, junk date) never wedges the journal and is never silently dropped:
the file stays untouched on disk, is skipped by loading, and the skip is
reported in-band — `add_entry` and `reindex` append a `WARNING:` line naming
the file, `list_tasks` appends a `{"warning": …}` row, and the CLI prints the
same. `get_task`/`update_task` on the broken file raise a `ValueError` naming
it.

## 9. CLI

| Command | Purpose |
|---------|---------|
| `init <path> [--name]` | Scaffold a new managed journal and register it in journals.toml |
| `discover <root>` | Read-only evidence report about an unfamiliar journal's layout (§3a) |
| `scan <root> [--spec <toml>]` | Dry-run intake report; `--spec` applies an extraction spec (§3a) |
| `migrate <root> [--apply] [--spec <toml>]` | Dry-run by default; apply per §5 |
| `consolidate <dest> --from <path>... [--apply]` | Consolidate sources into a fresh managed journal; dry-run by default |
| `reindex <roots...> --db <path>` | Build index from explicit paths |
| `search <query> --db <path> [--limit/--theme/--since/--until]` | Query an index |
| `refresh <root>` | Regenerate views per §6 |
| `serve` | Run the MCP stdio server (requires `ai-journal-mcp[server]`) |
