"""Scoring for computing_math/scheduling_model_recovery.

One integer is graded per held-out instance: the optimal makespan under the plant's
real model. An optimal objective value is unique even when the optimal schedule is
not, so a correct submission cannot be marked down for finding a different schedule
with the same cost, and solver nondeterminism cannot move the score.

There is no partial credit within an instance. A makespan is the right integer or it
is not, which is the point: the observable is one number, and it cannot be attributed
to any individual rule of the model behind it.
"""

from __future__ import annotations


def score(results, expected) -> dict:
    """Fraction of held-out instances whose optimal makespan is reproduced exactly.

    Never raises: anything missing, non-integer or unparseable counts as wrong.
    """
    if not isinstance(results, dict):
        results = {}
    exact, wrong, missing = 0, 0, 0
    for key, want in expected.items():
        got = results.get(key)
        if got is None:
            missing += 1
            continue
        if isinstance(got, bool) or not isinstance(got, (int, float)):
            wrong += 1
            continue
        if float(got) != float(want) or float(got) != int(got):
            wrong += 1
            continue
        exact += 1
    n = len(expected) or 1
    return {"instances": len(expected), "exact": exact, "wrong": wrong,
            "missing": missing, "reward": round(exact / n, 6)}
