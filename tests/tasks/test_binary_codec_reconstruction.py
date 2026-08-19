"""End-to-end checks for computing_math/binary_codec_reconstruction.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk. The positive control submits the
reference codec itself, which is the only thing that proves the byte-exact half is
reachable at all.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import types

import pytest

from tasks.computing_math.binary_codec_reconstruction import main as task
from tasks.computing_math.binary_codec_reconstruction.scripts import grade


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


def _expected():
    out = {}
    for name in task._HOLDOUT:
        blob = (task.DATA / "holdout" / f"{name}.bin").read_bytes()
        doc = json.loads((task.DATA / "holdout" / f"{name}.json").read_text())
        out[name] = {"doc": doc, "hex": blob.hex()}
    return out


def test_start_stages_the_samples_as_real_binaries(staged):
    root = pathlib.Path(staged.metadata["input_dir"]) / "samples"
    for name in task._SAMPLES:
        b = root / f"{name}.bin"
        assert b.is_file() and (root / f"{name}.json").is_file(), name
        assert b.read_bytes()[:4] == b"TLG1", f"{name} did not survive staging as bytes"
        assert not (root / f"{name}.hex").exists(), "the hex shim was left behind"


def test_no_held_out_file_or_codec_source_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for name in task._HOLDOUT:
        h = (task.DATA / "holdout" / f"{name}.bin").read_bytes().hex()[:60]
        assert h not in text, f"held-out file {name} is on the VM"
    for giveaway in ("LAZY_GAIN", "lz77_compress", "MIN_MATCH"):
        assert giveaway not in text, f"the reference codec leaked: {giveaway}"


def test_samples_and_holdout_are_disjoint():
    assert not (set(task._SAMPLES) & set(task._HOLDOUT))
    assert len(task._SAMPLES) >= 20 and len(task._HOLDOUT) >= 10


def test_the_reference_files_are_self_consistent():
    """Each shipped pair must actually correspond, or the task grades noise."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("ref", task.ASSETS / "reference_codec.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for name in task._SAMPLES[:6] + task._HOLDOUT[:6]:
        folder = "samples" if name in task._SAMPLES else "holdout"
        blob = (task.DATA / folder / f"{name}.bin").read_bytes()
        doc = json.loads((task.DATA / folder / f"{name}.json").read_text())
        assert ref.encode(doc) == blob, f"{name}: shipped bytes are not what encode produces"


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_a_self_consistent_but_wrong_codec_scores_only_the_decode_half():
    """The failure this task exists to catch: round-tripping your own output.

    A codec that decodes correctly but encodes differently is internally consistent
    and still wrong, and must not be able to earn the byte-exact half.
    """
    exp = _expected()
    results = {n: {"decoded": v["doc"], "encoded_hex": (v["hex"][:-2] + "00")}
               for n, v in exp.items()}
    r = grade.score(results, exp)
    assert r["encoded"] == 0
    assert r["reward"] == pytest.approx(0.25)


def test_the_exact_reference_scores_one():
    exp = _expected()
    results = {n: {"decoded": v["doc"], "encoded_hex": v["hex"]} for n, v in exp.items()}
    assert grade.score(results, exp)["reward"] == 1.0


def test_malformed_results_score_zero_without_raising():
    exp = _expected()
    for junk in ({}, {n: None for n in exp}, {n: {"decoded": "x"} for n in exp},
                 {n: {"encoded_hex": 5} for n in exp}):
        assert grade.score(junk, exp)["reward"] == 0.0


def test_the_reference_codec_scores_one_end_to_end(staged):
    """The control that matters: the reference module, through evaluate()."""
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text((task.ASSETS / "reference_codec.py").read_text(encoding="utf-8"),
                   encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]
