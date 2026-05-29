# MemoryX 2.0 Public RC2

MemoryX `v2.0.0-rc.2` is a follow-up public release candidate focused on public release hygiene and install-test correctness.

## Status

- Release: MemoryX 2.0 Public RC2
- Tag: `v2.0.0-rc.2`
- Commit: `233be51`
- Type: prerelease
- Latest stable: false
- Stability: release candidate, not final stable `v2.0.0`

## What changed since RC1

RC2 fixes public install and archive hygiene issues found during the 23.14 public release audit.

Fixes:

- Repaired 2 test source syntax errors.
- Added FastAPI dependency coverage for the default dev test path.
- Isolated optional LanceDB backend tests behind an explicit optional dependency boundary.
- Removed stale tracked release artifacts.
- Added export-ignore coverage for internal tooling and artifact patterns.
- Replaced private local path examples with `$MEMORYX_HOME`.
- Revalidated fresh archive installation from the release asset.

## Validation

- collect-only: 328 collected / 0 errors
- full pytest: 328 passed / 1 skipped / 0 failed
- skipped test: optional LanceDB backend boundary
- import smoke: PASS
- repository smoke: PASS
- ReleaseGate: 9/9 PASS
- archive hygiene: PASS
- private path scan: clean
- secret scan: clean
- fresh archive install smoke: PASS

## Upgrade note

Use RC2 instead of RC1 for public install testing. RC1 remains available as the original public RC history point, but RC2 is the recommended release candidate for external evaluation.

## Install

```bash
git clone https://github.com/luckyl214/memoryx.git
cd memoryx
git checkout v2.0.0-rc.2
pip install -e ".[dev]"
pytest
```

Expected result:

```text
328 passed / 1 skipped / 0 failed
```

For optional LanceDB backend validation:

```bash
pip install -e ".[dev,lancedb]"
pytest tests/test_lancedb_vector_store.py -q
```

## Release classification

This is a public release candidate. Do not treat it as final stable `v2.0.0`.
