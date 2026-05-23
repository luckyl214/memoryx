# P8 Observability + E2E Gate

## What this adds

- Trace/session context via `contextvars`
- REST observability middleware
- Prometheus-compatible counters/histograms
- Retrieval total/stage timing wrapper
- MCP tool-call counters
- E2E tests for REST trace/error behavior, retrieval instrumentation, MCP instrumentation
- Benchmark threshold gate
- GitHub Actions workflow

## Wire into REST

In `memoryx/api/rest_app.py`, after `app = FastAPI(...)`:

```python
from memoryx.api.p8_bootstrap import install_p8_observability
install_p8_observability(app)
```

If your P7 app already installs error handlers, keep only one copy. The function is idempotent for middleware.

## Wire into retrieval

Where `HybridRetrievalEngine` is constructed:

```python
from memoryx.retrieval.observed import instrument_retrieval_engine

engine = HybridRetrievalEngine(repository=repository, vector_store=vector_store)
engine = instrument_retrieval_engine(engine)
```

For stricter stage metrics, call `observe_stage_async("semantic")`,
`observe_stage_async("keyword_fts")`, `observe_stage_async("graph")`,
`observe_stage_async("lesson_match")`, and `observe_stage_async("fusion")`
inside the actual stage methods.

## Wire into MCP

```python
from memoryx.mcp.observed import instrument_mcp_server

server = instrument_mcp_server(server, tool_names=["memoryx_search", "memoryx_feedback"])
```

Or decorate individual async tool handlers:

```python
from memoryx.mcp.observed import observe_mcp_tool

@observe_mcp_tool("memoryx_search")
async def memoryx_search(...):
    ...
```

## Run

```bash
pytest -q tests/e2e
python tools/e2e_gate.py --skip-docker
```

If Docker is available:

```bash
python tools/e2e_gate.py
```

## Metrics to expect

- `memoryx_rest_requests_total`
- `memoryx_rest_request_seconds`
- `memoryx_retrieval_stage_seconds`
- `memoryx_lesson_match_total`
- `memoryx_lesson_boost_score`
- `memoryx_feedback_events_total`
- `memoryx_mcp_tool_calls_total`
```
