# Evaluation

Sightline measures answer quality and retrieval quality separately. The goal is a
repeatable evaluation loop, not a one-off review.

## What is measured

| Layer | Signals |
|---|---|
| Turn | model, tokens, cost, latency, iterations, tool calls, citations, no-answer |
| Retrieval | Recall@K, nDCG@10, MRR over a labeled golden set |
| Answer quality | G-Eval judge score (1-5), human calibration (QWK), user feedback |

## Data flow

```
chat turn -> obs.db turns/tool_calls -> evaluation sample -> judge -> eval_scores
                                      -> human calibration -> human_labels
golden set -> pool retrieval -> Recall/nDCG/MRR -> eval_retrieval
```

- `obs.db` stores turn telemetry and tool previews (first 1.2 KB per tool).
- `chats.db` stores the actual questions and answers.
- `eval_scores` stores judge verdicts; `human_labels` stores human ratings.

## Fixed evaluation set

`scripts/eval_questions.json` contains a curated multilingual set covering
qualitative reports, displacement, funding, conflict, alerts, weather, World Bank
and OSM questions, plus one deliberately unanswerable case. It is the basis for a
comparable baseline across model and prompt changes.

```bash
python scripts/eval_fixed.py --dry-run                 # review questions
python scripts/eval_fixed.py --base-url http://127.0.0.1:5001
python scripts/eval_agent.py --days 365 --turn-ids <ids> --samples 3 --apply
python scripts/eval_report.py --out docs/EVALUATION_RESULTS.md
```

Use the generated run file (`data/eval/fixed_run.json`) to keep the exact question
set and turn ids. Do not sample unrelated chats for a published baseline.

## Chat evaluation

```bash
python scripts/eval_agent.py --days 30 --sample 10            # dry run
python scripts/eval_agent.py --days 30 --sample 10 --apply    # persist
python scripts/eval_agent.py --sample 5 --samples 1 --judge-model deepseek/deepseek-chat
```

Defaults: cross-family judge (OpenAI model for Gemini answers), three samples per
answer with averaged scores, evidence-aware prompt. The rubric scores factual grounding,
relevance, completeness, citation discipline, and honest abstention. Length is not a
quality signal; a grounded "no evidence found" is a valid answer.

When only Google is configured, the judge defaults to `gemini-3.1-pro-preview`; this is
same-family and must be treated as a weaker signal until calibrated with human labels.

Results are visible under Admin > Observability > Chat Quality Evaluation. Re-running
updates the same verdict (unique per turn, model, mode) instead of duplicating it.

## Human calibration

See [CALIBRATION.md](CALIBRATION.md). The admin UI provides a blind queue: the judge score
is hidden until the rating is submitted. Agreement metrics are quadratic weighted kappa
(primary), Spearman, MAE, exact and within-1 agreement.

## Retrieval evaluation

```bash
python scripts/eval_retrieval.py --curate "cholera in Yemen" --country Yemen --k 5
python scripts/eval_retrieval.py --gold data/golden_set.json --k 10 --stage1-k 50
python scripts/eval_retrieval.py --gold data/golden_set.json --apply
```

The harness uses the production pool-based retrieval path, not whole-collection Chroma
queries. It reports two stages:

- Stage 1 Recall@50: candidate coverage (the ceiling for the generator).
- Stage 2 Recall@10, nDCG@10, MRR: what the generator actually sees.

Golden-set labels are ReliefWeb report ids and require human confirmation. The template is
`scripts/golden_set.template.json`; empty or placeholder labels are rejected.

## Metrics

| Metric | Definition |
|---|---|
| Judge score | Mean of N judge samples, 1-5 |
| Low-score rate | share of judged answers below 3 |
| Citation rate | share of OK turns with at least one inline citation |
| No-answer rate | share of OK turns where the agent reports insufficient evidence |
| Recall@K | relevant reports in top-K / total relevant |
| nDCG@K | graded ranking quality with log discount |
| MRR | reciprocal rank of the first relevant report |
| QWK | quadratic weighted kappa between human and judge scores |

## Limitations

- Backfilled turns have no tool previews; the judge can assess internal consistency only.
- Judge-human agreement should be validated periodically with 20-30 human labels.
- Golden sets need human labels; 50 queries is a practical minimum (100-200 for fine
  differences). Unanswerable query scoring is not yet implemented.
- Judge outputs are an evaluation signal, not a substitute for domain review.

## Privacy and retention

Evaluation stores scores and issue lists, not raw model reasoning. Error and evaluation
data are retained for 90 days by default (`OBS_RETENTION_DAYS`, `ERRORS_RETENTION_DAYS`).
