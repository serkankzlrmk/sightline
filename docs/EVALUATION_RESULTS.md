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

## 2. Chat quality evaluation — pending

A fixed 22-question evaluation set is defined in `scripts/eval_questions.json`
(qualitative reports, displacement, funding, conflict, alerts, weather, World Bank,
OSM, one deliberately unanswerable case).

The pipeline is implemented and tested:

- `scripts/eval_fixed.py` runs the fixed set and records exact turn ids.
- `scripts/eval_agent.py --turn-ids` judges exactly those turns without sampling
  unrelated conversations.
- `scripts/eval_report.py` produces score distributions, citation/tool/no-answer
  rates, latency/cost and judge-human agreement.

**No chat quality numbers are published yet.** The local Google API key currently hits
the Free Tier limit (20 generate-content requests/day), so the 22-question run and
judge calls cannot complete. An earlier pilot sample was discarded because it contained
development/test prompts and was not representative.

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

1. Enable paid Google API quota or restore an OpenRouter balance.
2. Run the 22-question chat evaluation and human calibration (target: 20+ labels, QWK).
3. Complete the 52 retrieval relevance labels and run the two-stage retrieval metrics.
4. Extend proposal verification with adversarial fixtures and measure the LLM verifier
   against human review.
5. Compare Flash/Pro models and run RRF/clustering ablations once the evaluation quota is
   available.
