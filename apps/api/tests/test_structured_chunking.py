from app.services.document_parsing import DocumentElement
from app.services.structured_chunking import (
    build_parent_windows,
    build_structure_aware_children,
)
from app.services.tokenization import get_tokenizer


def _element(
    text: str,
    *,
    section: tuple[str, ...] = ("Travel",),
    page: int = 1,
    element_type: str = "paragraph",
    start: int = 0,
) -> DocumentElement:
    return DocumentElement(
        element_type=element_type,  # type: ignore[arg-type]
        text=text,
        section_path=section,
        page_start=page,
        page_end=page,
        source_start=start,
        source_end=start + len(text),
    )


def test_children_are_token_bounded_structured_and_source_only() -> None:
    tokenizer = get_tokenizer("cl100k_base")
    elements = [
        _element("Meals are reimbursable when receipts are submitted.", start=0),
        _element("The daily limit is 75 USD.", page=2, start=55),
        _element(
            "Approval is required above the limit.",
            section=("Travel", "Approval"),
            start=85,
        ),
    ]

    children = build_structure_aware_children(
        elements=elements,
        tokenizer=tokenizer,
        document_title="Employee Handbook",
        child_target_tokens=16,
        child_max_tokens=24,
        child_overlap_tokens=4,
    )

    assert len(children) >= 2
    assert all(child.token_count <= 24 for child in children)
    assert children[0].source_text in children[0].embedding_text
    assert "Document: Employee Handbook" in children[0].embedding_text
    assert all("Document:" not in child.source_text for child in children)
    assert children[-1].section_path == ("Travel", "Approval")


def test_tables_repeat_headers_and_parent_windows_are_bounded() -> None:
    tokenizer = get_tokenizer("cl100k_base")
    table = "Item | Limit\n" + "\n".join(
        f"Meal {index} | {index * 10} USD" for index in range(1, 15)
    )
    children = build_structure_aware_children(
        elements=[_element(table, element_type="table")],
        tokenizer=tokenizer,
        document_title="Policy",
        child_target_tokens=18,
        child_max_tokens=24,
        child_overlap_tokens=0,
    )
    assigned, parents = build_parent_windows(
        children=children,
        tokenizer=tokenizer,
        parent_target_tokens=35,
        parent_max_tokens=48,
    )

    assert len(children) > 1
    assert all(child.source_text.startswith("Item | Limit") for child in children)
    assert all(parent.token_count <= 48 for parent in parents)
    assert all(child.parent_index is not None for child in assigned)
    assert sum(len(parent.child_indexes) for parent in parents) == len(children)
