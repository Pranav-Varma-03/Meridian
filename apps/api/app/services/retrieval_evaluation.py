"""Versioned, provider-neutral metrics for grounded retrieval evaluation.

The evaluator intentionally consumes recorded candidate outcomes.  It can therefore
measure the current production pipeline, shadow candidates, and future strategies
without coupling tests or the command-line runner to a live Pinecone index.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

RECALL_CUTOFFS = (5, 10, 36)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """A source-grounded evaluation case with explicit gold evidence identities."""

    id: str
    kind: str
    query: str
    gold_chunk_ids: frozenset[str]
    answerable: bool
    expects_conflict: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationOutcome:
    """One recorded execution of an :class:`EvaluationCase`."""

    case_id: str
    retrieved_chunk_ids: tuple[str, ...]
    cited_chunk_ids: tuple[str, ...]
    answer_is_insufficient: bool
    answer_reports_conflict: bool
    answer_is_source_grounded: bool
    prompt_tokens: int
    ingestion_cost_usd: float
    index_record_count: int
    retrieval_latency_ms: float


def load_cases(payload: dict[str, Any]) -> list[EvaluationCase]:
    """Validate and normalize the checked-in fixture's externally supplied fields."""
    version = payload.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("Evaluation fixture must declare a positive integer version")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("Evaluation fixture must contain at least one case")

    cases: list[EvaluationCase] = []
    seen_ids: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise ValueError("Evaluation cases must be objects")
        case_id = raw.get("id")
        query = raw.get("query")
        kind = raw.get("kind")
        gold = raw.get("gold_evidence")
        answerable = raw.get("answerable")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen_ids
            or not isinstance(query, str)
            or not query.strip()
            or not isinstance(kind, str)
            or not isinstance(answerable, bool)
            or not isinstance(gold, list)
        ):
            raise ValueError(f"Invalid evaluation case: {case_id!r}")
        gold_chunk_ids = frozenset(
            str(item["chunk_id"])
            for item in gold
            if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)
        )
        if answerable and not gold_chunk_ids:
            raise ValueError(f"Answerable case {case_id} needs gold evidence")
        if not answerable and gold_chunk_ids:
            raise ValueError(f"Unanswerable case {case_id} must not have gold evidence")
        seen_ids.add(case_id)
        cases.append(
            EvaluationCase(
                id=case_id,
                kind=kind,
                query=query,
                gold_chunk_ids=gold_chunk_ids,
                answerable=answerable,
                expects_conflict=bool(raw.get("expects_conflict", False)),
            )
        )
    return cases


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def evaluate(
    cases: list[EvaluationCase], outcomes: list[EvaluationOutcome]
) -> dict[str, float | int]:
    """Return stable aggregate retrieval, citation, safety, and cost metrics."""
    by_case = {outcome.case_id: outcome for outcome in outcomes}
    unknown = set(by_case) - {case.id for case in cases}
    if unknown:
        raise ValueError(f"Outcomes reference unknown cases: {sorted(unknown)}")

    answerable = [case for case in cases if case.answerable]
    recall: dict[int, list[float]] = {cutoff: [] for cutoff in RECALL_CUTOFFS}
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    citation_correctness: list[float] = []
    source_groundedness: list[float] = []
    insufficiency_or_conflict: list[float] = []
    prompt_tokens: list[float] = []
    ingestion_costs: list[float] = []
    index_records: list[float] = []
    latencies: list[float] = []

    for case in cases:
        outcome = by_case.get(case.id)
        if outcome is None:
            continue
        retrieved = list(outcome.retrieved_chunk_ids)
        cited = set(outcome.cited_chunk_ids)
        prompt_tokens.append(float(outcome.prompt_tokens))
        ingestion_costs.append(outcome.ingestion_cost_usd)
        index_records.append(float(outcome.index_record_count))
        latencies.append(outcome.retrieval_latency_ms)
        source_groundedness.append(1.0 if outcome.answer_is_source_grounded else 0.0)

        if case.answerable:
            for cutoff in RECALL_CUTOFFS:
                recall[cutoff].append(
                    1.0 if set(retrieved[:cutoff]) & case.gold_chunk_ids else 0.0
                )
            rank = next(
                (
                    index + 1
                    for index, chunk_id in enumerate(retrieved[:10])
                    if chunk_id in case.gold_chunk_ids
                ),
                None,
            )
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            precision_window = retrieved[:10]
            precisions.append(
                sum(chunk_id in case.gold_chunk_ids for chunk_id in precision_window)
                / len(precision_window)
                if precision_window
                else 0.0
            )
            citation_correctness.append(
                1.0 if cited and cited.issubset(case.gold_chunk_ids) else 0.0
            )
            insufficiency_or_conflict.append(
                1.0
                if (case.expects_conflict and outcome.answer_reports_conflict)
                or (not case.expects_conflict and not outcome.answer_is_insufficient)
                else 0.0
            )
        else:
            insufficiency_or_conflict.append(
                1.0 if outcome.answer_is_insufficient and not cited else 0.0
            )

    return {
        "case_count": len(cases),
        "outcome_count": len(outcomes),
        "answerable_case_count": len(answerable),
        **{f"recall_at_{cutoff}": _mean(values) for cutoff, values in recall.items()},
        "mrr_at_10": _mean(reciprocal_ranks),
        "context_precision_at_10": _mean(precisions),
        "citation_correctness": _mean(citation_correctness),
        "insufficiency_conflict_accuracy": _mean(insufficiency_or_conflict),
        "source_groundedness": _mean(source_groundedness),
        "prompt_tokens_mean": _mean(prompt_tokens),
        "ingestion_cost_usd_mean": _mean(ingestion_costs),
        "index_record_count_mean": _mean(index_records),
        "retrieval_latency_ms_p50": _percentile(latencies, 0.50),
        "retrieval_latency_ms_p95": _percentile(latencies, 0.95),
    }


def outcomes_from_payload(payload: dict[str, Any]) -> list[EvaluationOutcome]:
    """Parse runner result files without accepting malformed metric inputs."""
    raw_outcomes = payload.get("outcomes")
    if not isinstance(raw_outcomes, list):
        raise ValueError("Results must contain an outcomes array")
    outcomes: list[EvaluationOutcome] = []
    for raw in raw_outcomes:
        if not isinstance(raw, dict):
            raise ValueError("Each outcome must be an object")
        try:
            outcomes.append(
                EvaluationOutcome(
                    case_id=str(raw["case_id"]),
                    retrieved_chunk_ids=tuple(
                        map(str, raw.get("retrieved_chunk_ids", []))
                    ),
                    cited_chunk_ids=tuple(map(str, raw.get("cited_chunk_ids", []))),
                    answer_is_insufficient=bool(raw["answer_is_insufficient"]),
                    answer_reports_conflict=bool(
                        raw.get("answer_reports_conflict", False)
                    ),
                    answer_is_source_grounded=bool(raw["answer_is_source_grounded"]),
                    prompt_tokens=int(raw["prompt_tokens"]),
                    ingestion_cost_usd=float(raw["ingestion_cost_usd"]),
                    index_record_count=int(raw["index_record_count"]),
                    retrieval_latency_ms=float(raw["retrieval_latency_ms"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid evaluation outcome") from exc
    return outcomes
