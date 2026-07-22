"""Opt-in browser-driven end-to-end test for the "Ask the Arbiter" flow.

These tests drive a real Chromium browser against a real (locally bound)
uvicorn server backed by fake model/source adapters. They exist to catch
client-side JavaScript bugs -- like disabled form fields being silently
excluded from FormData -- that a server-only TestClient cannot detect.

Excluded from the default `uv run pytest` run (see `addopts` in
pyproject.toml). Run explicitly with:

    uv run playwright install chromium   # one-time, local only
    uv run pytest -m e2e -q --no-cov

`--no-cov` avoids a spurious coverage-floor failure: the repo-wide 80%
coverage floor is calibrated against the full default suite, and running
only these two e2e tests in isolation covers far less of the codebase.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect

from frosthaven_arbiter.arbitration.arbiter import Arbiter
from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.inference import ChatMessage
from frosthaven_arbiter.knowledge import KnowledgeBrowser
from frosthaven_arbiter.profile import ProfileManager
from frosthaven_arbiter.retrieval.authoritative import AuthoritativeRetrieval
from frosthaven_arbiter.sources.sync import SourceSynchronizer
from frosthaven_arbiter.web.app import create_app

from .conftest import FakeChatModel, FakeEmbeddingModel, FakeSourceFetcher

pytestmark = pytest.mark.e2e

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass
class _SlowFakeChatModel(FakeChatModel):
    """Adds an artificial delay so transient busy/loading UI states can be
    reliably observed by the browser. The fake local model normally
    responds fast enough that Playwright's polling assertions would race
    against completion.
    """

    delay_seconds: float = 0.6

    async def complete(self, messages: Sequence[ChatMessage]) -> str:
        await asyncio.sleep(self.delay_seconds)
        return await super().complete(messages)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run_async(coro) -> None:
    """Run a coroutine to completion on a fresh event loop in its own thread.

    Playwright's sync API keeps an event loop running in the main test
    thread for the duration of the `page` fixture, so a plain
    `asyncio.run()` call here would raise "cannot be called from a running
    event loop". Running it on a dedicated thread avoids that conflict.
    """
    error: list[BaseException] = []

    def _target() -> None:
        try:
            asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the calling thread below
            error.append(exc)

    thread = threading.Thread(target=_target)
    thread.start()
    thread.join()
    if error:
        raise error[0]


class _LiveServer:
    """Runs a real uvicorn server for the given app in a background thread."""

    def __init__(self, app, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        while not self._server.started:
            pass

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5)


@pytest.fixture
def live_arbiter_server(tmp_path: Path, settings) -> Iterator[tuple[str, FakeChatModel]]:
    database = Database(tmp_path / "arbiter.sqlite3")
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, (FIXTURES / "rulebook.md").read_text())
    fetcher.register(SourceKey.FAQ, (FIXTURES / "faq.md").read_text())
    _run_async(SourceSynchronizer(database, fetcher, FakeEmbeddingModel(), settings).sync())

    retrieval = AuthoritativeRetrieval(database, FakeEmbeddingModel(), settings.retrieval)
    chat_model = _SlowFakeChatModel(
        responses=[
            '{"outcome": "ruling", "text": "Draw a road event card [E1].", "citation_ids": ["E1"]}',
            "Road Events",
        ]
    )
    arbiter = Arbiter(database, retrieval, chat_model, settings.paths.prompt, settings.paths.title_prompt)
    conversations = ConversationHistory(database)
    profile = ProfileManager(database)
    knowledge = KnowledgeBrowser(database)
    app = create_app(arbiter, conversations, profile, knowledge)

    server = _LiveServer(app, _free_port())
    server.start()
    try:
        yield server.base_url, chat_model
    finally:
        server.stop()


def test_ask_question_streams_and_renders_ruling(page: Page, live_arbiter_server: tuple[str, FakeChatModel]) -> None:
    base_url, _ = live_arbiter_server
    page.goto(base_url)
    page.get_by_role("button", name="New conversation").click()
    page.wait_for_url("**/conversations/*")

    textarea = page.locator("textarea#question")
    button = page.get_by_role("button", name="Ask the Arbiter")
    overlay = page.locator(".loading-overlay")
    status = page.locator(".loading-status")

    textarea.fill("Can I get rid of Bane by long resting?")
    button.click()

    # The regression check: this exercises the exact code path that broke
    # (disabling the textarea before capturing FormData). If that bug
    # reappears, the server receives an empty question and the final
    # assertions below fail because "A question is required." is shown
    # instead of a ruling.
    expect(overlay).to_be_visible()
    expect(textarea).to_be_disabled()
    expect(button).to_be_disabled()
    # The "searching"/"reviewing"/"generating" stages complete almost
    # instantly against the fake retrieval/model; only the artificial delay
    # inside `_SlowFakeChatModel.complete()` reliably keeps the UI in the
    # "generating" stage long enough to observe. Exact intermediate wording
    # for the fast stages is not asserted here to avoid test flakiness.
    expect(status).to_have_text("Preparing a ruling from the evidence")

    expect(overlay).to_be_hidden(timeout=5000)
    expect(page.locator("#messages .badge-ruling")).to_be_visible()
    expect(page.locator("#messages")).to_contain_text("Draw a road event card")
    expect(page.locator("#messages .error")).to_have_count(0)

    expect(textarea).to_have_value("")
    expect(textarea).to_be_enabled()
    expect(button).to_be_enabled()


def test_double_submit_is_prevented(page: Page, live_arbiter_server: tuple[str, FakeChatModel]) -> None:
    base_url, _ = live_arbiter_server
    page.goto(base_url)
    page.get_by_role("button", name="New conversation").click()
    page.wait_for_url("**/conversations/*")

    textarea = page.locator("textarea#question")
    button = page.get_by_role("button", name="Ask the Arbiter")

    textarea.fill("Can I get rid of Bane by long resting?")
    button.click(force=True)
    button.click(force=True)

    expect(page.locator(".loading-overlay")).to_be_hidden(timeout=5000)
    expect(page.locator("#messages .message-arbiter")).to_have_count(1)
