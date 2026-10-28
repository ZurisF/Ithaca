# Concurrent session-command windows

## Scope

These scenarios force two commands or results to compete for the same session transition. The winning behavior is determined by committed PostgreSQL facts and the documented session lock/conditional-write rules, not by request arrival order in the test client.

## Baseline fixture

- Tests use two independent database connections or HTTP clients.
- A synchronization barrier pauses each operation immediately before it attempts the session-locking transaction.
- Each ordering is run explicitly: A commits before B, then B commits before A where both orderings are meaningful.
- Final behavior is asserted after both requests and all deliberately delayed external results have finished.

## Scenarios

### FW-RACE-01 — Concurrent identical and conflicting answers

**Given** one published unanswered turn.

**When**, in separate runs:

1. two clients submit identical `turn_no + answer` values concurrently;
2. two clients submit different answers for the same turn concurrently.

**Then**:

- case 1 stores one answer and both callers converge on the same current state;
- case 2 stores the first committed answer and returns `409 answer_conflict` for the other;
- at most one answer-triggered Supervisor decision can publish;
- the answer timestamp is consistent with answer nullability.

### FW-RACE-02 — Double start creates one first question

**Given** a prepared session with a valid plan and no turn.

**When** two clients start the interview concurrently.

**Then**:

- the session enters `interviewing` once;
- exactly one Stage-entry trigger is fulfilled;
- the first published question has `turn_no = 1`;
- a second physical model request, if caused by a crash/retry window, cannot publish another first turn.

### FW-RACE-03 — Feedback update and terminal freeze serialize

**Given** an active session and feedback for a published turn.

**When** a feedback PUT and any terminal transition compete for the session row.

**Then**:

- feedback committed before the terminal transaction is the frozen value used by settlement;
- feedback attempting to commit after the terminal transaction returns the documented conflict;
- settlement never reads a value that later changes;
- no extra feedback field is copied into Graph State.

### FW-RACE-04 — Confirmed force exit competes with answer submission

**Given** an active unanswered turn and a user-confirmed force-exit command.

**When** force exit and answer submission are released in both commit orderings.

**Then**:

- if answer commits first, it remains in history, but force exit prevents any later question or post-processing artifact;
- if force exit commits first, answer submission fails and the turn remains unanswered;
- session ends `aborted/forced_exit` in both runs once force exit succeeds;
- late model output cannot publish.

### FW-RACE-05 — Confirmed force exit competes with finish-early

**Given** a session eligible for finish-early and a confirmed force-exit command.

**When** both terminal commands compete.

**Then**:

- the first committed terminal state is respected under the current 6.5 contract;
- force exit may replace a just-entered `post_processing` state only while no post-processing artifact or post-verification append has published;
- once post-processing output has published or completion committed, force exit does not retroactively delete it;
- no mixed `aborted` session with visible post-processing artifacts is produced.

### FW-RACE-06 — Retry double-click starts at most one new decision attempt

**Given** the session is visibly awaiting `decision_retry` and the trigger is still unpublished.

**When** two retry commands arrive concurrently.

**Then**:

- at most one new bounded decision execution starts;
- the other request returns current progress or `retry_not_available/operation_in_progress`;
- a retry that has already published a question cannot be restarted;
- turn number does not change merely because retry was requested.

### FW-RACE-07 — Question-bank settlement has one winner

**Given** a frozen session not yet represented in `bank.session_settlements`.

**When** two workers invoke settlement concurrently.

**Then**:

- one settlement marker commits;
- each affected question counter is incremented once by the aggregate for this session;
- the losing worker observes the existing settlement and performs no counter update;
- the behavior also holds when every turn has null `question_id`.

### FW-RACE-08 — Curation publication competes with grant revocation

**Given** a completed session with `curation_review = true` and an administrator-selected curation item ready to publish.

**When** the owner revokes the grant while the administrator confirms addition to the question bank.

**Then**:

- both operations lock/recheck the same session authorization fact;
- revocation committed first causes publication to fail without inserting a bank question;
- publication committed first may retain the already-generalized public question, but subsequent administrator reads cannot use the revoked private source session;
- no administrator role check alone can bypass the grant.

### FW-RACE-09 — The 100-turn cap handles both close and continue

**Given** turn 100 is answered.

**When**, in separate runs, Supervisor returns:

1. `complete` or `unresolved`;
2. `continue + question`.

**Then**:

- case 1 may close the current Stage normally without creating another turn;
- case 2 does not insert turn 101 and routes to the documented safety-stop behavior;
- report eligibility is derived from committed complete Stage results;
- no generated turn-101 text is exposed or stored as a business turn.

## Required observable assertions

- Concurrency tests must control transaction commit order, not merely send requests close together.
- Public views are read after both contenders complete.
- Direct database inspection is used for unique rows/counters only.
- Tests never assert acquisition order of internal locks; they assert outcomes under each forced commit order.
