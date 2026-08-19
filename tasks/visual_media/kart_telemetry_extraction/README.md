# Kart Telemetry Extraction From Gameplay Video

Recover a racing game's internal counters from gameplay video alone.

A game engine knows exactly what happened in a race: how many item boxes each kart
drove through, how many times it spun out, how long it spent drifting. A viewer
watching the same race sees all of it happen and has to count. This task puts an
agent in the viewer's seat and grades it against the engine's own numbers.

## What the agent gets

Twenty-four recorded SuperTuxKart races at 960x540:

```
input/
  train/  12 races + labels.json    the engine's telemetry for these races
  test/   12 races                  six different tracks, unlabelled
```

Every race is the same setup: a chase camera locked to one hero kart (`tux`) for
the whole race, four laps, five AI opponents on the strongest difficulty. Races run
2 to 7 minutes; the corpus is about 108 minutes of video in total.

Each half covers **six tracks, raced twice**, and **no track appears in both
halves**. A detector calibrated on the labelled races has to survive scenery,
lighting and layouts it has never seen labelled. The split is by track for a
measured reason, recorded under "A flaw this task shipped with" below.

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
{"lighthouse_a": {"items_collected": 12, "spinouts": 3, "skid_time": 41.5}, "...": {}}
```

Keys are race ids: the `test/` file name without its extension.

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

Every number here is measured through the shipped grader on the twelve held-out
races.

| submission | reward |
|---|---|
| exact telemetry | **1.000** |
| a constant answer, or the labelled half's mean | 0.000 |
| perfect ranking, values ten times too large | 0.000 |
| author's hand-built extractor | 0.011 |
| Codex CLI `gpt-5.6-sol` at `xhigh`, 51 min | **0.116** |

The author's extractor had its thresholds fitted on the twelve labelled races and
its per-dimension gains least-squares fitted on the same split. Per dimension it
scores `skid_time` tau +0.33 accuracy 0.05, `spinouts` tau +0.12 accuracy 0.18, and
`items_collected` **no signal at all**. Item boxes are not separable by colour
statistics in a fixed region; they need real detection.

Its predictions ship as `data/author_baseline_predictions.json` and a test pins them
below 0.10, so a later change to the metric cannot quietly move the floor this
difficulty claim rests on.

The agent run is text-only, so it measures the programmatic path: write detectors,
run them over the corpus, report counts. It decoded video (84 ffmpeg invocations)
and earned every point, since the no-video floor is 0.000. Per dimension it scores
`spinouts` tau +0.67 accuracy 0.33, `skid_time` tau +0.52 accuracy 0.32, and
`items_collected` tau 0.00: it systematically undercounts pickups on the busiest
tracks, reporting 4 where the engine counted 28.

**Neither number is a ceiling.** Ten times the author's extractor, and still under
an eighth of the way to exact. A vision-capable agent that watches rather than
writing detectors is not measured here at all.

## A flaw this task shipped with

The first version paired the halves by track: the same twelve tracks appeared in
both, raced twice. The stated rationale was that per-track calibration keeps the
ceiling reachable.

It also made the task partly solvable without watching anything. A track raced twice
yields similar telemetry, so **copying the labelled value for the matching track
scored 0.257 with no video decoded at all**, and on `skid_time` that copy was *more
accurate* (0.715) than the agent that had actually built detectors (0.647). The rank
gate did not catch it, because track identity genuinely correlates with the counts.

The split is now by track: six tracks in each half, both races of a track moving
together, no track labelled and graded. The best no-video submission is now a
constant, which scores 0.000. `test_copying_the_labelled_half_scores_near_zero`
holds the line.

The controls that existed at the time tested a constant answer and a rank-only
answer. Neither covers "copy the labelled half", which is the obvious exploit once
the halves share a key. A control has to be derived from the specific structure a
task hands the agent, not from a generic list.

## Caveats worth stating

- The author's calibration harness is text-only, so it could not be used to measure
  an agent that *looks* at frames. Real ALE agents drive a VM with a screen. The
  baseline above is a programmatic floor, and it does not bound what a vision-capable
  agent can do by watching.
- `items_collected` carries the largest weight and is the hardest of the three. A
  submission that solves the two motion quantities perfectly and the pickups not at
  all caps at 0.60.
- Each half holds six tracks raced twice, so the two races of a track share scenery.
  Measuring one well and inferring its twin is a legitimate strategy, not an exploit:
  neither race is labelled, so nothing can be copied from the labelled half.
- Two hours of video on four vCPUs is a real time cost. The VM budget is six hours;
  decoding the corpus once at a reduced frame rate and caching features takes a
  small fraction of that, but decoding it repeatedly at full rate does not fit.
