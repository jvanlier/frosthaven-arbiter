"""Conversation and message persistence.

`ConversationHistory` is the single seam for creating conversations,
listing them, loading full transcripts, and clearing a conversation's
messages independently of profile and source data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import Citation, OutcomeKind, SourceKey


@dataclass(frozen=True)
class ConversationSummary:
    id: int
    title: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: int
    role: str
    status: str
    outcome_kind: OutcomeKind | None
    content: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Conversation:
    id: int
    title: str | None
    messages: tuple[Message, ...]


def _row_to_citation(row) -> Citation:
    return Citation(
        citation_id=row["citation_id"],
        source=SourceKey(row["source_key"]),
        source_title=row["source_title"],
        authority_label=row["authority_label"],
        heading_path=tuple(json.loads(row["heading_path_json"])),
        page_or_section=row["page_or_section"],
        anchor=row["anchor"],
        excerpt=row["excerpt"],
        revision=row["revision"],
        canonical_url=row["canonical_url"],
    )


class ConversationHistory:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, title: str | None = None) -> int:
        with self._database.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO conversations (title, created_at, updated_at) "
                "VALUES (?, datetime('now'), datetime('now'))",
                (title,),
            )
            new_id = cursor.lastrowid
            assert new_id is not None
            return new_id

    def list(self) -> tuple[ConversationSummary, ...]:
        with self._database.connect() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(ConversationSummary(row["id"], row["title"], row["created_at"], row["updated_at"]) for row in rows)

    def get(self, conversation_id: int) -> Conversation:
        with self._database.connect() as conn:
            conv_row = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if conv_row is None:
                raise KeyError(f"no conversation {conversation_id}")
            message_rows = conn.execute(
                "SELECT id, role, status, outcome_kind, content FROM messages "
                "WHERE conversation_id = ? ORDER BY sequence_no",
                (conversation_id,),
            ).fetchall()
            messages = []
            for message_row in message_rows:
                citation_rows = conn.execute(
                    "SELECT * FROM message_citations WHERE message_id = ? ORDER BY display_order",
                    (message_row["id"],),
                ).fetchall()
                messages.append(
                    Message(
                        id=message_row["id"],
                        role=message_row["role"],
                        status=message_row["status"],
                        outcome_kind=OutcomeKind(message_row["outcome_kind"]) if message_row["outcome_kind"] else None,
                        content=message_row["content"],
                        citations=tuple(_row_to_citation(row) for row in citation_rows),
                    )
                )
        return Conversation(id=conv_row["id"], title=conv_row["title"], messages=tuple(messages))

    def clear(self, conversation_id: int) -> None:
        with self._database.transaction() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )

    def set_title(self, conversation_id: int, title: str) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?",
                (title, conversation_id),
            )

    def recent_complete_messages(self, conversation_id: int, limit: int) -> tuple[Message, ...]:
        conversation = self.get(conversation_id)
        complete = [m for m in conversation.messages if m.status == "complete"]
        return tuple(complete[-limit:])
