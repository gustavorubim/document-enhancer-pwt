from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from document_enhancer.errors import UnsupportedInputError
from document_enhancer.ingest.docx import DocxParser
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.pdf import PdfParser, ScannedPDFError

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _docx_bytes(*, macro: bool = False, traversal: bool = False, image: bool = False) -> bytes:
    image_paragraph = (
        "<w:p><w:r><w:t>Open the review screen.</w:t>"
        '<w:drawing><a:blip r:embed="rId2"/></w:drawing></w:r></w:p>'
        if image
        else ""
    )
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Monthly Loss Forecasting</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="7"/></w:numPr></w:pPr><w:r><w:t>Load approved extract</w:t></w:r></w:p>
  <w:tbl>
   <w:tr><w:tc><w:p><w:r><w:t>Input</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Owner</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:p><w:r><w:t>Claims</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Forecasting</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
  {image_paragraph}
  <w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure 1. Review flow</w:t></w:r></w:p>
  <w:p><w:hyperlink r:id="rId1"><w:r><w:t>External reference</w:t></w:r></w:hyperlink></w:p>
  <w:sectPr/>
 </w:body>
</w:document>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://example.com" TargetMode="External"/>
 {('<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/screen.png"/>') if image else ''}
</Relationships>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", relationships)
        if image:
            archive.writestr("word/media/screen.png", PNG_1X1)
        if macro:
            archive.writestr("word/vbaProject.bin", b"not executable here")
        if traversal:
            archive.writestr("../escape.txt", b"bad")
    return buffer.getvalue()


def _text_pdf_bytes(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 20 250 Td ({escaped}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


@pytest.mark.unit
def test_docx_preserves_body_order_headings_lists_tables_captions_and_relationship_warnings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "facts.docx"
    source.write_bytes(_docx_bytes())

    raw = DocxParser().parse(source)

    assert [block.block_type for block in raw.blocks] == [
        "heading",
        "paragraph",
        "table",
        "caption",
        "paragraph",
    ]
    assert raw.blocks[0].level == 1
    assert raw.blocks[1].list_kind == "ordered"
    assert raw.blocks[2].attributes["rows"][1] == ["Claims", "Forecasting"]
    assert raw.blocks[3].caption is True
    assert any(warning.code == "external_relationship_not_fetched" for warning in raw.warnings)
    assert any(asset.kind == "link" and asset.safety == "unresolved" for asset in raw.assets)
    assert all(
        asset.target != "https://example.com" or asset.safety == "unresolved"
        for asset in raw.assets
    )
    assert normalize_document(raw).selected_view is not None


@pytest.mark.unit
def test_docx_extracts_image_bytes_and_maps_them_to_source_span(tmp_path: Path) -> None:
    source = tmp_path / "figures.docx"
    source.write_bytes(_docx_bytes(image=True))

    raw = DocxParser().parse(source)

    figures = [asset for asset in raw.assets if asset.kind == "figure"]
    assert len(figures) == 1
    assert figures[0].payload == PNG_1X1
    assert figures[0].source_span_id is not None
    assert figures[0].metadata["caption"] == "Figure 1. Review flow"
    assert figures[0].metadata["occurrences"][0]["ordinal"] == 3


@pytest.mark.security
def test_docx_active_content_and_zip_traversal_fail_closed(tmp_path: Path) -> None:
    macro = tmp_path / "macro.docx"
    macro.write_bytes(_docx_bytes(macro=True))
    with pytest.raises(UnsupportedInputError, match="active content"):
        DocxParser().parse(macro)

    traversal = tmp_path / "traversal.docx"
    traversal.write_bytes(_docx_bytes(traversal=True))
    with pytest.raises(UnsupportedInputError, match="path-traversal"):
        DocxParser().parse(traversal)


@pytest.mark.unit
def test_text_pdf_preserves_page_provenance_and_warns_reading_order(tmp_path: Path) -> None:
    source = tmp_path / "facts.pdf"
    source.write_bytes(_text_pdf_bytes("Approved extract and loss formula"))

    raw = PdfParser().parse(source)

    assert raw.blocks
    assert raw.blocks[0].location.page == 1
    assert any(warning.code == "pdf_reading_order_best_effort" for warning in raw.warnings)
    assert "Approved extract" in raw.blocks[0].text


@pytest.mark.security
def test_scanned_pdf_is_detected_before_promotion(tmp_path: Path) -> None:
    source = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    with source.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(ScannedPDFError, match="OCR is unsupported"):
        PdfParser().parse(source)
