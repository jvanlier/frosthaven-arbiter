"""HTTP routes for the Frosthaven Arbiter web interface."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from frosthaven_arbiter.domain import SourceKey
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
        response = state.templates.TemplateResponse(request, "conversation.html", {"conversation": conversation})
        response.headers["HX-Push-Url"] = f"/conversations/{conversation_id}"
        return response
    return {"id": conversation_id}


@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def get_conversation(request: Request, conversation_id: int) -> HTMLResponse:
    state = _state(request)
    conversation = state.conversations.get(conversation_id)
    return _render_page(request, state, "conversation.html", {"conversation": conversation})


@router.get("/conversations/{conversation_id}/title", response_class=HTMLResponse)
async def get_conversation_title(request: Request, conversation_id: int) -> HTMLResponse:
    state = _state(request)
    title = state.conversations.get_title(conversation_id)
    return state.templates.TemplateResponse(request, "title.html", {"conversation_id": conversation_id, "title": title})


@router.post("/conversations/{conversation_id}/questions", response_class=HTMLResponse)
async def ask_question(request: Request, conversation_id: int) -> HTMLResponse:
    state = _state(request)
    form = await request.form()
    question = str(form.get("question", "")).strip()
    if not question:
        return HTMLResponse("<p class='error'>A question is required.</p>", status_code=400)
    result = await state.arbiter.ask(conversation_id, question)
    conversation = state.conversations.get(conversation_id)
    return state.templates.TemplateResponse(
        request,
        "turn.html",
        {
            "messages": conversation.messages[-2:],
            "conversation_id": conversation_id,
            "titling_started": result.titling_started,
        },
    )


@router.post("/conversations/{conversation_id}/questions/stream")
async def ask_question_stream(request: Request, conversation_id: int) -> StreamingResponse:
    state = _state(request)
    form = await request.form()
    question = str(form.get("question", "")).strip()

    async def error_stream(message: str):
        yield json.dumps({"type": "error", "message": message}) + "\n"

    if not question:
        return StreamingResponse(
            error_stream("A question is required."), media_type="application/x-ndjson", status_code=400
        )

    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    def on_progress(stage: str, message: str) -> None:
        # `Arbiter.ask()` runs as a task on this same event loop, so the
        # callback fires on this loop/thread directly; no cross-thread
        # scheduling is needed, and using it here would reorder/drop
        # events relative to the queue.put() calls below.
        queue.put_nowait((stage, message))

    async def run_arbitration():
        try:
            result = await state.arbiter.ask(conversation_id, question, on_progress=on_progress)
            conversation = state.conversations.get(conversation_id)
            html = state.templates.env.get_template("turn.html").render(
                {
                    "messages": conversation.messages[-2:],
                    "conversation_id": conversation_id,
                    "titling_started": False,
                }
            )
            result_payload = {
                "type": "result",
                "html": html,
                "titling_started": result.titling_started,
            }
            await queue.put(("__result__", json.dumps(result_payload)))
        except Exception:
            error_payload = {"type": "error", "message": "The Arbiter could not process that question."}
            await queue.put(("__error__", json.dumps(error_payload)))
        finally:
            await queue.put(("__done__", ""))

    task = asyncio.create_task(run_arbitration())
    state.streaming_tasks.add(task)

    def _discard(finished_task: asyncio.Task) -> None:
        state.streaming_tasks.discard(finished_task)
        if not finished_task.cancelled():
            finished_task.exception()

    task.add_done_callback(_discard)

    async def event_stream():
        while True:
            stage, payload = await queue.get()
            if stage == "__done__":
                break
            if stage in ("__result__", "__error__"):
                yield payload + "\n"
            else:
                yield json.dumps({"type": "status", "stage": stage, "message": payload}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.delete("/conversations/{conversation_id}")
async def clear_conversation(request: Request, conversation_id: int):
    state = _state(request)
    state.conversations.clear(conversation_id)
    return {"cleared": True}


@router.delete("/conversations/{conversation_id}/full")
async def delete_conversation(request: Request, conversation_id: int):
    state = _state(request)
    state.conversations.delete(conversation_id)
    if request.headers.get("HX-Request") == "true":
        conversations = state.conversations.list()
        response = state.templates.TemplateResponse(
            request, "conversations_list.html", {"conversations": conversations}
        )
        response.headers["HX-Push-Url"] = "/"
        return response
    return {"deleted": True}


@router.get("/citations/{message_id}/{citation_id}", response_class=HTMLResponse)
async def get_citation(request: Request, message_id: int, citation_id: str) -> HTMLResponse:
    state = _state(request)
    try:
        citation = state.conversations.get_citation(message_id, citation_id)
    except KeyError:
        return HTMLResponse("<p class='error'>Citation not found.</p>", status_code=404)
    return _render_page(request, state, "citation.html", {"citation": citation})


@router.get("/knowledge", response_class=HTMLResponse)
async def get_knowledge(request: Request, source: str | None = None, section: str | None = None) -> HTMLResponse:
    state = _state(request)
    unlocked = state.profile.get().unlocked_scope_keys

    sources = state.knowledge.list_sources(unlocked)
    try:
        selected_source = SourceKey(source) if source else SourceKey.RULEBOOK
    except ValueError:
        selected_source = SourceKey.RULEBOOK

    sections = state.knowledge.list_sections(selected_source, unlocked)
    selected_section = (
        section
        if section and any(s.section_key == section for s in sections)
        else (sections[0].section_key if sections else None)
    )

    chunks = state.knowledge.list_chunks(selected_source, selected_section, unlocked) if selected_section else ()

    return _render_page(
        request,
        state,
        "knowledge.html",
        {
            "sources": sources,
            "selected_source": selected_source,
            "sections": sections,
            "selected_section": selected_section,
            "chunks": chunks,
        },
    )


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
