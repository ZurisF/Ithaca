# External-call fault windows

## Scope

These scenarios exercise the seams to the model provider, Retrieval Service and Local Project Runtime. They distinguish physical calls from adopted business effects and require late or duplicated responses to be harmless.

## Baseline fixture

- A session is `interviewing` with a persisted plan and current Stage.
- Unless stated otherwise, one current turn has a persisted answer and no subsequent decision has been published.
- `controlled_model_provider` returns schema-valid deterministic outputs.
- `controlled_retrieval` returns at most three known candidates.
- A public session view and captured external-provider call log are available.

## Fault positions

Run applicable scenarios at:

1. before the external request is sent;
2. after the request is sent but before any response is received;
3. after a response is received and validated but before its business effect is published;
4. after a competing retry has published a result but before the older request returns.

## Scenarios

### FW-EXT-01 — Retrieval failure degrades to an empty candidate list

**Given** an answered turn or Stage-entry trigger is ready for the next Supervisor decision.

**When** Retrieval Service times out or returns a retryable dependency failure through its allowed attempt budget.

**Then**:

- Supervisor is still invoked with zero candidate questions;
- no ideal answer or question-bank answer is read as a fallback;
- a valid Supervisor decision can publish exactly one question or close the Stage;
- retrieval failure alone does not change session status or create a turn;
- the user-facing error stream does not expose retrieval request bodies or scores.

### FW-EXT-02 — A malformed Supervisor result is repaired within one logical budget

**Given** a Supervisor decision is due.

**When** the provider first returns invalid structured output and then returns a valid decision in the permitted repair attempt.

**Then**:

- the provider records two physical requests;
- only the valid decision is eligible for publication;
- exactly one turn or Stage result is created;
- no third automatic request occurs;
- the invalid body is absent from PostgreSQL business data, Redis checkpoint content, trace and HTTP errors.

### FW-EXT-03 — Sent request with unknown response cannot duplicate a business decision

**Given** a decision is due and no decision has been published.

**When** the worker sends the model request and terminates before it knows whether a response was delivered.

**Then**:

- recovery may issue another physical model request within the current retry policy;
- at most one validated result can publish a turn or Stage result;
- a repeated answer submission does not itself start another model attempt;
- the public view eventually shows either one published result or the explicit `decision_retry` failure state;
- there is no requirement that the external provider executed only once.

### FW-EXT-04 — An old Supervisor response arriving after explicit retry is rejected

**Given** the first Supervisor call is blocked, its automatic budget has reached the user-visible retry state, and the user explicitly retries the current decision.

**When** the retry publishes a valid result and the older blocked call later returns another valid result.

**Then**:

- the current trigger facts admit only the already-published result;
- no second turn or alternate Stage result appears;
- the old result is not copied into checkpoint as the pending decision;
- the public view remains on the result published by the successful retry;
- trace may record both physical completions without recording either response body.

### FW-EXT-05 — Exact candidate adoption attaches `question_id`; rewriting does not

**Given** retrieval returns candidate `{question_id: Q1, question: T1}` and the Supervisor receives only `T1`.

**When**, in separate runs, the validated final question is:

1. exactly `T1`;
2. a whitespace, punctuation or wording variant of `T1`;
3. a generated question unrelated to all candidates.

**Then**:

- case 1 publishes a turn associated with `Q1`;
- cases 2 and 3 publish turns whose `question_id` is null;
- no semantic retrieval or normalization pass runs after publication;
- ideal-answer reuse and statistics later consume only the stored association.

### FW-EXT-06 — A lost Local Runtime project-answer task cannot overwrite snapshot-only fallback

**Given** post-processing has started with a valid `source_handle` and the Local Runtime project-answer request is blocked.

**When** the handle expires or Local Runtime becomes unavailable, Application Runtime completes the same logical project-answer task through the documented snapshot-only fallback, and the old local result later arrives.

**Then**:

- one logical project-answer task reaches a terminal result;
- only one set of project answers can be adopted;
- the late local result cannot append another `## 事后核验` section or overwrite adopted answers;
- evaluations see the final PostgreSQL snapshot and the one adopted result set;
- no per-question directory task is created as a fallback.

### FW-EXT-07 — Truncated project-answer JSON is not partially guessed

**Given** the project-answer task is running for multiple answered turns.

**When** every allowed attempt returns a truncated top-level JSON document.

**Then**:

- no substring or apparently complete inner item is adopted;
- project-answer fields remain null;
- the task reaches its documented failed terminal state;
- ideal-answer and evaluation processing continues according to the nullable-reference contract;
- no raw response body enters the public result, checkpoint or trace.

## Required observable assertions

- Provider physical-call count comes only from the controlled external adapter.
- Turn and Stage cardinality is verified through the current interview/full-history views; direct database inspection may additionally confirm uniqueness.
- Prompt capture verifies that Supervisor sees candidate text but not `question_id`, retrieval score or ideal answer.
- Late-result tests must wait until the delayed provider has actually returned before making the final assertion.
