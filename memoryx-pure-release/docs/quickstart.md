# Quick Start

Get MemoryX running in under 10 minutes.

## Prerequisites
- Python 3.11+
- pip
- (Optional) LanceDB for vector search

## Install

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/memoryx
cd memoryx
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configure

```bash
cp .env.example .env
# Edit .env: replace your_api_key_here with your OpenAI-compatible API key
```

## Verify

```bash
python tools/memoryx_production_selfcheck.py --root .
```

Expected: `FATAL=0, ERROR=0`

## Start REST Server

```bash
uvicorn memoryx.api.rest_app:app --host 0.0.0.0 --port 8080
```

Test:
```bash
curl http://127.0.0.1:8080/live
curl http://127.0.0.1:8080/ready
curl http://127.0.0.1:8080/metrics
```

## Docker

```bash
docker build -t memoryx .
docker run --rm -p 8080:8080 memoryx
curl http://127.0.0.1:8080/live
```

## Run Tests

```bash
# Core cognitive tests
pytest -q tests/test_cognitive_learning.py tests/test_cognitive_timeline_opinion.py

# E2E tests
pytest -q tests/e2e/

# Full suite
pytest -q
```

## Create Your First Memory

```bash
curl -X POST http://127.0.0.1:8080/v1/memories \
  -H "Content-Type: application/json" \
  -d '{"content":"I prefer async Python for web services","memory_type":"PREFERENCE","importance_score":0.9}'
```

## Search

```bash
curl -X POST http://127.0.0.1:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Python preference","limit":5}'
```

## Next Steps
- [REST API Docs](docs/rest_api.md)
- [MCP Integration](docs/mcp.md)
- [Docker Deployment](docs/docker.md)
- [Observability](docs/observability.md)
