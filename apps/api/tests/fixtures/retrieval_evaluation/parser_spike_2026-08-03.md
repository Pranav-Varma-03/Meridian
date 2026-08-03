# Local parser spike — 2026-08-03

## Method

Compared the current Meridian extractor, local Unstructured, and PDFMiner on
generated non-sensitive PDF and DOCX samples containing headings, a policy
identifier, paragraphs, and a two-column table. The sample generator and output
were kept under `/private/tmp`; no user uploads were inspected.

## Results

| Provider | PDF headings/text | PDF table signal | DOCX headings/text | DOCX table signal | Dependencies and runtime notes |
| --- | --- | --- | --- | --- | --- |
| Current `pypdf` / OOXML extractor | Preserved text order | Preserved literal `Plan \| Seats` text only | Flattened headings into text | Flattened table cells into separate lines | Already installed; lowest build and latency cost. |
| Unstructured (`partition_pdf(strategy="fast")`, `partition_docx`) | Classified header/title/narrative elements | Preserved row-like labels, not a semantic table in fast PDF mode | Preserved title/narrative element classes | Emitted a `Table` element | Apache-2.0; installed with PDF/DOCX extras. PDF initialization was materially heavier and emitted font-cache warnings in constrained environments. |
| PDFMiner text extraction | Preserved text order | Preserved literal table lines only | N/A | N/A | MIT; lightweight pure-Python dependency already transitively available. No DOCX support. |

## Selection

Use **Unstructured behind Meridian's internal `DocumentParser` adapter** for
structured DOCX and supported digital PDFs. Retain the current `pypdf`/OOXML
extractor as the compatibility fallback when Unstructured is unavailable or its
runtime dependencies fail. Treat scanned PDFs/OCR as unsupported in this change;
fail ingestion safely rather than silently producing empty evidence.

The requested local Unstructured layout (`by_title`/`hi_res`) probe was also run.
It could not initialize because its layout model attempted to download into the
non-writable Hugging Face cache. This confirms that `by_title` requires a pinned,
pre-provisioned model cache and writable cache directories before it can be enabled;
it is not safe to make it Meridian's default during this change.

## Operational constraints

- Pin Unstructured and its PDF extras in the API environment.
- Provide writable Matplotlib/font caches in container deployments; otherwise
  parser startup emits cache warnings and can pay initialization cost repeatedly.
- Do not claim PDF fast-mode table reconstruction. Preserve row-like text and keep
  table-specific structure improvements behind future fixture evaluation.
- PDFMiner remains the lightweight layout-capable comparison adapter for the spike,
  not the selected cross-format parser.
