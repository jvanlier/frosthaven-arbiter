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
    latest_outcome_kind: OutcomeKind | None


@dataclass(frozen=True)
class Message:
    id: int
    role: str
    status: str
    outcome_kind: OutcomeKind | None
    content: str
    created_at: str
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
                "WITH message_activity AS ("
                "  SELECT conversation_id, MAX(COALESCE(completed_at, created_at)) AS updated_at "
                "  FROM messages GROUP BY conversation_id"
                "), latest_outcomes AS ("
                "  SELECT conversation_id, outcome_kind, "
                "    ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY sequence_no DESC) AS recency "
                "  FROM messages WHERE status = 'complete' AND outcome_kind IS NOT NULL"
                ") "
                "SELECT conversations.id, conversations.title, conversations.created_at, "
                "  MAX(conversations.updated_at, COALESCE(message_activity.updated_at, conversations.updated_at)) "
                "    AS updated_at, "
                "  latest_outcomes.outcome_kind "
                "FROM conversations "
                "LEFT JOIN message_activity ON message_activity.conversation_id = conversations.id "
                "LEFT JOIN latest_outcomes ON latest_outcomes.conversation_id = conversations.id "
                "  AND latest_outcomes.recency = 1 "
                "ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(
            ConversationSummary(
                id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                latest_outcome_kind=OutcomeKind(row["outcome_kind"]) if row["outcome_kind"] else None,
            )
            for row in rows
        )

    def get(self, conversation_id: int) -> Conversation:
        with self._database.connect() as conn:
            conv_row = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if conv_row is None:
                raise KeyError(f"no conversation {conversation_id}")
            message_rows = conn.execute(
                "SELECT id, role, status, outcome_kind, content, created_at FROM messages "
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
                        created_at=message_row["created_at"],
                        citations=tuple(_row_to_citation(row) for row in citation_rows),
                    )
                )
        return Conversation(id=conv_row["id"], title=conv_row["title"], messages=tuple(messages))

    def get_citation(self, message_id: int, citation_id: str) -> Citation:
        with self._database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM message_citations WHERE message_id = ? AND citation_id = ?",
                (message_id, citation_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"no citation {citation_id} for message {message_id}")
            return _row_to_citation(row)

    def clear(self, conversation_id: int) -> None:
        with self._database.transaction() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute(
                "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                (conversation_id,),
            )

    def delete(self, conversation_id: int) -> None:
        with self._database.transaction() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

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
