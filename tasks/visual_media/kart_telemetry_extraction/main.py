"""AgentHLE task: visual_media/kart_telemetry_extraction.

Recover a racing game's internal counters from gameplay video alone.

The agent gets twenty-four recorded SuperTuxKart races: twelve labelled with the
engine's own per-race telemetry for the camera-followed kart, and twelve unlabelled.
It must report, for each unlabelled race, how many item boxes the hero drove
through, how many times it spun out, and how many seconds it spent drifting.

Ground truth is SuperTuxKart's profile-mode counter table, written by the engine
itself. Nothing is human-annotated, so there is no labelling noise to argue with.

The videos are large and arrive through ALE's task-data store. Everything else --
the labels for the labelled half, the data card, and the grading -- is in this
directory, and the held-out labels never reach the VM.
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
SCRIPTS = TASK_DIR / "scripts"

DOMAIN_NAME = "visual_media"
TASK_NAME = "kart_telemetry_extraction"
VARIANT_NAME = "base"

_TRAIN = json.loads((DATA / "train_labels.json").read_text(encoding="utf-8"))
_HOLDOUT = json.loads((DATA / "holdout_labels.json").read_text(encoding="utf-8"))


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/predictions.json"

    @property
    def task_description(self) -> str:
        return """\
Recover a racing game's internal counters from gameplay video.

Under `{input}` are twenty-four recorded SuperTuxKart races, twelve under \
`train/` and twelve under `test/`. Every race is the same setup: a chase camera \
locked to a single hero kart (`tux`) for the whole race, four laps, five AI \
opponents. `train/labels.json` gives you the engine's own telemetry for each \
`train/` race. The `test/` races are unlabelled.

Each half covers **six tracks, raced twice**, and **no track appears in both \
halves**. Whatever you build on the labelled races has to work on tracks you have \
never seen labelled, with different scenery, lighting and layout.

## What to report

For the hero kart in each `test/` race, three quantities:

- **`items_collected`** -- how many item boxes the hero drove through. The HUD \
does not display the held item, so there is no on-screen readout; the pickups \
themselves are the only evidence.
- **`spinouts`** -- how many times the hero spun out, shown as a ring of stars \
around the kart. A banana and a bomb cause the same visible spin-out and are not \
reliably distinguishable, so they count together.
- **`skid_time`** -- total seconds the hero spent drifting, as a float. Drifting \
sprays bright sparks from the rear wheels.

## Deliverable

Write `{submission}`: a JSON object keyed by race id, which is the `test/` file \
name without its extension, each mapping to the three fields. For example:

    {"lighthouse_a": {"items_collected": 12, "spinouts": 3, "skid_time": 41.5}, ...}

Report every `test/` race. A race you omit scores zero for that race.

## How this is graded

Each quantity is scored against the engine's counters as a rank gate times an \
absolute accuracy: you must both order the twelve races correctly on that \
quantity and land within 30% of each true value. Ranking alone earns nothing, and \
neither does a constant or random answer.

`ffmpeg`, `ffprobe`, Python 3 and NumPy are installed. Do not rely on internet \
access, and do not modify anything under `input/`.
"""

    def to_metadata(self) -> dict:
        m = super().to_metadata()
        m.update({"submission_path": self.submission_path})
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
    """Write the labels for the labelled half; confirm the videos arrived and the
    held-out labels did not."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir = meta["input_dir"], meta["remote_output_dir"]

    await session.run_command(f"mkdir -p {out_dir!r}", check=True)
    await session.write_file(f"{input_dir}/train/labels.json",
                             json.dumps(_TRAIN, indent=1) + "\n")

    # The videos come from the task-data store, so their absence is a staging
    # failure rather than a task bug, and it must not be mistaken for a hard task.
    listing = await session.run_command(
        f"ls {input_dir!r}/train/*.mp4 2>/dev/null | wc -l; "
        f"ls {input_dir!r}/test/*.mp4 2>/dev/null | wc -l", check=False)
    counts = (listing.get("stdout") or "").split()
    if counts[:2] != [str(len(_TRAIN)), str(len(_HOLDOUT))]:
        raise RuntimeError(
            f"task data staged {counts or 'nothing'}; expected "
            f"{len(_TRAIN)} train and {len(_HOLDOUT)} test videos under {input_dir}")

    # Reference correctly hidden: no held-out value is anywhere on this machine
    # while the agent works. Probe on a skid time, which is distinctive enough
    # that an accidental match would itself be worth knowing about.
    probe = f"{next(iter(_HOLDOUT.values()))['skid_time']}"
    leak = await session.run_command(
        f"grep -rl --binary-files=without-match {probe!r} {input_dir!r} 2>/dev/null",
        check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"held-out labels leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[kart] staged %d labelled and %d unlabelled races",
                len(_TRAIN), len(_HOLDOUT))


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Read the reported telemetry and score it against the engine's counters."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("kart_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[kart] no submission at %s", submission)
        return [0.0]
    try:
        preds = json.loads(await session.read_file(submission))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.info("[kart] submission is not readable JSON: %s", exc)
        return [0.0]

    report = grade.score(preds, _HOLDOUT)
    logger.info("[kart] reported %d/%d races; items=%s spinouts=%s skid=%s reward=%.3f",
                report["reported"], report["races"],
                _fmt(report["items_collected"]), _fmt(report["spinouts"]),
                _fmt(report["skid_time"]), report["reward"])
    return [float(report["reward"])]


def _fmt(dim: dict | None) -> str:
    """One-line per-dimension summary for the run log."""
    if dim is None:
        return "unscored"
    return f"{dim['score']:.3f}(tau {dim['tau']:.2f} acc {dim['accuracy']:.2f})"
