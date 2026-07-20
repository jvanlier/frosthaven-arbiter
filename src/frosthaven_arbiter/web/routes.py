"""HTTP routes for the Frosthaven Arbiter web interface."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from frosthaven_arbiter.web.app import AppState

router = APIRouter()


def _state(request: Request) -> AppState:
    return request.app.state.arbiter_state


def _render_page(request: Request, state: AppState, template_name: str, context: dict):
    if request.headers.get("HX-Request") == "true":
        return state.templates.TemplateResponse(request, template_name, context)
    return state.templates.TemplateResponse(request, "layout.html", {**context, "content_template": template_name})


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    state = _state(request)
    conversations = state.conversations.list()
    return _render_page(request, state, "conversations_list.html", {"conversations": conversations})


@router.post("/conversations")
async def create_conversation(request: Request):
    state = _state(request)
    conversation_id = state.conversations.create()
    if request.headers.get("HX-Request") == "true":
        conversation = state.conversations.get(conversation_id)
        response = state.templates.TemplateResponse(
            request, "conversation.html", {"conversation": conversation}
        )
        response.headers["HX-Push-Url"] = f"/conversations/{conversation_id}"
        return response
    return {"id": conversation_id}


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def get_conversation(request: Request, conversation_id: int) -> HTMLResponse:
    state = _state(request)
    conversation = state.conversations.get(conversation_id)
    return _render_page(request, state, "conversation.html", {"conversation": conversation})


@router.post("/conversations/{conversation_id}/questions", response_class=HTMLResponse)
async def ask_question(request: Request, conversation_id: int) -> HTMLResponse:
    state = _state(request)
    form = await request.form()
    question = str(form.get("question", "")).strip()
    if not question:
        return HTMLResponse("<p class='error'>A question is required.</p>", status_code=400)
    result = await state.arbiter.ask(conversation_id, question)
    return state.templates.TemplateResponse(request, "message.html", {"outcome": result.outcome})


@router.delete("/conversations/{conversation_id}")
async def clear_conversation(request: Request, conversation_id: int):
    state = _state(request)
    state.conversations.clear(conversation_id)
    return {"cleared": True}


@router.get("/profile", response_class=HTMLResponse)
async def get_profile(request: Request) -> HTMLResponse:
    state = _state(request)
    profile = state.profile.get()
    scopes = state.profile.known_scopes()
    return _render_page(request, state, "profile.html", {"profile": profile, "scopes": scopes})


@router.put("/profile", response_class=HTMLResponse)
async def update_profile(request: Request) -> HTMLResponse:
    state = _state(request)
    form = await request.form()
    context_text = str(form.get("campaign_context", ""))
    unlocked = {str(key) for key in form.getlist("unlocked_scope_keys")}
    profile = state.profile.replace(context_text, unlocked)
    scopes = state.profile.known_scopes()
    return state.templates.TemplateResponse(
        request, "profile.html", {"profile": profile, "scopes": scopes, "saved": True}
    )
