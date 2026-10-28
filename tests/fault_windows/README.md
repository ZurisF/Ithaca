# Fault-window test specifications

> Status: executable-test specifications; application implementation is in progress, and the scenarios are not yet fully automated.
>
> Authority: `PRODUCT_DEVELOPMENT.md` defines product behavior. `IMPLEMENTATION_DESIGN.md` defines the current engineering contract. `History/ENGINEERING_DESIGN.md` is only a source of reusable fault windows; conflicting historical behavior is not carried forward.

## Purpose

This directory turns recurring failure windows into a small set of reusable test families. The goal is to verify observable business behavior across crashes, retries, late results and concurrent commands without reintroducing the historical global receipt/job/epoch/fence scheduler.

These files are specifications, not placeholder test code. Once the implementation and test framework exist, convert one scenario at a time into a failing integration test, implement only enough behavior to pass it, and keep assertions at the confirmed seams below.

## Confirmed test seams

1. **Application Runtime seam**
   - Send commands through the public HTTP interface.
   - Observe behavior through the current session/interview/result views and exported artifacts.
   - Do not call Graph nodes, repositories or transaction helpers directly from behavioral tests.

2. **Local Project Runtime seam**
   - Authorize sources and submit local tasks through its HTTP interface.
   - The Application Runtime may use only `source_handle`; tests must never give it a real path.

3. **External dependency seams**
   - Replace the model provider, embedding/reranking clients, clock and checkpointer with controlled adapters where a fault must be injected.
   - Prefer real PostgreSQL and Redis instances for integration and recovery scenarios.
   - Do not mock internal application modules.

4. **Persistence inspection seam**
   - Prefer public views for behavioral assertions.
   - Direct PostgreSQL/Redis inspection is allowed only for database constraints, exactly-once business effects, cleanup, checkpoint recovery and content-leak checks that are not visible through a public view.

5. **SSE seam**
   - SSE is an advisory notification channel, not a source of truth.
   - Tests may discard events. Recovery is asserted by re-reading the current HTTP view, not by inspecting internal send order.

## Case identifiers

```text
FW-EXT-*   external model, retrieval and Local Runtime calls
FW-COM-*   PostgreSQL commit, checkpoint and response-loss windows
FW-INT-*   interrupt and snapshot-correction confirmation windows
FW-CTX-*   compact and checkpoint reconstruction windows
FW-RACE-*  concurrent session commands
FW-POST-*  post-processing fan-out, barriers and joins
FW-SEC-*   terminal cleanup, authorization and content security
```

Identifiers are stable references for implementation plans and CI reports. They are not database fields or runtime operation identifiers.

## Shared fixtures

Implement these as test helpers only after the corresponding production seam exists.

### `runtime_cluster`

Runs:

- a real PostgreSQL instance with current migrations;
- a real Redis instance and the production checkpointer adapter;
- Application Runtime over HTTP;
- Local Project Runtime over HTTP when the scenario needs directory access;
- background worker(s), with a test-only way to stop and restart their processes.

Each test receives a fresh database namespace or fully isolated transaction/schema. Redis keys must be isolated by test run. Tests must not depend on execution order.

### `controlled_model_provider`

An adapter at the external model seam that can independently:

- return a known valid structured result;
- return malformed structured output;
- return a retryable transport error;
- return a deterministic non-retryable error;
- block until the test releases it;
- record that a physical request was sent;
- deliver a result after cancellation or after another retry has succeeded.

Its call log may be asserted because it is the fake external provider's public test interface. Tests must not assert which internal Graph node called it.

### `controlled_retrieval`

Provides deterministic candidates and can time out or fail. A candidate has an internal `question_id` and exact `question` text, while the Supervisor-facing projection contains only text. Tests must cover exact-text association and the absence of semantic post-matching.

### `faultable_checkpointer`

Uses the production checkpointer interface and can fail or terminate the worker immediately before or after a checkpoint write. Tests may clear all session checkpoint keys to simulate Redis loss.

It must not expose Graph implementation details to the behavioral assertion layer. Prompt/call capture from `controlled_model_provider` is used to verify reconstructed context.

### `test_project`

A temporary authorized project containing:

- ordinary text and source files;
- a test credential fixture;
- a symlink whose destination can be switched after inventory;
- deterministic files for Observer and project-answer tasks.

The fixture owns its temporary directory. Production code must not write to it.

### `content_leak_oracle`

Given unique canary strings for source code, credentials, prompt content and answers, scan only the stores the test is authorized to inspect:

- PostgreSQL business and telemetry tables;
- Redis checkpoint values;
- HTTP/SSE responses;
- exported Markdown;
- captured structured logs and controlled-provider requests.

The oracle asserts allowlisted destinations rather than a blanket absence. For example, an answer may exist in the owner's business history but its unfiltered credential canary must not enter a model request, checkpoint or trace.

## Reusable fault positions

Fault injection should concentrate at a small number of internal seams:

```text
external call:
  before_send
  after_send_before_response
  after_response_before_business_publish

business transaction:
  before_commit
  after_commit_before_ack

checkpoint:
  before_checkpoint_write
  after_checkpoint_write

notification:
  after_business_commit_before_sse

worker ownership:
  after_claim_before_work
  after_work_before_publish
```

Do not add production workflow states for these positions. Implement them through controlled adapters, transaction hooks available only in tests, or actual worker termination.

## Cross-cutting assertions

Every scenario chooses the relevant subset of these assertions:

1. **User-visible outcome**: the current HTTP view is internally consistent and exposes only commands legal in that state.
2. **Business-effect cardinality**: a turn, Stage result, snapshot append, post-result, report or settlement exists zero or one time as required.
3. **Physical-call cardinality**: repeated external calls are counted separately from business effects; a retry may increase calls but cannot create another business result.
4. **State continuity**: resume uses the authoritative PostgreSQL facts and does not skip or repeat a Stage/turn.
5. **Content boundary**: raw secrets, disallowed source contents and model bodies do not appear in checkpoints, trace or errors.
6. **Authorization**: owner and `curation_review` checks are re-evaluated at the time of reading or publishing.
7. **No hidden semantic matching**: a turn receives `question_id` only when the final question exactly equals a candidate from that retrieval call.

## Implementation discipline

- Convert one scenario to a failing automated test before implementing the behavior it specifies.
- Keep scenario setup at the public seam; use fault adapters only for the failure itself.
- Do not create a global `operation_receipts` abstraction, execution epoch, persistent call-slot ledger or notification log solely to satisfy these specifications.
- Prefer database constraints and conditional writes where the invariant is expressible there.
- A test passes because observable behavior is correct, not because a particular node, repository method or SQL statement was invoked.
- Keep a small process-kill suite for true cross-process windows. Most permutations should run through the same adapters without repeatedly booting the entire cluster.

## Files

- `01_external_calls.md` — external requests, retries, unknown responses and late results.
- `02_commit_and_checkpoint.md` — commit/ACK/checkpoint/SSE loss windows.
- `03_interrupt_confirmation.md` — correction-card interrupts and append resolution.
- `04_compact_and_rebuild.md` — 20-turn compact boundaries and Redis reconstruction.
- `05_session_races.md` — answer, feedback, termination, retry and curation races.
- `06_post_processing_barriers.md` — reference-answer fan-out, final-snapshot barrier, evaluation and report join.
- `07_terminal_cleanup_and_security.md` — filesystem TOCTOU, deletion, stale writes, authorization and leak checks.

## Historical cases intentionally not reproduced

The following historical mechanisms are outside the current design and must not be inferred from these tests:

- semantic or post-interview question matching;
- a universal operation receipt for every command;
- a global `runtime_jobs` graph-runner scheduler with wake sequence, epoch and fence propagation;
- persistent model-call attempt slots;
- persisted SSE notification replay;
- configuration-proposal publishing tables;
- deletion-time reversal of aggregate question-bank counts;
- generation of reference answers for an unanswered final turn.
