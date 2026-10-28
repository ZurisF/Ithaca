# Terminal cleanup, authorization and content-security windows

## Scope

These scenarios verify that filesystem authorization, terminal transitions, deletion, trace and error handling cannot reintroduce private data or revive a completed/deleted workflow.

## Baseline fixture

- `test_project` contains unique canaries for ordinary source content, a credential and an outside-root file.
- Application and Local Runtime use their production HTTP authentication mechanism over loopback.
- The test can delay model responses, checkpoint writes, trace export and Local Runtime cleanup.
- `content_leak_oracle` scans all allowed stores after the delayed work finishes.

## Scenarios

### FW-SEC-01 — Symlink replacement after inventory cannot escape the authorized root

**Given** inventory accepted a symlink or path while it resolved inside the authorized project root.

**When** the test replaces it so that the path resolves to an outside-root canary immediately before the file-open operation.

**Then**:

- Local Runtime canonicalizes and verifies the target again at open time;
- the read/tool request fails with a controlled error;
- the outside-root canary does not enter model input, snapshot, result, checkpoint, log or trace;
- other valid authorized reads remain usable.

### FW-SEC-02 — Expired or restarted source authorization degrades safely

**Given** a session stores an opaque `source_handle`.

**When** Local Runtime restarts or the handle expires.

**Then**:

- another session cannot reuse the handle;
- Application Runtime never attempts to interpret it as a path;
- Observer requires renewed authorization instead of silently reading the directory;
- project answers follow the documented snapshot-only fallback;
- loss of directory access does not delete or mutate the session snapshot.

### FW-SEC-03 — Confirmed force exit rejects all late generative effects

**Given** a Supervisor or post-processing model call is blocked in flight.

**When** force exit commits and the old call later returns.

**Then**:

- no new turn, Stage result, snapshot append, post-result or report is published;
- historical committed turns remain visible;
- checkpoint is removed according to terminal cleanup;
- trace may record cancellation/completion metadata but not returned text;
- question-bank settlement may still run only under its deterministic frozen-data contract.

### FW-SEC-04 — Session deletion rejects late business and checkpoint writes

**Given** deletion has acquired the session execution lock and an old worker/checkpointer write is delayed.

**When** PostgreSQL session deletion commits and delayed work is released.

**Then**:

- no PostgreSQL business row is recreated;
- the checkpointer adapter's terminal/delete guard rejects a late checkpoint write, or cleanup deterministically removes it before deletion completes;
- no trace row linked to the deleted session is recreated;
- the public session resource remains not found/invisible;
- source files and user-exported local files are untouched.

### FW-SEC-05 — Redis cleanup failure does not destroy the only cleanup locator

**Given** a session deletion request and an unavailable Redis instance.

**When** initial checkpoint cleanup fails before PostgreSQL deletion.

**Then**:

- the command returns a retryable cleanup failure under the current deletion contract;
- PostgreSQL still contains the session needed to retry cleanup;
- no content becomes visible to a different user;
- retry after Redis recovery completes deletion once.

### FW-SEC-06 — Local authorization release is best effort after business deletion

**Given** PostgreSQL deletion and Redis cleanup have succeeded.

**When** Local Runtime is unavailable for `source_handle` release.

**Then**:

- business deletion is not rolled back;
- Application Runtime no longer retains or returns the handle;
- the Local Runtime authorization expires through its bounded TTL;
- the real path never appears in Application Runtime data or errors.

### FW-SEC-07 — Administrator access requires current session grant

**Given** private completed sessions owned by different users, only one of which has `curation_review = true`.

**When** an Administrator uses list, direct item, curation creation and publication interfaces against both sessions.

**Then**:

- only the currently granted session is visible and selectable;
- direct identifiers do not bypass the grant;
- revocation immediately prevents future source-material reads;
- public question-bank records do not expose private answer, feedback reason or source snapshot;
- error differences do not reveal the existence of an inaccessible session.

### FW-SEC-08 — Content canaries remain within their allowed destinations

**Given** unique canaries are placed in source, imported Markdown, answer, model output and credential fixtures.

**When** the system exercises success, schema error, provider error, checkpoint recovery and export paths.

**Then**:

- allowed owner-visible business content appears only where the product contract permits;
- credential values are replaced before model input, snapshot, checkpoint, derived artifacts and logs;
- trace contains only the allowlisted metadata schema;
- HTTP errors contain controlled codes and no SDK/provider body;
- raw invalid model output is not persisted as Graph State;
- prompt-injection text remains data and cannot alter tools, actions or output schemas.

### FW-SEC-09 — Model and Runtime authentication data never enters content stores

**Given** service bearer tokens, provider credentials and user session cookies contain unique canaries.

**When** normal calls, authentication failures and retries occur.

**Then**:

- credentials never enter business rows, checkpoint, model prompts, SSE payloads or exported files;
- logs and trace do not record Authorization/Cookie header values;
- a `source_handle` alone cannot authorize Local Runtime access without the bound session and service identity;
- caller-supplied `user_id` or role cannot replace the server-derived principal.

## Required observable assertions

- Delayed work must be released before running the final leak scan.
- Security tests inspect captured logs and stores with exact canary search, not broad assumptions about serializer behavior.
- Authorization tests exercise list and direct-object paths.
- Filesystem tests use real filesystem operations in a temporary authorized root; a pure path-string mock is insufficient for the symlink race.
