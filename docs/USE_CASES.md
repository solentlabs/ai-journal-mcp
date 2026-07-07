# Use Cases

What ai-journal-mcp is for, expressed as the situations it serves. Each use case
names the tools involved; contracts are in `SPECIFICATION.md`.

## UC1 — Capture an insight without leaving the work

**Situation:** Mid-session, something worth keeping surfaces: a debugging
pattern, a process failure, a "this could be a blog post" moment.

**Flow:** The user tells their LLM session to journal it (or invokes a
capture skill). The agent calls `add_entry` with title, body, themes, and
optional blog angles. The entry file, index views, and search index are
consistent after the single call.

**Why it matters:** Insights fade within hours. Capture has to be cheaper
than not capturing, from any session, with no format discipline required of
the human.

## UC2 — Ask questions of your own history

**Situation:** "What do I keep relearning about contributor management?"
"Which insights from March have blog potential I haven't used?" "When did I
first hit this bug pattern?"

**Flow:** `search_journal` (ranked FTS with theme/journal/date filters) →
`get_entry` for full text. `entries_over_time` and `list_themes` give the
shape of activity; the LLM synthesizes across hits. An entry's `tags` are
folded into its searchable text, so a free-text query for a tag surfaces the
entries that carry it even when the word never appears in the prose — the same
way task tags are searchable.

**Why it matters:** This is the end goal — the journal as raw material for
blog posts, talks, self-reflection, and not repeating old mistakes. A journal
you can't interrogate is write-only memory.

## UC3 — Absorb an existing, messy journal

**Situation:** A user has years of journaling in whatever shape it grew
into: an 18,000-line index file, themed megafiles, ad-hoc archive
directories, three header conventions, duplicated entries.

**Flow:** `scan` produces a dry-run report (counts, date ranges, duplicates,
orphan files needing triage). The user reviews; `migrate --apply` produces
the managed layout with every original preserved in `attic/` and every dedup
decision logged in `migration-report.md`.

**Why it matters:** This is the adoption path. Nobody starts clean; the tool
must meet data where it is. (The first production run absorbed 1,460 entries
across 340 files spanning three format eras — see ARCHITECTURE_DECISIONS for
what it taught the design.)

## UC4 — Query across separate journals

**Situation:** Work lives in more than one journal — e.g. a technical
engineering journal and an investment deal-research journal with its own
conventions.

**Flow:** Both are registered in `journals.toml`; the deal-research journal
stays `indexed` (read-only, untouched). `search_journal` spans both;
`journal=` filters to one. "What was I learning in engineering the same week
I was learning X in deal research?" becomes answerable.

**Why it matters:** Cross-domain patterns are invisible when each journal is
an island, and the tool must not demand ownership of every source to include
it.

## UC5 — Keep the journal from decaying again

**Situation:** Manual maintenance policies die. The index file regrows; theme
files balloon; the structure rots back toward UC3.

**Flow:** All writes go through `add_entry`/`write_entry`, which regenerate
the views; `refresh` exists for bulk edits. Generated views are never edited
by hand. Storage is bounded by month, so no file grows without limit.

**Why it matters:** The original journal decayed precisely because its
upkeep was a human chore. Structural prevention beats scheduled cleanup.

## UC6 — Someone else adopts it

**Situation:** Another developer wants the same capture/query/intake loop
for their own journals.

**Flow:** `pip install ai-journal-mcp`, write `journals.toml`, `claude mcp add
ai-journal-mcp -- ai-journal-mcp serve`, run `scan`/`migrate` on whatever they have.
Shippable Claude Code skills (capture + maintenance) package the habit, not
just the engine.

**Status:** Engine, server, CLI, intake, consolidation, and the bundled
capture/maintenance skills are built.

## UC7 — Track tasks with the context behind them

**Situation:** Alongside the journal there's a running task list — some items
top priority, some waiting on others — and picking one back up later means
re-finding the entry that explains *why* it matters.

**Flow:** `add_task`/`update_task`/`list_tasks` manage a mutable task kind
(status, priority, `blocked_by`). `list_tasks` returns the ready-to-pick-up set
(blockers done) and each task's linked `entries`; `get_entry` on those pulls the
context. Tasks are markdown files under `tasks/`, separate from append-only
entries.

**Why it matters:** Insights and intentions live together. The journal already
holds *what you learned*; tasks add *what's left to do about it*, linked so the
reasoning is one hop away when you resume.

## UC8 — Build a case from recurring evidence ("receipts")

**Situation:** The same friction keeps happening — a meeting pattern, a
process gap, a class of bug. Each instance alone is an anecdote; collected
and counted, they're the evidence behind a process-improvement proposal or a
"this is where to focus" call.

**Flow:** Capture each instance as it happens (`add_entry`) under a
consistent label — a theme (`meeting-overrun`) or a tag; `suggest_themes`
keeps the label converging instead of fragmenting. When it's time to make
the case: `search_journal` retrieves every instance (tags are searchable),
`get_entry` pulls the details, and `entries_over_time(theme=…)` or
`entries_over_time(tag=…)` produces the frequency evidence — "nine times in
five months" — that turns anecdotes into a pattern.

**Why it matters:** Patterns are invisible at the moment of capture and
undeniable in aggregate. The journal already pays this cost one entry at a
time; the label + count is what converts it into leverage at work.
