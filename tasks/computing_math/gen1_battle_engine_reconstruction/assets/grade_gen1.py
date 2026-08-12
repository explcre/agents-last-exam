"""Host-side scoring for the Gen-I battle engine reconstruction task.

No sandbox dependency, so it can be unit tested directly and the expected
transcripts never need to exist on the task VM.

Two numbers, because they answer different questions:

  full_pass    every scenario reproduced exactly. This is the headline: an
               engine is either bit-exact or it is not, and it is what ALE
               reports.
  mechanics    mean over families of the fraction of that family's scenarios
               reproduced. A family is one move, so this reads as "how many of
               the 48 mechanics did the submission get right". An engine with a
               single localized bug scores near 1.0 here and 0 on full_pass,
               which is the honest description of it.

The per-family breakdown is the diagnostic: the lowest-scoring families name the
broken mechanic. A corpus of random battles cannot do that.
"""

from __future__ import annotations

import re

LINE = re.compile(r"^u\d+ ")


def parse(text: str) -> list[str]:
    """Transcript lines from a submission's stdout; anything else is ignored."""
    return [ln.rstrip() for ln in (text or "").splitlines() if LINE.match(ln)]


def family_of(scenario_id: str) -> str:
    """Scenario ids are <side>_<species>_<move>_<tape index>."""
    return scenario_id.rsplit("_", 1)[0]


def score(results: dict, expected: dict) -> dict:
    """Score raw runner output against the hidden transcripts.

    ``results`` maps scenario id to {"rc": int, "stdout": str}. A missing entry
    is a failed run, never an error.
    """
    per_family: dict[str, list[bool]] = {}
    failures: list[str] = []

    for sid, want in expected.items():
        got = parse((results.get(sid) or {}).get("stdout", ""))
        ok = got == list(want)
        per_family.setdefault(family_of(sid), []).append(ok)
        if not ok:
            failures.append(sid)

    families = {f: sum(v) / len(v) for f, v in per_family.items()}
    mechanics = sum(families.values()) / len(families) if families else 0.0
    total = sum(len(v) for v in per_family.values())
    exact = sum(sum(v) for v in per_family.values())

    return {
        "families": families,
        "broken": sorted((f for f, v in families.items() if v < 1.0),
                         key=lambda f: families[f]),
        "scenarios_exact": exact,
        "scenarios_total": total,
        "mechanics": mechanics,
        "full_pass": 1.0 if exact == total and total else 0.0,
        "failures": failures[:20],
    }


def report(rep: dict) -> str:
    lines = [f"scenarios exact : {rep['scenarios_exact']}/{rep['scenarios_total']}",
             f"mechanics       : {rep['mechanics']:.3f}",
             f"full pass       : {rep['full_pass']:.0f}"]
    if rep["broken"]:
        lines.append("families below 1.000 (the diagnostic):")
        lines += [f"    {f:<34}{rep['families'][f]:.2f}" for f in rep["broken"][:12]]
    return "\n".join(lines)
