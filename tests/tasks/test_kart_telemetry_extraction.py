"""End-to-end checks for visual_media/kart_telemetry_extraction.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk, so staging, the leak check and the
grader are exercised without a VM.

The videos live in ALE's task-data store rather than in this repo, so the tests
fake the staging step by creating empty ``.mp4`` files with the expected names. That
is enough to exercise every code path here: no test in this file decodes video.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import types

import pytest

from tasks.visual_media.kart_telemetry_extraction import main as task
from tasks.visual_media.kart_telemetry_extraction.scripts import grade


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


def _stage_videos(cfg):
    """Stand in for the task-data store, which is what delivers the videos."""
    for split, labels in (("train", task._TRAIN), ("test", task._HOLDOUT)):
        d = pathlib.Path(cfg.input_dir) / split
        d.mkdir(parents=True, exist_ok=True)
        for track in labels:
            (d / f"{track}.mp4").touch()


@pytest.fixture
def staged(tmp_path):
    cfg = task.TaskConfig(REMOTE_ROOT_DIR=str(tmp_path / "root"))
    tc = types.SimpleNamespace(metadata=cfg.to_metadata())
    _stage_videos(cfg)
    asyncio.run(task.start(tc, LocalSession()))
    return tc


def test_start_writes_the_labelled_half(staged):
    labels = json.loads(
        (pathlib.Path(staged.metadata["input_dir"]) / "train" / "labels.json").read_text())
    assert labels == task._TRAIN
    assert len(labels) == 12
    for row in labels.values():
        assert set(row) == {"items_collected", "spinouts", "skid_time"}


def test_start_fails_loudly_when_the_videos_are_missing(tmp_path):
    """A staging failure must not be silently gradeable as a very hard task."""
    cfg = task.TaskConfig(REMOTE_ROOT_DIR=str(tmp_path / "root"))
    tc = types.SimpleNamespace(metadata=cfg.to_metadata())
    with pytest.raises(RuntimeError, match="task data staged"):
        asyncio.run(task.start(tc, LocalSession()))


def test_no_held_out_label_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for track, row in task._HOLDOUT.items():
        assert str(row["skid_time"]) not in text, f"held-out skid_time for {track} is on the VM"


def _track(race_id: str) -> str:
    return race_id.rsplit("_", 1)[0]


def test_the_splits_share_no_track():
    """A track in both halves lets a submission copy its labelled twin."""
    assert not ({_track(r) for r in task._TRAIN} & {_track(r) for r in task._HOLDOUT})


def test_copying_the_labelled_half_scores_near_zero():
    """The exploit this split exists to close, measured rather than assumed.

    Pairing the halves by track scored 0.257 for a submission that decoded no
    video, because a track raced twice yields similar telemetry. With disjoint
    tracks the labelled half carries no per-race information about the graded one,
    so the best copy is a constant and the rank gate rejects it.
    """
    ordered = sorted(task._TRAIN)
    copied = {race: dict(task._TRAIN[ordered[i % len(ordered)]])
              for i, race in enumerate(sorted(task._HOLDOUT))}
    assert grade.score(copied, task._HOLDOUT)["reward"] < 0.10


def test_every_graded_dimension_varies():
    """A dimension with no spread is silently dropped, which would hide a broken split."""
    for field, _ in grade.DIMS:
        values = {row[field] for row in task._HOLDOUT.values()}
        assert len(values) > 1, f"{field} has no spread in the held-out set"


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_malformed_submissions_score_zero_without_raising(staged):
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    for junk in ("not json at all", "[]", '{"hacienda": "twelve"}', '{"hacienda": {}}'):
        sub.write_text(junk, encoding="utf-8")
        assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0], junk


def test_exact_telemetry_scores_one(staged):
    """The positive control: the grading path must reach 1.0 on a correct answer."""
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text(json.dumps(task._HOLDOUT), encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]


def test_a_constant_answer_scores_about_zero():
    """The rank gate exists to stop guessing; measure it rather than assume it."""
    flat = {t: {"items_collected": 10, "spinouts": 3, "skid_time": 55.0}
            for t in task._HOLDOUT}
    assert grade.score(flat, task._HOLDOUT)["reward"] == 0.0


def test_ranking_without_accuracy_earns_almost_nothing():
    """Order the races perfectly but report tenfold values: rank alone is not enough."""
    ranked = {t: {f: row[f] * 10 for f, _ in grade.DIMS}
              for t, row in task._HOLDOUT.items()}
    report = grade.score(ranked, task._HOLDOUT)
    assert all(report[f]["tau"] == 1.0 for f, _ in grade.DIMS)
    assert report["reward"] == 0.0


def test_the_author_baseline_is_reproduced_and_is_weak():
    """Guard the calibration claim: the hand-built extractor scores near zero.

    These are the numbers the packaged extractor produced on this held-out split,
    recorded so that a later change to the metric cannot quietly move the floor
    the task's difficulty claim rests on.
    """
    baseline = json.loads(
        (task.DATA / "author_baseline_predictions.json").read_text(encoding="utf-8"))
    report = grade.score(baseline, task._HOLDOUT)
    assert report["reward"] < 0.10, report
