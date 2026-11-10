# Human Calibration

LLM judges need periodic calibration against human ratings. Sightline provides a blind
rating workflow and computes judge-human agreement.

## Admin workflow

1. Open `/app` as an admin and go to **Admin > Observability > Human Calibration**.
2. Select **Load next unlabeled turns**. The queue contains judged turns without a human
   rating for the current admin.
3. Read the question, answer and available tool evidence. The judge score is hidden.
4. Rate the answer from 1 to 5, optionally add notes, and submit.
5. The judge score and difference are revealed after submission; the next answer loads.
6. Select **Compute QWK** to persist agreement metrics and show them in the panel.

## CSV workflow (bulk/offline)

```bash
python scripts/eval_agent.py --days 3650 --sample 30 --apply
python scripts/calibrate_judge.py --export 30 --out data/calibration/round1.csv
# fill human_score (1-5) in the CSV
python scripts/calibrate_judge.py --score data/calibration/round1.csv
python scripts/calibrate_judge.py --latest
```

The export is blind: judge scores are not included. Ratings are stored in
`human_labels`; each scoring run is recorded in `calibration_runs`.

## Rubric

| Score | Meaning |
|---|---|
| 5 | Fully grounded in the evidence, complete, clear, citations consistent |
| 4 | Correct and relevant with minor gaps |
| 3 | Partially useful, thin, tangential or incomplete |
| 2 | Mostly wrong, misleading or evasive |
| 1 | Fabricated, dangerous or off-topic |

Rules: length is not quality; a justified "insufficient evidence" is correct; rate each
answer independently; use the evidence panel when present.

## Metrics and interpretation

| Metric | Meaning |
|---|---|
| QWK | quadratic weighted kappa (1-5 ordinal); primary agreement metric |
| Spearman | rank correlation |
| MAE | mean absolute error |
| Exact / within-1 | percentage of identical / adjacent ratings |

Guideline: QWK >= 0.8 excellent, 0.6-0.8 good, 0.4-0.6 moderate, < 0.4 poor. If QWK is
low, revise rubric anchors and re-run the judge on the same sample. If the judge is
systematically more lenient or stricter, record the bias and adjust the rubric.

## Notes

- At least 20-30 completed ratings are needed for a useful first calibration.
- Multiple admins can rate the same turns; ratings are stored per rater.
- The judge score is revealed only after a rating is saved, preserving blind evaluation.
