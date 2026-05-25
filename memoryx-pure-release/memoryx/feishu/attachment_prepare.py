"""附件预处理 — 下载后确认 Hermes 能否消费。

对不同文件类型做预处理，确保 Hermes 能正确读取。
"""
from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from .schemas import AttachmentRef


@dataclass(slots=True)
class PreparedAttachment:
    """预处理后的附件"""
    kind: str                       # image | file | media | audio | unknown
    name: str                       # 文件名
    local_path: str                 # 本地路径
    mime_type: str                  # MIME 类型
    size: int                       # 文件大小（字节）
    sha256: str                     # SHA256 哈希
    status: str                     # downloaded | parsed | unsupported | too_large | missing
    text_preview: str = ""          # 文本预览（用于文本类文件）
    extra: dict | None = None       # 额外信息

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}

    def is_usable(self) -> bool:
        """附件是否可用（Hermes 能消费）"""
        return self.status in ("downloaded", "parsed")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "name": self.name,
            "local_path": self.local_path,
            "mime_type": self.mime_type,
            "size": self.size,
            "sha256": self.sha256,
            "status": self.status,
            "text_preview": self.text_preview,
            "extra": self.extra,
        }


class AttachmentPreparer:
    """附件预处理器"""

    # 支持文本提取的文件扩展名
    TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".html", ".css", ".sql", ".xml"}

    # 最大文件大小（100MB）
    MAX_BYTES = 100 * 1024 * 1024

    def __init__(self, *, max_bytes: int | None = None) -> None:
        self.max_bytes = max_bytes or self.MAX_BYTES

    def prepare(self, ref: AttachmentRef) -> PreparedAttachment:
        """预处理单个附件"""
        # 检查本地路径
        if not ref.local_path:
            return PreparedAttachment(
                kind=ref.kind,
                name=ref.name or "attachment",
                local_path="",
                mime_type=ref.mime_type or "",
                size=ref.size or 0,
                sha256="",
                status="missing_local_path",
            )

        path = Path(ref.local_path)

        # 检查文件存在
        if not path.exists():
            return self._bad(ref, "missing_file")

        # 检查文件大小
        try:
            size = path.stat().st_size
        except OSError:
            return self._bad(ref, "stat_error")

        if size <= 0:
            return self._bad(ref, "empty_file")

        if size > self.max_bytes:
            return self._bad(ref, "too_large", extra={"size_bytes": size, "max_bytes": self.max_bytes})

        # 计算 SHA256
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        # 确定 MIME 类型
        mime = ref.mime_type
        if not mime:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        # 提取文本预览
        text_preview = ""
        if mime.startswith("text/") or path.suffix.lower() in self.TEXT_EXTENSIONS:
            try:
                text_preview = path.read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                pass

        return PreparedAttachment(
            kind=ref.kind,
            name=ref.name or path.name,
            local_path=str(path),
            mime_type=mime,
            size=size,
            sha256=digest,
            status="parsed" if text_preview else "downloaded",
            text_preview=text_preview,
        )

    def _bad(self, ref: AttachmentRef, status: str, extra: dict | None = None) -> PreparedAttachment:
        return PreparedAttachment(
            kind=ref.kind,
            name=ref.name or "attachment",
            local_path=ref.local_path or "",
            mime_type=ref.mime_type or "",
            size=ref.size or 0,
            sha256="",
            status=status,
            extra=extra or {},
        )
