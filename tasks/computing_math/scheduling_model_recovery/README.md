# Scheduling Model Recovery

Rebuild a plant's scheduling model from the only thing its retired planner left behind.

A contract manufacturer is replacing a production planner nobody has the source for.
All that survives is a log: for each historical run, the shop-floor data the planner was
given and the makespan it achieved, which was always optimal for its model. The agent
rebuilds that model in CP-SAT and predicts the optimal makespan for runs it has not seen.

This is what actually happens when a legacy planning system is replaced. The vendor is
gone, the model was never written down, and the only specification anyone has is a
history of decisions.

## Why the observable is one integer

Six tasks built before this one were solved completely by a frontier agent, and the
reason was always the same: the observable could be taken apart. A byte-exact codec ships
the whole output stream, so an agent diffs its way to the error. A pipeline ships
row-level tables, so a wrong row names the rule that produced it.

A makespan is a global optimum. It cannot be attributed to any individual rule, because
changing one rule changes which schedule is optimal and therefore how every other rule
shows up. There is no intermediate to diff against and no way to isolate one mechanic at
a time.

## What has to be recovered

| rule | what it does |
| --- | --- |
| speed scaling | a duration at machine `m` is `ceil(duration * speed[m] / 100)` |
| cooling lag | a job waits `ceil(previous duration / 4)` after each operation |
| transport | moving a job between machines costs `transport[a][b]` |
| changeover | `setup[m][a][b]` between consecutive ops on a machine, and before its first, from family 0 |
| technician | every changeover needs one of a **single** technician, shared across all machines |
| maintenance | operations may not overlap a maintenance window at all |

Every field an instance carries is read by the model, and every rule is demonstrated in
the worked runs, so nothing has to be guessed. A rule that turned out not to change any
makespan was removed rather than shipped: see `NOTES.md`.

## Grading

`output/scheduler.py` exposes `optimal_makespan(run) -> int`. The reward is the fraction
of held-out runs whose optimal makespan is reproduced exactly, with no partial credit
within a run.

An optimal objective value is unique even when the optimal schedule is not, so a correct
submission is never marked down for finding a different schedule of the same cost, and
solver nondeterminism cannot move the score. Everything is integer arithmetic, so there
is no tolerance to tune and no floating-point fairness trap.

## Measured

| submission | reward |
| --- | --- |
| reference model | **1.000** (25/25, 6.5 s) |
| naive flexible job shop, none of the plant's rules | 0.000 |
| constant answer | < 0.15 |
| copying makespans out of the log | < 0.15 |
| the plant's model with any single rule wrong | 0.000 to 0.36 |

The graded runs were chosen to be discriminating: every rule changes the makespan of at
least 16 of the 25, so a model that is nearly right cannot coast. On a set chosen without
that care, one wrong-lag model scored 0.95.

## Calibrated

Two runs of Codex CLI `gpt-5.6-sol` at `xhigh` scored **0.08** and **0.04**, each after
about 80 to 90 minutes and half a million tokens. Both produced working CP-SAT models
that proved optimality on every graded run; neither recovered the plant's model, and
both missed the cooling lag. In the first run that was the only rule missed, and the
task's own discrimination table had predicted that score, 1 - 23/25 = 0.08, before the
run happened.

The first run also solved all 60 worked runs optimally and reproduced only 33 of them:
it could not fit even the log it was given. `NOTES.md` has the detail.

**The answer is determined, not ambiguous.** All 2304 models in the plausible rule grid
were solved against the worked log, and exactly one reproduces it: the true model.
