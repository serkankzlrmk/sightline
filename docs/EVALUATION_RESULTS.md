# Evaluation Results (preliminary)

> Status: 2026-11-10. This report contains only results that were actually measured.
> Chat and retrieval evaluation are staged but not yet measured; they are explicitly
> marked as pending rather than filled with estimates.

## 1. Scope and environment

- Application: Sightline, release `3539448` (local), Python 3.13, Google Gemini
  `gemini-3-flash-preview` for the chat smoke test.
- Evaluation stores: `obs.db` (turns, tool calls, judge scores, human labels) and
  `errors.db` (runtime errors).
- Public report contains aggregate results only; no questions, answers, user ids or
  tool payloads.

## 2. Chat quality evaluation — preliminary

A fixed evaluation set of 22 questions is defined in `scripts/eval_questions.json`. The
first 12 were run end-to-end against the local agent using Google `gemini-3-flash-preview`;
all 12 produced answers (no empty responses). Eleven were judged with a Google judge
(`gemini-3.1-pro-preview` for 10 turns, `gemini-3-flash-preview` for one turn); one judge
call returned no verdict and is excluded from the score distribution.

| Metric | Value |
|---|---:|
| Turns in run | 12 |
| Judged turns | 11 |
| Mean judge score (1-5) | 3.55 |
| Median judge score | 3.67 |
| Low-score rate (<3) | 27.3% (3/11) |
| Citation rate | 36.4% |
| No-answer rate | 0.0% |
| Tool-use rate | 100% |
| Average tool calls | 6.27 |
| Median latency | 14.8 s |
| p95 latency | 179 s |
| Average cost per turn | $0.124 |

Score distribution: 1 x1, 2 x1, 3 x2, 4 x3, 5 x3 (rounded judge scores).

**Human calibration is pending.** Judge scores are not validated quality until the
20 judged turns are rated by a human reviewer. They are available in the admin
calibration queue; QWK will be added after review.

Operational notes:

- The Google free-tier quota was replaced by a paid quota before this run.
- Long-tail latency is driven by HDX rate limits; tool calls are capped per turn and the
  agent forces a final answer after the budget.
- One answer could not be judged and is excluded rather than estimated.
- The Pakistan answer exposed a citation-grounding failure (fabricated figures/URLs).
- A post-generation URL grounding guard now removes links whose target was not present in
  the turn's tool output (deployed in `4e3babc`). Numeric claims are not yet verified.

## 3. Retrieval evaluation — pending labels

A retrieval pool-based evaluation harness exists (`scripts/eval_retrieval.py`) and
reports two stages:

- Stage 1 Recall@50: candidate coverage ceiling.
- Stage 2 Recall@10, nDCG@10, MRR: evidence actually shown to the generator.

Twelve queries and 52 real candidate reports were retrieved with the production
pool-based path. Human relevance labels are required before metrics can be computed;
the labeling sheet is `data/eval/golden_set_labeling.csv` (not published; local only).

## 4. Proposal deterministic verifier — measured

The deterministic compliance branch of the Proposal Studio verifier was exercised on a
labelled fixture matrix: OCHA CBPF character ceilings (five sections), USAID BHA
character limits plus the 50% displaced-population quota, and EU PRAG character limits.

| Metric | Value |
|---|---:|
| Fixtures | 14 |
| True positives | 10 |
| False positives | 0 |
| False negatives | 0 |
| Precision | 1.000 |
| Recall | 1.000 |

What the fixtures cover:

- Every section ceiling for OCHA (4,000 chars) and EU PRAG (3,500-5,000 chars).
- USAID 50% displaced-population threshold, including the inclusive boundary.
- Section-specific issue reporting (the failing section key is preserved).
- Clean proposals produce no false positives.

Limitations:

- The fixtures are synthetic and derived from the verifier contract; they validate
  implementation and regression safety, not field accuracy.
- Only the deterministic branch was measured. The LLM blind verifier and cross-section
  semantic checks are not covered by these numbers.
- Human review remains the authority for proposal compliance.

## 5. Operational signals

The deployed release exposes:

- `GET /api/health`: database, vector, LLM, data freshness, release.
- Admin > Observability: turn telemetry, tool usage, model/cost breakdown, feedback,
  judge scores, human calibration queue.
- Admin > Errors: request ids, grouped fingerprints, tool/LLM failures, resolve action.
- Audit API and synthetic canary.

## 6. Next steps

1. Collect 20+ human labels and publish QWK (the 21 judged turns are already queued).
2. Add post-generation citation URL/claim grounding and re-run the Pakistan case.
3. Complete the 52 retrieval relevance labels and run the two-stage retrieval metrics.
4. Extend proposal verification with adversarial fixtures and measure the LLM verifier
   against human review.
5. Compare Flash/Pro models and run RRF/clustering ablations once the evaluation quota is
   available.Twenty-two of the 22 questions produced answers; 21 were judged. One answer could not be
judged (empty judge verdict) and is excluded. Answers were generated with Google
`gemini-3-flash-preview`; judging used `gemini-3.1-pro-preview` (20 turns) and
`gemini-3-flash-preview` (one turn).

| Metric | Value |
|---|---:|
| Questions in set | 22 |
| Answers produced | 22 |
| Judged turns | 21 |
| Mean judge score (1-5) | 3.52 |
| Median judge score | 3.67 |
| Low-score rate (<3) | 23.8% (5/21) |
| Citation rate | 47.6% |
| No-answer rate | 0.0% |
| Tool-use rate | 100% |
| Average tool calls | 5.29 |
| Median latency | 13.1 s |
| p95 latency | 169 s |
| Average cost per turn | $0.103 |

Score distribution: 1 x2, 2 x2, 3 x5, 4 x5, 5 x7 (rounded judge scores).

The lowest-scoring answer (Pakistan floods) was judged 1/5 for fabricated displacement
and food-security statistics plus fake URLs. This is a concrete quality finding: citation
URLs and numeric claims need a post-generation grounding check before this answer class is
treated as production-safe.

Operational notes:

- The Google free-tier quota was replaced by a paid quota before this run.
- Long-tail latency is driven by HDX rate limits; tool calls are capped per turn and the
  agent forces a final answer after the budget.
- One answer could not be judged and is excluded rather than estimated.
- The Pakistan answer exposed a citation-grounding failure (fabricated figures/URLs).
- A post-generation URL grounding guard now removes links whose target was not present in
  the turn's tool output (deployed in `4e3babc`). Numeric claims are not yet verified.

## 3. Retrieval evaluation — pending labels

A retrieval pool-based evaluation harness exists (`scripts/eval_retrieval.py`) and
reports two stages:

- Stage 1 Recall@50: candidate coverage ceiling.
- Stage 2 Recall@10, nDCG@10, MRR: evidence actually shown to the generator.

Twelve queries and 52 real candidate reports were retrieved with the production
pool-based path. Human relevance labels are required before metrics can be computed;
the labeling sheet is `data/eval/golden_set_labeling.csv` (not published; local only).

## 4. Proposal deterministic verifier — measured

The deterministic compliance branch of the Proposal Studio verifier was exercised on a
labelled fixture matrix: OCHA CBPF character ceilings (five sections), USAID BHA
character limits plus the 50% displaced-population quota, and EU PRAG character limits.

| Metric | Value |
|---|---:|
| Fixtures | 14 |
| True positives | 10 |
| False positives | 0 |
| False negatives | 0 |
| Precision | 1.000 |
| Recall | 1.000 |

What the fixtures cover:

- Every section ceiling for OCHA (4,000 chars) and EU PRAG (3,500-5,000 chars).
- USAID 50% displaced-population threshold, including the inclusive boundary.
- Section-specific issue reporting (the failing section key is preserved).
- Clean proposals produce no false positives.

Limitations:

- The fixtures are synthetic and derived from the verifier contract; they validate
  implementation and regression safety, not field accuracy.
- Only the deterministic branch was measured. The LLM blind verifier and cross-section
  semantic checks are not covered by these numbers.
- Human review remains the authority for proposal compliance.

## 5. Operational signals

The deployed release exposes:

- `GET /api/health`: database, vector, LLM, data freshness, release.
- Admin > Observability: turn telemetry, tool usage, model/cost breakdown, feedback,
  judge scores, human calibration queue.
- Admin > Errors: request ids, grouped fingerprints, tool/LLM failures, resolve action.
- Audit API and synthetic canary.

## 6. Next steps

1. Collect 20+ human labels and publish QWK (the 21 judged turns are already queued).
2. Add post-generation citation URL/claim grounding and re-run the Pakistan case.
3. Complete the 52 retrieval relevance labels and run the two-stage retrieval metrics.
4. Extend proposal verification with adversarial fixtures and measure the LLM verifier
   against human review.
5. Compare Flash/Pro models and run RRF/clustering ablations once the evaluation quota is
   available.
