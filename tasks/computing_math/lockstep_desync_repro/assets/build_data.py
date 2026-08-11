"""Build every artifact the task ships, and refuse to ship a broken one.

    python3 build_data.py

Writes ../data/:

    starter/sim.py                the agent-visible build, reference + deviations
    visible/replay_{0,1,2}.json   agent-visible replays
    visible/expected_{0,1,2}.json published checkpoint hashes for those replays
    visible/trace_0.txt           25-tick-resolution hash trace of replay 0
    reference/holdout_*.json      held-out replays, staged only at eval time
    reference/expected.json       hidden hashes: holdout scored + visible gate

Assertions run on every build, because each one has already caught a real defect
here: an open-loop replay that did not reproduce its own recording, a patch that
matched twice, and two deviations that were invisible to the state hash.
"""

from __future__ import annotations

import json
import pathlib
import sys

import bugs
import diagnose
import replaygen as G
import sim_reference as R

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE.parent / "data"
N_VISIBLE = 3
N_HOLDOUT = 5
TRACE_STRIDE = 25


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _replay_json(replay: dict) -> str:
    """Compact but diffable: one command per line, everything else inline."""
    head = {k: v for k, v in replay.items() if k != "commands"}
    lines = [json.dumps(head)[:-1] + ', "commands": [']
    cmds = replay["commands"]
    for i, c in enumerate(cmds):
        lines.append("  " + json.dumps(c) + ("," if i + 1 < len(cmds) else ""))
    lines.append("]}")
    return "\n".join(lines) + "\n"


def build() -> dict:
    ref_src = (HERE / "sim_reference.py").read_text(encoding="utf-8")

    starter_src = bugs.make_starter(ref_src)
    if "sorted(lane, key=" in starter_src:
        raise AssertionError("starter still carries the reference acquisition order")
    starter_mod = diagnose.load_module(starter_src, "starter_check")
    _write(DATA / "starter" / "sim.py", starter_src)

    report: dict = {"visible": [], "holdout": [], "starter_gate_pass": None}
    scored = list(R.CHECKPOINTS)
    gate = list(R.GATE_CHECKPOINTS)
    hidden = {"scored_checkpoints": scored, "gate_checkpoints": gate,
              "holdout": {}, "visible_gate": {}}

    starter_gate_ok = True
    for i in range(N_VISIBLE + N_HOLDOUT):
        seed, pseed = diagnose.SEEDS[i]
        replay = G.generate(seed, pseed)
        replay["checkpoints"] = scored

        # The recording must replay open loop. If the policy ever consumed the
        # simulation RNG this assertion is what would catch it.
        scored_hashes = diagnose.hashes(R, replay, scored)
        if [h for _t, h in R.run(replay)] != [scored_hashes[t] for t in scored]:
            raise AssertionError(f"replay {i} does not reproduce open loop")

        gate_hashes = diagnose.hashes(R, replay, gate)

        if i < N_VISIBLE:
            name = f"replay_{i}"
            _write(DATA / "visible" / f"{name}.json", _replay_json(replay))
            _write(DATA / "visible" / f"expected_{i}.json",
                   json.dumps({"replay": f"{name}.json",
                               "checkpoints": [[t, scored_hashes[t]] for t in scored]},
                              indent=2) + "\n")
            hidden["visible_gate"][name] = [[t, gate_hashes[t]] for t in gate]
            report["visible"].append({"replay": name, "seed": seed})
            starter_div = diagnose.first_divergence(
                diagnose.hashes(starter_mod, replay, gate), gate_hashes
            )
            report["visible"][-1]["starter_first_gate_divergence"] = starter_div
            starter_gate_ok = starter_gate_ok and starter_div is None
            if i == 0:
                stride = list(range(TRACE_STRIDE, replay["ticks"] + 1, TRACE_STRIDE))
                trace = diagnose.hashes(R, replay, stride)
                _write(DATA / "visible" / "trace_0.txt",
                       "".join(f"{t} {trace[t]}\n" for t in stride))
        else:
            name = f"holdout_{i - N_VISIBLE}"
            _write(DATA / "reference" / f"{name}.json", _replay_json(replay))
            hidden["holdout"][name] = [[t, scored_hashes[t]] for t in scored]
            report["holdout"].append({"replay": name, "seed": seed})

    _write(DATA / "reference" / "expected.json", json.dumps(hidden, indent=2) + "\n")
    report["starter_gate_pass"] = starter_gate_ok
    if starter_gate_ok:
        raise AssertionError(
            "the unmodified starter passes the visible gate: the task would have a "
            "do-nothing floor above zero"
        )
    return report


def main(argv: list[str]) -> int:
    report = build()
    print(json.dumps(report, indent=2))
    print(f"\nwrote {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
