# Architecture Decisions

Distilled decisions and their rationale — the "why" behind the design.
For the full design see `ARCHITECTURE.md` and `SPECIFICATION.md`.

## Markdown is the source of truth; the index is disposable

**Decision:** All journal content lives in plain markdown files. The SQLite
FTS5 database is derived, lives outside the journal tree, and can be deleted
at any time.

**Rationale:** The user's journal must outlive this tool. Plain files are
greppable, diffable, syncable (OneDrive), and readable in fifty years. Making
the index disposable also makes the no-data-loss guarantee structural: no
write path can corrupt the journal through the database, and "rebuild from
scratch" is the recovery story for every index problem.

## Managed vs indexed journal modes

**Decision:** Each configured journal is either `managed` (ai-journal-mcp owns
the layout) or `indexed` (parsed in place, never written).

**Rationale:** Forced by a real case: the Staysail deal-research journal
already had working conventions (append-only, year archives, a sister
lessons.md). Migrating it would have destroyed a system that worked.
Cross-journal querying must not require ownership of every source.

## Themes are metadata, not storage location

**Decision:** An entry's themes live in its frontmatter as a list; per-theme
files are generated views. Storage is purely chronological
(`entries/YYYY-MM/`).

**Rationale:** Theme-named storage files were the original failure mode: the
journal this tool was born from had a 1 MB, 12,000-line `cable-modem-monitor.md`
because themed files grow without bound, and single-theme storage forces a
false choice for entries that belong to two themes (~10% in practice).
Monthly directories are bounded by time; themes-as-metadata gives the
pattern-finding lens without the megafile.

## One entry per file

**Decision:** The managed store is one markdown file per entry.

**Rationale:** Entries get stable addresses (path = date + slug), edits have
minimal blast radius, parsing is trivial, and a 1,400-entry journal stays
fast to load selectively. The alternative (sectioned megafiles) is exactly
what intake exists to clean up.

## Dedup keeps the longest body and merges themes

**Decision:** Migration groups **titled** entries by `(date, title-slug)`; the
longest body survives, group themes are unioned, every drop is logged, and
originals stay in `attic/`. **Title-less** entries group by `(date, exact
normalized-body hash)` instead — two different date-only session logs on the
same day are never merged, only byte-identical copies are.

**Rationale:** The observed duplication pattern was copy-on-archive (the old
rollover copied entries into themed files without removing the index copy),
where copies diverge by truncation, not contradiction — longest body is the
information-preserving choice. Title-less entries carry no title signal at
all, so "same day" alone is not identity — hence the exact-body rule for
them. Because originals are never deleted, a wrong dedup choice is
recoverable, which is what allows it to be automatic at all.

**Kept deliberately:** `migrate --apply` auto-merges the same-day same-title
"near duplicates" that the dry-run report flags for human review, without a
per-group confirmation step. The dry run *is* the review gate; adding an
interactive confirm loop would complicate the one-shot migration for a case
that is fully recoverable from `attic/` and logged per-decision in
`migration-report.md`.

## Attic over deletion

**Decision:** Intake/migration never deletes anything. Original files —
markdown or not — move to `attic/` with their relative paths intact.

**Rationale:** "No data loss" was a hard user constraint, and intake runs on
exactly the data people care most about (years of personal records). Disk is
cheap; trust is not. The user deletes the attic when satisfied, or never.

## LLM as format detective, code as scalpel (extraction specs)

**Decision:** Intake of arbitrary foreign formats leverages the LLM already
operating the MCP server — but only to *understand* the format, never to
*copy* the data. `discover` emits a read-only evidence report; the LLM
proposes an extraction spec (TOML: globs + date/time/title rules); the
migrator executes the spec deterministically, slicing original text
verbatim. The tool itself never calls an LLM (no API key, no network). The
spec is throwaway — recorded in `migration-report.md`, never persistent
config — and applying a migration stays CLI-only; the MCP surface
(`discover_journal`, `scan_source`) is read-only.

**Rationale:** Users configure existing journals in effectively infinite
ways, and regex-by-regex chasing can't keep up — but an LLM re-emitting
thousands of entry bodies through `add_entry` would silently paraphrase,
truncate, and drop at scale, violating the no-data-loss constraint in an
unverifiable way. Models are unreliable copiers but excellent format
detectives, so the split puts judgment where variety is infinite (one-shot,
human-reviewed migration) and keeps parsing reproducible — the index is
rebuilt from markdown constantly and must parse identically every time,
which also rules out persisting LLM parsing into indexed mode. Truly
unstructured remainders (a handful of orphans) can still go through
`add_entry` one at a time, where a human reviews each.

## FTS5 first, embeddings later (maybe)

**Decision:** Search is SQLite FTS5 (bm25 + snippets), in the standard
library. No embeddings, no vector store, no services.

**Rationale:** At journal scale (thousands of entries), ranked full-text
search answers most real questions, requires zero infrastructure, and keeps
the install light. The consumer is usually an LLM that can reformulate
queries — which compensates for the literal-matching weakness that embeddings
would solve. Embeddings remain a future option behind the same tool surface.

## MCP server as the primary interface, CLI as the secondary

**Decision:** The product interface is an MCP stdio server (FastMCP); the CLI
exists for scripting, maintenance, and non-Claude use. Both are thin layers
over the same library modules.

**Rationale:** The end goal is "ask questions of my journal from any
session" — that's an LLM-native workflow, and MCP makes the tools available
in every Claude Code session at user scope. Keeping logic out of the server
layer keeps it testable without an MCP client and keeps the CLI honest.

## Generated views are never hand-edited

**Decision:** `JOURNAL.md` and `themes/*.md` are regenerated wholesale by
`refresh_views()`; hand edits are explicitly unsupported.

**Rationale:** The original journal decayed because index maintenance was
manual ("move entries older than 7 days" — a policy that died within months
and left an 18,683-line index). Removing the human from view maintenance
removes the decay mode. Recency in views is computed relative to the newest
entry, not the wall clock, so regeneration is deterministic.

## Python, stdlib-lean, packaging conventions

**Decision:** Python ≥3.11, hatchling, MIT, `pyyaml` as the only required
dependency, `mcp` behind the `[server]` extra, and the dev toolchain (ruff,
mypy, pytest, pre-commit) behind `[dev]`.

**Rationale:** Matches the existing Solent Labs PyPI packages (har-capture,
ai-launcher) so release tooling and muscle memory transfer. The `[server]`
split keeps `pip install ai-journal-mcp` light for CLI-only users. The floor was
raised 3.10 → 3.11 once it surfaced that `config.py` imports the stdlib
`tomllib` (3.11+) unconditionally: the package would have `ImportError`d on
3.10 despite advertising it. Requiring 3.11 made the metadata honest without
adding a `tomli` backport for a version the code never actually ran on.

## Ruff-only tooling, mypy authority, fixtures over inline tests

**Decision:** One tool per job, configured once in `pyproject.toml`: Ruff is
the sole linter *and* formatter (replacing black + isort + flake8), mypy is the
type-check authority, line length is 120, and test data is fixture-based —
format samples under `tests/fixtures/`, a `make_journal` factory for filesystem
behavior, `parametrize` tables for pure logic, and inline data only for
in-memory units.

**Rationale:** A single source of truth means the editor, the `Makefile`, CI,
and the pre-commit hook cannot disagree — there is no `setup.cfg`, `.flake8`,
or `mypy.ini` to drift out of sync. Ruff-only (over black + ruff) drops a
dependency and a second formatter for no loss; the repo was greenfield when the
formatter was adopted, so normalizing every file cost zero churn against
history. Line length 120 and the markdownlint/cspell calibration (e.g. MD060
off — it misreads table separator rows as "compact" and flags every data row)
match the sibling Cable Modem Monitor repo, so house style transfers across
projects. Fixtures-over-inline is the same instinct as intake itself: real
inputs belong in discoverable files, not pasted into test bodies — so adding a
newly-seen journal format is a two-file drop with no test-code change, which is
what the `CLAUDE.md` "parser changes ship with a fixture" rule means in
practice.

## Tasks are a mutable kind; entries stay append-only

**Decision:** Journal entries are append-only and immutable (what happened).
Tasks are a separate, **mutable** kind (what to do next) — `status`, `priority`,
and `blocked_by` change over time — stored one markdown file per task under
`<journal>/tasks/`, rewritten in place. Tasks link to entries (`entries:`) for
context; entries never point at tasks.

**Rationale:** A `status` field on entries was the first idea, but it fought the
model — entries are append-only, status is mutable. Splitting by mutability
resolves it cleanly: two kinds, different rules, neither bent. The driving use
case is a running task list kept alongside the journal (priorities, items
waiting on others) where picking a task back up should surface the entry that
gave it context (UC7). Markdown stays the source of truth for both; a task is
just the mutable file. Tasks are mutated by loading their files directly, but
they are **also indexed alongside entries** so `search_journal` spans the whole
archive — see "Tasks are indexed too" below.

A **blog-topic backlog** is the same kind, not a separate tool: a blog topic is
a task tagged `blog` — title + the entry that sparked it + a done flag —
so `list_tasks(tag="blog")` is the sortable, checkable list. (A read-only
"blog-angle miner" was prototyped and dropped: it couldn't mark items complete
or curate a list, which is the whole point. The `blog_angles` entry field stays
as the in-the-moment seed; promoting a seed to a tracked topic is one
`add_task`.)

**Tasks are planned future; entries are completed past — graduation is a one-way
bridge on `update_task`, not a separate verb.** Completing a task is itself just
an update (`status → done`), so the bridge rides on `update_task` rather than its
own tool: pass a `reflection` and it also writes a dated entry from the task
(title from the task, body the reflection) and links the two. It is deliberate,
not automatic, because the relationship isn't one-to-one — most checkboxes ("fix
CI flake") don't deserve a permanent entry, and a single work session usually
finishes several tasks but yields one entry. Auto-converting every completion
would bury the journal's signal (lessons, patterns) in noise. So
`update_task(status="done")` alone quietly closes a trivial task, while
`update_task(status="done", reflection=…)` graduates the ones worth remembering.
The two kinds stay distinct (tasks keep `status`/`priority`/`blocked_by`; entries
stay immutable and themed); only this bridge crosses between them, future → past.

## Tasks are indexed too (reverses a 0.1.0 choice)

**Decision:** Tasks are written into the same SQLite/FTS index as entries, so
`search_journal` returns both (each result carries `kind` = `entry` | `task`). A
task's `tags` and `status` are folded into its searchable body, so a query like
"blog" surfaces a task tagged `blog`. The managed-journal staleness signature
folds in a hash of `tasks/`, so adding, editing, or completing a task rebuilds
the index on the next query. Entry-only views (`list_themes`,
`entries_over_time`) stay entry-only.

**Rationale:** 0.1.0 deliberately kept tasks out of the index ("loaded from
their files directly"). In real use that was wrong: a user files blog ideas,
plans, and reference docs as tasks, then *can't find them* — `search_journal`
and the journal views act empty, defeating the recall the tool exists for. The
index is disposable and rebuilt wholesale, so adding tasks to it costs nothing
structurally and makes "one place, searchable" actually true. Tasks remain
mutated through their files (the index never owns them); it only mirrors them
for search. CLI `reindex` indexes tasks the same way — the CLI must not build
a poorer index than the server would.

## Deliberately out of 0.1.0

**Decision:** Two would-be features are intentionally not built for 0.1.0, and
the parser is extended only reactively:

- **Incremental index updates.** The SQLite/FTS index is rebuilt in full
  whenever a source's content signature changes. That is correct and fast at
  journal scale (thousands of entries); an incremental updater is a premature
  optimization, deferred until profiling shows the full rebuild is a real
  bottleneck.
- **Speculative intake formats.** The parser handles the formats actually seen
  (the founding journal's three eras). New formats are added when one is
  encountered — each with a fixture reproducing it — not guessed at ahead of
  demand.
- **Cross-journal correlation queries.** No dedicated tool. The valuable form —
  entries from several journals in a shared time window (UC4) — is already
  served by composing `search_journal` (journal + date filters) with
  `entries_over_time`. Statistical temporal correlation, by contrast, is a
  quantified-self technique for numeric streams; on a handful of prose entries
  per period it isn't meaningful. Prior art agrees: PKM tools surface
  cross-source patterns through a shared date axis and shared tags, not
  correlation math.

(Semantic search / embeddings is excluded separately; see "FTS5 first,
embeddings later".)

**Rationale:** "Build it right or cut it." The index is *complete* as a full
rebuild, and there is nothing concrete to build for formats not yet seen — so
both are terminal decisions, not deferred backlog. Recorded so the exclusions
are deliberate and don't quietly reappear as open work.

## Concurrency: lock the read-modify-writes, make everything else atomic

**Decision:** Every write goes through `fsio.py`: finished files are written
to a temp path and `os.replace`d (entries, tasks, views, `journals.toml`, the
index); new entry files are claimed with an atomic exclusive create (two
sessions writing the same date+title land in two files); and the two
read-modify-write sequences — task updates and view regeneration — run under
an exclusive flock on `<journal>/.lock`. The index is never mutated in place:
a rebuild produces a complete temp database and swaps it in, with staleness
signatures computed *before* loading sources and committed in the same
transaction. No daemon, no global lock, no lock for readers.

**Rationale:** The real deployment is several MCP sessions (one process each)
plus the CLI on one journal. Atomicity alone fixes crash-truncation and
readers seeing half-written files, but not lost updates: `get_task` → think →
`update_task` is a wide window in which another session's field changes would
be silently dropped, and tasks have no attic — that loss is unrecoverable,
which is what justifies a lock. Scoping the lock to one journal's mutations
keeps readers lock-free and the failure surface small; flock self-releases on
process death, so a crashed session can't wedge the journal. Windows has no
flock — there the lock degrades to a no-op and the atomic-write guarantees
remain (documented, acceptable for a POSIX-first tool).

## Known limitations, accepted deliberately

Recorded so they read as decisions, not oversights. Each is cut until real
usage says otherwise:

- **Exotic code fences can confuse the parser** (four-plus backticks, `~~~`
  inside a backtick fence). Fix ships with a fixture when a real journal
  hits it — per the reactive-parser rule above. Noted in SPECIFICATION §3.
- **`get_entry` on a single-file journal exposes the file's siblings** (the
  containment root is the file's parent directory). Single-user local tool;
  configure a dedicated directory if it matters. Noted in ARCHITECTURE.
- **Search snippets can mis-highlight when the match is in a folded-in tag**
  (FTS positions are computed over body+tags, snippets render from the body).
  Cosmetic; the hit itself is correct.
- **Unix-convention paths on Windows** (`~/.config`, `~/.local/share`).
  Works via `expanduser()`; `platformdirs` is not worth a dependency until a
  Windows user exists.
- **A frontmatter `date:` carrying a time component is stored verbatim**
  (`YYYY-MM-DDTHH:MM:SS`), which makes that entry compare oddly against
  `since`/`until` day bounds. Tool-written entries never do this.
- **Atomic writes are not fsync'd.** `os.replace` guarantees readers and
  process crashes never see a truncated file; a *power loss* in the seconds
  after a write can still lose that write (not corrupt others). Journals are
  prose captured interactively — the user notices a missing entry and
  re-adds it — and per-write fsync would tax every capture to guard a rare
  event with a benign failure mode. Revisit only if real data loss occurs.

## Named `ai-journal-mcp` (was `ai-journal`)

**Decision:** The package, PyPI distribution, CLI command, import package, and
repo are all `ai-journal-mcp` / `ai_journal_mcp`. The on-disk config and data
directories follow: `~/.config/ai-journal-mcp/`, `~/.local/share/ai-journal-mcp/`.

**Rationale:** The project was originally `ai-journal`, chosen for family
coherence with `ai-launcher` and `ai-monitor`, search obviousness, and rejecting
nautical names (shipslog, soundings) as too cute. At PyPI registration `ai-journal`
was rejected as too similar to an existing project — the similarity guard is
broader than the plain availability check that read clear on 2026-06-11. Only the
*distribution* name strictly had to change, but a split (publish `ai-journal-mcp`,
keep everything else `ai-journal`, the scikit-learn/sklearn pattern) was rejected
in favour of one name everywhere: the small per-package consistency beats matching
the `ai-*` siblings, and `-mcp` accurately signals what the package is. The cost
was a one-time rename while there were no external users and a single local config
dir to move.
