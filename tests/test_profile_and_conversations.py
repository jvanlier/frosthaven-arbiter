"""Tests for Campaign Context, Unlocked Scopes, and conversation persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import OutcomeKind, SourceKey
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


def test_delete_conversation_removes_it_and_its_messages(database: Database):
    conversations = ConversationHistory(database)
    conversation_id = conversations.create(title="To be deleted")
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, sequence_no, role, status, content, created_at) "
            "VALUES (?, 1, 'user', 'complete', 'hello', datetime('now'))",
            (conversation_id,),
        )

    conversations.delete(conversation_id)

    assert all(c.id != conversation_id for c in conversations.list())
    with pytest.raises(KeyError):
        conversations.get(conversation_id)
    with database.connect() as conn:
        message_count = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()["n"]
        assert message_count == 0


def _insert_completed_message(
    database: Database,
    conversation_id: int,
    sequence_no: int,
    outcome_kind: str,
    completed_at: str,
) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO messages "
            "(conversation_id, sequence_no, role, status, outcome_kind, content, created_at, completed_at) "
            "VALUES (?, ?, 'arbiter', 'complete', ?, 'answer', ?, ?)",
            (conversation_id, sequence_no, outcome_kind, completed_at, completed_at),
        )


def test_list_reports_the_most_recent_outcome_kind(database: Database):
    conversations = ConversationHistory(database)
    conversation_id = conversations.create(title="Two outcomes")
    _insert_completed_message(database, conversation_id, 1, "abstention", "2026-01-01 00:00:00")
    _insert_completed_message(database, conversation_id, 2, "ruling", "2026-01-02 00:00:00")

    summary = next(c for c in conversations.list() if c.id == conversation_id)

    assert summary.latest_outcome_kind == OutcomeKind.RULING


def test_list_reports_no_outcome_for_conversation_without_completed_outcomes(database: Database):
    conversations = ConversationHistory(database)
    conversation_id = conversations.create(title="No outcome yet")

    summary = next(c for c in conversations.list() if c.id == conversation_id)

    assert summary.latest_outcome_kind is None


def test_list_orders_by_latest_message_activity_not_only_stored_updated_at(database: Database):
    conversations = ConversationHistory(database)
    older_conversation_id = conversations.create(title="Older, but touched recently")
    newer_conversation_id = conversations.create(title="Newer, but untouched")

    # Simulate a follow-up question completing well after the conversation
    # row's own `updated_at` was last written, without going through
    # `set_title`/`clear` (which are the only seams that currently bump it).
    _insert_completed_message(database, older_conversation_id, 1, "ruling", "2030-01-01 00:00:00")

    listed_ids = [c.id for c in conversations.list()]

    assert listed_ids.index(older_conversation_id) < listed_ids.index(newer_conversation_id)
