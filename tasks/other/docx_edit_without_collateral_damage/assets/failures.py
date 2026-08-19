"""Simulate the ways a careless edit loses parts of a document, and check the grader
notices each one. These are the real failure modes: a model that understands
paragraphs but not revisions, a rewrite that forgets a part, a re-zip that reflows
whitespace.
"""
from __future__ import annotations

import io
import pathlib
import re
import sys
import zipfile

sys.path.insert(0, "/tmp/galaxy_srv_disk00/pengchx3/docx")
from grade import score
from reference_edit import fill_placeholder, recolour_heading1, set_alignment

SRC = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/docx/out/source_1.docx").read_bytes()
REF = pathlib.Path("/tmp/galaxy_srv_disk00/pengchx3/docx/out/edited_1.docx").read_bytes()


def rebuild(mutate_doc=None, drop=(), touch=None, keep_order=True):
    zin = zipfile.ZipFile(io.BytesIO(SRC))
    names = [n for n in zin.namelist() if n not in drop]
    data = {n: zin.read(n) for n in names}
    doc = set_alignment(data["word/document.xml"])
    if mutate_doc:
        doc = mutate_doc(doc)
    data["word/document.xml"] = doc
    if "word/styles.xml" in data:
        data["word/styles.xml"] = recolour_heading1(data["word/styles.xml"])
    for part in ("word/header1.xml", "word/footer1.xml"):
        if part in data:
            data[part] = fill_placeholder(data[part], "Q1 2026")
    if touch:
        for n, fn in touch.items():
            if n in data:
                data[n] = fn(data[n])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in (names if keep_order else sorted(names)):
            z.writestr(n, data[n])
    return buf.getvalue()


def strip(pattern):
    return lambda d: re.sub(pattern, b"", d, flags=re.DOTALL)


CASES = {
    "reference edit": rebuild(),
    "drops tracked changes (keeps the text)":
        rebuild(lambda d: re.sub(rb"<w:ins [^>]*>(.*?)</w:ins>", rb"\1", d, flags=re.DOTALL)),
    "drops the deletion entirely":
        rebuild(strip(rb"<w:del .*?</w:del>")),
    "drops the content control wrapper":
        rebuild(lambda d: re.sub(rb"<w:sdt>.*?<w:sdtContent>(.*?)</w:sdtContent></w:sdt>",
                                 rb"\1", d, flags=re.DOTALL)),
    "drops comment anchors":
        rebuild(strip(rb"<w:commentRange(Start|End) [^>]*/>|<w:commentReference [^>]*/>")),
    "drops the footnote reference":
        rebuild(strip(rb"<w:footnoteReference [^>]*/>")),
    "drops the customXml part": rebuild(drop={"customXml/item1.xml"}),
    "drops the comments part": rebuild(drop={"word/comments.xml"}),
    "pretty-prints a part it was told to edit":
        rebuild(touch={"word/styles.xml": lambda b: b.replace(b"><", b">\n<")}),
    "reserialises a part it was not told to touch":
        rebuild(touch={"word/numbering.xml": lambda b: b.replace(b"><", b">\n<")}),
    "re-sorts the parts in the zip": rebuild(keep_order=False),
    "aligns everything, headings included":
        rebuild(lambda d: d.replace(b'w:val="left"', b'w:val="both"')),
    "forgets the footer placeholder":
        rebuild(touch={"word/footer1.xml": lambda b: b.replace(b"Q1 2026", b"[[CYCLE]]")}),
}

print(f"{'edit':<44}{'reward':>8}  what the grader saw")
for name, blob in CASES.items():
    r = score({"d": (SRC, REF, blob)})
    d = r["per_doc"]["d"]
    notes = []
    if not d.get("parts_preserved"): notes.append(f"missing {d.get('missing_parts')}")
    if not d.get("unnamed_parts_identical"): notes.append(f"changed {d.get('changed_parts')}")
    if not d.get("body_content_preserved"): notes.append("body content altered")
    if not d.get("alignment_correct"): notes.append("alignment wrong")
    if not d.get("styles_correct"): notes.append("styles wrong")
    if not d.get("header_footer_correct"): notes.append("header/footer wrong")
    print(f"{name:<44}{r['reward']:>8.3f}  {'; '.join(notes) or 'clean'}")
