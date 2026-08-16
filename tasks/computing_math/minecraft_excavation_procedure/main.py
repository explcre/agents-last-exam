"""AgentHLE task: computing_math/minecraft_excavation_procedure.

Infer a procedure from its effects, then write a bot that carries it out.

The agent is shown several worlds before and after a reference bot acted on them,
and is told nothing about what the bot did. It must write a Minecraft bot that
reproduces the same transformation on held-out worlds it has never seen.

The stack is `mineflayer` against a `flying-squid` server, both MIT and both pure
JavaScript, so no proprietary game asset is involved anywhere. The bot under test
connects without operator rights and has to dig for real; the arena is built and
read through the server API, never through the bot.
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
TASK_NAME = "minecraft_excavation_procedure"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/minecraft_excavation_procedure"
EPISODE_TIMEOUT_S = 420.0
RUNNER_TIMEOUT_S = 5400.0

_EXAMPLES = json.loads((DATA / "examples.json").read_text(encoding="utf-8"))
_HOLDOUT = json.loads((DATA / "holdout.json").read_text(encoding="utf-8"))

INPUT_FILES: dict[str, Path] = {
    "examples.json": DATA / "examples.json",
    "runner/episode.js": ASSETS / "episode.js",
    "runner/README.md": ASSETS / "runner_README.md",
}


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/bot.js"

    @property
    def task_description(self) -> str:
        return """\
Work out what a bot did to a world, then write a bot that does the same thing.

Under `{input}` is `examples.json`: several worlds recorded before and after a \
reference bot acted on each one. You are told nothing about what the bot did. The \
transformation is a fixed procedure, identical in every example, and it is the only \
thing that separates `before` from `after`.

## The world

Each world is a 9x9 arena of blocks, one layer, addressed by offset from its centre \
as `"dx,dz"` with `dx` and `dz` from -4 to 4. Cells start as `grass_block` except \
for a handful of markers. `before` and `after` are the full grids.

## What you write

`{submission}`, a CommonJS module exporting `run(arena)`:

    module.exports = { run: async function (arena) { ... } }

`arena` gives you `{centre: [x, y, z], size: 9, host, port, version, username}`. \
Connect with `mineflayer`, act, and return when finished. The arena floor is the \
plane `y = centre[1]`.

Your bot connects **without operator rights**, so server commands are unavailable: \
whatever the procedure does, your bot has to do it by acting in the world. \
`mineflayer` and `flying-squid` are installed, as is Node.

`runner/episode.js` builds a world, runs your bot against it and writes the \
resulting grid, so you can test locally. Run it as \
`node runner/episode.js <seed> <port> <path-to-bot.js> <out.json>`. The seeds used \
for grading are not the seeds in your examples.

## How this is graded

Your bot is run against held-out worlds. For each one, the arena after your bot \
finishes is compared with the arena after the reference bot finished. Half the \
score is the fraction of worlds reproduced **exactly**, cell for cell; the other \
half is the overlap between the set of cells you changed and the set the reference \
changed, so partial credit exists but neither doing nothing nor digging everything \
pays.

Do not modify anything under `input/`. Do not rely on internet access.
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
    """Stage the worked examples and the local runner; confirm nothing hidden leaked."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r}/runner {out_dir!r}", check=True)
    for rel, src in INPUT_FILES.items():
        await session.write_file(f"{input_dir}/{rel}", src.read_text(encoding="utf-8"))

    # The rule is never written down anywhere the agent can read, and no held-out
    # world reaches the VM. Probe on a held-out grid, which is distinctive enough
    # that an accidental match would itself be worth knowing about.
    probe = json.dumps(next(iter(_HOLDOUT.values()))["after"])[:120]
    leak = await session.run_command(
        f"grep -rlF {probe!r} {input_dir!r} 2>/dev/null; ls {ref_dir!r} 2>/dev/null",
        check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"held-out data leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[mc] staged %d examples; %d held-out worlds kept host side",
                len(_EXAMPLES), len(_HOLDOUT))


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted bot over the held-out worlds; compare host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("mc_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    meta = task_cfg.metadata
    submission = meta["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[mc] no submission at %s", submission)
        return [0.0]

    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)
    await session.write_file(f"{EVAL_DIR}/episode.js",
                             (ASSETS / "episode.js").read_text(encoding="utf-8"))

    results: dict[str, dict] = {}
    port = 26500
    for seed in sorted(_HOLDOUT):
        out = f"{EVAL_DIR}/out_{seed}.json"
        r = await session.run_command(
            f"cd {EVAL_DIR!r} && node episode.js {seed} {port} {submission!r} {out!r}",
            timeout=EPISODE_TIMEOUT_S, check=False)
        port += 1
        if r.get("return_code") != 0:
            logger.info("[mc] seed %s runner rc=%s", seed, r.get("return_code"))
            continue
        try:
            results[seed] = json.loads(await session.read_file(out))
        except (json.JSONDecodeError, UnicodeDecodeError, FileNotFoundError) as exc:
            logger.info("[mc] seed %s unreadable: %s", seed, exc)

    report = grade.score(results, _HOLDOUT)
    logger.info("[mc] exact=%d/%d mean_overlap=%.3f reward=%.3f",
                report["exact"], report["seeds"], report["mean_overlap"], report["reward"])
    return [float(report["reward"])]
