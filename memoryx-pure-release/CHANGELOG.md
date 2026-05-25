# Changelog

All notable changes to MemoryX are documented in this file.

## [Unreleased]

### Added
- P11 cognitive guard: claim verification against MemoryX evidence
- LESSON policy enforcement: allow/warn/block/require_dry_run/require_tool_verification
- Narrative reflection: synthesize task/opinion/lesson/claim into periodic reflections
- Guarded generation: CognitiveGuard for answer + action verification
- REST /v1/cognitive/verify-answer, /v1/cognitive/evaluate-action, /v1/cognitive/narrative-reflection

## [1.1.0-rc1] - 2026-05-23

### Added
- Cognitive LESSON memory flow with feedback propagation and learning engine
- Entity timeline engine via `entity_memory_links` (replaces metadata_json LIKE)
- REST API hardening: unified error format, `/live` and `/ready` probes
- Docker HEALTHCHECK against `/live` endpoint
- Prometheus-compatible metrics for REST, retrieval stages, LESSON, and MCP
- Retrieval session isolation and LESSON retrieval boost
- P8 observability: trace-id propagation, middleware, stage timing instrumentation
- P9 benchmark baseline: scale dataset generator and benchmark runner
- LESSON trigger index consistency check and repair tool
- SQLite busy retry policy with exponential backoff and jitter
- Production selfcheck tooling with CI gate
- MCP tool observability
- E2E test suite: REST, retrieval, MCP, benchmark, Docker smoke

### Changed
- REST PATCH now routes through versioned `update_memory_versioned`
- Retrieval engine supports `session_id`, `include_lessons`, `include_global`
- `store_memory` uses `BEGIN IMMEDIATE` atomic transaction for memories + versions + audit
- MCP server accepts `embedding_manager` parameter
- Dockerfile entrypoint unified to `uvicorn memoryx.api.rest_app:app`
- `vector_json` marked deprecated; LanceDB is primary vector backend
- SelfEditor routes through `update_memory_versioned` for version preservation

### Fixed
- P0 schema consistency: unified `id` primary keys, `active_state TEXT`
- Legacy `memory_id`/`entity_id` reference drift across modules
- Session isolation gap in retrieval engine
- Missing `scope` column in memories schema
- Observability engine `subject_id` column compatibility
- Schema migration foreign key references for opinion_shifts and lesson_evidence

### Known Warnings
- `async_safety`: async_weights uses documented async/thread boundary (no shared asyncio state)
- `SelfEditor` SQL builder uses controlled column whitelist
- `SelfEditor.apply` contains direct UPDATE (routed through versioned repository path)

---

## [1.0.0] - Initial Release
- SQLite WAL storage with FTS5
- Hybrid retrieval: semantic + keyword + temporal + entity + episodic
- Memory palace spatial organization
- MCP server with memoryx_search and memoryx_feedback tools
- Self-editing memory with preview/apply
- Event-driven hook system with queue persistence
