"""End-to-end checks for visual_media/procedural_animation_extrapolation.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk. The tests that need Blender are
skipped when it is absent, so the suite still runs without it; the grader tests and
the fairness tests do not need it at all.

The fairness tests here derive what they check from the published frames rather than
from the hidden rig, because that is the only evidence an agent has. A rule the
visible window never exercises would be unguessable rather than difficult.
"""

from __future__ import annotations

import asyncio
import json
import math
import pathlib
import shutil
import subprocess
import types

import pytest

from tasks.visual_media.procedural_animation_extrapolation import main as task
from tasks.visual_media.procedural_animation_extrapolation.scripts import grade

BLENDER = shutil.which("blender") or "/tmp/galaxy_srv_disk00/pengchx3/anim/b501/blender"
HAVE_BLENDER = pathlib.Path(BLENDER).exists()


class LocalSession:
    async def run_command(self, command, *, check=False, timeout=None):
        env = {"PATH": f"{pathlib.Path(BLENDER).parent}:/usr/bin:/bin"}
        p = subprocess.run(  # noqa: ASYNC221 - the fake session is deliberately blocking
            ["bash", "-c", command], capture_output=True, text=True,
            timeout=timeout, check=False, env=env)
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


def _visible():
    return json.loads((task.DATA / "visible" / "frames_001_060.json").read_text())


def _rest():
    return json.loads((task.DATA / "visible" / "rest_meshes.json").read_text())["rest_vertices"]


def _bodies_slices():
    rest, off, out = _rest(), 0, {}
    for name in task.BODIES:
        out[name] = (off, len(rest[name]))
        off += len(rest[name])
    return out


def _pose(frame, name):
    """Recover one body's Z rotation and translation from published vertices alone.

    This is the first step any solution has to take, so doing it here keeps the
    fairness checks honest: they read only what the agent is given.
    """
    rest, (start, count) = _rest()[name], _bodies_slices()[name]
    world = [frame[3 * (start + j):3 * (start + j) + 3] for j in range(count)]
    # pick the rest vertex furthest from the body's axis so the angle is well posed
    j = max(range(count), key=lambda k: math.hypot(rest[k][0], rest[k][1]))
    ang = math.atan2(world[j][1] - sum(w[1] for w in world) / count,
                     world[j][0] - sum(w[0] for w in world) / count)
    ang -= math.atan2(rest[j][1] - sum(r[1] for r in rest) / count,
                      rest[j][0] - sum(r[0] for r in rest) / count)
    cx = sum(w[0] for w in world) / count - sum(r[0] for r in rest) / count
    cy = sum(w[1] for w in world) / count - sum(r[1] for r in rest) / count
    cz = sum(w[2] for w in world) / count - sum(r[2] for r in rest) / count
    return (ang + math.pi) % (2 * math.pi) - math.pi, (cx, cy, cz)


def test_start_stages_the_meshes_and_the_visible_frames(staged):
    d = pathlib.Path(staged.metadata["input_dir"])
    for name in ("rest_meshes.json", "frames_001_060.json"):
        assert (d / name).is_file(), name
    frames = json.loads((d / "frames_001_060.json").read_text())
    assert sorted(int(k) for k in frames) == list(range(1, 61))
    rest = json.loads((d / "rest_meshes.json").read_text())
    assert rest["bodies"] == list(task.BODIES)
    total = sum(len(v) for v in rest["rest_vertices"].values())
    assert len(frames["1"]) == 3 * total


def test_no_graded_frame_or_rig_source_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    held = task._holdout()
    for f in ("61", "120", "180"):
        probe = json.dumps(held[f][:6])[1:-1]
        assert probe not in text, f"graded frame {f} is on the VM"
    for giveaway in ("BREATHE_MULT", "Z_HI", "reference_rig", "reference_solution"):
        assert giveaway not in text, f"the rig leaked: {giveaway}"


def test_the_visible_and_graded_windows_are_disjoint_and_the_graded_one_is_new():
    vis, held = _visible(), task._holdout()
    assert not (set(vis) & set(held))
    assert len(vis) == 60 and len(held) == 120
    seen = {tuple(v) for v in vis.values()}
    repeats = sum(1 for v in held.values() if tuple(v) in seen)
    assert repeats == 0, f"{repeats} graded frames simply repeat a published one"


def test_the_visible_window_does_not_span_whole_periods():
    """The premise of the task. If the window closed on itself, fitting it would do."""
    vis = _visible()
    first, last = vis["1"], vis["60"]
    assert max(abs(a - b) for a, b in zip(first, last)) > 1.0


def test_every_rule_is_exercised_inside_the_visible_window():
    """Fairness: a rule the published frames never show could not be inferred.

    Checked from the published frames alone. The tip's height must reach both clamp
    bounds, and its distance from the arm must visibly vary, or the clamp and the
    breathing reach would be invisible until the graded window.
    """
    vis = _visible()
    slices = _bodies_slices()
    zs, reaches = [], []
    for f in range(1, 61):
        frame = vis[str(f)]
        _, (_, _, tz) = _pose(frame, "tip")
        zs.append(tz)
        (ta, tc), (aa, ac) = slices["tip"], slices["arm"]
        tcx = sum(frame[3 * (ta + j)] for j in range(tc)) / tc
        tcy = sum(frame[3 * (ta + j) + 1] for j in range(tc)) / tc
        acx = sum(frame[3 * (aa + j)] for j in range(ac)) / ac
        acy = sum(frame[3 * (aa + j) + 1] for j in range(ac)) / ac
        reaches.append(math.hypot(tcx - acx, tcy - acy))

    top = sum(1 for z in zs if abs(z - max(zs)) < 1e-6)
    bottom = sum(1 for z in zs if abs(z - min(zs)) < 1e-6)
    assert top >= 3, f"the upper clamp is flat for only {top} visible frames"
    assert bottom >= 3, f"the lower clamp is flat for only {bottom} visible frames"
    assert abs(max(zs)) - abs(min(zs)) > 1e-3, "the clamp band looks symmetric here"
    assert max(reaches) - min(reaches) > 1e-2, "the breathing reach is invisible"


def test_the_reference_frames_score_one():
    """The positive control at the grader level."""
    held = task._holdout()
    assert grade.score(dict(held), held)["reward"] == 1.0


def test_the_tolerance_sits_between_honest_drift_and_a_wrong_parameter():
    """Guard the measurement the grading tolerance rests on.

    Two correct rigs built differently drift by up to 9.9e-07 because Blender
    evaluates in single precision; the smallest parameter error tried moves a vertex
    by 1.5e-04. If a later change moved the tolerance outside that band it would
    either fail correct rigs or pass wrong ones.
    """
    assert grade.EXACT_TOL > 9.9e-07 * 5
    assert grade.EXACT_TOL < 1.5e-04 / 5


@pytest.mark.parametrize("shortcut", ["loop", "hold", "linear"])
def test_shortcuts_that_ignore_the_rule_score_zero(shortcut):
    """Continuing the window without understanding it must earn nothing."""
    vis, held = _visible(), task._holdout()
    n = len(vis["1"])
    if shortcut == "loop":
        sub = {k: vis[str((int(k) - 1) % 60 + 1)] for k in held}
    elif shortcut == "hold":
        sub = {k: vis["60"] for k in held}
    else:
        sub = {k: [vis["60"][i] + (vis["60"][i] - vis["59"][i]) * (int(k) - 60)
                   for i in range(n)] for k in held}
    assert grade.score(sub, held)["reward"] == 0.0, shortcut


def test_a_near_miss_is_distinguishable_from_nothing():
    """The loose band exists so a rig that is close is not scored as if it were absent."""
    held = task._holdout()
    nudged = {k: [v + 1e-3 for v in row] for k, row in held.items()}
    r = grade.score(nudged, held)
    assert r["exact"] == 0
    assert 0.0 < r["reward"] < 0.5


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_malformed_results_score_zero_without_raising():
    held = task._holdout()
    for junk in ({}, {k: None for k in held}, {k: [1.0, 2.0] for k in held},
                 {k: "not a frame" for k in held}, {k: [float("nan")] * len(held["61"])
                                                    for k in held}):
        assert grade.score(junk, held)["reward"] == 0.0


@pytest.mark.skipif(not HAVE_BLENDER, reason="blender not installed on this host")
def test_the_reference_rig_scores_one_end_to_end(staged):
    """The control that matters: a real rig, through Blender, through evaluate()."""
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text((task.ASSETS / "reference_solution.py").read_text(encoding="utf-8"),
                   encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]


@pytest.mark.skipif(not HAVE_BLENDER, reason="blender not installed on this host")
def test_a_rig_that_never_animates_scores_zero(staged):
    """Building the bodies and posing them once must not pass.

    The scene is stepped with frame_set(), so a submission that computes the right
    numbers but does not put them under animation cannot earn anything.
    """
    ref = (task.ASSETS / "reference_solution.py").read_text(encoding="utf-8")
    static = ref.replace('''    for f in range(1, 181):
        for name, (loc, rot) in state(f).items():
            o = bpy.data.objects[name]
            o.location = loc
            o.rotation_euler = rot
            o.keyframe_insert("location", frame=f)
            o.keyframe_insert("rotation_euler", frame=f)''', '''    for name, (loc, rot) in state(60).items():
        o = bpy.data.objects[name]
        o.location = loc
        o.rotation_euler = rot''')
    assert static != ref, "the static variant did not actually change the rig"
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text(static, encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


@pytest.mark.skipif(not HAVE_BLENDER, reason="blender not installed on this host")
def test_a_rig_that_raises_scores_zero_without_raising(staged):
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text("raise RuntimeError('nope')\n", encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]
