from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SenseNovaLiteConfig:
    api_key: str
    base_url: str = "https://api.sensenova.cn/compatible-mode/v2"
    model: str = "SenseChat-Turbo"
    timeout_seconds: float = 30.0
    temperature: float = 0.01
    top_p: float = 0.7
    max_tokens: int = 800


class SenseNovaLiteClient:
    """
    OpenAI-compatible SenseNova client.

    设计原则：
    - 只用于"辅助提取 JSON"，不参与核心判断。
    - 输出必须能被 json.loads 解析，否则视为失败。
    - 失败时抛异常，由上层 fallback。
    """

    def __init__(self, config: SenseNovaLiteConfig | None = None) -> None:
        if config is None:
            api_key = (
                os.getenv("SENSENOVA_API_KEY")
                or os.getenv("SENSENOVA_API_TOKEN")
                or os.getenv("MEMORYX_LLM_API_KEY")
                or ""
            )
            base_url = os.getenv("SENSENOVA_BASE_URL", "https://api.sensenova.cn/compatible-mode/v2")
            model = os.getenv("SENSENOVA_MODEL", "SenseChat-Turbo")
            config = SenseNovaLiteConfig(api_key=api_key, base_url=base_url, model=model)

        if not config.api_key:
            raise RuntimeError(
                "Missing SenseNova API key. Set SENSENOVA_API_KEY or MEMORYX_LLM_API_KEY."
            )

        self.config = config

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from openai import AsyncOpenAI
        except Exception as exc:
            raise RuntimeError("openai package is required: pip install openai") from exc

        client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
        )

        schema_text = ""
        if schema_hint:
            schema_text = "\n\nJSON schema hint:\n" + json.dumps(
                schema_hint,
                ensure_ascii=False,
                indent=2,
            )

        response = await client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "system",
                    "content": system + schema_text,
                },
                {
                    "role": "user",
                    "content": user,
                },
            ],
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            max_tokens=self.config.max_tokens,
        )

        content = response.choices[0].message.content or ""
        return self._parse_json(content)

    def _parse_json(self, content: str) -> dict[str, Any]:
        text = content.strip()

        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()

        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            text = text[first:last + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"SenseNova returned non-JSON content: {content[:300]}") from exc

        if not isinstance(data, dict):
            raise ValueError("SenseNova JSON output must be an object")

        return data
