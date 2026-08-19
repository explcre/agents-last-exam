"""End-to-end checks for computing_math/eval_harness_leakage_audit.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk, so staging, the leak check and
the host-side grader are all exercised without a VM.
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import subprocess
import types

import pytest

from tasks.computing_math.eval_harness_leakage_audit import main as task
from tasks.computing_math.eval_harness_leakage_audit.scripts import probes

ASSETS = task.ASSETS
ORACLE_SUITE = ASSETS / "oracle_suite.py"


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


def _defects():
    import importlib.util
    spec = importlib.util.spec_from_file_location("d", ASSETS / "defects.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_start_stages_a_harness_whose_own_suite_passes(staged):
    """The premise of the task: the shipped tests are green and insufficient."""
    d = pathlib.Path(staged.metadata["input_dir"])
    assert (d / "harness.py").is_file() and (d / "test_suite.py").is_file()
    r = subprocess.run(["python3", "test_suite.py"], cwd=d,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout[-600:]


def test_the_staged_harness_actually_carries_every_defect(staged):
    d = pathlib.Path(staged.metadata["input_dir"])
    results = probes.run_all(d / "harness.py")
    assert not any(results.values()), f"a defect is missing from the starter: {results}"


def test_reference_is_not_on_the_machine(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for giveaway in ("fitted on training rows only",
                     "appears in exactly one of train",
                     "selected by validation loss",
                     "constant predictor scores 0.5",
                     "Each arm gets its own generator"):
        assert giveaway not in text, f"the starter states the answer in prose: {giveaway!r}"
    assert "Preprocessor().fit(rows_tr)\n" not in text, "the corrected call is visible"


def test_every_probe_detects_its_own_defect():
    d = _defects()
    ref = (ASSETS / "harness_reference.py").read_text()
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        for did, ids in d.GROUPS.items():
            p = pathlib.Path(t) / f"{did}.py"
            p.write_text(d.apply(ref, only=ids))
            assert probes.run_all(p)[did] is False, f"probe {did} misses its own defect"


def test_reference_passes_every_probe():
    assert all(probes.run_all(ASSETS / "harness_reference.py").values())


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_repairing_without_proving_scores_half(staged):
    """The distinction the task exists to measure."""
    out = pathlib.Path(staged.metadata["harness_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "harness_reference.py", out)
    pathlib.Path(staged.metadata["suite_path"]).write_text(
        "import harness\nprint('ok')\n", encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.5]


def test_a_suite_that_always_fails_earns_no_kills(staged):
    out = pathlib.Path(staged.metadata["harness_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "harness_reference.py", out)
    pathlib.Path(staged.metadata["suite_path"]).write_text(
        "import sys\nsys.exit(1)\n", encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.5]


@pytest.mark.skipif(not ORACLE_SUITE.exists(), reason="oracle suite not present")
def test_full_solution_scores_one(staged):
    out = pathlib.Path(staged.metadata["harness_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ASSETS / "harness_reference.py", out)
    shutil.copy(ORACLE_SUITE, staged.metadata["suite_path"])
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]
