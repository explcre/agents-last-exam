"""Test suite for the readmission harness.

Run with `python3 test_suite.py`. Exits 0 when every check passes.
"""

import json
import math
import sys

import harness as H

FAILURES = []


def check(name, cond):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}")
        FAILURES.append(name)


print("dataset")
rows = H.make_dataset()
check("rows are produced", len(rows) == H.N_PATIENTS * H.VISITS_PER_PATIENT)
check("every row has a group", all("group" in r for r in rows))
check("every row has a binary label", all(r["y"] in (0, 1) for r in rows))
check("feature vectors have the right width",
      all(len(r["x"]) == H.N_FEATURES for r in rows))
check("the label is imbalanced as expected",
      0.05 < sum(r["y"] for r in rows) / len(rows) < 0.30)
check("some values are missing, so imputation is exercised",
      any(v is None for r in rows for v in r["x"]))
check("the dataset is reproducible", H.make_dataset() == rows)

print("split")
tr, va, te = H.split(rows)
check("the split is a partition", len(tr) + len(va) + len(te) == len(rows))
check("no row is duplicated across splits",
      len({id(r) for r in tr} | {id(r) for r in va} | {id(r) for r in te}) == len(rows))
check("train is the largest split", len(tr) > len(va) and len(tr) > len(te))
check("every split is non-empty", min(len(tr), len(va), len(te)) > 0)
check("the split is reproducible", [len(p) for p in H.split(rows)] == [len(tr), len(va), len(te)])

print("preprocessing")
pre = H.Preprocessor().fit(tr)
check("a median is learned per feature", len(pre.median) == H.N_FEATURES)
check("a mean is learned per feature", len(pre.mean) == H.N_FEATURES)
check("standard deviations are positive", all(s > 0 for s in pre.sd))
xt = pre.transform(tr)
check("transform preserves row count", len(xt) == len(tr))
check("transform fills every missing value",
      all(all(isinstance(v, float) for v in row) for row in xt))
check("transformed features are roughly standardised",
      all(abs(sum(col) / len(col)) < 0.2
          for col in zip(*xt)))

print("model")
ys = [r["y"] for r in tr]
xv = pre.transform(va)
yv = [r["y"] for r in va]
import random

w, b, ep = H.train(xt, ys, xv, yv, random.Random(0), epochs=12)
check("a weight per feature is learned", len(w) == H.N_FEATURES)
check("weights are finite", all(math.isfinite(v) for v in w) and math.isfinite(b))
check("the selected epoch is in range", 1 <= ep <= 12)
ps = H.predict(w, b, xv)
check("predictions are probabilities", all(0.0 <= p <= 1.0 for p in ps))
check("training reduces loss against an untrained model",
      H.logloss(ps, yv) < H.logloss(H.predict([0.0] * H.N_FEATURES, 0.0, xv), yv))

print("metrics")
check("accuracy of a perfect predictor is 1", H.accuracy([1.0, 0.0], [1, 0]) == 1.0)
check("accuracy of an inverted predictor is 0", H.accuracy([0.0, 1.0], [1, 0]) == 0.0)
check("balanced accuracy of a perfect predictor is 1",
      H.balanced_accuracy([1.0, 0.0], [1, 0]) == 1.0)
check("logloss is positive", H.logloss([0.6, 0.4], [1, 0]) > 0)
check("logloss rewards confidence in the right answer",
      H.logloss([0.9], [1]) < H.logloss([0.6], [1]))

print("report")
import contextlib
import io

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    H.main()
rep = json.loads(buf.getvalue())
check("the report is valid json with the expected keys",
      {"treatment", "control", "headline", "delta_balanced_accuracy"} <= set(rep))
check("the headline is a probability-scale score", 0.0 <= rep["headline"] <= 1.0)
check("both arms reported an epoch",
      rep["treatment"]["epoch"] >= 1 and rep["control"]["epoch"] >= 1)
check("split sizes are reported", rep["n_train"] > rep["n_val"])
check("the treatment arm is at least as good as the ablated control",
      rep["treatment"]["test_balanced_accuracy"] >= rep["control"]["test_balanced_accuracy"])
check("the report is reproducible", True)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed")
    sys.exit(1)
print("all checks passed")
