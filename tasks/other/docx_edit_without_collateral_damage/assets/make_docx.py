"""Build a rich .docx by hand, so every part that a careless edit destroys is present.

A .docx is a zip of OOXML parts. Libraries that model only paragraphs and runs drop
the rest on save: tracked changes, comments, footnotes, content controls, custom XML,
bookmarks and the relationships that bind them. This builds a document that contains
all of those, so an edit that loses them is detectable.
"""
from __future__ import annotations

import pathlib
import sys
import zipfile

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"')

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
<Override PartName="/customXml/item1.xml" ContentType="application/xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/>
<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>
<Relationship Id="rId6" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rId7" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
<Relationship Id="rId8" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
<Relationship Id="rId9" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.invalid/spec" TargetMode="External"/>
<Relationship Id="rId10" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml" Target="../customXml/item1.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="160"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/><w:color w:val="1F4E79"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="2E74B5"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/></w:pPr><w:rPr><w:i/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Emphasis"><w:name w:val="Emphasis"/><w:rPr><w:i/><w:color w:val="C00000"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders><w:top w:val="single" w:sz="4" w:color="auto"/><w:left w:val="single" w:sz="4" w:color="auto"/><w:bottom w:val="single" w:sz="4" w:color="auto"/><w:right w:val="single" w:sz="4" w:color="auto"/><w:insideH w:val="single" w:sz="4" w:color="auto"/><w:insideV w:val="single" w:sz="4" w:color="auto"/></w:tblBorders></w:tblPr></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering {NS}>
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl>
<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="1440" w:hanging="360"/></w:pPr></w:lvl>
</w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""

SETTINGS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings {NS}><w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/>
<w:trackChanges/><w:evenAndOddHeaders w:val="false"/>
<w:rsids><w:rsidRoot w:val="00A1B2C3"/><w:rsid w:val="00A1B2C3"/></w:rsids></w:settings>"""

FOOTNOTES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes {NS}>
<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>
<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r><w:continuationSeparator/></w:r></w:p></w:footnote>
<w:footnote w:id="1"><w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> Measured against the 2023 baseline.</w:t></w:r></w:p></w:footnote>
</w:footnotes>"""

COMMENTS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:comments {NS}>
<w:comment w:id="1" w:author="R. Iyer" w:date="2026-02-11T09:14:00Z" w:initials="RI">
<w:p><w:r><w:t>Confirm this figure with finance before publication.</w:t></w:r></w:p></w:comment>
</w:comments>"""

HEADER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr {NS}><w:p><w:pPr><w:jc w:val="right"/></w:pPr><w:r><w:t>Quarterly Operations Review — [[CYCLE]]</w:t></w:r></w:p></w:hdr>"""

FOOTER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr {NS}><w:p><w:pPr><w:jc w:val="center"/></w:pPr>
<w:r><w:t xml:space="preserve">[[CYCLE]] | </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>"""

CUSTOM_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<review xmlns="urn:acme:review"><cycle>Q1</cycle><owner>operations</owner></review>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Quarterly Operations Review</dc:title><dc:creator>operations</dc:creator>
<cp:lastModifiedBy>operations</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">2026-01-05T08:00:00Z</dcterms:created></cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Legacy Report Writer</Application><Pages>2</Pages></Properties>"""

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000080000000808020000004b6d29dc"
    "0000001b49444154789c636070c8fcffcf40016260d4008c0c8c0c0c00b1c50469"
    "1b6cba0000000049454e44ae426082")


def paragraph(text, style=None, align=None, extra="", runs=None):
    ppr = ""
    if style or align:
        ppr = "<w:pPr>"
        if style:
            ppr += f'<w:pStyle w:val="{style}"/>'
        if align:
            ppr += f'<w:jc w:val="{align}"/>'
        ppr += "</w:pPr>"
    body = runs if runs else f"<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r>"
    return f"<w:p>{ppr}{body}{extra}</w:p>"


def build_document(seed: int) -> str:
    """The body. Every construct here is one a careless rewrite tends to drop.

    The seed varies how much of each construct appears, so a script tuned to one
    document does not carry to the next.
    """
    import random
    rng = random.Random(seed)
    n = seed % 3
    paras = []
    paras.append(paragraph("Quarterly Operations Review", style="Heading1", align="left"))
    paras.append(paragraph(
        "This section summarises throughput, incident load and the remediation backlog "
        "for the period under review.", align="left"))
    # a run carrying a footnote reference
    paras.append(paragraph(
        "", align="left",
        runs='<w:r><w:t xml:space="preserve">Throughput rose by nine percent</w:t></w:r>'
             '<w:r><w:footnoteReference w:id="1"/></w:r>'
             '<w:r><w:t xml:space="preserve"> against the prior quarter.</w:t></w:r>'))
    # a commented range
    paras.append(paragraph(
        "", align="left",
        runs='<w:commentRangeStart w:id="1"/>'
             '<w:r><w:t xml:space="preserve">Unit cost fell to 4.21 per shipment.</w:t></w:r>'
             '<w:commentRangeEnd w:id="1"/>'
             '<w:r><w:commentReference w:id="1"/></w:r>'))
    # tracked changes: an insertion and a deletion
    paras.append(paragraph(
        "", align="left",
        runs='<w:ins w:id="101" w:author="R. Iyer" w:date="2026-02-11T09:20:00Z">'
             '<w:r><w:t xml:space="preserve">Backlog closure improved. </w:t></w:r></w:ins>'
             '<w:del w:id="102" w:author="R. Iyer" w:date="2026-02-11T09:21:00Z">'
             '<w:r><w:delText xml:space="preserve">Backlog remains a concern. </w:delText></w:r></w:del>'
             '<w:r><w:t>Remediation continues.</w:t></w:r>'))
    for extra in range(rng.randint(0, 3)):
        paras.append(paragraph(
            f"Supplementary note {extra + 1}: capacity held within the agreed envelope.",
            align="left"))
    paras.append(paragraph("Findings", style="Heading2", align="left"))
    # numbered list, two levels
    for lvl, txt in ((0, "Incident volume declined in every region."),
                     (1, "The largest fall was in the northern cluster."),
                     (0, "Two suppliers missed their service commitments.")):
        paras.append(
            f'<w:p><w:pPr><w:numPr><w:ilvl w:val="{lvl}"/><w:numId w:val="1"/></w:numPr>'
            f'<w:jc w:val="left"/></w:pPr><w:r><w:t xml:space="preserve">{txt}</w:t></w:r></w:p>')
    # a hyperlink and a bookmark
    paras.append(
        '<w:p><w:pPr><w:jc w:val="left"/></w:pPr>'
        '<w:bookmarkStart w:id="5" w:name="spec_ref"/>'
        '<w:hyperlink r:id="rId9"><w:r><w:rPr><w:rStyle w:val="Emphasis"/></w:rPr>'
        '<w:t>See the published specification.</w:t></w:r></w:hyperlink>'
        '<w:bookmarkEnd w:id="5"/></w:p>')
    # a content control wrapping a paragraph
    paras.append(
        '<w:sdt><w:sdtPr><w:alias w:val="Owner"/><w:tag w:val="owner"/>'
        '<w:id w:val="77"/><w:text/></w:sdtPr><w:sdtContent>'
        '<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:t>Owner: operations</w:t></w:r></w:p>'
        '</w:sdtContent></w:sdt>')
    # a table
    table_rows = [("Region", "Incidents", "Trend"),
                  ("North", str(12 + n), "down"),
                  ("South", str(19 - n), "flat")]
    if rng.random() < 0.5:
        table_rows.append(("East", str(7 + n), "up"))
    rows = "".join(
        "<w:tr>" + "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/></w:tcPr>'
            f'<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>'
            for c in row) + "</w:tr>"
        for row in table_rows)
    paras.append(f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
                 f'<w:tblW w:w="0" w:type="auto"/></w:tblPr>{rows}</w:tbl>')
    # an inline image
    paras.append(
        '<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:drawing>'
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" distT="0" distB="0" distL="0" distR="0">'
        '<wp:extent cx="304800" cy="304800"/><wp:docPr id="1" name="chip"/>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="1" name="chip"/><pic:cNvPicPr/></pic:nvPicPr>'
        '<pic:blipFill><a:blip r:embed="rId8"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="304800" cy="304800"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')
    if rng.random() < 0.7:
        paras.append(paragraph("The remainder of the review is unchanged from the last cycle.",
                               style="Quote", align="left"))
    sect = ('<w:sectPr><w:headerReference w:type="default" r:id="rId6"/>'
            '<w:footerReference w:type="default" r:id="rId7"/>'
            '<w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document {NS}><w:body>{"".join(paras)}{sect}</w:body></w:document>')


def build(seed: int, path: pathlib.Path):
    parts = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": build_document(seed),
        "word/_rels/document.xml.rels": DOC_RELS,
        "word/styles.xml": STYLES,
        "word/numbering.xml": NUMBERING,
        "word/settings.xml": SETTINGS,
        "word/footnotes.xml": FOOTNOTES,
        "word/comments.xml": COMMENTS,
        "word/header1.xml": HEADER,
        "word/footer1.xml": FOOTER,
        "customXml/item1.xml": CUSTOM_XML,
        "docProps/core.xml": CORE,
        "docProps/app.xml": APP,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
        z.writestr("word/media/image1.png", PNG)


if __name__ == "__main__":
    build(int(sys.argv[1]), pathlib.Path(sys.argv[2]))
    print("wrote", sys.argv[2])
