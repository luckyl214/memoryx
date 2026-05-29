"""P0-E: API Key 认证 — 使用 secrets.compare_digest 防时序攻击。

规则：
- MEMORYX_API_KEY 未设置 → 本地开发无感，所有请求通过。
- MEMORYX_API_KEY="" → 不强制 auth。
- MEMORYX_API_KEY 为 placeholder → 不强制 auth。
- MEMORYX_API_KEY 已设置为真实值 → 所有 REST route 要求 X-MemoryX-API-Key。
"""

from __future__ import annotations

import os
import secrets
from typing import Optional

from fastapi import Header, HTTPException, Request

_PLACEHOLDER_KEYS = {
    "", "your_api_key_here", "your_api_key", "changeme", "change_me",
    "placeholder", "test", "example", "sk-xxx", "YOUR_API_KEY",
}


def _get_expected_key() -> str | None:
    """Runtime getter: read MEMORYX_API_KEY from env each call."""
    key = os.environ.get("MEMORYX_API_KEY")
    if key is None:
        return None
    key = key.strip()
    if key.lower() in _PLACEHOLDER_KEYS:
        return None
    return key


def verify_api_key(x_memoryx_api_key: str | None = Header(default=None, alias="X-MemoryX-API-Key")) -> Optional[str]:
    """FastAPI dependency: verify API key from header.

    Returns the validated key value on success, raises 401 on failure.
    When MEMORYX_API_KEY is not set or is a placeholder, skips verification (local dev mode).
    """
    expected = _get_expected_key()
    if expected is None:
        return None  # local dev — no auth required

    if x_memoryx_api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-MemoryX-API-Key header")

    if not secrets.compare_digest(x_memoryx_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid API key")

    return x_memoryx_api_key


def is_auth_required() -> bool:
    """Return True if API key auth is enforced."""
    return _get_expected_key() is not None
