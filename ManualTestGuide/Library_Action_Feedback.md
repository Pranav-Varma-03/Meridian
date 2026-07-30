# Library action feedback

Use this checklist after starting the web app with `make dev-web` and signing in with a test
account. It verifies the frontend-only action feedback change; it does not require a new API
contract or Swagger procedure.

## Prerequisites

- Start the API, workers, and web app.
- Sign in to Meridian.
- Have at least one ready document and one collection available. Use disposable test data for
  deletion checks.

## Documents

1. Open **Documents** and select a supported file.
   - The drop area immediately changes to `Uploading file…` and cannot accept a second file.
   - After the upload endpoint accepts it, the message says that processing continues in the
     background. No made-up percentage is shown.
   - The new row then follows the server job status: `Queued`, `Processing`, `Ready`, or `Failed`.
2. With a user that has `documents:reingest`, choose a re-ingestion reason from a ready row.
   - The row control changes to `Queueing…` and no re-ingestion control can submit a second
     request while acceptance is pending.
   - After acceptance, the notice says the current ready generation remains available until the
     replacement succeeds. Confirm the row transitions using the server-provided job status.
3. Select **Delete** for a disposable document, then confirm.
   - The dialog stays visible with `Deleting…`; both action buttons are disabled.
   - After a successful response it closes, the success message says cleanup is queued, and the
     document list refreshes.
   - To exercise failure recovery, temporarily stop the API before confirming: the dialog remains
     open and the user can retry after the request settles.

## Collections

1. Enter a name and optional description, then select **Create**.
   - The button becomes `Creating…` and rejects a second submission.
   - On success, the form clears and the list refreshes. On failure, both entered values remain.
2. Select **Rename**, change the name, and select **Save name**.
   - The dialog displays `Saving…` while the request is in flight and closes only after success.
   - Force a validation/conflict error to verify the dialog and entered name remain editable.
3. Select **Delete** for a disposable collection and confirm.
   - The dialog displays `Deleting…` until the request finishes and only closes on success.
   - Confirm the list refreshes and the message states that documents were left unfiled.
4. Move between pages of documents and collections with more than ten records.
   - Existing rows remain visible while the next page is loading and pagination indicates its
     pending request. No full-page loading panel replaces the library.

## Completion checklist

- [ ] Upload, re-ingestion, and deletion states are immediate and server-truthful.
- [ ] Mutation controls do not submit duplicate requests.
- [ ] Failed create/rename/delete actions preserve a retryable UI state.
- [ ] Server job labels transition through queued, processing, ready, and failed as returned.
- [ ] Pagination keeps existing data visible during refresh.
