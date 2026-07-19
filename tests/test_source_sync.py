"""Tests for source synchronization: revision pinning, idempotency,
incremental embedding, transactional activation, and spoiler invariants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey, Visibility
from frosthaven_arbiter.sources.sync import SourceSynchronizer

from .conftest import FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _rulebook_text() -> str:
    return (FIXTURES / "rulebook.md").read_text()


def _faq_text() -> str:
    return (FIXTURES / "faq.md").read_text()


@pytest.fixture
def fetcher() -> FakeSourceFetcher:
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, _rulebook_text())
    fetcher.register(SourceKey.FAQ, _faq_text())
    return fetcher


@pytest.fixture
def embedding_model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel()


async def test_first_sync_activates_both_sources(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)

    report = await synchronizer.sync()

    assert len(report.activated_revisions) == 2
    assert report.unchanged_sources == ()
    assert report.chunks_added > 0
    assert report.embeddings_created == report.chunks_added
    assert report.scopes_discovered >= 2

    with database.connect() as conn:
        sources = conn.execute("SELECT source_key, current_revision_id FROM sources").fetchall()
        for row in sources:
            assert row["current_revision_id"] is not None
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        assert chunk_count == report.chunks_added


async def test_unchanged_content_is_a_no_op(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()
    embedding_model.calls.clear()

    report = await synchronizer.sync()

    assert set(report.unchanged_sources) == {SourceKey.RULEBOOK, SourceKey.FAQ}
    assert report.chunks_added == 0
    assert embedding_model.calls == []


async def test_changed_content_reembeds_only_changed_chunks(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    changed_text = _rulebook_text() + "\n\n### New Section\n\nA brand new rule appears here.\n"
    fetcher.register(SourceKey.RULEBOOK, changed_text, commit_sha="second-commit")

    report = await synchronizer.sync()

    assert SourceKey.FAQ in report.unchanged_sources
    assert report.chunks_added >= 1
    with database.connect() as conn:
        revisions = conn.execute("SELECT COUNT(*) AS n FROM source_revisions WHERE source_key = 'rulebook'").fetchone()[
            "n"
        ]
        assert revisions == 2


async def test_protected_chunks_always_have_a_scope(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        protected_without_scope = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunks
            WHERE visibility = 'protected'
              AND id NOT IN (SELECT chunk_id FROM chunk_spoiler_scopes)
            """
        ).fetchone()["n"]
        assert protected_without_scope == 0

        public_with_scope = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunks
            WHERE visibility = 'public'
              AND id IN (SELECT chunk_id FROM chunk_spoiler_scopes)
            """
        ).fetchone()["n"]
        assert public_with_scope == 0


async def test_sticker_content_is_protected(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        row = conn.execute("SELECT visibility FROM chunks WHERE body LIKE '%must never leak%'").fetchone()
        assert row is not None
        assert row["visibility"] == Visibility.PROTECTED.value


async def test_failed_embedding_leaves_previous_index_active(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        original_revision = conn.execute(
            "SELECT current_revision_id FROM sources WHERE source_key = 'rulebook'"
        ).fetchone()["current_revision_id"]

    fetcher.register(SourceKey.RULEBOOK, _rulebook_text() + "\n\nmore text\n", commit_sha="broken-commit")

    class FailingEmbeddingModel(FakeEmbeddingModel):
        async def embed(self, texts):  # noqa: ARG002
            raise RuntimeError("embedding service unavailable")

    failing_model = FailingEmbeddingModel()
    failing_synchronizer = SourceSynchronizer(database, fetcher, failing_model, settings)

    with pytest.raises(RuntimeError):
        await failing_synchronizer.sync()

    with database.connect() as conn:
        current_revision = conn.execute(
            "SELECT current_revision_id FROM sources WHERE source_key = 'rulebook'"
        ).fetchone()["current_revision_id"]
        assert current_revision == original_revision
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE source_revision_id = ?", (current_revision,)
        ).fetchone()["n"]
        assert chunk_count > 0
