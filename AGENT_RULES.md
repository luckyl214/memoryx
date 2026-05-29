# MemoryX Agent Rules

MemoryX v2.0.0 stable is frozen.

## Absolute prohibitions

Agents must not:

- move, delete, recreate, or overwrite these tags:
  - v2.0.0
  - v2.0.0-rc.1
  - v2.0.0-rc.2
- edit GitHub release assets
- edit runtime data:
  - .env
  - runtime DB
  - logs
  - traces
  - vector stores
  - lancedb runtime directories
- disable SQLite foreign keys
- use INSERT OR IGNORE to hide parent-row / FK errors
- make schema or migration changes without explicit batch approval
- use pytest skip/xfail to clear release failures
- run git add .
- tag from a dirty worktree
- publish from a dirty worktree
- mix docs/hygiene changes with core logic fixes
- treat Hermes update failures as MemoryX failures without attribution

## Required workflow before any commit

1. Identify batch:
   - hotfix
   - patch
   - docs
   - hygiene
   - feature
2. Define allowed files.
3. Define forbidden files.
4. Run:
   - git status --short
   - python -m pytest --collect-only -q
   - python -m pytest -q
   - python scripts/run_memoryx_release_gate.py
5. If packaging changed, run archive hygiene.
6. Commit only explicit files.

## Stable release rule

v2.0.0 is immutable. Any fix must become:

- v2.0.1 for patch/hotfix
- v2.1.0-rc.1 for feature/minor work
