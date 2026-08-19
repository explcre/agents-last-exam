"""Positive, negative and ablation controls for the grader.

    python3 controls.py

Runs the full eval path (stage replays -> run a candidate sim.py -> grade) on
several candidate submissions and prints the score each one earns. A task whose
oracle does not score 1.0 through the same path the benchmark uses is not a
task; a task whose do-nothing submission scores above 0 has a floor.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TASK = HERE.parent
DATA = TASK / "data"
sys.path.insert(0, str(TASK / "scripts"))
import bugs
import grade

EXPECTED = json.loads((DATA / "reference" / "expected.json").read_text())


def stage_eval_replays(dest: pathlib.Path) -> None:
    """Write the replay set the grader runs: visible on gate ticks, holdout on scored."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED["visible_gate"]:
        replay = json.loads((DATA / "visible" / f"{name}.json").read_text())
        replay["checkpoints"] = EXPECTED["gate_checkpoints"]
        (dest / f"{name}.json").write_text(json.dumps(replay))
    for name in EXPECTED["holdout"]:
        replay = json.loads((DATA / "reference" / f"{name}.json").read_text())
        replay["checkpoints"] = EXPECTED["scored_checkpoints"]
        (dest / f"{name}.json").write_text(json.dumps(replay))


CANDIDATES: dict[str, str] = {
    "oracle_reference": (HERE / "sim_reference.py").read_text(),
    "starter_unchanged": (DATA / "starter" / "sim.py").read_text(),
    "empty_output": "import sys\n",
    "crashes": "raise SystemExit('no')\n",
    "replays_published_hashes": (
        "import json, sys\n"
        "pub = " + json.dumps({
            name: {str(t): h for t, h in
                   json.loads((DATA / "visible" / f"expected_{i}.json").read_text())["checkpoints"]}
            for i, name in enumerate(sorted(EXPECTED["visible_gate"]))
        }) + "\n"
        "rp = json.load(open(sys.argv[1]))\n"
        "key = 'replay_%d' % 0\n"
        "for name, cps in pub.items():\n"
        "    for t in rp['checkpoints']:\n"
        "        if str(t) in cps:\n"
        "            print(t, cps[str(t)])\n"
        "    break\n"
    ),
    # The task's own harness test caught this one: the published 25-tick trace
    # hands over a hash for every tick on that grid, so gate ticks that sat on
    # the grid could be answered by lookup. The gate ticks were moved off it.
    # Kept here so the shortcut stays measured rather than merely fixed.
    "replays_published_trace": (
        "import json, sys\n"
        "trace = " + json.dumps({
            int(line.split()[0]): line.split()[1]
            for line in (DATA / "visible" / "trace_0.txt").read_text().splitlines()
            if line.strip()
        }) + "\n"
        "rp = json.load(open(sys.argv[1]))\n"
        "for t in rp['checkpoints']:\n"
        "    if str(t) in trace:\n"
        "        print(t, trace[str(t)])\n"
    ),
}

# Partial repairs, for the difficulty ladder: each entry leaves exactly the
# named deviations unfixed. Built from the same patch table as the starter.
LADDER: dict[str, tuple[str, ...]] = {
    "all_fixed_except_B4": ("B4",),
    "all_fixed_except_B2": ("B2",),
    "only_B2_fixed": ("B1", "B3", "B4", "B5"),
    "only_B1_B5_fixed": ("B2", "B3", "B4"),
}


def run_candidate(source: str, replay_dir: pathlib.Path, timeout: float = 300.0) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        sim = pathlib.Path(tmp) / "sim.py"
        sim.write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(TASK / "scripts" / "eval_runner.py"),
             str(sim), str(replay_dir), str(timeout)],
            capture_output=True, text=True, check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"eval_runner failed: {proc.stderr[-2000:]}")
        return json.loads(proc.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        replay_dir = pathlib.Path(tmp) / "replays"
        stage_eval_replays(replay_dir)
        print(f"{'candidate':<26} {'gate':>6} {'holdout':>8} {'score':>7}")
        rows = {}
        for name, src in CANDIDATES.items():
            report = grade.score(run_candidate(src, replay_dir), EXPECTED)
            rows[name] = report
            print(f"{name:<26} {report['gate_pass']!s:>6} "
                  f"{report['holdout_fraction']:>8.3f} {report['score']:>7.3f}")
        print()
        print("difficulty ladder (deviations left unfixed)")
        print(f"{'candidate':<26} {'gate':>6} {'holdout':>8} {'score':>7}")
        ref_src = (HERE / "sim_reference.py").read_text()
        for name, remaining in LADDER.items():
            ids = tuple(pid for group in remaining for pid in bugs.GROUPS[group])
            report = grade.score(
                run_candidate(bugs.apply(ref_src, only=ids), replay_dir), EXPECTED
            )
            print(f"{name:<26} {report['gate_pass']!s:>6} "
                  f"{report['holdout_fraction']:>8.3f} {report['score']:>7.3f}")

        print()
        ok = True
        if rows["oracle_reference"]["score"] != 1.0:
            print("FAIL: oracle does not score 1.0 through the harness path")
            ok = False
        for name in ("starter_unchanged", "empty_output", "crashes",
                     "replays_published_hashes"):
            if rows[name]["score"] != 0.0:
                print(f"FAIL: {name} scores {rows[name]['score']}, expected 0.0")
                ok = False
        print("controls PASS" if ok else "controls FAIL")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
