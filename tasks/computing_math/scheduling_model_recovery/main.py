"""AgentHLE task: computing_math/scheduling_model_recovery.

Recover a plant's scheduling model from the only thing its retired planner left behind.

A contract manufacturer is replacing a planning system nobody has the source for. What
survives is a log: for each historical production run, the shop-floor data the planner
was given and the makespan it achieved, which was always optimal for its model. The
agent must rebuild that model in CP-SAT and predict the optimal makespan for runs it
has not seen.

The observable is one integer per run. That is the point. A makespan is a global
optimum, so it cannot be attributed to any individual rule: changing one rule changes
which schedule is optimal and therefore how every other rule shows up. There is no
intermediate output to diff against, which is what separates this from reconstructing a
file format or a pipeline, where a rich observable lets an agent localise its error.

Every field an instance carries is read by the model, and every rule is exercised by
the worked runs, so nothing has to be guessed. A rule that turned out not to change any
makespan was removed rather than shipped: "the release date applies to every operation
rather than only the first" was measured to be redundant under job precedence on 40 of
40 instances, so it is not part of the model.

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

DOMAIN_NAME = "computing_math"
TASK_NAME = "scheduling_model_recovery"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/scheduling_model_recovery"
RUNNER_TIMEOUT_S = 2400.0


def _worked() -> list:
    return json.loads((DATA / "worked_runs.json").read_text(encoding="utf-8"))


def _holdout() -> list:
    return json.loads((DATA / "holdout_runs.json").read_text(encoding="utf-8"))


def _expected() -> dict:
    return {r["id"]: r["makespan"] for r in _holdout()}


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/scheduler.py"

    @property
    def task_description(self) -> str:
        return """\
Rebuild a plant's scheduling model from its retired planner's log.

A contract manufacturer is replacing a production planner nobody has the source for. \
All that survives is a log. Under `{input}` you have:

- `worked_runs.json`: historical runs, each with the shop-floor data the planner was \
given and `makespan`, the schedule length it achieved. The old planner always found \
the optimal makespan for its own model.
- `holdout_runs.json`: further runs in the same format, with `makespan` removed.

Each run describes one shop:

    machines      how many machines
    speed[m]      machine m runs at this percent of nominal rate
    jobs[j]       release, and an ordered list of operations
      ops[k]        family, duration (at nominal rate), eligible machines
    setup[m][a][b]  changeover time on machine m from family a to family b;
                    family 0 is the state a machine is in before its first job
    transport[a][b] time to move work from machine a to machine b
    maintenance[m]  windows in which machine m cannot process anything

Every field above is read by the plant's model. What the log does not tell you is how \
they combine, and that is what you have to recover.

## What you write

`{submission}`, a self-contained Python 3 module exposing:

    def optimal_makespan(run: dict) -> int

returning the optimal makespan for one run under the plant's model. OR-Tools is \
installed, so `from ortools.sat.python import cp_model` is available and is the \
intended way to solve each instance.

## How this is graded

Your module is run against held-out runs. For each one, the integer you return is \
compared with the plant's optimal makespan. The reward is the fraction reproduced \
exactly; there is no partial credit within a run.

An optimal objective value is unique even when the optimal schedule is not, so you are \
not required to find any particular schedule, only the right cost. Reproducing a run \
you were shown proves only that a model fits the past; the graded runs are what decide \
whether you recovered the model.

Everything you need is in `{input}`. Do not rely on internet access, and do not modify \
anything under `input/`.
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
    """Stage the worked runs and the unlabelled held-out runs; confirm no answer leaked."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r} {out_dir!r}", check=True)
    await session.write_file(f"{input_dir}/worked_runs.json",
                             json.dumps(_worked(), indent=1))
    stripped = [{k: v for k, v in r.items() if k != "makespan"} for r in _holdout()]
    await session.write_file(f"{input_dir}/holdout_runs.json", json.dumps(stripped, indent=1))

    leak = await session.run_command(
        f"grep -rlE 'lag_den|speed_round|setup_at_start|crew|DEFAULT_RULES' {input_dir!r} "
        f"2>/dev/null; ls {ref_dir!r} 2>/dev/null", check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference material leaked onto the VM: {leak['stdout'][:400]}")
    staged = await session.read_file(f"{input_dir}/holdout_runs.json")
    if "makespan" in staged:
        raise RuntimeError("a held-out makespan was staged onto the VM")
    logger.info("[sched] staged %d worked runs; %d held out host side",
                len(_worked()), len(_holdout()))


RUNNER = r'''
import importlib.util, json, pathlib, sys

spec = importlib.util.spec_from_file_location("submitted_scheduler", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

runs = json.loads(pathlib.Path(sys.argv[2]).read_text())
out = {}
for run in runs:
    try:
        v = mod.optimal_makespan(run)
        out[run["id"]] = int(v) if v is not None else None
    except Exception:
        out[run["id"]] = None
pathlib.Path(sys.argv[3]).write_text(json.dumps(out))
'''


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted module over the held-out runs; compare host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("sched_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[sched] no submission at %s", submission)
        return [0.0]

    expected = _expected()
    stripped = [{k: v for k, v in r.items() if k != "makespan"} for r in _holdout()]
    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)
    await session.write_file(f"{EVAL_DIR}/runs.json", json.dumps(stripped))
    await session.write_file(f"{EVAL_DIR}/runner.py", RUNNER)

    r = await session.run_command(
        f"python3 {EVAL_DIR}/runner.py {submission!r} {EVAL_DIR}/runs.json "
        f"{EVAL_DIR}/result.json",
        timeout=RUNNER_TIMEOUT_S, check=False)
    if not await session.file_exists(f"{EVAL_DIR}/result.json"):
        logger.info("[sched] runner produced nothing rc=%s err=%s",
                    r.get("return_code"), (r.get("stderr") or "")[:300])
        return [0.0]
    try:
        results = json.loads(await session.read_file(f"{EVAL_DIR}/result.json"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.info("[sched] result unparseable: %s", exc)
        return [0.0]

    report = grade.score(results, expected)
    logger.info("[sched] exact=%d/%d wrong=%d missing=%d reward=%.3f",
                report["exact"], report["instances"], report["wrong"],
                report["missing"], report["reward"])
    return [float(report["reward"])]
