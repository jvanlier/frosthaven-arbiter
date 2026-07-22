"""Read-only browsing of indexed Authoritative Sources.

`KnowledgeBrowser` is the single seam for the Knowledge web view. It
exposes the current active revision of each source, its sections, and
its chunks in stored `position` order, so the browser can double as a
reference and as a diagnostic view for chunking and spoiler boundaries.

Spoiler visibility here follows the same rule as retrieval: a protected
chunk's body is only readable when every one of its Spoiler Scopes is
unlocked. Locked chunks still appear, with structural metadata intact,
so misclassified boundaries and scopes remain visible without leaking
protected text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey, Visibility


def embedding_input(heading_path: tuple[str, ...], body: str) -> str:
    """Reconstruct the exact text sent to the embedding model for a chunk.

    Must stay identical to `sources.sync._embedding_input()`; the two are
    tested against each other so this view never drifts from what was
    actually embedded.
    """
    heading = " > ".join(heading_path)
    return f"{heading}\n\n{body}" if heading else body


@dataclass(frozen=True)
class SourceSummary:
    source_key: SourceKey
    display_name: str
    authority_label: str
    canonical_url: str
    revision_id: int | None
    commit_sha: str | None
    retrieved_at: str | None
    total_chunks: int
    protected_chunks: int
    locked_chunks: int


@dataclass(frozen=True)
class SectionSummary:
    section_key: str
    heading_path: tuple[str, ...]
    first_position: int
    total_chunks: int
    protected_chunks: int
    locked_chunks: int


@dataclass(frozen=True)
class ChunkView:
    chunk_id: int
    position: int
    section_key: str
    heading_path: tuple[str, ...]
    anchor: str | None
    page_or_section: str | None
    token_count: int
    visibility: Visibility
    scope_keys: tuple[str, ...]
    scope_labels: tuple[str, ...]
    content_sha256: str
    revision_commit_sha: str | None
    readable: bool
    body: str | None
    embedding_input: str | None
    embedding_model_fingerprint: str | None
    embedding_input_sha256: str | None
    embedding_dimensions: int | None


class KnowledgeBrowser:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_sources(self, unlocked_scope_keys: frozenset[str]) -> tuple[SourceSummary, ...]:
        with self._database.connect() as conn:
            source_rows = conn.execute(
                "SELECT source_key, display_name, authority_label, canonical_url, "
                "current_revision_id FROM sources ORDER BY precedence"
            ).fetchall()
            summaries: list[SourceSummary] = []
            for row in source_rows:
                revision_id = row["current_revision_id"]
                revision_row = None
                if revision_id is not None:
                    revision_row = conn.execute(
                        "SELECT commit_sha, retrieved_at FROM source_revisions WHERE id = ?",
                        (revision_id,),
                    ).fetchone()
                total = protected = locked = 0
                if revision_id is not None:
                    chunk_rows = conn.execute(
                        "SELECT id, visibility FROM chunks WHERE source_revision_id = ?",
                        (revision_id,),
                    ).fetchall()
                    total = len(chunk_rows)
                    for chunk_row in chunk_rows:
                        if chunk_row["visibility"] == Visibility.PROTECTED.value:
                            protected += 1
                            if not self._is_readable(conn, chunk_row["id"], unlocked_scope_keys):
                                locked += 1
                summaries.append(
                    SourceSummary(
                        source_key=SourceKey(row["source_key"]),
                        display_name=row["display_name"],
                        authority_label=row["authority_label"],
                        canonical_url=row["canonical_url"],
                        revision_id=revision_id,
                        commit_sha=revision_row["commit_sha"] if revision_row else None,
                        retrieved_at=revision_row["retrieved_at"] if revision_row else None,
                        total_chunks=total,
                        protected_chunks=protected,
                        locked_chunks=locked,
                    )
                )
        return tuple(summaries)

    def list_sections(self, source: SourceKey, unlocked_scope_keys: frozenset[str]) -> tuple[SectionSummary, ...]:
        with self._database.connect() as conn:
            revision_id = self._active_revision_id(conn, source)
            if revision_id is None:
                return ()
            chunk_rows = conn.execute(
                "SELECT id, position, section_key, heading_path_json, visibility "
                "FROM chunks WHERE source_revision_id = ? ORDER BY position",
                (revision_id,),
            ).fetchall()
            sections: dict[str, dict] = {}
            order: list[str] = []
            for row in chunk_rows:
                key = row["section_key"]
                if key not in sections:
                    order.append(key)
                    sections[key] = {
                        "heading_path": tuple(json.loads(row["heading_path_json"])),
                        "first_position": row["position"],
                        "total": 0,
                        "protected": 0,
                        "locked": 0,
                    }
                bucket = sections[key]
                bucket["total"] += 1
                if row["visibility"] == Visibility.PROTECTED.value:
                    bucket["protected"] += 1
                    if not self._is_readable(conn, row["id"], unlocked_scope_keys):
                        bucket["locked"] += 1
        return tuple(
            SectionSummary(
                section_key=key,
                heading_path=sections[key]["heading_path"],
                first_position=sections[key]["first_position"],
                total_chunks=sections[key]["total"],
                protected_chunks=sections[key]["protected"],
                locked_chunks=sections[key]["locked"],
            )
            for key in order
        )

    def list_chunks(
        self, source: SourceKey, section_key: str, unlocked_scope_keys: frozenset[str]
    ) -> tuple[ChunkView, ...]:
        with self._database.connect() as conn:
            revision_id = self._active_revision_id(conn, source)
            if revision_id is None:
                return ()
            revision_row = conn.execute(
                "SELECT commit_sha FROM source_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            commit_sha = revision_row["commit_sha"] if revision_row else None
            chunk_rows = conn.execute(
                "SELECT * FROM chunks WHERE source_revision_id = ? AND section_key = ? ORDER BY position",
                (revision_id, section_key),
            ).fetchall()
            return tuple(self._to_chunk_view(conn, row, unlocked_scope_keys, commit_sha) for row in chunk_rows)

    def get_chunk(self, chunk_id: int, unlocked_scope_keys: frozenset[str]) -> ChunkView | None:
        with self._database.connect() as conn:
            row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
            if row is None:
                return None
            revision_row = conn.execute(
                "SELECT commit_sha FROM source_revisions WHERE id = ?", (row["source_revision_id"],)
            ).fetchone()
            commit_sha = revision_row["commit_sha"] if revision_row else None
            return self._to_chunk_view(conn, row, unlocked_scope_keys, commit_sha)

    def _active_revision_id(self, conn, source: SourceKey) -> int | None:
        row = conn.execute("SELECT current_revision_id FROM sources WHERE source_key = ?", (source.value,)).fetchone()
        return row["current_revision_id"] if row else None

    def _scope_rows(self, conn, chunk_id: int):
        return conn.execute(
            "SELECT spoiler_scopes.scope_key, spoiler_scopes.label FROM chunk_spoiler_scopes "
            "JOIN spoiler_scopes ON spoiler_scopes.scope_key = chunk_spoiler_scopes.scope_key "
            "WHERE chunk_spoiler_scopes.chunk_id = ? ORDER BY spoiler_scopes.label",
            (chunk_id,),
        ).fetchall()

    def _is_readable(self, conn, chunk_id: int, unlocked_scope_keys: frozenset[str]) -> bool:
        scope_rows = self._scope_rows(conn, chunk_id)
        if not scope_rows:
            return True
        return all(row["scope_key"] in unlocked_scope_keys for row in scope_rows)

    def _to_chunk_view(self, conn, row, unlocked_scope_keys: frozenset[str], commit_sha: str | None) -> ChunkView:
        scope_rows = self._scope_rows(conn, row["id"])
        visibility = Visibility(row["visibility"])
        readable = visibility == Visibility.PUBLIC or all(
            scope_row["scope_key"] in unlocked_scope_keys for scope_row in scope_rows
        )
        heading_path = tuple(json.loads(row["heading_path_json"]))

        embedding_row = conn.execute(
            "SELECT embeddings.model_fingerprint, embeddings.input_sha256, embeddings.dimensions "
            "FROM chunk_embeddings JOIN embeddings ON embeddings.id = chunk_embeddings.embedding_id "
            "WHERE chunk_embeddings.chunk_id = ?",
            (row["id"],),
        ).fetchone()

        return ChunkView(
            chunk_id=row["id"],
            position=row["position"],
            section_key=row["section_key"],
            heading_path=heading_path,
            anchor=row["anchor"],
            page_or_section=row["page_or_section"],
            token_count=row["token_count"],
            visibility=visibility,
            scope_keys=tuple(scope_row["scope_key"] for scope_row in scope_rows),
            scope_labels=tuple(scope_row["label"] for scope_row in scope_rows),
            content_sha256=row["content_sha256"],
            revision_commit_sha=commit_sha,
            readable=readable,
            body=row["body"] if readable else None,
            embedding_input=embedding_input(heading_path, row["body"]) if readable else None,
            embedding_model_fingerprint=embedding_row["model_fingerprint"] if embedding_row else None,
            embedding_input_sha256=embedding_row["input_sha256"] if embedding_row else None,
            embedding_dimensions=embedding_row["dimensions"] if embedding_row else None,
        )
