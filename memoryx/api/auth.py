"""P0-E: API Key 认证 — 使用 secrets.compare_digest 防时序攻击。

规则：
- MEMORYX_API_KEY 未设置 → 本地开发无感，所有请求通过。
- MEMORYX_API_KEY 已设置 → 所有 REST route 要求 X-MemoryX-API-Key。
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Request


EXPECTED_API_KEY: str | None = os.environ.get("MEMORYX_API_KEY")


def verify_api_key(x_memoryx_api_key: str | None = Header(default=None, alias="X-MemoryX-API-Key")) -> Optional[str]:
    """FastAPI dependency: verify API key from header.

    Returns the validated key value on success, raises 401 on failure.
    When MEMORYX_API_KEY is not set, skips verification (local dev mode).
    """
    if EXPECTED_API_KEY is None:
        return None  # local dev — no auth required

    if x_memoryx_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-MemoryX-API-Key header")

    if not secrets.compare_digest(x_memoryx_api_key, EXPECTED_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return x_memoryx_api_key


def is_auth_required() -> bool:
    """Return True if API key auth is enforced."""
    return EXPECTED_API_KEY is not None
