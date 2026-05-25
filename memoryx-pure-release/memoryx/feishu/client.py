# memoryx/feishu/client.py
"""
飞书 OpenAPI 客户端：发送消息、更新卡片、上传图片/文件。

P14.1 硬化：
  - 所有请求走 _request_json（带 retry/backoff）
  - 429/5xx 自动重试，指数退避
  - 飞书错误码 99991400（频控）特殊处理
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import httpx


class FeishuAPIError(RuntimeError):
    pass


# 需要重试的 HTTP 状态码和飞书错误码
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_FEISHU_CODE = {99991400}  # 频控


class FeishuClient:
    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        base_url: str = "https://open.feishu.cn",
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self.app_id = app_id or os.getenv("FEISHU_APP_ID")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET")

        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET are required")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
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

    async def _request_json(self, method: str, url: str, **kwargs) -> dict:
        """带 retry/backoff 的请求"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(method, url, **kwargs)

                data = resp.json()

                # 判断是否可重试
                is_retryable = (
                    resp.status_code in RETRYABLE_STATUS
                    or data.get("code") in RETRYABLE_FEISHU_CODE
                )

                if is_retryable:
                    backoff = min(8.0, 0.5 * (2 ** attempt))
                    await asyncio.sleep(backoff)
                    continue

                if resp.status_code >= 400 or data.get("code", 0) != 0:
                    raise FeishuAPIError(f"Feishu API error status={resp.status_code} body={data}")

                return data

            except httpx.HTTPError as exc:
                last_error = exc
                backoff = min(8.0, 0.5 * (2 ** attempt))
                await asyncio.sleep(backoff)

        raise FeishuAPIError(f"Feishu request failed after {self.max_retries} retries: {last_error}")

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

        return await self._request_json(
            "POST",
            f"{self.base_url}/open-apis/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            headers={**await self._headers(), "Content-Type": "application/json"},
            json=body,
        )

    async def patch_message_card(self, *, message_id: str, card: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(
            "PATCH",
            f"{self.base_url}/open-apis/im/v1/messages/{message_id}/card",
            headers={**await self._headers(), "Content-Type": "application/json"},
            json={"content": json.dumps(card, ensure_ascii=False)},
        )

    async def upload_image(self, *, path: str | Path, image_type: str = "message") -> str:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError(f"invalid image file: {path}")

        with path.open("rb") as f:
            data = await self._request_json(
                "POST",
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
        return data["data"]["image_key"]

    async def upload_file(self, *, path: str | Path, file_type: str = "stream") -> str:
        path = Path(path)
        if not path.exists() or path.stat().st_size <= 0:
            raise ValueError(f"invalid file: {path}")

        with path.open("rb") as f:
            data = await self._request_json(
                "POST",
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
        return data["data"]["file_key"]

    async def download_image(self, *, image_key: str, save_path: str | Path | None = None) -> Path:
        """下载图片到本地（带 sha256 哈希和 spool 管理）"""
        import hashlib

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/open-apis/im/v1/images/{image_key}/image",
                headers=await self._headers(),
            )

        if resp.status_code >= 400:
            raise FeishuAPIError(f"Failed to download image {image_key}: status={resp.status_code}")

        # 计算 sha256
        content = resp.content
        sha256 = hashlib.sha256(content).hexdigest()

        # 确定保存路径
        if save_path is None:
            spool_dir = Path(os.getenv("FEISHU_SPOOL_DIR", "/tmp/feishu_spool"))
            spool_dir.mkdir(parents=True, exist_ok=True)
            # 使用 image_key 前 8 位 + sha256 前 8 位作为文件名，避免冲突
            file_name = f"img_{image_key[:8]}_{sha256[:8]}.png"
            save_path = spool_dir / file_name

        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 如果文件已存在且 sha256 匹配，直接返回
        if path.exists():
            existing_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if existing_sha == sha256:
                return path

        # 写入文件
        path.write_bytes(content)
        return path

    async def download_file(self, *, file_key: str, save_path: str | Path | None = None) -> Path:
        """下载文件到本地（带 sha256 哈希和 spool 管理）"""
        import hashlib

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{self.base_url}/open-apis/im/v1/files/{file_key}/file",
                headers=await self._headers(),
            )

        if resp.status_code >= 400:
            raise FeishuAPIError(f"Failed to download file {file_key}: status={resp.status_code}")

        # 计算 sha256
        content = resp.content
        sha256 = hashlib.sha256(content).hexdigest()

        # 确定保存路径
        if save_path is None:
            spool_dir = Path(os.getenv("FEISHU_SPOOL_DIR", "/tmp/feishu_spool"))
            spool_dir.mkdir(parents=True, exist_ok=True)
            # 使用 file_key 前 8 位 + sha256 前 8 位作为文件名
            file_name = f"file_{file_key[:8]}_{sha256[:8]}"
            save_path = spool_dir / file_name

        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 如果文件已存在且 sha256 匹配，直接返回
        if path.exists():
            existing_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if existing_sha == sha256:
                return path

        # 写入文件
        path.write_bytes(content)
        return path
