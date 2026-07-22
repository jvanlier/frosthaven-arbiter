"""Tests for source synchronization: revision pinning, idempotency,
incremental embedding, transactional activation, and spoiler invariants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from frosthaven_arbiter.database import Database
from frosthaven_arbiter.domain import SourceKey, Visibility
from frosthaven_arbiter.sources.parse import ParsedChunk, approx_tokens, parse_source, slugify
from frosthaven_arbiter.sources.sync import SourceSynchronizer

from .conftest import FakeEmbeddingModel, FakeSourceFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _rulebook_text() -> str:
    return (FIXTURES / "rulebook.md").read_text()


def _faq_text() -> str:
    return (FIXTURES / "faq.md").read_text()


@pytest.fixture
def fetcher() -> FakeSourceFetcher:
    fetcher = FakeSourceFetcher()
    fetcher.register(SourceKey.RULEBOOK, _rulebook_text())
    fetcher.register(SourceKey.FAQ, _faq_text())
    return fetcher


@pytest.fixture
def embedding_model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel()


def _faq_document(body: str) -> str:
    return (
        '# FAQ\n\n## <a name="page_01" class="page-number">1.0</a> '
        f"First Printing Production Errors and Typos\n\n{body}"
    )


def _metadata(chunk: ParsedChunk):
    return (
        chunk.heading_path,
        chunk.anchor,
        chunk.page_or_section,
        chunk.visibility,
        chunk.scope_keys,
        chunk.section_key,
        chunk.atomic,
    )


def _expected_metadata(
    heading_path: tuple[str, ...],
    anchor: str,
    page: str | None,
    visibility: Visibility = Visibility.PUBLIC,
    scopes: frozenset[str] = frozenset(),
    section_key: str | None = None,
    *,
    atomic: bool = False,
):
    return (
        heading_path,
        anchor,
        page,
        visibility,
        scopes,
        section_key or "/".join(slugify(part) for part in heading_path),
        atomic,
    )


def test_rulebook_parser_preserves_ordered_structural_contract() -> None:
    chunks = parse_source(SourceKey.RULEBOOK, _rulebook_text())

    assert [chunk.body for chunk in chunks] == [
        "Introductory rules begin here.",
        "Road events occur when the party travels between locations. Draw one road event card and resolve it.",
        "Boat events occur when traveling by sea.",
        "Select a character and take its components.",
        "The first protected setup rule.",
        "Read the public setup reminder between stickers.",
        "The second protected setup rule.",
        "Finish public character setup.",
        (
            "Once a monster has found a focus and identified its path, it performs its abilities in order. "
            "A monster moves only when its ability card lists movement, which grants movement points equal "
            "to its base movement stat plus the listed modifier.\n\nFocus Diagram explains the focus example."
        ),
        "Roll | Result\n1-3 | Calm seas\n4-6 | Storm",
        "Resolve one movement point at a time.",
        "This is protected sticker content describing a locked scenario reward that must never leak.",
        "Items cannot be purchased freely until building 37 is built.",
        "Items may be purchased after the Trading Stall is available.",
        "Scenario Level | 0 | 1\nGold Conversion | 2 | 2\nTrap Damage | 2 | 3",
        "Recommended Scenario Level: Average Character Level ÷ 2 (rounded up).",
    ]
    getting_started = ("Getting Started",)
    road_events = (*getting_started, "Road Events")
    character_setup = (*getting_started, "Character Setup")
    monster_movement = (*getting_started, "Monster Movement")
    item_purchases = (*getting_started, "Item Purchases")
    quick_reference = ("Quick Reference", "Scenario Level")
    assert [_metadata(chunk) for chunk in chunks] == [
        _expected_metadata(getting_started, "getting-started", None),
        _expected_metadata(road_events, "road-events", "12"),
        _expected_metadata((*road_events, "Boat Events"), "boat-events", "12"),
        _expected_metadata(character_setup, "character-setup", "12", atomic=True),
        _expected_metadata(
            (*character_setup, "Sticker 1"),
            "sticker-1",
            "12",
            Visibility.PROTECTED,
            frozenset({"rulebook:sticker-1"}),
            "getting-started/character-setup",
        ),
        _expected_metadata(character_setup, "character-setup", "12", atomic=True),
        _expected_metadata(
            (*character_setup, "Sticker 3"),
            "sticker-3",
            "12",
            Visibility.PROTECTED,
            frozenset({"rulebook:sticker-3"}),
            "getting-started/character-setup",
        ),
        _expected_metadata(character_setup, "character-setup", "12", atomic=True),
        _expected_metadata(monster_movement, "monster-movement", "12"),
        _expected_metadata(monster_movement, "monster-movement", "12", atomic=True),
        _expected_metadata(monster_movement, "monster-movement", "12"),
        _expected_metadata(
            (*monster_movement, "Sticker 4"),
            "sticker-4",
            "12",
            Visibility.PROTECTED,
            frozenset({"rulebook:sticker-4"}),
            "getting-started/monster-movement",
        ),
        _expected_metadata(
            (*item_purchases, "Sticker 13 (Cover Purchase Items)"),
            "sticker-13-cover-purchase-items",
            "12",
            Visibility.PROTECTED,
            frozenset({"rulebook:sticker-13"}),
            "getting-started/item-purchases",
        ),
        _expected_metadata(
            (*item_purchases, "Sticker 13 (Cover Purchase Items)", "Purchase Items"),
            "purchase-items",
            "12",
            Visibility.PROTECTED,
            frozenset({"rulebook:sticker-13"}),
            "getting-started/item-purchases",
        ),
        _expected_metadata(quick_reference, "scenario-level", "12", atomic=True),
        _expected_metadata(quick_reference, "scenario-level", "12", atomic=True),
    ]
    rendered = "\n".join(chunk.body for chunk in chunks)
    assert "Source maintainer front matter" not in rendered
    assert "Road Events navigation text" not in rendered
    assert "Credits and transcription notes" not in rendered
    assert "Skipped due to spoilers" not in rendered
    assert "{:" not in rendered
    assert "table-responsive" not in rendered


def test_faq_parser_preserves_entry_and_spoiler_contract() -> None:
    chunks = parse_source(SourceKey.FAQ, _faq_text())

    assert [chunk.body for chunk in chunks] == [
        "Envelope 24 should list sticker 10. This nested correction stays with its parent.",
        "Public erratum with a protected correction.",
        "Secret erratum This entire erratum is protected.",
        "What buildings are available at the start? The Barracks and Workshop are available.",
        (
            "What can I build at the start of the game?\n\nBuild a Logging Camp.\nBuild Wall Section J.\n"
            "Build any of the three Travel Tools."
        ),
        (
            "Building 44\n\nLevel 2 - When does the 10g discount apply? After all other modifiers.\n"
            "Level 3 - This building effect reduces the level penalties by 10 each."
        ),
        "Building 81, Envelope A Immediately build Level 2 at no cost.",
        "Trials are referred to here by their Card Number.\n\nTrial 0355 Count enemy standee numbers only.",
        "Trials are referred to here by their Card Number.\n\nTrial 0359 Gain every applicable check mark.",
        "This standalone informational paragraph does not own the following list.",
        "First unrelated FAQ bullet.",
        "Second unrelated FAQ bullet.",
        "Meaningful Map",
        "Can I teleport into the hex I currently occupy? Yes, but nothing happens.",
        (
            "Does a question keep its continuation? Yes, this is the first answer paragraph.\n\n"
            "This continuation remains attached to the parent question."
        ),
        "Scenario 62 - Scenario 62 protected correction text.",
        (
            "Can you explain how Infusions work? Astral characters may ignore line of sight for ranged attacks.\n\n"
            "The trigger ability is performed whenever another Infusion is played.\n\n"
            "If, later, I play Caress of the Night, all active Infusion effects apply."
        ),
        "Does the next question stay separate? Yes.",
        (
            "Note on an Interaction with Shackles\n\nWhat happens if I have my Animated Claymore summoned? "
            "The complete protected interaction answer."
        ),
        "Nested protected question? Nested protected answer.",
        "PQ 11 The hidden envelope reward is a Trap class unlock.",
        "Item 013 - Dancing Slippers interact with Retaliate after added conditions.",
        "Item 109 - Major Renewing Potion answer.",
        "Item 245 - Ancient Coin answer.",
    ]
    assert all(chunk.anchor and chunk.anchor.startswith("page_") for chunk in chunks)
    assert all(chunk.body and approx_tokens(chunk.body) <= 600 for chunk in chunks)
    assert [chunk.visibility for chunk in chunks] == [
        Visibility.PUBLIC,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PUBLIC,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
        Visibility.PROTECTED,
    ]
    assert [chunk.atomic for chunk in chunks] == [
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    assert chunks[4].heading_path == ("4.0 Outpost General Questions",)
    assert chunks[4].section_key == "4-0-outpost-general-questions"
    assert chunks[4].anchor == "page_4"
    assert chunks[4].page_or_section == "4"
    assert chunks[5].scope_keys == frozenset({"faq:building-44"})
    assert chunks[7].heading_path == (
        "4.0 Outpost General Questions",
        "Spoilers for Building 81",
        "Specific Trial Questions",
    )
    assert chunks[7].scope_keys == chunks[8].scope_keys == frozenset({"faq:spoilers-for-building-81"})
    assert chunks[16].heading_path == ('8.7 "Astral"', "Locked Class: Astral")
    assert chunks[16].scope_keys == frozenset({"faq:locked-class-astral"})
    assert chunks[19].heading_path == ('8.7 "Astral"', "Outer Lock", "Inner Lock")
    assert chunks[19].scope_keys == frozenset({"faq:outer-lock", "faq:inner-lock"})
    assert chunks[21].anchor == "page_91"
    assert chunks[21].scope_keys == frozenset({"faq:item-013"})
    rendered = "\n".join(chunk.body for chunk in chunks)
    assert "OFFICIAL FAQ FOR FROSTHAVEN" not in rendered
    assert "Maintainer notes and navigation" not in rendered
    assert "divider" not in rendered.lower()


def test_oversized_faq_list_is_split_at_item_boundaries() -> None:
    list_items = "\n".join(f"{index}. " + "word " * 500 for index in range(1, 3))

    chunks = parse_source(SourceKey.FAQ, _faq_document(list_items))

    assert len(chunks) > 2
    assert all(chunk.atomic for chunk in chunks)
    assert all(approx_tokens(chunk.body) <= 600 for chunk in chunks)


def test_oversized_faq_entry_repeats_label_within_limit() -> None:
    chunks = parse_source(SourceKey.FAQ, _faq_document("**Why is this long?** " + "word " * 1000))

    assert len(chunks) > 1
    assert all(chunk.body.startswith("Why is this long?") for chunk in chunks)
    assert all(not chunk.atomic for chunk in chunks)
    assert all(approx_tokens(chunk.body) <= 600 for chunk in chunks)


@pytest.mark.parametrize(
    "markdown_text",
    [
        "# No table of contents",
        "# Table Of Contents",
    ],
)
def test_rulebook_requires_content_start(markdown_text: str) -> None:
    with pytest.raises(ValueError, match="^rulebook content start not found$"):
        parse_source(SourceKey.RULEBOOK, markdown_text)


@pytest.mark.parametrize(
    "body",
    [
        '<div class="table-responsive">\n| A |\n| - |',
        "</div>",
        ('<div class="table-responsive">\n<div>\n<div class="table-responsive">\n| A |\n| - |\n</div>\n</div>\n</div>'),
    ],
)
def test_rulebook_rejects_invalid_responsive_table_wrappers(body: str) -> None:
    markdown_text = f"# Table Of Contents\n\n# Getting Started\n\n{body}"
    with pytest.raises(ValueError, match="^invalid table-responsive wrapper$"):
        parse_source(SourceKey.RULEBOOK, markdown_text)


def test_faq_requires_anchored_content_start() -> None:
    with pytest.raises(ValueError, match="^FAQ content start not found$"):
        parse_source(SourceKey.FAQ, "# FAQ\n\n## 1.0 First Printing Production Errors and Typos")


async def test_first_sync_activates_both_sources(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)

    report = await synchronizer.sync()

    assert len(report.activated_revisions) == 2
    assert report.unchanged_sources == ()
    assert report.chunks_added > 0
    assert report.embeddings_created == report.chunks_added
    assert report.scopes_discovered >= 2

    with database.connect() as conn:
        sources = conn.execute("SELECT source_key, current_revision_id FROM sources").fetchall()
        for row in sources:
            assert row["current_revision_id"] is not None
        chunk_count = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        assert chunk_count == report.chunks_added


async def test_unchanged_content_is_a_no_op(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()
    embedding_model.calls.clear()

    report = await synchronizer.sync()

    assert set(report.unchanged_sources) == {SourceKey.RULEBOOK, SourceKey.FAQ}
    assert report.chunks_added == 0
    assert embedding_model.calls == []


async def test_changed_content_reembeds_only_changed_chunks(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    changed_text = _rulebook_text() + "\n\n### New Section\n\nA brand new rule appears here.\n"
    fetcher.register(SourceKey.RULEBOOK, changed_text, commit_sha="second-commit")

    report = await synchronizer.sync()

    assert SourceKey.FAQ in report.unchanged_sources
    assert report.chunks_added >= 1
    with database.connect() as conn:
        revisions = conn.execute("SELECT COUNT(*) AS n FROM source_revisions WHERE source_key = 'rulebook'").fetchone()[
            "n"
        ]
        assert revisions == 2


async def test_protected_chunks_always_have_a_scope(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        protected_without_scope = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunks
            WHERE visibility = 'protected'
              AND id NOT IN (SELECT chunk_id FROM chunk_spoiler_scopes)
            """
        ).fetchone()["n"]
        assert protected_without_scope == 0

        public_with_scope = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chunks
            WHERE visibility = 'public'
              AND id IN (SELECT chunk_id FROM chunk_spoiler_scopes)
            """
        ).fetchone()["n"]
        assert public_with_scope == 0


async def test_sticker_content_is_protected(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        row = conn.execute("SELECT visibility FROM chunks WHERE body LIKE '%must never leak%'").fetchone()
        assert row is not None
        assert row["visibility"] == Visibility.PROTECTED.value


async def test_failed_embedding_leaves_previous_index_active(database: Database, fetcher, embedding_model, settings):
    synchronizer = SourceSynchronizer(database, fetcher, embedding_model, settings)
    await synchronizer.sync()

    with database.connect() as conn:
        original_revision = conn.execute(
            "SELECT current_revision_id FROM sources WHERE source_key = 'rulebook'"
        ).fetchone()["current_revision_id"]

    fetcher.register(SourceKey.RULEBOOK, _rulebook_text() + "\n\nmore text\n", commit_sha="broken-commit")

    class FailingEmbeddingModel(FakeEmbeddingModel):
        async def embed(self, texts):  # noqa: ARG002
            raise RuntimeError("embedding service unavailable")

    failing_model = FailingEmbeddingModel()
    failing_synchronizer = SourceSynchronizer(database, fetcher, failing_model, settings)

    with pytest.raises(RuntimeError):
        await failing_synchronizer.sync()

    with database.connect() as conn:
        current_revision = conn.execute(
            "SELECT current_revision_id FROM sources WHERE source_key = 'rulebook'"
        ).fetchone()["current_revision_id"]
        assert current_revision == original_revision
        chunk_count = conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE source_revision_id = ?", (current_revision,)
        ).fetchone()["n"]
        assert chunk_count > 0
