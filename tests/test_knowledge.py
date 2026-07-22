"""Tests for the read-only Knowledge browser service."""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey, Visibility
from frosthaven_arbiter.knowledge import KnowledgeBrowser, embedding_input
from frosthaven_arbiter.sources.sync import SourceSynchronizer

from .conftest import FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def indexed_database(database: Database, settings) -> Database:
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, (FIXTURES / "rulebook.md").read_text())
    fetcher.register(SourceKey.FAQ, (FIXTURES / "faq.md").read_text())
    await SourceSynchronizer(database, fetcher, FakeEmbeddingModel(), settings).sync()
    return database


def test_list_sources_returns_current_active_revisions(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)

    sources = browser.list_sources(frozenset())

    assert {s.source_key for s in sources} == {SourceKey.RULEBOOK, SourceKey.FAQ}
    for source in sources:
        assert source.revision_id is not None
        assert source.commit_sha is not None
        assert source.total_chunks > 0


def test_list_sources_counts_locked_protected_chunks(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)

    locked = browser.list_sources(frozenset())
    rulebook_locked = next(s for s in locked if s.source_key == SourceKey.RULEBOOK)
    assert rulebook_locked.protected_chunks >= 1
    assert rulebook_locked.locked_chunks == rulebook_locked.protected_chunks

    partially_unlocked = browser.list_sources(frozenset({"rulebook:sticker-4"}))
    rulebook_partially_unlocked = next(s for s in partially_unlocked if s.source_key == SourceKey.RULEBOOK)
    assert rulebook_partially_unlocked.locked_chunks == rulebook_locked.locked_chunks - 1

    all_fixture_scopes = frozenset(
        {"rulebook:sticker-1", "rulebook:sticker-3", "rulebook:sticker-4", "rulebook:sticker-13"}
    )
    fully_unlocked = browser.list_sources(all_fixture_scopes)
    rulebook_fully_unlocked = next(s for s in fully_unlocked if s.source_key == SourceKey.RULEBOOK)
    assert rulebook_fully_unlocked.locked_chunks == 0


def test_list_sections_orders_by_first_position(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)

    sections = browser.list_sections(SourceKey.RULEBOOK, frozenset())

    positions = [s.first_position for s in sections]
    assert positions == sorted(positions)


def test_list_sections_for_unsynchronized_source_is_empty(database: Database):
    browser = KnowledgeBrowser(database)

    assert browser.list_sections(SourceKey.RULEBOOK, frozenset()) == ()
    assert browser.list_sources(frozenset())[0].revision_id is None


def test_list_chunks_preserves_stored_position_order(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)
    sections = browser.list_sections(SourceKey.RULEBOOK, frozenset())
    road_events = next(s for s in sections if "Road Events" in s.heading_path)

    chunks = browser.list_chunks(SourceKey.RULEBOOK, road_events.section_key, frozenset())

    positions = [c.position for c in chunks]
    assert positions == sorted(positions)
    assert len(chunks) >= 1


def test_protected_chunk_is_locked_by_default(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)
    sections = browser.list_sections(SourceKey.RULEBOOK, frozenset())
    monster_section = next(s for s in sections if "Monster Movement" in s.heading_path)

    chunks = browser.list_chunks(SourceKey.RULEBOOK, monster_section.section_key, frozenset())
    protected = [c for c in chunks if c.visibility == Visibility.PROTECTED]

    assert protected
    for chunk in protected:
        assert chunk.readable is False
        assert chunk.body is None
        assert chunk.embedding_input is None
        assert chunk.scope_labels


def test_protected_chunk_becomes_readable_once_all_scopes_unlocked(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)
    sections = browser.list_sections(SourceKey.RULEBOOK, frozenset())
    monster_section = next(s for s in sections if "Monster Movement" in s.heading_path)

    chunks = browser.list_chunks(SourceKey.RULEBOOK, monster_section.section_key, frozenset({"rulebook:sticker-4"}))
    protected = next(c for c in chunks if c.visibility == Visibility.PROTECTED)

    assert protected.readable is True
    assert protected.body is not None
    assert "protected sticker content" in protected.body
    assert protected.embedding_input == embedding_input(protected.heading_path, protected.body)


def test_protected_chunk_requires_every_attached_scope(indexed_database: Database):
    with indexed_database.transaction() as conn:
        conn.execute(
            "INSERT INTO spoiler_scopes (scope_key, label, source_key, first_seen_revision_id) "
            "SELECT 'rulebook:extra-scope', 'Extra Scope', source_key, first_seen_revision_id "
            "FROM spoiler_scopes WHERE scope_key = 'rulebook:sticker-4'"
        )
        chunk_id = conn.execute(
            "SELECT chunk_id FROM chunk_spoiler_scopes WHERE scope_key = 'rulebook:sticker-4'"
        ).fetchone()["chunk_id"]
        conn.execute(
            "INSERT INTO chunk_spoiler_scopes (chunk_id, scope_key) VALUES (?, 'rulebook:extra-scope')",
            (chunk_id,),
        )

    browser = KnowledgeBrowser(indexed_database)
    chunk = browser.get_chunk(chunk_id, frozenset({"rulebook:sticker-4"}))
    assert chunk is not None
    assert chunk.readable is False

    chunk = browser.get_chunk(chunk_id, frozenset({"rulebook:sticker-4", "rulebook:extra-scope"}))
    assert chunk is not None
    assert chunk.readable is True


def test_embedding_metadata_matches_ingestion(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)
    sections = browser.list_sections(SourceKey.RULEBOOK, frozenset())
    road_events = next(s for s in sections if "Road Events" in s.heading_path)

    chunks = browser.list_chunks(SourceKey.RULEBOOK, road_events.section_key, frozenset())
    chunk = chunks[0]
    assert chunk.body is not None

    assert chunk.embedding_model_fingerprint == "fake-embedding-model"
    assert chunk.embedding_input_sha256 is not None
    assert chunk.embedding_dimensions == 16
    assert chunk.embedding_input == embedding_input(chunk.heading_path, chunk.body)


def test_get_chunk_returns_none_for_unknown_id(indexed_database: Database):
    browser = KnowledgeBrowser(indexed_database)

    assert browser.get_chunk(999999, frozenset()) is None
