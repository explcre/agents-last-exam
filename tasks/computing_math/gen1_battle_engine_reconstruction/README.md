# Battle Engine Reconstruction From Behaviour

Reimplementing a system whose specification is lost, from the behaviour of the
system itself, is an ordinary and expensive engineering job. This task is that,
made exactly checkable.

The agent is given a labelled corpus of battles from a deterministic Generation I
battle engine and **no rules at all**: no damage formula, no critical-hit rule, no
random-number consumption order, no turn order. It must write an engine that
reproduces held-out battles bit for bit.

Comparison is exact on both the protocol log and the final battle state. No
tolerance, no rubric, no model in the grading path.

## How grading works

![grading pipeline](docs/pipeline.svg)

**The reference binary is never staged.** That is deliberate, and it was the
decisive packaging choice. Shipping the oracle so the agent could probe it freely
is the more natural design and it is hackable: a submission can shell out to the
oracle, or embed all 276 KB of it in its own source, and score perfectly having
implemented nothing. Deleting the oracle before grading does not help, because
the submission can carry a copy. So the agent gets data, not a callable engine.

The cost of that choice is real: the agent cannot test a hypothesis against a
fresh input, only against the corpus it was given. That is the price of a corpus
that cannot be gamed, and it is a tradeoff rather than a free win.

## What is given, and what is withheld

| given | withheld |
|---|---|
| 186 scenarios: roll tape, starting state, both choices, protocol log, final state | every rule |
| `docs/protocol.json`: the names of every event the engine can emit | when any of them fire |
| `docs/layout.json`: byte offsets and sizes of the battle state | what changes any field |

The two documents are emitted by the engine's own `dump` tool, so the split
between format and rule is drawn by the upstream project rather than by us.

## Scoring

Two numbers, because they answer different questions.

- **full_pass**: every held-out scenario exact, or zero. An engine is bit-exact or
  it is not, and this is the headline.
- **mechanics**: mean over families of the fraction reproduced. One family is one
  move, so this reads as "how many of the 48 mechanics did it get right".

Measured through the same grader the benchmark uses:

| candidate | scenarios | mechanics | full pass | families flagged |
|---|---|---|---|---|
| reference engine | 140/140 | 1.000 | 1 | none |
| one localized bug | 135/140 | 0.965 | 0 | **Wrap 0.00, Pin Missile 0.33** |
| empty output | 0/140 | 0.000 | 0 | all 48 |

The last column is the point. The grader **names the broken mechanic** rather
than returning a scalar. A corpus of random full-length battles rated that same
build 0.542 and could say nothing about why.

## Design properties, each verified by a test

- **Every graded mechanic is demonstrated.** The corpus is split by roll tape
  within each family, never by family. A family-level split would grade mechanics
  the agent had never seen an example of, and a move-specific effect cannot be
  inferred from never observing it: that is unsolvable rather than hard.
- **Families are isolated by construction.** Each scenario is one Pokemon a side,
  so a faint ends the battle instead of handing the move script to a replacement.
  At six a side, 65% of scenarios leaked into a neighbouring family at cap 12, and
  no shorter cap fixed it.
- **No two families are indistinguishable.** A transcript shared across different
  families would mean two mechanics cannot be told apart. Measured: zero.
- **Nothing held out reaches the VM.** No graded scenario id, no graded
  transcript.

## Roster

48 moves chosen for structural distinctness rather than count, covering partial
trapping, lock-in, charge, multi-hit, high-crit, one-hit KO, recoil, drain,
self-KO, screens, Haze, Mist, Disable, Mimic, Conversion, Bide, Rage, Leech Seed,
fixed damage, Super Fang, all four status classes, and eight secondary-effect
chances: 47 of the engine's 68 move effects.

Twelve species cover all 15 Generation I types with base Speed from 30 to 140.
Speed matters because the critical-hit rate is derived from it, and only a
species at 128 or above reaches the clamp in that calculation.

Teams are synthetic. The engine does not enforce learnsets, and these movesets
are chosen for mechanical coverage, not legality.

## Reference provenance

Every transcript is produced by executing `pkmn/engine` (MIT) built in
cartridge-accurate mode at commit `78dc891`. No transcript is hand written. The
ground truth is precisely "whatever that pinned binary does": it is a well
defined, deterministic, reproducible authority, and it is not a claim of fidelity
to 1996 hardware. See [ATTRIBUTION.md](ATTRIBUTION.md).

No Nintendo code, no ROM, no game assets.

## Running it

```
uv run pytest tests/tasks/test_gen1_battle_engine_reconstruction.py
```

Self-contained: no baked image data, no task-data pull, no
`requiredSystemPackages`, no network. `start()` writes 1.3 MB of JSON inline.

To rebuild the corpus from source, see [NOTES.md](NOTES.md).

## Difficulty

Not yet measured against a reference agent, and not claimed. ALE runs difficulty
classification as one of its own review controls.

One measurement from the sibling task in this contribution is worth stating,
because it cuts against the obvious assumption: on
`computing_math/lockstep_desync_repro`, withholding the specification entirely
changed a strong agent's effort by roughly 7.5x in wall time and did not change
the outcome at all, which stayed at a perfect score. Absence of a specification
is therefore not by itself evidence that a task is hard. Whether the far larger
mechanical surface here behaves differently is an open question that a
calibration run, not an argument, has to settle.
