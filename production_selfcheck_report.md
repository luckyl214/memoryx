# MemoryX Production Self-Check Report

- Root: `/home/lucky/memoryx`
- Python: `3.12.3 (main, Mar 23 2026, 19:04:32) [GCC 13.3.0]`
- Started: `2026-05-23T10:43:20.358078+00:00`
- Finished: `2026-05-23T10:43:24.214831+00:00`
- Duration: `3.857s`
- Worst severity: **ERROR**

## Counts

| Severity | Count |
|---|---:|
| FATAL | 0 |
| ERROR | 3 |
| WARN | 4 |
| INFO | 21 |

## Production readiness

❌ Not production-ready by this suite.

## Findings

| Severity | Check | Status | Path | Message |
|---|---|---|---|---|
| ERROR | `retrieval_static_contract` | `fail` | `memoryx/retrieval/engine.py` | Retrieval engine lacks session_id support; session-level isolation is likely missing. |
| ERROR | `retrieval_static_contract` | `fail` | `memoryx/retrieval/engine.py` | Retrieval engine does not appear to boost or include LESSON memories. |
| ERROR | `source_schema_consistency` | `fail` | `` | Source contains SQL/schema references incompatible with detected schema. |
| WARN | `async_safety` | `warn` | `` | Daemon thread detected in async path; verify no shared asyncio state. |
| WARN | `self_editor_static_contract` | `warn` | `memoryx/self_editor.py` | SelfEditor.apply contains UPDATE memories; verify it only appears in safe repository-backed paths. |
| WARN | `self_editor_static_contract` | `warn` | `memoryx/self_editor.py` | SelfEditor.apply builds UPDATE columns from changes dict; ensure column whitelist is enforced. |
| WARN | `source_schema_consistency` | `warn` | `` | Source contains suspicious active_state numeric usage. |
| INFO | `cognitive_static_contract` | `pass` | `` | Expected cognitive module files are present. |
| INFO | `cognitive_static_contract` | `pass` | `` | Feedback LESSON creation policy appears to handle propagated evidence. |
| INFO | `cognitive_static_contract` | `pass` | `` | Cognitive schema compatibility helpers are present. |
| INFO | `compileall` | `pass` | `` | memoryx/ compiles successfully. |
| INFO | `mcp_static_contract` | `pass` | `` | MCPServer does not appear to silently return empty vectors without controls. |
| INFO | `migrations_apply` | `pass` | `` | 2 migrations apply cleanly. |
| INFO | `project_layout` | `pass` | `` | Required MemoryX layout files are present. |
| INFO | `project_layout` | `pass` | `` | memoryx/cognitive/ exists. |
| INFO | `python_version` | `pass` | `` | Python version is 3.12.3. |
| INFO | `repository_static_contract` | `pass` | `` | store_memory appears transaction/version/audit aware. |
| INFO | `repository_static_contract` | `pass` | `` | Repository exposes update_memory_versioned(). |
| INFO | `retrieval_static_contract` | `pass` | `` | Retrieval engine mentions scope_filter and likely filtering logic. |
| INFO | `runtime_smoke` | `pass` | `` | Runtime repository/storage smoke test passed. |
| INFO | `schema_bootstrap` | `pass` | `` | db/schema.sql bootstraps a temporary SQLite database. |
| INFO | `schema_contract` | `pass` | `` | Core production tables are present. |
| INFO | `schema_contract` | `pass` | `` | memories primary identifier appears to be id. |
| INFO | `schema_contract` | `pass` | `` | entities identifier appears to be id. |
| INFO | `schema_contract` | `pass` | `` | memories.active_state type is TEXT. |
| INFO | `schema_contract` | `pass` | `` | Cognitive schema tables are present. |
| INFO | `secret_scan` | `pass` | `` | No obvious hardcoded secrets detected by built-in patterns. |
| INFO | `sqlite_capabilities` | `pass` | `` | SQLite and FTS5 are available. |

## Agent repair guidance

Fix all ERROR/FATAL findings first. Do not overwrite db/schema.sql, repository.py, or mcp_server.py from older patches; prefer additive migrations and compatibility adapters.
