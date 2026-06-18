# Roadmap

Open items as of 2026-06-11, roughly ordered. Done work lives in git
history, not here.

## Release

- [ ] Create `solentlabs/ai-journal` on GitHub (pyproject URLs already point there)
- [ ] Publish `0.1.0` to PyPI — the name is verified free but unclaimed until
      first publish; this is the land grab
- [ ] Add `ai-journal` to `PYPI_PACKAGES` in `community/collect-metrics.sh`
      after publishing, so download stats join har-capture/ai-launcher dashboards

## Product

- [ ] Ship Claude Code skills inside the package (`skills/`): a **capture**
      skill (entry template, add_entry workflow) and a **maintenance** skill
      (refresh/reindex, health checks). Ken's personal insights-journal skill
      works but lives in his operations repo; UC6 (adoption by others) needs
      them bundled and journal-agnostic
- [ ] `ai-journal init <path>` — scaffold a new managed journal + config stanza
      without requiring a migration
- [ ] Theme suggestions on `add_entry` (offer existing themes when none given,
      based on FTS similarity to existing entries)
- [ ] Structured/updatable record kind alongside freeform insight entries.
      Driving use case: an upstream-contributions log (project, PR, target
      release, status). Three strains against the current model — (1) status
      is mutable ("merged → released") but entries are append-only, so updates
      mean hand-editing source markdown; (2) ledger fields live as prose, so
      you can't filter "merged but unreleased"; (3) a contribution is a record
      that may carry an insight, not an insight itself. Minimal version: a
      filterable `status` field the engine understands; fuller version: a
      second entry kind with declared fields. First example entry:
      2026-06/14-upstream-contribution-google-wifi-read-timeout-fix-ha-core.md
- [ ] Multi-source consolidation: gather entries from several sources into one
      fresh managed journal — dedup across sources, provenance in frontmatter,
      originals retired into a single compressed archive, dry-run then `--apply`.
      Design: `docs/proposals/multi-source-consolidation.md`

## Quality / hardening

- [ ] Staleness detection for directory-mode indexed sources (currently only
      managed JOURNAL.md and file sources are mtime-checked; see
      SPECIFICATION.md §7)
- [ ] Incremental index update on `add_entry` (full rebuild is fine at ~1k
      entries; will not be at 10k)
- [ ] `migrate` support for additional intake formats as they appear in the
      wild (current parser covers the three eras of the founding journal)

## Exploratory

- [ ] Embeddings/semantic search behind the same tool surface, if real query
      logs show FTS5 missing reformulation-resistant questions (see
      ARCHITECTURE_DECISIONS — FTS5 first)
- [ ] Blog-angle mining tool: surface unused `blog_angles` ranked by entry
      cluster size ("which insights keep recurring but were never written up")
- [ ] Cross-journal correlation queries (UC4: "what was I learning in
      engineering the same week as X in deal research")

## Housekeeping (Ken, not code)

- [ ] Initial commits: journal repo, this repo, operations repo (skill rewrite)
- [ ] Delete `attic/` and `~/backups/journals-backup-2026-06-11.tar.gz`
      whenever the migration is trusted — no deadline, they cost nothing
