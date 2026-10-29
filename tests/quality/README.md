# Gate 7 frozen quality protocol

Status: protocol frozen for the first Gate 7 evaluation. The three-query retrieval run is exploratory; it cannot establish the product-level quality thresholds by itself.

## Fixed inputs

- `tests/fixtures/gate7/projects.json` names the three synthetic project types: documented directory, code-only directory, and user oral/Markdown supplement. The referenced snapshot files fix expected facts and a selected Thread. No private credential is present.
- `tests/fixtures/gate7/retrieval_queries.json` fixes three Stage-goal queries, the relevant reviewed-bank question for each, and a reference description. Do not change this file after seeing results without starting a separately versioned run.
- `test_gate7_fixed_replay.py` repeats each project twice through public HTTP, real PostgreSQL and Redis with a controlled model/retriever. This checks business behavior and repeatability, not model quality.
- Real-provider Observer, Planner, Supervisor, post-processing and local retrieval are run through their existing opt-in integration tests. Report each role separately, including failures.

## Retrieval scoring

For each query use the online retriever at K=3, the imported reviewed bank, and the configured local embedding/reranking models. `Recall@3` counts frozen gold questions returned divided by frozen gold questions; `nDCG@3` uses binary gain for those gold questions, with non-gold unjudged items receiving zero in this exploratory run. Exact duplicate count compares candidate text within each query. Semantic duplication and Stage adaptation need human labels and remain `null` until reviewed. The offline runner also calls RAGAS 0.4.3 `ContextRelevance` and `ContextRecall` with the frozen query, contexts and reference description; a failed judge or empty retrieval is recorded as missing, never as a zero or success. RAGAS is absent from online code.

## Product-level acceptance sample, fixed before human review

Run at least six independent sessions per project type, with at least 20 actual questions per project type (60 total minimum). Include normal completion, early finish, force exit, retry, correction confirmation and checkpoint recovery. Label every actual question in transcript order, including unanswered final questions for repetition analysis. A session with no model-generated question is an invalid sample but remains in the failure ledger; replace it with a new session before calculating content ratios. Do not remove hard or low-scoring valid samples.

Two reviewers independently blind-score each question for project relevance, Stage adaptation, whether it asks one clear main question, whether it repeats an earlier question in the same session, and whether the answer/feedback supports a new project fact. Use yes/no labels plus a short evidence note. Resolve disagreements by joint adjudication, retaining both initial labels. A question is relevant only when its topic and object are supported by the selected project material and current Stage; generic topic overlap alone is insufficient. Semantic repetition means the same answer would substantively satisfy an earlier question, even if wording differs. The denominator for relevance and repetition is all valid actual questions; the numerator is adjudicated `yes` for each criterion. At least 51 of the first 60 valid questions must be project-relevant (85%); at most 5 of 60 may be semantic repeats (strictly below 10%). Recompute the exact threshold from the actual denominator if more than 60 are collected.

For Observer, freeze at least ten verifiable facts per project before replay (30 facts total). Review every factual snapshot claim against the checked-in fixture or the oral Markdown assertion, and every citation against the cited line. Unsupported claims count against fact precision; missing gold facts count against recall. Citation validity uses the number of actual source-line citations as denominator and counts only those whose lines exist and support the attached claim. If a project legitimately has no file citation, it contributes zero citations and is reported separately rather than silently counted as valid.

For recovery, run at least 20 controlled single-model-failure trials across the three projects and terminal paths. The denominator is all triggered trials, including timeouts and failed retries; the numerator is trials that reach a valid current view without duplicate business effects. At least 18/20 must recover (90%). Count physical model calls and business effects separately.

Record raw transcript IDs, reviewer labels, adjudications, invalid/excluded samples, exact numerator and denominator, fixture hash, model/prompt versions, settings, and runtime date in a run result. Report any missing manual review, incomplete sample count, unavailable provider, or failed RAGAS judge as **未验证**. Do not infer a product pass from controlled replay or from three retrieval queries.

## Latency

`scripts/gate7_trace_latency.py` reads only approved trace metadata from the last seven days, grouped by operation, provider and status. It reports count and empirical P50/P95/P99. A percentile from fewer than 30 successful observations is descriptive only and is not a tuning basis. Compare failures and successes separately; include cold model load and live end-to-end timings before adjusting deadlines, concurrency, retrieval threshold or backoff.
