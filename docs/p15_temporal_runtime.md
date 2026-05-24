# P15.2 Temporal Runtime

Task lifecycle tracking for MemoryX — records session/learning duration and
provides per-entity time queries.

## Quick Start

No setup needed. Hermes automatically calls `/task/start` when a session begins
and `/task/end` when it ends. No manual timer management required.

After a Hermes session, check your time:

```bash
# All tasks today for a given entity
python tools/memoryx_today_duration.py --entity xhs-learning

# Or directly via SQL
sqlite3 /home/lucky/memoryx/data/memoryx.db "
SELECT session_id, entity_id, task_type, title, duration_seconds,
       started_at, ended_at
FROM tasks
ORDER BY started_at DESC
LIMIT 10;
"
```

## REST Routes

All routes are on the `v1/cognitive` prefix.

### POST /v1/cognitive/task/start

Start a running task timer.

```json
{
  "session_id": "sess-abc",
  "entity_id": "xhs-learning",
  "task_type": "research",
  "title": "账号定位学习",
  "source": "hermes.on_session_start"
}
```

Response:

```json
{
  "task_id": "abc123...",
  "session_id": "sess-abc",
  "status": "running",
  "started_at": "2026-05-24T12:00:00+00:00"
}
```

### POST /v1/cognitive/task/end

End a running task (matched by session_id + entity_id). Computes duration_seconds
and writes a compatible row to `task_durations`.

```json
{
  "session_id": "sess-abc",
  "entity_id": "xhs-learning",
  "status": "done",
  "summary": "完成定位拆解",
  "source": "hermes.on_session_end"
}
```

Response:

```json
{
  "task_id": "abc123...",
  "duration_seconds": 2725,
  "status": "done",
  "ended_at": "2026-05-24T12:45:25+00:00"
}
```

### POST /v1/cognitive/task/durations

Aggregate duration stats. All filters optional.

```json
{
  "session_id": null,
  "entity_id": "xhs-learning",
  "task_type": null,
  "since": "2026-05-24T00:00:00Z",
  "until": null
}
```

Response:

```json
{
  "summary": {
    "total_tasks": 3,
    "total_seconds": 5440,
    "avg_seconds": 1813.3
  },
  "by_session": [],
  "by_entity": [
    {"entity_id": "xhs-learning", "count": 3, "total_seconds": 5440}
  ],
  "by_task_type": [
    {"task_type": "research", "count": 2, "total_seconds": 4200},
    {"task_type": "practice", "count": 1, "total_seconds": 1240}
  ]
}
```

### POST /v1/cognitive/entity/timeline

Chronological task list for an entity.

```json
{
  "entity_id": "xhs-learning",
  "since": null,
  "until": null,
  "limit": 20
}
```

Response:

```json
{
  "entity_id": "xhs-learning",
  "entries": [
    {
      "task_id": "abc...",
      "session_id": "sess-abc",
      "title": "账号定位学习",
      "task_type": "research",
      "status": "done",
      "started_at": "...",
      "ended_at": "...",
      "duration_seconds": 2725
    },
    ...
  ],
  "count": 3
}
```

## Hermes Plugin Integration

The `memoryx_runtime` plugin automatically starts/stops tasks:

| Hook | Action |
|------|--------|
| `on_session_start` | `POST /v1/cognitive/task/start` |
| `on_session_end` | `POST /v1/cognitive/task/end` + narrative reflection |

Entity and task_type are extracted from kwargs. Default: `general` / `conversation`.

## Database Tables

Two tables are used (pre-existing, no migration needed):

- **tasks** — live task tracking with FK constraints (bypassed via raw SQL)
- **task_durations** — completed duration records for aggregation queries

Both tables link via `task_id`. FK constraints on `session_id` and `entity_id`
reference `sessions` and `entities` tables respectively.

## Tags

```
baseline/p15-2-temporal-runtime-green
```

## Gate

```bash
MEMORYX_DB_PATH=/home/lucky/memoryx/data/memoryx.db \
  python tools/memoryx_p152_temporal_gate.py
```

Checks 9 items: table existence, all 4 REST routes, duration computation,
entity aggregation, and timeline completeness.

## Tomorrow's Verification

When learning tomorrow, verify:

1. Session auto start/end works (check tasks table)
2. Duration is realistic (not 0s, not wrong)
3. Entity_id maps correctly (xhs-positioning, xhs-title, etc.)
4. /task/durations answers "how long did I spend on X"
5. /entity/timeline lists key learning nodes