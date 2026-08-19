"""AgentHLE task: computing_math/lockstep_desync_repro.

Lockstep replay conformance. The agent is given the normative rules of a
deterministic lockstep simulation, a starter build that does not reproduce
recorded replays, three recorded replays with their published checkpoint hashes,
and a hash trace to bisect against. It must produce a simulator that reproduces
held-out replays bit for bit.

All task data is written by ``start()``. Nothing is baked into an image and
nothing is fetched at run time. The hidden reference never touches the VM: the
held-out replays are pushed only during ``evaluate()``, after the agent is gone,
and the expected hashes are compared host side against repo-local assets.
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
ASSETS = TASK_DIR / "assets"
DATA = TASK_DIR / "data"
SCRIPTS = TASK_DIR / "scripts"

DOMAIN_NAME = "computing_math"
TASK_NAME = "lockstep_desync_repro"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/lockstep_desync_repro"
PER_REPLAY_TIMEOUT_S = 300.0
RUNNER_TIMEOUT_S = 3000.0

_EXPECTED = json.loads((DATA / "reference" / "expected.json").read_text(encoding="utf-8"))

# Written into input/. Everything here is agent visible by design.
INPUT_FILES: dict[str, Path] = {
    "SPEC.md": ASSETS / "SPEC.md",
    "starter/sim.py": DATA / "starter" / "sim.py",
    "replays/replay_0.json": DATA / "visible" / "replay_0.json",
    "replays/replay_1.json": DATA / "visible" / "replay_1.json",
    "replays/replay_2.json": DATA / "visible" / "replay_2.json",
    "replays/expected_0.json": DATA / "visible" / "expected_0.json",
    "replays/expected_1.json": DATA / "visible" / "expected_1.json",
    "replays/expected_2.json": DATA / "visible" / "expected_2.json",
    "replays/trace_0.txt": DATA / "visible" / "trace_0.txt",
}


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    # Everything the agent sees is written by start(). Nothing is pulled from the
    # task data source, so this task adds no data-staging burden.
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/sim.py"

    @property
    def task_description(self) -> str:
        return """\
You are fixing a deterministic lockstep simulator so that it reproduces recorded \
matches bit for bit.

Lane Siege is a lockstep simulation: every client replays the same recorded input \
stream and must arrive at exactly the same state on every tick. The build you have \
been given does not. It agrees with the recording for a while and then diverges, \
which in production is a desynchronised match.

## Visible inputs, under `{input}`

- `SPEC.md` is the normative specification. Where the starter disagrees with it, \
the starter is wrong.
- `starter/sim.py` is the build that fails to reproduce the replays.
- `replays/replay_0.json`, `replay_1.json`, `replay_2.json` are recorded matches.
- `replays/expected_0.json` and the other two hold the correct state hash at every \
checkpoint of the matching replay. Use them to check your work.
- `replays/trace_0.txt` is a 25-tick-resolution hash trace of `replay_0`, so you \
can bisect to the exact tick where a divergence starts.

## The interface

Your simulator is invoked as

    python3 sim.py <replay.json>

and must write one line per checkpoint tick to stdout, in ascending tick order:

    <tick> <16 lowercase hex digits>

The checkpoint ticks are read from the replay file's `checkpoints` field. They \
differ between replays, and the ticks used for grading are not the ticks published \
in `expected_*.json`.

## Deliverable

Write your simulator to `{submission}`. It must be a single self-contained \
Python 3 file that runs with the system interpreter and the standard library only. \
Every visible replay must reproduce every published hash exactly before you are \
finished; there is no partial credit for a simulator that does not.

## How this is graded

Your submission is run against the three visible replays on a checkpoint tick set \
that was not published, and against five held-out replays you have not seen. If \
any visible replay fails to reproduce on the unpublished ticks, the score is 0. \
Otherwise the score is the mean fraction of leading checkpoints your simulator \
reproduces on the held-out replays.

Comparison is exact. There is no tolerance.

Do not modify anything under `input/`. Do not rely on internet access.
"""

    def to_metadata(self) -> dict:
        m = super().to_metadata()
        m.update({
            "submission_path": self.submission_path,
            "eval_dir": EVAL_DIR,
            "per_replay_timeout_s": PER_REPLAY_TIMEOUT_S,
        })
        return m


config = TaskConfig()


@cb.tasks_config(split="train")
def load():
    cfg = TaskConfig()
    description = (
        cfg.task_description
        .replace("{input}", cfg.input_dir)
        .replace("{submission}", cfg.submission_path)
    )
    return [cb.Task(
        description=description,
        metadata=cfg.to_metadata(),
        computer={
            "provider": "computer",
            "setup_config": {"os_type": cfg.OS_TYPE},
        },
    )]


@cb.setup_task(split="train")
async def start(task_cfg, session: cb.DesktopSession):
    """Write the visible inputs, clear the output directory, confirm nothing leaked."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir = meta["input_dir"]
    out_dir = meta["remote_output_dir"]
    ref_dir = meta["reference_dir"]

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(
        f"mkdir -p {input_dir!r}/starter {input_dir!r}/replays {out_dir!r}", check=True
    )

    for rel, src in INPUT_FILES.items():
        await session.write_file(f"{input_dir}/{rel}", src.read_text(encoding="utf-8"))

    # The starter must be present and runnable, otherwise the agent has nothing
    # to bisect against and every run would score 0 for an infrastructure reason.
    probe = await session.run_command(
        f"cd {input_dir!r} && python3 starter/sim.py replays/replay_0.json | head -1",
        check=False,
    )
    if not (probe.get("stdout") or "").strip():
        raise RuntimeError(
            "staged starter did not produce checkpoint output: "
            f"rc={probe.get('return_code')} stderr={(probe.get('stderr') or '')[:400]}"
        )

    # Reference correctly hidden: no held-out replay and no expected-hash file for
    # them exists anywhere on this machine while the agent works.
    leak = await session.run_command(
        f"grep -rl --binary-files=without-match holdout_ {input_dir!r} 2>/dev/null; "
        f"ls {ref_dir!r} 2>/dev/null",
        check=False,
    )
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference leaked onto the VM: {leak.get('stdout')[:400]}")
    logger.info("[lockstep] staged %d input files; reference correctly hidden",
                len(INPUT_FILES))


def _eval_replays() -> dict[str, str]:
    """The replay set the grader runs, as {filename: json text}.

    Visible replays are re-issued on the gate checkpoint ticks, which are
    published nowhere, so a submission that memorised `expected_*.json` fails the
    gate instead of passing it. Held-out replays carry the scored ticks.
    """
    out: dict[str, str] = {}
    for name in _EXPECTED["visible_gate"]:
        replay = json.loads((DATA / "visible" / f"{name}.json").read_text(encoding="utf-8"))
        replay["checkpoints"] = _EXPECTED["gate_checkpoints"]
        out[f"{name}.json"] = json.dumps(replay)
    for name in _EXPECTED["holdout"]:
        replay = json.loads((DATA / "reference" / f"{name}.json").read_text(encoding="utf-8"))
        replay["checkpoints"] = _EXPECTED["scored_checkpoints"]
        out[f"{name}.json"] = json.dumps(replay)
    return out


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submission over the gate and held-out replays; score host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "lockstep_desync_repro_grade", SCRIPTS / "grade.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    meta = task_cfg.metadata
    submission = meta["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[lockstep] no submission at %s", submission)
        return [0.0]

    replay_dir = f"{EVAL_DIR}/replays"
    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {replay_dir!r}", check=True)
    for filename, text in _eval_replays().items():
        await session.write_file(f"{replay_dir}/{filename}", text)
    await session.write_file(
        f"{EVAL_DIR}/eval_runner.py",
        (SCRIPTS / "eval_runner.py").read_text(encoding="utf-8"),
    )

    result = await session.run_command(
        f"python3 {EVAL_DIR}/eval_runner.py {submission!r} {replay_dir!r} "
        f"{PER_REPLAY_TIMEOUT_S}",
        timeout=RUNNER_TIMEOUT_S,
        check=False,
    )
    stdout = (result.get("stdout") or "").strip()
    if result.get("return_code") != 0 or not stdout:
        logger.error("[lockstep] eval runner failed: rc=%s stderr=%s",
                     result.get("return_code"), (result.get("stderr") or "")[:600])
        return [0.0]
    try:
        results = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.error("[lockstep] eval runner output unparseable: %s", exc)
        return [0.0]

    report = grade.score(results, _EXPECTED)
    logger.info("[lockstep] gate_pass=%s holdout=%.3f score=%.3f detail=%s",
                report["gate_pass"], report["holdout_fraction"], report["score"],
                json.dumps({"gate": report["gate"], "holdout": report["holdout"]}))
    return [float(report["score"])]
