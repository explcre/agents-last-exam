# Third-party attribution

## Google OR-Tools

The reference model and the intended solution use
[OR-Tools](https://developers.google.com/optimization) CP-SAT, which is free software
under the Apache 2.0 licence. No OR-Tools source is redistributed here; the task's
package installs it with pip at image build time, pinned to 9.15.6755.

- Upstream: <https://github.com/google/or-tools>
- Licence: Apache 2.0

## The instances and the model

The shop-floor instances, the scheduling model behind them and every published and
held-out makespan are original to this task. Nothing is taken from a published
benchmark instance set. Every makespan is the output of actually solving the instance to
proven optimality, not a hand-authored number, and a test re-solves a sample of the
graded answers to catch drift between the shipped file and the model.
