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


def _accept_with_one_rule_wrong(**wrong):
    """Apply the reference edit from source with a single acceptance rule broken."""
    import sys
    sys.path.insert(0, str(task.ASSETS))
    from accept_revisions import stop_tracking
    from reference_edit import fill_placeholder, recolour_heading1, set_alignment
    src = (task.DATA / "holdout" / "doc_21.docx").read_bytes()
    z = zipfile.ZipFile(io.BytesIO(src))
    data = {n: z.read(n) for n in z.namelist()}
    data["word/document.xml"] = set_alignment(
        _naive_accept(data["word/document.xml"], **wrong))
    data["word/styles.xml"] = recolour_heading1(data["word/styles.xml"])
    data["word/settings.xml"] = stop_tracking(data["word/settings.xml"])
    for part in ("word/header1.xml", "word/footer1.xml"):
        data[part] = fill_placeholder(data[part], "Q1 2026")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in z.namelist():
            out.writestr(n, data[n])
    return buf.getvalue()


def _naive_accept(xml, *, keep_para_mark=False, drop_move_to=False,
                  keep_move_from=False, keep_row=False, keep_change_records=False):
    from lxml import etree
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = etree.fromstring(xml)
    for tr in list(root.iter(f"{W}tr")):
        trpr = tr.find(f"{W}trPr")
        if trpr is not None and trpr.find(f"{W}del") is not None and not keep_row:
            tr.getparent().remove(tr)
        elif trpr is not None:
            for m in list(trpr.findall(f"{W}ins")):
                trpr.remove(m)
    if not keep_para_mark:
        for para in list(root.iter(f"{W}p")):
            ppr = para.find(f"{W}pPr")
            rpr = ppr.find(f"{W}rPr") if ppr is not None else None
            if rpr is None or rpr.find(f"{W}del") is None:
                continue
            nxt = para.getnext()
            if nxt is None or nxt.tag != f"{W}p":
                rpr.remove(rpr.find(f"{W}del"))
                continue
            body = [c for c in para if c.tag != f"{W}pPr"]
            npp = nxt.find(f"{W}pPr")
            at = list(nxt).index(npp) + 1 if npp is not None else 0
            for i, c in enumerate(body):
                nxt.insert(at + i, c)
            para.getparent().remove(para)
    drop = {f"{W}del", f"{W}moveFromRangeStart", f"{W}moveFromRangeEnd",
            f"{W}moveToRangeStart", f"{W}moveToRangeEnd"}
    unwrap = {f"{W}ins"}
    if not keep_move_from:
        drop.add(f"{W}moveFrom")
    (drop if drop_move_to else unwrap).add(f"{W}moveTo")
    for el in list(root.iter()):
        if el.getparent() is not None and el.tag in drop:
            el.getparent().remove(el)
    for el in list(root.iter()):
        if el.getparent() is None or el.tag not in unwrap:
            continue
        par = el.getparent()
        at = list(par).index(el)
        for i, c in enumerate(list(el)):
            par.insert(at + i, c)
        par.remove(el)
    if not keep_change_records:
        for el in list(root.iter()):
            if el.getparent() is not None and el.tag.endswith("PrChange"):
                el.getparent().remove(el)
    for rpr in list(root.iter(f"{W}rPr")):
        par = rpr.getparent()
        if len(rpr) == 0 and not rpr.attrib and par is not None and par.tag == f"{W}pPr":
            par.remove(rpr)
    for ppr in list(root.iter(f"{W}pPr")):
        if len(ppr) == 0 and not ppr.attrib and ppr.getparent() is not None:
            ppr.getparent().remove(ppr)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def test_accepting_revisions_correctly_scores_one():
    """The positive control for the hard half: the plain rules, all of them right."""
    src, ref = _pair()
    assert grade.score({"d": (src, ref, _accept_with_one_rule_wrong())})["reward"] == 1.0


@pytest.mark.parametrize("wrong", [
    {"keep_para_mark": True},      # the merge that a deleted paragraph mark implies
    {"drop_move_to": True},        # a move's destination must stay
    {"keep_move_from": True},      # a move's source must go
    {"keep_row": True},            # a row marked deleted loses the whole row
    {"keep_change_records": True},  # the record goes, the formatting it records stays
])
def test_one_wrong_acceptance_rule_fails(wrong):
    """Each of these produces a document that opens cleanly and reads plausibly."""
    src, ref = _pair()
    r = grade.score({"d": (src, ref, _accept_with_one_rule_wrong(**wrong))})
    assert r["both"] == 0, f"{wrong} was not caught"


def test_malformed_submissions_score_zero_without_raising():
    src, ref = _pair()
    for junk in (None, b"", b"not a zip at all"):
        assert grade.score({"d": (src, ref, junk)})["reward"] == 0.0
