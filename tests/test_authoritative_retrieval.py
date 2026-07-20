"""Tests for spoiler-safe hybrid retrieval of authoritative evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.profile import ProfileManager
from frosthaven_arbiter.retrieval.authoritative import AuthoritativeRetrieval
from frosthaven_arbiter.sources.sync import SourceSynchronizer

from .conftest import FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def indexed_database(database: Database, settings) -> Database:
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, (FIXTURES / "rulebook.md").read_text())
    fetcher.register(SourceKey.FAQ, (FIXTURES / "faq.md").read_text())
    embedding_model = FakeEmbeddingModel()
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()
    return database


async def test_lexical_match_is_retrieved(indexed_database: Database, settings):
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), settings.retrieval)

    evidence = await retrieval.retrieve("road events travels between locations", frozenset())

    assert any("Road events occur" in item.citation.excerpt for item in evidence)


async def test_lexical_match_handles_inflected_question_terms(indexed_database: Database, settings):
    lexical_only = settings.retrieval.__class__(
        lexical_candidates=settings.retrieval.lexical_candidates,
        semantic_candidates=0,
        final_chunks=settings.retrieval.final_chunks,
        rrf_k=settings.retrieval.rrf_k,
        evidence_token_budget=settings.retrieval.evidence_token_budget,
        adjacency_limit=settings.retrieval.adjacency_limit,
    )
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), lexical_only)

    evidence = await retrieval.retrieve("How do monsters move?", frozenset())

    assert any(item.citation.heading_path[-1] == "Monster Movement" for item in evidence)


async def test_locked_content_never_appears_in_evidence(indexed_database: Database, settings):
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), settings.retrieval)

    evidence = await retrieval.retrieve("locked scenario reward sticker", frozenset())

    assert all("must never leak" not in item.citation.excerpt for item in evidence)
    assert all("Astral" not in item.citation.excerpt for item in evidence)


async def test_naming_locked_scope_does_not_unlock_it(indexed_database: Database, settings):
    profile = ProfileManager(indexed_database)
    before = profile.get().unlocked_scope_keys

    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), settings.retrieval)
    await retrieval.retrieve("Tell me about Sticker 4 and the locked class Astral", frozenset())

    after = profile.get().unlocked_scope_keys
    assert before == after == frozenset()


async def test_unlocking_scope_makes_evidence_eligible(indexed_database: Database, settings):
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), settings.retrieval)

    locked = await retrieval.retrieve("protected sticker content locked scenario reward", frozenset())
    assert all("must never leak" not in item.citation.excerpt for item in locked)

    unlocked = await retrieval.retrieve(
        "protected sticker content locked scenario reward", frozenset({"rulebook:sticker-4"})
    )
    assert any("must never leak" in item.citation.excerpt for item in unlocked)


async def test_evidence_respects_token_budget(indexed_database: Database, settings):
    tiny_settings = settings.retrieval
    tiny_settings = tiny_settings.__class__(
        lexical_candidates=tiny_settings.lexical_candidates,
        semantic_candidates=tiny_settings.semantic_candidates,
        final_chunks=8,
        rrf_k=tiny_settings.rrf_k,
        evidence_token_budget=5,
        adjacency_limit=0,
    )
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), tiny_settings)

    evidence = await retrieval.retrieve("road events", frozenset())

    total_tokens = sum(item.token_count for item in evidence)
    assert total_tokens <= tiny_settings.evidence_token_budget


async def test_stable_citation_ids_map_to_same_chunks(indexed_database: Database, settings):
    retrieval = AuthoritativeRetrieval(indexed_database, FakeEmbeddingModel(), settings.retrieval)

    first = await retrieval.retrieve("road events", frozenset())
    second = await retrieval.retrieve("road events", frozenset())

    first_map = {item.citation.citation_id: item.chunk_id for item in first}
    second_map = {item.citation.citation_id: item.chunk_id for item in second}
    assert first_map == second_map
