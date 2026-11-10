"""observability/calibration.py — judge-human agreement metrics (pure functions).

Used by both the CLI (scripts/calibrate_judge.py) and the admin calibration API
(blueprints/obs_bp.py), so the math lives in one place.
"""

from __future__ import annotations

_RATINGS = (1, 2, 3, 4, 5)


def _ranks(values: list[float]) -> list[float]:
    """Average ranks for ties (Spearman without scipy)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return cov / (va**0.5 * vb**0.5)


def spearman(a: list[float], b: list[float]) -> float:
    return pearson(_ranks(a), _ranks(b))


def mean_absolute_error(a: list[float], b: list[float]) -> float:
    if not a:
        return 0.0
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) / len(a)


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def exact_agreement(human: list[float], judge: list[float]) -> float:
    return _rate(sum(1 for h, j in zip(human, judge, strict=True) if round(h) == round(j)), len(human))


def within_one_agreement(human: list[float], judge: list[float]) -> float:
    return _rate(sum(1 for h, j in zip(human, judge, strict=True) if abs(h - j) <= 1), len(human))


def confusion_matrix(human: list[float], judge: list[float]) -> list[list[int]]:
    """Rows = human rating 1–5, cols = judge rating 1–5 (rounded)."""
    matrix = [[0 for _ in _RATINGS] for _ in _RATINGS]
    for h, j in zip(human, judge, strict=True):
        matrix[min(5, max(1, int(round(h)))) - 1][min(5, max(1, int(round(j)))) - 1] += 1
    return matrix


def quadratic_weighted_kappa(human: list[float], judge: list[float]) -> float:
    """QWK on the 1–5 ordinal scale (Cohen's kappa with quadratic weights)."""
    n = len(human)
    if n == 0:
        return 0.0
    observed = confusion_matrix(human, judge)
    k = len(_RATINGS)
    row_sums = [sum(row) for row in observed]
    col_sums = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    numerator = 0.0
    denominator = 0.0
    for i in range(k):
        for j in range(k):
            weight = ((i - j) ** 2) / ((k - 1) ** 2)
            numerator += weight * observed[i][j]
            expected = row_sums[i] * col_sums[j] / n
            denominator += weight * expected
    if denominator == 0:
        return 1.0 if numerator == 0 else 0.0
    return 1.0 - numerator / denominator


def interpret(qwk: float, bias: float, within1: float) -> dict:
    if qwk >= 0.8:
        verdict = "excellent"
    elif qwk >= 0.6:
        verdict = "good"
    elif qwk >= 0.4:
        verdict = "moderate"
    else:
        verdict = "poor"
    advice = []
    if qwk < 0.6:
        advice.append("Rubric anchors/örnekleri netleştir; aynı örneklerle judge'ı yeniden çalıştır.")
    if within1 < 0.8:
        advice.append("Komşu puanlarda (3 vs 4) ayrım zayıf: 3/4 çapalarını somutlaştır.")
    if bias > 0.25:
        advice.append(f"Judge insana göre {bias:+.2f} puan cömert; rubric'e 'kanıt yoksa 3' üst sınırı ekle.")
    elif bias < -0.25:
        advice.append(f"Judge insana göre {bias:+.2f} puan katı; 'eksik ama doğru' cevaplar için 4 çapasını gevşet.")
    return {"verdict": verdict, "bias": round(bias, 3), "advice": advice}


def compute_metrics(human: list[float], judge: list[float]) -> dict:
    bias = (sum(judge) / len(judge)) - (sum(human) / len(human)) if human else 0.0
    metrics = {
        "n": len(human),
        "qwk": round(quadratic_weighted_kappa(human, judge), 4),
        "spearman": round(spearman(human, judge), 4),
        "pearson": round(pearson(human, judge), 4),
        "mae": round(mean_absolute_error(human, judge), 4),
        "exact_rate": exact_agreement(human, judge),
        "within1_rate": within_one_agreement(human, judge),
        "human_mean": round(sum(human) / len(human), 3) if human else 0.0,
        "judge_mean": round(sum(judge) / len(judge), 3) if judge else 0.0,
    }
    metrics["interpretation"] = interpret(metrics["qwk"], bias, metrics["within1_rate"])
    return metrics
