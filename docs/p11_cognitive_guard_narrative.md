# P11 Cognitive Guard + Narrative Reflection

P11 turns MemoryX from a memory/retrieval system into a stronger cognitive guard layer.

## Modules

- `memoryx.cognitive.claim_guard`
  - Extracts answer claims.
  - Retrieves evidence from MemoryX.
  - Persists supported/unsupported/contradicted claim status.
  - Produces allow/warn/block decisions.

- `memoryx.cognitive.lesson_enforcement`
  - Converts matching LESSON memories into action policy decisions:
    allow, warn, require_confirmation, require_dry_run, require_tool_verification, block.

- `memoryx.cognitive.narrative_reflection`
  - Summarizes task duration, opinion shifts, lessons, and claim verification events over a time window.

- `memoryx.cognitive.guarded_generation`
  - Facade for agent integrations.

## Migration

```bash
sqlite3 "$MEMORYX_DB_PATH" < db/migrations/020_cognitive_guard_narrative.sql
```

## REST wiring

```python
from memoryx.api.p11_routes import create_p11_router

app.include_router(
    create_p11_router(
        repository=_app_repo,
        retrieval_engine=_app_api.retrieval_engine,
        lesson_policy=getattr(_app_api.retrieval_engine, "lesson_policy", None),
    )
)
```

## Agent usage

```python
guard = CognitiveGuard(repository=repo, retrieval_engine=retrieval, lesson_policy=lesson_policy)

answer_guard = await guard.verify_answer(
    question=user_query,
    answer=draft_answer,
    session_id=session_id,
)

if answer_guard.should_block:
    return answer_guard.guard_block

action_guard = await guard.evaluate_action(
    action_text="deploy production with --force",
    intent="deployment",
    session_id=session_id,
)

if action_guard.requires_user:
    return action_guard.guard_block
```

## Gate

```bash
pytest -q tests/p11
python tools/p11_gate.py
```
