"""Configuration loading for the Frosthaven Arbiter.

Loads version-controlled defaults, an optional machine-specific override
file, and validates the merged result. Callers depend on `Settings` only;
they do not read TOML themselves.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DEFAULTS_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "defaults.toml"
_PROMPT_ENV_VAR = "FROSTHAVEN_ARBITER_CONFIG"


@dataclass(frozen=True)
class PathSettings:
    database: Path
    snapshots: Path
    prompt: Path


@dataclass(frozen=True)
class WebSettings:
    host: str
    port: int


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model_path: str
    timeout_seconds: float
    context_size: int = 0
    temperature: float = 0.0
    seed: int = 1
    batch_size: int = 1


@dataclass(frozen=True)
class RetrievalSettings:
    lexical_candidates: int
    semantic_candidates: int
    final_chunks: int
    rrf_k: int
    evidence_token_budget: int
    adjacency_limit: int


@dataclass(frozen=True)
class SourceSettings:
    canonical_url: str
    repository: str
    path: str


@dataclass(frozen=True)
class Settings:
    paths: PathSettings
    web: WebSettings
    embedding_model: ModelSettings
    chat_model: ModelSettings
    retrieval: RetrievalSettings
    sources: dict[str, SourceSettings]

    def validate(self) -> None:
        if self.web.host != "127.0.0.1":
            raise ValueError("web.host must be 127.0.0.1 (loopback-only default)")
        if self.embedding_model.base_url == self.chat_model.base_url:
            raise ValueError("embedding and chat model base_url must differ")
        if self.retrieval.final_chunks <= 0:
            raise ValueError("retrieval.final_chunks must be positive")
        if self.retrieval.evidence_token_budget <= 0:
            raise ValueError("retrieval.evidence_token_budget must be positive")


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(defaults_path: Path | None = None, override_path: Path | None = None) -> Settings:
    path = defaults_path or _DEFAULTS_PATH
    with path.open("rb") as fh:
        raw = tomllib.load(fh)

    override_env = os.environ.get(_PROMPT_ENV_VAR)
    override_file = override_path or (Path(override_env) if override_env else None)
    if override_file and override_file.exists():
        with override_file.open("rb") as fh:
            raw = _merge(raw, tomllib.load(fh))

    root = path.parent.parent
    raw_paths: dict[str, Any] = raw["paths"]
    raw_web: dict[str, Any] = raw["web"]
    paths = PathSettings(
        database=(root / raw_paths["database"]).resolve(),
        snapshots=(root / raw_paths["snapshots"]).resolve(),
        prompt=(root / raw_paths["prompt"]).resolve(),
    )
    web = WebSettings(host=raw_web["host"], port=int(raw_web["port"]))
    models: dict[str, Any] = raw["models"]
    embedding_model = ModelSettings(**models["embedding"])
    chat_model = ModelSettings(**models["chat"])
    retrieval = RetrievalSettings(**raw["retrieval"])
    raw_sources: dict[str, Any] = raw["sources"]
    sources = {key: SourceSettings(**value) for key, value in raw_sources.items()}

    settings = Settings(
        paths=paths,
        web=web,
        embedding_model=embedding_model,
        chat_model=chat_model,
        retrieval=retrieval,
        sources=sources,
    )
    settings.validate()
    return settings
