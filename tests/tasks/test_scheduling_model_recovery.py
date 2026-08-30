"""End-to-end checks for computing_math/scheduling_model_recovery.

These drive the task's real ``start()`` and ``evaluate()`` hooks against a local
session that runs bash and keeps files on disk. The tests that need a CP-SAT solver
are skipped when OR-Tools is absent; the grader and fairness tests do not need it.

The fairness tests here assert the property the task's difficulty claim rests on:
every rule is demonstrated in the worked runs, and every rule is tested by the graded
runs. A rule the worked runs never exercise would be unguessable rather than hard, and
a rule the graded runs never test would hand full marks to a model that got it wrong.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import types

import pytest

from tasks.computing_math.scheduling_model_recovery import main as task
from tasks.computing_math.scheduling_model_recovery.scripts import grade

REPO_VENV_BIN = pathlib.Path(__file__).resolve().parents[2] / ".venv" / "bin"
try:
    from ortools.sat.python import cp_model  # noqa: F401
    HAVE_ORTOOLS = True
except ImportError:
    HAVE_ORTOOLS = False


class LocalSession:
    async def run_command(self, command, *, check=False, timeout=None):
        env = {"PATH": f"{REPO_VENV_BIN}:/usr/bin:/bin"}
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


def _disc():
    return json.loads((task.DATA / "discrimination.json").read_text(encoding="utf-8"))


def test_start_stages_both_sets_and_strips_the_answers(staged):
    d = pathlib.Path(staged.metadata["input_dir"])
    worked = json.loads((d / "worked_runs.json").read_text())
    hold = json.loads((d / "holdout_runs.json").read_text())
    assert len(worked) == 60 and len(hold) == 25
    assert all("makespan" in r for r in worked), "the worked runs must carry their answers"
    assert not any("makespan" in r for r in hold), "a graded answer was staged"
    for r in worked + hold:
        assert set(r) >= {"id", "machines", "speed", "jobs", "setup", "transport",
                          "maintenance", "horizon"}


def test_no_graded_answer_or_rule_name_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file())
    for giveaway in ("lag_den", "speed_round", "setup_at_start", "DEFAULT_RULES",
                     "reference_scheduler", "LAG_NUM"):
        assert giveaway not in text, f"the model leaked: {giveaway}"


def test_worked_and_graded_runs_are_disjoint():
    worked, hold = task._worked(), task._holdout()
    assert not ({r["id"] for r in worked} & {r["id"] for r in hold})

    def shape(r):
        return json.dumps({k: v for k, v in r.items() if k not in ("id", "makespan")},
                          sort_keys=True)
    assert not ({shape(r) for r in worked} & {shape(r) for r in hold}), \
        "a graded run duplicates a worked one"


def test_every_rule_is_demonstrated_in_the_worked_runs():
    """Fairness. A rule no worked run exercises could not be inferred from the log."""
    d = _disc()
    counts = {rule: sum(1 for sig in d["worked"].values() if rule in sig)
              for rule in d["rules"]}
    thin = {r: n for r, n in counts.items() if n < 5}
    assert not thin, f"rules barely demonstrated in the worked runs: {thin}"


def test_every_rule_is_tested_by_the_graded_runs():
    """Discrimination. A rule the graded runs cannot see would be worth free marks.

    ``discrimination.json`` records, per run, which single-rule errors change its
    makespan. Each rule must move a large share of the graded runs, so that a model
    with that one rule wrong cannot score well.
    """
    d = _disc()
    n = len(d["holdout"])
    for rule in d["rules"]:
        hit = sum(1 for sig in d["holdout"].values() if rule in sig)
        assert hit >= 0.6 * n, (
            f"{rule} only changes {hit}/{n} graded runs, so a model with it wrong "
            f"would still score {1 - hit / n:.2f}")


def test_the_recorded_discrimination_matches_the_shipped_runs():
    """The evidence file must describe the runs actually shipped, not an older corpus."""
    d = _disc()
    assert set(d["worked"]) == {r["id"] for r in task._worked()}
    assert set(d["holdout"]) == {r["id"] for r in task._holdout()}


def test_the_reference_answers_score_one():
    exp = task._expected()
    assert grade.score(dict(exp), exp)["reward"] == 1.0


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


def test_malformed_results_score_zero_without_raising():
    exp = task._expected()
    for junk in ({}, None, {k: None for k in exp}, {k: "x" for k in exp},
                 {k: True for k in exp}, {k: 12.5 for k in exp}):
        assert grade.score(junk, exp)["reward"] == 0.0


def test_a_constant_answer_scores_almost_nothing():
    """The cheapest shortcut: return one number and hope the spread is narrow."""
    exp = task._expected()
    for guess in (0, 1, 50, 999):
        assert grade.score({k: guess for k in exp}, exp)["reward"] < 0.15, guess


def test_copying_a_worked_answer_scores_almost_nothing():
    """The other cheap shortcut: reuse the log rather than rebuild the model."""
    exp = task._expected()
    worked = task._worked()
    copied = {k: worked[i % len(worked)]["makespan"] for i, k in enumerate(sorted(exp))}
    assert grade.score(copied, exp)["reward"] < 0.15


@pytest.mark.skipif(not HAVE_ORTOOLS, reason="ortools not installed on this host")
def test_the_shipped_answers_are_what_the_reference_model_produces():
    """Guard against data drift: re-solve some graded runs and compare with the file.

    If the shipped answers ever stopped matching the reference model, the task would
    be grading against numbers nothing produces.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ref_sched", task.ASSETS / "reference_scheduler.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for run in task._holdout()[:6]:
        stripped = {k: v for k, v in run.items() if k != "makespan"}
        assert ref.optimal_makespan(stripped) == run["makespan"], run["id"]


@pytest.mark.skipif(not HAVE_ORTOOLS, reason="ortools not installed on this host")
def test_the_reference_scheduler_scores_one_end_to_end(staged):
    """The control that matters: the reference module, through evaluate()."""
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text((task.ASSETS / "reference_scheduler.py").read_text(encoding="utf-8"),
                   encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [1.0]


@pytest.mark.skipif(not HAVE_ORTOOLS, reason="ortools not installed on this host")
def test_a_submission_that_raises_scores_zero_without_raising(staged):
    sub = pathlib.Path(staged.metadata["submission_path"])
    sub.parent.mkdir(parents=True, exist_ok=True)
    sub.write_text("def optimal_makespan(run):\n    raise RuntimeError('nope')\n",
                   encoding="utf-8")
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


@pytest.mark.skipif(not HAVE_ORTOOLS, reason="ortools not installed on this host")
def test_the_model_is_recoverable_from_the_published_log():
    """Solvability, executed rather than asserted.

    That a solving program exists is not enough, because the reference scheduler was
    written by someone who already knew the rules. This fits candidate cooling lags
    against the worked runs alone and checks that the log selects exactly the right
    one. The cooling lag is the rule both calibrated agents missed, so it is the part
    of the claim most worth guarding.

    The full search over all 3456 models lives in ``assets/recovery_search.py``. It
    finds two survivors, the same model written two ways, both scoring 25/25 on the
    graded runs, and 8 worked runs are enough to get there.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "recovery", task.ASSETS / "recovery_search.py")
    rec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rec)

    base = {"round": "ceil", "start_setup": True, "transport": True,
            "crew": 1, "maint": True, "setup": True}
    worked = task._worked()[:8]
    fits = []
    for kind, param in ([("none", None)]
                        + [("prop", (1, b)) for b in (2, 3, 4, 5, 6, 8)]
                        + [("const", c) for c in (1, 2, 3)]):
        r = dict(base, lag_kind=kind, lag_param=param)
        if all(rec.solve(run, r) == run["makespan"] for run in worked):
            fits.append((kind, param))
    assert fits == [("prop", (1, 4))], (
        f"the worked log should select exactly the cooling lag ceil(d/4); it left {fits}")
