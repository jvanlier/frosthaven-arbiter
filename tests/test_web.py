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
    arbiter = Arbiter(database, retrieval, chat_model, settings.paths.prompt, settings.paths.title_prompt)
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


def test_create_conversation_renders_new_conversation_for_htmx(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")

    response = client.post("/conversations", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert response.headers["HX-Push-Url"] == "/conversations/1"
    assert "Conversation 1" in response.text
    assert "Ask a rules question" in response.text
    assert "titling…" not in response.text


def test_ask_first_question_triggers_title_polling_via_oob_swap(indexed_database: Database, settings):
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
    assert 'hx-swap-oob="true"' in response.text
    assert "titling…" in response.text


def test_ask_second_question_does_not_retrigger_title_polling(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "ruling", "text": "Draw a road event card.", "citation_ids": ["E1"]}',
    )
    conversation_id = client.post("/conversations").json()["id"]
    client.post(f"/conversations/{conversation_id}/questions", data={"question": "First question?"})

    response = client.post(f"/conversations/{conversation_id}/questions", data={"question": "Second question?"})

    assert response.status_code == 200
    assert "hx-swap-oob" not in response.text
    assert "titling…" not in response.text


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


def test_delete_conversation(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.delete(f"/conversations/{conversation_id}/full")
    assert response.status_code == 200

    with pytest.raises(KeyError):
        ConversationHistory(indexed_database).get(conversation_id)


def test_delete_conversation_via_htmx_returns_conversation_list(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.delete(f"/conversations/{conversation_id}/full", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert response.headers["HX-Push-Url"] == "/"
    assert f"/conversations/{conversation_id}" not in response.text
    with pytest.raises(KeyError):
        ConversationHistory(indexed_database).get(conversation_id)


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


def test_reload_conversation_page_is_styled(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.get(f"/conversations/{conversation_id}")

    assert response.status_code == 200
    assert "Frosthaven Arbiter" in response.text
    assert 'href="/static/arbiter.css"' in response.text


def test_reload_profile_page_is_styled(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")

    response = client.get("/profile")

    assert response.status_code == 200
    assert "Frosthaven Arbiter" in response.text
    assert 'href="/static/arbiter.css"' in response.text


def test_htmx_conversation_returns_partial(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.get(f"/conversations/{conversation_id}", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<html>" not in response.text
    assert "Conversation 1" in response.text


def test_htmx_profile_returns_partial(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")

    response = client.get("/profile", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<html>" not in response.text
    assert "Campaign Context" in response.text


def test_conversation_page_has_back_button(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.get(f"/conversations/{conversation_id}")

    assert 'class="button"' in response.text
    assert 'hx-get="/" ' in response.text
    assert "← Back" in response.text


def test_profile_page_has_back_button(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")

    response = client.get("/profile")

    assert 'class="button"' in response.text
    assert 'hx-get="/" ' in response.text
    assert "← Back" in response.text


def test_title_endpoint_polling_when_null(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.get(f"/conversations/{conversation_id}/title")

    assert response.status_code == 200
    assert "hx-get" in response.text
    assert "hx-trigger" in response.text
    assert "titling…" in response.text


def test_citation_detail_page_renders(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "ruling", "text": "Draw a road event card.", "citation_ids": ["E1"]}',
    )
    conversation_id = client.post("/conversations").json()["id"]
    client.post(f"/conversations/{conversation_id}/questions", data={"question": "What happens during road events?"})
    conversation = ConversationHistory(indexed_database).get(conversation_id)
    message = next(m for m in conversation.messages if m.citations)
    citation = message.citations[0]

    response = client.get(f"/citations/{message.id}/{citation.citation_id}")

    assert response.status_code == 200
    assert citation.excerpt in response.text
    assert citation.source_title in response.text


def test_citation_detail_page_returns_404_for_unknown_citation(indexed_database: Database, settings):
    client = _make_client(indexed_database, settings, "{}")
    conversation_id = client.post("/conversations").json()["id"]

    response = client.get(f"/citations/{conversation_id}/E999")

    assert response.status_code == 404


def test_message_citation_link_targets_citation_page(indexed_database: Database, settings):
    client = _make_client(
        indexed_database,
        settings,
        '{"outcome": "ruling", "text": "Draw a road event card.", "citation_ids": ["E1"]}',
    )
    conversation_id = client.post("/conversations").json()["id"]

    response = client.post(
        f"/conversations/{conversation_id}/questions", data={"question": "What happens during road events?"}
    )

    conversation = ConversationHistory(indexed_database).get(conversation_id)
    message = next(m for m in conversation.messages if m.citations)
    assert f'href="/citations/{message.id}/E1"' in response.text


def test_title_endpoint_stops_polling_when_set(indexed_database: Database, settings):
    from frosthaven_arbiter.conversations import ConversationHistory

    conversations = ConversationHistory(indexed_database)
    conversation_id = conversations.create(title="My Campaign")

    client = _make_client(indexed_database, settings, "{}")
    response = client.get(f"/conversations/{conversation_id}/title")

    assert response.status_code == 200
    assert "hx-get" not in response.text
    assert "My Campaign" in response.text
