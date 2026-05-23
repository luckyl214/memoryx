from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp

from .cache_layer import EmbeddingCache
from .models import EmbeddingRequest, EmbeddingResult


class GenericEmbeddingClient:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        base_delay: float = 0.2,
        transport: Callable[..., aiohttp.ClientSession] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.transport = transport or aiohttp.ClientSession

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "input": texts}
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)

        for attempt in range(1, self.max_retries + 1):
            try:
                async with self.transport(timeout=timeout) as session:
                    async with session.post(self.endpoint, json=payload, headers=headers) as response:
                        response.raise_for_status()
                        body = await response.json()
                        data = body.get("data", [])
                        return [[float(value) for value in item.get("embedding", [])] for item in data]
            except (aiohttp.ClientError, asyncio.TimeoutError):
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.base_delay * attempt)
        raise RuntimeError("unreachable")


class EmbeddingManager:
    def __init__(
        self,
        *,
        client: Any,
        cache: EmbeddingCache,
        batch_size: int = 16,
        expected_dimension: int = 4096,
    ) -> None:
        self.client = client
        self.cache = cache
        self.batch_size = batch_size
        self.expected_dimension = expected_dimension

    async def embed_text(self, text: str) -> list[float]:
        cached = await self.cache.get(text)
        if cached is not None:
            return cached
        vector = (await self.client.embed_texts([text]))[0]
        self._validate_dimension(vector)
        await self.cache.set(text, vector)
        return vector

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = [None] * len(texts)
        missing_pairs: list[tuple[int, str]] = []

        for index, text in enumerate(texts):
            cached = await self.cache.get(text)
            if cached is not None:
                results[index] = cached
            else:
                missing_pairs.append((index, text))

        for start in range(0, len(missing_pairs), self.batch_size):
            batch = missing_pairs[start : start + self.batch_size]
            vectors = await self.client.embed_texts([text for _, text in batch])
            for (index, text), vector in zip(batch, vectors, strict=False):
                self._validate_dimension(vector)
                await self.cache.set(text, vector)
                results[index] = vector

        return [[float(value) for value in result] for result in results if result is not None]

    async def embed_request(self, request: EmbeddingRequest) -> EmbeddingResult:
        vector = await self.embed_text(request.content)
        return EmbeddingResult(
            memory_id=request.memory_id,
            vector=vector,
            dimension=len(vector),
            freshness_score=1.0,
            metadata=request.metadata,
        )

    def _validate_dimension(self, vector: list[float]) -> None:
        if len(vector) != self.expected_dimension:
            raise ValueError(f"Unexpected embedding dimension: {len(vector)} != {self.expected_dimension}")
