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


def _page_image_objects(page: Any) -> list[tuple[str, Any]]:
    """Return direct embedded image XObjects without rasterizing a page or running OCR."""

    try:
        resources = page.get("/Resources")
        if resources is None:
            return []
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return []
        xobjects = xobjects.get_object()
        return sorted(
            (
                (str(name), value.get_object())
                for name, value in xobjects.items()
                if value.get_object().get("/Subtype") == "/Image"
            ),
            key=lambda item: item[0],
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return []


def _unsupported_image_asset(
    *,
    source_digest: str,
    page_number: int,
    image_name: str,
    source_span_id: str | None,
    ordinal: int,
    width: int,
    height: int,
    reason: str,
) -> EmbeddedAsset:
    location = SourceLocation(kind="pdf", page=page_number)
    identity = f"{source_digest}:{page_number}:{image_name}:{reason}".encode()
    return EmbeddedAsset(
        asset_id=f"asset-{sha256_bytes(identity)[:20]}",
        kind="figure",
        name=f"page-{page_number}-{image_name.lstrip('/') or 'image'}",
        source_span_id=source_span_id,
        location=location,
        safety="unsupported",
        metadata={
            "pdf_embedded_image": True,
            "xobject": image_name,
            "width": width,
            "height": height,
            "reason": reason,
            "occurrences": [
                {
                    "source_span_id": source_span_id,
                    "ordinal": ordinal,
                    "location": location.model_dump(mode="json"),
                }
            ],
        },
    )


def _extract_page_images(
    page: Any,
    *,
    source_digest: str,
    page_number: int,
    source_span_id: str | None,
    ordinal: int,
    remaining_images: int,
    max_image_bytes: int,
    max_image_pixels: int,
    max_image_dimension: int,
) -> tuple[list[EmbeddedAsset], list[ExtractionWarning], int]:
    assets: list[EmbeddedAsset] = []
    warnings: list[ExtractionWarning] = []
    extracted = 0
    location = SourceLocation(kind="pdf", page=page_number)
    for image_name, image_object in _page_image_objects(page):
        try:
            width = int(image_object.get("/Width", 0))
            height = int(image_object.get("/Height", 0))
        except (TypeError, ValueError):
            width = height = 0
        reason = ""
        if remaining_images - extracted <= 0:
            reason = "document_image_count_budget_exceeded"
        elif (
            width <= 0
            or height <= 0
            or width > max_image_dimension
            or height > max_image_dimension
            or width * height > max_image_pixels
        ):
            reason = "image_dimensions_budget_exceeded"
        if reason:
            assets.append(
                _unsupported_image_asset(
                    source_digest=source_digest,
                    page_number=page_number,
                    image_name=image_name,
                    source_span_id=source_span_id,
                    ordinal=ordinal,
                    width=width,
                    height=height,
                    reason=reason,
                )
            )
            warnings.append(
                ExtractionWarning(
                    code="pdf_image_budget_exceeded",
                    message="An embedded PDF image exceeded the configured extraction budget and was inventoried without decoding.",
                    severity="warning",
                    location=location,
                    source_digest=source_digest,
                )
            )
            continue
        try:
            image = page.images[image_name]
            payload = bytes(image.data)
        except (ImportError, KeyError, PdfReadError, OSError, TypeError, ValueError):
            assets.append(
                _unsupported_image_asset(
                    source_digest=source_digest,
                    page_number=page_number,
                    image_name=image_name,
                    source_span_id=source_span_id,
                    ordinal=ordinal,
                    width=width,
                    height=height,
                    reason="image_decode_failed",
                )
            )
            warnings.append(
                ExtractionWarning(
                    code="pdf_image_decode_failed",
                    message="An embedded PDF image could not be decoded safely and remains an unsupported inventory entry.",
                    severity="warning",
                    location=location,
                    source_digest=source_digest,
                )
            )
            continue
        suffix = Path(str(image.name)).suffix.lower()
        media_type = (
            "image/png"
            if suffix == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n")
            else "image/jpeg"
            if suffix in {".jpg", ".jpeg"} and payload.startswith(b"\xff\xd8\xff")
            else None
        )
        if media_type is None or len(payload) > max_image_bytes:
            reason = (
                "image_encoded_size_budget_exceeded"
                if len(payload) > max_image_bytes
                else "image_format_unsupported"
            )
            assets.append(
                _unsupported_image_asset(
                    source_digest=source_digest,
                    page_number=page_number,
                    image_name=image_name,
                    source_span_id=source_span_id,
                    ordinal=ordinal,
                    width=width,
                    height=height,
                    reason=reason,
                )
            )
            warnings.append(
                ExtractionWarning(
                    code=(
                        "pdf_image_budget_exceeded"
                        if len(payload) > max_image_bytes
                        else "pdf_image_format_unsupported"
                    ),
                    message="An embedded PDF image was inventoried but not promoted because its decoded format or size is unsupported.",
                    severity="warning",
                    location=location,
                    source_digest=source_digest,
                )
            )
            continue
        image_digest = sha256_bytes(payload)
        assets.append(
            EmbeddedAsset(
                asset_id=f"asset-{image_digest[:20]}",
                kind="figure",
                name=f"page-{page_number}-{image_name.lstrip('/')}{suffix}",
                source_span_id=source_span_id,
                location=location,
                media_type=media_type,
                digest=image_digest,
                size_bytes=len(payload),
                safety="passive",
                metadata={
                    "pdf_embedded_image": True,
                    "xobject": image_name,
                    "width": width,
                    "height": height,
                    "occurrences": [
                        {
                            "source_span_id": source_span_id,
                            "ordinal": ordinal,
                            "location": location.model_dump(mode="json"),
                        }
                    ],
                },
                payload=payload,
            )
        )
        extracted += 1
    return assets, warnings, extracted


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
    """Extract text and bounded direct image objects; image-only/scanned pages remain unsupported."""

    supported_suffixes = frozenset({".pdf"})

    def __init__(
        self,
        *,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        fail_on_scanned: bool = True,
        max_extracted_images: int = 16,
        max_image_bytes: int = 4_000_000,
        max_image_pixels: int = 16_000_000,
        max_image_dimension: int = 8192,
    ) -> None:
        if (
            min(
                max_extracted_images,
                max_image_bytes,
                max_image_pixels,
                max_image_dimension,
            )
            <= 0
        ):
            raise ValueError("PDF image extraction budgets must be positive")
        self.max_source_bytes = max_source_bytes
        self.fail_on_scanned = fail_on_scanned
        self.max_extracted_images = max_extracted_images
        self.max_image_bytes = max_image_bytes
        self.max_image_pixels = max_image_pixels
        self.max_image_dimension = max_image_dimension

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
        extracted_image_count = 0
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
                image_assets, image_warnings, extracted = _extract_page_images(
                    page,
                    source_digest=digest,
                    page_number=page_number,
                    source_span_id=block.span_id,
                    ordinal=block.ordinal,
                    remaining_images=self.max_extracted_images - extracted_image_count,
                    max_image_bytes=self.max_image_bytes,
                    max_image_pixels=self.max_image_pixels,
                    max_image_dimension=self.max_image_dimension,
                )
                assets.extend(image_assets)
                warnings.extend(image_warnings)
                extracted_image_count += extracted

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
            parser_version="2",
            scanned=bool(scanned_pages),
            metadata={
                "page_count": len(reader.pages),
                "scanned_pages": scanned_pages,
                "extracted_image_count": extracted_image_count,
                "image_extraction": {
                    "mode": "embedded_xobject_only",
                    "max_images": self.max_extracted_images,
                    "max_bytes_per_image": self.max_image_bytes,
                    "max_pixels_per_image": self.max_image_pixels,
                    "max_dimension": self.max_image_dimension,
                    "ocr": False,
                    "whole_page_rasterization": False,
                },
            },
        )


__all__ = ["PdfParser", "ScannedPDFError"]
