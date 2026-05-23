# Hermes integration guide for Mnemosyne-X Phase 1

## Goal
Attach Mnemosyne-X as a non-intrusive plugin using Hermes' existing plugin hook system.

## Files to install
Copy these into a Hermes plugin directory:
- `memoryx/`
- a plugin manifest that calls `memoryx.plugin:register`

## Integration steps
1. Place the repository at `/path/to/memoryx` or another path on `PYTHONPATH`.
2. Install dependencies from `requirements.txt` inside a Python 3.11 virtual environment.
3. Register `memoryx.plugin:register` with Hermes' plugin bootstrap.
4. Ensure the host emits these hook names verbatim:
   - `on_user_message`
   - `on_assistant_response`
   - `on_tool_call`
   - `on_tool_result`
   - `on_session_end`
5. If Hermes exposes middleware registration, attach `MemoryHookManager.middleware`.
6. On startup call `MemoryHookManager.start()`; on shutdown call `MemoryHookManager.stop()`.

## Hook mapping
- Hermes `on_user_message` -> MemoryX `ON_USER_MESSAGE`
- Hermes `on_assistant_response` -> MemoryX `ON_ASSISTANT_RESPONSE`
- Hermes `on_tool_call` -> MemoryX `ON_TOOL_CALL`
- Hermes `on_tool_result` -> MemoryX `ON_TOOL_RESULT`
- Hermes `on_session_end` -> MemoryX `ON_SESSION_END`

## Runtime behavior
- Background workers consume an async queue
- Queue is bounded and applies backpressure
- Handler failures are retried
- Shutdown drains in-flight events gracefully
- Middleware can mutate events before queueing
- Plugins register per-event handlers through the manager

## Verification
```bash
pytest -q tests/test_hook.py tests/integration/test_plugin_integration.py
```
