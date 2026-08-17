"""AgentHLE task: other/docx_edit_without_collateral_damage.

Apply a house-style pass to Word documents without destroying anything else.

The brief names four changes. Everything else in each document has to survive
untouched: tracked changes, comments and their anchors, footnotes, a content
control, a custom XML part, bookmarks, a hyperlink, an embedded image, numbering and
section properties.

This is the failure mode the task exists for, and it is a real one. A tool that
models paragraphs and runs but not revisions or content controls rewrites the
document on save and silently drops what it does not understand. The output still
opens, still looks broadly right, and has quietly lost the review history.

Grading is exhaustive rather than by sampling: parts the brief does not name must be
byte-identical, and the edited document must be identical to the original once
alignment is normalised away.

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

DOMAIN_NAME = "other"
TASK_NAME = "docx_edit_without_collateral_damage"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/docx_edit_without_collateral_damage"
PER_DOC_TIMEOUT_S = 300.0
CYCLE = "Q1 2026"

_VISIBLE = sorted(p.name for p in (DATA / "visible").glob("doc_*.docx"))
_HOLDOUT = sorted(p.name for p in (DATA / "holdout").glob("doc_*.docx"))


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/restyle.py"

    @property
    def task_description(self) -> str:
        return """\
Apply a house-style pass to Word documents without damaging them.

Under `{input}/documents` are `.docx` files from a review pipeline. They are real \
documents: they carry tracked changes, comments, footnotes, a content control, a \
custom XML part, bookmarks, a hyperlink, an embedded image, numbered lists and \
headers and footers.

## The brief

Exactly four changes, and nothing else:

1. In the main document body, every paragraph is justified (`w:jc` = `both`), \
except paragraphs styled `Heading1` or `Heading2`, which are left-aligned. \
Paragraphs inside tables count as body paragraphs. Paragraphs in headers, footers, \
footnotes and comments are body paragraphs and must not be touched.
2. In `word/styles.xml`, the `Heading1` style's colour becomes `7A2E2E`.
3. In the header, the placeholder `[[CYCLE]]` is replaced with `Q1 2026`.
4. In the footer, the same placeholder is replaced the same way.

**Everything else must survive exactly.** Any package part the brief does not name \
must come out byte-identical to the way it went in. Within the document body, \
nothing may change except paragraph alignment: every revision, comment anchor, \
footnote reference, bookmark, field, drawing and content control has to be where it \
was.

## What you write

`{submission}`, a self-contained Python 3 script, standard library plus `lxml`, \
invoked as

    python3 restyle.py <input.docx> <output.docx>

It must work on documents of this shape that you have not seen, not only the three \
provided.

## How this is graded

Your script is run against held-out documents. For each, two things are checked \
independently: that all four changes were made, and that nothing else moved. Most of \
the score requires both on the same document. A document that opens and looks right \
but has lost its tracked changes scores as a failure, which is the point.

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


async def _put_binary(session, remote: str, blob: bytes) -> None:
    """Write bytes through a text-only session channel without corrupting them."""
    await session.write_file(remote + ".hex", blob.hex())
    await session.run_command(
        f"python3 -c \"import binascii,pathlib;"
        f"p=pathlib.Path('{remote}.hex');"
        f"pathlib.Path('{remote}').write_bytes(binascii.unhexlify(p.read_text().strip()));"
        f"p.unlink()\"", check=True)


@cb.setup_task(split="train")
async def start(task_cfg, session: cb.DesktopSession):
    """Stage the sample documents; confirm no held-out answer reached the VM."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r}/documents {out_dir!r}", check=True)
    for name in _VISIBLE:
        await _put_binary(session, f"{input_dir}/documents/{name}",
                          (DATA / "visible" / name).read_bytes())

    leak = await session.run_command(
        f"ls {input_dir!r}/documents | grep -c '^expected' || true; "
        f"grep -rl '7A2E2E' {input_dir!r} 2>/dev/null; ls {ref_dir!r} 2>/dev/null",
        check=False)
    out = (leak.get("stdout") or "").strip().splitlines()
    if (out and out[0] != "0") or len(out) > 1:
        raise RuntimeError(f"reference material leaked onto the VM: {out}")
    logger.info("[docx] staged %d sample documents; %d held out host side",
                len(_VISIBLE), len(_HOLDOUT))


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted script over held-out documents; compare host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("docx_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[docx] no submission at %s", submission)
        return [0.0]

    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)

    cases = {}
    for name in _HOLDOUT:
        src = (DATA / "holdout" / name).read_bytes()
        ref = (DATA / "holdout" / name.replace("doc_", "expected_")).read_bytes()
        remote_in = f"{EVAL_DIR}/{name}"
        remote_out = f"{EVAL_DIR}/out_{name}"
        await _put_binary(session, remote_in, src)
        r = await session.run_command(
            f"python3 {submission!r} {remote_in!r} {remote_out!r}",
            timeout=PER_DOC_TIMEOUT_S, check=False)
        produced = None
        if r.get("return_code") == 0 and await session.file_exists(remote_out):
            dump = await session.run_command(
                f"python3 -c \"import pathlib;"
                f"print(pathlib.Path('{remote_out}').read_bytes().hex())\"", check=False)
            hexed = (dump.get("stdout") or "").strip()
            if hexed:
                try:
                    produced = bytes.fromhex(hexed)
                except ValueError:
                    produced = None
        cases[name] = (src, ref, produced)

    report = grade.score(cases)
    logger.info("[docx] both=%d/%d preserved=%d edited=%d reward=%.3f",
                report["both"], report["documents"], report["preserved"],
                report["edited"], report["reward"])
    return [float(report["reward"])]
