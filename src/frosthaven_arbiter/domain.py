"""Core domain types shared across the Frosthaven Arbiter.

These are plain, dependency-free data types. Modules that need richer
behavior (retrieval, arbitration, synchronization) define their own
internal types and depend on these only at their public seams.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class SourceKey(StrEnum):
    RULEBOOK = "rulebook"
    FAQ = "faq"


class OutcomeKind(StrEnum):
    RULING = "ruling"
    ABSTENTION = "abstention"


class Visibility(StrEnum):
    PUBLIC = "public"
    PROTECTED = "protected"


@dataclass(frozen=True)
class Profile:
    """The single saved Campaign Context and its Unlocked Scopes."""

    campaign_context: str
    unlocked_scope_keys: frozenset[str]


@dataclass(frozen=True)
class Citation:
    citation_id: str  # E1, E2, ... stable within one arbitration response
    source: SourceKey
    source_title: str
    authority_label: str
    heading_path: tuple[str, ...]
    page_or_section: str | None
    anchor: str | None
    excerpt: str
    revision: str
    canonical_url: str


@dataclass(frozen=True)
class Evidence:
    citation: Citation
    chunk_id: int
    prompt_text: str
    token_count: int
    precedence: int
    fused_rank: float


@dataclass(frozen=True)
class Ruling:
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Abstention:
    explanation: str
    relevant_evidence: tuple[Citation, ...] = field(default_factory=tuple)
    locked_scope_labels: tuple[str, ...] = field(default_factory=tuple)


Outcome = Ruling | Abstention


def evidence_texts(evidence: Sequence[Evidence]) -> tuple[str, ...]:
    return tuple(item.prompt_text for item in evidence)
