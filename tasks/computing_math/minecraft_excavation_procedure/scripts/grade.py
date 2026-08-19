"""Score a reproduced excavation procedure against the reference's world states.

Exactness carries the score: a held-out world counts only if every cell of the arena
matches, which is what reproducing a procedure means. Jaccard over the set of dug
cells contributes the remaining fifth so that progress is visible rather than
collapsing to a flat zero, and unlike per-cell accuracy it scores a bot that does
nothing at 0 rather than rewarding it for leaving an arena that is mostly untouched
anyway.

The weighting was set from measurement, not taste. At an even split a solver that
recovers most of the procedure and almost none of it exactly still scored 0.47-0.51,
because Jaccard is bounded below by the share of the cleared set any one rule
contributes and so stays near 0.88 whenever errors are local. At 0.8 the same
submissions score 0.23-0.28 while a bot that digs the whole arena falls to 0.07.

Standard library only. No path raises on a malformed or missing result.
"""

from __future__ import annotations

# Exactness carries the score; see the module docstring for how the split was set.
EXACT_WEIGHT = 0.8


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
            "reward": max(0.0, EXACT_WEIGHT * exact_frac + (1 - EXACT_WEIGHT) * mean_f1)}
