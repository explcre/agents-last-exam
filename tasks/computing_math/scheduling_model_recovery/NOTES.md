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
