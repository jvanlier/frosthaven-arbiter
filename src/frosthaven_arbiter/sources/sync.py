"""Source synchronization: the seam that indexes Authoritative Sources.

`SourceSynchronizer.sync()` fetches, parses, embeds, and atomically
activates a new revision for each configured source. Failure at any step
before activation leaves the previously active revision untouched.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from frosthaven_arbiter.config import Settings
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey
from frosthaven_arbiter.inference import EmbeddingModel
from frosthaven_arbiter.sources.fetch import FetchedSource, SourceFetcher
from frosthaven_arbiter.sources.parse import ParsedChunk, parse_source
from frosthaven_arbiter.sources.parse import approx_tokens as _approx_tokens


@dataclass(frozen=True)
class SyncReport:
    activated_revisions: tuple[str, ...]
    unchanged_sources: tuple[SourceKey, ...]
    chunks_added: int
    chunks_reused: int
    embeddings_created: int
    scopes_discovered: int


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _embedding_input(chunk: ParsedChunk) -> str:
    heading = " > ".join(chunk.heading_path)
    return f"{heading}\n\n{chunk.body}" if heading else chunk.body


class SourceSynchronizer:
    def __init__(
        self,
        database: Database,
        fetcher: SourceFetcher,
        embedding_model: EmbeddingModel,
        settings: Settings,
    ) -> None:
        self._database = database
        self._fetcher = fetcher
        self._embedding_model = embedding_model
        self._settings = settings

    async def sync(self) -> SyncReport:
        activated: list[str] = []
        unchanged: list[SourceKey] = []
        chunks_added = 0
        chunks_reused = 0
        embeddings_created = 0
        scopes_discovered: set[str] = set()

        for source in SourceKey:
            source_settings = self._settings.sources[source.value]
            fetched = await self._fetcher.fetch(source, source_settings)

            with self._database.connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM source_revisions WHERE source_key = ? AND content_sha256 = ?",
                    (source.value, fetched.content_sha256),
                ).fetchone()
            if existing is not None:
                unchanged.append(source)
                continue

            parsed_chunks = parse_source(source, fetched.content.decode("utf-8"))
            embedding_inputs = [_embedding_input(chunk) for chunk in parsed_chunks]
            input_hashes = [_content_hash(text) for text in embedding_inputs]

            with self._database.connect() as conn:
                cached_rows = conn.execute(
                    f"SELECT input_sha256 FROM embeddings WHERE model_fingerprint = ? "
                    f"AND input_sha256 IN ({','.join('?' * len(input_hashes))})"
                    if input_hashes
                    else "SELECT input_sha256 FROM embeddings WHERE 0",
                    [self._embedding_model.fingerprint, *input_hashes] if input_hashes else [],
                ).fetchall()
            cached_hashes = {row["input_sha256"] for row in cached_rows}

            texts_to_embed = [
                text for text, h in zip(embedding_inputs, input_hashes, strict=True) if h not in cached_hashes
            ]
            new_vectors = await self._embedding_model.embed(texts_to_embed) if texts_to_embed else None

            vector_by_hash: dict[str, tuple[list[float], float]] = {}
            if new_vectors is not None:
                idx = 0
                for text, h in zip(embedding_inputs, input_hashes, strict=True):
                    if h in cached_hashes:
                        continue
                    vector = new_vectors[idx]
                    idx += 1
                    norm = float((vector.astype("float64") ** 2).sum() ** 0.5) or 1.0
                    vector_by_hash[h] = (vector.tolist(), norm)

            with self._database.transaction() as conn:
                revision_id = self._activate_revision(conn, source, fetched)
                self._store_chunks(
                    conn,
                    source,
                    revision_id,
                    parsed_chunks,
                    embedding_inputs,
                    input_hashes,
                    vector_by_hash,
                    cached_hashes,
                    scopes_discovered,
                )
                conn.execute(
                    "UPDATE sources SET current_revision_id = ? WHERE source_key = ?",
                    (revision_id, source.value),
                )

            activated.append(fetched.commit_sha)
            chunks_added += sum(1 for h in input_hashes if h not in cached_hashes)
            chunks_reused += sum(1 for h in input_hashes if h in cached_hashes)
            embeddings_created += len(vector_by_hash)

        return SyncReport(
            activated_revisions=tuple(activated),
            unchanged_sources=tuple(unchanged),
            chunks_added=chunks_added,
            chunks_reused=chunks_reused,
            embeddings_created=embeddings_created,
            scopes_discovered=len(scopes_discovered),
        )

    def _activate_revision(self, conn, source: SourceKey, fetched: FetchedSource) -> int:
        cursor = conn.execute(
            "INSERT INTO source_revisions "
            "(source_key, commit_sha, declared_updated_at, retrieved_at, artifact_url, "
            "content_sha256, snapshot_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source.value,
                fetched.commit_sha,
                fetched.declared_updated_at,
                fetched.retrieved_at,
                fetched.artifact_url,
                fetched.content_sha256,
                self._write_snapshot(source, fetched),
            ),
        )
        revision_id = cursor.lastrowid
        assert revision_id is not None
        return revision_id

    def _write_snapshot(self, source: SourceKey, fetched: FetchedSource) -> str:
        snapshot_dir = self._settings.paths.snapshots
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{source.value}-{fetched.commit_sha}.md"
        snapshot_path.write_bytes(fetched.content)
        return str(snapshot_path)

    def _store_chunks(
        self,
        conn,
        source: SourceKey,
        revision_id: int,
        parsed_chunks: list[ParsedChunk],
        embedding_inputs: list[str],
        input_hashes: list[str],
        vector_by_hash: dict[str, tuple[list[float], float]],
        cached_hashes: set[str],
        scopes_discovered: set[str],
    ) -> None:
        for position, (chunk, embedding_input, input_hash) in enumerate(
            zip(parsed_chunks, embedding_inputs, input_hashes, strict=True)
        ):
            body_hash = _content_hash(chunk.body)
            cursor = conn.execute(
                "INSERT INTO chunks "
                "(source_revision_id, position, section_key, anchor, heading_path_json, "
                "page_or_section, body, search_text, token_count, content_sha256, visibility) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    revision_id,
                    position,
                    chunk.section_key,
                    chunk.anchor,
                    json.dumps(list(chunk.heading_path)),
                    chunk.page_or_section,
                    chunk.body,
                    chunk.body.lower(),
                    _approx_tokens(chunk.body),
                    body_hash,
                    chunk.visibility.value,
                ),
            )
            chunk_id = cursor.lastrowid

            for scope_key in chunk.scope_keys:
                scopes_discovered.add(scope_key)
                conn.execute(
                    "INSERT OR IGNORE INTO spoiler_scopes (scope_key, label, source_key, first_seen_revision_id) "
                    "VALUES (?, ?, ?, ?)",
                    (scope_key, _label_for_scope(scope_key), source.value, revision_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO chunk_spoiler_scopes (chunk_id, scope_key) VALUES (?, ?)",
                    (chunk_id, scope_key),
                )

            if input_hash in cached_hashes:
                embedding_row = conn.execute(
                    "SELECT id FROM embeddings WHERE model_fingerprint = ? AND input_sha256 = ?",
                    (self._embedding_model.fingerprint, input_hash),
                ).fetchone()
                embedding_id = embedding_row["id"]
            else:
                vector, norm = vector_by_hash[input_hash]
                import numpy as np

                blob = np.array(vector, dtype="<f4").tobytes()
                embed_cursor = conn.execute(
                    "INSERT INTO embeddings (model_fingerprint, input_sha256, dimensions, vector_f32, norm) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (self._embedding_model.fingerprint, input_hash, len(vector), blob, norm),
                )
                embedding_id = embed_cursor.lastrowid

            conn.execute(
                "INSERT INTO chunk_embeddings (chunk_id, embedding_id) VALUES (?, ?)",
                (chunk_id, embedding_id),
            )


def _label_for_scope(scope_key: str) -> str:
    parts = scope_key.split(":")
    return " ".join(p.replace("-", " ").title() for p in parts[1:])
