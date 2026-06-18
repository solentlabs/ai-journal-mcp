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

**Decision:** Each configured journal is either `managed` (ai-journal owns
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

**Decision:** Migration groups entries by `(date, title-slug)`; the longest
body survives, group themes are unioned, every drop is logged, and originals
stay in `attic/`.

**Rationale:** The observed duplication pattern was copy-on-archive (the old
rollover copied entries into themed files without removing the index copy),
where copies diverge by truncation, not contradiction — longest body is the
information-preserving choice. Because originals are never deleted, a wrong
dedup choice is recoverable, which is what allows it to be automatic at all.

## Attic over deletion

**Decision:** Intake/migration never deletes anything. Original files —
markdown or not — move to `attic/` with their relative paths intact.

**Rationale:** "No data loss" was a hard user constraint, and intake runs on
exactly the data people care most about (years of personal records). Disk is
cheap; trust is not. The user deletes the attic when satisfied, or never.

## FTS5 first, embeddings later (maybe)

**Decision:** Search is SQLite FTS5 (bm25 + snippets), in the standard
library. No embeddings, no vector store, no services.

**Rationale:** At journal scale (thousands of entries), ranked full-text
search answers most real questions, requires zero infrastructure, and keeps
the install light. The consumer is usually an LLM that can reformulate
queries — which compensates for the literal-matching weakness that embeddings
would solve. Embeddings remain a roadmap option behind the same tool surface.

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
split keeps `pip install ai-journal` light for CLI-only users. The floor was
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

## Named `ai-journal`

**Decision:** Package and repo are `ai-journal`, joining `ai-launcher` and
`ai-monitor` as a product family.

**Rationale:** Family coherence, search obviousness, and a deliberate PyPI
land grab (name verified free 2026-06-11; unclaimed until first publish).
Nautical names (shipslog, soundings) were considered and rejected as too
cute for a tool meant for strangers to find.
