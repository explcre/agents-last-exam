"""The plant's model, written as a valid submission. Never staged onto the VM.

This is the answer. It exists so the task's positive control runs the real grading
path, and so that "solvable" is demonstrated rather than asserted: every held-out
makespan below is produced by this module, and it proves optimality on every instance
well inside the time the grader allows.

The rules it encodes are exactly what the agent has to recover:

  durations   scale with machine speed and round UP
  cooling     a job waits ceil(prev_duration / 4) after each operation
  transport   moving a job between machines costs transport[a][b]
  setup       sequence dependent, charged only between consecutive ops on a machine,
              and also before a machine's first op, from family 0
  crew        every changeover needs one of ONE technician, shared across all machines
  maintenance operations may not overlap a maintenance window at all
"""

from __future__ import annotations

from ortools.sat.python import cp_model

LAG_NUM, LAG_DEN = 1, 4
CREW = 1


def _dur(base: int, speed: int) -> int:
    """Duration at a machine's speed, rounded up."""
    return -(-(base * speed) // 100)


def optimal_makespan(run: dict, time_limit: float = 60.0) -> int | None:
    """Optimal makespan for one run, or None if optimality was not proven."""
    m = cp_model.CpModel()
    H = run["horizon"]
    ops = []
    for j, job in enumerate(run["jobs"]):
        for k, op in enumerate(job["ops"]):
            ops.append((j, k, op["family"], op["duration"], op["eligible"]))

    start, end, on = {}, {}, {}
    for i, (j, k, f, base, elig) in enumerate(ops):
        start[i] = m.NewIntVar(0, H, f"s{i}")
        end[i] = m.NewIntVar(0, H, f"e{i}")
        lits = []
        for mach in elig:
            b = m.NewBoolVar(f"x{i}_{mach}")
            on[(i, mach)] = b
            lits.append(b)
            m.Add(end[i] == start[i] + _dur(base, run["speed"][mach])).OnlyEnforceIf(b)
        m.AddExactlyOne(lits)
        if k == 0:
            m.Add(start[i] >= run["jobs"][j]["release"])

    by_job = {}
    for i, (j, k, *_x) in enumerate(ops):
        by_job.setdefault(j, []).append((k, i))
    for j, lst in sorted(by_job.items()):
        lst.sort()
        for (_k1, i1), (_k2, i2) in zip(lst, lst[1:]):
            for mach in ops[i1][4]:
                d_prev = _dur(ops[i1][3], run["speed"][mach])
                lag = -(-(d_prev * LAG_NUM) // LAG_DEN)
                m.Add(start[i2] >= end[i1] + lag).OnlyEnforceIf(on[(i1, mach)])
            for m1 in ops[i1][4]:
                for m2 in ops[i2][4]:
                    t = run["transport"][m1][m2]
                    if t:
                        m.Add(start[i2] >= end[i1] + t).OnlyEnforceIf(
                            [on[(i1, m1)], on[(i2, m2)]])

    setup_ivs = []
    for mach in range(run["machines"]):
        members = [i for i in range(len(ops)) if mach in ops[i][4]]
        if not members:
            continue
        arcs, idx = [], {op_i: n + 1 for n, op_i in enumerate(members)}
        for i in members:
            arcs.append((idx[i], idx[i], on[(i, mach)].Not()))
            first = m.NewBoolVar(f"f{mach}_{i}")
            arcs.append((0, idx[i], first))
            arcs.append((idx[i], 0, m.NewBoolVar(f"l{mach}_{i}")))
            s0 = run["setup"][mach][0][ops[i][2]]
            if s0:
                st = m.NewIntVar(0, H, f"ss{mach}_{i}")
                en = m.NewIntVar(0, H, f"se{mach}_{i}")
                setup_ivs.append(
                    m.NewOptionalIntervalVar(st, s0, en, first, f"si{mach}_{i}"))
                m.Add(en <= start[i]).OnlyEnforceIf(first)
            for j2 in members:
                if i == j2:
                    continue
                nxt = m.NewBoolVar(f"n{mach}_{i}_{j2}")
                arcs.append((idx[i], idx[j2], nxt))
                gap = run["setup"][mach][ops[i][2]][ops[j2][2]]
                if gap:
                    st = m.NewIntVar(0, H, f"cs{mach}_{i}_{j2}")
                    en = m.NewIntVar(0, H, f"ce{mach}_{i}_{j2}")
                    setup_ivs.append(
                        m.NewOptionalIntervalVar(st, gap, en, nxt, f"ci{mach}_{i}_{j2}"))
                    m.Add(st >= end[i]).OnlyEnforceIf(nxt)
                    m.Add(en <= start[j2]).OnlyEnforceIf(nxt)
                else:
                    m.Add(start[j2] >= end[i]).OnlyEnforceIf(nxt)
        m.AddCircuit(arcs)

        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i1, i2 = members[a], members[b]
                bf = m.NewBoolVar(f"d{mach}_{i1}_{i2}")
                m.Add(end[i1] <= start[i2]).OnlyEnforceIf(
                    [on[(i1, mach)], on[(i2, mach)], bf])
                m.Add(end[i2] <= start[i1]).OnlyEnforceIf(
                    [on[(i1, mach)], on[(i2, mach)], bf.Not()])

        for (ws, we) in run["maintenance"][mach]:
            for i in members:
                bf = m.NewBoolVar(f"mb{mach}_{i}_{ws}")
                m.Add(end[i] <= ws).OnlyEnforceIf([on[(i, mach)], bf])
                m.Add(start[i] >= we).OnlyEnforceIf([on[(i, mach)], bf.Not()])

    if setup_ivs:
        m.AddCumulative(setup_ivs, [1] * len(setup_ivs), CREW)

    mk = m.NewIntVar(0, H, "makespan")
    m.AddMaxEquality(mk, [end[i] for i in range(len(ops))])
    m.Minimize(mk)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    if solver.Solve(m) != cp_model.OPTIMAL:
        return None
    return int(solver.ObjectiveValue())
