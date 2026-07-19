"""Fetching Authoritative Source revisions.

`SourceFetcher` is the seam between synchronization and the network. The
real adapter resolves the latest GitHub Pages deployment for a source
repository and downloads its revision-pinned `index.md`. Tests use a fake
implementation instead of reaching the network.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx

from frosthaven_arbiter.config import SourceSettings
from frosthaven_arbiter.domain import SourceKey


@dataclass(frozen=True)
class FetchedSource:
    source: SourceKey
    commit_sha: str
    declared_updated_at: str | None
    retrieved_at: str
    canonical_url: str
    artifact_url: str
    content: bytes

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


class SourceFetcher(Protocol):
    async def fetch(self, source: SourceKey, settings: SourceSettings) -> FetchedSource: ...


class GitHubSourceFetcher:
    """Fetches the latest deployed `index.md` for a source repository."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(timeout=30.0)

    async def fetch(self, source: SourceKey, settings: SourceSettings) -> FetchedSource:
        deployments_url = f"https://api.github.com/repos/{settings.repository}/deployments"
        response = await self._client.get(deployments_url, params={"environment": "github-pages"})
        response.raise_for_status()
        deployments = response.json()
        latest = next(d for d in deployments if d.get("ref") is not None)
        commit_sha = latest["sha"]

        artifact_url = f"https://raw.githubusercontent.com/{settings.repository}/{commit_sha}/{settings.path}"
        content_response = await self._client.get(artifact_url)
        content_response.raise_for_status()

        return FetchedSource(
            source=source,
            commit_sha=commit_sha,
            declared_updated_at=None,
            retrieved_at=datetime.now(UTC).isoformat(),
            canonical_url=settings.canonical_url,
            artifact_url=artifact_url,
            content=content_response.content,
        )
