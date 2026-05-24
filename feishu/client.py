# memoryx/feishu/client.py
"""
飞书 OpenAPI 客户端：发送消息、更新卡片、上传图片/文件。

支持：
  - tenant_access_token
  - 发送 interactive card
  - 更新 card
  - 上传图片（返回 image_key）
  - 上传文件（返回 file_key）
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx


class FeishuAPIError(RuntimeError):
    pass


class FeishuClient:
    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_url: str = "https://open.feishu.cn",
        timeout: float = 30.0,
    ) -> None:
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")

        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._tenant_token: str | None = None
        self._tenant_token_expire_at = 0.0

    async def tenant_access_token(self) -> str:
        if self._tenant_token and time.time() < self._tenant_token_expire_at - 60:
            return self._tenant_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
            )

        data = resp.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"tenant token failed: {data}")

        token = data.get("tenant_access_token")
        if not token:
            raise FeishuAPIError(f"tenant_access_token missing in response: {data}")

        self._tenant_token = token
        self._tenant_token_expire_at = time.time() + int(data.get("expire", 7200))
        return self._tenant_token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.tenant_access_token()}"}

    async def send_message(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        msg_type: str,
        content: dict[str, Any] | str,
        uuid: str | None = None,
    ) -> dict[str, Any]:
        body = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        }
        if uuid:
            body["uuid"] = uuid

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={**await self._headers(), "Content-Type": "application/json"},
                json=body,
            )
        return self._check(resp)

    async def patch_message_card(self, *, message_id: str, card: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.patch(
                f"{self.base_url}/open-apis/im/v1/messages/{message_id}/card",
                headers={**await self._headers(), "Content-Type": "application/json"},
                json={"content": json.dumps(card, ensure_ascii=False)},
            )
        return self._check(resp)

    async def upload_image(self, *, path: str | Path, image_type: str = "message") -> str:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError(f"invalid image file: {path}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with path.open("rb") as f:
                resp = await client.post(
                    f"{self.base_url}/open-apis/im/v1/images",
                    headers=await self._headers(),
                    data={"image_type": image_type},
                    files={
                        "image": (
                            path.name,
                            f,
                            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        )
                    },
                )
        data = self._check(resp)
        return data["data"]["image_key"]

    async def upload_file(self, *, path: str | Path, file_type: str = "stream") -> str:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError(f"invalid file: {path}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            with path.open("rb") as f:
                resp = await client.post(
                    f"{self.base_url}/open-apis/im/v1/files",
                    headers=await self._headers(),
                    data={
                        "file_type": file_type,
                        "file_name": path.name,
                    },
                    files={
                        "file": (
                            path.name,
                            f,
                            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        )
                    },
                )
        data = self._check(resp)
        return data["data"]["file_key"]

    def _check(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except Exception as exc:
            raise FeishuAPIError(f"non-json response {resp.status_code}: {resp.text[:500]}") from exc

        if resp.status_code >= 400 or data.get("code", 0) != 0:
            raise FeishuAPIError(f"Feishu API error status={resp.status_code} body={data}")
        return data
