# Interrupt and correction-confirmation windows

## Scope

These scenarios cover the snapshot-correction card produced from a Supervisor decision. The card is an execution interrupt, not a turn, and resolving it must reuse the already-generated decision without another Supervisor call.

## Baseline fixture

- A session is `interviewing` with an answered current turn.
- Supervisor returns a valid decision containing `correct_project_fact`, an optional interviewer message and either a next question or Stage-closing action.
- Candidate correction text is filtered before it enters checkpoint state.
- The current HTTP view can expose `snapshot_confirmation_required` without exposing internal candidate IDs beyond an opaque public locator.

## Scenarios

### FW-INT-01 — Restart while waiting preserves the same confirmation

**Given** the filtered correction candidate and pending Supervisor decision have been checkpointed and the Graph is awaiting confirmation.

**When** the worker process restarts before the user acts.

**Then**:

- the current view still requires confirmation for the same final text;
- no new Supervisor call occurs;
- no turn or Stage result is published early;
- answer submission returns `409 operation_in_progress` while confirmation is pending;
- the snapshot remains unchanged.

### FW-INT-02 — Edited text that is redacted requires another explicit confirmation

**Given** the user edits the candidate before confirming.

**When** the edited text contains a test credential and safety processing replaces it.

**Then**:

- the first resolution request does not append anything;
- the response exposes the final sanitized text and states that another confirmation is required;
- submitting the old unfiltered edit again cannot bypass the second confirmation;
- only the exact sanitized text shown to the user can be appended on the subsequent confirmation;
- findings never include the secret value.

### FW-INT-03 — Confirm applies one append and the original decision

**Given** a pending correction and Supervisor decision are awaiting confirmation.

**When** the user confirms the displayed text and the append commits.

**Then**:

- one `## 用户意见` append is visible in the current snapshot;
- State refreshes from the database snapshot before the decision is published;
- the original interviewer message/action/question is applied once;
- Supervisor physical-call count does not increase because of confirmation;
- the confirmation card does not appear in dialogue history and does not create a turn.

### FW-INT-04 — Skip changes no snapshot bytes and still applies the decision once

**Given** the same pending correction state.

**When** the user chooses `do_not_write` and the process later replays the checkpoint.

**Then**:

- the snapshot is byte-for-byte unchanged;
- the pending append is cleared;
- the already-generated decision is applied once;
- no second Supervisor call occurs;
- replay does not show the same card again after the decision has been published.

### FW-INT-05 — Append rollback keeps the confirmation unresolved

**Given** the user confirms safe correction text.

**When** the snapshot append transaction rolls back.

**Then**:

- the HTTP view reports a retryable confirmation/write failure;
- neither operation row nor snapshot append exists;
- the next question or Stage result remains unpublished;
- retrying the same confirmed text may commit once without calling Supervisor again.

### FW-INT-06 — Append commit with unknown response remains blocked until reconciled

**Given** the confirmed append transaction may have committed.

**When** its acknowledgement is lost and PostgreSQL is temporarily unavailable for reconciliation.

**Then**:

- the view reports an unknown write outcome rather than success or definite failure;
- no blind second append is attempted;
- no dependent question or Stage result is displayed;
- once PostgreSQL is available, the existing operation row determines whether to refresh State or retry the transaction.

### FW-INT-07 — Total checkpoint loss may discard only the unconfirmed candidate

**Given** the Graph is awaiting confirmation and no append has committed.

**When** all Redis checkpoint state for the session is lost.

**Then**:

- authoritative snapshot, answer, plan and Stage results remain intact;
- the unconfirmed candidate may disappear as permitted by the current contract;
- recovery may rerun the still-unpublished decision within the allowed retry/recovery behavior;
- no correction is silently accepted;
- if a new card is generated, the user must review it as a new pending candidate.

### FW-INT-08 — Force exit while confirmation is pending publishes no decision

**Given** a correction card is awaiting user action.

**When** the user confirms force exit through the terminal command.

**Then**:

- the session becomes `aborted` and feedback freezes;
- pending correction and decision are never appended or published;
- late confirmation requests return a state conflict;
- late model or checkpoint activity cannot create a new turn or post-processing artifact.

## Required observable assertions

- Snapshot bytes before and after skip/failed confirmation are compared directly.
- Model-call count is asserted at the controlled provider seam.
- Public history proves that the card is not dialogue content.
- Direct Redis inspection is used only to create total checkpoint loss, not to assert Graph node order.
