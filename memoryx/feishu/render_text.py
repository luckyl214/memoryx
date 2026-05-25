"""附件状态文案生成 — 根据 attachments 真实状态动态渲染。

P14.4.1 UX Reliability Hotfix:
- 纯文本无附件 → "已收到文本消息。"
- 有附件已下载 → "已收到 N 个附件，已安全下载。"
- 有附件处理失败 → "已收到 N 个附件，其中 M 个处理失败。"
- 附件处理中 → "已收到 N 个附件，正在处理。"
- 永远不固定写"附件已安全入队"
"""
from __future__ import annotations

from typing import Any


def attachment_status_text(attachments: list[Any]) -> str:
    """根据附件列表生成准确的附件状态文案"""
    if not attachments:
        return "已收到文本消息。"

    total = len(attachments)
    downloaded = sum(
        1 for a in attachments
        if _has_local_path(a) or _has_status(a, "uploaded")
    )
    failed = sum(
        1 for a in attachments
        if _has_status(a, "failed") or _has_status(a, "download_failed")
    )
    pending = total - downloaded - failed

    if failed > 0 and downloaded == 0 and pending == 0:
        return f"已收到 {total} 个附件，全部处理失败。"

    if failed > 0:
        return f"已收到 {total} 个附件，其中 {failed} 个处理失败。"

    if downloaded == total:
        return f"已收到 {total} 个附件，已安全下载。"

    if pending > 0 and downloaded > 0:
        return f"已收到 {total} 个附件，{downloaded} 个已就绪。"

    return f"已收到 {total} 个附件，正在处理。"


def _has_local_path(a: Any) -> bool:
    """检查附件是否有本地路径"""
    return bool(getattr(a, "local_path", None))


def _has_status(a: Any, status: str) -> bool:
    """检查附件状态是否匹配"""
    return getattr(a, "status", "") == status