"""Black-box probes, one per planted defect.

Each probe loads a harness module and checks a property that the correct
pipeline has and a defective one does not. Nothing inspects source, so a
submission is judged on behaviour rather than on whether it happened to phrase a
fix the way the reference does.

A probe returns True when the property holds, meaning the defect is absent.
"""

from __future__ import annotations

import importlib.util
import pathlib
import random
import types


def load(path: str | pathlib.Path, name: str = "harness_under_test") -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fit(h, tr, va, te, seed=1):
    """Train one arm and return the weights, bias and selected epoch."""
    rng = random.Random(seed)
    pre = h.Preprocessor().fit(tr)
    xs, ys = pre.transform(tr), [r["y"] for r in tr]
    xv, yv = pre.transform(va), [r["y"] for r in va]
    return h.train(xs, ys, xv, yv, rng)


def probe_d1_preprocessing_ignores_test(h) -> bool:
    """The fitted model must not change when only the test set changes.

    Preprocessing fitted on train and test together makes the model a function of
    the test set, which this detects without looking at any source.
    """
    rows = h.make_dataset()
    tr, va, te = h.split(rows)
    other = [dict(r, x=[(None if v is None else v + 5.0) for v in r["x"]]) for r in te]
    a = h.run_arm(tr, va, te, arm_seed=1)
    b = h.run_arm(tr, va, other, arm_seed=1)
    return a["epoch"] == b["epoch"] and abs(a["val_logloss"] - b["val_logloss"]) < 1e-12


def probe_d2_groups_do_not_span_splits(h) -> bool:
    rows = h.make_dataset()
    tr, va, te = h.split(rows)
    g = [{r["group"] for r in part} for part in (tr, va, te)]
    return not (g[0] & g[1] or g[0] & g[2] or g[1] & g[2])


def probe_d3_epoch_selected_on_validation(h) -> bool:
    """The selected epoch must not change when only the test set changes."""
    rows = h.make_dataset()
    tr, va, te = h.split(rows)
    other = [dict(r, y=1 - r["y"]) for r in te]
    return h.run_arm(tr, va, te, arm_seed=1)["epoch"] == \
        h.run_arm(tr, va, other, arm_seed=1)["epoch"]


def probe_d4_headline_beats_a_constant_predictor(h) -> bool:
    """A predictor that always says "no" must not win the harness's headline.

    Behavioural, not structural: the model is forced to emit a constant, the
    harness builds its own report, and the number it publishes as the headline is
    read back. A submission that renames the metric is still judged on what it
    publishes.
    """
    rows = h.make_dataset()
    tr, va, te = h.split(rows)
    ys = [r["y"] for r in te]
    if not (0.02 < sum(ys) / len(ys) < 0.45):
        return False
    real_predict = h.predict
    h.predict = lambda w, b, xs: [0.0] * len(xs)
    try:
        report = h.run_arm(tr, va, te, arm_seed=1)
        headline_key = _headline_key(h)
        score = report.get(headline_key)
    finally:
        h.predict = real_predict
    return score is not None and score <= 0.55


def _headline_key(h) -> str:
    """Which per-arm field the harness publishes as its headline."""
    import contextlib
    import io
    import json
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        h.main()
    rep = json.loads(buf.getvalue())
    for k, v in rep["treatment"].items():
        if v == rep["headline"]:
            return k
    return "test_balanced_accuracy"


def probe_d5_arms_are_independent(h) -> bool:
    """Swapping the order the arms run in must not change either arm's result."""
    rows = h.make_dataset()
    tr, va, te = h.split(rows)
    a1 = h.run_arm(tr, va, te, arm_seed=1)
    b1 = h.run_arm(tr, va, te, arm_seed=2, drop_feature=0)
    b2 = h.run_arm(tr, va, te, arm_seed=2, drop_feature=0)
    a2 = h.run_arm(tr, va, te, arm_seed=1)
    return a1 == a2 and b1 == b2


PROBES = {
    "D1": probe_d1_preprocessing_ignores_test,
    "D2": probe_d2_groups_do_not_span_splits,
    "D3": probe_d3_epoch_selected_on_validation,
    "D4": probe_d4_headline_beats_a_constant_predictor,
    "D5": probe_d5_arms_are_independent,
}


def run_all(path: str | pathlib.Path) -> dict[str, bool]:
    """Run every probe. A probe that raises counts as a failure, not an error."""
    out = {}
    for pid, fn in PROBES.items():
        try:
            out[pid] = bool(fn(load(path, f"hut_{pid}")))
        except Exception:  # noqa: BLE001 - a harness that crashes has the defect
            out[pid] = False
    return out
