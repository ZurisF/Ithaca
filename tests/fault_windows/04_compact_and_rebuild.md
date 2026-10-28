# Compact and checkpoint-rebuild windows

## Scope

These scenarios verify cumulative compaction at 20-turn boundaries and reconstruction after checkpoint loss. They assert the context observed by the next Supervisor call, not private summarizer implementation details.

## Baseline fixture

- Completed answered turns contain unique markers such as `Q-001/A-001` so omissions and duplicates are detectable.
- The fake compact model deterministically returns the ordered marker range it received plus a generation marker.
- The fake Supervisor records the final assembled prompt/context through the external provider seam.
- Full raw turns remain in PostgreSQL throughout the test.

## Context oracle

For a given `compacted_through_turn_no = N`, the next Supervisor context must contain:

- exactly one cumulative compact covering turns `1..N` in order;
- original recent turns beginning at `N+1`;
- the current answered trigger exactly once;
- no Stage-close pseudo-turn, correction card or feedback record;
- no `question_id`, retrieval score or post-processing result.

## Scenarios

### FW-CTX-01 — Boundary compaction is correct at turns 20, 40 and 60

Run the same scenario for `N = 20, 40, 60`.

**Given** the `N`th answer has been processed by its Supervisor decision.

**When** the next model context is prepared.

**Then**:

- one cumulative compact covers exactly through turn `N`;
- recent original history starts at `N+1`;
- no turn appears in both compact input coverage and recent raw context;
- no answered turn is missing;
- PostgreSQL still contains every original question and answer.

### FW-CTX-02 — Crash before compact checkpoint write retries without losing raw history

**Given** a full 20-turn batch is ready to compact.

**When** the compact model succeeds but the worker stops before the new compact/checkpoint is stored.

**Then**:

- PostgreSQL history is unchanged;
- recovery may regenerate the compact;
- the next Supervisor prompt satisfies the context oracle;
- repeated compact generation produces no business turn, Stage or snapshot effect;
- the provider call count may increase, but context coverage does not.

### FW-CTX-03 — Crash after compact checkpoint write reuses the stored compact

**Given** a compact and its covered-through marker have been written atomically to checkpoint.

**When** the worker stops before the next Graph step.

**Then**:

- recovery reuses the checkpointed compact;
- the same 20-turn batch is not appended as a second compact layer;
- recent raw turns start after the stored marker;
- the next Supervisor context satisfies the oracle.

### FW-CTX-04 — Compact failure retains old compact and uncompressed originals

**Given** an earlier cumulative compact exists and the next 20-turn batch is due.

**When** all allowed compact attempts fail.

**Then**:

- the previous compact and marker remain unchanged;
- raw turns after that marker remain available for retry/reconstruction;
- no history is silently dropped or truncated;
- the system exposes the documented recoverable failure rather than sending an unbounded or incomplete context;
- explicit recovery does not create turns or Stage results.

### FW-CTX-05 — Redis loss after a Stage close reconstructs the next Stage trigger

**Given** a Stage result is committed and the next Stage has no first question.

**When** all session checkpoint keys are deleted.

**Then**:

- recovery derives the first unclosed Stage from the plan and Stage results;
- the next retrieval query uses the next Stage goal;
- the prior Stage is not closed again;
- no placeholder turn is created.

### FW-CTX-06 — Redis loss after an answer reconstructs one unpublished decision

**Given** the latest turn has a persisted answer and no newer turn or Stage result represents its decision.

**When** checkpoint state is lost.

**Then**:

- recovery identifies an answered-turn trigger for that turn;
- one decision may be regenerated and conditionally published;
- repeated answer submission is not required and does not initiate recovery itself;
- at most one next turn or Stage result appears.

### FW-CTX-07 — Redis loss after committed snapshot correction uses the database snapshot

**Given** a correction append has committed and the associated decision has not yet published.

**When** checkpoint state is lost.

**Then**:

- recovery loads the appended snapshot from PostgreSQL;
- the append is not repeated and the user is not asked to confirm the already-committed text again;
- any regenerated decision sees the current snapshot;
- future prompts contain the sanitized append exactly once.

### FW-CTX-08 — Rebuild from zero reproduces cumulative 20-turn boundaries

**Given** at least 45 answered turns and no checkpoint data.

**When** compact state is rebuilt from PostgreSQL.

**Then**:

- rebuild processes deterministic batches `1..20` and `21..40`;
- the final cumulative compact covers through 40;
- turns 41 onward remain recent raw context;
- rebuilding again yields equivalent coverage and ordering;
- no business data is written by the rebuild.

## Required observable assertions

- Assert compact coverage using deterministic markers captured at the external model seam.
- Do not snapshot arbitrary prompt formatting; assert ordered inclusion/exclusion of semantic sections and markers.
- Use direct Redis operations only to place the fault or verify terminal cleanup, not to couple tests to internal Graph serialization.
