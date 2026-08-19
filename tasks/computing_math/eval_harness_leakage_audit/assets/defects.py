"""The five defects planted in the harness the agent receives.

Each is a real evaluation-integrity failure that a passing test suite does not
catch, because each one leaves the pipeline running and the numbers plausible.
Every patch is a literal string replacement asserted to apply exactly once, so
the defective build provably differs from the reference in exactly these places.

  D1  preprocessing fitted on train and test together, so test statistics reach
      the model.
  D2  the split shuffles rows and cuts on a row index, scattering each patient
      across all three splits, so the model is scored on patients it trained on.
  D3  early stopping selects the epoch by test loss, so the reported number was
      chosen with knowledge of the set it is reported on.
  D4  the headline metric becomes plain accuracy, which a constant majority
      predictor wins on a 12% positive rate.
  D5  both arms draw from one shared generator, so the difference between them
      depends on the order they ran in rather than on the intervention.

The next two are deliberately harder to *demonstrate* than to find, because
that is where a strong agent was measured to be unreliable.

  D6  the preprocessor keeps the medians from an earlier fit, so refitting the
      same object on different data silently reuses stale statistics.
  D7  early stopping tracks the best epoch and then returns the final weights,
      so the reported epoch and the returned model are not the same thing.
"""

from __future__ import annotations

STARTER_HEADER = '''"""Readmission risk evaluation harness.

Grouped train/validation/test split, imputation and scaling, logistic regression
with early stopping, and a treatment/control comparison.

The accompanying test suite passes.
"""
'''

PATCHES: list[tuple[str, str, str]] = [
    (
        "D1",
        """    pre = Preprocessor().fit(rows_tr)""",
        """    pre = Preprocessor().fit(rows_tr + rows_te)""",
    ),
    (
        "D2",
        """    groups = sorted({r["group"] for r in rows})
    random.Random(seed).shuffle(groups)
    n = len(groups)
    tr = set(groups[: int(n * 0.6)])
    va = set(groups[int(n * 0.6): int(n * 0.8)])
    te = set(groups[int(n * 0.8):])
    pick = lambda s: [r for r in rows if r["group"] in s]
    return pick(tr), pick(va), pick(te)""",
        """    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    n = len(shuffled)
    return (shuffled[: int(n * 0.6)],
            shuffled[int(n * 0.6): int(n * 0.8)],
            shuffled[int(n * 0.8):])""",
    ),
    (
        "D3",
        """    w, b, ep = train(xs, ys, xv, yv, rng)""",
        """    w, b, ep = train(xs, ys, xt, yt, rng)""",
    ),
    (
        "D4",
        """        "headline": treatment["test_balanced_accuracy"],""",
        """        "headline": treatment["test_accuracy"],""",
    ),
    (
        "D5",
        """    rng = random.Random(arm_seed)""",
        """    rng = _SHARED_RNG""",
    ),
    (
        "D5b",
        """SEED = 20260812""",
        """SEED = 20260812

_SHARED_RNG = random.Random(SEED)""",
    ),
]

PATCHES += [
    (
        "D6",
        """        self.median = [_median(c) for c in cols]""",
        """        if not self.median:
            self.median = [_median(c) for c in cols]""",
    ),
    (
        "D7",
        """        if vl < best[0]:
            best = (vl, list(w), b, ep)
    return best[1], best[2], best[3]""",
        """        if vl < best[0]:
            best = (vl, list(w), b, ep)
    return w, b, best[3]""",
    ),
]

PATCHES += [
]

# The code patches above change behaviour. These replace the reference's
# explanatory docstrings, which otherwise state the correct behaviour in prose
# directly above the defective code and hand the agent all five answers.
DOC_PATCHES: list[tuple[str, str]] = [
    ("""    """ + '"""' + """Synthetic visits. Rows from one patient share a group id and a bias term.

    The per-patient bias is what makes a grouped split necessary: a random row
    split would let the model memorise a patient seen in training and be scored
    on that same patient in test.
    """ + '"""',
     """    """ + '"""' + """Generate the synthetic visit table.""" + '"""'),
    ("""    """ + '"""' + """Grouped split. A patient appears in exactly one of train, val or test.

    The shuffle is applied to the *groups*, never to the rows. Shuffling rows
    first and then cutting on a row index would scatter each patient across all
    three splits.
    """ + '"""',
     """    """ + '"""' + """Partition the rows into train, validation and test.""" + '"""'),
    ("""    """ + '"""' + """Median imputation then standardisation.

    Both are fitted on training rows only. Fitting on anything else lets test
    statistics reach the model.
    """ + '"""',
     """    """ + '"""' + """Median imputation then standardisation.""" + '"""'),
    ("""    """ + '"""' + """Logistic regression, mini-batch SGD, with early stopping.

    The epoch is selected by validation loss. Selecting it on test would report a
    number chosen with knowledge of the set it is reported on.

    Batches are reshuffled every epoch from the arm's own generator, so the fit
    depends on that generator and on nothing else.
    """ + '"""',
     """    """ + '"""' + """Logistic regression, mini-batch SGD, with early stopping.""" + '"""'),
    ("""    """ + '"""' + """Headline metric. Chosen because a constant predictor scores 0.5 on it.

    Plain accuracy is unusable as a headline here: the positive rate is around
    12%, so predicting the majority class always scores about 0.88 and looks
    excellent while being worthless.
    """ + '"""',
     """    """ + '"""' + """Mean of sensitivity and specificity.""" + '"""'),
    ("""    """ + '"""' + """One experimental arm.

    Each arm gets its own generator. Sharing one generator between arms makes
    the difference between them depend on the order they ran in, so the
    comparison stops measuring what it claims to.
    """ + '"""',
     """    """ + '"""' + """Run one experimental arm and report its metrics.""" + '"""'),
]


GROUPS: dict[str, tuple[str, ...]] = {
    "D1": ("D1",),
    "D2": ("D2",),
    "D3": ("D3",),
    "D4": ("D4",),
    "D5": ("D5", "D5b"),
    "D6": ("D6",),
    "D7": ("D7",),
}

DESCRIPTIONS = {
    "D1": "preprocessing fitted on train and test together",
    "D2": "split scatters each patient across all three splits",
    "D3": "early stopping selects the epoch on test",
    "D4": "headline metric is accuracy on an imbalanced label",
    "D5": "both arms share one random generator",
    "D6": "the preprocessor keeps medians from an earlier fit",
    "D7": "the returned model is not the selected epoch's model",
}


def apply(source: str, only: tuple[str, ...] | None = None) -> str:
    """Return ``source`` with the selected patches applied.

    Every selected patch must match exactly once, otherwise the reference has
    drifted away from the patch table and the build must fail rather than ship a
    harness that differs in unintended places.
    """
    out = source
    for pid, old, new in PATCHES:
        if only is not None and pid not in only:
            continue
        count = out.count(old)
        if count != 1:
            raise AssertionError(f"patch {pid}: expected exactly 1 match, found {count}")
        out = out.replace(old, new)
    return out


def make_starter(reference_source: str) -> str:
    """The build the agent receives: all five defects, reference docstring swapped."""
    body = apply(reference_source)
    for old, new in DOC_PATCHES:
        if body.count(old) != 1:
            raise AssertionError(f"doc patch matched {body.count(old)} times: {old[:60]!r}")
        body = body.replace(old, new)
    _head, sep, rest = body.partition('"""')
    if not sep:
        raise AssertionError("reference source has no module docstring to replace")
    _doc, sep2, tail = rest.partition('"""')
    if not sep2:
        raise AssertionError("reference module docstring is not terminated")
    return STARTER_HEADER + tail.lstrip("\n")
