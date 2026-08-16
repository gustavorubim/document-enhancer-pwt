"""Versioned contracts and deterministic rendering for Stage 1 drafts.

The transformation lane is intentionally independent from the existing core models.  It
describes the boundary between source evidence, a selected template, and an unapproved
candidate draft.  The contracts carry identifiers rather than copied source text so a later
runner can attach the bundle to the canonical source and figure inventories without weakening
provenance checks.

``validate_coverage`` is the fail-closed boundary.  It checks that every known source span has
one and only one disposition, every section status and reference resolves, and all figure and
question references are known.  ``render_markdown`` calls that validator before rendering, so a
candidate cannot silently turn an invalid mapping into a plausible document.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_FIGURE_ID_PATTERN = r"^FIG-\d{3,}$"
_GAP_ID_PATTERN = r"^GAP-\d{3,}$"

DraftStatus = Literal[
    "populated",
    "partial",
    "missing",
    "conflicting",
    "not_applicable",
]
SourceAction = Literal["placed", "duplicated", "intentionally_omitted"]
GapKind = Literal["missing", "ambiguous", "conflicting", "unreadable_visual"]
VisualKind = Literal[
    "table",
    "process_diagram",
    "chart",
    "ui_screenshot",
    "decorative",
    "unknown",
]
VisualStatus = Literal["extracted", "best_effort", "requires_review", "unsupported"]
ContentOrigin = Literal["source", "accepted_decision", "recipe_structure"]


class TransformationModel(BaseModel):
    """Strict, assignment-validating base for transformation contracts."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
    )


class DraftSection(TransformationModel):
    """One template-aligned section in the unapproved candidate draft.

    ``required`` and ``order`` are copied from the selected template requirement.  They live on
    the draft section so a serialized transformation bundle is self-describing and can be
    validated without importing a recipe implementation.
    """

    schema_version: Literal["core.draft-section.v1"] = "core.draft-section.v1"
    template_section_id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    status: DraftStatus
    rewritten_markdown: str = ""
    source_span_ids: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    gap_ids: list[str] = Field(default_factory=list)
    required: bool = True
    order: int = Field(default=0, ge=0)
    level: int = Field(default=2, ge=1, le=6)
    content_origin: ContentOrigin = "source"
    accepted_decision_ids: list[str] = Field(default_factory=list)


# The plan names the bundle collection ``template_sections`` while the item contract is
# ``DraftSection``.  Exporting this semantic alias makes both vocabulary choices available
# without introducing a second, weaker copy of the section contract.
TemplateSection = DraftSection


class SourceDisposition(TransformationModel):
    """The sole disposition record for one source span."""

    schema_version: Literal["core.source-disposition.v1"] = "core.source-disposition.v1"
    source_span_id: str = Field(min_length=1)
    action: SourceAction
    destination_section_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_destinations(self) -> SourceDisposition:
        destinations = self.destination_section_ids
        if len(destinations) != len(set(destinations)):
            raise ValueError("source disposition destination_section_ids must be unique")
        if self.action == "placed" and len(destinations) != 1:
            raise ValueError("a placed source span must have exactly one destination section")
        if self.action == "duplicated" and len(destinations) < 2:
            raise ValueError("a duplicated source span must have at least two destinations")
        if self.action == "intentionally_omitted" and destinations:
            raise ValueError("an intentionally omitted source span cannot have destinations")
        return self


class Gap(TransformationModel):
    """Structured missing, ambiguous, conflicting, or unreadable evidence marker."""

    schema_version: Literal["core.gap.v1"] = "core.gap.v1"
    gap_id: str = Field(pattern=_GAP_ID_PATTERN)
    template_section_id: str = Field(min_length=1)
    kind: GapKind
    description: str = Field(min_length=1)
    evidence_span_ids: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    blocking: bool = True
    question_id: str | None = Field(default=None, min_length=1)


class TransformationQuestion(TransformationModel):
    """A reviewer question linked to source or figure evidence."""

    schema_version: Literal["core.transformation-question.v1"] = "core.transformation-question.v1"
    question_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    blocking: bool = True
    section_id: str | None = Field(default=None, min_length=1)
    evidence_span_ids: list[str] = Field(default_factory=list)
    figure_ids: list[str] = Field(default_factory=list)
    suggestion: str | None = None


# ``Question`` is convenient for callers that use the short contract name; the longer name
# avoids colliding with the pre-existing review Question when this module is read alongside it.
Question = TransformationQuestion


class VisualReference(TransformationModel):
    """Immutable source-figure identity available to the transformation."""

    schema_version: Literal["core.visual-reference.v1"] = "core.visual-reference.v1"
    figure_id: str = Field(pattern=_FIGURE_ID_PATTERN)
    source_digest: str = Field(pattern=_SHA256_PATTERN)
    media_type: str = Field(min_length=1)
    source_span_ids: list[str] = Field(default_factory=list)
    caption: str = ""


class VisualExtraction(TransformationModel):
    """Bounded interpretation of a source figure, retaining its source digest."""

    schema_version: Literal["core.visual-extraction.v1"] = "core.visual-extraction.v1"
    figure_id: str = Field(pattern=_FIGURE_ID_PATTERN)
    source_digest: str = Field(pattern=_SHA256_PATTERN)
    kind: VisualKind
    status: VisualStatus
    structured_content: dict[str, Any] | list[Any] | None = None
    source_span_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CoverageReport(TransformationModel):
    """Machine-readable result of deterministic transformation coverage validation."""

    schema_version: Literal["core.transformation-coverage.v1"] = "core.transformation-coverage.v1"
    valid: bool
    source_span_ids: list[str] = Field(default_factory=list)
    disposition_span_ids: list[str] = Field(default_factory=list)
    missing_source_span_ids: list[str] = Field(default_factory=list)
    duplicate_source_span_ids: list[str] = Field(default_factory=list)
    missing_section_status_ids: list[str] = Field(default_factory=list)
    duplicate_section_ids: list[str] = Field(default_factory=list)
    unknown_span_references: list[str] = Field(default_factory=list)
    unknown_section_references: list[str] = Field(default_factory=list)
    unknown_gap_references: list[str] = Field(default_factory=list)
    unknown_question_references: list[str] = Field(default_factory=list)
    unknown_figure_references: list[str] = Field(default_factory=list)
    invalid_gap_ids: list[str] = Field(default_factory=list)
    invalid_visual_references: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    source_span_coverage: float = Field(ge=0.0, le=1.0)
    required_section_status_coverage: float = Field(ge=0.0, le=1.0)


class TransformationBundle(TransformationModel):
    """Complete source-to-template mapping and unapproved draft contract."""

    schema_version: Literal["core.transformation.v1"] = "core.transformation.v1"
    source_digest: str = Field(pattern=_SHA256_PATTERN)
    recipe_id: str = Field(min_length=1)
    recipe_digest: str = Field(pattern=_SHA256_PATTERN)
    # ``draft_sections`` is accepted as an input alias for callers that prefer that name.  The
    # serialized and canonical field name remains the frozen-plan name, ``template_sections``.
    template_sections: list[DraftSection] = Field(
        default_factory=list,
        validation_alias=AliasChoices("template_sections", "draft_sections"),
    )
    source_span_ids: list[str] = Field(default_factory=list)
    source_dispositions: list[SourceDisposition] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    questions: list[TransformationQuestion] = Field(default_factory=list)
    visual_references: list[VisualReference] = Field(default_factory=list)
    visual_extractions: list[VisualExtraction] = Field(default_factory=list)

    @property
    def draft_sections(self) -> list[DraftSection]:
        """Return the template-aligned draft sections under the alternate vocabulary."""

        return self.template_sections

    def coverage_report(
        self,
        *,
        source_span_ids: Iterable[str] | None = None,
        figure_ids: Iterable[str] | None = None,
    ) -> CoverageReport:
        """Build a deterministic coverage report without mutating the bundle."""

        return coverage_report(self, source_span_ids=source_span_ids, figure_ids=figure_ids)

    def validate_coverage(
        self,
        *,
        source_span_ids: Iterable[str] | None = None,
        figure_ids: Iterable[str] | None = None,
    ) -> CoverageReport:
        """Raise ``TransformationCoverageError`` unless all references resolve."""

        return validate_coverage(self, source_span_ids=source_span_ids, figure_ids=figure_ids)

    def render_markdown(self) -> str:
        """Render this candidate draft using the canonical byte-stable renderer."""

        return render_markdown(self)


class TransformationCoverageError(ValueError):
    """Fail-closed error raised for invalid transformation coverage or references."""

    def __init__(self, report: CoverageReport) -> None:
        self.report = report
        detail = "; ".join(report.errors) if report.errors else "unknown coverage error"
        super().__init__(f"transformation coverage validation failed: {detail}")


def _ordered_unique(values: Iterable[str]) -> tuple[list[str], list[str]]:
    """Return values in first-seen order and duplicate values in sorted order."""

    ordered: list[str] = []
    counts: Counter[str] = Counter()
    for value in values:
        item = str(value)
        if counts[item] == 0:
            ordered.append(item)
        counts[item] += 1
    duplicates = sorted(item for item, count in counts.items() if count > 1)
    return ordered, duplicates


def _coerce_inventory(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [str(value) for value in values]


def coverage_report(
    bundle: TransformationBundle,
    *,
    source_span_ids: Iterable[str] | None = None,
    figure_ids: Iterable[str] | None = None,
) -> CoverageReport:
    """Return deterministic coverage diagnostics for ``bundle``.

    ``source_span_ids`` and ``figure_ids`` are optional authoritative inventories supplied by a
    caller that owns the source extraction.  When omitted, source spans are derived from the
    disposition records and figures are derived from visual references/extractions.  Supplying an
    inventory is recommended because it lets this function detect an entirely missing
    disposition or figure record.
    """

    errors: list[str] = []

    def error(message: str) -> None:
        errors.append(message)

    explicit_source_ids = _coerce_inventory(source_span_ids)
    configured_source_ids = (
        explicit_source_ids
        if explicit_source_ids is not None
        else (list(bundle.source_span_ids) if bundle.source_span_ids else None)
    )
    disposition_ids = [item.source_span_id for item in bundle.source_dispositions]
    if configured_source_ids is None:
        source_ids, duplicate_source_ids = _ordered_unique(disposition_ids)
    else:
        source_ids, duplicate_source_ids = _ordered_unique(configured_source_ids)

    disposition_counts = Counter(disposition_ids)
    missing_source_ids = sorted(item for item in source_ids if disposition_counts[item] == 0)
    duplicate_disposition_ids = sorted(
        item for item, count in disposition_counts.items() if count > 1
    )
    duplicate_source_ids = sorted(set(duplicate_source_ids) | set(duplicate_disposition_ids))
    unknown_disposition_ids = (
        sorted(set(disposition_ids) - set(source_ids)) if configured_source_ids is not None else []
    )
    if missing_source_ids:
        error(f"source spans without exactly one disposition: {', '.join(missing_source_ids)}")
    if duplicate_source_ids:
        error(f"source spans with multiple disposition records: {', '.join(duplicate_source_ids)}")
    if unknown_disposition_ids:
        error(f"dispositions reference unknown source spans: {', '.join(unknown_disposition_ids)}")

    section_ids, duplicate_section_ids = _ordered_unique(
        item.template_section_id for item in bundle.template_sections
    )
    if duplicate_section_ids:
        error(f"duplicate template section IDs: {', '.join(duplicate_section_ids)}")
    section_id_set = set(section_ids)
    missing_section_status_ids = sorted(
        item.template_section_id for item in bundle.template_sections if not item.status
    )
    if missing_section_status_ids:
        error(
            "required template sections without a status: " + ", ".join(missing_section_status_ids)
        )

    known_gap_ids, duplicate_gap_ids = _ordered_unique(item.gap_id for item in bundle.gaps)
    if duplicate_gap_ids:
        error(f"duplicate gap IDs: {', '.join(duplicate_gap_ids)}")
    invalid_gap_ids = sorted(
        item.gap_id for item in bundle.gaps if not re.fullmatch(_GAP_ID_PATTERN, item.gap_id)
    )
    if invalid_gap_ids:
        error(f"gap IDs are not stable GAP-### identifiers: {', '.join(invalid_gap_ids)}")
    gap_id_set = set(known_gap_ids)

    known_question_ids, duplicate_question_ids = _ordered_unique(
        item.question_id for item in bundle.questions
    )
    if duplicate_question_ids:
        error(f"duplicate question IDs: {', '.join(duplicate_question_ids)}")
    question_id_set = set(known_question_ids)

    visual_reference_ids, duplicate_visual_reference_ids = _ordered_unique(
        item.figure_id for item in bundle.visual_references
    )
    extraction_ids, duplicate_extraction_ids = _ordered_unique(
        item.figure_id for item in bundle.visual_extractions
    )
    if duplicate_visual_reference_ids:
        error("duplicate visual reference IDs: " + ", ".join(duplicate_visual_reference_ids))
    if duplicate_extraction_ids:
        error("duplicate visual extraction IDs: " + ", ".join(duplicate_extraction_ids))
    invalid_visual_references: set[str] = set(duplicate_visual_reference_ids) | set(
        duplicate_extraction_ids
    )

    configured_figure_ids = _coerce_inventory(figure_ids)
    known_figure_ids = set(visual_reference_ids) | set(extraction_ids)
    if configured_figure_ids is not None:
        _, duplicate_configured_figure_ids = _ordered_unique(configured_figure_ids)
        if duplicate_configured_figure_ids:
            error(
                "duplicate figure IDs in authoritative inventory: "
                + ", ".join(duplicate_configured_figure_ids)
            )
        known_figure_ids |= set(configured_figure_ids)
    visual_reference_by_id = {item.figure_id: item for item in bundle.visual_references}
    for extraction in bundle.visual_extractions:
        reference = visual_reference_by_id.get(extraction.figure_id)
        if reference is not None and reference.source_digest != extraction.source_digest:
            error(f"visual extraction digest mismatch for {extraction.figure_id}")
            invalid_visual_references.add(extraction.figure_id)
        if configured_figure_ids is not None and extraction.figure_id not in set(
            configured_figure_ids
        ):
            error(f"visual extraction references unknown figure: {extraction.figure_id}")
            invalid_visual_references.add(extraction.figure_id)
    if configured_figure_ids is not None:
        unknown_visual_inventory_ids = sorted(
            set(visual_reference_ids) - set(configured_figure_ids)
        )
        if unknown_visual_inventory_ids:
            error(
                "visual references contain unknown figures: "
                + ", ".join(unknown_visual_inventory_ids)
            )
            invalid_visual_references.update(unknown_visual_inventory_ids)

    source_id_set = set(source_ids)
    unknown_span_references: set[str] = set(unknown_disposition_ids)
    unknown_section_references: set[str] = set()
    unknown_gap_references: set[str] = set()
    unknown_question_references: set[str] = set()
    unknown_figure_references: set[str] = set()

    for disposition in bundle.source_dispositions:
        unknown_section_references.update(
            item for item in disposition.destination_section_ids if item not in section_id_set
        )
    for section in bundle.template_sections:
        unknown_span_references.update(
            item for item in section.source_span_ids if item not in source_id_set
        )
        unknown_figure_references.update(
            item for item in section.figure_ids if item not in known_figure_ids
        )
        unknown_gap_references.update(item for item in section.gap_ids if item not in gap_id_set)
        for gap_id in section.gap_ids:
            if gap_id not in gap_id_set:
                continue
            gap = next(item for item in bundle.gaps if item.gap_id == gap_id)
            if gap.kind == "conflicting" and section.status != "conflicting":
                error(
                    f"section {section.template_section_id} references conflicting gap "
                    f"{gap_id} without conflicting status"
                )
        if section.status in {"partial", "missing", "conflicting"} and not section.gap_ids:
            error(
                f"section {section.template_section_id} has status {section.status} "
                "without a structured gap marker"
            )
        if section.status == "conflicting" and section.gap_ids:
            linked_gaps = [item for item in bundle.gaps if item.gap_id in set(section.gap_ids)]
            if not any(item.kind == "conflicting" for item in linked_gaps):
                error(f"conflicting section {section.template_section_id} lacks a conflicting gap")
        if section.rewritten_markdown.strip() and section.status in {
            "populated",
            "partial",
            "conflicting",
        }:
            if section.content_origin == "source" and not section.source_span_ids:
                error(
                    f"section {section.template_section_id} has content without source span evidence"
                )
            if section.content_origin == "accepted_decision" and not section.accepted_decision_ids:
                error(
                    f"section {section.template_section_id} has decision-origin content "
                    "without an accepted decision ID"
                )
    for gap in bundle.gaps:
        if gap.template_section_id not in section_id_set:
            unknown_section_references.add(gap.template_section_id)
        unknown_span_references.update(
            item for item in gap.evidence_span_ids if item not in source_id_set
        )
        unknown_figure_references.update(
            item for item in gap.figure_ids if item not in known_figure_ids
        )
        if gap.question_id is not None and gap.question_id not in question_id_set:
            unknown_question_references.add(gap.question_id)
    for question in bundle.questions:
        unknown_span_references.update(
            item for item in question.evidence_span_ids if item not in source_id_set
        )
        unknown_figure_references.update(
            item for item in question.figure_ids if item not in known_figure_ids
        )
        if question.section_id is not None and question.section_id not in section_id_set:
            unknown_section_references.add(question.section_id)
    for visual in bundle.visual_references:
        unknown_span_references.update(
            item for item in visual.source_span_ids if item not in source_id_set
        )
    for extraction in bundle.visual_extractions:
        unknown_span_references.update(
            item for item in extraction.source_span_ids if item not in source_id_set
        )

    if unknown_span_references:
        error("unknown source span references: " + ", ".join(sorted(unknown_span_references)))
    if unknown_section_references:
        error(
            "unknown template section references: " + ", ".join(sorted(unknown_section_references))
        )
    if unknown_gap_references:
        error("unknown gap references: " + ", ".join(sorted(unknown_gap_references)))
    if unknown_question_references:
        error("unknown question references: " + ", ".join(sorted(unknown_question_references)))
    if unknown_figure_references:
        error("unknown figure references: " + ", ".join(sorted(unknown_figure_references)))

    source_coverage = (
        1.0
        if not source_ids
        else sum(1 for item in source_ids if disposition_counts[item] == 1) / len(source_ids)
    )
    required_sections = [item for item in bundle.template_sections if item.required]
    required_status_coverage = (
        1.0
        if not required_sections
        else sum(1 for item in required_sections if bool(item.status)) / len(required_sections)
    )
    return CoverageReport(
        valid=not errors,
        source_span_ids=source_ids,
        disposition_span_ids=disposition_ids,
        missing_source_span_ids=missing_source_ids,
        duplicate_source_span_ids=duplicate_source_ids,
        missing_section_status_ids=missing_section_status_ids,
        duplicate_section_ids=duplicate_section_ids,
        unknown_span_references=sorted(unknown_span_references),
        unknown_section_references=sorted(unknown_section_references),
        unknown_gap_references=sorted(unknown_gap_references),
        unknown_question_references=sorted(unknown_question_references),
        unknown_figure_references=sorted(unknown_figure_references),
        invalid_gap_ids=invalid_gap_ids,
        invalid_visual_references=sorted(invalid_visual_references),
        errors=sorted(set(errors)),
        source_span_coverage=source_coverage,
        required_section_status_coverage=required_status_coverage,
    )


def validate_coverage(
    bundle: TransformationBundle,
    *,
    source_span_ids: Iterable[str] | None = None,
    figure_ids: Iterable[str] | None = None,
) -> CoverageReport:
    """Validate source coverage and all cross-references, raising on any failure."""

    report = coverage_report(bundle, source_span_ids=source_span_ids, figure_ids=figure_ids)
    if not report.valid:
        raise TransformationCoverageError(report)
    return report


def validate_transformation_bundle(
    bundle: TransformationBundle,
    *,
    source_span_ids: Iterable[str] | None = None,
    figure_ids: Iterable[str] | None = None,
) -> CoverageReport:
    """Explicitly named alias for integrations that use the full contract name."""

    return validate_coverage(bundle, source_span_ids=source_span_ids, figure_ids=figure_ids)


def check_coverage(
    bundle: TransformationBundle,
    *,
    source_span_ids: Iterable[str] | None = None,
    figure_ids: Iterable[str] | None = None,
) -> bool:
    """Return only the validity bit for callers that do not need diagnostics."""

    return coverage_report(bundle, source_span_ids=source_span_ids, figure_ids=figure_ids).valid


_STATUS_NOTES: dict[DraftStatus, str] = {
    "populated": "This candidate section is marked populated; it remains unapproved.",
    "partial": "Required information is incomplete; resolve the structured review markers.",
    "missing": "Required information is absent; resolve the structured review markers.",
    "conflicting": "Source evidence conflicts; do not choose a value without review.",
    "not_applicable": "This section is explicitly classified as not applicable.",
}


def _single_line(value: str) -> str:
    return " ".join(value.replace("\r\n", "\n").replace("\r", "\n").split())


def _normalise_markdown(value: str) -> str:
    lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _render_gap(gap: Gap, questions: dict[str, TransformationQuestion]) -> list[str]:
    lines = [
        f"> **{gap.gap_id}** — {gap.kind.replace('_', ' ').title()}: {_single_line(gap.description)}",
        "> This is structured review metadata, not a source fact.",
    ]
    if gap.question_id is not None:
        question = questions[gap.question_id]
        lines.extend(
            [
                f"> **{question.question_id}** — Review question: {_single_line(question.prompt)}",
                f"> Reason: {_single_line(question.reason)}",
            ]
        )
        if question.suggestion:
            lines.append(f"> Suggestion for review only: {_single_line(question.suggestion)}")
    return lines


def render_markdown(bundle: TransformationBundle) -> str:
    """Render a byte-deterministic, visibly unapproved candidate Markdown document.

    Sections are ordered by their explicit template order and then by ID.  Newlines are always
    LF, trailing whitespace is removed, and review markers are emitted in sorted identifier order.
    The function validates first, so unresolved references cannot disappear into the rendered
    text.
    """

    validate_coverage(bundle)
    questions = {item.question_id: item for item in bundle.questions}
    gaps = {item.gap_id: item for item in bundle.gaps}
    sections = sorted(
        bundle.template_sections,
        key=lambda item: (item.order, item.template_section_id),
    )
    used_gap_ids: set[str] = set()
    used_question_ids: set[str] = set()
    lines = [
        "# Candidate draft",
        "",
        (
            "> **UNAPPROVED DRAFT** — This Stage 1 candidate is for human review and is not "
            "approved or sealed."
        ),
        "",
    ]
    for section in sections:
        status = section.status
        lines.extend(
            [
                f"<!-- document-enhancer:section={section.template_section_id} status={status} -->",
                f"{'#' * section.level} {section.heading.strip()}",
                "",
                f"> **DRAFT STATUS: {status.upper()}** — {_STATUS_NOTES[status]}",
            ]
        )
        content = _normalise_markdown(section.rewritten_markdown)
        if content:
            lines.extend(["", content])
        for gap_id in sorted(section.gap_ids):
            gap = gaps[gap_id]
            used_gap_ids.add(gap_id)
            if gap.question_id is not None:
                used_question_ids.add(gap.question_id)
            lines.extend(["", *_render_gap(gap, questions)])
        lines.append("")

    unplaced_gaps = sorted(set(gaps) - used_gap_ids)
    standalone_questions = sorted(set(questions) - used_question_ids)
    if unplaced_gaps or standalone_questions:
        lines.extend(["## Review markers", ""])
        for gap_id in unplaced_gaps:
            gap = gaps[gap_id]
            if gap.question_id is not None:
                used_question_ids.add(gap.question_id)
            lines.extend([*_render_gap(gap, questions), ""])
        for question_id in standalone_questions:
            question = questions[question_id]
            lines.extend(
                [
                    f"> **{question.question_id}** — Review question: {_single_line(question.prompt)}",
                    f"> Reason: {_single_line(question.reason)}",
                ]
            )
            if question.suggestion:
                lines.append(f"> Suggestion for review only: {_single_line(question.suggestion)}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_draft_markdown(bundle: TransformationBundle) -> str:
    """Named alias used by draft-focused callers."""

    return render_markdown(bundle)


__all__ = [
    "ContentOrigin",
    "CoverageReport",
    "DraftSection",
    "DraftStatus",
    "Gap",
    "GapKind",
    "Question",
    "SourceAction",
    "SourceDisposition",
    "TemplateSection",
    "TransformationBundle",
    "TransformationCoverageError",
    "TransformationModel",
    "TransformationQuestion",
    "VisualExtraction",
    "VisualKind",
    "VisualReference",
    "VisualStatus",
    "check_coverage",
    "coverage_report",
    "render_draft_markdown",
    "render_markdown",
    "validate_coverage",
    "validate_transformation_bundle",
]
