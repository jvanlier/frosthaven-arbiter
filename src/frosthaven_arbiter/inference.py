"""Local llama.cpp model adapters.

`EmbeddingModel` and `ChatModel` are the seams between retrieval/
arbitration and local inference. Production adapters speak the
OpenAI-compatible HTTP API exposed by `llama-server`. Tests use fake
adapters instead.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx
import numpy as np

from frosthaven_arbiter.config import ModelSettings


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class EmbeddingModel(Protocol):
    @property
    def fingerprint(self) -> str: ...

    async def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class ChatModel(Protocol):
    async def complete(self, messages: Sequence[ChatMessage]) -> str: ...


class LlamaCppEmbeddingModel:
    def __init__(self, settings: ModelSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(base_url=settings.base_url, timeout=settings.timeout_seconds)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self._settings.model_path.encode()).hexdigest()[:16]

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        response = await self._client.post("/embeddings", json={"input": list(texts)})
        response.raise_for_status()
        data = response.json()["data"]
        vectors = np.array([item["embedding"] for item in data], dtype=np.float32)
        return vectors


class LlamaCppChatModel:
    def __init__(self, settings: ModelSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(base_url=settings.base_url, timeout=settings.timeout_seconds)

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        response = await self._client.post(
            "/chat/completions",
            json={
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": self._settings.temperature,
                "seed": self._settings.seed,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
