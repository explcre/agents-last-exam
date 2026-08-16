# minecraft_excavation_procedure: maintainer notes

## Layout

```
assets/
  episode.js         the runner, shipped to the VM verbatim and used to build the corpus
  runner_README.md   how the agent invokes it
data/
  examples.json      40 worked worlds, written onto the VM
  holdout.json       16 graded worlds, never leaves the host
scripts/
  grade.py           the metric; standard library only, never raises
```

The reference procedure lives outside this directory, in the corpus builder on the
author's machine. It is deliberately not in the repository path that gets staged,
and a test asserts the string `reference_rule` appears nowhere on the VM.

One runner serves both roles. An earlier version had a `--reference` branch inside
`episode.js`, which put the literal string `require('./reference_rule.js')` on the
VM: not the rule itself, but a pointer to its existence. The branch is gone and the
reference is loaded by path like any other bot, so the file the agent reads is
byte-identical to the one that produced the ground truth.

## Rebuilding the corpus

```
node episode.js <seed> <port> <bot.js> <out.json>
```

Seeds 1000-1039 are the examples, 2000-2015 are graded. Six episodes run in parallel
on distinct ports; a whole rebuild takes a few minutes. Each episode starts its own
server, so a port left in TIME_WAIT is the usual cause of a failed run.

## What the environment forced

None of this design was chosen freely. Measured on `flying-squid` 1.12.0:

| operation | result |
|---|---|
| `bot.dig` | works, 81 of 81 cells from a standing position |
| `bot.placeBlock` | "blockUpdate did not fire"; 6 of 12 actions failed, deterministically |
| `/tp` | crashes the server, `ERR_OUT_OF_RANGE ... Received 88888888` |
| pathfinding | silently skips work when it cannot reach |
| ore and metal markers | will not break at all |
| wool markers | break instantly |

So: excavation only, no movement, arena sized to one standing position, wool
markers. Swapping ores for wool took an episode from 242 s and incomplete to 29 s and
complete. Protocol is pinned to 1.16.5; 1.20.1 crashes on `/give` and 1.20.2 fails
placement.

Two guards exist because of the above. The reference retries each dig once and
reports any cell it failed to clear, so a partial execution cannot be silently baked
into the ground truth; the corpus build asserts zero such reports. And every recorded
change is checked to be a change to `air`, since the procedure only ever removes.

## Choosing the metric

Three candidates, decided by measuring what each pays a bot that does no real work.

| metric | do nothing | dig everything |
|---|---|---|
| per-cell accuracy | ~0.5 | low |
| F1 over dug cells | 0.000 | **0.264** |
| **Jaccard over dug cells** | **0.000** | **0.183** |

Per-cell accuracy is disqualified because most of the arena is untouched by the
procedure anyway. F1 fixes that but rewards recall enough that digging everything
scores 0.53 on the partial half. Jaccard charges for every cell wrongly touched.

## Why v1 was replaced

The first version used a 7x7 arena, three marker types and one conditional
exception, and a strong agent scored **1.000 in 1100 s on its first attempt**. The
cause was structural: effects were independent and additive, so each rule could be
inferred alone from one before/after pair.

v2 makes the effects ordered and state-dependent, so a rule's outcome depends on
what earlier rules did, and widens the surface to eight marker types including a
suppressor, a global parity gate and a fixpoint closure. Examples went from 8 to 40:
the intent is a large hypothesis space, not scarce evidence.

## Variants

`load()` returns `base` only. Natural variants: a different rule set at the same
scale, a larger arena (untested beyond radius 4, which is what a standing bot
reaches), or showing only the final world so the initial layout must be recovered
too.
