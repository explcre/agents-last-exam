"""Score a recovered pipeline against the reference pipeline's output tables.

A dataset counts only when the produced table matches the reference exactly as a
multiset of rows. Row-level F1 contributes a fifth of the score so that partial
progress is visible rather than collapsing to a flat zero, which matters here
because ten independent decisions all have to be right at once and a submission can
be close on nine of them.

Standard library only. No path raises on a missing or malformed result: an
unreadable output scores zero for that dataset.
"""

from __future__ import annotations

import collections
import csv
import io

EXACT_WEIGHT = 0.8


def read_rows(text: str) -> collections.Counter | None:
    """Parse a result CSV into a multiset of rows, or None if it is unusable.

    Rows are compared as a multiset rather than a set because a pipeline that
    duplicates a row is wrong in a way a set comparison would hide. The header is
    compared too: renaming a column is a real difference.
    """
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except (csv.Error, TypeError):
        return None
    if not rows:
        return None
    header = tuple(c.strip() for c in rows[0])
    body = [tuple(c.strip() for c in r) for r in rows[1:] if any(c.strip() for c in r)]
    if any(len(r) != len(header) for r in body):
        return None
    return collections.Counter([header] + body)


def f1(got: collections.Counter, want: collections.Counter) -> float:
    if not got and not want:
        return 1.0
    if not got or not want:
        return 0.0
    hit = sum((got & want).values())
    if not hit:
        return 0.0
    p, r = hit / sum(got.values()), hit / sum(want.values())
    return 2 * p * r / (p + r)


def score(produced: dict, expected: dict) -> dict:
    """``produced`` and ``expected`` map dataset name to result-CSV text."""
    names = sorted(expected)
    exact, f1s, per_case = 0, [], {}
    for name in names:
        want = read_rows(expected[name])
        got = read_rows(produced.get(name, "")) if isinstance(produced, dict) else None
        if want is None:
            raise RuntimeError(f"reference result for {name} is unreadable")
        if got is None:
            f1s.append(0.0)
            per_case[name] = {"exact": False, "f1": 0.0, "rows": 0, "note": "unreadable"}
            continue
        is_exact = got == want
        v = f1(got, want)
        exact += is_exact
        f1s.append(v)
        per_case[name] = {"exact": is_exact, "f1": round(v, 4),
                          "rows": max(0, sum(got.values()) - 1)}
    n = len(names)
    exact_frac = exact / n if n else 0.0
    mean_f1 = sum(f1s) / n if n else 0.0
    return {"cases": n, "exact": exact, "exact_fraction": exact_frac,
            "mean_f1": mean_f1, "per_case": per_case,
            "reward": max(0.0, EXACT_WEIGHT * exact_frac + (1 - EXACT_WEIGHT) * mean_f1)}
