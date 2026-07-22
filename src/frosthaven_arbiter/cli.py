"""Command-line entry points for the Frosthaven Arbiter.

This slice implements `sync` and `serve`. Model setup, process
supervision, and diagnostics are deferred to a later iteration.
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn

from frosthaven_arbiter.arbitration.arbiter import Arbiter
from frosthaven_arbiter.config import load_settings
from frosthaven_arbiter.conversations import ConversationHistory
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.inference import LlamaCppChatModel, LlamaCppEmbeddingModel
from frosthaven_arbiter.knowledge import KnowledgeBrowser
from frosthaven_arbiter.profile import ProfileManager
from frosthaven_arbiter.retrieval.authoritative import AuthoritativeRetrieval
from frosthaven_arbiter.sources.fetch import GitHubSourceFetcher
from frosthaven_arbiter.sources.sync import SourceSynchronizer
from frosthaven_arbiter.web.app import create_app


def _sync_command() -> None:
    settings = load_settings()
    database = Database(settings.paths.database)
    embedding_model = LlamaCppEmbeddingModel(settings.embedding_model)
    fetcher = GitHubSourceFetcher()
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    report = asyncio.run(synchronizer.sync())
    print(  # noqa: T201
        f"Activated {len(report.activated_revisions)} revision(s); "
        f"{len(report.unchanged_sources)} unchanged; "
        f"{report.chunks_added} chunks added, {report.chunks_reused} reused; "
        f"{report.embeddings_created} embeddings created; "
        f"{report.scopes_discovered} scopes discovered."
    )


def create_production_app():
    settings = load_settings()
    database = Database(settings.paths.database)
    embedding_model = LlamaCppEmbeddingModel(settings.embedding_model)
    chat_model = LlamaCppChatModel(settings.chat_model)
    retrieval = AuthoritativeRetrieval(database, embedding_model, settings.retrieval)
    arbiter = Arbiter(database, retrieval, chat_model, settings.paths.prompt, settings.paths.title_prompt)
    conversations = ConversationHistory(database)
    profile = ProfileManager(database)
    knowledge = KnowledgeBrowser(database)
    return create_app(arbiter, conversations, profile, knowledge)


def _serve_command() -> None:
    settings = load_settings()
    uvicorn.run(
        "frosthaven_arbiter.cli:create_production_app",
        host=settings.web.host,
        port=settings.web.port,
        reload=True,
        factory=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="frosthaven-arbiter")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sync", help="Synchronize Authoritative Sources")
    subparsers.add_parser("serve", help="Start the web interface")

    args = parser.parse_args()
    if args.command == "sync":
        _sync_command()
    elif args.command == "serve":
        _serve_command()


if __name__ == "__main__":
    main()
