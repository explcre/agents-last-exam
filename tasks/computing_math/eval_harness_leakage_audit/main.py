"""AgentHLE task: computing_math/eval_harness_leakage_audit.

Audit a machine learning evaluation harness that reports plausible numbers and
passes its own tests, and whose numbers are wrong.

The agent must both repair the pipeline and produce a test suite that
demonstrates each repair, where demonstrating means the suite detects a harness
that still carries the defect. Half the score is the repair and half is the
proof, because finding a defect and proving you found it are different skills
and benchmarks usually only measure the first.

All task data is written by ``start()``. Nothing is baked into an image and
nothing is fetched at run time. The reference harness never reaches the VM.
"""

from __future__ import annotations

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
SCRIPTS = TASK_DIR / "scripts"

DOMAIN_NAME = "computing_math"
TASK_NAME = "eval_harness_leakage_audit"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/eval_harness_leakage_audit"


def _reference() -> str:
    return (ASSETS / "harness_reference.py").read_text(encoding="utf-8")


def _starter() -> str:
    import importlib.util
    spec = importlib.util.spec_from_file_location("elha_defects", ASSETS / "defects.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the defect table")
    defects = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(defects)
    return defects.make_starter(_reference())


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def harness_path(self) -> str:
        return f"{self.remote_output_dir}/harness.py"

    @property
    def suite_path(self) -> str:
        return f"{self.remote_output_dir}/test_audit.py"

    @property
    def task_description(self) -> str:
        return """\
An evaluation harness reports that a readmission risk model reaches a good \
headline score, and that a treatment arm beats its control. The pipeline runs, \
the numbers look reasonable, and its test suite passes.

The numbers are wrong. The harness contains defects that corrupt what it \
measures while leaving it running and plausible.

## What you are given, under `{input}`

- `harness.py`: the pipeline. Grouped split, imputation and scaling, logistic \
regression with early stopping, and a treatment versus control comparison.
- `test_suite.py`: its existing tests. They pass. They are not sufficient.
- `run.sh`: runs the harness and prints its report.

## What you must produce

1. `{harness}`: the repaired pipeline. It must keep the same public surface, \
because it is exercised programmatically: `make_dataset`, `split`, \
`Preprocessor` with `fit` and `transform`, `train`, `predict`, `run_arm(rows_tr, \
rows_va, rows_te, arm_seed, drop_feature=None)` returning a dict, and `main()` \
printing a JSON report with a `headline` field.

2. `{suite}`: a test suite that **demonstrates** each repair. It must be \
runnable as `python3 test_audit.py`, exiting 0 when every check passes and \
non-zero otherwise. It must import the pipeline as `import harness`, because it \
will be run against pipelines other than yours.

## How this is graded

Two halves, each worth half the score.

- **Repair.** Your harness is exercised by hidden behavioural probes. Nothing \
reads your source; a defect counts as repaired when the pipeline stops \
exhibiting it.
- **Proof.** Your suite is run against several harnesses, each carrying exactly \
one of the original defects. A defect counts as demonstrated when your suite \
fails on the harness that still has it. Your suite must also pass on a \
known-correct harness, so a suite that always fails earns nothing.

A repair you cannot demonstrate is worth half of one you can.

Do not modify anything under `input/`. Do not rely on internet access.
"""

    def to_metadata(self) -> dict:
        m = super().to_metadata()
        m.update({"harness_path": self.harness_path, "suite_path": self.suite_path,
                  "eval_dir": EVAL_DIR})
        return m


@cb.tasks_config(split="train")
def load():
    cfg = TaskConfig()
    description = (cfg.task_description
                   .replace("{input}", cfg.input_dir)
                   .replace("{harness}", cfg.harness_path)
                   .replace("{suite}", cfg.suite_path))
    return [cb.Task(
        description=description,
        metadata=cfg.to_metadata(),
        computer={"provider": "computer", "setup_config": {"os_type": cfg.OS_TYPE}},
    )]


@cb.setup_task(split="train")
async def start(task_cfg, session: cb.DesktopSession):
    """Write the defective harness and its passing test suite."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r} {out_dir!r}", check=True)

    starter = _starter()
    await session.write_file(f"{input_dir}/harness.py", starter)
    await session.write_file(f"{input_dir}/test_suite.py",
                             (ASSETS / "existing_tests.py").read_text(encoding="utf-8"))
    await session.write_file(
        f"{input_dir}/run.sh",
        f"#!/usr/bin/env bash\nset -eu\ncd {input_dir!r}\npython3 harness.py\n")

    probe = await session.run_command(
        f"cd {input_dir!r} && python3 harness.py >/dev/null && python3 test_suite.py",
        check=False)
    if probe.get("return_code") != 0:
        raise RuntimeError(
            "the staged harness must run and its suite must pass: "
            f"rc={probe.get('return_code')} {(probe.get('stderr') or '')[:400]}")

    # Reference correctly hidden: the corrected pipeline is never on the machine.
    # A phrase that exists only in the corrected pipeline: the docstrings that
    # state the intended behaviour are stripped from the build the agent sees.
    marker = "fitted on training rows only"
    leak = await session.run_command(
        f"grep -rl --binary-files=without-match {marker!r} {input_dir!r} 2>/dev/null; "
        f"ls {ref_dir!r} 2>/dev/null", check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[audit] staged the defective harness; its suite passes; reference hidden")


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Probe the repaired harness and run the agent's suite against the mutants."""
    import importlib.util
    import tempfile

    def _load(path, name):
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    grade = _load(SCRIPTS / "grade.py", "elha_grade")
    probes = _load(SCRIPTS / "probes.py", "elha_probes")
    defects = _load(ASSETS / "defects.py", "elha_defects")

    meta = task_cfg.metadata
    harness_p, suite_p = meta["harness_path"], meta["suite_path"]
    if not await session.file_exists(harness_p):
        logger.info("[audit] no harness at %s", harness_p)
        return [0.0]

    candidate = await session.read_file(harness_p)
    suite_src = await session.read_file(suite_p) if await session.file_exists(suite_p) else None

    reference = _reference()
    mutants = {d: defects.apply(reference, only=ids) for d, ids in defects.GROUPS.items()}

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        cand_file = tmp / "candidate.py"
        cand_file.write_text(candidate, encoding="utf-8")
        probe_results = probes.run_all(cand_file)

        if suite_src is None:
            report = grade.score(probe_results, None, None, {})
        else:
            suite_file = tmp / "test_audit.py"
            suite_file.write_text(suite_src, encoding="utf-8")
            report = grade.score(
                probe_results,
                grade.run_suite(suite_file, reference),
                grade.run_suite(suite_file, candidate),
                {d: grade.run_suite(suite_file, m) for d, m in mutants.items()},
            )

    logger.info("[audit] fixes=%.2f kills=%.2f score=%.3f remaining=%s survived=%s",
                report["fixes"], report["kills"], report["score"],
                report["defects_remaining"], report["mutants_survived"])
    return [float(report["score"])]
