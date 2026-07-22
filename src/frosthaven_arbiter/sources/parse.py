"""Parse authoritative Markdown into ordered, spoiler-aware chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString
from markdown_it import MarkdownIt

from frosthaven_arbiter.domain import SourceKey, Visibility

_MD = MarkdownIt("commonmark", {"html": True}).enable(["table"])
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_MAX_CHUNK_TOKENS = 600
_KRAMDOWN_ATTRIBUTE = re.compile(r"\{:\s*[^}]*\}")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_STICKER_LABEL = re.compile(r"^Sticker\s+\d+$", re.IGNORECASE)
_STICKER_ID = re.compile(r"^sticker_(\d+)$")
_FAQ_START = "1.0 First Printing Production Errors and Typos"


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


@dataclass(frozen=True)
class _Context:
    heading_path: tuple[str, ...]
    anchor: str | None
    page_or_section: str | None
    visibility: Visibility
    scope_keys: frozenset[str]
    section_key_override: str | None = None

    @property
    def section_key(self) -> str:
        return self.section_key_override or "/".join(slugify(part) for part in self.heading_path) or "root"


@dataclass
class _SemanticBlock:
    context: _Context
    kind: Literal["prose", "list", "table", "blockquote", "pre"]
    units: list[str]

    @property
    def atomic(self) -> bool:
        return self.kind in {"list", "table", "blockquote"}


@dataclass
class _FaqEntry:
    nodes: list[Tag]
    label: str | None
    heading_path: tuple[str, ...]
    atomic: bool = False


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "section"


def approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


_approx_tokens = approx_tokens


def render_html(markdown_text: str) -> str:
    return _MD.render(markdown_text)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_source_text(text: str) -> str:
    return _normalize_whitespace(_KRAMDOWN_ATTRIBUTE.sub("", text))


def _normalize_faq(markdown_text: str) -> str:
    lines = []
    for line in markdown_text.splitlines():
        lines.append("" if line.strip().lower() in {"<br>", "<br/>", "<br />"} else line)
    return "\n".join(lines)


def _normalize_rulebook(markdown_text: str) -> str:
    lines: list[str] = []
    stack: list[bool] = []
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"<div(?:\s+[^>]*)?>", stripped, flags=re.IGNORECASE):
            responsive = stripped == '<div class="table-responsive">'
            if responsive and any(stack):
                raise ValueError("invalid table-responsive wrapper")
            stack.append(responsive)
            if not responsive:
                lines.append(line)
            continue
        if stripped.lower() == "</div>":
            if not stack:
                raise ValueError("invalid table-responsive wrapper")
            responsive = stack.pop()
            if not responsive:
                lines.append(line)
            continue
        lines.append(line)
    if any(stack):
        raise ValueError("invalid table-responsive wrapper")
    return "\n".join(lines)


def _clone(node: Tag) -> Tag:
    clone = BeautifulSoup(str(node), "html.parser").find()
    if not isinstance(clone, Tag):
        raise ValueError("unable to clone source node")
    return clone


def _replace_images(node: Tag, source: SourceKey) -> None:
    for image in node.find_all("img"):
        raw_classes = image.get("class")
        classes = {str(item) for item in raw_classes} if isinstance(raw_classes, list) else set()
        alt = _normalize_whitespace(str(image.get("alt", "")))
        ignored = not alt
        if source is SourceKey.FAQ and alt.lower() in {"divider", "divider-narrow"}:
            ignored = True
        if source is SourceKey.RULEBOOK and "new-to-fh-icon" in classes:
            ignored = True
        if ignored:
            image.decompose()
        else:
            image.replace_with(NavigableString(alt))


def _text_of(node: Tag, source: SourceKey, *, remove_hidden: bool = False) -> str:
    clone = _clone(node)
    if remove_hidden:
        for hidden in clone.select("span.hidden"):
            hidden.decompose()
    _replace_images(clone, source)
    for br in clone.find_all("br"):
        br.replace_with(NavigableString("\n"))
    raw_text = clone.get_text(" ", strip=True)
    text = _clean_source_text(raw_text)
    return text


def _heading_text(node: Tag) -> str:
    clone = _clone(node)
    for image in clone.find_all("img"):
        image.decompose()
    return _normalize_whitespace(clone.get_text(" ", strip=True))


def _table_rows(node: Tag, source: SourceKey, *, remove_hidden: bool = False) -> list[str]:
    rows: list[str] = []
    for row in node.find_all("tr"):
        cells = [
            _text_of(cell, source, remove_hidden=remove_hidden) for cell in row.find_all(["th", "td"], recursive=False)
        ]
        rendered = " | ".join(cell for cell in cells if cell)
        if rendered:
            rows.append(rendered)
    return rows


def _list_items(node: Tag, source: SourceKey, *, remove_hidden: bool = False) -> list[str]:
    return [
        text
        for item in node.find_all("li", recursive=False)
        if (text := _text_of(item, source, remove_hidden=remove_hidden))
    ]


def _split_long_unit(text: str, *, prefix: str | None = None) -> list[str]:
    if not text:
        return []
    if prefix is None and _approx_tokens(text) <= _MAX_CHUNK_TOKENS:
        return [text]

    prefix_words = len(prefix.split()) if prefix else 0
    max_words = max(1, int(_MAX_CHUNK_TOKENS / 1.3) - prefix_words - 1)
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    fine_units: list[str] = []
    for sentence in sentences or [text]:
        candidate = f"{prefix}\n\n{sentence}" if prefix else sentence
        if _approx_tokens(candidate) <= _MAX_CHUNK_TOKENS:
            fine_units.append(sentence)
            continue
        words = sentence.split()
        fine_units.extend(" ".join(words[start : start + max_words]) for start in range(0, len(words), max_words))

    parts: list[str] = []
    current: list[str] = []
    for unit in fine_units:
        candidate_body = " ".join([*current, unit])
        candidate = f"{prefix}\n\n{candidate_body}" if prefix else candidate_body
        if current and _approx_tokens(candidate) > _MAX_CHUNK_TOKENS:
            body = " ".join(current)
            parts.append(f"{prefix}\n\n{body}" if prefix else body)
            current = []
        current.append(unit)
    if current:
        body = " ".join(current)
        parts.append(f"{prefix}\n\n{body}" if prefix else body)
    return parts


def _pack_units(units: list[str], separator: str = "\n\n") -> list[str]:
    expanded: list[str] = []
    for unit in units:
        expanded.extend(_split_long_unit(unit))
    parts: list[str] = []
    current: list[str] = []
    for unit in expanded:
        candidate = separator.join([*current, unit])
        if current and _approx_tokens(candidate) > _MAX_CHUNK_TOKENS:
            parts.append(separator.join(current))
            current = []
        current.append(unit)
    if current:
        parts.append(separator.join(current))
    return parts


def _split_table(rows: list[str]) -> list[str]:
    if not rows:
        return []
    header = rows[0]
    if len(rows) == 1:
        return _split_long_unit(header)
    parts: list[str] = []
    current = [header]
    for row in rows[1:]:
        candidate = "\n".join([*current, row])
        if _approx_tokens(f"{header}\n{row}") > _MAX_CHUNK_TOKENS:
            if len(current) > 1:
                parts.append("\n".join(current))
                current = [header]
            parts.extend(_split_long_unit(row, prefix=header))
            continue
        if len(current) > 1 and _approx_tokens(candidate) > _MAX_CHUNK_TOKENS:
            parts.append("\n".join(current))
            current = [header]
        current.append(row)
    if len(current) > 1 or not parts:
        parts.append("\n".join(current))
    return parts


def _chunks_for_block(block: _SemanticBlock) -> list[ParsedChunk]:
    if block.kind == "table":
        bodies = _split_table(block.units)
    else:
        separator = "\n" if block.kind == "list" else "\n\n"
        bodies = _pack_units(block.units, separator)
    return [
        ParsedChunk(
            section_key=block.context.section_key,
            heading_path=block.context.heading_path,
            anchor=block.context.anchor,
            page_or_section=block.context.page_or_section,
            body=body,
            scope_keys=block.context.scope_keys,
            visibility=block.context.visibility,
            atomic=block.atomic,
        )
        for body in bodies
        if body and _approx_tokens(body) <= _MAX_CHUNK_TOKENS
    ]


class _RulebookCollector:
    def __init__(self) -> None:
        self.chunks: list[ParsedChunk] = []
        self.pending: _SemanticBlock | None = None

    def flush(self) -> None:
        if self.pending is not None:
            self.chunks.extend(_chunks_for_block(self.pending))
            self.pending = None

    def add(
        self,
        context: _Context,
        kind: Literal["prose", "list", "table", "blockquote", "pre"],
        units: list[str],
    ) -> None:
        units = [unit for unit in units if unit and not _KRAMDOWN_ATTRIBUTE.fullmatch(unit)]
        if not units:
            return
        if (
            kind == "prose"
            and self.pending is not None
            and self.pending.kind == "prose"
            and self.pending.context == context
        ):
            self.pending.units.extend(units)
            return
        self.flush()
        block = _SemanticBlock(context, kind, units)
        if kind == "prose":
            self.pending = block
        else:
            self.chunks.extend(_chunks_for_block(block))


def _summary_info(details: Tag, source: SourceKey) -> tuple[str, str, str]:
    summary = details.find("summary", recursive=False)
    if summary is None:
        return "locked content", "", f"{source.value}:locked-content"
    summary_text = _text_of(summary, source) or "locked content"
    heading = summary.find(_HEADING_TAGS)
    label = _heading_text(heading) if isinstance(heading, Tag) else summary_text
    remainder = ""
    if isinstance(heading, Tag):
        clone = _clone(summary)
        clone_heading = clone.find(_HEADING_TAGS)
        if isinstance(clone_heading, Tag):
            clone_heading.decompose()
        remainder = _text_of(clone, source)
    if source is SourceKey.RULEBOOK:
        sticker = summary.find(id=_STICKER_ID)
        match = _STICKER_ID.fullmatch(str(sticker.get("id"))) if isinstance(sticker, Tag) else None
        scope = f"rulebook:sticker-{match.group(1)}" if match else f"rulebook:{slugify(summary_text)}"
    else:
        scope = f"faq:{slugify(summary_text)}"
    return label, remainder, scope


def parse_rulebook(markdown_text: str) -> list[ParsedChunk]:
    soup = BeautifulSoup(render_html(_normalize_rulebook(markdown_text)), "html.parser")
    top_level = [node for node in soup.children if isinstance(node, Tag)]
    toc_index = next(
        (
            index
            for index, node in enumerate(top_level)
            if node.name == "h1" and _heading_text(node) == "Table Of Contents"
        ),
        None,
    )
    if toc_index is None:
        raise ValueError("rulebook content start not found")
    start_index = next(
        (index for index in range(toc_index + 1, len(top_level)) if top_level[index].name == "h1"),
        None,
    )
    if start_index is None:
        raise ValueError("rulebook content start not found")

    collector = _RulebookCollector()
    heading_stack: list[tuple[int, str]] = []
    current_page: str | None = None
    excluded_h1 = False

    def context(visibility: Visibility, scopes: frozenset[str], stack: list[tuple[int, str]]) -> _Context:
        path = tuple(text for _, text in stack)
        spoiler_index = next((index for index, (level, _) in enumerate(stack) if level == -1), None)
        section_path = path[:spoiler_index] if spoiler_index is not None else path
        section_key_override = (
            "/".join(slugify(part) for part in section_path) or "root" if spoiler_index is not None else None
        )
        return _Context(
            heading_path=path,
            anchor=slugify(path[-1]) if path else None,
            page_or_section=current_page,
            visibility=visibility,
            scope_keys=scopes,
            section_key_override=section_key_override,
        )

    def update_heading(node: Tag, stack: list[tuple[int, str]]) -> None:
        collector.flush()
        level = int(node.name[1])
        text = _heading_text(node)
        while stack and stack[-1][0] >= level:
            stack.pop()
        if text:
            stack.append((level, text))

    def ordered_parts(node: Tag) -> list[str | Tag]:
        parts: list[str | Tag] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                text = _clean_source_text(str(child))
                if text:
                    parts.append(text)
                continue
            if not isinstance(child, Tag):
                continue
            if child.name == "details":
                parts.append(child)
            elif child.find("details") is not None:
                parts.extend(ordered_parts(child))
            else:
                text = _text_of(child, SourceKey.RULEBOOK)
                if text:
                    parts.append(text)
        return parts

    def process_details(
        node: Tag,
        stack: list[tuple[int, str]],
        scopes: frozenset[str],
    ) -> None:
        collector.flush()
        label, remainder, scope = _summary_info(node, SourceKey.RULEBOOK)
        nested_stack = [*stack, (-1, label)]
        nested_scopes = scopes | {scope}
        protected_context = context(Visibility.PROTECTED, nested_scopes, nested_stack)
        if remainder:
            collector.add(protected_context, "prose", [remainder])
        for child in node.children:
            if isinstance(child, NavigableString):
                text = _clean_source_text(str(child))
                if text:
                    protected_context = context(Visibility.PROTECTED, nested_scopes, nested_stack)
                    collector.add(protected_context, "prose", [text])
                continue
            if not isinstance(child, Tag) or child.name == "summary":
                continue
            process_node(child, nested_stack, Visibility.PROTECTED, nested_scopes)
        collector.flush()

    def process_list(
        node: Tag,
        stack: list[tuple[int, str]],
        visibility: Visibility,
        scopes: frozenset[str],
    ) -> None:
        units: list[str] = []

        def flush_units() -> None:
            nonlocal units
            if units:
                collector.add(context(visibility, scopes, stack), "list", units)
                units = []

        for item in node.find_all("li", recursive=False):
            item_text = _text_of(item, SourceKey.RULEBOOK)
            if _STICKER_LABEL.fullmatch(item_text):
                continue
            for part in ordered_parts(item):
                if isinstance(part, Tag):
                    flush_units()
                    process_details(part, stack, scopes)
                elif part and not _STICKER_LABEL.fullmatch(part):
                    units.append(part)
        flush_units()

    def process_node(
        node: Tag,
        stack: list[tuple[int, str]],
        visibility: Visibility,
        scopes: frozenset[str],
    ) -> None:
        nonlocal current_page
        if node.name in _HEADING_TAGS:
            update_heading(node, stack)
            return
        if node.name == "details":
            process_details(node, stack, scopes)
            return
        if node.name == "p":
            page_anchor = node.find("a", attrs={"name": re.compile(r"^page_\d+$")})
            if page_anchor is not None:
                collector.flush()
                current_page = str(page_anchor["name"]).removeprefix("page_")
                return
            text = _text_of(node, SourceKey.RULEBOOK)
            if text and text != "Skipped due to spoilers":
                collector.add(context(visibility, scopes, stack), "prose", [text])
            return
        if node.name in {"ul", "ol"}:
            process_list(node, stack, visibility, scopes)
            return
        if node.name == "table":
            collector.add(context(visibility, scopes, stack), "table", _table_rows(node, SourceKey.RULEBOOK))
            return
        if node.name == "blockquote":
            text = _text_of(node, SourceKey.RULEBOOK)
            collector.add(context(visibility, scopes, stack), "blockquote", [text] if text else [])
            return
        if node.name == "pre":
            text = _text_of(node, SourceKey.RULEBOOK)
            collector.add(context(visibility, scopes, stack), "pre", [text] if text else [])
            return
        for child in node.children:
            if isinstance(child, Tag):
                process_node(child, stack, visibility, scopes)

    for node in top_level[start_index:]:
        if node.name == "h1":
            title = _heading_text(node)
            excluded_h1 = title in {"Appendix G: Index", "Credits"}
            if excluded_h1:
                collector.flush()
                heading_stack.clear()
                continue
        if excluded_h1:
            continue
        process_node(node, heading_stack, Visibility.PUBLIC, frozenset())
    collector.flush()
    return collector.chunks


def _leading_label(node: Tag) -> str | None:
    def first_meaningful(parent: Tag) -> tuple[str, str] | None:
        for child in parent.children:
            if isinstance(child, NavigableString):
                text = _clean_source_text(str(child))
                if text:
                    return "text", text
                continue
            if not isinstance(child, Tag) or child.name in {"br", "img"}:
                continue
            if child.name in {"strong", "b"}:
                text = _normalize_whitespace(child.get_text(" ", strip=True))
                return ("label", text) if text else None
            result = first_meaningful(child)
            if result is not None:
                return result
        return None

    result = first_meaningful(node)
    return result[1] if result and result[0] == "label" else None


def _faq_render_nodes(nodes: list[Tag], *, remove_hidden: bool) -> list[str]:
    units: list[str] = []
    for node in nodes:
        if node.name in {"ul", "ol"}:
            items = _list_items(node, SourceKey.FAQ, remove_hidden=remove_hidden)
            if items:
                units.append("\n".join(items))
        elif node.name == "table":
            rows = _table_rows(node, SourceKey.FAQ, remove_hidden=remove_hidden)
            if rows:
                units.append("\n".join(rows))
        else:
            text = _text_of(node, SourceKey.FAQ, remove_hidden=remove_hidden)
            if text:
                units.append(text)
    return units


def _faq_entry_text(nodes: list[Tag], *, remove_hidden: bool) -> str:
    return "\n\n".join(_faq_render_nodes(nodes, remove_hidden=remove_hidden))


def _has_hidden(nodes: list[Tag]) -> bool:
    return any(node.select_one("span.hidden") is not None for node in nodes)


def _text_before_first_hidden(nodes: list[Tag]) -> str:
    wrapper = BeautifulSoup("<div></div>", "html.parser").div
    if wrapper is None:
        return ""
    for node in nodes:
        wrapper.append(BeautifulSoup(str(node), "html.parser"))
    hidden = wrapper.select_one("span.hidden")
    if hidden is None:
        return ""
    pieces: list[str] = []
    for descendant in wrapper.descendants:
        if descendant is hidden:
            break
        if isinstance(descendant, NavigableString) and not descendant.find_parent("span", class_="hidden"):
            text = _normalize_whitespace(str(descendant))
            if text:
                pieces.append(text)
    return _normalize_whitespace(" ".join(pieces))


def _remove_label(text: str, label: str | None) -> str:
    remaining = text.strip()
    if label and remaining.lower().startswith(label.lower()):
        remaining = remaining[len(label) :]
    return remaining.lstrip(" \t\n-:–—")


def _public_variant_is_substantive(text: str, label: str | None) -> bool:
    remaining = _remove_label(text, label)
    if not remaining:
        return False
    lines = [line.strip(" \t-:–—") for line in remaining.splitlines() if line.strip(" \t-:–—")]
    return any(not re.fullmatch(r"Level\s+\d+", line, flags=re.IGNORECASE) for line in lines)


def _split_faq_entry(text: str, label: str | None) -> list[str]:
    if _approx_tokens(text) <= _MAX_CHUNK_TOKENS:
        return [text]
    if not label or _approx_tokens(label) >= _MAX_CHUNK_TOKENS:
        return _pack_units([text])
    answer = _remove_label(text, label)
    if not answer:
        return _split_long_unit(text)
    return _split_long_unit(answer, prefix=label)


def parse_faq(markdown_text: str) -> list[ParsedChunk]:
    soup = BeautifulSoup(render_html(_normalize_faq(markdown_text)), "html.parser")
    top_level = [node for node in soup.children if isinstance(node, Tag)]
    start_index = next(
        (
            index
            for index, node in enumerate(top_level)
            if node.name == "h2"
            and _heading_text(node) == _FAQ_START
            and isinstance(node.find("a", attrs={"name": "page_01"}), Tag)
        ),
        None,
    )
    if start_index is None:
        raise ValueError("FAQ content start not found")

    chunks: list[ParsedChunk] = []
    current_anchor: str | None = None
    current_section: str | None = None

    def emit_text(
        text: str,
        heading_path: tuple[str, ...],
        visibility: Visibility,
        scopes: frozenset[str],
        *,
        label: str | None,
        atomic: bool,
    ) -> None:
        if not text:
            return
        for body in _split_faq_entry(text, label):
            if not body or _approx_tokens(body) > _MAX_CHUNK_TOKENS:
                continue
            chunks.append(
                ParsedChunk(
                    section_key="/".join(slugify(part) for part in heading_path) or "root",
                    heading_path=heading_path,
                    anchor=current_anchor,
                    page_or_section=current_section,
                    body=body,
                    scope_keys=scopes,
                    visibility=visibility,
                    atomic=atomic,
                )
            )

    def emit_entry(entry: _FaqEntry, enclosing_scopes: frozenset[str]) -> None:
        full_text = _faq_entry_text(entry.nodes, remove_hidden=False)
        if not full_text:
            return
        if enclosing_scopes:
            emit_text(
                full_text,
                entry.heading_path,
                Visibility.PROTECTED,
                enclosing_scopes,
                label=entry.label,
                atomic=entry.atomic,
            )
            return
        if not _has_hidden(entry.nodes):
            emit_text(
                full_text,
                entry.heading_path,
                Visibility.PUBLIC,
                frozenset(),
                label=entry.label,
                atomic=entry.atomic,
            )
            return

        scope_label = entry.label or _text_before_first_hidden(entry.nodes)
        scope = (
            f"faq:{slugify(scope_label)}"
            if scope_label
            else f"faq:section:{slugify(current_section or 'section')}:locked"
        )
        public_text = _faq_entry_text(entry.nodes, remove_hidden=True)
        if _public_variant_is_substantive(public_text, entry.label or scope_label):
            emit_text(
                public_text,
                entry.heading_path,
                Visibility.PUBLIC,
                frozenset(),
                label=entry.label,
                atomic=entry.atomic,
            )
        emit_text(
            full_text,
            entry.heading_path,
            Visibility.PROTECTED,
            frozenset({scope}),
            label=entry.label,
            atomic=entry.atomic,
        )

    def emit_standalone(node: Tag, heading_path: tuple[str, ...], scopes: frozenset[str]) -> None:
        if node.name in {"ul", "ol"}:
            for item in node.find_all("li", recursive=False):
                emit_entry(_FaqEntry([item], _leading_label(item), heading_path, atomic=True), scopes)
            return
        emit_entry(
            _FaqEntry([node], _leading_label(node), heading_path, atomic=node.name in {"table", "blockquote"}),
            scopes,
        )

    def parse_sequence(
        nodes: list[Tag],
        stack: list[tuple[int, str]],
        enclosing_scopes: frozenset[str],
        *,
        details_mode: bool,
    ) -> None:
        nonlocal current_anchor, current_section
        current: _FaqEntry | None = None
        context_prefix: list[Tag] = []
        context_used = False
        heading_context = False
        pending_note: list[Tag] = []

        def heading_path() -> tuple[str, ...]:
            return tuple(text for _, text in stack)

        def finalize() -> None:
            nonlocal current
            if current is not None:
                emit_entry(current, enclosing_scopes)
                current = None

        def flush_unused_context() -> None:
            nonlocal context_prefix, context_used, pending_note
            if context_prefix and not context_used:
                for context_node in context_prefix:
                    emit_standalone(context_node, heading_path(), enclosing_scopes)
            for note in pending_note:
                emit_standalone(note, heading_path(), enclosing_scopes)
            context_prefix = []
            context_used = False
            pending_note = []

        for node in nodes:
            if node.name in _HEADING_TAGS:
                finalize()
                flush_unused_context()
                level = int(node.name[1])
                while stack and stack[-1][0] >= level:
                    stack.pop()
                text = _heading_text(node)
                if text:
                    stack.append((level, text))
                anchor = node.find("a", attrs={"name": re.compile(r"^page_")})
                if isinstance(anchor, Tag):
                    current_anchor = str(anchor.get("name"))
                    current_section = current_anchor.removeprefix("page_")
                heading_context = details_mode
                continue
            if node.name == "details":
                finalize()
                flush_unused_context()
                label, _, scope = _summary_info(node, SourceKey.FAQ)
                nested_stack = [*stack, (-1, label)]
                children = [child for child in node.children if isinstance(child, Tag) and child.name != "summary"]
                parse_sequence(children, nested_stack, enclosing_scopes | {scope}, details_mode=True)
                heading_context = False
                continue
            if node.name == "p":
                text = _text_of(node, SourceKey.FAQ)
                if not text:
                    continue
                label = _leading_label(node)
                if label:
                    finalize()
                    prefix = [*context_prefix, *pending_note] if heading_context else [*pending_note]
                    context_used = context_used or bool(context_prefix)
                    pending_note = []
                    current = _FaqEntry([*prefix, node], label, heading_path())
                    continue
                if current is not None:
                    if text.lower().startswith("note on "):
                        finalize()
                        pending_note = [node]
                    else:
                        current.nodes.append(node)
                    continue
                if pending_note:
                    pending_note.append(node)
                elif heading_context:
                    context_prefix.append(node)
                else:
                    emit_standalone(node, heading_path(), enclosing_scopes)
                continue
            if node.name in {"ul", "ol", "table", "blockquote", "pre"}:
                if current is not None:
                    current.nodes.append(node)
                elif heading_context:
                    context_prefix.append(node)
                else:
                    emit_standalone(node, heading_path(), enclosing_scopes)
                continue
            if node.name in {"hr", "link"}:
                continue
            nested = [child for child in node.children if isinstance(child, Tag)]
            if nested:
                parse_sequence(nested, stack, enclosing_scopes, details_mode=details_mode)

        finalize()
        flush_unused_context()

    parse_sequence(top_level[start_index:], [], frozenset(), details_mode=False)
    return chunks


def parse_source(source: SourceKey, markdown_text: str) -> list[ParsedChunk]:
    if source is SourceKey.RULEBOOK:
        return parse_rulebook(markdown_text)
    return parse_faq(markdown_text)
