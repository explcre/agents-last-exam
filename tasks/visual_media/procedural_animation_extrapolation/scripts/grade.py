"""Scoring for visual_media/procedural_animation_extrapolation.

A graded frame counts as reproduced when every one of its vertices sits within
``EXACT_TOL`` of the reference. The tolerance is measured rather than chosen: Blender
evaluates in single precision, so two correct rigs built differently drift apart by up
to 9.9e-07, while the smallest parameter error tried here moves a vertex by 1.5e-04.
1e-05 sits an order of magnitude above the first and well below the second.

``LOOSE_TOL`` carries a minority of the reward so that a rig which recovered the
structure but missed a parameter is distinguishable from one that recovered nothing.
"""

from __future__ import annotations

EXACT_TOL = 1e-5
LOOSE_TOL = 1e-2
EXACT_WEIGHT = 0.8


def frame_error(got, want) -> float | None:
    """Largest absolute vertex deviation, or None if the frame is unusable."""
    if not isinstance(got, (list, tuple)) or len(got) != len(want):
        return None
    worst = 0.0
    for a, b in zip(got, want):
        if not isinstance(a, (int, float)) or a != a:
            return None
        d = abs(float(a) - b)
        if d > worst:
            worst = d
    return worst


def score(results, expected) -> dict:
    """Fraction of graded frames reproduced. Never raises on a malformed submission."""
    exact = loose = 0
    errors = {}
    if not isinstance(results, dict):
        results = {}
    for key, want in expected.items():
        err = frame_error(results.get(key), want)
        errors[key] = err
        if err is None:
            continue
        if err <= EXACT_TOL:
            exact += 1
        if err <= LOOSE_TOL:
            loose += 1
    n = len(expected) or 1
    reward = EXACT_WEIGHT * (exact / n) + (1.0 - EXACT_WEIGHT) * (loose / n)
    finite = [e for e in errors.values() if e is not None]
    return {"frames": len(expected), "exact": exact, "loose": loose,
            "worst_error": max(finite) if finite else None,
            "reward": round(reward, 6)}
