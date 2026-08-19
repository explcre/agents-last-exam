"""Score reported kart telemetry: a rank gate multiplied by absolute accuracy.

The rank term only gates; the score is carried by how close each reported value is
to the engine's own counter. A constant or random answer has no rank agreement and
scores 0, and an answer that ranks every race correctly but reports values outside
the tolerance also scores 0.

Standard library only. No path in this module raises on a malformed or missing
submission: unparseable input scores 0.
"""

from __future__ import annotations

import math

# (field, weight). Weights follow the source project: pickups are the hardest
# quantity to witness and carry the most; the two motion quantities split the rest.
DIMS: tuple[tuple[str, float], ...] = (
    ("items_collected", 0.40),
    ("spinouts", 0.30),
    ("skid_time", 0.30),
)
TOL_FRAC = 0.30


def kendall(pred: list[float], gt: list[float]) -> float:
    """Normalised concordant-minus-discordant over the pairs the truth can order.

    Returns a value in [-1, 1]. Pairs tied in ``gt`` are excluded from the
    denominator, so an exact prediction scores 1.0 even though several races share
    a spin-out count. A pair ``gt`` orders but ``pred`` ties contributes to the
    denominator only, and so is penalised.
    """
    concordant = discordant = orderable = 0
    for i in range(len(pred)):
        for j in range(i + 1, len(pred)):
            if gt[i] == gt[j]:
                continue
            orderable += 1
            s = (pred[i] - pred[j]) * (gt[i] - gt[j])
            if s > 0:
                concordant += 1
            elif s < 0:
                discordant += 1
    return (concordant - discordant) / orderable if orderable else 0.0


def accuracy(pred: list[float], gt: list[float]) -> float:
    """Mean per-race closeness: full credit when exact, zero one tolerance away.

    The tolerance is 30% of the true value, floored at 1 so that races with a
    ground truth of 0 or 1 stay winnable rather than demanding a perfect hit.
    """
    total = 0.0
    for p, g in zip(pred, gt):
        tol = max(1.0, TOL_FRAC * abs(g))
        total += max(0.0, 1.0 - abs(p - g) / tol)
    return total / len(gt) if gt else 0.0


def _number(value) -> float:
    """Coerce a reported value to a float, treating anything unusable as absent."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    if not math.isfinite(value):  # NaN or infinity would poison the comparisons
        return 0.0
    return float(value)


def score(preds: dict, truth: dict) -> dict:
    """Score a prediction table against ground truth, per dimension and overall.

    ``preds`` maps race id to a mapping of field to number. Missing races, missing
    fields and junk values are all scored as 0 for that entry rather than raising.
    """
    ids = sorted(truth)
    report: dict = {"races": len(ids), "reported": 0}
    if isinstance(preds, dict):
        report["reported"] = sum(1 for i in ids if isinstance(preds.get(i), dict))
    else:
        preds = {}

    numerator = denominator = 0.0
    for field, weight in DIMS:
        gt = [float(truth[i][field]) for i in ids]
        if len(set(gt)) <= 1:
            # No spread means the dimension cannot be ranked; drop it and
            # renormalise so a correct extractor can still reach 1.0.
            report[field] = None
            continue
        pred = [_number(row.get(field) if isinstance(row := preds.get(i), dict) else None)
                for i in ids]
        tau = max(0.0, min(1.0, kendall(pred, gt)))
        acc = accuracy(pred, gt)
        report[field] = {"tau": tau, "accuracy": acc, "score": tau * acc}
        numerator += weight * tau * acc
        denominator += weight

    report["reward"] = max(0.0, numerator / denominator) if denominator else 0.0
    return report
