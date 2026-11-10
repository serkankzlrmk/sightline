"""Tests for the retrieval golden-set CSV labeling helper."""

import csv
import json


def test_export_then_import_labels(tmp_path):
    import scripts.golden_label_sheet as sheet

    draft = tmp_path / "draft.json"
    draft.write_text(
        json.dumps(
            [
                {
                    "query": "q1",
                    "country": "Sudan",
                    "candidates": [
                        {"report_id": "r1", "title": "A", "date": "2026-01-01", "url": "u1"},
                        {"report_id": "r2", "title": "B", "date": "2026-01-02", "url": "u2"},
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "labels.csv"
    out = tmp_path / "golden.json"
    assert sheet.export(draft, csv_path) == 0
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert len(rows) == 2
    rows[0]["relevant"] = "1"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    assert sheet.import_labels(csv_path, out) == 0
    golden = json.loads(out.read_text(encoding="utf-8"))
    assert golden == [{"query": "q1", "relevant": ["r1"], "country": "Sudan"}]


def test_import_empty_returns_nonzero(tmp_path):
    import scripts.golden_label_sheet as sheet

    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("query,country,report_id,date,title,url,relevant\nq,Sudan,r1,,,,\n", encoding="utf-8")
    assert sheet.import_labels(csv_path, tmp_path / "out.json") == 2
