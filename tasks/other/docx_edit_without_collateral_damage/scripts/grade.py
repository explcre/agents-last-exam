"""Score an edited .docx: was every named change made, and was nothing else disturbed?

The brief names four things to change. Everything else in the package, including the
parts of the edited document that were not named, must survive untouched. That
second half is what fails in practice: a document model that does not understand
tracked changes, content controls, comment anchors or custom parts drops them on
save and says nothing.

Preservation is checked exhaustively rather than by sampling. Parts the brief does
not name must be byte-identical to the source. The named parts are compared with
what the reference edit produced, canonicalised so that formatting of the XML itself
does not count against a submission.
"""
from __future__ import annotations

import io
import zipfile

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADING_STYLES = {"Heading1", "Heading2"}
NAMED_PARTS = ("word/document.xml", "word/styles.xml",
               "word/header1.xml", "word/footer1.xml")


def _c14n(xml: bytes) -> bytes:
    """Canonical form with inter-element whitespace dropped.

    A submission that pretty-prints a part it was told to edit has not lost
    anything, so only real content differences should count against it. Parts the
    brief does not name are held to byte-identity instead, which is where a
    reserialising tool does real damage.
    """
    from lxml import etree
    root = etree.fromstring(xml, etree.XMLParser(remove_blank_text=True))
    return etree.tostring(root, method="c14n")


def _strip_alignment(xml: bytes) -> bytes:
    """The document with every w:jc removed, leaving only other differences."""
    from lxml import etree
    root = etree.fromstring(xml)
    for jc in list(root.iter(f"{W}jc")):
        p = jc.getparent()
        if p is not None:
            p.remove(jc)
    for ppr in list(root.iter(f"{W}pPr")):
        if len(ppr) == 0 and not ppr.attrib:
            p = ppr.getparent()
            if p is not None:
                p.remove(ppr)
    return etree.tostring(root, method="c14n")


def _alignments(xml: bytes):
    from lxml import etree
    root = etree.fromstring(xml)
    body = root.find(f"{W}body")
    out = []
    if body is None:
        return out
    for p in body.iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        style = jc = None
        if ppr is not None:
            ps = ppr.find(f"{W}pStyle")
            style = ps.get(f"{W}val") if ps is not None else None
            j = ppr.find(f"{W}jc")
            jc = j.get(f"{W}val") if j is not None else None
        out.append((style, jc))
    return out


def score_one(source: bytes, reference: bytes, submitted: bytes) -> dict:
    r = {"opens": False, "parts_preserved": False, "unnamed_parts_identical": False,
         "body_content_preserved": False, "alignment_correct": False,
         "styles_correct": False, "header_footer_correct": False}
    try:
        zsrc = zipfile.ZipFile(io.BytesIO(source))
        zref = zipfile.ZipFile(io.BytesIO(reference))
        zsub = zipfile.ZipFile(io.BytesIO(submitted))
    except (zipfile.BadZipFile, OSError):
        return r
    r["opens"] = True

    names_src, names_sub = set(zsrc.namelist()), set(zsub.namelist())
    r["parts_preserved"] = names_src == names_sub
    if not r["parts_preserved"]:
        r["missing_parts"] = sorted(names_src - names_sub)
        r["added_parts"] = sorted(names_sub - names_src)

    unnamed = [n for n in sorted(names_src & names_sub) if n not in NAMED_PARTS]
    changed = [n for n in unnamed if zsrc.read(n) != zsub.read(n)]
    r["unnamed_parts_identical"] = not changed
    if changed:
        r["changed_parts"] = changed

    try:
        if "word/document.xml" in names_sub:
            r["body_content_preserved"] = (
                _strip_alignment(zsrc.read("word/document.xml"))
                == _strip_alignment(zsub.read("word/document.xml")))
            aligns = _alignments(zsub.read("word/document.xml"))
            r["alignment_correct"] = bool(aligns) and all(
                jc == ("left" if style in HEADING_STYLES else "both")
                for style, jc in aligns)
        if "word/styles.xml" in names_sub:
            r["styles_correct"] = (_c14n(zsub.read("word/styles.xml"))
                                   == _c14n(zref.read("word/styles.xml")))
        r["header_footer_correct"] = all(
            p in names_sub and _c14n(zsub.read(p)) == _c14n(zref.read(p))
            for p in ("word/header1.xml", "word/footer1.xml"))
    except Exception as exc:  # noqa: BLE001 - any parse failure is a failure
        r["error"] = type(exc).__name__
    return r


def score(cases: dict) -> dict:
    """``cases`` maps name to (source, reference, submitted|None)."""
    names = sorted(cases)
    per_doc, preserved, edited, both = {}, 0, 0, 0
    for name in names:
        source, reference, submitted = cases[name]
        if submitted is None:
            per_doc[name] = {"opens": False}
            continue
        r = score_one(source, reference, submitted)
        r["preserved"] = (r["parts_preserved"] and r["unnamed_parts_identical"]
                          and r["body_content_preserved"])
        r["edited"] = (r["alignment_correct"] and r["styles_correct"]
                       and r["header_footer_correct"])
        preserved += r["preserved"]
        edited += r["edited"]
        both += r["preserved"] and r["edited"]
        per_doc[name] = r
    n = len(names) or 1
    return {"documents": len(names), "preserved": preserved, "edited": edited,
            "both": both, "per_doc": per_doc,
            "preserve_fraction": preserved / n, "edit_fraction": edited / n,
            "both_fraction": both / n,
            "reward": max(0.0, 0.7 * (both / n) + 0.15 * (preserved / n)
                          + 0.15 * (edited / n))}
