"""渲染文案工具 — 动态判断附件状态，不写死"附件已入队"。

原则：
- 纯文本消息 → "已收到文本消息。"
- 有附件且全部下载成功 → "已收到 N 个附件，已安全下载。"
- 有附件且部分失败 → "已收到 N 个附件，其中 M 个处理失败。"
- 有附件且正在处理 → "已收到 N 个附件，正在处理。"
"""
from __future__ import annotations

from typing import Any


def attachment_status_text(attachments: list[Any]) -> str:
    """根据附件列表生成准确的文案。"""
    if not attachments:
        return "已收到文本消息。"

    total = len(attachments)
    downloaded = sum(
        1 for a in attachments if getattr(a, "local_path", None)
    )
    failed = sum(
        1 for a in attachments
        if getattr(a, "status", "") in {"failed", "download_failed"}
    )

    if failed:
        return f"已收到 {total} 个附件，其中 {failed} 个处理失败。"
    if downloaded == total:
        return f"已收到 {total} 个附件，已安全下载。"
    return f"已收到 {total} 个附件，正在处理。"
