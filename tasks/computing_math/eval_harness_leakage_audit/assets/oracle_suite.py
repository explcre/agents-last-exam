"""Oracle test suite: what a correct audit should produce. Used as a control."""
import sys

import harness as H


def check(name, cond):
    if not cond:
        print("FAIL:", name); sys.exit(1)

rows = H.make_dataset()
tr, va, te = H.split(rows)

# D2: a patient must not appear in more than one split
g = [{r["group"] for r in p} for p in (tr, va, te)]
check("groups span splits", not (g[0] & g[1] or g[0] & g[2] or g[1] & g[2]))

# D1: the fitted model must not change when only the test set changes
shifted = [dict(r, x=[(None if v is None else v + 5.0) for v in r["x"]]) for r in te]
a = H.run_arm(tr, va, te, arm_seed=1)
b = H.run_arm(tr, va, shifted, arm_seed=1)
check("preprocessing sees test", abs(a["val_logloss"] - b["val_logloss"]) < 1e-12)

# D3: the selected epoch must not change when only test labels change
flipped = [dict(r, y=1 - r["y"]) for r in te]
check("epoch selected on test",
      H.run_arm(tr, va, te, arm_seed=1)["epoch"] == H.run_arm(tr, va, flipped, arm_seed=1)["epoch"])

# D4: a constant predictor must not win the published headline
import contextlib
import io
import json

real = H.predict
H.predict = lambda w, b, xs: [0.0] * len(xs)
try:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        H.main()
    rep = json.loads(buf.getvalue())
    check("constant predictor wins the headline", rep["headline"] <= 0.55)
finally:
    H.predict = real

# D5: arm results must not depend on the order the arms ran in
a1 = H.run_arm(tr, va, te, arm_seed=1)
_ = H.run_arm(tr, va, te, arm_seed=2, drop_feature=0)
a2 = H.run_arm(tr, va, te, arm_seed=1)
check("arms share a generator", a1 == a2)

print("all checks passed")
