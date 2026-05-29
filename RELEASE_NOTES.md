# MemoryX v2.0.0

**Stable release promoted from v2.0.0-rc.2.**
**Previous release candidates:** [v2.0.0-rc.2](https://github.com/luckyl214/memoryx/releases/tag/v2.0.0-rc.2) · [v2.0.0-rc.1](https://github.com/luckyl214/memoryx/releases/tag/v2.0.0-rc.1)

**Status**: FATAL=0, ERROR=0, WARN=3, E2E=6/6, Core=9/9

## What's New

### Cognitive Memory System
- **LESSON memory flow**: feedback → propagation → LESSON creation → retrieval boost
- **Entity timeline**: via `entity_memory_links` instead of metadata_json LIKE
- **Self-editing**: versioned preview/apply with audit trail

### Production Hardening
- **REST API**: unified error format, `/live` and `/ready` probes, PATCH uses versioned writes
- **Docker**: HEALTHCHECK on `/live`, unified uvicorn entrypoint
- **Observability**: Prometheus metrics for REST, retrieval stages, LESSON, MCP
- **Trace context**: automatic X-Trace-Id propagation and response echo

### Performance
- **Lesson trigger index**: consistent sub-10ms matching at 1000+ LESSON scale
- **SQLite busy retry**: exponential backoff with jitter for concurrent writes
- **Benchmark baseline**: scale dataset generator and benchmark runner

### Quality Gates
- **E2E tests**: 6 tests covering REST, retrieval, MCP, Docker, benchmark
- **Production selfcheck**: FATAL/ERROR gate for CI
- **Core cognitive tests**: 9 tests for LESSON, timeline, self-editing

## Installation

```bash
pip install memoryx==2.0.0
# Or from source:
git clone https://github.com/YOUR_GITHUB_USERNAME/memoryx
cd memoryx && pip install -e ".[dev]"
```

## Quick Start

```bash
cp .env.example .env  # edit your_api_key_here
uvicorn memoryx.api.rest_app:app --host 0.0.0.0 --port 8080
curl http://localhost:8080/live
```

## Known Warnings (3)
- async_weights uses documented async/thread boundary
- SelfEditor uses controlled column whitelist for SQL
- SelfEditor UPDATE paths routed through versioned repository

## Full Changelog
See [CHANGELOG.md](CHANGELOG.md)
