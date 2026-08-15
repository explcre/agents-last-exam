# kart_telemetry_extraction: maintainer notes

## Layout

```
data/
  train_labels.json                 written onto the VM by start()
  holdout_labels.json               never leaves the host
  author_baseline_predictions.json  the measured difficulty floor, guarded by a test
scripts/
  grade.py                          the metric; standard library only, never raises
```

The videos are **not** in this repository. They come from ALE's task-data store in
the canonical layout:

```
<task-data-root>/visual_media/kart_telemetry_extraction/base/input/
    train/<track>.mp4    12 files
    test/<track>.mp4     12 files
```

602 MB in total. `start()` writes `input/train/labels.json` and then asserts that
twelve videos landed in each split, so a staging failure raises instead of quietly
presenting the agent with an impossible task. That check exists because a missing
corpus and a very hard task produce the same score.

## Rebuilding the corpus

Recordings come from SuperTuxKart 1.5 profile mode; see `ATTRIBUTION.md` for the
exact invocation. From a directory of per-race `{race_raw.mp4, gt.json, track.txt,
hero.txt}`:

- keep races whose hero row has a non-null `skid_time` (one recorded suite lacked
  it and was dropped, taking the usable set from 32 races to 24);
- `spinouts = bananas_hit + times_exploded` from the hero row, matching the source
  project's scorer;
- encode `-vf scale=960:540 -c:v libx264 -preset veryfast -crf 32 -an`;
- name each file after `track.txt` so the train/test pairing is visible.

## Why the split is by track

Both recorded suites raced the same twelve tracks, so the obvious split is by suite.
That version shipped first and was wrong: a track raced twice yields similar
telemetry, so copying the labelled value for the matching track scored **0.257** with
no video decoded. The split is now by track. Each half holds six tracks, both races
of a track move together, and no track is both labelled and graded. The best no-video
submission is a constant, which the rank gate scores 0.

`kart_split.json` records the chosen tracks. The split was picked by enumerating all
924 six-track combinations and taking the one whose halves are most similar in mean
and spread across the three fields, subject to every field varying in both halves (a
field with no spread is dropped by the grader, which would silently reweight the
task).

## A metric defect the positive control caught

The first grader normalised Kendall's tau over *all* race pairs. Several races share
a spin-out count, and tied pairs sat in the denominator while contributing nothing
to the numerator, so **the exact ground truth scored below 1.0 as a submission**.
`test_exact_telemetry_scores_one` failed and named it immediately.

`kendall()` now excludes pairs the truth cannot order. A pair the truth *does* order
but the prediction ties still earns nothing, so this is not a loophole.

The defect was self-inflicted and worth recording as such. The scorer this metric
was ported from **already guards ground-truth ties** (`if dg == 0: continue`, and it
normalises by the orderable count). Its module docstring describes the metric as
"concordant-minus-discordant / pairs", and that prose, not the implementation, is
what got ported. Porting a summary of code instead of the code is how a correct
reference turns into a broken copy.

Two further defects surfaced the same way: a submission mapping a race to a string
crashed the grader with `AttributeError`, and the same tie handling capped the
rank-only control below tau 1.0 and made that test unreadable.

## What the tests actually constrain

Eleven checks. The ones that earn their place:

- `test_exact_telemetry_scores_one`: the positive control, which found the tie bug;
- `test_a_constant_answer_scores_about_zero` and
  `test_ranking_without_accuracy_earns_almost_nothing`: the two ways this metric
  could be farmed, both measured rather than argued;
- `test_start_fails_loudly_when_the_videos_are_missing`: a staging failure must not
  be gradeable;
- `test_malformed_submissions_score_zero_without_raising`: four junk shapes,
  because `evaluate()` must never raise on agent output;
- `test_the_author_baseline_is_reproduced_and_is_weak`: pins the difficulty floor
  so a metric change cannot silently move it.

No test in the suite decodes video; they stage empty files with the right names.
Staging against the real 602 MB corpus was validated separately and end to end,
including the positive control.

## Variants

`load()` returns `base` only. The natural variants are a track-disjoint split, a
subset of the three quantities, and a wider tolerance; all reuse this grader
unchanged.
