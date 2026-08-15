"""End-to-end checks for computing_math/minecraft_excavation_procedure.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk. No test here starts a Minecraft
server: the grader is exercised with recorded world states, which is what the
scoring actually consumes.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import types

import pytest

from tasks.computing_math.minecraft_excavation_procedure import main as task
from tasks.computing_math.minecraft_excavation_procedure.scripts import grade


class LocalSession:
    async def run_command(self, command, *, check=False, timeout=None):
        p = subprocess.run(  # noqa: ASYNC221 - the fake session is deliberately blocking
            ["bash", "-c", command], capture_output=True, text=True,
            timeout=timeout, check=False)
        if check and p.returncode != 0:
            raise RuntimeError(f"{command}\n{p.stderr[:400]}")
        return {"stdout": p.stdout, "stderr": p.stderr, "return_code": p.returncode}

    async def write_file(self, path, content):
        t = pathlib.Path(path)
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_text(content, encoding="utf-8")

    async def read_file(self, path):
        return pathlib.Path(path).read_text(encoding="utf-8")

    async def file_exists(self, path):
        return pathlib.Path(path).is_file()


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setattr(task, "EVAL_DIR", str(tmp_path / "eval"))
    cfg = task.TaskConfig(REMOTE_ROOT_DIR=str(tmp_path / "root"))
    tc = types.SimpleNamespace(metadata=cfg.to_metadata())
    asyncio.run(task.start(tc, LocalSession()))
    return tc


def test_start_stages_examples_and_runner(staged):
    input_dir = pathlib.Path(staged.metadata["input_dir"])
    for rel in task.INPUT_FILES:
        assert (input_dir / rel).is_file(), rel
    ex = json.loads((input_dir / "examples.json").read_text())
    assert len(ex) >= 6
    for w in ex.values():
        assert set(w) >= {"before", "after"}
        assert len(w["before"]) == 49 and len(w["after"]) == 49


def test_no_held_out_world_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for seed, w in task._HOLDOUT.items():
        assert json.dumps(w["after"]) not in text, f"held-out world {seed} is on the VM"
    assert "reference_rule" not in text, "the reference procedure reached the VM"


def test_the_rule_is_not_written_down_anywhere_the_agent_can_read(staged):
    """The examples are the only statement of the procedure that exists.

    Block names necessarily appear in the example grids, and the local runner has to
    name them to build an arena, so their presence is not a leak. What must not
    appear is prose describing what the procedure does with them.
    """
    input_dir = pathlib.Path(staged.metadata["input_dir"])
    prose = [p for p in input_dir.rglob("*") if p.is_file() and p.name != "examples.json"]
    text = " ".join(p.read_text(encoding="utf-8", errors="ignore").lower() for p in prose)
    text += " " + task.TaskConfig().task_description.lower()
    for giveaway in ("orthogonal", "neighbour", "neighbor", "adjacent",
                     "dig it and", "unless it is", "east of"):
        assert giveaway not in text, f"the prompt or runner leaks the rule: {giveaway}"


def test_examples_and_holdout_are_disjoint():
    assert not (set(task._EXAMPLES) & set(task._HOLDOUT))


def test_every_graded_case_is_demonstrated():
    """A held-out world needing a case absent from the examples would be unfair."""
    def cases(worlds):
        """Marker type, plus the neighbour condition only where it changes the outcome."""
        seen = set()
        for w in worlds.values():
            markers = {k: v for k, v in w["before"].items() if v != "grass_block"}
            for k, v in markers.items():
                dx, dz = (int(n) for n in k.split(","))
                near = any(markers.get(f"{dx+a},{dz+b}") == "orange_wool"
                           for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                seen.add((v, near) if v == "white_wool" else (v, None))
        return seen
    missing = cases(task._HOLDOUT) - cases(task._EXAMPLES)
    assert not missing, f"graded but never demonstrated: {sorted(missing)}"


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_reference_worlds_score_one():
    """The positive control: reproducing the reference exactly must reach 1.0."""
    assert grade.score(dict(task._HOLDOUT), task._HOLDOUT)["reward"] == 1.0


def test_a_bot_that_does_nothing_scores_zero():
    """Per-cell accuracy would hand this roughly half, which is why F1 over dug cells is used."""
    idle = {s: {"before": w["before"], "after": dict(w["before"])}
            for s, w in task._HOLDOUT.items()}
    assert grade.score(idle, task._HOLDOUT)["reward"] == 0.0


def test_digging_the_whole_arena_scores_poorly():
    """The other cheap shortcut: change everything and hope."""
    greedy = {s: {"before": w["before"], "after": {k: "air" for k in w["before"]}}
              for s, w in task._HOLDOUT.items()}
    assert grade.score(greedy, task._HOLDOUT)["reward"] < 0.5


def test_malformed_results_score_zero_without_raising():
    for junk in ({}, {s: None for s in task._HOLDOUT}, {s: {"after": "nope"} for s in task._HOLDOUT}):
        assert grade.score(junk, task._HOLDOUT)["reward"] == 0.0
