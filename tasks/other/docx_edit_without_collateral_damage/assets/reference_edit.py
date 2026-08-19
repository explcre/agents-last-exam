"""The reference edit. Never shipped to the agent.

Set every body paragraph to justified, except headings which go left, and change
nothing else anywhere in the package. Operating on the XML in place is what keeps
the rest of the document intact; rebuilding the file from a document model is what
loses it.
"""
from __future__ import annotations

import pathlib
import sys
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_STYLES = {"Heading1", "Heading2"}


def set_alignment(xml: bytes) -> bytes:
    from lxml import etree
    root = etree.fromstring(xml)
    body = root.find(f"{W}body")
    for p in body.iter(f"{W}p"):
        style = None
        ppr = p.find(f"{W}pPr")
        if ppr is not None:
            ps = ppr.find(f"{W}pStyle")
            if ps is not None:
                style = ps.get(f"{W}val")
        want = "left" if style in HEADING_STYLES else "both"
        if ppr is None:
            ppr = etree.SubElement(p, f"{W}pPr")
            p.remove(ppr)
            p.insert(0, ppr)
        jc = ppr.find(f"{W}jc")
        if jc is None:
            jc = etree.SubElement(ppr, f"{W}jc")
        jc.set(f"{W}val", want)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def recolour_heading1(xml: bytes) -> bytes:
    """Heading 1 takes the house colour. Only that one attribute may move."""
    return xml.replace(b'<w:color w:val="1F4E79"/>', b'<w:color w:val="7A2E2E"/>', 1)


def fill_placeholder(xml: bytes, value: str) -> bytes:
    """The review-cycle placeholder is replaced wherever it appears."""
    return xml.replace(b"[[CYCLE]]", value.encode("utf-8"))


def apply(src: pathlib.Path, dst: pathlib.Path, cycle: str = "Q1 2026") -> None:
    """Rewrite the parts the brief names and copy every other byte through untouched.

    Revisions are accepted first: accepting a deleted paragraph mark merges two
    paragraphs, and the alignment pass has to run over the paragraphs that survive.
    """
    from accept_revisions import accept, stop_tracking
    with zipfile.ZipFile(src) as zin:
        infos = zin.infolist()
        data = {i.filename: zin.read(i.filename) for i in infos}
    data["word/document.xml"] = set_alignment(accept(data["word/document.xml"]))
    data["word/settings.xml"] = stop_tracking(data["word/settings.xml"])
    data["word/styles.xml"] = recolour_heading1(data["word/styles.xml"])
    for part in ("word/header1.xml", "word/footer1.xml"):
        data[part] = fill_placeholder(data[part], cycle)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for i in infos:
            zout.writestr(i.filename, data[i.filename])


if __name__ == "__main__":
    apply(pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]))
    print("wrote", sys.argv[2])
