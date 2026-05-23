# P12.1 Hermes Perfection + FastAPI Lifespan + LLM Safety

## What this fixes

1. FastAPI REST app now supports `create_app()` and lifespan-managed resources.
2. `memoryx.api.rest_app:app` remains compatible with Uvicorn/Docker.
3. P11 routes resolve repository/retrieval dependencies lazily; no `repository=None` capture.
4. Conversation logs use the actual schema (`id`, not `log_id`) and FTS rowid joins.
5. REST metrics use canonical label helpers.
6. LLM Firewall adds prompt-injection, secret-like content, dangerous tool-call, and untrusted tool-output handling.
7. Hermes bridge returns context blocks and guard decisions to the host agent.

## Apply

```bash
cp -r /tmp/memoryx_p12_1/* .
sqlite3 "$MEMORYX_DB_PATH" < db/migrations/021_hermes_perfection.sql
pytest -q tests/p12
python tools/p12_1_extreme_gate.py
```

## FastAPI factory

```python
from memoryx.api.app_factory import create_app

app = create_app(repository=repo, query_api=api, auto_open=False)
```

Production keeps:

```bash
uvicorn memoryx.api.rest_app:app --host 0.0.0.0 --port 8080
```

## Hermes bridge

```python
from memoryx.hermes_bridge import HermesMemoryBridge

bridge = HermesMemoryBridge(repository=repo, query_api=api)

ctx.memoryx_bridge = bridge
memoryx.plugin.register(ctx)
```

The host can consume hook return values:

- `on_user_message` -> `context_block`
- `on_tool_call` -> `decision`, `requires_user`, `should_block`, `guard_block`
- `on_assistant_response` -> claim/safety guard block
- `on_session_end` -> narrative reflection summary

## LLM safety stance

This patch does not claim to mathematically eliminate hallucination or prompt injection. It makes every high-risk surface explicit and auditable:

- user input inspection
- memory context inspection
- tool call gating
- tool output isolation
- assistant output inspection
- claim verification via P11 CognitiveGuard
