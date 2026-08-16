"""End-to-end checks for computing_math/undocumented_pipeline_recovery.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk. The tests that need DuckDB are
skipped when it is absent, so the suite still runs on a machine without it; the
grader tests do not need it at all.
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import subprocess
import types

import pytest

from tasks.computing_math.undocumented_pipeline_recovery import main as task
from tasks.computing_math.undocumented_pipeline_recovery.scripts import grade

DUCKDB = shutil.which("duckdb") or "/tmp/galaxy_srv_disk00/pengchx3/etl/duckdb"
HAVE_DUCKDB = pathlib.Path(DUCKDB).exists()


class LocalSession:
    async def run_command(self, command, *, check=False, timeout=None):
        env = {"PATH": f"{pathlib.Path(DUCKDB).parent}:/usr/bin:/bin"}
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


def _expected():
    return {c: (task.DATA / "holdout" / c / "expected.csv").read_text(encoding="utf-8")
            for c in task._HOLDOUT}


def test_start_stages_every_worked_dataset(staged):
    root = pathlib.Path(staged.metadata["input_dir"]) / "cases"
    assert sorted(p.name for p in root.iterdir()) == task._CASES
    for case in task._CASES:
        for name in (*task.SOURCE_TABLES, "expected"):
            assert (root / case / f"{name}.csv").is_file(), f"{case}/{name}"


def test_no_held_out_answer_and_no_pipeline_source_reach_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for case, csv_text in _expected().items():
        body = csv_text.splitlines()[1:]
        assert body and body[0] not in text, f"held-out answer for {case} is on the VM"
    for giveaway in ("ASOF JOIN", "INTERVAL 30 DAY", "row_number() OVER"):
        assert giveaway not in text, f"the pipeline's own SQL leaked: {giveaway}"


def test_worked_and_held_out_datasets_are_disjoint():
    assert not (set(task._CASES) & set(task._HOLDOUT))
    assert len(task._CASES) >= 10 and len(task._HOLDOUT) >= 6


def test_reference_outputs_are_reproduced_exactly_by_themselves():
    """The positive control at the grader level: the reference tables score 1.0."""
    exp = _expected()
    assert grade.score(dict(exp), exp)["reward"] == 1.0


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_malformed_results_score_zero_without_raising():
    exp = _expected()
    for junk in ({}, {c: "" for c in exp}, {c: "not,a,valid\ncsv,row" for c in exp},
                 {c: None for c in exp}):
        assert grade.score(junk, exp)["reward"] == 0.0


def test_an_empty_table_scores_zero():
    """The cheapest shortcut: produce the right columns and no rows."""
    exp = _expected()
    header = {c: v.splitlines()[0] + "\n" for c, v in exp.items()}
    assert grade.score(header, exp)["reward"] < 0.05


def test_row_multiset_not_set(staged):
    """Duplicating a row is a real error and must not be hidden by set comparison."""
    exp = _expected()
    doubled = {}
    for c, v in exp.items():
        lines = v.splitlines()
        doubled[c] = "\n".join([lines[0], lines[1], *lines[1:]]) + "\n"
    r = grade.score(doubled, exp)
    assert r["exact"] == 0


@pytest.mark.skipif(not HAVE_DUCKDB, reason="duckdb not installed on this host")
def test_the_reference_pipeline_scores_one_end_to_end(staged, tmp_path):
    """The control that matters: the pipeline itself, run through evaluate()."""
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text((task.ASSETS / "reference.sql").read_text(encoding="utf-8"),
                   encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]
