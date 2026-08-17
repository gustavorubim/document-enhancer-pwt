"""Small deterministic PDF builders shared by parser and end-to-end tests."""

from __future__ import annotations

import io

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


def text_pdf_with_embedded_rgb(
    text: str,
    *,
    width: int = 4,
    height: int = 3,
    declared_width: int | None = None,
    declared_height: int | None = None,
) -> bytes:
    """Return a text PDF containing one displayed, direct RGB image XObject."""

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)

    image = DecodedStreamObject()
    pixels = bytes([220, 52, 70, 44, 132, 220, 36, 180, 126])
    sample_count = max(width * height, 1)
    image.set_data((pixels * ((sample_count + 2) // 3))[: sample_count * 3])
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(declared_width or width),
            NameObject("/Height"): NumberObject(declared_height or height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image)

    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
            NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): image_ref}),
        }
    )
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = DecodedStreamObject()
    content.set_data(
        (f"BT /F1 12 Tf 20 250 Td ({escaped}) Tj ET\nq 120 0 0 75 20 130 cm /Im1 Do Q\n").encode(
            "ascii"
        )
    )
    page[NameObject("/Contents")] = writer._add_object(content)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


__all__ = ["text_pdf_with_embedded_rgb"]
