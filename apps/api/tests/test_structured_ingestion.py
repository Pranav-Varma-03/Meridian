import uuid

import pytest

from app.services import structured_ingestion
from app.services.structured_chunking import ParentWindow, StructuredChild


class _Session:
    def __init__(self) -> None:
        self.groups: list[list[object]] = []

    def add_all(self, values: list[object]) -> None:
        self.groups.append(values)

    async def flush(self) -> None:
        for group in self.groups:
            for value in group:
                if getattr(value, "id", None) is None:
                    value.id = uuid.uuid4()


def _child(index: int, *, parent_index: int) -> StructuredChild:
    return StructuredChild(
        child_index=index,
        source_text=f"exact evidence {index}",
        embedding_text=f"Document: Test\n\nexact evidence {index}",
        token_count=5,
        section_path=("Policy",),
        page_start=1,
        page_end=1,
        source_start=index * 20,
        source_end=index * 20 + 16,
        previous_child_index=index - 1 if index else None,
        next_child_index=index + 1 if index == 0 else None,
        parent_index=parent_index,
    )


@pytest.mark.asyncio
async def test_persist_parent_child_generation_keeps_source_and_links_rows() -> None:
    session = _Session()
    document_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    parents = [
        ParentWindow(
            parent_index=0,
            source_text="exact evidence 0\n\nexact evidence 1",
            token_count=10,
            section_path=("Policy",),
            page_start=1,
            page_end=1,
            source_start=0,
            source_end=36,
            child_indexes=(0, 1),
        )
    ]

    rows = await structured_ingestion.persist_parent_child_generation(
        session,  # type: ignore[arg-type]
        document_id=document_id,
        generation_id=generation_id,
        source_file="policy.txt",
        strategy_version="structure_aware_parent_child_v1",
        children=[_child(0, parent_index=0), _child(1, parent_index=0)],
        parents=parents,
    )

    assert len(rows) == 2
    assert all(row.parent_id for row in rows)
    assert rows[0].next_chunk_id == rows[1].id
    assert rows[1].previous_chunk_id == rows[0].id
    assert rows[0].chunk_text == "exact evidence 0"
    assert rows[0].embedding_text.startswith("Document: Test")
    assert rows[0].metadata_json == {
        "source_file": "policy.txt",
        "chunk_index": 0,
        "page_number": 1,
        "section_heading": "Policy",
    }


def test_uses_structured_generation_requires_the_persisted_strategy() -> None:
    assert structured_ingestion.uses_structured_generation(
        {"chunker": {"strategy": "structure_aware_parent_child_v1"}}
    )
    assert not structured_ingestion.uses_structured_generation({})
    assert not structured_ingestion.uses_structured_generation(None)
