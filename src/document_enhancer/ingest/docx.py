"""Safe, order-preserving DOCX extraction.

DOCX is treated as a ZIP/XML container.  The parser reads only the document XML
and inventories relationships; it never follows external targets, executes
macros, or materializes embedded files.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from document_enhancer.errors import UnsupportedInputError

from .common import (
    DEFAULT_MAX_SOURCE_BYTES,
    block_digest,
    media_type_for,
    read_source,
    sha256_bytes,
    span_id,
)
from .models import EmbeddedAsset, ExtractionWarning, RawBlock, RawDocument, SourceLocation

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_UNSAFE_NAMES = ("vbaproject", "activeX", "oleObject", "embeddings")


def _safe_zip(data: bytes, *, max_uncompressed_bytes: int) -> zipfile.ZipFile:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise UnsupportedInputError("DOCX is not a valid ZIP container") from exc
    total = 0
    seen: set[str] = set()
    for info in archive.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or any(part == ".." for part in name.split("/")):
            archive.close()
            raise UnsupportedInputError("DOCX contains a path-traversal ZIP member")
        if name in seen:
            archive.close()
            raise UnsupportedInputError("DOCX contains duplicate ZIP members")
        seen.add(name)
        if info.file_size < 0 or info.file_size > max_uncompressed_bytes:
            archive.close()
            raise UnsupportedInputError("DOCX contains an oversized ZIP member")
        total += info.file_size
        if total > max_uncompressed_bytes:
            archive.close()
            raise UnsupportedInputError("DOCX uncompressed content exceeds the configured limit")
    return archive


def _text(element: ET.Element) -> str:
    parts: list[str] = []
    for child in element.iter():
        if child.tag == f"{W}t":
            parts.append(child.text or "")
        elif child.tag == f"{W}tab":
            parts.append("\t")
        elif child.tag in {f"{W}br", f"{W}cr"}:
            parts.append("\n")
    return "".join(parts)


def _paragraph_metadata(paragraph: ET.Element) -> dict[str, Any]:
    ppr = paragraph.find(f"{W}pPr")
    if ppr is None:
        return {}
    style = ppr.find(f"{W}pStyle")
    num_pr = ppr.find(f"{W}numPr")
    outline = ppr.find(f"{W}outlineLvl")
    metadata: dict[str, Any] = {}
    if style is not None:
        metadata["style"] = style.attrib.get(f"{W}val", "")
    if outline is not None and outline.attrib.get(f"{W}val") is not None:
        metadata["outline_level"] = int(outline.attrib[f"{W}val"]) + 1
    if num_pr is not None:
        ilvl = num_pr.find(f"{W}ilvl")
        num_id = num_pr.find(f"{W}numId")
        metadata["list_depth"] = int(ilvl.attrib.get(f"{W}val", "0")) if ilvl is not None else 0
        metadata["list_id"] = num_id.attrib.get(f"{W}val") if num_id is not None else None
    return metadata


def _relationship_map(
    archive: zipfile.ZipFile,
) -> tuple[dict[str, dict[str, str]], list[ExtractionWarning]]:
    warnings: list[ExtractionWarning] = []
    try:
        rel_xml = archive.read("word/_rels/document.xml.rels")
    except KeyError:
        return {}, warnings
    try:
        root = ET.fromstring(rel_xml)
    except ET.ParseError as exc:
        raise UnsupportedInputError("DOCX relationships XML is malformed") from exc
    result: dict[str, dict[str, str]] = {}
    for relation in root.findall(f"{REL}Relationship"):
        relation_id = relation.attrib.get("Id", "")
        target = relation.attrib.get("Target", "")
        target_mode = relation.attrib.get("TargetMode", "Internal")
        rel_type = relation.attrib.get("Type", "")
        result[relation_id] = {"target": target, "mode": target_mode, "type": rel_type}
        if target_mode.lower() == "external":
            warnings.append(
                ExtractionWarning(
                    code="external_relationship_not_fetched",
                    message="External DOCX relationship was inventoried but not fetched.",
                    severity="warning",
                )
            )
    return result, warnings


def _asset_for_relationship(
    *, archive: zipfile.ZipFile, relation_id: str, relation: dict[str, str], index: int
) -> EmbeddedAsset:
    target = relation.get("target", "")
    mode = relation.get("mode", "Internal").lower()
    suffix = Path(target).suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    }.get(suffix)
    digest: str | None = None
    size: int | None = None
    payload: bytes | None = None
    safety: str = "unresolved" if mode == "external" else "passive"
    if mode != "external":
        normalized = target.lstrip("/")
        if not normalized.startswith("word/"):
            normalized = f"word/{normalized}"
        try:
            payload = archive.read(normalized)
        except KeyError:
            safety = "unsupported"
        else:
            digest = sha256_bytes(payload)
            size = len(payload)
    return EmbeddedAsset(
        asset_id=(
            f"asset-{digest[:20]}"
            if digest
            else f"asset-{sha256_bytes(f'{relation_id}:{index}:{target}'.encode())[:20]}"
        ),
        kind=(
            "link"
            if "hyperlink" in relation.get("type", "").lower()
            else "figure"
            if "image" in relation.get("type", "").lower()
            else "embedded_file"
        ),
        name=Path(target).name or relation_id,
        media_type=media_type,
        digest=digest,
        size_bytes=size,
        safety=safety,  # type: ignore[arg-type]
        relationship_id=relation_id,
        target=target,
        metadata={"relationship_type": relation.get("type", ""), "target_mode": mode},
        payload=payload,
    )


class DocxParser:
    """Parse paragraphs and tables in document.xml body order."""

    supported_suffixes = frozenset({".docx"})

    def __init__(
        self,
        *,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
        max_uncompressed_bytes: int = 100 * 1024 * 1024,
        fail_on_unsafe: bool = True,
    ) -> None:
        self.max_source_bytes = max_source_bytes
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.fail_on_unsafe = fail_on_unsafe

    def can_parse(self, source: Path) -> bool:
        return source.suffix.lower() in self.supported_suffixes

    def parse(self, source: Path) -> RawDocument:
        data = read_source(source, max_bytes=self.max_source_bytes)
        source_digest = sha256_bytes(data)
        archive = _safe_zip(data, max_uncompressed_bytes=self.max_uncompressed_bytes)
        try:
            names = {info.filename for info in archive.infolist()}
            unsafe_members = [
                name
                for name in names
                if any(token.lower() in name.lower() for token in _UNSAFE_NAMES)
            ]
            if "word/document.xml" not in names:
                raise UnsupportedInputError("DOCX is missing word/document.xml")
            try:
                xml_data = archive.read("word/document.xml")
            except KeyError as exc:
                raise UnsupportedInputError("DOCX is missing word/document.xml") from exc
            if re.search(rb"<!DOCTYPE|<!ENTITY", xml_data, re.I):
                raise UnsupportedInputError("DOCX XML contains unsupported entity declarations")
            try:
                root = ET.fromstring(xml_data)
            except ET.ParseError as exc:
                raise UnsupportedInputError("DOCX document XML is malformed") from exc
            relationships, warnings = _relationship_map(archive)
            if unsafe_members:
                warnings.append(
                    ExtractionWarning(
                        code="unsafe_embedded_content",
                        message="DOCX contains macros or executable/active embedded content; it was not opened.",
                        severity="error",
                    )
                )
                if self.fail_on_unsafe:
                    raise UnsupportedInputError("DOCX contains unsupported active content")

            assets: list[EmbeddedAsset] = []
            for index, (relation_id, relation) in enumerate(sorted(relationships.items())):
                relation_type = relation.get("type", "").lower()
                if (
                    "image" in relation_type
                    or "oleobject" in relation_type
                    or "package" in relation_type
                    or "hyperlink" in relation_type
                ):
                    assets.append(
                        _asset_for_relationship(
                            archive=archive, relation_id=relation_id, relation=relation, index=index
                        )
                    )

            body = root.find(f"{W}body")
            if body is None:
                raise UnsupportedInputError("DOCX document has no document body")
            blocks: list[RawBlock] = []
            paragraph_index = 0
            table_index = 0
            for child_index, child in enumerate(list(body)):
                if child.tag == f"{W}p":
                    value = _text(child)
                    metadata = _paragraph_metadata(child)
                    style = str(metadata.get("style", "")) or None
                    level = metadata.get("outline_level")
                    if level is None and style and style.lower().startswith("heading"):
                        match = re.search(r"(\d+)$", style)
                        level = int(match.group(1)) if match else 1
                    is_caption = bool(style and style.lower() == "caption") or bool(
                        re.match(r"\s*(?:figure|table)\s+\d+", value, re.I)
                    )
                    block_type = "heading" if level is not None else "paragraph"
                    if is_caption:
                        block_type = "caption"
                    location = SourceLocation(
                        kind="docx",
                        paragraph_index=paragraph_index,
                        xml_path=f"/w:document/w:body/w:p[{child_index + 1}]",
                    )
                    blocks.append(
                        RawBlock(
                            span_id=span_id(
                                source_digest=source_digest,
                                ordinal=len(blocks),
                                block_type=block_type,
                                text=value,
                                location=location,
                            ),
                            ordinal=len(blocks),
                            block_type=block_type,
                            text=value,
                            location=location,
                            content_digest=block_digest(block_type, value, location),
                            level=level,
                            style=style,
                            list_kind="ordered" if metadata.get("list_id") else "none",
                            list_depth=metadata.get("list_depth"),
                            caption=is_caption,
                            attributes={
                                "list_id": metadata.get("list_id"),
                                "relationship_ids": sorted(
                                    {
                                        value_id
                                        for element in child.iter()
                                        for attribute, value_id in element.attrib.items()
                                        if attribute in {f"{R}embed", f"{R}id"}
                                    }
                                ),
                            },
                        )
                    )
                    paragraph_index += 1
                elif child.tag == f"{W}tbl":
                    rows: list[list[str]] = []
                    for row_index, row in enumerate(child.findall(f"{W}tr")):
                        cells: list[str] = []
                        for column_index, cell in enumerate(row.findall(f"{W}tc")):
                            cell_value = _text(cell)
                            cells.append(cell_value)
                            if not cell_value:
                                warnings.append(
                                    ExtractionWarning(
                                        code="empty_table_cell",
                                        message="DOCX table contains an empty cell; cell order was retained.",
                                        severity="info",
                                        location=SourceLocation(
                                            kind="docx",
                                            table_index=table_index,
                                            row=row_index,
                                            column=column_index,
                                        ),
                                    )
                                )
                        rows.append(cells)
                    value = "\n".join("\t".join(row) for row in rows)
                    location = SourceLocation(
                        kind="docx",
                        table_index=table_index,
                        xml_path=f"/w:document/w:body/w:tbl[{child_index + 1}]",
                    )
                    blocks.append(
                        RawBlock(
                            span_id=span_id(
                                source_digest=source_digest,
                                ordinal=len(blocks),
                                block_type="table",
                                text=value,
                                location=location,
                            ),
                            ordinal=len(blocks),
                            block_type="table",
                            text=value,
                            location=location,
                            content_digest=block_digest("table", value, location),
                            attributes={
                                "rows": rows,
                                "column_count": max((len(row) for row in rows), default=0),
                                "relationship_ids": sorted(
                                    {
                                        value_id
                                        for element in child.iter()
                                        for attribute, value_id in element.attrib.items()
                                        if attribute in {f"{R}embed", f"{R}id"}
                                    }
                                ),
                            },
                        )
                    )
                    table_index += 1
                elif child.tag in {f"{W}sectPr", f"{W}proofErr"}:
                    continue
                else:
                    warnings.append(
                        ExtractionWarning(
                            code="unsupported_docx_body_element",
                            message="Unsupported DOCX body element was retained only in parser metadata.",
                            severity="warning",
                            location=SourceLocation(
                                kind="docx", xml_path=f"/w:document/w:body[{child_index + 1}]"
                            ),
                        )
                    )

            block_by_relationship: dict[str, list[RawBlock]] = {}
            for block in blocks:
                for relation_id in block.attributes.get("relationship_ids", []):
                    block_by_relationship.setdefault(str(relation_id), []).append(block)
            located_assets: list[EmbeddedAsset] = []
            for asset in assets:
                occurrences = block_by_relationship.get(asset.relationship_id or "", [])
                if asset.kind == "figure" and occurrences:
                    first = occurrences[0]
                    caption = next(
                        (
                            block.text.strip()
                            for block in blocks[first.ordinal + 1 : first.ordinal + 3]
                            if block.caption and block.text.strip()
                        ),
                        "",
                    )
                    located_assets.append(
                        asset.model_copy(
                            update={
                                "source_span_id": first.span_id,
                                "location": first.location,
                                "metadata": {
                                    **asset.metadata,
                                    "caption": caption,
                                    "occurrences": [
                                        {
                                            "source_span_id": block.span_id,
                                            "ordinal": block.ordinal,
                                            "location": block.location.model_dump(mode="json"),
                                        }
                                        for block in occurrences
                                    ],
                                },
                            }
                        )
                    )
                else:
                    located_assets.append(asset)
            assets = located_assets

            if any("footnotes" in name for name in names):
                warnings.append(
                    ExtractionWarning(
                        code="footnotes_not_in_body_order",
                        message="DOCX footnotes are present; body content is preserved, footnote order is separate.",
                        severity="warning",
                    )
                )
            if not blocks:
                warnings.append(
                    ExtractionWarning(
                        code="empty_docx_body",
                        message="DOCX body contains no extractable paragraphs or tables.",
                        severity="error",
                    )
                )
            return RawDocument(
                source_path=source,
                source_name=source.name,
                media_type=media_type_for(source),
                size_bytes=len(data),
                source_digest=source_digest,
                blocks=tuple(blocks),
                warnings=tuple(warnings),
                assets=tuple(assets),
                parser_name="docx",
                parser_version="1",
                metadata={"zip_members": len(names), "unsafe_members": unsafe_members},
            )
        finally:
            archive.close()


__all__ = ["DocxParser"]
