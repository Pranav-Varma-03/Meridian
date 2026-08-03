import json
from pathlib import Path

import pytest

from app.services.retrieval_evaluation import (
    EvaluationOutcome,
    evaluate,
    load_cases,
)

FIXTURE = Path(__file__).parent / "fixtures" / "retrieval_evaluation" / "v1.json"


def test_versioned_fixture_covers_required_retrieval_cases() -> None:
    cases = load_cases(json.loads(FIXTURE.read_text()))

    assert {case.kind for case in cases} == {
        "direct_fact",
        "paraphrase",
        "exact_identifier",
        "numbered_clause",
        "table",
        "neighbor_context",
        "multi_section",
        "conflict",
        "cross_document",
        "unanswerable",
    }
    assert all(case.gold_chunk_ids for case in cases if case.answerable)
    assert not next(case for case in cases if not case.answerable).gold_chunk_ids


def test_evaluator_reports_retrieval_safety_and_operational_metrics() -> None:
    cases = load_cases(json.loads(FIXTURE.read_text()))
    outcomes = [
        EvaluationOutcome(
            case_id=case.id,
            retrieved_chunk_ids=tuple(case.gold_chunk_ids),
            cited_chunk_ids=tuple(case.gold_chunk_ids),
            answer_is_insufficient=not case.answerable,
            answer_reports_conflict=case.expects_conflict,
            answer_is_source_grounded=True,
            prompt_tokens=100,
            ingestion_cost_usd=0.01,
            index_record_count=20,
            retrieval_latency_ms=10.0,
        )
        for case in cases
    ]

    metrics = evaluate(cases, outcomes)

    assert metrics["recall_at_5"] == 1.0
    assert metrics["recall_at_10"] == 1.0
    assert metrics["recall_at_36"] == 1.0
    assert metrics["mrr_at_10"] == 1.0
    assert metrics["citation_correctness"] == 1.0
    assert metrics["insufficiency_conflict_accuracy"] == 1.0
    assert metrics["retrieval_latency_ms_p95"] == 10.0


def test_fixture_rejects_answerable_cases_without_gold_evidence() -> None:
    with pytest.raises(ValueError, match="needs gold evidence"):
        load_cases(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "bad",
                        "kind": "x",
                        "query": "q",
                        "answerable": True,
                        "gold_evidence": [],
                    }
                ],
            }
        )
