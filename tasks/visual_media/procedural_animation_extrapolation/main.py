"""AgentHLE task: visual_media/procedural_animation_extrapolation.

Recover the rule behind a procedural animation and carry it into frames nobody showed.

The agent is given the rest meshes of three rigid bodies and the first sixty frames of
their motion, as world-space vertex positions. It must build a Blender scene that
reproduces frames 61 to 180, which it never sees.

Fitting the visible window does not answer this. The sixty published frames do not
span a whole number of periods, so an order-8 harmonic fit of them extrapolates to a
maximum vertex error of 6.89, and looping or holding the window is worse. What has to
be recovered is the rule itself: two turn rates, a Lissajous path, a reach that
breathes at a multiple of the arm's spin, and a vertical clamp whose band is not
centred on zero. Every one of those is exercised inside the visible window, so nothing
has to be guessed, but a turn rate wrong by 0.05% already moves a vertex by 2.6e-02.

The tolerance is measured rather than chosen. Blender evaluates in single precision,
so two correct rigs built differently, one parented and one flat, drift apart by up to
9.9e-07, while the smallest parameter error tried moves a vertex by 1.5e-04. Grading
at 1e-05 sits an order of magnitude above the first and well below the second.

All task data is written by ``start()``. Nothing is baked into an image and nothing is
fetched at run time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import cua_bench as cb

from tasks.common_setup import BaseTaskSetup
from tasks.linux_runtime import LinuxTaskConfig

_setup = BaseTaskSetup()

logger = logging.getLogger(__name__)

TASK_DIR = Path(__file__).resolve().parent
DATA = TASK_DIR / "data"
ASSETS = TASK_DIR / "assets"
SCRIPTS = TASK_DIR / "scripts"

DOMAIN_NAME = "visual_media"
TASK_NAME = "procedural_animation_extrapolation"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/procedural_animation_extrapolation"
RUNNER_TIMEOUT_S = 1800.0

VISIBLE_FRAMES = (1, 60)
GRADED_FRAMES = (61, 180)
BODIES = ("arm", "hub", "tip")


def _holdout() -> dict:
    return json.loads((DATA / "holdout" / "frames_061_180.json").read_text(encoding="utf-8"))


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/rig.py"

    @property
    def task_description(self) -> str:
        return """\
Recover a procedural animation and carry it into frames you have not seen.

Three rigid bodies named `arm`, `hub` and `tip` move under a rule that is a pure \
function of the frame number. Under `{input}` you have:

- `rest_meshes.json`: each body's vertices in its own rest space, in the vertex order \
used for grading;
- `frames_001_060.json`: frames 1 to 60, each a flat list of world-space vertex \
coordinates `[x, y, z, x, y, z, ...]`, bodies concatenated in the order `arm`, `hub`, \
`tip`, vertices of each body in the order given by `rest_meshes.json`.

The bodies are rigid: only their position and orientation change. Frames 61 to 180 \
are graded and are not published.

## What you write

`{submission}`, a Python module for Blender exposing:

    def build():
        \"\"\"Create the three bodies in the current scene, animated for frames 1..180.\"\"\"

It is imported by a Blender 5.0.1 run in background mode. After `build()` returns, \
the scene is stepped with `frame_set(f)` for each graded frame and the world-space \
vertices of `arm`, `hub` and `tip` are read back from the evaluated scene. So the \
animation must be driven by something `frame_set` evaluates, such as keyframes or \
drivers; setting transforms once at build time will not do. Your objects must carry \
exactly the vertices in `rest_meshes.json`, in that order.

## How this is graded

For each graded frame, every vertex is compared with the reference. A frame counts as \
reproduced when its largest vertex deviation is at most 1e-05, and counts toward a \
smaller share of the reward when it is within 1e-02. Most of the reward is the exact \
half.

Fitting the sixty published frames is not enough on its own: they do not span a whole \
number of periods, so a curve fitted to them does not continue correctly. You can \
check your own rig against frames 1 to 60 before submitting.

Blender is installed and `blender` is on the PATH. Everything you need is in \
`{input}`. Do not rely on internet access, and do not modify anything under `input/`.
"""

    def to_metadata(self) -> dict:
        m = super().to_metadata()
        m.update({"submission_path": self.submission_path, "eval_dir": EVAL_DIR})
        return m


@cb.tasks_config(split="train")
def load():
    cfg = TaskConfig()
    description = (cfg.task_description
                   .replace("{input}", cfg.input_dir)
                   .replace("{submission}", cfg.submission_path))
    return [cb.Task(
        description=description,
        metadata=cfg.to_metadata(),
        computer={"provider": "computer", "setup_config": {"os_type": cfg.OS_TYPE}},
    )]


@cb.setup_task(split="train")
async def start(task_cfg, session: cb.DesktopSession):
    """Stage the rest meshes and the visible frames; confirm nothing else leaked."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r} {out_dir!r}", check=True)
    for name in ("rest_meshes.json", "frames_001_060.json"):
        await session.write_file(f"{input_dir}/{name}",
                                 (DATA / "visible" / name).read_text(encoding="utf-8"))

    held = _holdout()
    probe = json.dumps(held[str(GRADED_FRAMES[0])][:6])[1:-1]
    leak = await session.run_command(
        f"grep -rlF {probe!r} {input_dir!r} 2>/dev/null; "
        f"grep -rlE 'BREATHE_MULT|reference_rig|Z_HI' {input_dir!r} 2>/dev/null; "
        f"ls {ref_dir!r} 2>/dev/null", check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference material leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[anim] staged frames %d-%d; %d frames held out host side",
                *VISIBLE_FRAMES, len(held))


RUNNER = r'''
import importlib.util, json, sys
import bpy

sub, order_path, frames_path, out_path = sys.argv[-4:]
spec = importlib.util.spec_from_file_location("submitted_rig", sub)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.build()

bodies = json.loads(open(order_path).read())
wanted = json.loads(open(frames_path).read())
out = {}
for f in wanted:
    bpy.context.scene.frame_set(int(f))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    try:
        for name in bodies:
            ev = bpy.data.objects[name].evaluated_get(dg)
            m = ev.to_mesh()
            mw = ev.matrix_world
            for v in m.vertices:
                w = mw @ v.co
                pts.extend([w.x, w.y, w.z])
            ev.to_mesh_clear()
    except Exception:
        pts = None
    out[f] = pts
open(out_path, "w").write(json.dumps(out))
'''


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted rig in Blender; compare the graded frames host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("anim_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[anim] no submission at %s", submission)
        return [0.0]

    expected = _holdout()
    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)
    await session.write_file(f"{EVAL_DIR}/runner.py", RUNNER)
    await session.write_file(f"{EVAL_DIR}/bodies.json", json.dumps(list(BODIES)))
    await session.write_file(f"{EVAL_DIR}/frames.json", json.dumps(sorted(expected)))

    r = await session.run_command(
        f"blender --background --factory-startup --python {EVAL_DIR}/runner.py -- "
        f"{submission!r} {EVAL_DIR}/bodies.json {EVAL_DIR}/frames.json "
        f"{EVAL_DIR}/result.json",
        timeout=RUNNER_TIMEOUT_S, check=False)
    if not await session.file_exists(f"{EVAL_DIR}/result.json"):
        logger.info("[anim] blender produced no result rc=%s err=%s",
                    r.get("return_code"), (r.get("stderr") or "")[:300])
        return [0.0]
    try:
        results = json.loads(await session.read_file(f"{EVAL_DIR}/result.json"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[anim] result unparseable: %s", exc)
        return [0.0]

    report = grade.score(results, expected)
    logger.info("[anim] exact=%d/%d loose=%d worst=%s reward=%.3f",
                report["exact"], report["frames"], report["loose"],
                report["worst_error"], report["reward"])
    return [float(report["reward"])]
