# Commit, checkpoint and response-loss windows

## Scope

These scenarios exercise the gap between PostgreSQL business commits, Redis checkpoint updates, HTTP acknowledgements and SSE notifications. PostgreSQL remains authoritative; Redis and SSE must be recoverable projections of current execution.

## Baseline fixture

- Real PostgreSQL and Redis instances are running.
- The production checkpointer adapter is used through `faultable_checkpointer`.
- Workers can be terminated immediately before or after a named write.
- HTTP responses and SSE delivery can be discarded without rolling back the database.

## Scenarios

### FW-COM-01 — Snapshot receipt and append roll back together

**Given** a valid, sanitized snapshot append command with a new operation key.

**When** the transaction fails after attempting to insert `snapshot_append_operations` but before updating the snapshot row.

**Then**:

- neither the operation row nor appended text is committed;
- the current snapshot returned through HTTP is byte-for-byte unchanged;
- retrying the same operation key and text can commit exactly one append;
- retrying the key with different text is rejected only after a successful first commit, not after the rolled-back attempt.

Direct database inspection is required here because atomic rollback is the behavior under test.

### FW-COM-02 — Snapshot commit followed by checkpoint failure appends once

**Given** a correction or post-verification append is ready to persist.

**When** PostgreSQL commits the append and its operation row, but the worker terminates before refreshing checkpoint state.

**Then**:

- the owner-visible snapshot contains one append;
- resume reads the current snapshot from PostgreSQL and refreshes State;
- the same operation key does not append a second copy;
- the Graph cannot publish a dependent next question or evaluation using a stale pre-append snapshot;
- no new general-purpose receipt is required beyond the existing snapshot append operation.

### FW-COM-03 — Decision commit followed by checkpoint failure does not call Supervisor again

**Given** a valid Supervisor decision has been validated for the current trigger.

**When** the conditional publication transaction commits a turn or Stage result and the worker stops before the next checkpoint write.

**Then**:

- recovery reconstructs the trigger from PostgreSQL facts;
- the committed turn or Stage result is returned through the public view;
- Supervisor is not called again for that already-published trigger;
- turn number and Stage result cardinality remain one;
- if the result closed a Stage, the next model call is a new Stage-entry call using the next Stage goal.

### FW-COM-04 — Stage close and next Stage first question are separate commits

**Given** the current Stage is ready to close and another Stage remains.

**When** the close transaction commits and the process stops before retrieving candidates for the next Stage.

**Then**:

- the original Stage has one immutable result;
- no empty or placeholder turn exists for the next Stage;
- recovery starts a Stage-entry trigger for the next index;
- that trigger uses the new Stage goal for retrieval and permits only `continue + question`;
- closing the previous Stage is not replayed.

### FW-COM-05 — Post-result publication and task success are atomic

**Given** a project answer, ideal answer, evaluation or report result has passed validation.

**When** the worker fails between writing the artifact and marking its `post_tasks` row successful, in both possible internal orderings.

**Then**:

- no committed state exposes `succeeded` without its artifact;
- a committed artifact is either accompanied by task success in the same transaction or remains unpublished;
- recovery reuses a committed artifact instead of calling the model again;
- one task cannot null or overwrite a result column owned by another task.

### FW-COM-06 — Settlement rolls back or commits as one business effect

**Given** feedback is frozen and turns contain known non-null `question_id` values.

**When**, in separate runs:

1. the transaction fails after some counter updates but before commit;
2. the transaction commits but the caller loses the acknowledgement.

**Then**:

- case 1 leaves both counters and `bank.session_settlements` unchanged;
- retry after case 1 applies the complete aggregate once;
- case 2 leaves the complete aggregate and settlement marker committed;
- retry after case 2 observes the marker and does not increment again;
- turns with null `question_id` never affect bank counters.

### FW-COM-07 — Lost SSE after question publication is recovered by GET

**Given** a question turn commits successfully.

**When** all SSE notifications associated with that publication are discarded and the client reconnects.

**Then**:

- `GET` current interview/session view returns the committed question and its turn number;
- subscribing again does not create or republish a turn;
- an old notification, if delivered later, cannot reopen an answered or terminal view;
- no persisted notification log is required for correctness.

### FW-COM-08 — HTTP acknowledgement loss reuses the committed answer

**Given** an answer submission is accepted and committed.

**When** the HTTP connection closes before the client receives the response and it resubmits the same `turn_no + answer`.

**Then**:

- the owner-visible history contains one answer;
- the repeated request returns current processing or published state;
- it does not reset retry budget or start another model call;
- a different answer for the same turn returns `409 answer_conflict`.

## Required observable assertions

- For every case, record PostgreSQL commit status, Redis checkpoint status and provider physical calls separately.
- SSE absence is never treated as evidence that the business commit failed.
- Direct database assertions are limited to transaction atomicity, uniqueness and aggregate counts.
