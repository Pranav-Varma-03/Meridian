# Dense 512-character baseline — disposable tenant (2026-08-03)

## Scope

- **Configuration:** existing dense-only production behavior; no application setting,
  retrieval code, or active document generation was changed.
- **Corpus:** two disposable TXT uploads (`employee-handbook.txt` and
  `evaluation-corpus.txt`), ingested by the running Meridian worker.
- **Index records:** 4 retrieval children (one handbook child and three corpus
  children).
- **Execution surface:** authenticated Next.js BFF `POST /api/meridian/chat`.
- **Caveat:** this is a live disposable smoke baseline, not the future full fixture
  harness. The current API exposes selected citations, not the full dense top-36
  candidate list, so Recall@K and MRR below are conservative selected-evidence
  proxies until retrieval instrumentation is added.

## Results

| Case | Outcome | Selected evidence | BFF stream duration |
| --- | --- | --- | ---: |
| Direct fact — travel meal limit | supported | handbook child `af0f6f33-29ff-4e8b-947c-517e90996f32` | 23,687 ms |
| Paraphrase — food expenses while travelling | supported | handbook child plus unrelated corpus child | 22,908 ms |
| Exact identifier — `TRV-104` | supported | corpus child `be1486fa-9779-489f-ae6f-73515474e436` | 12,949 ms |
| Numbered clause — `4.2(b)` | **insufficient** | none | 8,549 ms |
| Table — 250 seats | supported | corpus child `28cc017c-fe60-4815-a1fd-42874c74ca00` | 24,856 ms |
| Neighboring context — exception approver | supported | corpus child `28cc017c-fe60-4815-a1fd-42874c74ca00` | 11,436 ms |
| Multi-section — renewal vs. termination | supported | corpus child `8504e290-92d9-4c1c-9a03-27ac685e2d1b` | 12,002 ms |
| Conflict — retention period | conflict reported | corpus child `8504e290-92d9-4c1c-9a03-27ac685e2d1b` | 14,306 ms |
| Cross-document/supersession | supported | corpus child `8504e290-92d9-4c1c-9a03-27ac685e2d1b` | 11,383 ms |
| Unanswerable — capital of Japan | deterministic insufficiency | none | 8,194 ms |

## Baseline metrics

- Answerable selected-evidence recall proxy: **8/9 (0.889)**.
- Selected-evidence MRR proxy: **0.889**; each successful answer had a supporting
  selected citation in first position.
- Context precision proxy: **0.667**. Fixed character chunks often include
  neighboring unrelated material and trigger extra citations.
- Citation correctness proxy: **0.444** under strict evidence-only citation parity;
  several otherwise correct answers cited an extra, non-supporting fixed chunk.
- Insufficiency/conflict accuracy: **0.900**. The numbered clause is a false
  insufficiency; the unanswerable question and conflicting retention records were
  handled safely.
- Source-groundedness review: **0.800**. Two answers contained unsupported
  extrapolation despite relevant sources, reinforcing the source-only prompt-policy
  work in this change.
- Retrieval-plus-generation stream latency: **p50 12,476 ms**, **p95 24,330 ms**,
  mean **15,027 ms**.
- Prompt-token and ingestion-cost metrics: **not instrumented by the current
  production path**. The evaluation runner supports recording them when the capture
  adapter is connected; they are intentionally not fabricated for this baseline.

## Findings carried into the change

1. Dense-only retrieval misses the exact numbered-clause query, motivating the
   PostgreSQL lexical channel and rank fusion.
2. Fixed 512-character chunking creates overlap and unrelated neighboring citations.
3. The model can add unsupported interpretation even with source excerpts, so
   source-only policy tests must be activation gates.
4. The existing unsupported-question path correctly bypasses factual general-knowledge
   answers and returns deterministic insufficiency.
