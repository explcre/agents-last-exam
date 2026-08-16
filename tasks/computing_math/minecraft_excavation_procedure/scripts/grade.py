"""Score a reproduced excavation procedure against the reference's world states.

Two halves. Exactness is the headline: a held-out world counts only if every cell of
the arena matches. Jaccard over the set of dug cells supplies partial credit and,
unlike per-cell accuracy, scores a bot that does nothing at 0 rather than rewarding
it for leaving an arena that is mostly untouched anyway.

Standard library only. No path raises on a malformed or missing result.
"""

from __future__ import annotations


def dug(before: dict, after: dict) -> set:
    """Cells the run turned to air. The procedure only ever removes blocks."""
    return {k for k, v in before.items() if v != "air" and after.get(k) == "air"}


def overlap(pred: set, truth: set) -> float:
    """Jaccard over the dug cells.

    Chosen over F1 because F1 rewards recall enough that a bot which simply digs the
    entire arena scores 0.53 on it, and so 0.26 overall, for no work. Jaccard charges
    that bot for every cell it should not have touched.
    """
    if not pred and not truth:
        return 1.0
    union = pred | truth
    return len(pred & truth) / len(union) if union else 1.0


def score(results: dict, expected: dict) -> dict:
    """``results`` maps seed to {"before":…, "after":…}; ``expected`` is the reference."""
    seeds = sorted(expected)
    exact, f1s, per_seed = 0, [], {}
    for s in seeds:
        ref = expected[s]
        got = results.get(s) if isinstance(results, dict) else None
        if not isinstance(got, dict) or not isinstance(got.get("after"), dict):
            f1s.append(0.0)
            per_seed[s] = {"exact": False, "overlap": 0.0, "error": "no result"}
            continue
        is_exact = got["after"] == ref["after"]
        v = overlap(dug(ref["before"], got["after"]), dug(ref["before"], ref["after"]))
        exact += is_exact
        f1s.append(v)
        per_seed[s] = {"exact": is_exact, "overlap": round(v, 4), "error": got.get("err")}
    n = len(seeds)
    exact_frac = exact / n if n else 0.0
    mean_f1 = sum(f1s) / n if n else 0.0
    return {"seeds": n, "exact": exact, "exact_fraction": exact_frac,
            "mean_overlap": mean_f1, "per_seed": per_seed,
            "reward": max(0.0, 0.5 * exact_frac + 0.5 * mean_f1)}
