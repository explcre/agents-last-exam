"""End-to-end checks for computing_math/lockstep_desync_repro.

These drive the task's real ``start()`` and ``evaluate()`` hooks. The sandbox is
replaced by a local session that runs commands with bash and keeps files on
disk, so the staging, the leak check, the on-VM runner and the host-side grader
are all exercised; only the VM itself is absent.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from tasks.computing_math.lockstep_desync_repro import main as task
from tasks.computing_math.lockstep_desync_repro.scripts import grade


class LocalSession:
    """Minimal DesktopSession stand-in backed by bash and the local filesystem."""

    async def run_command(self, command, *, check=False, timeout=None):
        proc = subprocess.run(  # noqa: ASYNC221 - the fake session is deliberately blocking
            ["bash", "-c", command], capture_output=True, text=True,
            timeout=timeout, check=False,
        )
        result = {"stdout": proc.stdout, "stderr": proc.stderr,
                  "return_code": proc.returncode}
        if check and proc.returncode != 0:
            raise RuntimeError(f"command failed: {command}\n{proc.stderr[:500]}")
        return result

    async def write_file(self, path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def read_file(self, path):
        return Path(path).read_text(encoding="utf-8")

    async def file_exists(self, path):
        return Path(path).is_file()


def _task_cfg(root: Path) -> types.SimpleNamespace:
    cfg = task.TaskConfig(REMOTE_ROOT_DIR=str(root))
    return types.SimpleNamespace(metadata=cfg.to_metadata())


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """Run the real start() into a temporary root and hand back its metadata."""
    monkeypatch.setattr(task, "EVAL_DIR", str(tmp_path / "eval"))
    cfg = _task_cfg(tmp_path / "root")
    import asyncio
    asyncio.run(task.start(cfg, LocalSession()))
    return cfg


def test_start_stages_every_input_and_the_starter_runs(staged):
    input_dir = Path(staged.metadata["input_dir"])
    for rel in task.INPUT_FILES:
        assert (input_dir / rel).is_file(), rel
    proc = subprocess.run(
        ["python3", "starter/sim.py", "replays/replay_0.json"],
        cwd=input_dir, capture_output=True, text=True, check=True,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == len(task._EXPECTED["scored_checkpoints"])


def test_start_leaves_no_reference_on_the_machine(staged):
    root = Path(staged.metadata["task_dir"])
    published = {
        digest
        for entries in task._EXPECTED["holdout"].values()
        for _tick, digest in entries
    } | {
        digest
        for entries in task._EXPECTED["visible_gate"].values()
        for _tick, digest in entries
    }
    staged_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in root.rglob("*") if p.is_file()
    )
    leaked = sorted(d for d in published if d in staged_text)
    assert not leaked, f"hidden hashes present on the VM: {leaked[:5]}"
    assert "holdout_" not in staged_text


def test_missing_submission_scores_zero(staged):
    import asyncio
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_reference_simulator_scores_one_through_the_harness(staged):
    import asyncio
    submission = Path(staged.metadata["submission_path"])
    submission.parent.mkdir(parents=True, exist_ok=True)
    submission.write_text(
        (task.ASSETS / "sim_reference.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]


def test_gate_failure_zeroes_a_submission_that_matches_held_out_checkpoints():
    """A submission can be right on the held-out set and still score 0 at the gate."""
    holdout_perfect = {
        name: {"rc": 0, "stdout": "".join(f"{t} {h}\n" for t, h in entries)}
        for name, entries in task._EXPECTED["holdout"].items()
    }
    report = grade.score(holdout_perfect, task._EXPECTED)
    assert report["holdout_fraction"] == 1.0
    assert report["gate_pass"] is False
    assert report["score"] == 0.0


def test_prefix_scoring_does_not_credit_a_match_after_a_miss():
    entries = next(iter(task._EXPECTED["holdout"].values()))
    lines = [f"{t} {h}" for t, h in entries]
    lines[1] = f"{entries[1][0]} {'0' * 16}"
    assert grade.prefix_match(grade.parse_output("\n".join(lines)), entries) == 1
