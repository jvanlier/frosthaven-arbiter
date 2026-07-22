"""FastAPI application wiring for the Frosthaven Arbiter.

`create_app()` is the single seam for constructing the ASGI app from
already-built dependencies. Production wiring (real database, model
adapters) happens in `frosthaven_arbiter.cli`; tests build fakes and pass
them here directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

from frosthaven_arbiter.arbitration.arbiter import Arbiter
from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.knowledge import KnowledgeBrowser
from frosthaven_arbiter.profile import ProfileManager

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_MESSAGE_MARKDOWN = MarkdownIt("commonmark", {"html": False})


def _render_message_markdown(text: str) -> Markup:
    return Markup(_MESSAGE_MARKDOWN.render(text))


@dataclass
class AppState:
    arbiter: Arbiter
    conversations: ConversationHistory
    profile: ProfileManager
    knowledge: KnowledgeBrowser
    templates: Jinja2Templates
    streaming_tasks: set[asyncio.Task] = field(default_factory=set)


def create_app(
    arbiter: Arbiter,
    conversations: ConversationHistory,
    profile: ProfileManager,
    knowledge: KnowledgeBrowser,
) -> FastAPI:
    from frosthaven_arbiter.web.routes import router

    app = FastAPI(title="Frosthaven Arbiter")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["message_markdown"] = _render_message_markdown
    app.state.arbiter_state = AppState(
        arbiter=arbiter,
        conversations=conversations,
        profile=profile,
        knowledge=knowledge,
        templates=templates,
    )
    app.include_router(router)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    return app
