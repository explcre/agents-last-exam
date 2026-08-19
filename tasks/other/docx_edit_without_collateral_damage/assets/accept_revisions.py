"""Accept every tracked change in a document part. Never shipped to the agent.

The long tail is the point. Unwrapping insertions and dropping deletions is the
obvious half; the rest is where implementations go wrong:

  * a deleted paragraph mark merges its paragraph into the following one
  * moveFrom disappears while moveTo stays, and both range markers go
  * rPrChange, pPrChange, tblPrChange, tcPrChange and sectPrChange records are
    removed while the formatting they record survives
  * a row whose trPr carries w:del loses the entire row, not just the mark
"""
from __future__ import annotations

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
UNWRAP = {f"{W}ins", f"{W}moveTo"}
DROP = {f"{W}del", f"{W}moveFrom",
        f"{W}moveFromRangeStart", f"{W}moveFromRangeEnd",
        f"{W}moveToRangeStart", f"{W}moveToRangeEnd"}
CHANGE_RECORDS = {f"{W}rPrChange", f"{W}pPrChange", f"{W}tblPrChange",
                  f"{W}tcPrChange", f"{W}sectPrChange", f"{W}tblGridChange"}


def _unwrap(el) -> None:
    parent = el.getparent()
    at = list(parent).index(el)
    for i, child in enumerate(list(el)):
        parent.insert(at + i, child)
    if el.text and at > 0:
        pass
    parent.remove(el)


def _drop(el) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _paragraph_mark_deleted(p) -> bool:
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return False
    rpr = ppr.find(f"{W}rPr")
    return rpr is not None and rpr.find(f"{W}del") is not None


def accept(xml: bytes) -> bytes:
    root = etree.fromstring(xml)

    # rows deleted wholesale, before anything inside them is touched
    for tr in list(root.iter(f"{W}tr")):
        trpr = tr.find(f"{W}trPr")
        if trpr is not None and trpr.find(f"{W}del") is not None:
            _drop(tr)
        elif trpr is not None:
            for mark in list(trpr.findall(f"{W}ins")):
                _drop(mark)

    # paragraphs whose mark was deleted merge forward into the next paragraph
    for p in list(root.iter(f"{W}p")):
        if p.getparent() is None or not _paragraph_mark_deleted(p):
            continue
        nxt = p.getnext()
        if nxt is None or nxt.tag != f"{W}p":
            # nothing to merge into: the mark simply goes
            rpr = p.find(f"{W}pPr").find(f"{W}rPr")
            _drop(rpr.find(f"{W}del"))
            continue
        body = [c for c in p if c.tag != f"{W}pPr"]
        nxt_ppr = nxt.find(f"{W}pPr")
        at = list(nxt).index(nxt_ppr) + 1 if nxt_ppr is not None else 0
        for i, child in enumerate(body):
            nxt.insert(at + i, child)
        _drop(p)

    # deletions and move sources go; insertions and move destinations stay
    for el in list(root.iter()):
        if el.getparent() is None:
            continue
        if el.tag in DROP:
            _drop(el)
    for el in list(root.iter()):
        if el.getparent() is None:
            continue
        if el.tag in UNWRAP:
            _unwrap(el)
    for el in list(root.iter()):
        if el.getparent() is None:
            continue
        if el.tag in CHANGE_RECORDS:
            _drop(el)

    # an rPr left empty by a removed mark is not content
    for rpr in list(root.iter(f"{W}rPr")):
        if len(rpr) == 0 and not rpr.attrib and rpr.getparent() is not None \
                and rpr.getparent().tag == f"{W}pPr":
            _drop(rpr)
    for ppr in list(root.iter(f"{W}pPr")):
        if len(ppr) == 0 and not ppr.attrib and ppr.getparent() is not None:
            _drop(ppr)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def stop_tracking(settings_xml: bytes) -> bytes:
    root = etree.fromstring(settings_xml)
    for el in list(root.findall(f"{W}trackChanges")):
        _drop(el)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
