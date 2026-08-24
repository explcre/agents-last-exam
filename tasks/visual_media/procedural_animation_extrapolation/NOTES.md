# Build notes

What was measured while building this task, including the things that did not work.

## Blender is bit-reproducible, and stable across versions

Evaluating the same rig twice gives identical vertex arrays. Blender 4.5.12 LTS and
5.0.1 produce byte-identical output for this pipeline, and meshes built from explicit
vertex coordinates match ones built from primitives exactly. Exact grading is therefore
safe, provided the pipeline stays inside transforms and avoids primitives, modifiers
and solvers, which is why the rest meshes ship as explicit coordinates.

## Chaos would compound, and would also be unfair

The first design idea was to make errors compound so that a near-miss diverged over
time. Chaotic systems do that, but they punish correct submissions just as hard.
Measured on a logistic map at a = 3.90, over frames 61 to 180:

| system | wrong parameter | same maths, different float order |
| --- | --- | --- |
| logistic a = 3.90 | 8.6e-01 | 8.7e-01 |
| logistic a = 3.57 | 1.2e-02 | 4.5e-13 |
| rotation with normalisation | 6.4e-03 | 0.0 |

At a = 3.90 the float-reordering noise a correct reimplementation cannot avoid is as
large as the error from getting the parameter wrong. That design was dropped.

A stable recurrence has the opposite problem: at a = 1.9 the map contracts, so errors
die rather than grow and the ratio between the visible and graded windows is 1.0.
"Recurrence implies compounding" is simply false.

## So the difficulty is the hypothesis space, not amplification

Closed-form drivers compound only about threefold from the visible window to the graded
one, and only for frequency-like parameters. Phase and amplitude errors are flat or
shrinking, which makes sense: they are equally visible at frame 1, so they can be fitted
from the published frames, and fairly so.

What survives the boundary is not amplification but structure. The published window does
not span a whole number of periods, so a curve fitted to it does not continue correctly,
and the rule has to be recovered instead.

## The tolerance came from a measurement that nearly went wrong

The pure-Python reference and Blender disagreed by 5.8e-07, six orders of magnitude
above the expected float noise, because Blender stores vertices and matrices in single
precision. The originally planned 1e-06 tolerance was sitting on the noise floor.

Rebuilding the same correct animation four ways gives the honest spread:

| correct implementation | drift from the flat rig |
| --- | --- |
| keyframed | 0.0 |
| direct matrix_world | 7.2e-07 |
| parented hierarchy | 9.9e-07 |

against wrong rigs at 1.5e-04 and up. 1e-05 sits an order of magnitude above the
worst honest drift and well below the smallest real error, and a test guards the band.

## Blender in the benchmark is Windows-only

Every existing Blender task requires `blender-5.0.1`, which is a Windows MSI package,
and that package's own description notes the character-reconstruction eval rejects
4.5.x. Version sensitivity is a known hazard here. This task ships a Linux package
under a distinct id, `blender-5.0.1-linux`, pinning the same version by checksum, so it
can be built and graded on the CPU Ubuntu image and was tested end to end there.

## Calibration: this is an easy task, and that is the finding

Codex CLI `gpt-5.6-sol`, staged through the task's real `start()` and graded by its real
`evaluate()`:

| run | effort | elapsed | score |
| --- | --- | --- | --- |
| run1 | xhigh | 577 s | **1.000** |
| run2 | low | 368 s | **1.000** |

Low effort was faster than xhigh. Both runs recovered every constant exactly, including
the composed ones (0.264 = 0.073 + 0.191, 0.573 = 3 x 0.191) and the asymmetric clamp,
and both wrote Blender drivers rather than baking keyframes, which is more idiomatic
than the reference solution in `assets/`.

The design premise held and was still not enough. The held-out axis worked exactly as a
verifier boundary: every shortcut that skips the rule scores 0.000. What made it easy is
that the observable decomposes. World-space vertices give per-body rigid pose by SVD, and
the first run reported its own fit residual at 1.4e-07; from there each parameter reads
off its own channel.

That is the fifth difficulty lever measured and falsified while building these tasks,
after withholding a specification, statefulness, entanglement and starving the feedback.
Hiding a rule, adding state, entangling the encoding and holding out an axis are effort
levers. Non-decomposability is the difficulty lever.
