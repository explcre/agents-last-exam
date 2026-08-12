"""Readmission risk evaluation harness. The correct build.

A small, plausible tabular ML evaluation pipeline: grouped train/validation/test
split, imputation and scaling fitted on training data only, a logistic
regression trained with early stopping selected on validation, and a headline
metric that a degenerate constant predictor cannot win.

Standard library only, no numpy, so it runs anywhere the task does.

This file is the ground truth for the audit. The build the agent receives is this
file with the deviations in assets/defects.py applied.
"""

from __future__ import annotations

import json
import math
import random
import sys

N_PATIENTS = 240
VISITS_PER_PATIENT = 5
N_FEATURES = 8
POSITIVE_RATE = 0.12
EPOCHS = 140
LR = 0.20
BATCH = 32
SEED = 20260812


# --- data -------------------------------------------------------------------


def make_dataset(seed: int = SEED) -> list[dict]:
    """Synthetic visits. Rows from one patient share a group id and a bias term.

    The per-patient bias is what makes a grouped split necessary: a random row
    split would let the model memorise a patient seen in training and be scored
    on that same patient in test.
    """
    rng = random.Random(seed)
    rows = []
    for pid in range(N_PATIENTS):
        bias = rng.gauss(0.0, 1.4)
        for _ in range(VISITS_PER_PATIENT):
            x = [rng.gauss(0.0, 1.0) for _ in range(N_FEATURES)]
            logit = bias + 1.8 * x[0] - 1.3 * x[1] + 0.8 * x[2]
            p = 1.0 / (1.0 + math.exp(-(logit - 3.8)))
            y = 1 if rng.random() < p else 0
            # A single feature is missing sometimes, so imputation is required.
            if rng.random() < 0.15:
                x[3] = None
            rows.append({"group": pid, "x": x, "y": y})
    rng.shuffle(rows)
    return rows


def split(rows: list[dict], seed: int = SEED) -> tuple[list, list, list]:
    """Grouped split. A patient appears in exactly one of train, val or test.

    The shuffle is applied to the *groups*, never to the rows. Shuffling rows
    first and then cutting on a row index would scatter each patient across all
    three splits.
    """
    groups = sorted({r["group"] for r in rows})
    random.Random(seed).shuffle(groups)
    n = len(groups)
    tr = set(groups[: int(n * 0.6)])
    va = set(groups[int(n * 0.6): int(n * 0.8)])
    te = set(groups[int(n * 0.8):])
    pick = lambda s: [r for r in rows if r["group"] in s]
    return pick(tr), pick(va), pick(te)


# --- preprocessing ----------------------------------------------------------


class Preprocessor:
    """Median imputation then standardisation.

    Both are fitted on training rows only. Fitting on anything else lets test
    statistics reach the model.
    """

    def __init__(self) -> None:
        self.median: list[float] = []
        self.mean: list[float] = []
        self.sd: list[float] = []

    def fit(self, rows: list[dict]) -> Preprocessor:
        cols = [[r["x"][j] for r in rows if r["x"][j] is not None]
                for j in range(N_FEATURES)]
        self.median = [sorted(c)[len(c) // 2] if c else 0.0 for c in cols]
        filled = [[(r["x"][j] if r["x"][j] is not None else self.median[j])
                   for r in rows] for j in range(N_FEATURES)]
        self.mean = [sum(c) / len(c) for c in filled]
        self.sd = [max(1e-9, math.sqrt(sum((v - m) ** 2 for v in c) / len(c)))
                   for c, m in zip(filled, self.mean)]
        return self

    def transform(self, rows: list[dict]) -> list[list[float]]:
        out = []
        for r in rows:
            v = [(r["x"][j] if r["x"][j] is not None else self.median[j])
                 for j in range(N_FEATURES)]
            out.append([(v[j] - self.mean[j]) / self.sd[j] for j in range(N_FEATURES)])
        return out


# --- model ------------------------------------------------------------------


def _sigmoid(z: float) -> float:
    if z < -30:
        return 1e-13
    if z > 30:
        return 1.0 - 1e-13
    return 1.0 / (1.0 + math.exp(-z))


def train(xs, ys, xv, yv, rng, epochs: int = EPOCHS, lr: float = LR) -> tuple[list, float, int]:
    """Logistic regression, mini-batch SGD, with early stopping.

    The epoch is selected by validation loss. Selecting it on test would report a
    number chosen with knowledge of the set it is reported on.

    Batches are reshuffled every epoch from the arm's own generator, so the fit
    depends on that generator and on nothing else.
    """
    w = [0.0] * N_FEATURES
    b = 0.0
    best = (float("inf"), list(w), b, 0)
    idx = list(range(len(xs)))
    for ep in range(1, epochs + 1):
        rng.shuffle(idx)
        for start in range(0, len(idx), BATCH):
            batch = idx[start: start + BATCH]
            gw = [0.0] * N_FEATURES
            gb = 0.0
            for i in batch:
                x, y = xs[i], ys[i]
                d = _sigmoid(sum(wi * xi for wi, xi in zip(w, x)) + b) - y
                for j in range(N_FEATURES):
                    gw[j] += d * x[j]
                gb += d
            m = len(batch)
            w = [wi - lr * g / m for wi, g in zip(w, gw)]
            b -= lr * gb / m
        vl = logloss(predict(w, b, xv), yv)
        if vl < best[0]:
            best = (vl, list(w), b, ep)
    return best[1], best[2], best[3]


def predict(w, b, xs) -> list[float]:
    return [_sigmoid(sum(wi * xi for wi, xi in zip(w, x)) + b) for x in xs]


# --- metrics ----------------------------------------------------------------


def logloss(ps: list[float], ys: list[int]) -> float:
    return -sum(y * math.log(max(p, 1e-13)) + (1 - y) * math.log(max(1 - p, 1e-13))
                for p, y in zip(ps, ys)) / len(ys)


def accuracy(ps: list[float], ys: list[int]) -> float:
    return sum(1 for p, y in zip(ps, ys) if (p >= 0.5) == bool(y)) / len(ys)


def balanced_accuracy(ps: list[float], ys: list[int]) -> float:
    """Headline metric. Chosen because a constant predictor scores 0.5 on it.

    Plain accuracy is unusable as a headline here: the positive rate is around
    12%, so predicting the majority class always scores about 0.88 and looks
    excellent while being worthless.
    """
    tp = sum(1 for p, y in zip(ps, ys) if p >= 0.5 and y == 1)
    fn = sum(1 for p, y in zip(ps, ys) if p < 0.5 and y == 1)
    tn = sum(1 for p, y in zip(ps, ys) if p < 0.5 and y == 0)
    fp = sum(1 for p, y in zip(ps, ys) if p >= 0.5 and y == 0)
    sens = tp / max(1, tp + fn)
    spec = tn / max(1, tn + fp)
    return (sens + spec) / 2.0


# --- experiment -------------------------------------------------------------


def run_arm(rows_tr, rows_va, rows_te, arm_seed: int, drop_feature=None) -> dict:
    """One experimental arm.

    Each arm gets its own generator. Sharing one generator between arms makes
    the difference between them depend on the order they ran in, so the
    comparison stops measuring what it claims to.
    """
    rng = random.Random(arm_seed)
    pre = Preprocessor().fit(rows_tr)
    xs, ys = pre.transform(rows_tr), [r["y"] for r in rows_tr]
    xv, yv = pre.transform(rows_va), [r["y"] for r in rows_va]
    xt, yt = pre.transform(rows_te), [r["y"] for r in rows_te]

    if drop_feature is not None:
        zero = lambda m: [[0.0 if j == drop_feature else v for j, v in enumerate(r)] for r in m]
        xs, xv, xt = zero(xs), zero(xv), zero(xt)

    w, b, ep = train(xs, ys, xv, yv, rng)
    pt = predict(w, b, xt)
    return {
        "epoch": ep,
        "val_logloss": logloss(predict(w, b, xv), yv),
        "test_balanced_accuracy": balanced_accuracy(pt, yt),
        "test_accuracy": accuracy(pt, yt),
        "test_logloss": logloss(pt, yt),
    }


def main() -> int:
    rows = make_dataset()
    tr, va, te = split(rows)
    treatment = run_arm(tr, va, te, arm_seed=1)
    # Control ablates the most predictive feature, so the delta means something.
    control = run_arm(tr, va, te, arm_seed=2, drop_feature=0)
    report = {
        "n_train": len(tr), "n_val": len(va), "n_test": len(te),
        "treatment": treatment,
        "control": control,
        "headline": treatment["test_balanced_accuracy"],
        "delta_balanced_accuracy": (treatment["test_balanced_accuracy"]
                                    - control["test_balanced_accuracy"]),
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
