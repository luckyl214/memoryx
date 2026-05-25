"""飞书卡片更新合并器 — 防乱序、防闪、防重复 patch。

保证：
- 只允许新 revision 覆盖旧 revision
- 相同内容不重复发送
- 节流控制最小间隔
- 并发安全
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class PendingCardUpdate:
    message_id: str
    card: dict[str, Any]
    revision: int
    created_at: float


class CardUpdateCoalescer:
    """Throttle and de-duplicate Feishu card updates with revision control.

    Guarantees:
    - No stale revision can overwrite a newer one
    - Identical cards are not patched again
    - Minimum interval between patches enforced
    - Concurrent updates serialized per message_id
    """

    def __init__(self, *, min_interval: float = 0.8) -> None:
        self.min_interval = min_interval
        self._last_sent_at: dict[str, float] = {}
        self._last_hash: dict[str, str] = {}
        self._last_revision: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def patch(
        self,
        *,
        message_id: str,
        card: dict[str, Any],
        revision: int,
        sender: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> bool:
        """尝试更新卡片，返回是否实际发送了 patch。

        Args:
            message_id: 卡片消息 ID
            card: 卡片内容
            revision: 当前 revision（必须 >= 已记录的 revision）
            sender: 实际发送函数 (message_id, card) -> None

        Returns:
            True 如果实际发送了 patch，False 如果被跳过
        """
        lock = self._locks.setdefault(message_id, asyncio.Lock())

        async with lock:
            # 1. 拒绝旧 revision
            if revision < self._last_revision.get(message_id, -1):
                return False

            # 2. 相同内容不重复发送
            body = json.dumps(card, ensure_ascii=False, sort_keys=True)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

            if digest == self._last_hash.get(message_id):
                return False

            # 3. 节流控制
            now = time.monotonic()
            wait = self.min_interval - (now - self._last_sent_at.get(message_id, 0.0))
            if wait > 0:
                await asyncio.sleep(wait)

            # 4. 发送
            await sender(message_id, card)

            # 5. 更新状态
            self._last_sent_at[message_id] = time.monotonic()
            self._last_hash[message_id] = digest
            self._last_revision[message_id] = revision
            return True

    def get_last_revision(self, message_id: str) -> int:
        """获取该消息的最后 revision"""
        return self._last_revision.get(message_id, 0)

    def reset(self, message_id: str) -> None:
        """重置某个消息的追踪状态（用于手动重试）"""
        self._last_sent_at.pop(message_id, None)
        self._last_hash.pop(message_id, None)
        self._last_revision.pop(message_id, None)
        self._locks.pop(message_id, None)
