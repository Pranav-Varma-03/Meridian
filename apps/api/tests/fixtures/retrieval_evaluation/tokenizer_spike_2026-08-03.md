# Tokenizer selection — 2026-08-03

Meridian's current runtime already ships `tiktoken`. The hosted
`llama-text-embed-v2` provider does not expose a local compatible tokenizer, so the
ingestion strategy selects the deterministic `cl100k_base` tokenizer and records its
name in every future generation configuration.

Representative inputs showed that whitespace counts under-estimate structured input:

| Input shape | Whitespace words | `cl100k_base` tokens |
| --- | ---: | ---: |
| `TRV-104` identifier sentence | 7 | 11 |
| `4.2(b)` numbered clause | 11 | 16 |
| two-column table text | 6 | 8 |
| ordinary policy sentence | 9 | 10 |

Use the design's 512-token child hard maximum as a **conservative local limit** and
retain a 20% provider-limit margin until Pinecone publishes a model-specific local
tokenizer or rejects a documented payload size. This avoids treating whitespace word
counts as token counts and keeps ingestion deterministic across deployments.
