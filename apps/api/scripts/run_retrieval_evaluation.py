"""Compute comparable grounded-retrieval metrics from a fixture and result record.

Usage:
    python scripts/run_retrieval_evaluation.py \
      --fixture tests/fixtures/retrieval_evaluation/v1.json \
      --results /path/to/recorded-results.json \
      --output /path/to/metrics.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.retrieval_evaluation import (
    evaluate,
    load_cases,
    outcomes_from_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = load_cases(json.loads(args.fixture.read_text()))
    outcomes = outcomes_from_payload(json.loads(args.results.read_text()))
    metrics = evaluate(cases, outcomes)
    rendered = json.dumps(metrics, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
