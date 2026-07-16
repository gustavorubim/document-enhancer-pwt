"""Deterministic text-PDF extraction with page provenance and OCR fail-closed behavior."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from document_enhancer.errors import UnsupportedInputError

from .common import (
    DEFAULT_MAX_SOURCE_BYTES,
    block_digest,
    inventory_text_assets,
    media_type_for,
    read_source,
    sha256_bytes,
    span_id,
)
from .models import EmbeddedAsset, ExtractionWarning, RawBlock, RawDocument, SourceLocation


class ScannedPDFError(UnsupportedInputError):
    """Raised when OCR would be required to read one or more PDF pages."""


def _page_has_images(page: Any) -> bool:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return False
        xobjects = xobjects.get_object()
        return any(value.get_object().get("/Subtype") == "/Image" for value in xobjects.values())
    except (AttributeError, KeyError, TypeError, ValueError):
        return False


def _page_links(page: Any, page_number: int) -> tuple[EmbeddedAsset, ...]:
    assets: list[EmbeddedAsset] = []
    try:
        annotations = page.get("/Annots") or []
        for index, annotation_ref in enumerate(annotations):
            annotation = annotation_ref.get_object()
            action = annotation.get("/A")
            if action is None:
                continue
            action = action.get_object()
            uri = action.get("/URI")
            if uri is None:
                continue
            target = str(uri)
            safety = (
                "passive"
                if target.lower().startswith(("http://", "https://", "mailto:"))
                else "unsafe"
            )
            assets.append(
                EmbeddedAsset(
                    asset_id=f"asset-{sha256_bytes(f'pdf:{page_number}:link:{index}:{target}'.encode())[:20]}",
                    kind="link",
                    name=target,
                    location=SourceLocation(kind="pdf", page=page_number),
                    safety=safety,  # type: ignore[arg-type]
                    target=target,
                    metadata={"annotation": "URI"},
                )
            )
    except (AttributeError, KeyError, TypeError, ValueError):
        return ()
    return tuple(assets)


class PdfParser:
    """Extract text per page using pypdf; image-only/scanned pages are unsupported."""

    supported_suffixes = frozenset({".pdf"})

    def __init__(
        self,
        *,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        fail_on_scanned: bool = True,
    ) -> None:
        self.max_source_bytes = max_source_bytes
        self.fail_on_scanned = fail_on_scanned

    def can_parse(self, source: Path) -> bool:
        return source.suffix.lower() in self.supported_suffixes

    def parse(self, source: Path) -> RawDocument:
        data = read_source(source, max_bytes=self.max_source_bytes)
        digest = sha256_bytes(data)
        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
        except (PdfReadError, OSError, ValueError) as exc:
            raise UnsupportedInputError("PDF could not be parsed safely") from exc
        if reader.is_encrypted:
            raise UnsupportedInputError(
                "Encrypted PDFs are unsupported; decrypt outside the parser"
            )
        if not reader.pages:
            raise UnsupportedInputError("PDF has no pages")

        blocks: list[RawBlock] = []
        warnings: list[ExtractionWarning] = []
        assets: list[EmbeddedAsset] = []
        scanned_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except (PdfReadError, OSError, ValueError) as exc:
                warnings.append(
                    ExtractionWarning(
                        code="pdf_text_extraction_failed",
                        message="Text extraction failed for a page; OCR is not attempted.",
                        severity="error",
                        location=SourceLocation(kind="pdf", page=page_number),
                    )
                )
                page_text = ""
                _ = exc
            if not page_text.strip():
                scanned_pages.append(page_number)
                warnings.append(
                    ExtractionWarning(
                        code="scanned_or_image_only_page",
                        message="PDF page has no extractable text; OCR is unsupported and the page is not interpreted.",
                        severity="error",
                        location=SourceLocation(kind="pdf", page=page_number),
                    )
                )
            else:
                warnings.append(
                    ExtractionWarning(
                        code="pdf_reading_order_best_effort",
                        message="PDF text order is parser-derived and may be unreliable for multi-column layouts.",
                        severity="warning",
                        location=SourceLocation(kind="pdf", page=page_number),
                    )
                )
                location = SourceLocation(kind="pdf", page=page_number)
                block_type = "page_text"
                block = RawBlock(
                    span_id=span_id(
                        source_digest=digest,
                        ordinal=len(blocks),
                        block_type=block_type,
                        text=page_text,
                        location=location,
                    ),
                    ordinal=len(blocks),
                    block_type=block_type,
                    text=page_text,
                    location=location,
                    content_digest=block_digest(block_type, page_text, location),
                    attributes={
                        "page_number": page_number,
                        "paragraphs": tuple(
                            part.strip() for part in page_text.split("\n\n") if part.strip()
                        ),
                    },
                )
                blocks.append(block)
                link_assets = _page_links(page, page_number)
                assets.extend(link_assets)
                if _page_has_images(page):
                    assets.append(
                        EmbeddedAsset(
                            asset_id=f"asset-{sha256_bytes(f'pdf:{page_number}:figure'.encode())[:20]}",
                            kind="figure",
                            name=f"page-{page_number}-image",
                            source_span_id=block.span_id,
                            location=location,
                            safety="passive",
                            metadata={"page_image": True},
                        )
                    )

        if scanned_pages and self.fail_on_scanned:
            pages = ", ".join(str(page) for page in scanned_pages)
            raise ScannedPDFError(
                "PDF contains scanned or image-only pages; OCR is unsupported and the input was not promoted.",
                detail=f"pages={pages}; source={source.name}",
            )
        text_warnings, text_assets = inventory_text_assets(tuple(blocks))
        return RawDocument(
            source_path=source,
            source_name=source.name,
            media_type=media_type_for(source),
            size_bytes=len(data),
            source_digest=digest,
            blocks=tuple(blocks),
            warnings=tuple(warnings) + text_warnings,
            assets=tuple(assets) + tuple(text_assets),
            parser_name="pdf-pypdf",
            parser_version="1",
            scanned=bool(scanned_pages),
            metadata={"page_count": len(reader.pages), "scanned_pages": scanned_pages},
        )


__all__ = ["PdfParser", "ScannedPDFError"]
