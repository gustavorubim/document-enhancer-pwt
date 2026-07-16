"""Deterministic textual, semantic, and source-to-target diff builders."""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
from collections.abc import Iterable

from document_enhancer.domain.audit import SemanticChange, SemanticDiff, SourceTargetMapping
from document_enhancer.domain.enums import AuditFindingKind
from document_enhancer.domain.questions import ContentLedger
from document_enhancer.domain.semantic import SemanticDocument


def textual_diff(source: str, target: str) -> str:
    return "".join(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            target.splitlines(keepends=True),
            fromfile="source/normalized.md",
            tofile="output/enhanced.md",
            lineterm="",
        )
    )


def _change_id(change_type: str, object_id: str) -> str:
    token = hashlib.sha256(f"{change_type}\0{object_id}".encode()).hexdigest()[:16].upper()
    return f"CHANGE-{token}"


def semantic_diff(
    before_objects: Iterable[dict[str, object]],
    before_edges: Iterable[dict[str, object]],
    after: SemanticDocument,
) -> SemanticDiff:
    before = {str(item["id"]): item for item in [*before_objects, *before_edges] if item.get("id")}
    current = {
        str(item.id): item.model_dump(mode="json")
        for item in [*after.objects, *after.relationships]
        if item.id
    }
    buckets: dict[str, list[SemanticChange]] = {
        "added": [],
        "removed": [],
        "changed": [],
        "retyped": [],
    }
    for object_id in sorted(current.keys() - before.keys()):
        buckets["added"].append(
            SemanticChange(
                change_id=_change_id("added", object_id),
                object_id=object_id,
                change_type="added",
                after=current[object_id],
                kind=AuditFindingKind.STRUCTURED_FACT,
            )
        )
    for object_id in sorted(before.keys() - current.keys()):
        buckets["removed"].append(
            SemanticChange(
                change_id=_change_id("removed", object_id),
                object_id=object_id,
                change_type="removed",
                before=before[object_id],
                kind=AuditFindingKind.OMISSION,
            )
        )
    for object_id in sorted(before.keys() & current.keys()):
        old, new = before[object_id], current[object_id]
        old_type = old.get("entity_type", old.get("relationship_type"))
        new_type = new.get("entity_type", new.get("relationship_type"))
        kind = "retyped" if old_type != new_type else "changed"
        if old != new:
            buckets[kind].append(
                SemanticChange(
                    change_id=_change_id(kind, object_id),
                    object_id=object_id,
                    change_type=kind,
                    before=old,
                    after=new,
                    kind=AuditFindingKind.STRUCTURED_FACT,
                )
            )
    return SemanticDiff(**buckets)


def source_target_mapping(ledger: ContentLedger) -> tuple[SourceTargetMapping, ...]:
    return tuple(
        SourceTargetMapping(
            source_span_id=item.source_span_id,
            target_anchor=item.target_anchor,
            target_object_ids=item.target_object_ids,
            disposition=item.disposition.value,
            reason=item.omitted_reason or item.rationale,
        )
        for item in sorted(ledger.entries, key=lambda value: value.source_ordinal or 0)
    )


def mapping_csv(mapping: Iterable[SourceTargetMapping]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "source_span_id",
            "target_anchor",
            "target_object_ids",
            "disposition",
            "reason",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for item in mapping:
        writer.writerow(
            {
                "source_span_id": item.source_span_id,
                "target_anchor": item.target_anchor or "",
                "target_object_ids": ";".join(sorted(item.target_object_ids)),
                "disposition": item.disposition,
                "reason": item.reason or "",
            }
        )
    return output.getvalue()


__all__ = ["mapping_csv", "semantic_diff", "source_target_mapping", "textual_diff"]
