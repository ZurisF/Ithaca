# Post-processing fan-out and barrier windows

## Scope

These scenarios verify the ordering and adoption rules among question settlement, whole-session project answers, per-question ideal answers, optional post-verification, per-question evaluations and the final report.

## Baseline fixture

- A session has ended with at least two answered turns and is `post_processing`.
- Feedback is frozen and settlement can be observed independently of generative tasks.
- Controlled model results can complete in any order or fail per task.
- Turn markers ensure that output items cannot be silently associated with the wrong turn.

## Scenarios

### FW-POST-01 — Settlement commits before any answer task starts

**Given** post-processing has just begun.

**When** the settlement transaction is blocked or fails.

**Then**:

- no project-answer, generated ideal-answer, evaluation or report model request starts before settlement commits;
- recovery retries settlement using the same session-level idempotency rule;
- after commit, answer branches may start once;
- settlement failure does not modify frozen turns or feedback.

### FW-POST-02 — Project-answer items are adopted independently only after top-level validation

**Given** the project-answer response has a valid top-level document containing valid, missing, duplicate and nonexistent `turn_no` items.

**When** Application Runtime validates the response.

**Then**:

- only unique items for existing answered turns are eligible for adoption;
- missing/invalid/duplicate items remain null and are never shifted to another turn;
- one task writes only `project_answer` columns;
- a top-level parse failure instead adopts no items at all.

### FW-POST-03 — Post-verification is a barrier before dependent project answers

**Given** project answers rely on facts obtained from the authorized directory and the response includes a `## 事后核验` append.

**When** the append is delayed, fails or has an unknown database outcome.

**Then**:

- dependent project answers are not visible or available to evaluation before the append commits;
- an unknown append outcome is reconciled through the existing snapshot operation record;
- successful publication atomically makes the final snapshot and the validated answers available under the current task contract;
- failure leaves those answers unavailable rather than evaluating them against an older snapshot.

### FW-POST-04 — Reference branches may complete in any order

Run permutations where:

- project answers finish before all ideal answers;
- ideal answers finish before project answers;
- selected ideal-answer generation tasks fail permanently;
- project answers fail while ideal answers succeed.

**Then**:

- evaluation begins only after both reference branches have terminal outcomes;
- each evaluation receives final snapshot, its own Q/A and its own nullable references;
- failure of a reference task does not itself lower the user's evaluation;
- completion order does not change the input for any evaluation.

### FW-POST-05 — Restart after partial fan-out reuses completed results

**Given** some ideal-answer or evaluation tasks have successfully published and others are still running.

**When** the worker or Application Runtime restarts.

**Then**:

- completed artifacts and successful task states are loaded from PostgreSQL;
- completed model calls are not repeated;
- only unfinished/expired work is resumed within its remaining automatic policy;
- no branch overwrites a sibling result column with null.

### FW-POST-06 — One permanent evaluation failure prevents a fabricated report

**Given** all reference branches are terminal and evaluations fan out.

**When** one evaluation exhausts its attempts while others succeed.

**Then**:

- successful comments remain available in the full Q/A view;
- the failed turn has no fabricated placeholder comment;
- report generation does not start;
- the session eventually becomes `completed` with processing incomplete;
- no user-triggered post-processing rerun command is exposed in the current version.

### FW-POST-07 — Report publication is unique across acknowledgement loss

**Given** every evaluation succeeded and report generation returned a valid fixed JSON result.

**When** report publication commits and the worker terminates before acknowledging task completion to its caller/checkpoint.

**Then**:

- one report row and one successful report task exist;
- recovery reads the committed result and does not call the report model again;
- UI and Markdown are rendered from the same report JSON;
- Markdown excludes scores, mapped labels, radar data and the UI-only disclaimer.

### FW-POST-08 — Unanswered final turn is excluded from generative evidence

**Given** the interview ends with one published `answer IS NULL` turn and at least one completed Stage satisfying the report threshold.

**When** post-processing runs.

**Then**:

- settlement counts the unanswered turn's non-null `question_id` as one usage if present;
- project answers, ideal answers, evaluations and report evidence include only answered turns;
- full history still displays the unanswered final question;
- no missing answer is interpreted as a negative capability signal.

## Required observable assertions

- Capture each controlled provider's input and verify context isolation.
- Assert task/artifact state through result views first; direct database inspection may confirm atomic publication and column ownership.
- Run completion-order permutations from one parameterized scenario instead of maintaining separate implementations.
