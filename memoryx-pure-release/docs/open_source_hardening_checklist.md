# MemoryX Open Source Hardening Checklist

This patch focuses on deployability, diagnosability, and regression resistance.

## Fixed / Added

- Dockerfile starts the REST API with Uvicorn on `0.0.0.0:8080`.
- systemd service uses the same REST entrypoint.
- REST PATCH writes through `MemoryRepository.update_memory_versioned()`.
- Uniform REST error envelope:
  `{"error": {"code": "...", "message": "...", "details": {...}}, "trace_id": "..."}`
- `/live` and `/ready` probes.
- Prometheus-compatible `/metrics` endpoint.
- `lesson_triggers` indexed table for LESSON matching.
- `entity_memory_links` table for entity timeline queries.
- Benchmark scripts for store and retrieval paths.

## Apply

```bash
cp -r . /path/to/memoryx
cd /path/to/memoryx
sqlite3 "$MEMORYX_DB_PATH" < db/migrations/011_open_source_hardening.sql
pytest -q tests/test_rest_hardening.py tests/test_lesson_policy_triggers.py
docker build -t memoryx:local .
docker run --rm -p 8080:8080 memoryx:local
curl -f http://127.0.0.1:8080/live
```

## Follow-up

- Wire `sync_lesson_triggers()` after every `LessonAbstractionEngine.create_lesson()` call.
- Add E2E tests for MCP + REST search with session and lesson matching.
- Expand metrics to include retrieval stage timings inside `HybridRetrievalEngine`.
