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
- One answer could not be judged and one question timed out; both are excluded rather than estimated.

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

1. Collect 20 human labels and publish QWK (the 20 judged turns are already queued).
2. Re-run the two excluded questions (timeout / judge failure).
3. Complete the 52 retrieval relevance labels and run the two-stage retrieval metrics.
4. Extend proposal verification with adversarial fixtures and measure the LLM verifier
   against human review.
5. Compare Flash/Pro models and run RRF/clustering ablations once the evaluation quota is
   available.
