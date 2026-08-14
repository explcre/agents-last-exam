# Kart Telemetry Extraction From Gameplay Video

Recover a racing game's internal counters from gameplay video alone.

A game engine knows exactly what happened in a race: how many item boxes each kart
drove through, how many times it spun out, how long it spent drifting. A viewer
watching the same race sees all of it happen and has to count. This task puts an
agent in the viewer's seat and grades it against the engine's own numbers.

## What the agent gets

Twenty-four recorded SuperTuxKart races, one file per track, at 960x540:

```
input/
  train/  12 races + labels.json    the engine's telemetry for these races
  test/   12 races                  same twelve tracks, raced again, unlabelled
```

Every race is the same setup: a chase camera locked to one hero kart (`tux`) for
the whole race, four laps, five AI opponents on the strongest difficulty. Races run
2 to 7 minutes; the corpus is about 108 minutes of video in total.

`train/` and `test/` cover **the same twelve tracks** and the file names match, but
they are different races with different routes and incidents. That pairing is
deliberate: it means the agent can calibrate a detector per track rather than
having to build one that generalises to scenery it has never seen.

## What it reports

For the hero kart in each `test/` race, into `output/predictions.json`:

| field | meaning | how it is visible |
|---|---|---|
| `items_collected` | item boxes the hero drove through | the pickups themselves; the HUD shows no held item |
| `spinouts` | times the hero spun out | a ring of stars around the kart |
| `skid_time` | seconds spent drifting, as a float | bright sparks from the rear wheels |

Bananas and bombs cause the same visible spin-out and are not reliably
distinguishable, so they are counted together, which is why `spinouts` is a single
number rather than two.

```json
{"hacienda": {"items_collected": 12, "spinouts": 3, "skid_time": 41.5}, "...": {}}
```

## How it is graded

Per quantity, a rank gate multiplied by an absolute accuracy:

```
score_d   = clamp(tau_d, 0, 1) * accuracy_d
tau_d     = concordant - discordant over the race pairs the truth can order
accuracy_d= mean over races of max(0, 1 - |pred - gt| / tol),  tol = max(1, 0.30*gt)
reward    = sum_d w_d * score_d / sum_d w_d          w = .40 items, .30 spin, .30 skid
```

Both halves are load-bearing, and each closes a hole the other leaves open:

- **Accuracy alone** would reward systematic under-counting. An extractor that sees
  eight of twenty pickups is wrong everywhere but consistently, and a pure
  closeness score gives it partial credit race after race.
- **Rank alone** is too forgiving in the other direction. That same extractor
  orders the twelve races almost perfectly. Measured on this corpus: an answer that
  ranks every race correctly but reports tenfold values scores **tau 1.00 and
  reward 0.000**.
- A **constant or random answer** has no rank agreement and scores **0.000**.

Ground truth is SuperTuxKart's profile-mode counter table, written by the engine
itself. Nothing is human-annotated, so there is no labelling noise to dispute.

## Difficulty, measured rather than asserted

The task author built an extractor and reports it as a floor. Thresholds were fitted
on the twelve labelled races, per-dimension gains least-squares fitted on the same
split, and the number below is the twelve races the fit never saw.

| detector | held-out reward |
|---|---|
| colour-sum mask, uncalibrated | 0.000 |
| measured colour rule + control band | 0.005 |
| measured colour rule + control band + affine calibration | **0.023** |

Its predictions ship as `data/author_baseline_predictions.json` and a test asserts
they still score below 0.10, so a later change to the metric cannot quietly move the
floor this difficulty claim rests on.

Per dimension, that baseline scores `skid_time` tau +0.32 accuracy 0.08, `spinouts`
tau +0.20 accuracy 0.25, and `items_collected` **no signal at all**. Item boxes are
not separable by colour statistics in a fixed region; they need real detection. The
30% tolerance is what does the work: rank agreement is cheap here and accuracy is
not.

**0.023 is a floor, not a ceiling.** It is one author, three iterations, five
hand-tuned thresholds, and it deliberately ignores the strongest lever the task
offers, which is that every test track appears in the labelled half. A correct
answer scores 1.000 through the same grader, so the target is reachable by
construction; what is unknown is how close an agent gets.

## Caveats worth stating

- The author's calibration harness is text-only, so it could not be used to measure
  an agent that *looks* at frames. Real ALE agents drive a VM with a screen. The
  baseline above is a programmatic floor, and it does not bound what a vision-capable
  agent can do by watching.
- `items_collected` carries the largest weight and is the hardest of the three. A
  submission that solves the two motion quantities perfectly and the pickups not at
  all caps at 0.60.
- Two hours of video on four vCPUs is a real time cost. The VM budget is six hours;
  decoding the corpus once at a reduced frame rate and caching features takes a
  small fraction of that, but decoding it repeatedly at full rate does not fit.
