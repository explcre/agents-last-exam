# Procedural Animation Extrapolation

Recover the rule behind an animation and carry it into frames nobody showed.

Three rigid bodies move under a procedural rule that is a pure function of the frame
number. The agent gets the bodies' rest meshes and the first sixty frames as
world-space vertex positions, and must build a Blender scene that reproduces frames 61
to 180, which it never sees.

## Why the held-out frames are the point

The 3D animation tasks already in the benchmark grade the same frames the agent was
shown, against a similarity threshold or a vision model's opinion. Reproducing what you
can see is a different problem from continuing it: an agent can match visible frames by
fitting them, and a fit does not have to be the rule.

Time is a natural axis to hold out, and it is unforgiving in a useful way. Measured on
this rig, an order-8 harmonic least squares fitted to the sixty published frames
reproduces them and then extrapolates to a maximum vertex error of 6.89, scoring zero.
Looping the window and holding its last frame are worse. Nothing that skips the rule
survives the boundary.

## What the agent gets

```
input/
  rest_meshes.json      each body's vertices in its own rest space, in grading order
  frames_001_060.json   frames 1..60, world-space vertex coordinates
```

## What has to be recovered

Two turn rates, a Lissajous path, a reach that breathes at a multiple of the arm's
spin, and a vertical clamp whose band is not centred on zero. Every one of those is
exercised inside the visible window, so nothing has to be guessed. That is a fairness
requirement, not a courtesy: a rule the published frames never show could not be
inferred, and the test suite checks each one is witnessed there.

Recovery has to be precise. A turn rate wrong by 0.05% moves a vertex by 2.6e-02, and
missing the breathing reach entirely scores 0.01.

## Grading

The submitted `rig.py` is imported inside Blender in background mode, `build()` is
called, and the scene is then stepped with `frame_set()` over the graded frames while
world-space vertices are read back from the evaluated depsgraph. A submission that
computes correct numbers without putting them under animation scores zero, because
`frame_set` never reaches them.

A frame counts as reproduced when its largest vertex deviation is at most `1e-05`, and
counts toward a smaller share of the reward when within `1e-02`.

The tolerance is measured, not chosen. Blender evaluates in single precision, so two
correct rigs built differently, one parented and one flat, drift apart by up to
9.9e-07; the smallest parameter error tried moves a vertex by 1.5e-04. Grading at
1e-05 sits an order of magnitude above the first and well below the second, and the
test suite fails if a later change moves it outside that band.

## Measured scores

| submission | reward |
| --- | --- |
| reference solution | 1.000 |
| clamp assumed symmetric | 0.617 |
| clamp missed entirely | 0.233 |
| turn rate wrong by 0.05% | 0.042 |
| breathing reach missed | 0.008 |
| harmonic fit of the visible window | 0.000 |
| bodies built but never animated | 0.000 |
| rig that raises on import | 0.000 |

The partial scores are proportional to how often the missed rule matters: the clamp
band is asymmetric on 43% of graded frames, so a rig that assumes symmetry is right on
the rest. A rig that recovered four rules of five should not score as though it
recovered none.
