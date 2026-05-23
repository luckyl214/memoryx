from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sys
import time
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    fmt: Optional[str] = None,
) -> None:
    if fmt is None:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=fmt, handlers=handlers)


def hash_text(text: str, algorithm: str = "sha256") -> str:
    h = hashlib.sha256 if algorithm == "sha256" else hashlib.md5
    return h(text.encode("utf-8")).hexdigest()


def chunk_text(text: str, max_length: int = 500, overlap: int = 50) -> list[str]:
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    sentences = re.split(r"(?<=[。！？.!?])\s*", text)
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= max_length:
            current += sentence
        else:
            if current:
                chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    if not chunks:
        start = 0
        while start < len(text):
            end = min(start + max_length, len(text))
            chunks.append(text[start:end])
            start = end - overlap
    return chunks


def sanitize_filename(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return re.sub(r"\s+", "_", safe.strip())[:100]


def truncate_text(text: str, max_length: int = 200, suffix: str = "...") -> str:
    return text if len(text) <= max_length else text[: max_length - len(suffix)] + suffix


def retry_with_backoff(
    func: Callable,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_errors: tuple = (Exception,),
):
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return func()
        except retryable_errors as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning("retry %d/%d failed, waiting %.1fs: %s", attempt + 1, max_retries, delay, e)
                time.sleep(delay)
    if last_error:
        raise last_error


async def async_retry(
    coro_factory: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retryable_errors: tuple = (Exception,),
):
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await coro_factory()
        except retryable_errors as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = min(base_delay * (2**attempt), max_delay)
                logger.warning("async retry %d/%d, waiting %.1fs: %s", attempt + 1, max_retries, delay, e)
                await asyncio.sleep(delay)
    if last_error:
        raise last_error
