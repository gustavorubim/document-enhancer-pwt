"""Focused acceptance tests for the deterministic transformation boundary."""

import pytest
from pydantic import ValidationError

from document_enhancer.core.transformation import (
    DraftSection,
    Gap,
    SourceDisposition,
    TransformationBundle,
    TransformationCoverageError,
    VisualExtraction,
    VisualReference,
    render_draft_markdown,
    validate_coverage,
)


def _bundle(*, unknown_source: bool = False, unknown_figure: bool = False) -> TransformationBundle:
    source_span_ids = ["span-001", "span-002", "span-003", "span-004"]
    source_for_partial = "span-999" if unknown_source else "span-002"
    figure_for_partial = "FIG-999" if unknown_figure else "FIG-001"
    return TransformationBundle(
        source_digest="a" * 64,
        recipe_id="enterprise_core@2.0.0/process",
        recipe_digest="b" * 64,
        source_span_ids=source_span_ids,
        template_sections=[
            DraftSection(
                template_section_id="SEC-001",
                heading="Purpose",
                status="populated",
                rewritten_markdown="The process supports a documented outcome.",
                source_span_ids=["span-001"],
                order=20,
            ),
            DraftSection(
                template_section_id="SEC-002",
                heading="Roles",
                status="partial",
                rewritten_markdown="The performer is recorded, but the approver is unresolved.",
                source_span_ids=[source_for_partial],
                figure_ids=[figure_for_partial],
                gap_ids=["GAP-001"],
                order=30,
            ),
            DraftSection(
                template_section_id="SEC-003",
                heading="Controls",
                status="missing",
                gap_ids=["GAP-002"],
                order=40,
            ),
            DraftSection(
                template_section_id="SEC-004",
                heading="Decision rule",
                status="conflicting",
                rewritten_markdown="Two source values are recorded without choosing between them.",
                source_span_ids=["span-003"],
                gap_ids=["GAP-003"],
                order=50,
            ),
            DraftSection(
                template_section_id="SEC-005",
                heading="Local overlay",
                status="not_applicable",
                required=False,
                order=60,
            ),
        ],
        source_dispositions=[
            SourceDisposition(
                source_span_id="span-001",
                action="placed",
                destination_section_ids=["SEC-001"],
                rationale="The source states the purpose.",
            ),
            SourceDisposition(
                source_span_id="span-002",
                action="placed",
                destination_section_ids=["SEC-002"],
                rationale="The source names the performer.",
            ),
            SourceDisposition(
                source_span_id="span-003",
                action="duplicated",
                destination_section_ids=["SEC-003", "SEC-004"],
                rationale="The conflict is relevant to controls and the decision rule.",
            ),
            SourceDisposition(
                source_span_id="span-004",
                action="intentionally_omitted",
                rationale="The span is classified as out of scope for this template.",
            ),
        ],
        gaps=[
            Gap(
                gap_id="GAP-001",
                template_section_id="SEC-002",
                kind="missing",
                description="The accountable approver is not identified.",
                evidence_span_ids=["span-002"],
                figure_ids=["FIG-001"],
                question_id="Q-001",
            ),
            Gap(
                gap_id="GAP-002",
                template_section_id="SEC-003",
                kind="missing",
                description="No control evidence is present in the source.",
                question_id="Q-002",
            ),
            Gap(
                gap_id="GAP-003",
                template_section_id="SEC-004",
                kind="conflicting",
                description="The source records two incompatible thresholds.",
                evidence_span_ids=["span-003"],
                question_id="Q-003",
            ),
        ],
        questions=[
            {
                "question_id": "Q-001",
                "prompt": "Which accountable approver should be recorded?",
                "reason": "The template requires an approval role.",
            },
            {
                "question_id": "Q-002",
                "prompt": "What evidence demonstrates the control?",
                "reason": "The required control section has no source evidence.",
            },
            {
                "question_id": "Q-003",
                "prompt": "Which threshold is authoritative?",
                "reason": "The source statements conflict.",
            },
        ],
        visual_references=[
            VisualReference(
                figure_id="FIG-001",
                source_digest="c" * 64,
                media_type="image/png",
                source_span_ids=["span-002"],
            )
        ],
        visual_extractions=[
            VisualExtraction(
                figure_id="FIG-001",
                source_digest="c" * 64,
                kind="table",
                status="requires_review",
                structured_content={"headers": ["Role"], "rows": [["Performer"]]},
                source_span_ids=["span-002"],
                warnings=["The visual conversion requires human review."],
            )
        ],
    )


@pytest.mark.unit
def test_valid_bundle_has_complete_coverage_and_stable_contract_versions() -> None:
    bundle = _bundle()

    report = validate_coverage(bundle)

    assert report.valid
    assert report.source_span_coverage == 1.0
    assert report.required_section_status_coverage == 1.0
    assert bundle.schema_version == "core.transformation.v1"
    assert bundle.template_sections[0].schema_version == "core.draft-section.v1"


@pytest.mark.unit
def test_every_source_span_requires_exactly_one_disposition() -> None:
    bundle = _bundle()
    bundle.source_dispositions.append(
        SourceDisposition(
            source_span_id="span-001",
            action="placed",
            destination_section_ids=["SEC-002"],
            rationale="A duplicate record is intentionally invalid.",
        )
    )

    with pytest.raises(TransformationCoverageError, match="multiple disposition records"):
        validate_coverage(bundle)


@pytest.mark.unit
def test_unknown_span_and_figure_references_fail_closed() -> None:
    for invalid_bundle in (_bundle(unknown_source=True), _bundle(unknown_figure=True)):
        with pytest.raises(TransformationCoverageError, match="unknown"):
            validate_coverage(invalid_bundle)


@pytest.mark.unit
def test_unknown_section_gap_and_question_references_fail_closed() -> None:
    bundle = _bundle()
    bundle.source_dispositions[0].destination_section_ids = ["SEC-404"]
    bundle.template_sections[1].gap_ids = ["GAP-404"]
    bundle.gaps[0].question_id = "Q-404"

    with pytest.raises(TransformationCoverageError) as raised:
        validate_coverage(bundle)

    message = str(raised.value)
    assert "SEC-404" in message
    assert "GAP-404" in message
    assert "Q-404" in message


@pytest.mark.unit
def test_rendering_is_byte_deterministic_and_marks_unresolved_content_as_metadata() -> None:
    bundle = _bundle()

    first = render_draft_markdown(bundle)
    second = render_draft_markdown(bundle)

    assert first == second
    assert first.startswith("# Candidate draft\n")
    assert "UNAPPROVED DRAFT" in first
    assert "DRAFT STATUS: POPULATED" in first
    assert "DRAFT STATUS: PARTIAL" in first
    assert "DRAFT STATUS: MISSING" in first
    assert "DRAFT STATUS: CONFLICTING" in first
    assert "DRAFT STATUS: NOT_APPLICABLE" in first
    assert "GAP-001" in first and "Q-001" in first
    assert "structured review metadata, not a source fact" in first
    assert "TBD" not in first


@pytest.mark.unit
def test_disposition_and_gap_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SourceDisposition.model_validate(
            {
                "source_span_id": "span-001",
                "action": "placed",
                "destination_section_ids": ["SEC-001"],
                "rationale": "valid rationale",
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        Gap.model_validate(
            {
                "gap_id": "GAP-001",
                "template_section_id": "SEC-001",
                "kind": "missing",
                "description": "missing evidence",
                "unexpected": True,
            }
        )


@pytest.mark.unit
def test_draft_sections_alias_is_accepted_without_changing_canonical_field() -> None:
    source = _bundle()
    payload = source.model_dump(mode="python")
    sections = payload.pop("template_sections")
    payload["draft_sections"] = sections

    rebuilt = TransformationBundle.model_validate(payload)

    assert rebuilt.draft_sections == rebuilt.template_sections
    assert "template_sections" in rebuilt.model_dump()


@pytest.mark.unit
def test_source_disposition_action_cardinality_is_strict() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        SourceDisposition(
            source_span_id="span-001",
            action="placed",
            rationale="missing destination",
        )
    with pytest.raises(ValidationError, match="at least two"):
        SourceDisposition(
            source_span_id="span-001",
            action="duplicated",
            destination_section_ids=["SEC-001"],
            rationale="only one destination",
        )
