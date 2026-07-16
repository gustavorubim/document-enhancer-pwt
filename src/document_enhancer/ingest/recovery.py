"""Gemini-backed structure recovery with deterministic, fail-closed promotion.

This module is deliberately an adapter at the ingestion boundary.  Parser output stays in the
lane-local immutable contracts, while model calls use the authoritative WT1 source and structure
contracts.  Model prompts contain only source data inside the governed prompt-pack boundary;
artifacts and call manifests contain digests and identifiers, never prompt text or credentials.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from document_enhancer.domain.analysis import (
    BlockDisposition,
    RecoveredSection,
    StructureAssociation,
    StructureDisagreement,
    StructureRecoveryProposal,
    StructureScan,
)
from document_enhancer.domain.enums import (
    DocumentType,
    SourceBlockType,
    StructureDecision,
    StructureDisposition,
)
from document_enhancer.domain.provenance import SourceLocation as DomainSourceLocation
from document_enhancer.domain.run import PromptResolution
from document_enhancer.domain.source import (
    RawDocument as DomainRawDocument,
)
from document_enhancer.domain.source import (
    SourceBlock,
    StructuralSection,
    StructuralView,
)
from document_enhancer.errors import ValidationError
from document_enhancer.llm.models import CallManifest, GeminiModelGateway
from document_enhancer.llm.profiles import ROUTE_FLASH_LITE, resolve_route

from .common import canonical_json, sha256_bytes
from .models import (
    NormalizedDocument,
    OutlineSection,
    ParserOutline,
    RawDocument,
    RecoveryThresholds,
    SelectedStructuralView,
    StructuralBlockDisposition,
    StructuralBlockSegment,
    StructureQualityReport,
)
from .normalize import normalize_document
from .outline import build_parser_view

StructureMode = Literal["auto", "parser", "recover", "force", "off"]


class PromptComposerLike(Protocol):
    def compose_with_metadata(self, prompt_id: str, variables: Mapping[str, Any]) -> Any: ...


# WT4's native Gemini schema normalizer intentionally rejects regex constraints. These wire
# models keep the provider schema compatible; every returned object is immediately converted into
# the authoritative WT1 model, whose validators enforce the stricter identifiers and digests.
class GatewayBoundaryRegion(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start_span_id: str
    end_span_id: str
    confidence: float
    rationale: str | None = None


class GatewayStructureScan(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scan_id: str
    document_id: str
    source_digest: str
    parser_outline_digest: str
    decision: StructureDecision
    confidence: float
    boundary_regions: list[GatewayBoundaryRegion] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    model: str
    ref: str = Field(alias="prompt_id")
    digest: str = Field(alias="prompt_digest")


class GatewayRecoveredSection(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    section_id: str
    label: str
    level: int
    start_span_id: str
    end_span_id: str
    source_heading_text: str | None = None
    confidence: float
    rationale: str | None = None
    inferred_label: bool = False


class GatewayBlockSegment(BaseModel):
    """Provider-safe wire shape; authoritative validators enforce every constraint."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    segment_id: str
    char_start: int
    char_end: int
    offset_unit: str = "python_characters"
    disposition: StructureDisposition
    section_id: str | None = None
    confidence: float
    rationale: str | None = None
    slice_sha256: str


class GatewayBlockDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    span_id: str
    disposition: StructureDisposition
    section_id: str | None = None
    text_digest_ref: str = Field(alias="source_text_digest")
    confidence: float
    rationale: str | None = None
    segments: list[GatewayBlockSegment] | None = None


class GatewayStructureAssociation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    span_id: str
    section_id: str
    association: Literal["table", "figure", "formula", "caption", "nearby"]


class GatewayStructureDisagreement(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    span_ids: list[str]
    parser_label: str | None = None
    model_label: str | None = None
    resolution: str | None = None
    requires_review: bool = True


class GatewayBoundaryAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    alternative_id: str
    sections: list[GatewayRecoveredSection]
    confidence: float
    reason: str


class GatewayStructureValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    passed: bool
    covered_span_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GatewayStructureRecoveryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    recovery_id: str
    document_id: str
    source_digest: str
    proposed_document_type: DocumentType | None = None
    proposed_title: str | None = None
    confidence: float
    sections: list[GatewayRecoveredSection]
    dispositions: list[GatewayBlockDisposition]
    associations: list[GatewayStructureAssociation] = Field(default_factory=list)
    boundary_alternatives: list[GatewayBoundaryAlternative] = Field(default_factory=list)
    disagreements: list[GatewayStructureDisagreement] = Field(default_factory=list)
    validation: GatewayStructureValidation | None = None
    model: str
    ref: str = Field(alias="prompt_id")


def _authoritative_scan(value: GatewayStructureScan) -> StructureScan:
    return StructureScan.model_validate(value.model_dump(mode="json", by_alias=True))


def _authoritative_proposal(value: GatewayStructureRecoveryProposal) -> StructureRecoveryProposal:
    return StructureRecoveryProposal.model_validate(value.model_dump(mode="json", by_alias=True))


class RecoveryBudgetExceeded(ValidationError):
    """A configured structure input, output, window, or call budget was exceeded."""


class StructureValidationFailure(ValidationError):
    """A model proposal failed exact source coverage or hierarchy validation."""


class StructureRecoveryConfig(BaseModel):
    """Explicit structure routing and bounded recovery settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: StructureMode = "auto"
    document_type: str = "process"
    thresholds: RecoveryThresholds = Field(default_factory=RecoveryThresholds)
    max_window_chars: int = Field(default=100_000, ge=256, le=120_000)
    overlap_blocks: int = Field(default=1, ge=0, le=32)
    max_windows: int = Field(default=64, ge=1, le=512)
    max_model_calls: int = Field(default=65, ge=1, le=1024)
    max_total_input_chars: int = Field(default=2_000_000, ge=1, le=20_000_000)
    max_total_output_tokens: int = Field(default=400_000, ge=1, le=2_000_000)
    max_triage_chars: int = Field(default=120_000, ge=256, le=120_000)
    max_reconciliation_chars: int = Field(default=120_000, ge=256, le=120_000)
    allow_reconciliation: bool = True


class RecoveryWindow(BaseModel):
    """Stable block-boundary window metadata; raw text is reconstructed from raw blocks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_id: str
    start_ordinal: int = Field(ge=0)
    end_ordinal: int = Field(ge=0)
    span_ids: tuple[str, ...]
    input_digest: str
    character_count: int = Field(ge=0)


class StructureValidationReport(BaseModel):
    """Detailed promotion gate evidence, including preserved ambiguity/disagreement IDs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    scope: Literal["parser", "window", "full"]
    expected_span_ids: tuple[str, ...] = ()
    covered_span_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    uncertain_span_ids: tuple[str, ...] = ()
    ambiguity_count: int = Field(default=0, ge=0)
    disagreement_count: int = Field(default=0, ge=0)


class StructureArtifactMetadata(BaseModel):
    """Safe, independently digestible metadata for a structure-recovery run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_digest: str
    document_id: str
    mode: StructureMode
    parser_outline_digest: str
    quality_digest: str
    scan_digest: str | None = None
    windows_digest: str | None = None
    proposal_digest: str | None = None
    reconciliation_digest: str | None = None
    validation_digest: str
    selected_view_digest: str
    cache_keys: dict[str, str] = Field(default_factory=dict)
    call_manifests: tuple[CallManifest, ...] = ()
    prompt_resolutions: tuple[PromptResolution, ...] = ()
    warnings: tuple[str, ...] = ()
    status: Literal["parser", "recovered", "failed", "deferred"]


class StructureRecoveryResult(BaseModel):
    """Return value of :class:`StructureRecoveryService`."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    raw: RawDocument
    normalized: NormalizedDocument
    authoritative_raw: DomainRawDocument
    selected_view: SelectedStructuralView
    authoritative_view: StructuralView
    scan: StructureScan | None = None
    windows: tuple[RecoveryWindow, ...] = ()
    window_proposals: tuple[StructureRecoveryProposal, ...] = ()
    recovered_proposal: StructureRecoveryProposal | None = None
    reconciliation: StructureRecoveryProposal | None = None
    validation: StructureValidationReport
    metadata: StructureArtifactMetadata | None = None
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class DomainRawMapping:
    """Mapping between exact parser spans and authoritative domain spans."""

    local: RawDocument
    domain: DomainRawDocument
    local_to_domain: dict[str, str]
    domain_to_local: dict[str, str]


def _digest_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value))


def _domain_location(location: Any) -> DomainSourceLocation:
    return DomainSourceLocation(
        line_start=location.line_start,
        line_end=location.line_end,
        char_start=location.char_start,
        char_end=location.char_end,
        page=location.page,
        paragraph_index=location.paragraph_index,
        table_index=location.table_index,
        row_index=location.row,
        column_index=location.column,
        xml_path=location.xml_path,
    )


def _source_block_type(value: str) -> SourceBlockType:
    aliases = {
        "page_text": SourceBlockType.PARAGRAPH,
        "body": SourceBlockType.PARAGRAPH,
        "caption": SourceBlockType.PARAGRAPH,
        "embedded_file": SourceBlockType.UNKNOWN,
    }
    return aliases.get(
        value,
        SourceBlockType(value)
        if value in SourceBlockType._value2member_map_
        else SourceBlockType.UNKNOWN,
    )


def _domain_span(block: SourceBlock) -> str:
    if block.span_id is None:
        raise StructureValidationFailure("authoritative source block is missing its span ID")
    return block.span_id


def adapt_raw_document(raw: RawDocument) -> DomainRawMapping:
    """Adapt local parser blocks without changing their exact text or locations."""

    if not raw.blocks:
        raise StructureValidationFailure("cannot recover a document with no parser blocks")
    document_id = f"DOC-{raw.source_digest[:24].upper()}"
    domain_blocks: list[SourceBlock] = []
    local_to_domain: dict[str, str] = {}
    domain_to_local: dict[str, str] = {}
    for block in raw.blocks:
        domain_block = SourceBlock(
            ordinal=block.ordinal,
            block_type=_source_block_type(block.block_type),
            text=block.text,
            source_digest=raw.source_digest,
            location=_domain_location(block.location),
            heading_level=block.level,
            metadata={
                "local_span_id": block.span_id,
                "local_block_type": block.block_type,
            },
        )
        domain_span_id = _domain_span(domain_block)
        domain_blocks.append(domain_block)
        local_to_domain[block.span_id] = domain_span_id
        domain_to_local[domain_span_id] = block.span_id
    domain = DomainRawDocument(
        document_id=document_id,
        source_digest=raw.source_digest,
        media_type=raw.media_type,
        source_path=str(raw.source_path),
        size_bytes=raw.size_bytes,
        blocks=domain_blocks,
        extraction_warnings=[warning.code for warning in raw.warnings],
        parser_name=raw.parser_name,
        parser_version=raw.parser_version,
    )
    return DomainRawMapping(raw, domain, local_to_domain, domain_to_local)


def _render_blocks(
    blocks: Sequence[SourceBlock], *, max_chars: int, include_text: bool = True
) -> str:
    parts: list[str] = []
    total = 0
    for block in blocks:
        text = block.text if include_text else ""
        part = (
            f"[SPAN id={_domain_span(block)} ordinal={block.ordinal} type={block.block_type.value} "
            f"text_digest={block.text_digest}]\n{text}\n[/SPAN]"
        )
        total += len(part)
        if total > max_chars:
            raise RecoveryBudgetExceeded(
                f"structure input exceeds the configured character budget ({max_chars})"
            )
        parts.append(part)
    return "\n".join(parts)


def build_recovery_windows(
    raw: DomainRawDocument, config: StructureRecoveryConfig | None = None
) -> tuple[RecoveryWindow, ...]:
    """Partition ordered raw blocks into deterministic, overlapping windows."""

    config = config or StructureRecoveryConfig()
    blocks = raw.blocks
    windows: list[RecoveryWindow] = []
    start = 0
    while start < len(blocks):
        end = start
        chars = 0
        while end < len(blocks):
            candidate = _render_blocks(blocks[end : end + 1], max_chars=config.max_window_chars)
            separator = 1 if end > start else 0
            if end > start and chars + separator + len(candidate) > config.max_window_chars:
                break
            if end == start and len(candidate) > config.max_window_chars:
                raise RecoveryBudgetExceeded(
                    f"raw block {_domain_span(blocks[end])} exceeds the configured window budget"
                )
            chars += separator + len(candidate)
            end += 1
        if end <= start:
            raise RecoveryBudgetExceeded("unable to make forward progress while windowing")
        selected = blocks[start:end]
        chars = len(_render_blocks(selected, max_chars=config.max_window_chars))
        span_ids = tuple(_domain_span(block) for block in selected)
        input_digest = _digest_json(
            {
                "source_digest": raw.source_digest,
                "start": start,
                "end": end,
                "blocks": [
                    {
                        "span_id": _domain_span(block),
                        "ordinal": block.ordinal,
                        "text_digest": block.text_digest,
                    }
                    for block in selected
                ],
            }
        )
        window_id = (
            f"WIN-{_digest_json({'source': raw.source_digest, 'spans': span_ids})[:20].upper()}"
        )
        windows.append(
            RecoveryWindow(
                window_id=window_id,
                start_ordinal=selected[0].ordinal,
                end_ordinal=selected[-1].ordinal,
                span_ids=span_ids,
                input_digest=input_digest,
                character_count=chars,
            )
        )
        if end == len(blocks):
            break
        next_start = max(start + 1, end - config.overlap_blocks)
        start = next_start
        if len(windows) > config.max_windows:
            raise RecoveryBudgetExceeded("document requires more windows than configured")
    return tuple(windows)


def _outline_digest(outline: ParserOutline) -> str:
    return _digest_json(outline.model_dump(mode="json"))


def _quality_digest(quality: StructureQualityReport) -> str:
    return _digest_json(quality.model_dump(mode="json"))


def _safe_metadata(
    raw: RawDocument, mapping: DomainRawMapping, outline_digest: str
) -> dict[str, object]:
    return {
        "document_id": mapping.domain.document_id,
        "source_digest": raw.source_digest,
        "media_type": raw.media_type,
        "parser_name": raw.parser_name,
        "parser_version": raw.parser_version,
        "block_count": len(raw.blocks),
        "parser_outline_digest": outline_digest,
        "warning_codes": [warning.code for warning in raw.warnings],
    }


def _proposal_digest(proposal: StructureRecoveryProposal | None) -> str | None:
    return None if proposal is None else _digest_json(proposal.model_dump(mode="json"))


def _stable_model_payload(value: BaseModel | None, *, exclude: set[str] | None = None) -> object:
    if value is None:
        return None
    return value.model_dump(mode="json", exclude=exclude or set())


def _route_schema_dependency(route_id: str, schema: type[BaseModel]) -> dict[str, object]:
    route = resolve_route(route_id)
    return {
        "route_id": route.route_id,
        "model": route.model,
        "parameters": route.parameters(),
        "schema_name": schema.__name__,
        "schema_digest": _digest_json(schema.model_json_schema()),
    }


def _config_subset(config: StructureRecoveryConfig, fields: Sequence[str]) -> dict[str, object]:
    dumped = config.model_dump(mode="json")
    return {field: dumped[field] for field in fields}


def _structure_cache_keys(
    *,
    raw: RawDocument,
    config: StructureRecoveryConfig,
    outline_digest: str,
    quality_digest: str,
    scan: StructureScan | None,
    windows: Sequence[RecoveryWindow],
    recovered: StructureRecoveryProposal | None,
    reconciliation: StructureRecoveryProposal | None,
    validation: StructureValidationReport,
    prompt_dependencies: Mapping[str, Sequence[Mapping[str, object]]],
    call_manifests: Sequence[CallManifest],
    prompt_resolutions: Sequence[PromptResolution],
) -> dict[str, str]:
    """Build complete, stable stage keys without including source or prompt text."""

    downstream_common = {
        "source_digest": raw.source_digest,
        "parser_outline_digest": outline_digest,
        "quality_digest": quality_digest,
    }
    triage_inputs = {
        "source_digest": raw.source_digest,
        "parser_outline_digest": outline_digest,
        "document_metadata": {
            "media_type": raw.media_type,
            "parser_name": raw.parser_name,
            "parser_version": raw.parser_version,
            "block_count": len(raw.blocks),
            "warning_codes": [warning.code for warning in raw.warnings],
        },
        "configuration": _config_subset(config, ("document_type", "max_triage_chars")),
    }
    recovery_config = _config_subset(
        config,
        (
            "mode",
            "document_type",
            "thresholds",
            "max_window_chars",
            "overlap_blocks",
            "max_windows",
            "max_model_calls",
            "max_total_input_chars",
            "max_total_output_tokens",
        ),
    )
    reconciliation_config = {
        **recovery_config,
        **_config_subset(config, ("max_reconciliation_chars", "allow_reconciliation")),
    }
    selected_config = _config_subset(config, ("mode", "document_type", "thresholds"))
    scan_payload = _stable_model_payload(scan, exclude={"created_at"})
    window_payload = [window.model_dump(mode="json") for window in windows]
    recovery_payload = _stable_model_payload(recovered)
    reconciliation_payload = _stable_model_payload(reconciliation)
    validation_payload = validation.model_dump(mode="json")
    scan_key = _digest_json(
        {
            "stage": "structure_scan",
            **triage_inputs,
            "prompt_dependencies": list(prompt_dependencies.get("structure_scan", ())),
            "route_schema": _route_schema_dependency(ROUTE_FLASH_LITE, GatewayStructureScan),
        }
    )
    recovery_key = _digest_json(
        {
            "stage": "structure_recovery",
            **downstream_common,
            "configuration": recovery_config,
            "upstream_scan_key": scan_key,
            "scan": scan_payload,
            "windows": window_payload,
            "prompt_dependencies": list(prompt_dependencies.get("structure_recovery", ())),
            "route_schema": _route_schema_dependency(
                ROUTE_FLASH_LITE, GatewayStructureRecoveryProposal
            ),
        }
    )
    reconciliation_key = _digest_json(
        {
            "stage": "structure_reconciliation",
            **downstream_common,
            "configuration": reconciliation_config,
            "upstream_recovery_key": recovery_key,
            "recovered": recovery_payload,
            "conflicts": [
                disagreement.model_dump(mode="json")
                for disagreement in (recovered.disagreements if recovered else [])
            ],
            "prompt_dependencies": list(prompt_dependencies.get("structure_reconciliation", ())),
            "route_schema": _route_schema_dependency(
                ROUTE_FLASH_LITE, GatewayStructureRecoveryProposal
            ),
        }
    )
    metadata_key = _digest_json(
        {
            "stage": "structure_metadata",
            "source_digest": raw.source_digest,
            "upstream_stage_keys": {
                "structure_scan": scan_key,
                "structure_recovery": recovery_key,
                "structure_reconciliation": reconciliation_key,
            },
            "call_manifests": [
                manifest.model_dump(
                    mode="json",
                    exclude={
                        "call_id",
                        "duration_ms",
                        "attempts",
                        "retries",
                        "structured_repairs",
                        "usage",
                        "response_digest",
                        "error_message",
                    },
                )
                for manifest in call_manifests
            ],
            "prompt_resolutions": [
                resolution.model_dump(mode="json", exclude={"resolved_at"})
                for resolution in prompt_resolutions
            ],
        }
    )
    return {
        "structure_scan": scan_key,
        "structure_recovery": recovery_key,
        "selected_view": _digest_json(
            {
                "stage": "selected_view",
                **downstream_common,
                "configuration": selected_config,
                "upstream_stage_keys": {
                    "structure_scan": scan_key,
                    "structure_recovery": recovery_key,
                    "structure_reconciliation": reconciliation_key,
                },
                "scan": scan_payload,
                "windows": window_payload,
                "recovered": recovery_payload,
                "reconciliation": reconciliation_payload,
                "validation": validation_payload,
                "route_schema": {
                    "recovery": _route_schema_dependency(
                        ROUTE_FLASH_LITE, GatewayStructureRecoveryProposal
                    ),
                    "reconciliation": _route_schema_dependency(
                        ROUTE_FLASH_LITE, GatewayStructureRecoveryProposal
                    ),
                },
            }
        ),
        "structure_reconciliation": reconciliation_key,
        "structure_metadata": metadata_key,
    }


def _section_interval(section: Any, ordinal_by_span: Mapping[str, int]) -> tuple[int, int] | None:
    start = ordinal_by_span.get(section.start_span_id)
    end = ordinal_by_span.get(section.end_span_id)
    if start is None or end is None:
        return None
    return start, end


def _validate_section_collection(
    sections: Sequence[RecoveredSection],
    raw: DomainRawDocument,
    ordinal_by_span: Mapping[str, int],
    expected_ordinals: Sequence[int],
    *,
    label: str,
) -> tuple[list[str], list[tuple[int, int, int, str]], dict[str, RecoveredSection]]:
    errors: list[str] = []
    intervals: list[tuple[int, int, int, str]] = []
    by_id: dict[str, RecoveredSection] = {}
    section_ids = [section.section_id for section in sections]
    if len(section_ids) != len(set(section_ids)):
        errors.append(f"duplicate section IDs in {label}")
    for section in sections:
        by_id.setdefault(section.section_id, section)
        interval = _section_interval(section, ordinal_by_span)
        if interval is None:
            errors.append(
                f"{label} section {section.section_id} references an unknown boundary span"
            )
            continue
        start, end = interval
        if start > end:
            errors.append(f"{label} section {section.section_id} has reversed boundaries")
            continue
        if expected_ordinals and start < expected_ordinals[0]:
            errors.append(
                f"{label} section {section.section_id} begins outside the requested window"
            )
        if expected_ordinals and end > expected_ordinals[-1]:
            errors.append(f"{label} section {section.section_id} ends outside the requested window")
        heading = next(
            (block for block in raw.blocks if block.span_id == section.start_span_id), None
        )
        if section.source_heading_text is not None and heading is not None:
            allowed = {heading.text, heading.text.lstrip("# ").strip()}
            if section.source_heading_text not in allowed:
                errors.append(
                    f"source heading text mutation at {label} section {section.section_id}"
                )
        intervals.append((start, end, section.level, section.section_id))

    for left_index, left in enumerate(intervals):
        for right in intervals[left_index + 1 :]:
            left_start, left_end, left_level, left_id = left
            right_start, right_end, right_level, right_id = right
            crossing = (left_start < right_start <= left_end < right_end) or (
                right_start < left_start <= right_end < left_end
            )
            if crossing:
                errors.append(f"illegal crossing {label} boundaries: {left_id}/{right_id}")
            if left_start == right_start and left_end == right_end and left_level != right_level:
                errors.append(
                    f"duplicate section interval with conflicting levels: {left_id}/{right_id}"
                )

    stack: list[tuple[int, int, str]] = []
    for start, end, level, section_id in sorted(intervals, key=lambda item: (item[0], -item[1])):
        while stack and start > stack[-1][0]:
            stack.pop()
        if stack:
            parent_end, parent_level, parent_id = stack[-1]
            if level <= parent_level:
                errors.append(f"invalid section nesting level: {parent_id} contains {section_id}")
            elif level > parent_level + 1:
                errors.append(f"invalid section hierarchy level jump: {parent_id} to {section_id}")
        stack.append((end, level, section_id))
    return errors, intervals, by_id


def validate_recovery_proposal(
    proposal: StructureRecoveryProposal,
    raw: DomainRawDocument,
    *,
    expected_span_ids: Sequence[str] | None = None,
    scope: Literal["window", "full"] = "full",
) -> StructureValidationReport:
    """Validate exact once-only coverage, source digests, offsets-as-spans, and nesting."""

    expected = tuple(expected_span_ids or (_domain_span(block) for block in raw.blocks))
    expected_set = set(expected)
    by_id = {_domain_span(block): block for block in raw.blocks}
    ordinal_by_span = {_domain_span(block): block.ordinal for block in raw.blocks}
    expected_ordinals = tuple(
        ordinal_by_span[span_id] for span_id in expected if span_id in ordinal_by_span
    )
    errors: list[str] = []
    actual = tuple(item.span_id for item in proposal.dispositions)
    if proposal.document_id != raw.document_id:
        errors.append("proposal document_id does not match the authoritative raw document")
    if proposal.source_digest != raw.source_digest:
        errors.append("proposal source_digest does not match the authoritative raw document")
    if len(actual) != len(set(actual)):
        errors.append("duplicate span IDs in dispositions")
    unknown = sorted(set(actual) - set(by_id))
    if unknown:
        errors.append(f"nonexistent span IDs in dispositions: {unknown}")
    if actual != expected:
        missing = sorted(expected_set - set(actual))
        extra = sorted(set(actual) - expected_set)
        errors.append(f"coverage/order mismatch; missing={missing}; extra={extra}")
    if any(actual[index] not in expected_set for index in range(len(actual))):
        errors.append("dispositions contain a span outside the requested window")
    for item in proposal.dispositions:
        block = by_id.get(item.span_id)
        if block is not None and item.source_text_digest != block.text_digest:
            errors.append(f"source text digest mismatch for {item.span_id}")
    validation_raw = raw.model_copy(
        update={"blocks": [by_id[span_id] for span_id in expected if span_id in by_id]}
    )
    authoritative_validation = proposal.model_copy(deep=True).validate_against(validation_raw)
    errors.extend(authoritative_validation.errors)
    section_errors, _, section_by_id = _validate_section_collection(
        proposal.sections,
        raw,
        ordinal_by_span,
        expected_ordinals,
        label="proposal",
    )
    errors.extend(section_errors)
    known_sections = set(section_by_id)
    for item in proposal.dispositions:
        if item.section_id is not None and item.section_id not in known_sections:
            errors.append(
                f"disposition {item.span_id} references unknown section {item.section_id}"
            )
        elif item.section_id is not None:
            interval = _section_interval(section_by_id[item.section_id], ordinal_by_span)
            ordinal = ordinal_by_span.get(item.span_id)
            if interval is None or ordinal is None or not interval[0] <= ordinal <= interval[1]:
                errors.append(f"disposition {item.span_id} lies outside section {item.section_id}")
        for segment in item.segments or ():
            if segment.section_id is not None and segment.section_id not in known_sections:
                errors.append(
                    f"segment {segment.segment_id} references unknown section {segment.section_id}"
                )
            elif segment.section_id is not None:
                interval = _section_interval(section_by_id[segment.section_id], ordinal_by_span)
                ordinal = ordinal_by_span.get(item.span_id)
                if interval is None or ordinal is None or not interval[0] <= ordinal <= interval[1]:
                    errors.append(
                        f"segment {segment.segment_id} for {item.span_id} lies outside section "
                        f"{segment.section_id}"
                    )
    for association in proposal.associations:
        if association.span_id not in expected_set:
            errors.append(
                f"association references a span outside the requested window: {association.span_id}"
            )
        if association.section_id not in known_sections:
            errors.append(f"association references unknown section {association.section_id}")
        else:
            interval = _section_interval(section_by_id[association.section_id], ordinal_by_span)
            ordinal = ordinal_by_span.get(association.span_id)
            if interval is None or ordinal is None or not interval[0] <= ordinal <= interval[1]:
                errors.append(
                    f"association {association.span_id} lies outside section {association.section_id}"
                )
    for disagreement in proposal.disagreements:
        if any(span_id not in expected_set for span_id in disagreement.span_ids):
            errors.append("disagreement references a span outside the requested window")
    alternative_ids: set[str] = set()
    for alternative in proposal.boundary_alternatives:
        if alternative.alternative_id in alternative_ids:
            errors.append(f"duplicate boundary alternative ID: {alternative.alternative_id}")
        alternative_ids.add(alternative.alternative_id)
        alternative_errors, _, _ = _validate_section_collection(
            alternative.sections,
            raw,
            ordinal_by_span,
            expected_ordinals,
            label=f"alternative {alternative.alternative_id}",
        )
        errors.extend(alternative_errors)
    uncertain = tuple(
        item.span_id for item in proposal.dispositions if _disposition_is_uncertain(item)
    )
    return StructureValidationReport(
        passed=not errors,
        scope=scope,
        expected_span_ids=expected,
        covered_span_ids=actual,
        errors=tuple(dict.fromkeys(errors)),
        uncertain_span_ids=uncertain,
        ambiguity_count=len(proposal.boundary_alternatives),
        disagreement_count=len(proposal.disagreements),
    )


def _parser_authoritative_view(
    raw: DomainRawDocument, outline: ParserOutline, mapping: DomainRawMapping
) -> StructuralView:
    sections: list[StructuralSection] = []
    for section in outline.sections:
        start = mapping.local_to_domain.get(section.start_span_id)
        end = mapping.local_to_domain.get(section.end_span_id)
        if start is None or end is None:
            continue
        section_id = f"SEC-{_digest_json({'source': raw.source_digest, 'id': section.section_id})[:18].upper()}"
        sections.append(
            StructuralSection(
                section_id=section_id,
                title=section.title or "Untitled section",
                level=min(section.level, 9),
                start_span_id=start,
                end_span_id=end,
                source_heading=section.title,
                confidence=outline.confidence,
                inferred=section.inferred,
            )
        )
    return StructuralView(
        origin="parser",
        sections=sections,
        confidence=outline.confidence,
        validation_passed=True,
    )


def _recovered_authoritative_view(
    proposal: StructureRecoveryProposal, validation: StructureValidationReport
) -> StructuralView:
    sections = [
        StructuralSection(
            section_id=section.section_id,
            title=section.label,
            level=section.level,
            start_span_id=section.start_span_id,
            end_span_id=section.end_span_id,
            source_heading=section.source_heading_text,
            confidence=section.confidence,
            inferred=section.inferred_label,
        )
        for section in proposal.sections
    ]
    return StructuralView(
        origin="llm_recovered",
        sections=sections,
        confidence=proposal.confidence,
        validation_passed=validation.passed,
        validation_errors=list(validation.errors),
    )


def _recovered_local_view(
    raw: RawDocument,
    parser_outline: ParserOutline,
    proposal: StructureRecoveryProposal,
    mapping: DomainRawMapping,
) -> SelectedStructuralView:
    disposition_by_domain = {item.span_id: item for item in proposal.dispositions}
    local_by_span = {block.span_id: block for block in raw.blocks}
    sections: list[OutlineSection] = []
    for section in proposal.sections:
        start = mapping.domain_to_local.get(section.start_span_id)
        end = mapping.domain_to_local.get(section.end_span_id)
        if start is None or end is None:
            continue
        start_ordinal = local_by_span[start].ordinal
        end_ordinal = local_by_span[end].ordinal
        block_ids = tuple(
            block.span_id for block in raw.blocks if start_ordinal <= block.ordinal <= end_ordinal
        )
        sections.append(
            OutlineSection(
                section_id=section.section_id,
                title=section.label,
                level=min(section.level, 6),
                start_span_id=start,
                end_span_id=end,
                heading_span_id=start if section.source_heading_text else None,
                inferred=section.inferred_label,
                source_block_ids=block_ids,
            )
        )
    recovered_outline = ParserOutline(
        sections=tuple(sections),
        title=proposal.proposed_title or parser_outline.title,
        confidence=proposal.confidence,
        warnings=parser_outline.warnings,
    )
    blocks: list[StructuralBlockDisposition] = []
    for block in raw.blocks:
        domain_id = mapping.local_to_domain[block.span_id]
        item = disposition_by_domain[domain_id]
        segments = (
            tuple(
                StructuralBlockSegment.model_validate(segment.model_dump(mode="json"))
                for segment in item.segments
            )
            if item.segments is not None
            else None
        )
        blocks.append(
            StructuralBlockDisposition(
                source_span_id=block.span_id,
                ordinal=block.ordinal,
                disposition=(
                    StructureDisposition.UNCERTAIN.value
                    if _disposition_is_uncertain(item)
                    else item.disposition.value
                ),
                section_id=item.section_id,
                confidence=item.confidence,
                source_text_digest=block.content_digest,
                segments=segments,
            )
        )
    return SelectedStructuralView(
        origin="llm_recovered",
        source_digest=raw.source_digest,
        outline=recovered_outline,
        blocks=tuple(blocks),
        validation_passed=True,
        warnings=tuple(
            warning
            for warning in (
                "low_confidence_selection"
                if any(_disposition_is_uncertain(item) for item in proposal.dispositions)
                else "",
                "ambiguity_retained" if proposal.boundary_alternatives else "",
                "parser_model_disagreement_retained" if proposal.disagreements else "",
            )
            if warning
        ),
    )


def _material_disagreement(
    scan: StructureScan,
    quality: StructureQualityReport,
    parser_outline: ParserOutline,
    mapping: DomainRawMapping,
) -> bool:
    if quality.warnings and scan.confidence < 0.85:
        return True
    parser_boundaries = {
        (
            mapping.local_to_domain.get(section.start_span_id),
            mapping.local_to_domain.get(section.end_span_id),
        )
        for section in parser_outline.sections
    }
    scan_boundaries = {
        (region.start_span_id, region.end_span_id) for region in scan.boundary_regions
    }
    return bool(scan_boundaries and scan_boundaries != parser_boundaries)


def _disposition_is_uncertain(item: BlockDisposition) -> bool:
    return bool(
        item.disposition is StructureDisposition.UNCERTAIN
        or item.confidence < 0.5
        or any(
            segment.disposition is StructureDisposition.UNCERTAIN or segment.confidence < 0.5
            for segment in item.segments or ()
        )
    )


def _segment_structure_key(item: BlockDisposition) -> bytes:
    return canonical_json(
        [
            {
                "segment_id": segment.segment_id,
                "char_start": segment.char_start,
                "char_end": segment.char_end,
                "offset_unit": segment.offset_unit,
                "disposition": segment.disposition.value,
                "section_id": segment.section_id,
                "slice_sha256": segment.slice_sha256,
            }
            for segment in item.segments or ()
        ]
    )


def _conflict_key(item: BlockDisposition) -> tuple[str, str | None, str, bytes]:
    return (
        item.disposition.value,
        item.section_id,
        item.source_text_digest,
        _segment_structure_key(item),
    )


def _merge_structurally_identical_dispositions(
    candidates: Sequence[BlockDisposition],
) -> BlockDisposition:
    """Merge identical structure while retaining the most conservative confidence."""

    if not candidates:
        raise StructureValidationFailure("cannot merge an empty disposition candidate set")
    first = candidates[0]
    if any(_conflict_key(candidate) != _conflict_key(first) for candidate in candidates[1:]):
        raise StructureValidationFailure("cannot merge structurally different dispositions")
    segments = None
    if first.segments is not None:
        segments = [
            segment.model_copy(
                update={
                    "confidence": min(
                        candidate.segments[index].confidence
                        for candidate in candidates
                        if candidate.segments is not None
                    )
                }
            )
            for index, segment in enumerate(first.segments)
        ]
    return first.model_copy(
        update={
            "confidence": min(candidate.confidence for candidate in candidates),
            "segments": segments,
        }
    )


def _dedupe_disagreements(
    disagreements: Sequence[StructureDisagreement],
) -> list[StructureDisagreement]:
    retained: list[StructureDisagreement] = []
    seen: set[bytes] = set()
    for disagreement in disagreements:
        key = canonical_json(disagreement.model_dump(mode="json"))
        if key not in seen:
            seen.add(key)
            retained.append(disagreement)
    return retained


def _alternative_content_key(alternative: Any) -> bytes:
    payload = alternative.model_dump(mode="json")
    payload["alternative_id"] = ""
    return canonical_json(payload)


def merge_window_proposals(
    proposals: Sequence[StructureRecoveryProposal],
    raw: DomainRawDocument,
    *,
    conflicts: Sequence[str] = (),
) -> StructureRecoveryProposal:
    """Merge overlapping windows by exact span identity, retaining conflicts as uncertainty."""

    if not proposals:
        raise StructureValidationFailure("no window proposals were available to merge")
    by_span: dict[str, list[BlockDisposition]] = defaultdict(list)
    for proposal in proposals:
        for item in proposal.dispositions:
            by_span[item.span_id].append(item)
    merged_dispositions: list[BlockDisposition] = []
    disagreements: list[StructureDisagreement] = []
    for span_id in (_domain_span(block) for block in raw.blocks):
        candidates = by_span.get(span_id, [])
        if not candidates:
            raise StructureValidationFailure(f"window merge omitted span {span_id}")
        first = candidates[0]
        conflicting = [
            candidate
            for candidate in candidates[1:]
            if _conflict_key(candidate) != _conflict_key(first)
        ]
        if conflicting:
            segment_conflict = any(
                _segment_structure_key(candidate) != _segment_structure_key(first)
                for candidate in conflicting
            )
            merged_dispositions.append(
                first.model_copy(
                    update={
                        "disposition": StructureDisposition.UNCERTAIN,
                        "confidence": min(candidate.confidence for candidate in candidates),
                        "section_id": first.section_id,
                        "segments": None if segment_conflict else first.segments,
                    }
                )
            )
            disagreements.append(
                StructureDisagreement(
                    span_ids=[span_id],
                    parser_label=None,
                    model_label=(
                        "overlapping_window_segment_conflict"
                        if segment_conflict
                        else "overlapping_window_conflict"
                    ),
                    resolution=None,
                    requires_review=True,
                )
            )
        else:
            merged_dispositions.append(_merge_structurally_identical_dispositions(candidates))
    section_by_id: dict[str, Any] = {}
    alternatives: dict[str, Any] = {}
    associations: dict[tuple[str, str, str], StructureAssociation] = {}
    for proposal in proposals:
        for section in proposal.sections:
            prior = section_by_id.get(section.section_id)
            if prior is None:
                section_by_id[section.section_id] = section
            elif (
                prior.start_span_id,
                prior.end_span_id,
                prior.level,
                prior.label,
            ) != (
                section.start_span_id,
                section.end_span_id,
                section.level,
                section.label,
            ):
                boundary_span_ids = list(
                    dict.fromkeys(
                        [
                            prior.start_span_id,
                            prior.end_span_id,
                            section.start_span_id,
                            section.end_span_id,
                        ]
                    )
                )
                disagreements.append(
                    StructureDisagreement(
                        span_ids=boundary_span_ids,
                        parser_label=prior.label,
                        model_label="overlapping_window_section_boundary_conflict",
                        resolution=None,
                        requires_review=True,
                    )
                )
        for alternative in proposal.boundary_alternatives:
            if any(
                _alternative_content_key(existing) == _alternative_content_key(alternative)
                for existing in alternatives.values()
            ):
                continue
            prior = alternatives.get(alternative.alternative_id)
            if prior is None:
                alternatives[alternative.alternative_id] = alternative
            elif canonical_json(prior.model_dump(mode="json")) != canonical_json(
                alternative.model_dump(mode="json")
            ):
                base_alternative_id = (
                    f"{alternative.alternative_id}-ALT-"
                    f"{_digest_json(alternative.model_dump(mode='json'))[:12].upper()}"
                )
                alternative_id = base_alternative_id
                suffix = 2
                while alternative_id in alternatives:
                    alternative_id = f"{base_alternative_id}-{suffix}"
                    suffix += 1
                alternatives[alternative_id] = alternative.model_copy(
                    update={"alternative_id": alternative_id}
                )
                disagreements.append(
                    StructureDisagreement(
                        span_ids=list(
                            dict.fromkeys(
                                section.start_span_id
                                for section in (
                                    *prior.sections,
                                    *alternative.sections,
                                )
                            )
                        ),
                        parser_label=prior.alternative_id,
                        model_label="overlapping_window_alternative_conflict",
                        resolution=None,
                        requires_review=True,
                    )
                )
        for association in proposal.associations:
            associations[(association.span_id, association.section_id, association.association)] = (
                association
            )
        disagreements.extend(proposal.disagreements)
    recovery_id = f"REC-{_digest_json({'source': raw.source_digest, 'spans': [item.span_id for item in merged_dispositions]})[:20].upper()}"
    return StructureRecoveryProposal(
        recovery_id=recovery_id,
        document_id=raw.document_id,
        source_digest=raw.source_digest,
        proposed_document_type=proposals[0].proposed_document_type,
        proposed_title=proposals[0].proposed_title,
        confidence=min(proposal.confidence for proposal in proposals),
        sections=list(section_by_id.values()),
        dispositions=merged_dispositions,
        associations=list(associations.values()),
        boundary_alternatives=list(alternatives.values()),
        disagreements=_dedupe_disagreements(disagreements),
        model=proposals[0].model,
        prompt_id=proposals[0].prompt_id,
    )


class StructureRecoveryService:
    """High-level deterministic structure scan/recovery facade for WT5/WT6."""

    def __init__(
        self,
        *,
        config: StructureRecoveryConfig | None = None,
        gateway: GeminiModelGateway | None = None,
        prompt_composer: PromptComposerLike | None = None,
    ) -> None:
        self.config = config or StructureRecoveryConfig()
        self.gateway = gateway
        self.prompt_composer = prompt_composer
        self._calls: list[CallManifest] = []
        self._resolutions: list[PromptResolution] = []
        self._prompt_dependencies: list[dict[str, object]] = []
        self._input_chars = 0
        self._output_tokens = 0

    def run(
        self,
        document: RawDocument | NormalizedDocument,
        *,
        repository: Any | None = None,
        run_id: str | None = None,
    ) -> StructureRecoveryResult:
        self._calls = []
        self._resolutions = []
        self._prompt_dependencies = []
        self._input_chars = 0
        self._output_tokens = 0
        normalized = (
            document
            if isinstance(document, NormalizedDocument)
            else normalize_document(document, thresholds=self.config.thresholds)
        )
        raw = normalized.raw
        mapping = adapt_raw_document(raw)
        outline = normalized.parser_outline
        outline_digest = _outline_digest(outline)
        parser_view = normalized.selected_view or build_parser_view(raw, outline)
        parser_authoritative = _parser_authoritative_view(mapping.domain, outline, mapping)
        warnings: list[str] = list(normalized.quality.warnings)
        scan: StructureScan | None = None
        windows: tuple[RecoveryWindow, ...] = ()
        window_proposals: list[StructureRecoveryProposal] = []
        recovered: StructureRecoveryProposal | None = None
        reconciliation: StructureRecoveryProposal | None = None
        promoted_recovery = False
        conflicts: list[str] = []
        validation = StructureValidationReport(
            passed=parser_view.validation_passed,
            scope="parser",
            expected_span_ids=tuple(_domain_span(block) for block in mapping.domain.blocks),
            covered_span_ids=tuple(mapping.local_to_domain[block.span_id] for block in raw.blocks),
            errors=()
            if parser_view.validation_passed
            else ("parser selected view coverage failed",),
        )
        mode = self.config.mode
        should_recover = mode in {"recover", "force"}
        if mode == "auto":
            try:
                scan = self._triage(raw, mapping, outline_digest)
                should_recover = bool(
                    normalized.routing.mode == "llm_recovery"
                    or scan.decision is not StructureDecision.ACCEPT_PARSER
                    or _material_disagreement(scan, normalized.quality, outline, mapping)
                )
                if not should_recover:
                    warnings.append("triage_accept_parser")
            except Exception as exc:
                warnings.append(f"structure_scan_failed:{type(exc).__name__}")
                should_recover = normalized.routing.mode == "llm_recovery"
        elif mode == "off":
            warnings.append("structure_recovery_disabled")
        elif mode == "parser":
            warnings.append("parser_mode_selected_without_model_calls")
        elif mode == "force":
            warnings.append("force_mode_skipped_triage")
        if should_recover:
            if self.gateway is None or self.prompt_composer is None:
                warnings.append("recovery_dependencies_unavailable")
            else:
                try:
                    windows = build_recovery_windows(mapping.domain, self.config)
                    for window in windows:
                        self._budget_check(window.character_count)
                        source_blocks = [
                            block
                            for block in mapping.domain.blocks
                            if _domain_span(block) in set(window.span_ids)
                        ]
                        proposal = self._recover_window(
                            raw,
                            mapping,
                            outline_digest,
                            window,
                            source_blocks,
                        )
                        expected = window.span_ids
                        report = validate_recovery_proposal(
                            proposal,
                            mapping.domain,
                            expected_span_ids=expected,
                            scope="window",
                        )
                        if not report.passed:
                            warnings.append(f"window_validation_failed:{window.window_id}")
                            continue
                        window_proposals.append(proposal)
                    if window_proposals:
                        recovered = merge_window_proposals(window_proposals, mapping.domain)
                        preliminary = validate_recovery_proposal(
                            recovered, mapping.domain, scope="full"
                        )
                        if preliminary.disagreement_count:
                            conflicts.extend(
                                f"span:{item.span_ids[0]}"
                                for item in recovered.disagreements
                                if item.span_ids
                            )
                        if conflicts and self.config.allow_reconciliation:
                            if len(self._calls) < self.config.max_model_calls:
                                reconciliation = self._reconcile(
                                    raw,
                                    mapping,
                                    outline_digest,
                                    recovered,
                                )
                                reconciliation_report = validate_recovery_proposal(
                                    reconciliation, mapping.domain, scope="full"
                                )
                                if reconciliation_report.passed:
                                    recovered = reconciliation
                                    preliminary = reconciliation_report
                                else:
                                    warnings.append("boundary_reconciliation_failed_validation")
                            else:
                                warnings.append("reconciliation_budget_exhausted")
                        validation = validate_recovery_proposal(
                            recovered, mapping.domain, scope="full"
                        )
                        if validation.passed:
                            parser_view = _recovered_local_view(raw, outline, recovered, mapping)
                            authoritative_view = _recovered_authoritative_view(
                                recovered, validation
                            )
                            promoted_recovery = True
                        else:
                            warnings.extend(validation.errors)
                            recovered = recovered
                            authoritative_view = parser_authoritative
                    else:
                        warnings.append("no_window_proposal_promoted")
                        authoritative_view = parser_authoritative
                except Exception as exc:
                    warnings.append(f"structure_recovery_failed:{type(exc).__name__}")
                    authoritative_view = parser_authoritative
        else:
            authoritative_view = parser_authoritative
        if not promoted_recovery:
            parser_view = (
                parser_view if parser_view.validation_passed else build_parser_view(raw, outline)
            )
            selected = parser_view.model_copy(
                update={"warnings": tuple(dict.fromkeys((*parser_view.warnings, *warnings)))}
            )
            authoritative_view = parser_authoritative
            validation = validation.model_copy(
                update={
                    "passed": validation.passed if not should_recover else False,
                    "scope": "full" if should_recover else validation.scope,
                    "errors": tuple(dict.fromkeys((*validation.errors, *warnings))),
                }
            )
            status: Literal["parser", "recovered", "failed", "deferred"] = (
                "failed" if should_recover else "parser"
            )
        else:
            selected = parser_view.model_copy(
                update={"warnings": tuple(dict.fromkeys((*parser_view.warnings, *warnings)))}
            )
            status = "recovered"
        selected_digest = _digest_json(selected.model_dump(mode="json"))
        prompt_dependencies: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for dependency in self._prompt_dependencies:
            prompt_id = dependency.get("prompt_id")
            stage = {
                "structure.triage": "structure_scan",
                "structure.recover-window": "structure_recovery",
                "structure.reconcile-boundaries": "structure_reconciliation",
            }.get(str(prompt_id))
            if stage is not None:
                prompt_dependencies[stage].append(dependency)
        cache_keys = _structure_cache_keys(
            raw=raw,
            config=self.config,
            outline_digest=outline_digest,
            quality_digest=_quality_digest(normalized.quality),
            scan=scan,
            windows=windows,
            recovered=recovered,
            reconciliation=reconciliation,
            validation=validation,
            prompt_dependencies=prompt_dependencies,
            call_manifests=self._calls,
            prompt_resolutions=self._resolutions,
        )
        metadata = StructureArtifactMetadata(
            source_digest=raw.source_digest,
            document_id=mapping.domain.document_id,
            mode=mode,
            parser_outline_digest=outline_digest,
            quality_digest=_quality_digest(normalized.quality),
            validation_digest=_digest_json(validation.model_dump(mode="json")),
            selected_view_digest=selected_digest,
            cache_keys=cache_keys,
            call_manifests=tuple(self._calls),
            prompt_resolutions=tuple(self._resolutions),
            warnings=tuple(dict.fromkeys(warnings)),
            status=status,
        )
        result = StructureRecoveryResult(
            raw=raw,
            normalized=normalized,
            authoritative_raw=mapping.domain,
            selected_view=selected,
            authoritative_view=authoritative_view,
            scan=scan,
            windows=windows,
            window_proposals=tuple(window_proposals),
            recovered_proposal=recovered,
            reconciliation=reconciliation,
            validation=validation,
            metadata=metadata,
            conflicts=tuple(dict.fromkeys(conflicts)),
        )
        if repository is not None:
            result = persist_structure_result(
                result, repository, run_id=run_id, mode=mode, status=status
            )
        return result

    def _budget_check(self, input_chars: int) -> None:
        route = resolve_route(ROUTE_FLASH_LITE)
        if len(self._calls) >= self.config.max_model_calls:
            raise RecoveryBudgetExceeded("structure model-call budget exhausted")
        if self._input_chars + input_chars > self.config.max_total_input_chars:
            raise RecoveryBudgetExceeded("structure total input budget exhausted")
        if self._output_tokens + route.output_budget > self.config.max_total_output_tokens:
            raise RecoveryBudgetExceeded("structure total output budget exhausted")
        self._input_chars += input_chars
        self._output_tokens += route.output_budget

    def _compose(self, prompt_id: str, variables: Mapping[str, Any]) -> Any:
        if self.prompt_composer is None:
            raise ValidationError("structure recovery requires the WT11 prompt composer")
        composed = self.prompt_composer.compose_with_metadata(prompt_id, variables)
        self._resolutions.append(composed.resolution)
        resolution = composed.resolution.model_dump(mode="json", exclude={"resolved_at"})
        resolution["pack_manifest_sha256"] = getattr(composed, "pack_manifest_sha256", "")
        resolution["pack_sha256"] = getattr(composed, "pack_sha256", "")
        self._prompt_dependencies.append(resolution)
        return composed

    def _invoke(
        self,
        *,
        prompt_id: str,
        schema: type[Any],
        composed: Any,
        input_digests: Sequence[str],
    ) -> Any:
        if self.gateway is None:
            raise ValidationError("structure recovery requires the WT4 Gemini gateway")
        call = self.gateway.invoke(
            route=ROUTE_FLASH_LITE,
            schema=schema,
            prompt=composed.text,
            stage=prompt_id,
            prompt_id=prompt_id,
            prompt_version=composed.resolution.pack_version,
            prompt_digest=composed.digest,
            input_digests=input_digests,
            input_token_budget=composed.input_token_budget,
            output_token_budget=composed.output_token_budget,
        )
        schema_label = {
            GatewayStructureScan: "StructureScan",
            GatewayStructureRecoveryProposal: "StructureRecoveryProposal",
        }.get(schema)
        if schema_label is not None:
            call.manifest.schema_name = schema_label
        self._calls.append(call.manifest)
        return call.artifact

    def _triage(
        self, raw: RawDocument, mapping: DomainRawMapping, outline_digest: str
    ) -> StructureScan:
        source_text = _render_blocks(mapping.domain.blocks, max_chars=self.config.max_triage_chars)
        self._budget_check(len(source_text))
        composed = self._compose(
            "structure.triage",
            {
                "document_type": self.config.document_type,
                "document_metadata": _safe_metadata(raw, mapping, outline_digest),
                "source_text": source_text,
            },
        )
        wire_scan = self._invoke(
            prompt_id="structure.triage",
            schema=GatewayStructureScan,
            composed=composed,
            input_digests=[raw.source_digest, outline_digest],
        )
        scan = _authoritative_scan(wire_scan)
        if (
            scan.document_id != mapping.domain.document_id
            or scan.source_digest != raw.source_digest
        ):
            raise StructureValidationFailure("structure scan does not identify this source")
        if scan.parser_outline_digest != outline_digest:
            raise StructureValidationFailure("structure scan parser outline digest mismatch")
        if scan.prompt_id != "structure.triage":
            raise StructureValidationFailure("structure scan prompt ID mismatch")
        valid_ids = {_domain_span(block) for block in mapping.domain.blocks}
        if any(span_id not in valid_ids for span_id in scan.evidence_span_ids):
            raise StructureValidationFailure("structure scan references an unknown evidence span")
        if any(
            region.start_span_id not in valid_ids or region.end_span_id not in valid_ids
            for region in scan.boundary_regions
        ):
            raise StructureValidationFailure("structure scan references an unknown boundary span")
        return scan

    def _recover_window(
        self,
        raw: RawDocument,
        mapping: DomainRawMapping,
        outline_digest: str,
        window: RecoveryWindow,
        blocks: Sequence[SourceBlock],
    ) -> StructureRecoveryProposal:
        source_text = _render_blocks(blocks, max_chars=self.config.max_window_chars)
        composed = self._compose(
            "structure.recover-window",
            {
                "document_type": self.config.document_type,
                "document_metadata": {
                    **_safe_metadata(raw, mapping, outline_digest),
                    "window_id": window.window_id,
                    "window_start_ordinal": window.start_ordinal,
                    "window_end_ordinal": window.end_ordinal,
                    "window_input_digest": window.input_digest,
                },
                "source_text": source_text,
            },
        )
        wire_proposal = self._invoke(
            prompt_id="structure.recover-window",
            schema=GatewayStructureRecoveryProposal,
            composed=composed,
            input_digests=[raw.source_digest, window.input_digest, outline_digest],
        )
        proposal = _authoritative_proposal(wire_proposal)
        if proposal.prompt_id != "structure.recover-window":
            raise StructureValidationFailure("window proposal prompt ID mismatch")
        return proposal

    def _reconcile(
        self,
        raw: RawDocument,
        mapping: DomainRawMapping,
        outline_digest: str,
        proposal: StructureRecoveryProposal,
    ) -> StructureRecoveryProposal:
        global_map = _render_blocks(
            mapping.domain.blocks,
            max_chars=self.config.max_reconciliation_chars,
            include_text=False,
        )
        analysis_results = json.dumps(
            {
                "proposal": proposal.model_dump(mode="json"),
                "parser_outline_digest": outline_digest,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        self._budget_check(len(global_map) + len(analysis_results))
        composed = self._compose(
            "structure.reconcile-boundaries",
            {
                "document_type": self.config.document_type,
                "document_metadata": _safe_metadata(raw, mapping, outline_digest),
                "source_text": global_map,
                "analysis_results": analysis_results,
            },
        )
        wire_result = self._invoke(
            prompt_id="structure.reconcile-boundaries",
            schema=GatewayStructureRecoveryProposal,
            composed=composed,
            input_digests=[raw.source_digest, outline_digest, _proposal_digest(proposal) or ""],
        )
        result = _authoritative_proposal(wire_result)
        if result.prompt_id != "structure.reconcile-boundaries":
            raise StructureValidationFailure("reconciliation prompt ID mismatch")
        return result


def _record_payload(
    result: StructureRecoveryResult, mode: StructureMode, status: str
) -> dict[str, Any]:
    return {
        "source_digest": result.raw.source_digest,
        "document_id": result.authoritative_raw.document_id,
        "mode": mode,
        "status": status,
        "scan": result.scan.model_dump(mode="json")
        if result.scan is not None
        else {"status": "not_run"},
        "windows": [window.model_dump(mode="json") for window in result.windows],
        "window_proposals": [
            proposal.model_dump(mode="json") for proposal in result.window_proposals
        ],
        "reconciliation": result.reconciliation.model_dump(mode="json")
        if result.reconciliation
        else {"status": "not_needed"},
        "recovered_proposal": result.recovered_proposal.model_dump(mode="json")
        if result.recovered_proposal
        else {"status": "not_promoted"},
        "validation": result.validation.model_dump(mode="json"),
        "selected_view": result.selected_view.model_dump(mode="json"),
        "authoritative_view": result.authoritative_view.model_dump(mode="json"),
        "conflicts": list(result.conflicts),
    }


def persist_structure_result(
    result: StructureRecoveryResult,
    repository: Any,
    *,
    run_id: str | None,
    mode: StructureMode,
    status: Literal["parser", "recovered", "failed", "deferred"],
) -> StructureRecoveryResult:
    """Persist independent structure artifacts through the repository's atomic API."""

    storage = (
        repository if hasattr(repository, "paths") and hasattr(repository, "repository") else None
    )
    repo = storage.repository if storage is not None else repository
    resolved_run_id = storage.paths.run_id if storage is not None else run_id
    if resolved_run_id is None:
        raise ValidationError("run_id is required when persisting through a repository")
    if not hasattr(repo, "put_json_revision"):
        raise ValidationError("repository does not expose the M3B atomic revision API")
    records: list[Any] = []
    payload = _record_payload(result, mode, status)
    scan_value = payload["scan"]
    proposal_value = payload["recovered_proposal"]
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/structure-scan.json",
            scan_value,
            stage="structure_scan",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/recovery/windows.json",
            payload["windows"],
            stage="structure_recovery",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/recovery/window-proposals.json",
            payload["window_proposals"],
            stage="structure_recovery",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/recovery/reconciliation.json",
            payload["reconciliation"],
            stage="structure_reconciliation",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/recovered-outline.json",
            proposal_value,
            stage="structure_recovery",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/recovery/validation.json",
            payload["validation"],
            stage="structure_recovery",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/selected-view.json",
            payload["selected_view"],
            stage="selected_view",
            replace=True,
        )
    )
    calls = (
        [manifest.model_dump(mode="json") for manifest in result.metadata.call_manifests]
        if result.metadata
        else []
    )
    resolutions = (
        [resolution.model_dump(mode="json") for resolution in result.metadata.prompt_resolutions]
        if result.metadata
        else []
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/model-calls.json",
            calls,
            stage="structure_metadata",
            replace=True,
        )
    )
    records.append(
        repo.put_json_revision(
            resolved_run_id,
            "source/prompt-resolutions.json",
            resolutions,
            stage="structure_metadata",
            replace=True,
        )
    )
    parser_outline_digest = _outline_digest(result.normalized.parser_outline)
    quality_digest = _quality_digest(result.normalized.quality)
    digest_by_path = {record.relative_path: record.digest for record in records}
    cache_keys = dict(result.metadata.cache_keys) if result.metadata else {}
    metadata = StructureArtifactMetadata(
        source_digest=result.raw.source_digest,
        document_id=result.authoritative_raw.document_id,
        mode=mode,
        parser_outline_digest=parser_outline_digest,
        quality_digest=quality_digest,
        scan_digest=digest_by_path.get("source/structure-scan.json"),
        windows_digest=digest_by_path.get("source/recovery/windows.json"),
        proposal_digest=digest_by_path.get("source/recovered-outline.json"),
        reconciliation_digest=digest_by_path.get("source/recovery/reconciliation.json"),
        validation_digest=digest_by_path["source/recovery/validation.json"],
        selected_view_digest=digest_by_path["source/selected-view.json"],
        cache_keys=cache_keys,
        call_manifests=tuple(result.metadata.call_manifests) if result.metadata else (),
        prompt_resolutions=tuple(result.metadata.prompt_resolutions) if result.metadata else (),
        warnings=result.selected_view.warnings,
        status=status,
    )
    metadata_record = repo.put_json_revision(
        resolved_run_id,
        "source/structure-recovery-metadata.json",
        metadata.model_dump(mode="json"),
        stage="structure_metadata",
        replace=True,
    )
    records.append(metadata_record)
    if storage is not None:
        from ..artifacts.checkpoint import CheckpointRecord
        from ..artifacts.manifest import RunManifest, StageRecord

        manifest = RunManifest.load(storage.paths.manifest)
        manifest = manifest.with_structure_recovery(
            mode=mode,
            scan_digest=digest_by_path.get("source/structure-scan.json"),
            recovery_digest=digest_by_path.get("source/recovered-outline.json"),
            validation_digest=digest_by_path["source/recovery/validation.json"],
            selected_view_digest=digest_by_path["source/selected-view.json"],
            reconciliation_digest=digest_by_path.get("source/recovery/reconciliation.json"),
            call_manifests=metadata.call_manifests,
            prompt_resolutions=metadata.prompt_resolutions,
        )
        for record in records:
            manifest = manifest.record_artifact(record)
        grouped = {
            "structure_scan": [record for record in records if record.stage == "structure_scan"],
            "structure_recovery": [
                record for record in records if record.stage == "structure_recovery"
            ],
            "structure_reconciliation": [
                record for record in records if record.stage == "structure_reconciliation"
            ],
            "structure_metadata": [
                record for record in records if record.stage == "structure_metadata"
            ],
            "selected_view": [record for record in records if record.stage == "selected_view"],
        }
        for stage, stage_records in grouped.items():
            if not stage_records:
                continue
            cache_key = metadata.cache_keys.get(
                stage, _digest_json({"stage": stage, "source": result.raw.source_digest})
            )
            manifest = manifest.record_stage(
                StageRecord(
                    stage=stage,
                    status="succeeded" if status in {"parser", "recovered"} else "failed",
                    cache_key=cache_key,
                    artifact_paths=tuple(record.relative_path for record in stage_records),
                    artifact_digests=tuple(record.digest for record in stage_records),
                )
            )
            storage.checkpoints.save(
                CheckpointRecord(
                    run_id=resolved_run_id,
                    stage=stage,
                    cache_key=cache_key,
                    status="succeeded" if status in {"parser", "recovered"} else "failed",
                    artifact_digest=stage_records[0].digest,
                    artifact_path=stage_records[0].relative_path,
                    payload={"artifact_paths": [record.relative_path for record in stage_records]},
                )
            )
        storage.repository.save_manifest(
            manifest.with_status("succeeded" if status in {"parser", "recovered"} else "failed")
        )
    return result.model_copy(update={"metadata": metadata})


__all__ = [
    "DomainRawMapping",
    "GatewayStructureRecoveryProposal",
    "GatewayStructureScan",
    "RecoveryBudgetExceeded",
    "RecoveryWindow",
    "StructureArtifactMetadata",
    "StructureMode",
    "StructureRecoveryConfig",
    "StructureRecoveryResult",
    "StructureRecoveryService",
    "StructureValidationFailure",
    "StructureValidationReport",
    "adapt_raw_document",
    "build_recovery_windows",
    "merge_window_proposals",
    "persist_structure_result",
    "validate_recovery_proposal",
]
