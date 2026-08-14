"""Host-side scoring for computing_math/eval_harness_leakage_audit.

Two halves, because finding a defect and proving you found it are different
skills and the second is the one benchmarks usually skip.

  fixes   fraction of the planted defects the submitted harness no longer
          exhibits, under black-box probes. Halved if the repair also rewrote
          behaviour that was never defective, which the REG guard checks.
  kills   fraction of single-defect mutants the submitted test suite detects. A
          test that passes on a harness carrying a known defect did not test for
          it, however confidently the write-up claims otherwise.

The kills half is gated: the suite must pass on a known-correct harness. Without
that gate a suite of `assert False` kills every mutant and proves nothing.

Nothing inspects the agent's source. A fix is judged by behaviour and a test by
what it detects.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

TEST_TIMEOUT_S = 300.0


def run_suite(test_file: pathlib.Path, harness_src: str) -> int | None:
    """Run the agent's suite against a given harness. Returns the exit code.

    The harness under test is placed beside the suite as `harness.py`, which is
    the import contract stated in the task prompt. None means the run could not
    be completed at all.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "harness.py").write_text(harness_src, encoding="utf-8")
        shutil.copy(test_file, d / "test_audit.py")
        try:
            proc = subprocess.run([sys.executable, "test_audit.py"], cwd=d,
                                  capture_output=True, text=True,
                                  timeout=TEST_TIMEOUT_S, check=False)
            return proc.returncode
        except subprocess.TimeoutExpired:
            return None
        except Exception:  # noqa: BLE001 - a broken suite is a score, not an error
            return None


def score(probe_results: dict[str, bool],
          suite_on_reference: int | None,
          suite_on_candidate: int | None,
          suite_on_mutants: dict[str, int | None]) -> dict:
    """Combine the two halves into a report.

    ``suite_on_*`` are exit codes: 0 means the suite passed on that harness.
    """
    # REG is a guard, not a planted defect: a repair that gratuitously rewrites
    # behaviour that was never broken is a different failure, and a real one.
    guard_ok = probe_results.get("REG", True)
    defects = {d: ok for d, ok in probe_results.items() if d != "REG"}
    fixed = [d for d, ok in defects.items() if ok]
    fixes = (len(fixed) / len(defects)) if defects else 0.0
    # A repair that rewrote unrelated behaviour is halved rather than zeroed:
    # it is a real failure, but not the same failure as not repairing anything.
    # Halving also leaves a do-nothing submission at zero rather than giving the
    # guard away as a free point.
    if not guard_ok:
        fixes *= 0.5

    # A suite that cannot pass on a correct harness is not measuring properties
    # of the pipeline, so its kills do not count.
    gate = suite_on_reference == 0 and suite_on_candidate == 0
    killed = [d for d, rc in suite_on_mutants.items() if rc is not None and rc != 0]
    kills = (len(killed) / len(suite_on_mutants)) if (gate and suite_on_mutants) else 0.0

    return {
        "probes": probe_results,
        "regression_guard_passed": guard_ok,
        "defects_fixed": sorted(fixed),
        "defects_remaining": sorted(d for d in defects if d not in fixed),
        "fixes": fixes,
        "suite_gate_passed": gate,
        "suite_on_reference_rc": suite_on_reference,
        "suite_on_candidate_rc": suite_on_candidate,
        "mutants_killed": sorted(killed),
        "mutants_survived": sorted(d for d in suite_on_mutants if d not in killed),
        "kills": kills,
        "score": 0.5 * fixes + 0.5 * kills,
    }


def report(rep: dict) -> str:
    lines = [
        f"fixes  {rep['fixes']:.2f}   remaining: {rep['defects_remaining'] or 'none'}"
        + ("" if rep.get("regression_guard_passed", True)
           else "   (guard failed: unrelated behaviour was rewritten)"),
        f"kills  {rep['kills']:.2f}   survived : {rep['mutants_survived'] or 'none'}"
        + ("" if rep["suite_gate_passed"] else "   (gate failed: suite does not pass"
                                               " on a correct harness)"),
        f"score  {rep['score']:.3f}",
    ]
    return "\n".join(lines)
