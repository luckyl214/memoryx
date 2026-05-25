# memoryx/feishu/routes.py
"""
FastAPI 路由：接收飞书事件 → 去重 → 入队 → 返回 job_id。

流程：
  1. 接收 POST /feishu/events
  2. 签名验证 + 解密（event_security）
  3. URL Verification 响应 challenge
  4. 事件去重（dedupe）
  5. 创建 FeishuRenderJob 入队
  6. 发送 queued 卡片
  7. 返回 job_id
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from fastapi import APIRouter, Request, HTTPException

from .dedupe import FeishuEventDedupe
from .event_security import parse_event_request, verify_challenge
from .schemas import AttachmentRef, FeishuRenderJob


def create_feishu_router(*, bot_service, queue_db_path: str) -> APIRouter:
    """创建飞书事件路由"""
    router = APIRouter(prefix="/feishu", tags=["feishu"])
    dedupe = FeishuEventDedupe(queue_db_path)

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    verification_token = os.getenv("FEISHU_VERIFICATION_TOKEN", "")

    @router.post("/events")
    async def feishu_events(request: Request):
        raw = await request.body()

        # 1. 安全解析（签名验证 + 解密）
        try:
            payload = parse_event_request(raw, app_id, app_secret)
        except Exception as exc:
            raise HTTPException(400, f"event parse error: {exc}")

        # 2. URL Verification
        challenge_result = verify_challenge(payload, verification_token)
        if challenge_result:
            return challenge_result

        # 3. 提取事件信息
        header = payload.get("header", {})
        event = payload.get("event", {})

        event_id = header.get("event_id") or event.get("event_id")
        message = event.get("message", {})
        message_id = message.get("message_id")

        if not event_id:
            raise HTTPException(400, "missing event_id")

        # 4. 事件去重
        payload_hash = hashlib.sha256(raw).hexdigest()
        if dedupe.seen_or_mark(event_id=event_id, message_id=message_id, payload_hash=payload_hash):
            return {"ok": True, "deduped": True}

        # 5. 提取文本和附件
        chat_id = message.get("chat_id")
        sender = event.get("sender", {})
        user_id = (sender.get("sender_id") or {}).get("user_id")
        text = _extract_text(message)
        attachments = _extract_attachments(message)

        # 6. 创建 job 入队
        job = FeishuRenderJob(
            chat_id=chat_id or "",
            user_id=user_id,
            message_id=message_id,
            text=text,
            title="Hermes · MemoryX",
            trace_id=event_id[:12],
            memoryx_badges=["MemoryX ✅", "Semantic ✅", "P13 ✅"],
            attachments=attachments,
        )

        await bot_service.accept_event(job)

        return {"ok": True, "job_id": job.job_id}

    return router


def _extract_text(message: dict) -> str:
    """从飞书消息中提取文本"""
    content = message.get("content") or ""

    if isinstance(content, str):
        try:
            data = json.loads(content)
            # 如果是纯对象但没有 text/content/items 字段，返回空字符串
            if isinstance(data, dict) and not any(k in data for k in ("text", "content", "items")):
                return ""
            # 优先返回 text 或 content 字段
            if "text" in data:
                return data["text"]
            if "content" in data:
                return data["content"]
            # 富文本 items 格式 - 提取所有 text 项
            if "items" in data:
                parts = []
                for item in data["items"]:
                    if item.get("tag") == "text":
                        text = item.get("text", "").strip()
                        if text:
                            parts.append(text)
                return " ".join(parts)
            return content
        except Exception:
            return content

    if isinstance(content, dict):
        # 已经是 dict 格式
        if "text" in content:
            return content["text"]
        if "content" in content:
            return content["content"]
        # 富文本 items 格式
        if "items" in content:
            parts = []
            for item in content["items"]:
                if item.get("tag") == "text":
                    text = item.get("text", "").strip()
                    if text:
                        parts.append(text)
            return " ".join(parts)
        return ""

    return ""


def _extract_attachments(message: dict) -> list[AttachmentRef]:
    """从飞书消息中提取附件"""
    attachments: list[AttachmentRef] = []
    content = message.get("content") or "{}"

    if isinstance(content, str):
        try:
            data = json.loads(content)
        except Exception:
            return attachments
    elif isinstance(content, dict):
        data = content
    else:
        return attachments

    # 提取图片
    for item in data.get("items", []):
        if item.get("tag") == "img":
            image_key = item.get("image_key") or item.get("src")
            if image_key:
                attachments.append(AttachmentRef(
                    kind="image",
                    image_key=image_key,
                    name=item.get("alt", "image"),
                ))

    # 提取文件
    for item in data.get("items", []):
        if item.get("tag") == "file":
            file_key = item.get("file_key")
            if file_key:
                attachments.append(AttachmentRef(
                    kind="file",
                    file_key=file_key,
                    name=item.get("name", "file"),
                    size=item.get("size"),
                ))

    return attachments
