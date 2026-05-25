"""
MemoryX Runtime Plugin for Hermes.

Activates MemoryX at every lifecycle point:
  - on_session_start: P13 semantic readiness check
  - pre_llm_call: inject relevant MemoryX context
  - pre_tool_call: lesson/guard for dangerous tools
  - post_llm_call: auto-store conversation turns
  - on_session_end: trigger narrative reflection

IMPORTANT: All hook callbacks must be SYNCHRONOUS.
Hermes invoke_hook() is sync and does NOT await coroutines.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
import urllib.parse
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEMORYX_ROOT = os.getenv("MEMORYX_ROOT", "${HOME}/memoryx")
MEMORYX_DB_PATH = os.getenv("MEMORYX_DB_PATH", f"{MEMORYX_ROOT}./data/memoryx.db")
MEMORYX_BASE_URL = os.getenv("MEMORYX_BASE_URL", "http://127.0.0.1:8080")
P13_GATE_WRAPPER = f"{MEMORYX_ROOT}/tools/memoryx_p13_gate_wrapper.py"
PYTHON = f"{MEMORYX_ROOT}/.venv/bin/python"

# Cached P13 state
_p13_ok = False
_p13_checked_at = 0.0
_last_session_id = ""

# ---------------------------------------------------------------------------
# P13 Gate check
# ---------------------------------------------------------------------------


def _run_p13_gate() -> tuple[bool, str]:
    """Run the P13 gate wrapper subprocess. Returns (ok, message)."""
    global _p13_ok, _p13_checked_at

    env = os.environ.copy()
    env["MEMORYX_DB_PATH"] = MEMORYX_DB_PATH

    try:
        proc = subprocess.run(
            [PYTHON, P13_GATE_WRAPPER],
            cwd=MEMORYX_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=25,
        )
    except Exception as exc:
        _p13_ok = False
        _p13_checked_at = time.time()
        return False, f"P13 gate crashed: {exc}"

    ok = proc.returncode == 0 and "status=ok" in proc.stdout
    _p13_ok = ok
    _p13_checked_at = time.time()
    return ok, proc.stdout.strip() or "P13 gate completed"


def _ensure_p13(force: bool = False) -> tuple[bool, str]:
    """Re-check P13 if stale (>1 hour) or forced."""
    global _p13_ok, _p13_checked_at
    if force or not _p13_ok or time.time() - _p13_checked_at > 3600:
        return _run_p13_gate()
    return True, "P13 gate OK (cached)"


# ---------------------------------------------------------------------------
# HTTP helper (synchronous — Hermes invoke_hook does NOT support async)
# ---------------------------------------------------------------------------


def _memoryx_post(path: str, payload: dict, timeout: int = 20) -> dict[str, Any] | None:
    """POST to MemoryX REST API synchronously. Returns JSON or None on error."""
    url = f"{MEMORYX_BASE_URL}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except Exception as exc:
        logger.warning("MemoryX POST %s failed: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _session_id(kwargs: dict[str, Any]) -> str:
    return (
        kwargs.get("session_id")
        or kwargs.get("task_id")
        or kwargs.get("conversation_id")
        or kwargs.get("thread_id")
        or "default"
    )


def _extract_user_text(kwargs: dict[str, Any]) -> str:
    for key in ("prompt", "message", "content", "user_message", "input"):
        value = kwargs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    messages = kwargs.get("messages")
    if isinstance(messages, list) and len(messages) > 0:
        # message objects: last user message
        for item in reversed(messages):
            if isinstance(item, dict) and item.get("role") == "user":
                content = item.get("content")
                if isinstance(content, str):
                    return content.strip()
                if isinstance(content, list):
                    parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    if parts:
                        return " ".join(parts).strip()

    return ""


# ---------------------------------------------------------------------------
# Hook handlers — ALL MUST BE SYNCHRONOUS
# ---------------------------------------------------------------------------


def _on_session_start(**kwargs) -> dict | None:
    """P13 semantic readiness check before Hermes starts a session."""
    ok, message = _ensure_p13()
    if not ok:
        return {
            "action": "block",
            "message": (
                "MemoryX P13 semantic readiness failed. "
                "Hermes must not enter learning mode.\n\n"
                f"{message}"
            ),
        }
    logger.info("MemoryX P13 gate OK: %s", message)
    return None


def _pre_llm_call(**kwargs) -> dict | None:
    """Inject MemoryX context block before LLM call."""
    global _last_session_id

    ok, _ = _ensure_p13()
    if not ok:
        return {
            "action": "block",
            "message": "MemoryX P13 gate failed — blocking LLM call.",
        }

    session_id = _session_id(kwargs)
    user_text = _extract_user_text(kwargs)
    if not user_text:
        return None

    _last_session_id = session_id

    result = _memoryx_post(
        "/v1/cognitive/context",
        {
            "session_id": session_id,
            "query": user_text,
            "limit": 8,
            "include_lessons": True,
            "include_safety_contract": True,
        },
        timeout=15,
    )

    if result is None:
        # MemoryX REST unavailable — still allow LLM call without context
        return None

    context_block = result.get("context_block", "")
    if not context_block:
        return None

    return context_block


def _pre_tool_call(**kwargs) -> dict | None:
    """Guard dangerous tool calls via MemoryX evaluate-action."""
    session_id = _session_id(kwargs)
    tool_name = kwargs.get("tool_name") or kwargs.get("name") or "tool"
    tool_args = kwargs.get("args") or kwargs.get("arguments") or {}

    action_text = f"{tool_name} {json.dumps(tool_args, ensure_ascii=False)[:1000]}"

    result = _memoryx_post(
        "/v1/cognitive/evaluate-action",
        {
            "session_id": session_id,
            "action_text": action_text,
            "store": True,
        },
        timeout=15,
    )

    if result is None:
        # Guard unavailable: fail-closed for dangerous tools
        if tool_name in {"shell", "bash", "terminal", "exec", "subprocess"}:
            logger.warning("MemoryX guard unavailable for dangerous tool %s — blocking", tool_name)
            return {"action": "block", "message": "MemoryX guard unavailable for dangerous tool; blocked."}
        return None

    should_block = result.get("should_block") or result.get("block")
    requires_user = result.get("requires_user")
    guard_block = result.get("guard_block") or result.get("message") or ""

    if should_block:
        return {"action": "block", "message": guard_block or "MemoryX blocked this tool call."}

    if requires_user:
        return {
            "action": "block",
            "message": (
                "MemoryX requires confirmation before this tool call.\n\n"
                f"{guard_block}"
            ),
        }

    return None


def _post_llm_call(**kwargs) -> None:
    """Auto-store conversation turn and verify answer."""
    session_id = _session_id(kwargs)
    user_text = _extract_user_text(kwargs)
    response = (
        kwargs.get("response")
        or kwargs.get("output")
        or kwargs.get("assistant_response")
        or kwargs.get("content")
        or ""
    )

    if not isinstance(response, str) or not response.strip():
        return None

    # Auto-store (fire-and-forget — observer hook, never block)
    _memoryx_post(
        "/v1/cognitive/auto-store",
        {
            "session_id": session_id,
            "user_message": user_text,
            "assistant_response": response,
            "source": "hermes.post_llm_call",
        },
        timeout=20,
    )

    # Verify answer (fire-and-forget)
    if user_text:
        _memoryx_post(
            "/v1/cognitive/verify-answer",
            {
                "session_id": session_id,
                "question": user_text,
                "answer": response,
                "store": True,
            },
            timeout=20,
        )

    return None


def _on_session_end(**kwargs) -> None:
    """Trigger narrative reflection on session end."""
    session_id = _session_id(kwargs)

    _memoryx_post(
        "/v1/cognitive/narrative-reflection",
        {
            "session_id": session_id,
            "reflection_type": "session",
            "store": True,
            "window_start": "1970-01-01T00:00:00",
            "window_end": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        },
        timeout=30,
    )

    return None


def _post_tool_call(**kwargs) -> None:
    """Store tool result (observer — fire-and-forget)."""
    session_id = _session_id(kwargs)
    tool_name = kwargs.get("tool_name") or kwargs.get("name") or "tool"
    result = kwargs.get("result") or kwargs.get("output") or ""

    _memoryx_post(
        "/v1/cognitive/tool-result",
        {
            "session_id": session_id,
            "tool_name": tool_name,
            "result": str(result)[:4000],
            "source": "hermes.post_tool_call",
        },
        timeout=15,
    )

    return None


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx):
    """Register all MemoryX lifecycle hooks."""

    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("pre_llm_call", _pre_llm_call)
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_llm_call", _post_llm_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)

    logger.info("MemoryX Runtime Plugin registered: 6 hooks")