# eval_harness_leakage_audit: maintainer notes

Self-contained: standard library only, no baked image data, no task-data pull, no
`requiredSystemPackages`, no network. The pipeline runs in under a second, so the
whole grading pass is fast.

## Layout

```
assets/            build-time only, never staged onto the VM
  harness_reference.py  the correct pipeline; ground truth for the probes
  defects.py            the patch table: five code patches plus the docstring
                        replacements that strip the intent from the starter
  existing_tests.py     the 34-check suite shipped to the agent, which passes
                        on every build including the fully defective one
  oracle_suite.py       what a correct audit produces, used as the positive control
scripts/
  probes.py          black-box detectors, one per defect
  grade.py           two-half scoring, no sandbox dependency
```

There is no `data/`. The starter is generated from the reference at `start()`
time, so the two can never drift apart.

## Rebuilding and checking

```
uv run pytest tests/tasks/test_eval_harness_leakage_audit.py
uv run ruff check tasks/computing_math/eval_harness_leakage_audit
```

Nine checks, four of which encode properties that took a correction to get right:

- the shipped suite passes on the defective build (the premise of the task);
- the starter carries all five defects, so no probe passes on it;
- every probe detects its own defect and the reference passes all five;
- no giveaway prose reaches the VM.

## Why the docstrings are stripped

The code patches change behaviour but leave the reference's explanatory
docstrings in place. Unpatched, the starter says

    Grouped split. A patient appears in exactly one of train, val or test.
    The shuffle is applied to the *groups*, never to the rows.

directly above code that shuffles rows. All five answers sit in prose above the
defects. `defects.py` therefore also replaces six docstrings with neutral ones,
and the leak check in `start()` greps for a phrase that survives only in the
reference.

This is the same failure as shipping a normative specification, which the
calibration of `computing_math/lockstep_desync_repro` showed collapses that kind
of task into transcription: a strong agent scored 1.000 in 315 s with the
specification, and 1.000 again without it, so prose that states the intent is
worth a great deal more than prose that is merely absent.

## Probe independence

The probes are not fully independent. D1 and D3 are both detected by perturbing
the test set and observing whether the fitted model changes, so a harness that
still selects its epoch on test also fails the preprocessing probe. D5 trips both
for the same reason.

The cross-talk runs in the conservative direction: an agent that repairs one
defect but not another earns nothing for the first until the second is repaired
too. The score understates partial progress and never overstates it, and it stays
monotone because repairing a defect only ever adds passes. Documented rather than
engineered away, because the alternative is probes that inspect source, and
source inspection would score how a fix was phrased rather than whether it works.

## Scoring, and why it is halved

`fixes` alone would reward an agent that repairs the pipeline and cannot show it
did. `kills` alone would reward a suite of `assert False`. The gate, that the
suite must pass on a known-correct harness, closes the second hole; the halving
is what makes the first one visible. Measured:

| submission | fixes | kills | score |
|---|---|---|---|
| repaired and demonstrated | 1.00 | 1.00 | 1.000 |
| repaired, suite proves nothing | 1.00 | 0.00 | 0.500 |
| suite that always fails | 1.00 | 0.00 | 0.500 |
| changed nothing | 0.00 | 0.00 | 0.000 |

## A defect the build caught

The dataset's positive rate had drifted to 31% while every docstring still
claimed 12%, after the signal strength was raised to make early stopping trigger
at an interior epoch. One shipped check asserted a band the data no longer
satisfied, so the suite failed on the reference itself. Found by running the
shipped suite against the reference rather than assuming it passed. The rate is
now 12.25%, which matters because D4 is only a defect when the label is
imbalanced enough that a constant predictor wins on accuracy: it scores 0.86 here
against a balanced accuracy of 0.60.

## Variants

`load()` returns `base` only. A variant is a different defect subset or a
different dataset seed plus a rebuild; the probes and grader are unchanged.
