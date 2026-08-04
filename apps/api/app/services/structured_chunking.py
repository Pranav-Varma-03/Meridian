"""Deterministic token-bounded child and parent construction."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.services.document_parsing import DocumentElement
from app.services.tokenization import Tokenizer, validate_chunk_bounds


@dataclass(frozen=True, slots=True)
class StructuredChild:
    child_index: int
    source_text: str
    embedding_text: str
    token_count: int
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    source_start: int
    source_end: int
    previous_child_index: int | None
    next_child_index: int | None
    parent_index: int | None = None


@dataclass(frozen=True, slots=True)
class ParentWindow:
    parent_index: int
    source_text: str
    token_count: int
    section_path: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    source_start: int
    source_end: int
    child_indexes: tuple[int, ...]


def build_structure_aware_children(
    *,
    elements: list[DocumentElement],
    tokenizer: Tokenizer,
    document_title: str,
    child_target_tokens: int = 384,
    child_max_tokens: int = 512,
    child_overlap_tokens: int = 48,
) -> list[StructuredChild]:
    validate_chunk_bounds(
        child_target_tokens=child_target_tokens,
        child_max_tokens=child_max_tokens,
        child_overlap_tokens=child_overlap_tokens,
        parent_target_tokens=1,
        parent_max_tokens=1,
    )
    children: list[StructuredChild] = []
    current: list[DocumentElement] = []
    current_tokens = 0
    current_section: tuple[str, ...] | None = None

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        source_text = "\n\n".join(element.text for element in current)
        children.append(
            _child_from_elements(
                child_index=len(children),
                elements=current,
                source_text=source_text,
                token_count=current_tokens,
                document_title=document_title,
            )
        )
        current = []
        current_tokens = 0

    for element in elements:
        for fragment in _bounded_element_fragments(
            element, tokenizer, child_max_tokens
        ):
            fragment_tokens = tokenizer.count(fragment.text)
            changes_section = current and fragment.section_path != current_section
            exceeds_target = (
                current and current_tokens + fragment_tokens > child_target_tokens
            )
            exceeds_max = (
                current and current_tokens + fragment_tokens > child_max_tokens
            )
            if changes_section or exceeds_target or exceeds_max:
                flush()
            if not current:
                current_section = fragment.section_path
            current.append(fragment)
            current_tokens += fragment_tokens
    flush()

    # Add overlap only to adjacent children in the same section, and never push a
    # child above its hard maximum. The copied suffix remains exact source text.
    overlapped: list[StructuredChild] = []
    for index, child in enumerate(children):
        source_text = child.source_text
        token_count = child.token_count
        if index and children[index - 1].section_path == child.section_path:
            suffix = _suffix_at_most(
                children[index - 1].source_text, tokenizer, child_overlap_tokens
            )
            if suffix:
                candidate = f"{suffix}\n\n{source_text}"
                candidate_count = tokenizer.count(candidate)
                if candidate_count <= child_max_tokens:
                    source_text, token_count = candidate, candidate_count
        overlapped.append(
            replace(
                child,
                source_text=source_text,
                embedding_text=build_embedding_text(
                    document_title=document_title,
                    section_path=child.section_path,
                    page_start=child.page_start,
                    page_end=child.page_end,
                    source_text=source_text,
                ),
                token_count=token_count,
                previous_child_index=index - 1 if index else None,
                next_child_index=index + 1 if index + 1 < len(children) else None,
            )
        )
    return overlapped


def build_parent_windows(
    *,
    children: list[StructuredChild],
    tokenizer: Tokenizer,
    parent_target_tokens: int = 900,
    parent_max_tokens: int = 1200,
) -> tuple[list[StructuredChild], list[ParentWindow]]:
    validate_chunk_bounds(
        child_target_tokens=1,
        child_max_tokens=2,
        child_overlap_tokens=0,
        parent_target_tokens=parent_target_tokens,
        parent_max_tokens=parent_max_tokens,
    )
    parents: list[ParentWindow] = []
    assigned: list[StructuredChild] = []
    current: list[StructuredChild] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        source_text = "\n\n".join(child.source_text for child in current)
        parent_index = len(parents)
        parent = ParentWindow(
            parent_index=parent_index,
            source_text=source_text,
            token_count=tokenizer.count(source_text),
            section_path=current[0].section_path,
            page_start=_minimum_page(current),
            page_end=_maximum_page(current),
            source_start=min(child.source_start for child in current),
            source_end=max(child.source_end for child in current),
            child_indexes=tuple(child.child_index for child in current),
        )
        parents.append(parent)
        assigned.extend(replace(child, parent_index=parent_index) for child in current)
        current = []
        current_tokens = 0

    for child in children:
        changes_section = current and child.section_path != current[0].section_path
        exceeds_max = current and current_tokens + child.token_count > parent_max_tokens
        reaches_target = current and current_tokens >= parent_target_tokens
        if changes_section or exceeds_max or reaches_target:
            flush()
        current.append(child)
        current_tokens += child.token_count
    flush()
    return assigned, parents


def build_embedding_text(
    *,
    document_title: str,
    section_path: tuple[str, ...],
    page_start: int | None,
    page_end: int | None,
    source_text: str,
) -> str:
    locator = ""
    if page_start is not None:
        locator = (
            str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
        )
    section = " > ".join(section_path) or "(document body)"
    return f"Document: {document_title}\nSection: {section}\nPages: {locator}\n\n{source_text}"


def _child_from_elements(
    *,
    child_index: int,
    elements: list[DocumentElement],
    source_text: str,
    token_count: int,
    document_title: str,
) -> StructuredChild:
    return StructuredChild(
        child_index=child_index,
        source_text=source_text,
        embedding_text=build_embedding_text(
            document_title=document_title,
            section_path=elements[0].section_path,
            page_start=_minimum_page(elements),
            page_end=_maximum_page(elements),
            source_text=source_text,
        ),
        token_count=token_count,
        section_path=elements[0].section_path,
        page_start=_minimum_page(elements),
        page_end=_maximum_page(elements),
        source_start=min(element.source_start for element in elements),
        source_end=max(element.source_end for element in elements),
        previous_child_index=None,
        next_child_index=None,
    )


def _bounded_element_fragments(
    element: DocumentElement, tokenizer: Tokenizer, maximum_tokens: int
) -> list[DocumentElement]:
    if tokenizer.count(element.text) <= maximum_tokens:
        return [element]
    if element.element_type == "table":
        rows = element.text.splitlines()
        header, body = rows[0], rows[1:]
        pieces = _pack_units(body, tokenizer, maximum_tokens, prefix=header)
    else:
        units = _structural_units(element.text)
        pieces = _pack_units(units, tokenizer, maximum_tokens)
    fragments: list[DocumentElement] = []
    start = element.source_start
    for piece in pieces:
        fragments.append(
            DocumentElement(
                element_type=element.element_type,
                text=piece,
                section_path=element.section_path,
                page_start=element.page_start,
                page_end=element.page_end,
                source_start=start,
                source_end=start + len(piece),
                metadata=element.metadata,
            )
        )
        start += len(piece)
    return fragments


def _structural_units(text: str) -> list[str]:
    for pattern in (r"\n\s*\n", r"(?<=[.!?])\s+", r"(?<=[,;:])\s+", r"\s+"):
        units = [unit.strip() for unit in re.split(pattern, text) if unit.strip()]
        if len(units) > 1:
            return units
    return [text]


def _pack_units(
    units: list[str], tokenizer: Tokenizer, maximum_tokens: int, *, prefix: str = ""
) -> list[str]:
    pieces: list[str] = []
    current: list[str] = [prefix] if prefix else []
    for unit in units:
        candidate = "\n".join([*current, unit]) if current else unit
        if tokenizer.count(candidate) <= maximum_tokens:
            current.append(unit)
            continue
        if current and current != [prefix]:
            pieces.append("\n".join(current))
            current = [prefix, unit] if prefix else [unit]
        else:
            for token_piece in tokenizer.split(unit, maximum_tokens=maximum_tokens):
                pieces.append(
                    "\n".join([prefix, token_piece]) if prefix else token_piece
                )
            current = [prefix] if prefix else []
    if current and current != [prefix]:
        pieces.append("\n".join(current))
    return pieces


def _suffix_at_most(text: str, tokenizer: Tokenizer, maximum_tokens: int) -> str:
    tokens = tokenizer._encoding.encode(text, disallowed_special=())
    return tokenizer._encoding.decode(tokens[-maximum_tokens:]) if tokens else ""


def _minimum_page(values: list[DocumentElement] | list[StructuredChild]) -> int | None:
    pages = [value.page_start for value in values if value.page_start is not None]
    return min(pages) if pages else None


def _maximum_page(values: list[DocumentElement] | list[StructuredChild]) -> int | None:
    pages = [value.page_end for value in values if value.page_end is not None]
    return max(pages) if pages else None
