"""Recover the plant's model from the published log alone: the solvability proof.

Run as::

    python3 recovery_search.py ../data/worked_runs.json ../data/holdout_runs.json

Measured result, 2026-08-30: 3456 candidate models searched in 234 s against the 60
worked runs. Two survive, and they are the same model written two ways, since a lag of
ceil(d * 1/4) and one of ceil(d * 2/8) are the same lag. Both score 25/25 on the
held-out runs.

That is the property the task needs. It is not enough that a solving program exists,
because the reference scheduler was written by someone who already knew the rules. What
this shows is that the rules are recoverable from the published log by a mechanical
search, and that every model fitting the log also scores 1.000 on the graded runs, so a
correct agent cannot be marked wrong.

What the search does NOT do is invent its own hypothesis space; the space below was
written by hand. Conceiving it is the actual difficulty, and it is where both calibrated
agents failed: one never considered a cooling lag, the other considered neither the
cooling lag nor a shared changeover crew.

This never imports the reference model and never reads a held-out answer. It searches a
hypothesis space of the kind an operations-research practitioner would write down for a
shop floor, fits it against the 60 worked runs only, and reports every model that
survives. The held-out runs are scored at the very end, once, as a check.

The space is deliberately wider than the answer: the cooling lag may be absent,
proportional to the previous operation with any small ratio, or a flat constant, and
the changeover crew may be unlimited or hold one to three technicians.
"""

from __future__ import annotations

import itertools
import json
import sys
import time

from ortools.sat.python import cp_model



def _dur(base: int, speed: int, rounding: str) -> int:
    x = base * speed
    if rounding == "ceil":
        return -(-x // 100)
    if rounding == "floor":
        return x // 100
    return (x + 50) // 100


def _lag(d_prev: int, kind, param) -> int:
    if kind == "none":
        return 0
    if kind == "const":
        return param
    num, den = param
    return -(-(d_prev * num) // den)


def solve(run, r, time_limit=25.0):
    m = cp_model.CpModel()
    H = run["horizon"]
    ops = [(j, k, op["family"], op["duration"], op["eligible"])
           for j, job in enumerate(run["jobs"]) for k, op in enumerate(job["ops"])]
    start, end, on = {}, {}, {}
    for i, (j, k, f, base, elig) in enumerate(ops):
        start[i] = m.NewIntVar(0, H, f"s{i}")
        end[i] = m.NewIntVar(0, H, f"e{i}")
        lits = []
        for mach in elig:
            b = m.NewBoolVar(f"x{i}_{mach}")
            on[(i, mach)] = b
            lits.append(b)
            m.Add(end[i] == start[i] + _dur(base, run["speed"][mach], r["round"])
                  ).OnlyEnforceIf(b)
        m.AddExactlyOne(lits)
        if k == 0:
            m.Add(start[i] >= run["jobs"][j]["release"])

    by_job = {}
    for i, (j, k, *_x) in enumerate(ops):
        by_job.setdefault(j, []).append((k, i))
    for j, lst in sorted(by_job.items()):
        lst.sort()
        for (_a, i1), (_b, i2) in zip(lst, lst[1:]):
            for mach in ops[i1][4]:
                d_prev = _dur(ops[i1][3], run["speed"][mach], r["round"])
                lg = _lag(d_prev, r["lag_kind"], r["lag_param"])
                if lg:
                    m.Add(start[i2] >= end[i1] + lg).OnlyEnforceIf(on[(i1, mach)])
            if r["transport"]:
                for m1 in ops[i1][4]:
                    for m2 in ops[i2][4]:
                        t = run["transport"][m1][m2]
                        if t:
                            m.Add(start[i2] >= end[i1] + t).OnlyEnforceIf(
                                [on[(i1, m1)], on[(i2, m2)]])

    ivs = []
    for mach in range(run["machines"]):
        mem = [i for i in range(len(ops)) if mach in ops[i][4]]
        if not mem:
            continue
        arcs, idx = [], {o: n + 1 for n, o in enumerate(mem)}
        for i in mem:
            arcs.append((idx[i], idx[i], on[(i, mach)].Not()))
            first = m.NewBoolVar(f"f{mach}_{i}")
            arcs.append((0, idx[i], first))
            arcs.append((idx[i], 0, m.NewBoolVar(f"l{mach}_{i}")))
            if r["start_setup"] and r["setup"]:
                s0 = run["setup"][mach][0][ops[i][2]]
                if s0:
                    st = m.NewIntVar(0, H, f"ss{mach}_{i}")
                    en = m.NewIntVar(0, H, f"se{mach}_{i}")
                    ivs.append(m.NewOptionalIntervalVar(st, s0, en, first, f"si{mach}{i}"))
                    m.Add(en <= start[i]).OnlyEnforceIf(first)
            for j2 in mem:
                if i == j2:
                    continue
                nxt = m.NewBoolVar(f"n{mach}_{i}_{j2}")
                arcs.append((idx[i], idx[j2], nxt))
                gap = run["setup"][mach][ops[i][2]][ops[j2][2]] if r["setup"] else 0
                if gap:
                    st = m.NewIntVar(0, H, f"cs{mach}{i}{j2}")
                    en = m.NewIntVar(0, H, f"ce{mach}{i}{j2}")
                    ivs.append(m.NewOptionalIntervalVar(st, gap, en, nxt, f"ci{mach}{i}{j2}"))
                    m.Add(st >= end[i]).OnlyEnforceIf(nxt)
                    m.Add(en <= start[j2]).OnlyEnforceIf(nxt)
                else:
                    m.Add(start[j2] >= end[i]).OnlyEnforceIf(nxt)
        m.AddCircuit(arcs)
        for a in range(len(mem)):
            for b in range(a + 1, len(mem)):
                i1, i2 = mem[a], mem[b]
                bf = m.NewBoolVar(f"d{mach}{i1}{i2}")
                m.Add(end[i1] <= start[i2]).OnlyEnforceIf([on[(i1, mach)], on[(i2, mach)], bf])
                m.Add(end[i2] <= start[i1]).OnlyEnforceIf([on[(i1, mach)], on[(i2, mach)], bf.Not()])
        for (ws, we) in (run["maintenance"][mach] if r["maint"] else []):
            for i in mem:
                bf = m.NewBoolVar(f"mb{mach}{i}{ws}")
                m.Add(end[i] <= ws).OnlyEnforceIf([on[(i, mach)], bf])
                m.Add(start[i] >= we).OnlyEnforceIf([on[(i, mach)], bf.Not()])

    if ivs and r["crew"]:
        m.AddCumulative(ivs, [1] * len(ivs), r["crew"])

    mk = m.NewIntVar(0, H, "mk")
    m.AddMaxEquality(mk, [end[i] for i in range(len(ops))])
    m.Minimize(mk)
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = 8
    return int(s.ObjectiveValue()) if s.Solve(m) == cp_model.OPTIMAL else None


LAGS = ([("none", None)]
        + [("prop", (a, b)) for a in (1, 2) for b in (2, 3, 4, 5, 6, 7, 8)]
        + [("const", c) for c in (1, 2, 3)])
SPACE = list(itertools.product(LAGS, ("ceil", "floor", "nearest"), (True, False),
                               (True, False), (0, 1, 2, 3), (True, False), (True, False)))


def as_rules(point):
    """One point of the search space as the keyword form ``solve`` expects."""
    lag, rnd, ss, tr, crew, mt, su = point
    return {"lag_kind": lag[0], "lag_param": lag[1], "round": rnd, "start_setup": ss,
            "transport": tr, "crew": crew, "maint": mt, "setup": su}


def search(worked, space=None, verbose=True):
    """Every model in ``space`` that reproduces every worked makespan."""
    space = SPACE if space is None else space
    order = sorted(range(len(worked)), key=lambda i: len(worked[i]["jobs"]))
    survivors, t0 = [], time.time()
    for n, point in enumerate(space):
        r = as_rules(point)
        if all(solve(worked[i], r) == worked[i]["makespan"] for i in order):
            survivors.append(r)
            if verbose:
                print(f"  SURVIVOR after {time.time()-t0:.0f}s: {r}", flush=True)
        if verbose and (n + 1) % 300 == 0:
            print(f"  {n+1}/{len(space)} tested, {time.time()-t0:.0f}s", flush=True)
    return survivors


def main(argv):
    worked = json.load(open(argv[1]))
    holdout = json.load(open(argv[2]))
    print(f"hypothesis space: {len(SPACE)} models, fitted against {len(worked)} "
          f"worked runs only", flush=True)
    survivors = search(worked)
    print(f"\nsurvivors: {len(survivors)}")
    for r in survivors:
        hits = sum(1 for h in holdout if solve(h, r) == h["makespan"])
        print(f"  {r}\n    held-out score: {hits}/{len(holdout)} = {hits/len(holdout):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
