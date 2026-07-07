# Releasing ai-journal-mcp

A release is `git tag` → automated publish. No manual build-and-upload.

Prerequisite (one-time, done separately — not part of this procedure): the
GitHub repo and the PyPI trusted publisher exist.

## Cut a release

1. Bump `__version__` in `src/ai_journal_mcp/__init__.py` (the single version
   source — `pyproject.toml` reads it via hatch's dynamic version).
2. Move the `Unreleased` section of `CHANGELOG.md` under the new version.
3. Merge to `main` and confirm CI is green on the merge commit — the tag
   should only ever point at `main`.
4. `git tag vX.Y.Z && git push --tags`.
5. `.github/workflows/release.yml` verifies the tag matches `__version__`,
   runs the test suite on exactly that ref, builds with hatchling, and
   publishes to PyPI via trusted publishing — nothing typed by hand.
6. Verify: `pip install "ai-journal-mcp[server]==X.Y.Z"` in a fresh venv, run
   `ai-journal-mcp --help`, and check the PyPI project page renders with
   working links.

CI (lint, format, types, docs, tests) runs on every push and PR via
`.github/workflows/ci.yml`; the tag adds the verify + publish steps.
