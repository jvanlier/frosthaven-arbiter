"""Parsing Authoritative Source Markdown into spoiler-aware chunks.

This module renders source Markdown (which embeds raw HTML) to HTML with
`markdown-it-py`, then walks the DOM with BeautifulSoup to produce
`ParsedChunk` records. Spoiler classification happens here, before any
text is merged for chunk sizing, so that public and protected
representations are always kept separate.

This is internal to source synchronization. Callers should use
`sources.sync.SourceSynchronizer` rather than this module directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt

from frosthaven_arbiter.domain import SourceKey, Visibility

_MD = MarkdownIt("commonmark", {"html": True}).enable(["table"])
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_MAX_CHUNK_TOKENS = 600
_MIN_SPLIT_TOKENS = 350


@dataclass(frozen=True)
class ParsedChunk:
    section_key: str
    heading_path: tuple[str, ...]
    anchor: str | None
    page_or_section: str | None
    body: str
    scope_keys: frozenset[str]
    visibility: Visibility
    atomic: bool = False


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "section"


def approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


_approx_tokens = approx_tokens


def render_html(markdown_text: str) -> str:
    return _MD.render(markdown_text)


def _text_of(tag: Tag) -> str:
    return tag.get_text(" ", strip=True)


def _split_leaf_text(text: str) -> list[str]:
    if _approx_tokens(text) <= _MAX_CHUNK_TOKENS:
        return [text]
    paragraphs: list[str] = []
    max_words = int(_MAX_CHUNK_TOKENS / 1.3)
    for paragraph in (p.strip() for p in text.split("\n\n") if p.strip()):
        if _approx_tokens(paragraph) <= _MAX_CHUNK_TOKENS:
            paragraphs.append(paragraph)
            continue
        words = paragraph.split()
        paragraphs.extend(" ".join(words[start : start + max_words]) for start in range(0, len(words), max_words))
    parts: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = _approx_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > _MAX_CHUNK_TOKENS:
            parts.append("\n\n".join(current))
            current = []
            current_tokens = 0
        current.append(paragraph)
        current_tokens += paragraph_tokens
        if current_tokens >= _MIN_SPLIT_TOKENS:
            parts.append("\n\n".join(current))
            current = []
            current_tokens = 0
    if current:
        parts.append("\n\n".join(current))
    return parts or [text]


def _split_list(node: Tag) -> list[str]:
    items = [_text_of(item) for item in node.find_all("li", recursive=False)]
    return _split_leaf_text("\n\n".join(item for item in items if item))


class _LeafBuffer:
    """Accumulates public/protected text for the current leaf section."""

    def __init__(self, section_key: str, heading_path: tuple[str, ...], anchor: str | None, page: str | None) -> None:
        self.section_key = section_key
        self.heading_path = heading_path
        self.anchor = anchor
        self.page = page
        self.public_parts: list[str] = []
        self.protected_parts: list[tuple[str, frozenset[str]]] = []
        self.atomic_parts: list[tuple[str, Visibility, frozenset[str]]] = []

    def add_public(self, text: str) -> None:
        if text.strip():
            self.public_parts.append(text.strip())

    def add_protected(self, text: str, scope_keys: frozenset[str]) -> None:
        if text.strip():
            self.protected_parts.append((text.strip(), scope_keys))

    def add_atomic(self, text: str, visibility: Visibility, scope_keys: frozenset[str]) -> None:
        if text.strip():
            self.atomic_parts.append((text.strip(), visibility, scope_keys))

    def is_empty(self) -> bool:
        return not (self.public_parts or self.protected_parts or self.atomic_parts)

    def flush(self) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        if self.public_parts:
            for part in _split_leaf_text("\n\n".join(self.public_parts)):
                chunks.append(
                    ParsedChunk(
                        section_key=self.section_key,
                        heading_path=self.heading_path,
                        anchor=self.anchor,
                        page_or_section=self.page,
                        body=part,
                        scope_keys=frozenset(),
                        visibility=Visibility.PUBLIC,
                    )
                )
        for text, scope_keys in self.protected_parts:
            for part in _split_leaf_text(text):
                chunks.append(
                    ParsedChunk(
                        section_key=self.section_key,
                        heading_path=self.heading_path,
                        anchor=self.anchor,
                        page_or_section=self.page,
                        body=part,
                        scope_keys=scope_keys,
                        visibility=Visibility.PROTECTED,
                    )
                )
        for text, visibility, scope_keys in self.atomic_parts:
            chunks.append(
                ParsedChunk(
                    section_key=self.section_key,
                    heading_path=self.heading_path,
                    anchor=self.anchor,
                    page_or_section=self.page,
                    body=text,
                    scope_keys=scope_keys,
                    visibility=visibility,
                    atomic=True,
                )
            )
        return chunks


def _leaf_or_none(heading_path: tuple[str, ...]) -> bool:
    return len(heading_path) > 0


def parse_rulebook(markdown_text: str) -> list[ParsedChunk]:
    html = render_html(markdown_text)
    soup = BeautifulSoup(html, "html.parser")

    chunks: list[ParsedChunk] = []
    heading_stack: list[str] = []
    current_page: str | None = None
    buffer: _LeafBuffer | None = None

    def flush_buffer() -> None:
        nonlocal buffer
        if buffer is not None and not buffer.is_empty():
            chunks.extend(buffer.flush())
        buffer = None

    def ensure_buffer() -> _LeafBuffer:
        nonlocal buffer
        if buffer is None:
            heading_path = tuple(heading_stack)
            section_key = "/".join(slugify(h) for h in heading_path) or "root"
            anchor = slugify(heading_path[-1]) if heading_path else None
            buffer = _LeafBuffer(section_key, heading_path, anchor, current_page)
        return buffer

    def walk(nodes) -> None:
        nonlocal current_page
        for node in nodes:
            if not isinstance(node, Tag):
                continue
            if node.name in _HEADING_TAGS:
                flush_buffer()
                level = int(node.name[1])
                text = _text_of(node)
                if not text or text.lower() in {"table of contents", "new to frosthaven"}:
                    continue
                del heading_stack[level - 1 :]
                heading_stack.append(text)
                continue
            if node.name == "p":
                anchor_tag = node.find("a", attrs={"name": re.compile(r"^page_\d+$")})
                if anchor_tag is not None:
                    current_page = str(anchor_tag["name"]).removeprefix("page_")
                    continue
                text = _text_of(node)
                ensure_buffer().add_public(text)
                continue
            if node.name == "details":
                summary = node.find("summary")
                label = _text_of(summary) if summary else "locked content"
                scope_key = f"rulebook:{slugify(label)}"
                text_parts = []
                for child in node.find_all(recursive=False):
                    if child.name == "summary":
                        continue
                    text_parts.append(_text_of(child))
                text = "\n\n".join(t for t in text_parts if t)
                if text:
                    ensure_buffer().add_protected(text, frozenset({scope_key}))
                continue
            if node.name in {"ul", "ol"}:
                for text in _split_list(node):
                    ensure_buffer().add_atomic(text, Visibility.PUBLIC, frozenset())
                continue
            if node.name in {"table", "blockquote"}:
                text = _text_of(node)
                ensure_buffer().add_atomic(text, Visibility.PUBLIC, frozenset())
                continue
            walk(node.children)

    walk(soup.children)
    flush_buffer()
    return chunks


def parse_faq(markdown_text: str) -> list[ParsedChunk]:
    html = render_html(markdown_text)
    soup = BeautifulSoup(html, "html.parser")

    chunks: list[ParsedChunk] = []
    heading_stack: list[str] = []
    current_section: str | None = None

    def make_scope_for_hidden(node: Tag, section_slug: str) -> str:
        strong = node.find_previous_sibling("strong") or node.find_previous("strong")
        if strong is not None and _text_of(strong):
            return f"faq:{slugify(_text_of(strong))}"
        return f"faq:section:{section_slug}:locked"

    def emit_paragraph(node: Tag, heading_path: tuple[str, ...], section_key: str) -> None:
        hidden_spans = node.find_all("span", class_="hidden")
        if not hidden_spans:
            text = _text_of(node)
            for part in _split_leaf_text(text) if text else []:
                chunks.append(
                    ParsedChunk(
                        section_key=section_key,
                        heading_path=heading_path,
                        anchor=None,
                        page_or_section=current_section,
                        body=part,
                        scope_keys=frozenset(),
                        visibility=Visibility.PUBLIC,
                    )
                )
            return

        public_copy = BeautifulSoup(str(node), "html.parser")
        for span in public_copy.find_all("span", class_="hidden"):
            span.decompose()
        public_text = _text_of(public_copy)
        for part in _split_leaf_text(public_text) if public_text else []:
            chunks.append(
                ParsedChunk(
                    section_key=section_key,
                    heading_path=heading_path,
                    anchor=None,
                    page_or_section=current_section,
                    body=part,
                    scope_keys=frozenset(),
                    visibility=Visibility.PUBLIC,
                )
            )

        scope_keys = frozenset(make_scope_for_hidden(span, section_key) for span in hidden_spans)
        protected_text = _text_of(node)
        for part in _split_leaf_text(protected_text):
            chunks.append(
                ParsedChunk(
                    section_key=section_key,
                    heading_path=heading_path,
                    anchor=None,
                    page_or_section=current_section,
                    body=part,
                    scope_keys=scope_keys,
                    visibility=Visibility.PROTECTED,
                )
            )

    def walk(nodes) -> None:
        nonlocal current_section
        for node in nodes:
            if not isinstance(node, Tag):
                continue
            if node.name in _HEADING_TAGS:
                level = int(node.name[1])
                anchor_tag = node.find("a", class_="page-number") or node.find(
                    "a", attrs={"name": re.compile(r"^page_")}
                )
                if anchor_tag is not None:
                    name = anchor_tag.get("name") or anchor_tag.get_text(strip=True)
                    current_section = str(name).removeprefix("page_")
                text = _text_of(node)
                if text.lower() == "table of contents":
                    continue
                del heading_stack[level - 1 :]
                heading_stack.append(text)
                continue
            if node.name == "p":
                heading_path = tuple(heading_stack)
                section_key = "/".join(slugify(h) for h in heading_path) or "root"
                emit_paragraph(node, heading_path, section_key)
                continue
            if node.name == "details":
                summary = node.find("summary")
                label = _text_of(summary) if summary else "locked content"
                scope_key = f"faq:{slugify(label)}"
                heading_path = tuple(heading_stack)
                section_key = "/".join(slugify(h) for h in heading_path) or "root"
                text_parts = [_text_of(child) for child in node.find_all(recursive=False) if child.name != "summary"]
                text = "\n\n".join(t for t in text_parts if t)
                for part in _split_leaf_text(text) if text else []:
                    chunks.append(
                        ParsedChunk(
                            section_key=section_key,
                            heading_path=heading_path,
                            anchor=None,
                            page_or_section=current_section,
                            body=f"{label}: {part}",
                            scope_keys=frozenset({scope_key}),
                            visibility=Visibility.PROTECTED,
                        )
                    )
                continue
            if node.name in {"ul", "ol"}:
                heading_path = tuple(heading_stack)
                section_key = "/".join(slugify(h) for h in heading_path) or "root"
                for text in _split_list(node):
                    chunks.append(
                        ParsedChunk(
                            section_key=section_key,
                            heading_path=heading_path,
                            anchor=None,
                            page_or_section=current_section,
                            body=text,
                            scope_keys=frozenset(),
                            visibility=Visibility.PUBLIC,
                            atomic=True,
                        )
                    )
                continue
            walk(node.children)

    walk(soup.children)
    return chunks


def parse_source(source: SourceKey, markdown_text: str) -> list[ParsedChunk]:
    if source is SourceKey.RULEBOOK:
        return parse_rulebook(markdown_text)
    return parse_faq(markdown_text)
