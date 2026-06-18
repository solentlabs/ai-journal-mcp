# Releasing ai-journal

A release is `git tag` → automated publish. No manual build-and-upload.

Prerequisite (one-time, done separately — not part of this procedure): the
GitHub repo and the PyPI trusted publisher exist.

## Cut a release

1. Bump `version` in `pyproject.toml`.
2. `git tag vX.Y.Z && git push --tags`.
3. `.github/workflows/release.yml` builds with hatchling and publishes to PyPI
   via trusted publishing — triggered by the tag, nothing typed by hand.

CI (lint, format, types, docs, tests) runs on every push and PR via
`.github/workflows/ci.yml`; the tag just adds the publish step.
