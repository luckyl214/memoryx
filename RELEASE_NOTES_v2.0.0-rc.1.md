# MemoryX 2.0 Public RC1

MemoryX `v2.0.0-rc.1` is the first public release candidate for the MemoryX 2.0 memory system.

This release is published from a clean, reproducible baseline after the 23.x clean-baseline reconstruction cycle.

## Release status

- Status: Public release candidate
- Tag: `v2.0.0-rc.1`
- Commit: `20ae3db`
- Tag type: Annotated tag
- Stability: RC / prerelease, not final stable `v2.0.0`

## Validation

ReleaseGate result: 9/9 PASS

- `clean_status`: PASS
- `collect_only`: PASS, 317 collected
- `pytest_full`: PASS, 317 passed / 0 failed
- `core_smoke`: PASS
- `foreign_key_check`: PASS
- `forbidden_deps`: PASS
- `skip_xfail`: PASS
- `secret_scan`: PASS
- `package_hygiene`: PASS

Archive validation:

- Archive size: 642K
- Risky files: 0
- Risky directories: 0
- Secret scan: clean (no real secrets)

## Reconstruction summary

The 23.x release reconstruction started from the real clean baseline rather than a dirty-worktree result.

Baseline reconstruction outcome:

- Failed tests reduced from 55 to 0
- Test coverage increased from 299 tests to 322 tests
- Core fresh-clone verification: 317 passed / 0 failed
- Database-layer errors cleared
- SQLite foreign-key violations cleared
- No skip/xfail-based failure masking

## Major repaired areas

- SQLite schema drift and migration compatibility
- Canonical `id` / public `memory_id` alias compatibility
- SQL column aliasing discipline
- NOT NULL payload defaults
- JSON binding safety
- Foreign-key integrity
- Retrieval/search scope persistence
- Active-state contract normalization
- REST API auth runtime-key behavior
- MCP vector query handling
- Hook lifecycle compatibility
- ReleaseGate restoration
- Archive and open-source hygiene

## Compatibility notes

This release keeps backward-compatible public aliases where required.

Important contracts:

- `MemoryRecord.id` is canonical
- `MemoryRecord.memory_id` is retained as public / legacy alias
- `active_state` values are normalized as:
  - `active`
  - `archived`
  - `superseded`
  - `quarantined`
- REST auth is enabled only when a real API key is configured
- Placeholder or empty API keys do not enable auth
- SQLite foreign keys remain enforced

## Open-source hygiene

The release archive excludes runtime and private artifacts, including reports, local artifacts, logs, traces, runtime databases, `.env`, and vector-store runtime directories.

Secret scan and package hygiene checks passed before publication.

## Installation

```bash
git clone <repository-url>
cd <repository>
git checkout v2.0.0-rc.1
pip install -e ".[dev]"
pytest
```

Expected result:

```text
317 passed / 0 failed
```

## Release classification

This is a release candidate for public testing and integration review.

Do not treat this tag as final stable `v2.0.0`. Stable promotion should happen only after external install/smoke validation and a separate final release gate.
