# computing_math/lockstep_desync_repro: maintainer notes

Self-contained: no baked image data, no GCS pull, no `requiredSystemPackages`,
no network. `start()` writes every visible file; `evaluate()` pushes the held-out
replays only after the agent has finished and compares host side. Runs on
`cpu-free-ubuntu` under any provider, including the Docker one.

## Layout

```
assets/            build-time only, never staged onto the VM
  sim_reference.py   the normative simulator; source of every expected hash
  SPEC.md            the normative rules, staged to input/SPEC.md
  bugs.py            the patch table that turns the reference into the starter
  replaygen.py       scripted policy that records replays
  build_data.py      builds data/ and asserts the invariants
  diagnose.py        per-deviation first-divergence measurement
  controls.py        oracle / negative / ablation / ladder controls
data/              generated, committed
  starter/sim.py           staged to input/starter/sim.py
  visible/                 staged to input/replays/
  reference/               held-out replays and hidden hashes, host side only
                           (the oracle is assets/sim_reference.py, not a copy)
scripts/
  grade.py           host-side scoring, no sandbox dependency
  eval_runner.py     staged to the VM at eval time, runs the submission
```

## Rebuilding

```
cd assets
python3 build_data.py     # ~2 min; rewrites data/, asserts the invariants
python3 controls.py       # ~4 min; oracle 1.000, every shortcut 0.000
python3 diagnose.py 8     # ~6 min; per-deviation first-divergence ticks
```

`build_data.py` refuses to ship if any of these fail:

- a patch in `bugs.py` matches other than exactly once, which would mean the
  starter differs from the reference somewhere unintended;
- a replay does not reproduce its own recording open loop, which would mean the
  recording policy leaked into the simulation RNG;
- the unmodified starter passes the visible gate, which would give the task a
  do-nothing floor.

From `../../../..` (repo root):

```
uv run pytest tests/tasks/test_lockstep_desync_repro.py
uv run ruff check tasks/computing_math/lockstep_desync_repro
```

The pytest file drives the real `start()` and `evaluate()` against a local
session that runs bash and keeps files on disk, so staging, the leak check, the
on-VM runner and the grader are all exercised without a VM.

## The five deviations

Measured first-divergence tick, over all eight shipped replays. Every deviation
fires in 8 of 8.

| id | class | earliest | latest |
|---|---|---|---|
| B1 | division rounds by flooring instead of truncating toward zero | 1150 | 2025 |
| B5 | effect expiry runs after the attack phase instead of before it | 1500 | 2375 |
| B3 | crit draw is skipped when the cached target already died this tick | 1725 | 2225 |
| B2 | target acquisition walks the lane container in storage order | 2625 | 3500 |
| B4 | the team damage scoreboard never wraps to 32 bits | 7575 | 8675 |

B1 needs a negative operand with a remainder, which only happens once stacked
armor shred drives an entity's armor negative. B4 needs the scoreboard to pass
2^31, which happens near the end of a match. Neither is reachable by inspection
of the opening minutes.

## Two design decisions worth knowing

**The gate uses unpublished ticks.** The three visible replays are re-run at
eval time on `GATE_CHECKPOINTS`, which appear in no shipped file. Memorising
`expected_*.json` therefore fails the gate rather than passing it, and that
shortcut is a standing row in `controls.py`.

**The gate covers the first 44% of a match.** Four deviations diverge by tick
3500 and the fifth no earlier than 7575, so the gate certifies the opening of
every visible match while the held-out score measures how far into a match the
repair holds. Without that split the task was all-or-nothing: a submission with
four of five desyncs repaired scored 0 rather than 0.825.

## Two defects the build caught

Both are recorded because each was invisible to inspection and only a
measurement found it.

1. **Two deviations were unobservable.** B3 could never fire, because deaths
   resolve after the attack phase, so a target reduced to 0 hp was still flagged
   alive and the two code paths agreed. B4 could never fire either, because the
   state hash serialises each field as its low 32 bits, which makes a wrapped and
   an unwrapped accumulator produce identical bytes. The rules now make the
   wasted-attack condition non-positive hp, and route the scoreboard through a
   gameplay modifier so its wraparound changes play rather than only width.
   Found by `diagnose.py`, which reported both as "never".

2. **The published trace leaked the gate.** `trace_0.txt` carries a hash every
   25 ticks and the gate ticks were all multiples of 25, so one replay's gate was
   answerable by lookup. Found by the leak assertion in
   `tests/tasks/test_lockstep_desync_repro.py`, not by review.

## Variants

`load()` returns the `base` variant only. Additional variants are cheap: a
variant is a `(seed, policy_seed)` pair in `diagnose.SEEDS` plus a rebuild, and
the deviations, spec and grader are unchanged. The generator space is unbounded,
so held-out replays can be reminted if a set ever leaks.
