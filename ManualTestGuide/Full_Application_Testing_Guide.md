# Meridian full application testing guide

This guide is the practical acceptance test for the currently implemented Meridian application. It covers normal local development and controlled staging/production-safe verification. Use **disposable files and a test user**. Do not use customer documents, production credentials, or a real production user for destructive tests.

Swagger is the source of truth for API payloads: `http://localhost:8000/docs`.

Related focused guides: [grounded retrieval](Grounded_Retrieval_Swagger_Guide.md), [API contract reference](API_Contract_Reference.md), [Grafana observability](GrafanaObservability.md), [chat streaming](Streaming_Chat_Workspace.md), and [document-library UI](Document_Library_UI.md).

---

## 1. Test data and safety rules

Prepare two small disposable TXT files. Exact tokens distinguish a retrieval failure from an answer-quality issue.

`travel-policy.txt`:

```text
Travel policy TRV-104: employees may claim up to USD 75 for dinner while travelling overnight. Receipts are required for every dinner claim.
```

`benefits-policy.txt`:

```text
Benefits policy BEN-202: employees receive 20 days of annual leave each year. Travel dinner claims are not covered by this policy.
```

For a conflicting-evidence test, also create:

```text
Travel exception TRV-104: contractors may claim up to USD 50 for dinner while travelling overnight.
```

Keep the resulting document IDs, job IDs, collection IDs, conversation IDs, request IDs, and timestamps in a test record. They are the keys for comparing the API, worker logs, Grafana, and provider state.

- Delete only disposable documents created for this guide.
- A queued/processing document is **not** ready to answer questions. Wait for its job to reach `ready`.
- Chat is source-only. A grounded insufficiency answer with empty sources is correct if no lifecycle-valid evidence supports the question.

---

## 2. Local-development readiness

### 2.1 Start the complete topology

Run these commands from `Meridian/` in separate terminals:

```bash
make db-migrate
make dev-api
make dev-worker
make dev-web
```

| Test | Expected behavior | Observe / investigate if not |
|---|---|---|
| Database schema and app startup | API is at `http://localhost:8000/docs`; web is at `http://localhost:3000`. | A missing database column means migrations were not applied to the same `DATABASE_URL`. |
| Background processing | `make dev-worker` reports `ingestion` and `purge`, and both remain running. | A Redis timeout/exit means check `REDIS_URL` and connectivity before testing uploads. |
| Dependency readiness | `GET /health/ready` returns `200` only if Postgres, Redis, Pinecone, and generation configuration are healthy. | A `503` is a readiness failure; inspect the named failing dependency before testing RAG behavior. |
| Web development server | The browser loads without a stale webpack module error. | Stop web, remove only `apps/web/.next`, then restart. Do not delete application data. |

### 2.2 Health endpoints

Run in Swagger without authorization:

| Endpoint | Expected | Important observation |
|---|---|---|
| `GET /health/live` | `200` | Process liveness only; it deliberately does not prove dependencies work. |
| `GET /health/ready` | `200` or clear `503` | Use this as the traffic/readiness gate. |
| `GET /health` | `200`, `healthy` or `degraded` | Backward-compatible monitoring status. |

### 2.3 Authentication and permissions

Sign in at `http://localhost:3000`. In Swagger, click **Authorize** and paste the raw Auth0 **API access token**, not an ID token. Its audience must equal `AUTH0_AUDIENCE`.

| Test | Steps | Expected / observation |
|---|---|---|
| Protected API authentication | Run `POST /api/v1/users/me`. | `200` with a Meridian user and `X-Request-ID`. |
| Missing token | Remove Authorization, call `GET /api/v1/documents`. | `401` common error envelope with no sensitive details. |
| Permission claim | In development run `GET /api/v1/auth/token-claims`. | `200` includes allowlisted `iss`, `aud`, `permissions`; only the privileged user has `documents:reingest`. |
| Re-ingestion authorization | Call `POST /api/v1/ingest` without the permission. | `403`; no job/generation is created. |

---

## 3. Collections and document-library tests

### 3.1 Collection CRUD

Create a collection with `POST /api/v1/collections`:

```json
{
  "name": "Local retrieval test",
  "description": "Disposable collection for acceptance testing"
}
```

| Test | Expected behavior | What to look for |
|---|---|---|
| Create | `201` and collection ID. | Signed-in Collections UI displays it after loading. |
| List | `GET /api/v1/collections?limit=10&offset=0` returns `{collections, total}`. | Owner-scoped list; web shows at most 10 records per page and horizontal pagination. |
| Rename | `PATCH /api/v1/collections/{id}` returns `200`. | UI typing retains focus; Save visibly succeeds, closes dialog, and shows the new name. |
| Duplicate name | Create/rename to an owned duplicate. | `409`, with no duplicate record. |
| Delete | `DELETE /api/v1/collections/{id}` returns `200`. | It disappears from the list. |

**Semantic check:** deleting a collection never deletes its documents. Assign a disposable document, delete the collection, then list documents. It remains active with no `collection_id` and is discoverable through chat scope `all`.

### 3.2 Document-library UI

Open **Documents** from the permanent sidebar.

**Test:** list usability and asynchronous state feedback are clear rather than silently failing.

**Expected:** sidebar remains visible on Documents and Collections; its list scrolls while the profile remains reachable. Document and collection lists show 10 records maximum per page. Upload has immediate queued/processing feedback and eventual ready/failed feedback; it does not treat `202` as indexed.

**Observe:** Network responses and document/job IDs. For a UI `500`, retain its `X-Request-ID` and inspect the matching API log rather than blindly retrying.

---

## 4. Upload, ingestion, re-ingestion, and deletion

### 4.1 Upload one document

Use Swagger `POST /api/v1/documents/upload` with `travel-policy.txt`; optionally provide a user-owned `collection_id` query parameter.

**Test:** asynchronous acceptance and durable ingestion.

**Expected API result:** `202` containing `document_id`, `job_id`, `status: "queued"`, and `deduplicated: false`.

**Observe in sequence:**

1. Ingestion worker dequeues and processes the job.
2. `GET /api/v1/ingest/{job_id}` moves `queued` → `processing` → `ready`.
3. `GET /api/v1/documents/{document_id}` reports ready and `latest_job.status: ready`, completed timestamp, and generation.
4. Web Documents UI reaches the equivalent state.

**Pass condition:** `ready` means parsing, structured child/parent chunking, exact Postgres evidence, vector upsert, and generation activation completed. Pinecone alone does not prove success; the database job/generation is Meridian's lifecycle authority.

### 4.2 Deduplication and invalid upload behavior

| Test | Action | Expected / what it proves |
|---|---|---|
| Identical upload | Upload the same bytes as the same user. | `200`, `deduplicated: true`, `reused_existing_job: true`; no duplicate document/vectors. |
| Unsupported file | Upload PNG or executable content type. | `415`; no document/job. |
| Large file | Upload greater than 10 MiB. | `413`; no document/job. |
| Foreign collection | Use another user's collection ID. | `404`; no job. |
| Upload limit | Exceed configured upload limit with disposable user. | `429 RATE_LIMITED`, `Retry-After`, no extra job. |
| Redis limit outage | Non-production only: stop Redis while limits enabled. | `503 RATE_LIMIT_DEPENDENCY_UNAVAILABLE`; fail closed, never queue work. |

### 4.3 Explicit re-ingestion

With an admin token containing `documents:reingest`, call `POST /api/v1/ingest`:

```json
{
  "document_id": "<travel-document-id>",
  "reason": "chunking_change"
}
```

Only `manual_repair`, `model_migration`, and `chunking_change` are valid reasons.

**Test:** safe replacement generation.

**Expected:** `202` with new/reused job. The old active generation remains answerable while work is processing. After readiness, new answers cite only the new active generation; purge removes stale vectors later.

**Observe:** record old/new generation. Query while processing and after ready: the first can cite old evidence, the latter must cite new evidence. Historic citations are immutable snapshots. Unsupported reason returns `422`; absent permission returns `403`; a duplicate active request reuses the active job.

### 4.4 Deletion and purge isolation

Upload and wait for both travel and benefits documents. Delete only travel with `DELETE /api/v1/documents/{id}`.

**Expected:** immediate message that cleanup is queued; deleted document immediately disappears from document reads and retrieval. Purge worker later removes its raw file, lexical state, and vectors.

**Critical observation:** while travel is purging, ask about `BEN-202`. Benefits must remain retrievable throughout. Failure indicates unsafe ownership/generation filtering and is a release blocker.

---

## 5. Grounded chat and retrieval

### 5.1 All-documents chat

Send `POST /api/v1/chat` in Swagger:

```json
{
  "query": "What is the overnight dinner limit in TRV-104?",
  "retrieval_scope": { "mode": "all" }
}
```

**Test:** authenticated POST-SSE, evidence retrieval, source-only generation, and conversation creation.

**Expected stream:** zero or more `text` events, exactly one `sources`, then exactly one `done`. The answer says USD 75/receipts only when sources support it.

**Observe:**

- `done` includes `conversation_id` and the saved scope.
- Sources identify active generation, document, filename, and page/section/excerpt when available. Exact evidence is read from Postgres, not Pinecone metadata.
- UI renders Markdown, not raw `**` or list markers; assistant response has Copy and Sources controls.
- Sources opens a right-side pane of collapsible source cards. Card expansion exposes source metadata/excerpt. Escape or outside click closes it without changing conversation data.

### 5.2 Collection scope and scope history

Place travel and benefits documents in separate collections, then send:

```json
{
  "query": "What is the travel dinner limit?",
  "retrieval_scope": {
    "mode": "collections",
    "collection_ids": ["<travel-collection-id>"]
  }
}
```

**Expected:** sources are limited to the selected owned collection. `all` requires no IDs; `collections` requires unique, owned IDs. Invalid shape/foreign ID returns documented `422`/`404`, never silently broadening to all documents.

Continue the same conversation once with only `conversation_id`/`query`, then once with a replacement `retrieval_scope`. `GET /api/v1/chat/conversations/{id}` must show current scope and scope-event history. Older messages retain the scope in effect when sent.

**UI observation:** scope button beside composer opens near the button, shows selected collection chips, allows add/remove, and reflects saved scope after the next message. No large retrieval scope box occupies conversation space.

### 5.3 Evidence-safety tests

| Test | Query / setup | Expected behavior |
|---|---|---|
| No evidence | Ask “What is the CEO's birthday?” | Grounded insufficiency response, empty sources, no invented web knowledge. |
| Exact identifier | Ask “What does TRV-104 say about dinner?” | Finds active travel evidence after ready. |
| Conflict | Upload travel exception and ask unscope-limited entitlement question. | Explains conflict with citations; does not choose unsupported resolution. |
| Deleted evidence | Delete travel, then repeat TRV-104 question. | No travel answer/citation; benefits still retrieves. |

### 5.4 Conversation UI behavior

Test in the browser:

- `/new` is the empty chat landing page; selecting a recent chat routes to `/chat/<conversation-id>`.
- Sidebar navigation has usable New chat, Chat, Documents, Collections, Meridian, and profile controls. Profile closes on outside click/Escape and offers email, permissions, logout.
- Message area scrolls independently; composer stays visible while reading long chat. Jump-to-latest is a clear round down-arrow.
- Composer prevents duplicate sends; upward-arrow send control is disabled when invalid/sending; streaming/cancel/error feedback is visible.
- At desktop, tablet, and phone widths, sidebar/dialog/source-pane/focus order work without horizontal page overflow.

---

## 6. API resilience and security

Use a disposable local/staging account only.

| Test | Action | Expected / observation |
|---|---|---|
| Chat rate limit | Exceed `CHAT_RATE_LIMIT_REQUESTS` within `CHAT_RATE_LIMIT_WINDOW_SECONDS`. | `429 RATE_LIMITED` with `Retry-After` before retrieval/LLM generation. |
| Redis outage | Stop Redis with limits enabled; chat/upload. | `503 RATE_LIMIT_DEPENDENCY_UNAVAILABLE`; service does not fail open. Restore Redis. |
| Invalid scope | `all` with IDs; `collections` empty/duplicates. | `422`; no persisted message/conversation side effect. |
| Owner isolation | Read another test user's document/job/collection/conversation IDs. | `404`/documented validation, never other-user data. |
| SSE failure | Non-production: force generation failure after stream begins. | `error`, then `done`; partial assistant response not stored as completed. |
| Error safety | Trigger 401/403/404/422/429. | Common safe envelope; no stack trace, JWT, document content, or provider secret. |

---

## 7. Local Grafana and observability

When Alloy/Grafana configuration is enabled, also use [GrafanaObservability.md](GrafanaObservability.md).

Generate traffic: readiness check, document/collection list, disposable upload, grounded chat, and disposable re-ingestion/deletion.

**Expected:**

- API metric route labels are templates such as `/api/v1/documents`, never UUID/query/body/filename/token.
- RAG metrics show retrieval/evidence activity. Bounded retrieval observations distinguish lifecycle exclusions, expansion additions, and reranking candidates without identifiers/content.
- Worker heartbeat, queue-age, ingestion/purge results are visible.
- Logs/traces correlate safely and contain no prompts, message text, citations, JWTs, secrets, or request IDs.

**Interpret correctly:** browser navigation to `/documents` may hit the Next.js BFF/server layer. FastAPI metric route `/api/v1/documents` appears only when FastAPI receives the proxy request. Compare DevTools Network, BFF logs, and FastAPI logs—not frontend route names alone.

---

## 8. Staging / production-safe release validation

These are release gates in a dedicated staging tenant/namespace with test users, isolated Pinecone data, test Auth0 roles, an approved rollback window, and a named operator. Never use them as a reason to experiment with customer data.

### 8.1 Pre-flight

- [ ] Secrets come from the approved secret manager; none are in docs/logs/source.
- [ ] Database migration revision matches release.
- [ ] API, web, workers, Redis, Postgres, Pinecone, OpenRouter, Alloy are ready.
- [ ] Grafana dashboard datasource and alert owner are set.
- [ ] Normal and `documents:reingest` admin test users exist.
- [ ] Baseline dashboard screenshots and rollback owner are recorded.

### 8.2 Structured retrieval evaluation

Re-ingest the evaluation corpus in the isolated tenant. Run the agreed questions against structured current implementation and, where available, 512-token baseline. Record grounded-answer correctness, citation correctness, insufficiency precision, latency, failed jobs, and retrieval metrics.

**Pass condition:** candidate is not worse on grounded correctness or unsupported-answer prevention, without unacceptable latency/error regression. More sources alone is not a quality improvement.

### 8.3 Hybrid and reranker rollout

Set `RETRIEVAL_MODE=hybrid_shadow` only in staging. User-visible answers remain dense-compatible while lexical/fusion behavior is measured. PostgreSQL FTS is lexical retrieval, **not BM25**. Test lexical failure according to `LEXICAL_DEGRADATION_MODE` (`dense_only` or safe failure).

For reranking, use shadow mode first. Compare candidates, selected-source correctness, evidence coverage, latency, and failures before activation. Wrong-owner, deleted, wrong-generation, or out-of-scope evidence is an immediate no-go even if answer prose looks good.

### 8.4 Two-document cleanup canary

1. Upload documents A and B with unique facts.
2. Re-ingest A while continuously querying both facts.
3. Verify A activates only after readiness.
4. Delete A and verify immediate API/chat exclusion.
5. Keep querying B until A purge reaches terminal successful, retryable, or terminal-failed visible state.

**Pass condition:** B remains retrievable throughout; no cross-document vector/lexical/file cleanup. Silent data loss is a release blocker.

### 8.5 Grafana and controlled collector failure

Open **Meridian operational overview**. Verify API RED metrics, worker/queue/RAG panels, and safe correlated logs/traces. In non-production only, stop Alloy briefly: API remains functional while telemetry degradation is visible; restore Alloy immediately. Never deliberately break dependencies in production to test a dashboard.

### 8.6 Release decision and rollback

Record version, migration revision, configuration versions, tenant, evaluation results, latency/error/limit results, evidence-safety result, dashboard link/screenshots, alert owner, and decision (activate/hold/rollback).

Rollback configuration/retrieval mode first; do **not** delete generations/vectors as a first response. Verify prior active generation remains queryable and no evidence crosses user/scope/lifecycle boundaries.

---

## 9. Final acceptance record

### Local

- [ ] Migrations and all app processes started cleanly.
- [ ] Health, auth, collection CRUD/pagination, upload, dedupe, and ready job checks passed.
- [ ] Grounded, insufficient, conflicting, scoped, re-ingested, and deleted evidence behaved correctly.
- [ ] Two-document purge isolation passed.
- [ ] Chat/sidebar/source-pane/long-history/mobile UX checks passed.
- [ ] Relevant error, rate-limit, and Redis-degradation paths failed safely.

### Staging / release

- [ ] Evaluation and shadow/canary results are attached to release record.
- [ ] Two-document cleanup isolation passed in staging.
- [ ] Grafana metrics/logs/traces and controlled collector outage passed.
- [ ] Rollback was validated without destructive changes.
- [ ] Named owner approved activation or documented hold reason.
