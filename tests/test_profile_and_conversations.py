"""Tests for Campaign Context, Unlocked Scopes, and conversation persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.profile import ProfileManager, UnknownScopeError
from frosthaven_arbiter.sources.sync import SourceSynchronizer

from .conftest import FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def test_profile_persists_across_reopen(tmp_path: Path):
    db_path = tmp_path / "arbiter.sqlite3"
    database = Database(db_path)
    profile = ProfileManager(database)
    profile.replace("The party is on scenario 12.", set())

    reopened = Database(db_path)
    reopened_profile = ProfileManager(reopened)
    assert reopened_profile.get().campaign_context == "The party is on scenario 12."


def test_unknown_scope_key_is_rejected(database: Database):
    profile = ProfileManager(database)
    with pytest.raises(UnknownScopeError):
        profile.replace("context", {"nonexistent:scope"})


async def test_clearing_conversation_preserves_profile_and_sources(database: Database, settings):
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, (FIXTURES / "rulebook.md").read_text())
    fetcher.register(SourceKey.FAQ, (FIXTURES / "faq.md").read_text())
    synchronizer = SourceSynchronizer(database, fetcher, FakeEmbeddingModel(), settings)
    await synchronizer.sync()

    profile = ProfileManager(database)
    profile.replace("Campaign notes", set())

    conversations = ConversationHistory(database)
    conversation_id = conversations.create()
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, sequence_no, role, status, content, created_at) "
            "VALUES (?, 1, 'user', 'complete', 'hello', datetime('now'))",
            (conversation_id,),
        )

    conversations.clear(conversation_id)

    assert conversations.get(conversation_id).messages == ()
    assert profile.get().campaign_context == "Campaign notes"
    with database.connect() as conn:
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        assert chunk_count > 0


def test_conversation_create_list_and_get(database: Database):
    conversations = ConversationHistory(database)
    conversation_id = conversations.create(title="Test conversation")

    listed = conversations.list()
    assert any(c.id == conversation_id and c.title == "Test conversation" for c in listed)

    conversation = conversations.get(conversation_id)
    assert conversation.id == conversation_id
    assert conversation.messages == ()


def test_get_missing_conversation_raises(database: Database):
    conversations = ConversationHistory(database)
    with pytest.raises(KeyError):
        conversations.get(999)
