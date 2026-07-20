"""Spoiler-safe hybrid retrieval of Authoritative Source evidence.

`AuthoritativeRetrieval.retrieve()` is the single deep interface used by
arbitration. It hides eligibility filtering, lexical and dense candidate
generation, reciprocal-rank fusion, FAQ precedence, adjacency expansion,
and token budgeting.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import numpy as np

from frosthaven_arbiter.config import RetrievalSettings
from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import Citation, Evidence, SourceKey
from frosthaven_arbiter.inference import EmbeddingModel

_QUESTION_FILLER = frozenset(
    {
        "a",
        "an",
        "are",
        "can",
        "could",
        "do",
        "does",
        "how",
        "i",
        "if",
        "is",
        "me",
        "my",
        "of",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
    }
)


@dataclass(frozen=True)
class _Candidate:
    chunk_id: int
    source_key: str
    precedence: int
    section_key: str
    position: int
    body: str
    heading_path: tuple[str, ...]
    page_or_section: str | None
    anchor: str | None
    token_count: int
    revision_id: int
    commit_sha: str
    canonical_url: str
    display_name: str
    authority_label: str


def _eligibility_clause(unlocked_scope_keys: frozenset[str]) -> tuple[str, list[str]]:
    """Chunks are eligible only if every attached spoiler scope is unlocked.

    Uses the caller-supplied Unlocked Scopes rather than reading persisted
    state, so retrieval always reflects exactly the scopes the caller
    passed in.
    """
    if unlocked_scope_keys:
        placeholders = ",".join("?" * len(unlocked_scope_keys))
        clause = (
            "chunks.id NOT IN ("
            "SELECT css.chunk_id FROM chunk_spoiler_scopes css "
            f"WHERE css.scope_key NOT IN ({placeholders})"
            ")"
        )
        return clause, list(unlocked_scope_keys)
    clause = "chunks.id NOT IN (SELECT css.chunk_id FROM chunk_spoiler_scopes css)"
    return clause, []


class AuthoritativeRetrieval:
    def __init__(self, database: Database, embedding_model: EmbeddingModel, settings: RetrievalSettings) -> None:
        self._database = database
        self._embedding_model = embedding_model
        self._settings = settings

    async def retrieve(self, question: str, unlocked_scope_keys: frozenset[str]) -> tuple[Evidence, ...]:
        with self._database.connect() as conn:
            current_revisions = {
                row["source_key"]: row["current_revision_id"]
                for row in conn.execute(
                    "SELECT source_key, current_revision_id FROM sources WHERE current_revision_id IS NOT NULL"
                ).fetchall()
            }
            if not current_revisions:
                return ()

            candidates_by_id: dict[int, _Candidate] = {}

            lexical_ids = self._lexical_candidates(conn, question, current_revisions, unlocked_scope_keys)
            semantic_ids, semantic_ranks = await self._semantic_candidates(
                conn, question, current_revisions, unlocked_scope_keys
            )

            fused_ranks = self._fuse(lexical_ids, semantic_ids)

            all_ids = set(lexical_ids) | set(semantic_ids)
            if not all_ids:
                return ()

            rows = conn.execute(
                f"""
                SELECT chunks.*, source_revisions.commit_sha, source_revisions.source_key AS rev_source_key,
                       sources.canonical_url, sources.display_name, sources.authority_label, sources.precedence
                FROM chunks
                JOIN source_revisions ON source_revisions.id = chunks.source_revision_id
                JOIN sources ON sources.source_key = source_revisions.source_key
                WHERE chunks.id IN ({",".join("?" * len(all_ids))})
                """,
                list(all_ids),
            ).fetchall()
            for row in rows:
                candidates_by_id[row["id"]] = _Candidate(
                    chunk_id=row["id"],
                    source_key=row["rev_source_key"],
                    precedence=row["precedence"],
                    section_key=row["section_key"],
                    position=row["position"],
                    body=row["body"],
                    heading_path=tuple(json.loads(row["heading_path_json"])),
                    page_or_section=row["page_or_section"],
                    anchor=row["anchor"],
                    token_count=row["token_count"],
                    revision_id=row["source_revision_id"],
                    commit_sha=row["commit_sha"],
                    canonical_url=row["canonical_url"],
                    display_name=row["display_name"],
                    authority_label=row["authority_label"],
                )

            ordered = sorted(
                fused_ranks.items(),
                key=lambda item: (-item[1], -candidates_by_id[item[0]].precedence),
            )
            # Preserve strong single-channel results that RRF overlap would otherwise crowd out.
            channel_floor = min(3, self._settings.final_chunks // 2)
            channel_ids = set(lexical_ids[:channel_floor]) | set(semantic_ids[:channel_floor])
            ordered = [item for item in ordered if item[0] in channel_ids] + [
                item for item in ordered if item[0] not in channel_ids
            ]

            selected: list[tuple[int, float]] = []
            token_total = 0
            for chunk_id, score in ordered:
                if len(selected) >= self._settings.final_chunks:
                    break
                candidate = candidates_by_id[chunk_id]
                if token_total + candidate.token_count > self._settings.evidence_token_budget:
                    continue
                selected.append((chunk_id, score))
                token_total += candidate.token_count

            selected = self._expand_adjacent(conn, selected, candidates_by_id, token_total, unlocked_scope_keys)

        evidence: list[Evidence] = []
        for index, (chunk_id, score) in enumerate(selected, start=1):
            candidate = candidates_by_id[chunk_id]
            citation_id = f"E{index}"
            citation = Citation(
                citation_id=citation_id,
                source=SourceKey(candidate.source_key),
                source_title=candidate.display_name,
                authority_label=candidate.authority_label,
                heading_path=candidate.heading_path,
                page_or_section=candidate.page_or_section,
                anchor=candidate.anchor,
                excerpt=candidate.body,
                revision=candidate.commit_sha,
                canonical_url=candidate.canonical_url,
            )
            evidence.append(
                Evidence(
                    citation=citation,
                    chunk_id=chunk_id,
                    prompt_text=f"[{citation_id}] {' > '.join(candidate.heading_path)}\n{candidate.body}",
                    token_count=candidate.token_count,
                    precedence=candidate.precedence,
                    fused_rank=score,
                )
            )
        return tuple(evidence)

    def _lexical_candidates(
        self,
        conn,
        question: str,
        current_revisions: dict[str, int],
        unlocked_scope_keys: frozenset[str],
    ) -> list[int]:
        revision_ids = list(current_revisions.values())
        tokens = re.findall(r"[\w]+", question.lower())
        content_tokens = [token for token in tokens if token not in _QUESTION_FILLER]
        fts_query = " OR ".join(f'"{token}"' for token in content_tokens or tokens)
        if not fts_query:
            return []
        eligibility_sql, eligibility_params = _eligibility_clause(unlocked_scope_keys)
        rows = conn.execute(
            f"""
            SELECT chunks.id FROM chunks_fts
            JOIN chunks ON chunks.id = chunks_fts.rowid
            WHERE chunks_fts MATCH ?
              AND chunks.source_revision_id IN ({",".join("?" * len(revision_ids))})
              AND {eligibility_sql}
            ORDER BY rank
            LIMIT ?
            """,
            [fts_query, *revision_ids, *eligibility_params, self._settings.lexical_candidates],
        ).fetchall()
        return [row["id"] for row in rows]

    async def _semantic_candidates(
        self,
        conn,
        question: str,
        current_revisions: dict[str, int],
        unlocked_scope_keys: frozenset[str],
    ) -> tuple[list[int], dict[int, float]]:
        revision_ids = list(current_revisions.values())
        eligibility_sql, eligibility_params = _eligibility_clause(unlocked_scope_keys)
        rows = conn.execute(
            f"""
            SELECT chunks.id AS chunk_id, embeddings.vector_f32, embeddings.norm, embeddings.dimensions
            FROM chunks
            JOIN chunk_embeddings ON chunk_embeddings.chunk_id = chunks.id
            JOIN embeddings ON embeddings.id = chunk_embeddings.embedding_id
            WHERE chunks.source_revision_id IN ({",".join("?" * len(revision_ids))})
              AND {eligibility_sql}
            """,
            [*revision_ids, *eligibility_params],
        ).fetchall()
        if not rows:
            return [], {}

        query_vector = (await self._embedding_model.embed([question]))[0]
        query_norm = float(np.linalg.norm(query_vector)) or 1.0
        query_unit = query_vector / query_norm

        ids = []
        similarities = []
        for row in rows:
            vector = np.frombuffer(row["vector_f32"], dtype="<f4")
            norm = row["norm"] or 1.0
            similarity = float(np.dot(query_unit, vector)) / norm
            ids.append(row["chunk_id"])
            similarities.append(similarity)

        order = np.argsort(similarities)[::-1][: self._settings.semantic_candidates]
        ranked_ids = [ids[i] for i in order]
        return ranked_ids, {}

    def _fuse(self, lexical_ids: list[int], semantic_ids: list[int]) -> dict[int, float]:
        k = self._settings.rrf_k
        scores: dict[int, float] = {}
        for rank, chunk_id in enumerate(lexical_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        for rank, chunk_id in enumerate(semantic_ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
        return scores

    def _expand_adjacent(
        self,
        conn,
        selected: list[tuple[int, float]],
        candidates_by_id: dict[int, _Candidate],
        token_total: int,
        unlocked_scope_keys: frozenset[str],
    ) -> list[tuple[int, float]]:
        expanded = list(selected)
        added = 0
        eligibility_sql, eligibility_params = _eligibility_clause(unlocked_scope_keys)
        for chunk_id, score in selected:
            if added >= self._settings.adjacency_limit:
                break
            candidate = candidates_by_id[chunk_id]
            neighbor_row = conn.execute(
                f"""
                SELECT id, body, token_count, section_key, anchor, heading_path_json, page_or_section,
                       source_revision_id
                FROM chunks
                WHERE source_revision_id = ? AND position = ? AND section_key = ?
                  AND {eligibility_sql}
                """,
                (candidate.revision_id, candidate.position + 1, candidate.section_key, *eligibility_params),
            ).fetchone()
            if neighbor_row is None:
                continue
            neighbor_id = neighbor_row["id"]
            if neighbor_id in candidates_by_id or neighbor_row["token_count"] + token_total > (
                self._settings.evidence_token_budget
            ):
                continue
            row = conn.execute(
                """
                SELECT chunks.*, source_revisions.commit_sha, source_revisions.source_key AS rev_source_key,
                       sources.canonical_url, sources.display_name, sources.authority_label, sources.precedence
                FROM chunks
                JOIN source_revisions ON source_revisions.id = chunks.source_revision_id
                JOIN sources ON sources.source_key = source_revisions.source_key
                WHERE chunks.id = ?
                """,
                (neighbor_id,),
            ).fetchone()
            candidates_by_id[neighbor_id] = _Candidate(
                chunk_id=neighbor_id,
                source_key=row["rev_source_key"],
                precedence=row["precedence"],
                section_key=row["section_key"],
                position=row["position"],
                body=row["body"],
                heading_path=tuple(json.loads(row["heading_path_json"])),
                page_or_section=row["page_or_section"],
                anchor=row["anchor"],
                token_count=row["token_count"],
                revision_id=row["source_revision_id"],
                commit_sha=row["commit_sha"],
                canonical_url=row["canonical_url"],
                display_name=row["display_name"],
                authority_label=row["authority_label"],
            )
            expanded.append((neighbor_id, score))
            token_total += neighbor_row["token_count"]
            added += 1
        return expanded
