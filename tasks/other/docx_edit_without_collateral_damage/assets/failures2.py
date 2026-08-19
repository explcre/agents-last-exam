"""Check the grader catches each way accepting revisions goes wrong.

These are the mistakes an implementation actually makes, and every one of them
produces a document that opens cleanly and reads plausibly.
"""
from __future__ import annotations

import io
import pathlib
import sys
import zipfile

sys.path.insert(0, "/tmp/galaxy_srv_disk00/pengchx3/docx")
from grade import score
from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SRC = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/docx/out/src.docx").read_bytes()
REF = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/docx/out/ref.docx").read_bytes()


def variant(fn):
    z = zipfile.ZipFile(io.BytesIO(REF))
    data = {n: z.read(n) for n in z.namelist()}
    data["word/document.xml"] = fn(data["word/document.xml"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in z.namelist():
            out.writestr(n, data[n])
    return buf.getvalue()


def from_source(fn):
    """Start from the unaccepted source and apply a partial acceptance."""
    sys.path.insert(0, "/tmp/galaxy_srv_disk00/pengchx3/docx")
    from accept_revisions import stop_tracking
    from reference_edit import fill_placeholder, recolour_heading1, set_alignment
    z = zipfile.ZipFile(io.BytesIO(SRC))
    data = {n: z.read(n) for n in z.namelist()}
    data["word/document.xml"] = set_alignment(fn(data["word/document.xml"]))
    data["word/styles.xml"] = recolour_heading1(data["word/styles.xml"])
    data["word/settings.xml"] = stop_tracking(data["word/settings.xml"])
    for p in ("word/header1.xml", "word/footer1.xml"):
        data[p] = fill_placeholder(data[p], "Q1 2026")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for n in z.namelist():
            out.writestr(n, data[n])
    return buf.getvalue()


def naive_accept(xml, *, keep_para_mark=False, drop_move_to=False,
                 keep_move_from=False, keep_row=False, strip_formatting=False):
    """The obvious implementation, with one rule wrong."""
    root = etree.fromstring(xml)
    for tr in list(root.iter(f"{W}tr")):
        trpr = tr.find(f"{W}trPr")
        if trpr is not None and trpr.find(f"{W}del") is not None and not keep_row:
            tr.getparent().remove(tr)
        elif trpr is not None:
            for m in list(trpr.findall(f"{W}ins")):
                trpr.remove(m)
    if not keep_para_mark:
        for p in list(root.iter(f"{W}p")):
            ppr = p.find(f"{W}pPr")
            rpr = ppr.find(f"{W}rPr") if ppr is not None else None
            if rpr is None or rpr.find(f"{W}del") is None:
                continue
            nxt = p.getnext()
            if nxt is None or nxt.tag != f"{W}p":
                rpr.remove(rpr.find(f"{W}del")); continue
            body = [c for c in p if c.tag != f"{W}pPr"]
            npp = nxt.find(f"{W}pPr")
            at = list(nxt).index(npp) + 1 if npp is not None else 0
            for i, c in enumerate(body):
                nxt.insert(at + i, c)
            p.getparent().remove(p)
    drop = {f"{W}del", f"{W}moveFromRangeStart", f"{W}moveFromRangeEnd",
            f"{W}moveToRangeStart", f"{W}moveToRangeEnd"}
    if not keep_move_from:
        drop.add(f"{W}moveFrom")
    unwrap = {f"{W}ins"}
    if not drop_move_to:
        unwrap.add(f"{W}moveTo")
    else:
        drop.add(f"{W}moveTo")
    for el in list(root.iter()):
        if el.getparent() is not None and el.tag in drop:
            el.getparent().remove(el)
    for el in list(root.iter()):
        if el.getparent() is None or el.tag not in unwrap:
            continue
        par = el.getparent(); at = list(par).index(el)
        for i, c in enumerate(list(el)):
            par.insert(at + i, c)
        par.remove(el)
    if not strip_formatting:
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


CASES = {
    "accepts everything correctly": from_source(lambda x: naive_accept(x)),
    "leaves the deleted paragraph mark, no merge":
        from_source(lambda x: naive_accept(x, keep_para_mark=True)),
    "drops the move destination too":
        from_source(lambda x: naive_accept(x, drop_move_to=True)),
    "keeps the move source as well":
        from_source(lambda x: naive_accept(x, keep_move_from=True)),
    "keeps the row marked deleted":
        from_source(lambda x: naive_accept(x, keep_row=True)),
    "leaves the formatting-change records":
        from_source(lambda x: naive_accept(x, strip_formatting=True)),
    "forgets to stop tracking changes":
        variant(lambda x: x),
}
# the last case needs settings.xml left alone, built separately
z = zipfile.ZipFile(io.BytesIO(REF))
data = {n: z.read(n) for n in z.namelist()}
data["word/settings.xml"] = zipfile.ZipFile(io.BytesIO(SRC)).read("word/settings.xml")
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
    for n in z.namelist():
        out.writestr(n, data[n])
CASES["forgets to stop tracking changes"] = buf.getvalue()

print(f"{'submission':<46}{'reward':>8}  detail")
for name, blob in CASES.items():
    r = score({"d": (SRC, REF, blob)})
    d = r["per_doc"]["d"]
    notes = [k for k in ("parts_preserved", "unnamed_parts_identical",
                         "body_content_preserved", "alignment_correct",
                         "styles_correct", "header_footer_correct",
                         "revisions_accepted") if not d.get(k)]
    print(f"{name:<46}{r['reward']:>8.3f}  {', '.join(notes) or 'clean'}")
