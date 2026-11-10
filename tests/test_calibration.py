"""Tests for scripts/calibrate_judge.py — blind human sheet + agreement metrics."""

import csv
import sqlite3
import time
from pathlib import Path

import pytest


@pytest.fixture()
def calibration_env(tmp_path, monkeypatch):
    """obs.db with two judged turns + a chats.db whose messages pair with them."""
    import config
    from observability import store

    chats_path = tmp_path / "chats.db"
    conn = sqlite3.connect(str(chats_path))
    conn.executescript(
        """
        CREATE TABLE chats (id TEXT PRIMARY KEY, uid TEXT, title TEXT, created REAL);
        CREATE TABLE chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT, role TEXT, content TEXT, ts REAL, meta TEXT DEFAULT '{}'
        );
        """
    )
    now = time.time()
    for chat_id, question, answer in (
        ("c1", "How many were displaced?", "About 1,200 people [1]."),
        ("c2", "What is the cholera situation?", "No clear answer from the sources."),
    ):
        conn.execute("INSERT INTO chats VALUES (?, 'u1', 'T', ?)", (chat_id, now - 500))
        conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, 'user', ?, ?)",
            (chat_id, question, now - 120),
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, role, content, ts) VALUES (?, 'assistant', ?, ?)",
            (chat_id, answer, now - 100),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "CHATS_DB_PATH", chats_path, raising=False)
    monkeypatch.setattr(config, "OBS_DB_PATH", tmp_path / "obs.db", raising=False)
    monkeypatch.setattr(config, "OBS_ENABLED", True, raising=False)
    store.reset_for_tests()
    store.init_obs_db(force=True)

    for i, (turn_id, chat_id) in enumerate((("t1", "c1"), ("t2", "c2")), start=1):
        store.record_chat_turn(
            {
                "turn_id": turn_id,
                "uid": "u1",
                "chat_id": chat_id,
                "model_key": "flash",
                "model_id": "google/gemini-3.8-flash",
                "status": "ok",
                "started_at": now - 130,
                "finished_at": now - 100,
                "latency_ms": 1000 + i,
            }
        )
    store.record_eval_score("t1", 4, judge_model="judge/x")
    store.record_eval_score("t2", 2, judge_model="judge/x")
    yield store
    store.reset_for_tests()


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["turn_id", "question", "answer", "evidence", "human_score", "notes"])
        writer.writeheader()
        writer.writerows(rows)


# ── Metric math ──────────────────────────────────────────────────────────────


def test_perfect_agreement():
    from scripts.calibrate_judge import compute_metrics

    m = compute_metrics([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert m["qwk"] == 1.0
    assert m["spearman"] == 1.0
    assert m["mae"] == 0.0
    assert m["exact_rate"] == 1.0
    assert m["within1_rate"] == 1.0
    assert m["interpretation"]["verdict"] == "excellent"


def test_known_qwk_negative_case():
    from observability.calibration import quadratic_weighted_kappa

    # Judge shifts both ratings +1: observed/expected disagreement ratio 2/3 → QWK 1/3
    assert quadratic_weighted_kappa([1, 2], [2, 3]) == pytest.approx(1 / 3)


def test_qwk_range_and_within_one():
    from scripts.calibrate_judge import compute_metrics

    m = compute_metrics([1, 3, 5], [2, 3, 4])
    assert -1.0 <= m["qwk"] <= 1.0
    assert m["within1_rate"] == 1.0
    assert m["exact_rate"] == pytest.approx(1 / 3, abs=1e-4)


# ── Export / score round trip ────────────────────────────────────────────────


def test_export_sheet_is_blind_and_pairs_messages(calibration_env, tmp_path):
    from scripts.calibrate_judge import export_sheet

    out = tmp_path / "sheet.csv"
    report = export_sheet(n=5, days=3650, out=str(out))
    assert report["exported"] == 2

    rows = _read_csv(out)
    assert len(rows) == 2
    assert set(rows[0]) == {"turn_id", "question", "answer", "evidence", "human_score", "notes"}
    assert "1,200" in " ".join(r["answer"] for r in rows)
    # blind: judge score must not leak into the sheet
    assert all(r["human_score"] == "" for r in rows)
    assert "4.0" not in out.read_text(encoding="utf-8-sig")


def test_export_requires_judged_turns(calibration_env, tmp_path, monkeypatch):
    from observability import store
    from scripts.calibrate_judge import export_sheet

    monkeypatch.setattr(store, "db_path", lambda: tmp_path / "empty.db")
    store.reset_for_tests()
    with pytest.raises(SystemExit):
        export_sheet(n=5, days=3650, out=str(tmp_path / "x.csv"))


def test_score_sheet_persists_labels_and_run(calibration_env, tmp_path):
    from scripts.calibrate_judge import export_sheet, score_sheet

    out = tmp_path / "sheet.csv"
    export_sheet(n=5, days=3650, out=str(out))
    rows = _read_csv(out)
    scores = {"t1": "4", "t2": "3"}  # human: t1 agrees (4), t2 disagrees (2 vs 3)
    for row in rows:
        row["human_score"] = scores[row["turn_id"]]
        row["notes"] = "test"
    _write_csv(out, rows)

    report = score_sheet(str(out), min_n=2)
    assert report["stored_human_labels"] == 2
    assert report["matched_pairs"] == 2
    assert report["metrics"]["n"] == 2
    assert -1.0 <= report["metrics"]["qwk"] <= 1.0
    assert report["metrics"]["human_mean"] == 3.5

    labels = calibration_env.human_labels_for(["t1", "t2"])
    assert labels["t1"]["score"] == 4.0
    assert labels["t2"]["score"] == 3.0

    summary = calibration_env.calibration_summary(days=3650)
    assert summary["latest"]["n"] == 2
    assert summary["human_labeled_turns"] == 2


def test_score_sheet_rejects_bad_scores(calibration_env, tmp_path):
    from scripts.calibrate_judge import export_sheet, score_sheet

    out = tmp_path / "sheet.csv"
    export_sheet(n=5, days=3650, out=str(out))
    rows = _read_csv(out)
    rows[0]["human_score"] = "9"
    rows[1]["human_score"] = "3"
    _write_csv(out, rows)

    # one invalid row is reported; one valid row is not enough for min_n=2
    with pytest.raises(SystemExit):
        score_sheet(str(out), min_n=2)


def test_admin_calibration_endpoint(calibration_env):
    import server

    client = server.app.test_client()
    response = client.get("/api/admin/obs/calibration")
    assert response.status_code == 200
    assert "latest" in response.get_json()
