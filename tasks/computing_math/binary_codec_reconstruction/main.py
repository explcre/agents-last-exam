"""AgentHLE task: computing_math/binary_codec_reconstruction.

Reconstruct a binary container codec, byte-exactly, from samples.

A legacy system writes files in an undocumented container format. The agent is given
thirty of those files together with the data each one holds, and must write a codec
that both reads held-out files and writes them back to the exact bytes the original
encoder produced.

Reading is the reachable half. Writing is not: the format is entangled, so several
encoder decisions propagate through the whole stream. Record ids are delta-encoded,
the string table is ordered by first use, and the payload is compressed with a lazy
matching policy whose tie-breaks change every subsequent offset. Measured on this
corpus, choosing the wrong tie rule moves 55.6% of the bytes in a file and choosing
the wrong minimum match length moves 56.4%.

Byte-exact interoperability with a legacy encoder is ordinary work wherever files are
signed, deduplicated by hash, or diffed against an archive.

All task data is written by ``start()``. Nothing is baked into an image and nothing
is fetched at run time.
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
TASK_NAME = "binary_codec_reconstruction"
VARIANT_NAME = "base"

EVAL_DIR = "/tmp/agenthle_eval/binary_codec_reconstruction"
RUNNER_TIMEOUT_S = 1800.0

_SAMPLES = sorted(p.stem for p in (DATA / "samples").glob("*.bin"))
_HOLDOUT = sorted(p.stem for p in (DATA / "holdout").glob("*.bin"))


@dataclass
class TaskConfig(LinuxTaskConfig):
    DOMAIN_NAME: str = DOMAIN_NAME
    TASK_NAME: str = TASK_NAME
    VARIANT_NAME: str = VARIANT_NAME
    REQUIRES_TASK_DATA: bool = False

    @property
    def submission_path(self) -> str:
        return f"{self.remote_output_dir}/codec.py"

    @property
    def task_description(self) -> str:
        return """\
Reconstruct a binary container codec from samples.

A legacy system writes files in a container format nobody documented. Under \
`{input}/samples` are thirty of those files, each `sample_NNNN.bin` paired with \
`sample_NNNN.json`, the data that file holds. No specification exists: the pairs are \
the only description of the format.

## What you write

`{submission}`, a self-contained Python 3 module, standard library only, exposing:

    def decode(blob: bytes) -> dict     # the document a file holds
    def encode(doc: dict) -> bytes      # the file that document came from

`decode` must return a document equal to the paired JSON. `encode` must return the \
**exact bytes** the original encoder wrote, not merely a file that decodes back to \
the same document.

## How this is graded

Your module is run against held-out files you have not seen. For each one, two \
things are checked independently:

- `decode(file)` equals the document that file holds;
- `encode(that document)` equals the file, byte for byte.

Most of the score is the byte-exact half; decoding supplies the rest, so partial \
progress is visible. Round-tripping your own output proves nothing here: a codec \
that is self-consistent but disagrees with the original encoder scores zero on the \
half that matters.

Everything you need is in the samples. Do not rely on internet access, and do not \
modify anything under `input/`.
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
    """Stage the worked samples; confirm the codec and held-out files did not leak."""
    await _setup(task_cfg, session)
    meta = task_cfg.metadata
    input_dir, out_dir, ref_dir = (meta["input_dir"], meta["remote_output_dir"],
                                   meta["reference_dir"])

    await session.run_command(f"rm -rf {input_dir!r} {out_dir!r} {ref_dir!r}", check=False)
    await session.run_command(f"mkdir -p {input_dir!r}/samples {out_dir!r}", check=True)
    for name in _SAMPLES:
        blob = (DATA / "samples" / f"{name}.bin").read_bytes()
        await session.write_file(f"{input_dir}/samples/{name}.hex", blob.hex())
        await session.run_command(
            f"python3 -c \"import binascii,pathlib;"
            f"p=pathlib.Path('{input_dir}/samples/{name}.hex');"
            f"pathlib.Path('{input_dir}/samples/{name}.bin')"
            f".write_bytes(binascii.unhexlify(p.read_text().strip()));p.unlink()\"",
            check=True)
        await session.write_file(f"{input_dir}/samples/{name}.json",
                                 (DATA / "samples" / f"{name}.json").read_text(encoding="utf-8"))

    probe = (DATA / "holdout" / f"{_HOLDOUT[0]}.bin").read_bytes().hex()[:60]
    leak = await session.run_command(
        f"grep -rlF {probe!r} {input_dir!r} 2>/dev/null; "
        f"grep -rlE 'LAZY_GAIN|lz77_compress' {input_dir!r} 2>/dev/null; "
        f"ls {ref_dir!r} 2>/dev/null", check=False)
    if (leak.get("stdout") or "").strip():
        raise RuntimeError(f"reference material leaked onto the VM: {leak['stdout'][:400]}")
    logger.info("[codec] staged %d samples; %d held out host side",
                len(_SAMPLES), len(_HOLDOUT))


RUNNER = r'''
import binascii, json, pathlib, sys, traceback
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).parent))
import importlib.util
spec = importlib.util.spec_from_file_location("submitted_codec", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

out = {}
for item in json.loads(pathlib.Path(sys.argv[2]).read_text()):
    name, blob = item["name"], binascii.unhexlify(item["hex"])
    entry = {"decoded": None, "encoded_hex": None}
    try:
        entry["decoded"] = mod.decode(blob)
    except Exception:
        pass
    try:
        # encode the document the file actually holds, not the agent's own decode,
        # so a broken decode cannot silently excuse a broken encode
        entry["encoded_hex"] = mod.encode(item["doc"]).hex()
    except Exception:
        pass
    out[name] = entry
print(json.dumps(out))
'''


@cb.evaluate_task(split="train")
async def evaluate(task_cfg, session: cb.DesktopSession) -> list[float]:
    """Run the submitted codec over the held-out files; compare host side."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("codec_grade", SCRIPTS / "grade.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load grader from {SCRIPTS / 'grade.py'}")
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)

    submission = task_cfg.metadata["submission_path"]
    if not await session.file_exists(submission):
        logger.info("[codec] no submission at %s", submission)
        return [0.0]

    expected, payload = {}, []
    for name in _HOLDOUT:
        blob = (DATA / "holdout" / f"{name}.bin").read_bytes()
        doc = json.loads((DATA / "holdout" / f"{name}.json").read_text(encoding="utf-8"))
        expected[name] = {"doc": doc, "hex": blob.hex()}
        payload.append({"name": name, "hex": blob.hex(), "doc": doc})

    await session.run_command(f"rm -rf {EVAL_DIR!r}", check=False)
    await session.run_command(f"mkdir -p {EVAL_DIR!r}", check=True)
    await session.write_file(f"{EVAL_DIR}/cases.json", json.dumps(payload))
    await session.write_file(f"{EVAL_DIR}/runner.py", RUNNER)

    r = await session.run_command(
        f"python3 {EVAL_DIR}/runner.py {submission!r} {EVAL_DIR}/cases.json",
        timeout=RUNNER_TIMEOUT_S, check=False)
    stdout = (r.get("stdout") or "").strip()
    if r.get("return_code") != 0 or not stdout:
        logger.info("[codec] runner failed rc=%s err=%s",
                    r.get("return_code"), (r.get("stderr") or "")[:300])
        return [0.0]
    try:
        results = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.info("[codec] runner output unparseable: %s", exc)
        return [0.0]

    report = grade.score(results, expected)
    logger.info("[codec] decoded=%d/%d encoded=%d/%d reward=%.3f",
                report["decoded"], report["samples"],
                report["encoded"], report["samples"], report["reward"])
    return [float(report["reward"])]
