"""Stable semantic chunks derived only from approved M6 artifacts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from document_enhancer.domain.enums import EntityType, ReviewStatus
from document_enhancer.domain.run import ExportChunk
from document_enhancer.rewrite import EnhancedDocumentModel

_ATOMIC_TYPES = {
    EntityType.PROCESS_STEP,
    EntityType.METHODOLOGY_STEP,
    EntityType.RULE,
    EntityType.CONTROL,
    EntityType.ASSUMPTION,
    EntityType.LIMITATION,
    EntityType.EXCEPTION,
    EntityType.DEPENDENCY,
    EntityType.CALCULATOR,
    EntityType.REQUIREMENT,
    EntityType.EVIDENCE,
    EntityType.STATEMENT,
}


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chunk_id(
    document_id: str, version_id: str, section_id: str, object_id: str, ordinal: int
) -> str:
    identity = f"{document_id}\0{version_id}\0{section_id}\0{object_id}\0{ordinal}"
    return "CHUNK-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()


def _parts(text: str, max_chars: int) -> tuple[str, ...]:
    if len(text) <= max_chars:
        return (text.strip(),)
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    parts: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return tuple(parts or [text.strip()])


def _terms(values: Iterable[str]) -> list[str]:
    return sorted({item.strip() for item in values if item.strip()}, key=str.casefold)


def build_chunks(model: EnhancedDocumentModel, *, max_chars: int = 4000) -> tuple[ExportChunk, ...]:
    """Build stable chunks; provisional and unresolved material is always excluded."""

    unresolved_objects = {
        issue.target_object_id for issue in model.open_issues if issue.status == "open"
    }
    objects = {item.id: item for item in model.objects}
    chunks: list[ExportChunk] = []
    global_ordinal = 0
    for section in sorted(model.sections, key=lambda item: (item.order, item.section_id)):
        if section.open_issue_ids:
            continue
        section_objects = [objects[item] for item in section.object_ids if item in objects]
        atomic = [
            item
            for item in section_objects
            if item.entity_type in _ATOMIC_TYPES
            and not item.provisional
            and item.id not in unresolved_objects
            and item.review_status not in {ReviewStatus.REJECTED, ReviewStatus.DEPRECATED}
        ]
        emitted_ids: set[str] = set()
        for entity in sorted(atomic, key=lambda item: item.id):
            text = getattr(entity, "text", None) or entity.name
            for local_ordinal, part in enumerate(_parts(str(text), max_chars)):
                chunks.append(
                    ExportChunk(
                        chunk_id=_chunk_id(
                            model.document.id,
                            model.version.id,
                            section.section_id,
                            entity.id,
                            local_ordinal,
                        ),
                        document_id=model.document.id,
                        version_id=model.version.id,
                        section_id=section.section_id,
                        section_path=[section.heading],
                        object_ids=[entity.id],
                        canonical_terms=_terms([entity.name, *entity.aliases]),
                        text=part,
                        source_span_ids=[entity.provenance.source_span_id]
                        if entity.provenance.source_span_id
                        else [],
                        markdown_anchor=section.anchor,
                        authority=entity.authority or entity.provenance.authority,
                        review_status=entity.review_status or entity.provenance.review_status,
                        provenance=[entity.provenance],
                        security_classification=model.version.confidentiality,
                        valid_from=str(entity.validity.valid_from)
                        if entity.validity and entity.validity.valid_from
                        else None,
                        valid_to=str(entity.validity.valid_to)
                        if entity.validity and entity.validity.valid_to
                        else None,
                        checksum=_checksum(part),
                        ordinal=global_ordinal,
                    )
                )
                global_ordinal += 1
            emitted_ids.add(entity.id)
        narrative = section.body.strip()
        if narrative:
            remaining_ids = sorted(set(section.object_ids) - emitted_ids)
            provenance = section.provenance
            if not provenance:
                continue
            for local_ordinal, part in enumerate(_parts(narrative, max_chars)):
                chunks.append(
                    ExportChunk(
                        chunk_id=_chunk_id(
                            model.document.id,
                            model.version.id,
                            section.section_id,
                            section.section_id,
                            local_ordinal,
                        ),
                        document_id=model.document.id,
                        version_id=model.version.id,
                        section_id=section.section_id,
                        section_path=[section.heading],
                        object_ids=remaining_ids,
                        canonical_terms=_terms(
                            [objects[item].name for item in remaining_ids if item in objects]
                        ),
                        text=part,
                        source_span_ids=sorted(set(section.source_span_ids)),
                        markdown_anchor=section.anchor,
                        authority=provenance[0].authority,
                        review_status=provenance[0].review_status,
                        provenance=provenance,
                        security_classification=model.version.confidentiality,
                        valid_from=None,
                        valid_to=None,
                        checksum=_checksum(part),
                        ordinal=global_ordinal,
                    )
                )
                global_ordinal += 1
    return tuple(chunks)


__all__ = ["build_chunks"]
