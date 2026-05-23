"""Schema compatibility adapter for cognitive modules.

Allows cognitive code to work with both old (memory_id, entity_id)
and new P0 (id, active_state TEXT) schema without rewrites.
"""

from __future__ import annotations

from typing import Any


async def table_columns(repository: Any, table: str) -> set[str]:
    rows = await repository.db.fetchall(f"PRAGMA table_info({table});")
    return {str(row["name"]) for row in rows}


async def memory_pk(repository: Any) -> str:
    cols = await table_columns(repository, "memories")
    if "id" in cols:
        return "id"
    if "memory_id" in cols:
        return "memory_id"
    raise RuntimeError("memories table has neither id nor memory_id")


async def entity_pk(repository: Any) -> str:
    cols = await table_columns(repository, "entities")
    if "id" in cols:
        return "id"
    if "entity_id" in cols:
        return "entity_id"
    raise RuntimeError("entities table has neither id nor entity_id")


def is_active_state(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "active", "enabled"}
