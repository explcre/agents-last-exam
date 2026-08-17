"""End-to-end checks for other/docx_edit_without_collateral_damage.

The controls that matter here are the negative ones. A grader for this task is only
useful if it fails a document that opens cleanly and looks right but has quietly lost
its tracked changes, so each of those losses is constructed and asserted to fail.
"""

from __future__ import annotations

import asyncio
import io
import pathlib
import re
import subprocess
import types
import zipfile

import pytest

from tasks.other.docx_edit_without_collateral_damage import main as task
from tasks.other.docx_edit_without_collateral_damage.scripts import grade


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


def _pair(name="doc_21.docx"):
    src = (task.DATA / "holdout" / name).read_bytes()
    ref = (task.DATA / "holdout" / name.replace("doc_", "expected_")).read_bytes()
    return src, ref


def _rebuild(ref: bytes, mutate=None, drop=(), touch=None):
    z = zipfile.ZipFile(io.BytesIO(ref))
    names = [n for n in z.namelist() if n not in drop]
    data = {n: z.read(n) for n in names}
    if mutate:
        data["word/document.xml"] = mutate(data["word/document.xml"])
    for n, fn in (touch or {}).items():
        if n in data:
            data[n] = fn(data[n])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in names:
            out.writestr(n, data[n])
    return buf.getvalue()


def test_start_stages_documents_as_real_docx_files(staged):
    root = pathlib.Path(staged.metadata["input_dir"]) / "documents"
    for name in task._VISIBLE:
        f = root / name
        assert f.is_file(), name
        assert not (root / f"{name}.hex").exists(), "the hex shim was left behind"
        z = zipfile.ZipFile(f)
        assert "word/document.xml" in z.namelist()
        assert z.testzip() is None


def test_no_expected_document_reaches_the_vm(staged):
    root = pathlib.Path(staged.metadata["task_dir"])
    assert not list(root.rglob("expected_*.docx")), "an answer document is on the VM"
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in root.rglob("*") if p.is_file() and p.suffix != ".docx")
    assert "7A2E2E" not in text, "the target colour leaked outside the brief"


def test_sample_documents_actually_contain_the_fragile_parts():
    """If a sample lacked revisions or a content control there would be nothing to lose."""
    for name in task._VISIBLE:
        z = zipfile.ZipFile(task.DATA / "visible" / name)
        doc = z.read("word/document.xml").decode()
        assert "<w:ins " in doc and "<w:del " in doc, f"{name}: no tracked changes"
        assert "<w:sdt>" in doc, f"{name}: no content control"
        assert "commentReference" in doc and "footnoteReference" in doc, f"{name}: no anchors"
        assert "customXml/item1.xml" in z.namelist(), f"{name}: no custom part"
        assert b"[[CYCLE]]" in z.read("word/header1.xml"), f"{name}: no header placeholder"


def test_the_reference_edit_scores_one():
    src, ref = _pair()
    assert grade.score({"d": (src, ref, ref)})["reward"] == 1.0


def test_missing_submission_scores_zero(staged):
    assert asyncio.run(task.evaluate(staged, LocalSession())) == [0.0]


@pytest.mark.parametrize(("label", "kwargs"), [
    ("tracked insertion unwrapped",
     {"mutate": lambda d: re.sub(rb"<w:ins [^>]*>(.*?)</w:ins>", rb"\1", d, flags=re.DOTALL)}),
    ("deletion removed",
     {"mutate": lambda d: re.sub(rb"<w:del .*?</w:del>", b"", d, flags=re.DOTALL)}),
    ("content control unwrapped",
     {"mutate": lambda d: re.sub(rb"<w:sdt>.*?<w:sdtContent>(.*?)</w:sdtContent></w:sdt>",
                                 rb"\1", d, flags=re.DOTALL)}),
    ("comment anchors removed",
     {"mutate": lambda d: re.sub(rb"<w:commentRange(Start|End) [^>]*/>|"
                                 rb"<w:commentReference [^>]*/>", b"", d)}),
    ("footnote reference removed",
     {"mutate": lambda d: re.sub(rb"<w:footnoteReference [^>]*/>", b"", d)}),
    ("custom xml part dropped", {"drop": {"customXml/item1.xml"}}),
    ("comments part dropped", {"drop": {"word/comments.xml"}}),
    ("untouched part reserialised",
     {"touch": {"word/numbering.xml": lambda b: b.replace(b"><", b">\n<")}}),
])
def test_silent_content_loss_is_caught(label, kwargs):
    """Each of these opens cleanly and looks right, and each must fail."""
    src, ref = _pair()
    broken = _rebuild(ref, **kwargs)
    assert zipfile.ZipFile(io.BytesIO(broken)).testzip() is None, f"{label}: not a valid zip"
    r = grade.score({"d": (src, ref, broken)})
    assert r["both"] == 0, f"{label} was not caught"
    assert r["reward"] < 0.5, f"{label} scored {r['reward']}"


@pytest.mark.parametrize(("label", "kwargs"), [
    ("an edited part pretty-printed",
     {"touch": {"word/styles.xml": lambda b: b.replace(b"><", b">\n<")}}),
])
def test_harmless_variation_is_not_punished(label, kwargs):
    """Reformatting a part the brief names loses nothing and must still pass."""
    src, ref = _pair()
    variant = _rebuild(ref, **kwargs)
    assert grade.score({"d": (src, ref, variant)})["reward"] == 1.0, label


def test_malformed_submissions_score_zero_without_raising():
    src, ref = _pair()
    for junk in (None, b"", b"not a zip at all"):
        assert grade.score({"d": (src, ref, junk)})["reward"] == 0.0
