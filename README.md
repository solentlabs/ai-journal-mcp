# ai-journal

**A local MCP server for journaling, organizing, and recalling your work.**
Capture what each session taught you, let it organize into a clean, queryable
structure, then recall and analyze the whole archive — recurring patterns, past
lessons, blog-post material. Plain markdown stays the source of truth, and
nothing leaves your machine.

> Status: pre-alpha, under active development. Not yet on PyPI.

## The problem

You journal the hard-won lessons — the debugging pattern, the process failure,
the "this is a blog post" moment. Then they vanish. Not because you didn't
write them down, but because a journal you can't interrogate is **write-only
memory**: the insight is in there somewhere, in a file too big to reread, and
the pattern recurs anyway because nothing surfaced it at the moment you needed
it.

Naming a pattern in your journal doesn't prevent the next instance — but being
able to *recall* it does. That recall is the whole point, and it's what plain
markdown files alone can't give you.

## What it feels like

Ask your journal a real question, mid-work, from the same LLM session you're
already in:

> **You:** "What do I keep relearning about AI-assisted development?"
>
> **Claude (via ai-journal):** *searches across months of entries, pulls the
> seven that recur on the theme, and synthesizes the through-line* — "You've
> hit 'tests are an uneven safety net' three times since April; here are the
> entries and the common trigger…"

Or capture without breaking flow:

> **You:** "Journal that — the bit about auditing every artifact when a
> hypothesis dies, not just the one with a test."
>
> *ai-journal writes `entries/2026-04/30-when-a-hypothesis-dies.md` with
> themes and blog angles, regenerates the index views, and rebuilds search —
> one call, everything consistent.*

## What it does

Three capabilities, one local MCP server:

1. **Journal** — capture however suits the moment: dump the whole session, jot
   a single lesson, or hand it a rough list to clean up. The `add_entry` tool
   takes freeform text and files it as a canonical entry (one per file,
   `entries/YYYY-MM/DD-slug.md`, with `themes`, `tags`, and `blog_angles`) — no
   format discipline required. Prefer to write entries by hand? ai-journal
   reads what's already there as-is.
2. **Organize** — themes are metadata, not folders, so one entry can carry
   several and no themed file grows without bound. The index and per-theme
   views are generated, never hand-edited, so the structure can't rot back into
   a megafile. Bringing a mess? `scan` reports what a migration would do;
   `migrate --apply` rewrites a sprawling journal into the clean layout —
   originals preserved in `attic/`, every dedup decision logged, **no data loss,
   ever**. (The first run absorbed 1,460 entries across 340 files spanning three
   format eras.)
3. **Recall & analyze** — full-text + structured search across one or many
   journals (`search_journal`, `entries_over_time`, `list_themes`, `get_entry`),
   filtered by theme, journal, or date range. Surface recurring patterns, find
   unused blog material, trace when a problem first appeared. This is the
   payoff: the journal as raw material for posts, talks, and not repeating old
   mistakes.

## Your data stays yours

- **Markdown is the source of truth.** The SQLite + FTS5 index is disposable —
  delete it anytime, it rebuilds from your files. Nothing is locked in a
  database you don't control.
- **It runs locally.** An MCP stdio server; your journal never leaves your
  machine.
- **It doesn't demand ownership of every source.** Register a journal as
  `indexed` and ai-journal reads and searches it in place but never rewrites
  it — ideal for a journal that already has its own conventions. `managed`
  journals are the ones it maintains for you. Both are searchable together, so
  cross-domain patterns ("what was I learning in engineering the week I learned
  X in deal research?") stop being invisible.

## Quickstart

```bash
git clone https://github.com/solentlabs/ai-journal && cd ai-journal
./scripts/setup.sh          # Python 3.11+: creates .venv, installs the tool
```

Register your journals in `~/.config/ai-journal/journals.toml`:

```toml
[[journal]]
name = "technical"
path = "~/journal"
mode = "managed"            # ai-journal owns the layout

[[journal]]
name = "deal-research"
path = "~/research/deals"
mode = "indexed"            # read-only; searched but never rewritten
```

Wire it into Claude Code as an MCP server:

```bash
claude mcp add ai-journal -- ai-journal serve
```

Querying happens through the server (it builds and refreshes the index for
you). The CLI handles intake and maintenance directly:

```bash
ai-journal scan ~/old-journal            # dry-run intake report
ai-journal migrate ~/old-journal --apply # rewrite into the managed layout
ai-journal refresh ~/journal             # regenerate JOURNAL.md + theme views
```

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/USE_CASES.md](docs/USE_CASES.md) | What the product is for, case by case |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, data flow, journal modes, trust boundaries |
| [docs/SPECIFICATION.md](docs/SPECIFICATION.md) | Entry format, journals.toml, parser rules, tool/CLI contracts |
| [docs/ARCHITECTURE_DECISIONS.md](docs/ARCHITECTURE_DECISIONS.md) | The "why" behind each design choice |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Open work, ordered: release, product, hardening, exploratory |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Dev environment setup, make targets, tooling, troubleshooting |

## Development

```bash
./scripts/setup.sh   # Python 3.11+: creates .venv, installs the package + dev tools
make check           # lint + format-check + type-check + tests (the pre-push gate)
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full guide.

## License

MIT © Solent Labs™
