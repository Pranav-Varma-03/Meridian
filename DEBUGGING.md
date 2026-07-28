# Meridian VS Code debugging

The repository includes launch profiles in the workspace-level
`.vscode/launch.json`. They deliberately run the API without Uvicorn reload: reload
starts a child process and makes breakpoints unreliable. Stop and restart the debug
session after Python changes instead.

## One-time setup

1. Open `/Users/pranav/Desktop/RAG` as the VS Code workspace so the provided paths
   resolve correctly.
2. Run `make setup` from `Meridian`, then copy `Meridian/.env.example` to
   `Meridian/.env` and supply the required local service credentials.
3. Run database migrations with `make db-migrate` and make Redis available.
4. Install the recommended VS Code Python and JavaScript debugger extensions if
   prompted. The workspace pins Python debugging to
   `Meridian/apps/api/.venv/bin/python`, the same environment used by `make dev-api`.
   Python debug profiles read `Meridian/.env` unchanged, including the configured
   Upstash `REDIS_URL`; they do not replace it with a local Redis endpoint.

Before launching an API or worker debug profile, verify the configured Upstash Redis
connection from the same network:

```bash
redis-cli --tls -u "$REDIS_URL" ping
```

Expected output: `PONG`.

Never put breakpoints in token handling merely to inspect credentials. Use request
IDs and the existing structured logs; bearer tokens must not be copied into the
debug console or committed files.

## Launch profiles

| Profile | Use it for |
| --- | --- |
| `Meridian: FastAPI API` | Routes, authentication, validation, and API requests |
| `Meridian: Ingestion worker` | Redis queue consumption, parsing, chunking, embeddings, and vector upserts |
| `Meridian: Purge worker` | Background deletion of vectors and stored files |
| `Meridian: API + ingestion worker` | The normal upload-to-ready ingestion path |
| `Meridian: Next.js web` | Server-side web/auth behavior |
| `Meridian: Chrome web client` | Browser-side Next.js behavior; start the web profile first |
| `Meridian: Pytest current file` | Reproduce a failing backend test with breakpoints |

## Debug flows and breakpoint map

### Document ingestion

1. In the Run and Debug panel, select `Meridian: API + ingestion worker` and press
   `F5`.
2. Add breakpoints on the first executable line of these functions, in order:
   - `apps/api/app/routers/documents.py` → `upload_document`
   - `apps/api/app/services/documents.py` → `create_uploaded_document`
   - `apps/api/app/services/ingestion_worker.py` → `process_next_ingestion_job`
   - `apps/api/app/services/ingestion_worker_runner.py` →
     `default_ingestion_processor`
   - `apps/api/app/services/document_processor.py` → `extract_text_segments` and
     `build_chunks`
   - `apps/api/app/services/embeddings.py` → `embed_chunks` and `upsert_embeddings`
3. Upload a small TXT file through Swagger at `http://localhost:8000/docs` or the
   web app. Use `F10` to step over a call, `F11` to enter it, and `Shift+F11` to
   leave it.
4. Inspect `job.id`, `document.id`, `generation.id`, and `chunk_count`; do not
   inspect or export API keys. Continue until `mark_ingestion_job_ready` runs.

If a breakpoint in the worker is not reached, verify the upload returned `202`, the
job is queued in Redis, and the **Ingestion worker** debug session is still running.

### Grounded chat and SSE

1. Start `Meridian: FastAPI API` (or the full-stack compound).
2. Add breakpoints to:
   - `apps/api/app/routers/chat.py` → `chat`
   - `apps/api/app/services/chat_generation.py` → `rewrite_retrieval_query`,
     `build_messages`, and `stream_grounded_answer`
   - `apps/api/app/services/retrieval.py` → `retrieve_sources`
3. Send a chat request from Swagger or the web client. After `stream_grounded_answer`
   starts yielding, do not pause for long: the browser/Swagger client may time out.
4. Inspect source counts, document generation IDs, and token budgets. The successful
   stream should finish with `sources` then `done`; an error event must not persist a
   partial assistant message.

### Isolated test reproduction

1. Open the failing backend test file.
2. Set a breakpoint in the production function it exercises.
3. Choose `Meridian: Pytest current file` and press `F5`.
4. Use the Variables, Watch, and Call Stack panels rather than adding print
   statements. This keeps the async flow deterministic and avoids leaking secrets.

## Breakpoint tips

- Enable **Raised Exceptions** in the Breakpoints panel when locating an unexpected
  `HTTPException`, then turn it off after diagnosis.
- Add conditional breakpoints for a known `job_id` or `conversation_id` to avoid
  stopping on unrelated requests.
- Use logpoints for high-frequency worker loops; they avoid changing timing.
- The API responds with `x-request-id`. Add it to a Watch expression or correlate it
  with API logs when tracing one request across layers.
