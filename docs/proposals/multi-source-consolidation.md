# Multi-source consolidation

Status: **day-1 release scope**, design settled, not yet implemented. Once
built, the contracts move to `SPECIFICATION.md` and the rationale to
`ARCHITECTURE_DECISIONS.md`.

## What it does

One operation. Point ai-journal at **one or more source locations** and it:

1. reads every entry across all sources,
2. removes duplicates across them (longest body wins, themes merged),
3. writes canonical entries to a **new managed journal** at a path you name,
4. compresses **each source in place** into a `.tar.gz` that preserves its
   original folder tree, then removes the originals.

So scattered log/journal files across many folders become one clean managed
journal plus one tidy compressed archive per source — workspace cleaned up,
nothing lost. This **subsumes** the old in-place `migrate`: a single source is
just the N=1 case. Only the sources you explicitly name are touched.

## The flow

- **Dry-run (default):** a report of what *would* happen — per-source entry
  counts, cross-source duplicates, and same-date/same-title **conflicts**
  (different body) to review. Writes nothing.
- **`--apply`:**
  1. Write the deduplicated canonical entries to the fresh destination.
  2. For each source: build `<source>.tar.gz` (original tree preserved),
     **verify it reads back intact**, then remove the originals.
  3. Write a consolidation report: provenance, every dedup decision, and the
     archive manifest.

## No data loss (verified, not assumed)

Before any original is removed, assert that every source entry's normalized
`body_hash` is present in the managed store **or** the archive, and that the
archive is readable. Only then delete. Extends the existing
`test_migration_no_text_loss` guarantee to this path.

## Schema / provenance

- frontmatter `source` identifies the origin: `<source-name>::<relpath>:<line>`.
- When a duplicate is merged across sources, the kept winner's origin is the
  `source`; the full merge set (all origins, including dropped) goes in the
  report, not the frontmatter — the schema stays lean.

## Prerequisite: fix the untitled dedup over-merge

`Entry.identity` maps every title-less entry to `(date, "untitled")`, so
distinct same-date date-only logs collapse today. Multi-source multiplies these
collisions, so this lands first: dedup key becomes `(date, body_hash)` when an
entry has no title (exact-match only — distinct bodies stay distinct).

## Contracts (sketch; finalize in `SPECIFICATION.md` when built)

```text
scan_sources(specs)            -> ConsolidationReport
    entries tagged by source; duplicates; conflicts; orphans

apply_consolidation(report, dest)
    -> ConsolidationResult(written, dropped_duplicates, archives, loss_check)

CLI:
  ai-journal consolidate <dest> --from <path>[:name] [--from ...] [--apply]
  # dry-run by default; --apply writes
```

## Out of scope (v1)

- Merging into / updating an existing managed journal (fresh destination only).
- Auto-resolving same-date/title conflicts — the report flags them; the human
  decides.
