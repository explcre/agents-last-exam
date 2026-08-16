"""AgentHLE task: computing_math/undocumented_pipeline_recovery.

Recover an undocumented revenue pipeline from its inputs and outputs.

A reporting pipeline runs nightly over four source tables and produces one result
table. Its source is gone. The agent is given twelve datasets with both the inputs
and the table the pipeline produced from them, and must write SQL that reproduces
the same table on datasets it has never seen.

This is the shape of a real migration: the outputs are trusted and reconciled
against, the code that made them is not available, and the replacement has to agree
on data that has not been seen yet. The pipeline embeds ten decisions that are
invisible from a single output but that each change the numbers, and every one of
them is witnessed in the worked examples.

All task data is written by ``start()``. Nothing is baked into an image and nothing
is fetched at run time.
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
DATA = TASK_DIR / "data"
ASSETS = TASK_DIR / "assets"
SCRIPTS = TASK_DIR / "scripts"

DOMAIN_NAME = "computing_math"
TASK_NAME = "undocumented_pipeline_recovery"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/undocumented_pipeline_recovery"
CASE_TIMEOUT_S = 300.0

SOURCE_TABLES = ("orders", "customers", "refunds", "payments", "fx_rates")
_CASES = sorted(p.name for p in (DATA / "cases").iterdir() if p.is_dir())
_HOLDOUT = sorted(p.name for p in (DATA / "holdout").iterdir() if p.is_dir())


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/solution.sql"

    @property
    def task_description(self) -> str:
        return """\
Recover a reporting pipeline that no longer has any source code.

A nightly job read four tables and wrote one result table. The job is gone; its \
outputs are not. Under `{input}/cases` are twelve datasets, each holding the four \
source tables the job read and the `expected.csv` it produced from them. Nothing \
else about the job survives: no specification, no schema document, no comments.

## The source tables

- `orders(order_id, customer_id, placed_at, amount_cents, currency, status)`
- `customers(customer_id, region, tier, signed_up_at)`
- `refunds(refund_id, order_id, refunded_at, amount_cents)`
- `payments(payment_id, customer_id, paid_at, amount_cents, currency, method)`
- `fx_rates(currency, day, rate_to_usd)`

Amounts are integer minor units in each row's own currency. The source data is \
real-shaped rather than clean: read it carefully before assuming anything. Note \
that payments are not tied to particular orders, and that the result is not simply \
an aggregate of the orders table.

## What you write

`{submission}`, a DuckDB SQL script. It is run with the four source tables already \
loaded under those names, and must leave a table called `result` holding the same \
rows the pipeline produced. Column names, column order and row values all count. \
You may create intermediate tables or views; only `result` is read.

Test locally with `duckdb`, which is installed:

    duckdb -c "
      CREATE TABLE orders    AS SELECT * FROM read_csv_auto('cases/ds_7001/orders.csv');
      CREATE TABLE customers AS SELECT * FROM read_csv_auto('cases/ds_7001/customers.csv');
      CREATE TABLE refunds   AS SELECT * FROM read_csv_auto('cases/ds_7001/refunds.csv');
      CREATE TABLE payments  AS SELECT * FROM read_csv_auto('cases/ds_7001/payments.csv');
      CREATE TABLE fx_rates  AS SELECT * FROM read_csv_auto('cases/ds_7001/fx_rates.csv');
      .read output/solution.sql
      SELECT * FROM result ORDER BY ALL;"

## How this is graded

Your script is run against held-out datasets you have not seen, generated the same \
way as the twelve you have. For each, the `result` table is compared with the one \
the pipeline produced, as a multiset of rows including the header.

Most of the score is the fraction of held-out datasets reproduced **exactly**; the \
remainder is row-level agreement, so partial progress shows. Matching the twelve \
worked examples is not the task: the same script has to hold on data you cannot \
see.

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
    """Stage the worked datasets; confirm the pipeline and held-out answers did not leak."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r}/cases {out_dir!r}", check=True)
    for case in _CASES:
        await session.run_command(f"mkdir -p {input_dir!r}/cases/{case}", check=True)
        for name in (*SOURCE_TABLES, "expected"):
            src = DATA / "cases" / case / f"{name}.csv"
            await session.write_file(f"{input_dir}/cases/{case}/{name}.csv",
                                     src.read_text(encoding="utf-8"))

    # The pipeline's own SQL must not be on the machine, and neither must any
    # held-out answer. Probe on a distinctive line of the first held-out result.
    probe = (DATA / "holdout" / _HOLDOUT[0] / "expected.csv").read_text(
        encoding="utf-8").splitlines()[1]
    leak = await session.run_command(
        f"grep -rlF {probe!r} {input_dir!r} 2>/dev/null; "
        f"grep -rlE 'ASOF JOIN|cum_supply|cum_demand' {input_dir!r} 2>/dev/null; ls {ref_dir!r} 2>/dev/null",
        check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference material leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[pipeline] staged %d worked datasets; %d held out host side",
                len(_CASES), len(_HOLDOUT))


def _runner_sql(case_dir: str, submission: str) -> str:
    """A script that loads one dataset, applies the submission, and dumps `result`."""
    loads = "\n".join(
        f"CREATE TABLE {t} AS SELECT * FROM read_csv_auto('{case_dir}/{t}.csv');"
        for t in SOURCE_TABLES)
    return loads + f"\n.read {submission}\n"


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted SQL over the held-out datasets; compare host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("pipe_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[pipeline] no submission at %s", submission)
        return [0.0]

    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)

    produced: dict[str, str] = {}
    expected: dict[str, str] = {}
    for case in _HOLDOUT:
        case_dir = f"{EVAL_DIR}/{case}"
        await session.run_command(f"mkdir -p {case_dir!r}", check=True)
        for name in SOURCE_TABLES:
            await session.write_file(
                f"{case_dir}/{name}.csv",
                (DATA / "holdout" / case / f"{name}.csv").read_text(encoding="utf-8"))
        expected[case] = (DATA / "holdout" / case / "expected.csv").read_text(encoding="utf-8")

        script = f"{case_dir}/run.sql"
        out_csv = f"{case_dir}/result.csv"
        await session.write_file(script, _runner_sql(case_dir, submission) +
                                 f"COPY (SELECT * FROM result ORDER BY ALL) "
                                 f"TO '{out_csv}' (HEADER, DELIMITER ',');\n")
        r = await session.run_command(
            f"duckdb -init /dev/null -batch < {script!r}",
            timeout=CASE_TIMEOUT_S, check=False)
        if r.get("return_code") != 0:
            logger.info("[pipeline] %s failed: %s", case, (r.get("stderr") or "")[:200])
            continue
        if await session.file_exists(out_csv):
            produced[case] = await session.read_file(out_csv)

    report = grade.score(produced, expected)
    logger.info("[pipeline] exact=%d/%d mean_f1=%.3f reward=%.3f",
                report["exact"], report["cases"], report["mean_f1"], report["reward"])
    return [float(report["reward"])]
