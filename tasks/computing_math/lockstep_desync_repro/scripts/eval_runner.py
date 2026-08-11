"""On-VM eval driver, staged after the agent has finished.

    python3 eval_runner.py <sim.py> <replay_dir> <per_replay_timeout_s>

Runs the submission once per replay in <replay_dir> and prints one JSON object
mapping replay name to {"rc": int, "stdout": str, "stderr": str}. A submission
that crashes, hangs, or prints nothing produces a result row rather than an
exception, so the grader can score it as a miss.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


def main(argv: list[str]) -> int:
    sim, replay_dir, timeout = argv[1], pathlib.Path(argv[2]), float(argv[3])
    results = {}
    for path in sorted(replay_dir.glob("*.json")):
        name = path.stem
        try:
            proc = subprocess.run(
                [sys.executable, sim, str(path)],
                capture_output=True, text=True, timeout=timeout, cwd=str(replay_dir),
                check=False,
            )
            results[name] = {"rc": proc.returncode,
                             "stdout": proc.stdout[-65536:],
                             "stderr": proc.stderr[-4096:]}
        except subprocess.TimeoutExpired:
            results[name] = {"rc": -1, "stdout": "", "stderr": "timeout"}
        except Exception as exc:  # noqa: BLE001 - a broken submission is a score, not an error
            results[name] = {"rc": -2, "stdout": "", "stderr": repr(exc)[:4096]}
    sys.stdout.write(json.dumps(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
