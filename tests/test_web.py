"""Tests for the FastAPI web slice: profile editing, question flow,
citation rendering, and clear-chat behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from frosthaven_arbiter.arbitration.arbiter import Arbiter
from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.profile import ProfileManager
from frosthaven_arbiter.retrieval.authoritative import AuthoritativeRetrieval
from frosthaven_arbiter.sources.sync import SourceSynchronizer
from frosthaven_arbiter.web.app import create_app

from .conftest import FakeChatModel, FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def indexed_database(database: Database, settings) -> Database:
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, (FIXTURES / "rulebook.md").read_text())
    fetcher.register(SourceKey.FAQ, (FIXTURES / "faq.md").read_text())
    await SourceSynchronizer(database, fetcher, FakeEmbeddingModel(), settings).sync()
    return database


def _make_client(database: Database, settings, chat_response: str) -> TestClient:
    retrieval = AuthoritativeRetrieval(database, FakeEmbeddingModel(), settings.retrieval)
    chat_model = FakeChatModel(response=chat_response)
    arbiter = Arbiter(database, retrieval, chat_model, settings.paths.prompt)
    conversations = ConversationHistory(database)
    profile = ProfileManager(database)
    app = create_app(arbiter, conversations, profile)
    return TestClient(app)


def test_index_page_loads(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    response = client.get("/")
    assert response.status_code == 200
    assert "Frosthaven Arbiter" in response.text


def test_stylesheet_is_served(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    response = client.get("/static/arbiter.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "--parchment" in response.text


def test_create_and_view_conversation(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    created = client.post("/conversations")
    assert created.status_code == 200
    conversation_id = created.json()["id"]

    response = client.get(f"/conversations/{conversation_id}")
    assert response.status_code == 200


def test_ask_question_returns_ruling_html(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "ruling", "text": "Draw a road event card.", "citation_ids": ["E1"]}',
    )
    conversation_id = client.post("/conversations").json()["id"]

    response = client.post(
        f"/conversations/{conversation_id}/questions", data={"question": "What happens during road events?"}
    )

    assert response.status_code == 200
    assert "badge-ruling" in response.text
    assert "Draw a road event card" in response.text


def test_ask_question_returns_abstention_html(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "abstention", "text": "No evidence resolves this.", "citation_ids": []}',
    )
    conversation_id = client.post("/conversations").json()["id"]

    response = client.post(f"/conversations/{conversation_id}/questions", data={"question": "Best strategy for act 3?"})

    assert response.status_code == 200
    assert "badge-abstention" in response.text


def test_empty_question_is_rejected(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.post(f"/conversations/{conversation_id}/questions", data={"question": "   "})

    assert response.status_code == 400


def test_profile_get_and_update(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    response = client.get("/profile")
    assert response.status_code == 200

    update = client.put("/profile", data={"campaign_context": "New campaign notes"})
    assert update.status_code == 200
    assert "New campaign notes" in update.text
    assert "saved-notice" in update.text


def test_clear_conversation(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "abstention", "text": "No evidence resolves this.", "citation_ids": []}',
    )
    conversation_id = client.post("/conversations").json()["id"]
    client.post(f"/conversations/{conversation_id}/questions", data={"question": "Anything?"})

    response = client.delete(f"/conversations/{conversation_id}")
    assert response.status_code == 200

    conversation = ConversationHistory(indexed_database).get(conversation_id)
    assert conversation.messages == ()


def test_model_text_is_escaped(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "abstention", "text": "<script>alert(1)</script>", "citation_ids": []}',
    )
    conversation_id = client.post("/conversations").json()["id"]

    response = client.post(f"/conversations/{conversation_id}/questions", data={"question": "hostile?"})

    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
