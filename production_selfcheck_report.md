# MemoryX Production Self-Check Report

- Root: `/home/lucky/memoryx`
- Python: `3.12.3 (main, Mar 23 2026, 19:04:32) [GCC 13.3.0]`
- Started: `2026-05-23T16:00:36.770114+00:00`
- Finished: `2026-05-23T16:00:39.333996+00:00`
- Duration: `2.564s`
- Worst severity: **WARN**

## Counts

| Severity | Count |
|---|---:|
| FATAL | 0 |
| ERROR | 0 |
| WARN | 3 |
| INFO | 24 |

## Production readiness

✅ Production-ready by this suite.

## Findings

| Severity | Check | Status | Path | Message |
|---|---|---|---|---|
| WARN | `async_safety` | `warn` | `` | Daemon thread detected in async path; verify no shared asyncio state. |
| WARN | `self_editor_static_contract` | `warn` | `memoryx/self_editor.py` | SelfEditor.apply contains UPDATE memories; verify it only appears in safe repository-backed paths. |
| WARN | `self_editor_static_contract` | `warn` | `memoryx/self_editor.py` | SelfEditor.apply builds UPDATE columns from changes dict; ensure column whitelist is enforced. |
| INFO | `cognitive_static_contract` | `pass` | `` | Expected cognitive module files are present. |
| INFO | `cognitive_static_contract` | `pass` | `` | Feedback LESSON creation policy appears to handle propagated evidence. |
| INFO | `cognitive_static_contract` | `pass` | `` | Cognitive schema compatibility helpers are present. |
| INFO | `compileall` | `pass` | `` | memoryx/ compiles successfully. |
| INFO | `mcp_static_contract` | `pass` | `` | MCPServer does not appear to silently return empty vectors without controls. |
| INFO | `migrations_apply` | `pass` | `` | 5 migrations apply cleanly. |
| INFO | `project_layout` | `pass` | `` | Required MemoryX layout files are present. |
| INFO | `project_layout` | `pass` | `` | memoryx/cognitive/ exists. |
| INFO | `python_version` | `pass` | `` | Python version is 3.12.3. |
| INFO | `repository_static_contract` | `pass` | `` | store_memory appears transaction/version/audit aware. |
| INFO | `repository_static_contract` | `pass` | `` | Repository exposes update_memory_versioned(). |
| INFO | `retrieval_static_contract` | `pass` | `` | Retrieval engine mentions session_id. |
| INFO | `retrieval_static_contract` | `pass` | `` | Retrieval engine mentions scope_filter and likely filtering logic. |
| INFO | `retrieval_static_contract` | `pass` | `` | Retrieval engine appears lesson-aware. |
| INFO | `runtime_smoke` | `pass` | `` | Runtime repository/storage smoke test passed. |
| INFO | `schema_bootstrap` | `pass` | `` | db/schema.sql bootstraps a temporary SQLite database. |
| INFO | `schema_contract` | `pass` | `` | Core production tables are present. |
| INFO | `schema_contract` | `pass` | `` | memories primary identifier appears to be id. |
| INFO | `schema_contract` | `pass` | `` | entities identifier appears to be id. |
| INFO | `schema_contract` | `pass` | `` | memories.active_state type is TEXT. |
| INFO | `schema_contract` | `pass` | `` | Cognitive schema tables are present. |
| INFO | `secret_scan` | `pass` | `` | No obvious hardcoded secrets detected by built-in patterns. |
| INFO | `source_schema_consistency` | `pass` | `` | No fatal legacy SQL/schema references detected. |
| INFO | `sqlite_capabilities` | `pass` | `` | SQLite and FTS5 are available. |

## Agent repair guidance

Fix all ERROR/FATAL findings first. Do not overwrite db/schema.sql, repository.py, or mcp_server.py from older patches; prefer additive migrations and compatibility adapters.
