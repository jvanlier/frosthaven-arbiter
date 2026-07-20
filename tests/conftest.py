"""Shared fixtures and fakes for Frosthaven Arbiter tests."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

from frosthaven_arbiter.config import (
    ModelSettings,
    PathSettings,
    RetrievalSettings,
    Settings,
    SourceSettings,
    WebSettings,
)
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.inference import ChatMessage
from frosthaven_arbiter.sources.fetch import FetchedSource


@pytest.fixture
def database(tmp_path: Path) -> Database:
    return Database(tmp_path / "arbiter.sqlite3")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        paths=PathSettings(
            database=tmp_path / "arbiter.sqlite3",
            snapshots=tmp_path / "snapshots",
            prompt=Path(__file__).resolve().parent.parent / "config" / "arbitration-prompt.txt",
            title_prompt=Path(__file__).resolve().parent.parent / "config" / "title-prompt.txt",
        ),
        web=WebSettings(host="127.0.0.1", port=8088),
        embedding_model=ModelSettings(base_url="http://127.0.0.1:9001/v1", model_path="fake-embed", timeout_seconds=5),
        chat_model=ModelSettings(base_url="http://127.0.0.1:9002/v1", model_path="fake-chat", timeout_seconds=5),
        retrieval=RetrievalSettings(
            lexical_candidates=10,
            semantic_candidates=10,
            final_chunks=8,
            rrf_k=60,
            evidence_token_budget=6000,
            adjacency_limit=2,
        ),
        sources={
            "rulebook": SourceSettings(
                canonical_url="https://example.test/rulebook/", repository="test/rulebook", path="index.md"
            ),
            "faq": SourceSettings(canonical_url="https://example.test/faq/", repository="test/faq", path="index.md"),
        },
    )


@dataclass
class FakeSourceFetcher:
    """Records fetch calls and returns pre-registered fixture content."""

    content_by_source: dict[SourceKey, bytes] = field(default_factory=dict)
    commit_by_source: dict[SourceKey, str] = field(default_factory=dict)
    calls: list[SourceKey] = field(default_factory=list)

    def register(self, source: SourceKey, content: str, commit_sha: str | None = None) -> None:
        self.content_by_source[source] = content.encode("utf-8")
        self.commit_by_source[source] = commit_sha or hashlib.sha1(content.encode()).hexdigest()[:12]

    async def fetch(self, source: SourceKey, settings: SourceSettings) -> FetchedSource:
        self.calls.append(source)
        content = self.content_by_source[source]
        return FetchedSource(
            source=source,
            commit_sha=self.commit_by_source[source],
            declared_updated_at=None,
            retrieved_at="2026-01-01T00:00:00+00:00",
            canonical_url=settings.canonical_url,
            artifact_url=f"https://example.test/{source.value}/index.md",
            content=content,
        )


@dataclass
class FakeEmbeddingModel:
    """Deterministic embeddings keyed by a hash of the input text."""

    dimensions: int = 16
    calls: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        return "fake-embedding-model"

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            self.calls.append(text)
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            vectors.append(rng.normal(size=self.dimensions).astype(np.float32))
        return np.array(vectors, dtype=np.float32)


@dataclass
class FakeChatModel:
    """Returns a pre-scripted response, recording every call's messages."""

    response: str = '{"outcome": "abstention", "text": "no evidence", "citation_ids": []}'
    responses: list[str] | None = None
    calls: list[list[ChatMessage]] = field(default_factory=list)
    raise_error: bool = False

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        if self.raise_error:
            raise RuntimeError("model unavailable")
        if self.responses is not None:
            return self.responses.pop(0)
        return self.response
