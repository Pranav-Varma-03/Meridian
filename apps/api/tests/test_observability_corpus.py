import json
from pathlib import Path


def test_representative_observability_corpus_profile_is_bounded() -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "observability"
        / "representative_corpus_v1.json"
    )
    profile = json.loads(fixture.read_text())

    assert profile["classification"] == "de-identified-disposable"
    assert len(profile["document_set"]) >= 10
    assert sum(profile["query_mix"].values()) == 1
    assert profile["load_profiles"]["expected_concurrency"] > 0
    assert "p95_latency_ms" in profile["acceptance_measurements"]
