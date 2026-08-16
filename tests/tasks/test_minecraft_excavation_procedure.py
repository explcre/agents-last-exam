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
        assert len(w["before"]) == 81 and len(w["after"]) == 81


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


def test_every_graded_marker_type_is_demonstrated():
    """A graded world needing a marker absent from the examples would be unfair."""
    def types(worlds):
        return {v for w in worlds.values() for v in w["before"].values() if v != "grass_block"}
    missing = types(task._HOLDOUT) - types(task._EXAMPLES)
    assert not missing, f"graded but never demonstrated: {sorted(missing)}"


def _phase_one_size(world):
    """Re-derive the first-phase footprint the gate branches on, from the world alone."""
    CARD = ((1, 0), (-1, 0), (0, 1), (0, -1))
    markers = {k: v for k, v in world["before"].items() if v != "grass_block"}
    dead = set()
    for k, v in markers.items():
        if v != "cyan_wool":
            continue
        dx, dz = (int(n) for n in k.split(","))
        dead.add(k)
        for a, b in CARD:
            if f"{dx+a},{dz+b}" in markers:
                dead.add(f"{dx+a},{dz+b}")
    live = {k: v for k, v in markers.items() if k not in dead}

    def inb(x, z):
        return abs(x) <= 4 and abs(z) <= 4

    air = set()
    for t in ("orange_wool", "white_wool", "light_blue_wool"):
        for k, v in live.items():
            if v != t:
                continue
            dx, dz = (int(n) for n in k.split(","))
            if t == "light_blue_wool":
                d = 1
                while inb(dx + d, dz) and f"{dx+d},{dz}" not in air:
                    air.add(f"{dx+d},{dz}")
                    d += 1
                continue
            cells = [(dx, dz)] if t == "orange_wool" else [(dx + a, dz + b) for a, b in CARD]
            if any(f"{a},{b}" in air for a, b in cells):
                continue
            air |= {f"{a},{b}" for a, b in cells if inb(a, b)}
    return len(air)


def test_both_gate_regimes_appear_on_both_sides():
    """The procedure branches on a global property of the world. If one branch never
    occurs, the branch is untestable and the task is quietly simpler than intended."""
    for name, worlds in (("examples", task._EXAMPLES), ("holdout", task._HOLDOUT)):
        dense = sum(1 for w in worlds.values() if _phase_one_size(w) >= 12)
        sparse = len(worlds) - dense
        assert dense >= 3 and sparse >= 3, f"{name}: {dense} dense / {sparse} sparse"


def test_the_suppressing_marker_is_exercised_on_both_sides():
    """One marker cancels its neighbours. If it never neighbours anything, the
    interaction it exists for is never tested and the rule is silently simpler."""
    def suppressions(worlds):
        n = 0
        for w in worlds.values():
            markers = {k: v for k, v in w["before"].items() if v != "grass_block"}
            for k, v in markers.items():
                if v != "cyan_wool":
                    continue
                dx, dz = (int(x) for x in k.split(","))
                n += sum(1 for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         if f"{dx+a},{dz+b}" in markers)
        return n
    assert suppressions(task._EXAMPLES) >= 5, "the examples barely show the interaction"
    assert suppressions(task._HOLDOUT) >= 2, "the graded set barely tests the interaction"


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
    assert grade.score(greedy, task._HOLDOUT)["reward"] < 0.10


def test_malformed_results_score_zero_without_raising():
    for junk in ({}, {s: None for s in task._HOLDOUT}, {s: {"after": "nope"} for s in task._HOLDOUT}):
        assert grade.score(junk, task._HOLDOUT)["reward"] == 0.0
