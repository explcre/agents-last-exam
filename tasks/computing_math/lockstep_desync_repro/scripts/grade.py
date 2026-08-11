"""Host-side scoring for computing_math/lockstep_desync_repro.

Kept free of any sandbox dependency so it can be unit tested directly and so the
hidden expected hashes never need to exist on the task VM.

Scoring:

  gate    every agent-visible replay, re-run on a tick set that was never
          published, must match at every gate checkpoint. A submission that
          memorised the published hashes fails here rather than passing.
  score   mean over the held-out replays of the fraction of leading checkpoints
          reproduced. Leading, because a lockstep simulation that has desynced
          stays desynced; crediting a later coincidental match would be wrong.

  final = mean holdout prefix fraction, or 0.0 if the gate fails.
"""

from __future__ import annotations

import re

LINE_RE = re.compile(r"^\s*(\d+)\s+([0-9a-f]{16})\s*$")


def parse_output(text: str) -> list[tuple[int, str]]:
    """Parse a submission's stdout into (tick, hash) pairs.

    Unparseable lines are ignored rather than fatal: a submission that prints a
    banner alongside correct checkpoint lines is not what this task is testing.
    """
    out = []
    for line in (text or "").splitlines():
        m = LINE_RE.match(line)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def prefix_match(actual: list[tuple[int, str]], expected: list[list]) -> int:
    """Number of leading expected checkpoints the submission reproduced."""
    got = dict(actual)
    n = 0
    for tick, digest in expected:
        if got.get(int(tick)) != digest:
            break
        n += 1
    return n


def score(results: dict, expected: dict) -> dict:
    """Score raw runner results against the hidden expected hashes.

    ``results`` maps replay name to {"rc": int, "stdout": str}. Missing entries
    are treated as a failed run, never as an error.
    """
    report: dict = {"gate": {}, "holdout": {}, "gate_pass": True, "score": 0.0}

    for name, exp in expected["visible_gate"].items():
        res = results.get(name) or {}
        matched = prefix_match(parse_output(res.get("stdout", "")), exp)
        ok = matched == len(exp)
        report["gate"][name] = {"matched": matched, "total": len(exp), "pass": ok,
                                "rc": res.get("rc")}
        report["gate_pass"] = report["gate_pass"] and ok

    fractions = []
    for name, exp in expected["holdout"].items():
        res = results.get(name) or {}
        matched = prefix_match(parse_output(res.get("stdout", "")), exp)
        fractions.append(matched / len(exp))
        report["holdout"][name] = {"matched": matched, "total": len(exp),
                                   "rc": res.get("rc")}

    report["holdout_fraction"] = sum(fractions) / len(fractions) if fractions else 0.0
    report["score"] = report["holdout_fraction"] if report["gate_pass"] else 0.0
    return report
