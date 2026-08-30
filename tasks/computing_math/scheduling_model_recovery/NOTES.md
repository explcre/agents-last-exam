# Build notes

What was measured while building this task, including what had to be thrown away.

## The task exists because of a measured law

Five difficulty levers were tried and falsified across earlier tasks: withholding a
specification, statefulness, entanglement, starving the feedback, and holding out an
axis the agent was never shown. Each bought effort, not difficulty; a frontier agent
solved every one of those tasks completely.

What survived is narrower. **An agent given worked examples over a decomposable
observable will take the observable apart.** A byte-exact codec ships the whole output
stream, so the agent diffs. A pipeline ships row-level tables, so a wrong row names its
own rule. This task was designed backwards from that finding: the observable is one
integer per run, and a makespan is a global optimum, so it cannot be attributed to any
single rule.

## A rule that changed nothing was removed

"The release date applies to every operation rather than only the first" was in the
first draft of the model. Measured against 40 instances, it changed **0** makespans:
job precedence already forces later operations past the release. A rule with no
observable effect is not difficulty, it is a trap, so it was deleted rather than shipped.

## Two more rules were nearly dead, and the generator was retuned

On the first corpus, transport changed 2 of 40 makespans and the technician limit
changed 1 of 40. A rule that thin is close to free marks. Widening machine eligibility,
raising setup and transport magnitudes and tightening the crew to a single technician
moved the crew to 36 of 40. Transport stayed the weakest rule and is handled by
selection instead.

## Instance selection matters more than instance size

The first instinct was to make instances bigger so more rules bind at once. Bigger
instances cost solve time the agent also has to pay, and a size probe showed medium
instances were too slow to prove optimal reliably.

Selection turned out to be the stronger lever. Each of 260 candidates was solved once
under the true model and once under each single-rule ablation; the ablations that move
its makespan are its signature. The graded set was then chosen greedily to maximise the
worst-covered rule.

| | before selection | after selection |
| --- | --- | --- |
| worst-covered rule in the graded set | 1 of 20 | 16 of 25 |
| score of a model with one wrong lag rule | 0.95 | 0.24 |

The worked runs are chosen separately so every rule is demonstrated at least 9 times,
because a rule the log never exercises would be unguessable rather than hard.

## The answer is unique, and that was checked exhaustively

A lossy observable raises the opposite risk to ambiguity in grading: two different
models might fit the whole log and disagree only on the graded runs, which would mark a
correct agent wrong. All 2304 models in the plausible rule grid, spanning lag numerator
and denominator, three rounding rules, the start-of-machine changeover, transport,
technician counts from zero to three, and switching maintenance or setup off entirely,
were solved against the 60 worked runs with early exit at the first mismatch.

**Exactly one survives: the true model.** 2304 models, 290 s.

## Fairness properties that came for free

An optimal objective value is unique even when the optimal schedule is not, so a
correct submission cannot be marked down for finding a different schedule of the same
cost, and solver nondeterminism cannot move the score. Everything is integer arithmetic,
so unlike an earlier animation task there is no tolerance to derive and no
floating-point trap: the earlier one nearly shipped with a tolerance sitting on
Blender's single-precision noise floor.

The agent's iteration loop is fast on purpose. Solving all 60 worked runs takes about
24 s, so a hypothesis can be tested end to end in well under a minute. The difficulty is
meant to be in finding the model, not in waiting for the solver.

## Calibration

Codex CLI `gpt-5.6-sol`, staged through the task's real `start()` and graded by its
real `evaluate()`:

| run | effort | elapsed | tokens | score |
| --- | --- | --- | --- | --- |
| run1 | xhigh | 4677 s | 485k | **0.08** |
| run2 | xhigh | 5486 s | 618k | **0.04** |

Both runs produced a working CP-SAT model that proved optimality on all 25 graded runs.
Neither recovered the plant's model.

run1 recovered five of the six rules: speed scaling with the correct rounding,
transport, changeovers at machine start and between consecutive operations, the single
shared crew as a cumulative resource, and maintenance windows. It missed the cooling lag
between a job's own operations. run2 missed the cooling lag as well and did not model
the shared crew at all; it parameterised the rounding and transport rules and searched
over them, which is the right instinct, but never found the two rules it was missing.

The cooling lag is the rule both runs missed. It is a delay proportional to the previous
operation's duration, so it does not show up as a constant anywhere and is only visible
in how gaps scale.

**The score was predicted before the run.** Because each graded run was selected so that
every rule changes its makespan, the discrimination table gives the score of a model
with a given rule wrong. It said a model missing only the cooling lag scores
1 - 23/25 = **0.08**. run1 missed only the cooling lag and scored exactly 0.08.

The most telling number is not the score. run1 solved all 60 worked runs to proven
optimality and reproduced **33 of them**. It could not fit the log it was given, which
is what a lossy observable is supposed to do: five rules right out of six buys almost
nothing, because a makespan cannot be assembled from partial credit.

## Is it solvable? Recovering the model from the log alone

A reference that scores 1.000 proves the task is well posed, not that it is solvable:
that reference was written by someone who already knew the rules. The question that
matters is whether the rules can be recovered from the published log.

`assets/recovery_search.py` answers it by execution. It never imports the reference and
never reads a graded answer. It searches a space deliberately wider than the truth,
where the cooling lag may be absent, proportional to the previous operation with any
ratio a/b for a in 1..2 and b in 2..8, or a flat constant, and the changeover crew may
be unlimited or hold one to three technicians. 3456 models, fitted against the 60 worked
runs only.

**Two survive, in 234 s, and they are the same model:** a lag of `ceil(d * 1/4)` and one
of `ceil(d * 2/8)` are the same lag. Both score **25/25** on the graded runs.

That second half matters as much as the first. Every model that fits the log also scores
1.000 on the graded runs, so the task cannot mark a correct agent wrong. That is the
failure a lossy observable invites and it does not occur here.

### The log is generous; the hypothesis space is the bottleneck

| worked runs used | models still fitting, of 3456 |
| --- | --- |
| 1 | 41 |
| 2 | 20 |
| 3 | 8 |
| 8 | 2 |
| 60 | 2 |

One run eliminates 99% of the space and eight runs pin it down, so the shipped 60 carry
about sevenfold redundancy. The data is not what makes this hard.

What the search does not do is invent its own hypothesis space. That space was written
by hand, and conceiving it is the actual difficulty. It is exactly where both calibrated
agents failed: run1 never considered a cooling lag at all, and run2 did build a
parameterised search over rounding and transport, which is the right instinct, but its
space contained neither the cooling lag nor a shared changeover crew.
