"""Deterministic human-readable Markdown renderers for analysis artifacts."""

from __future__ import annotations

from collections.abc import Iterable

from document_enhancer.domain.analysis import (
    DiscoveryAnalysis,
    Finding,
    MacroAnalysis,
    RagReadinessAnalysis,
    SectionAnalysis,
)

from .models import FindingConflict, RankedFinding, SourceDispositionMap


def _text(value: object | None) -> str:
    if value is None or value == "":
        return "Not established"
    return str(value).replace("\n", " ").replace("|", "\\|").strip()


def _evidence(finding: Finding) -> str:
    if not finding.evidence:
        return _text(finding.requirement_id)
    return "; ".join(f"`{item.span_id}`: “{_text(item.quote)}”" for item in finding.evidence)


def _render_findings(findings: Iterable[Finding]) -> list[str]:
    values = list(findings)
    if not values:
        return ["No findings were returned."]
    lines = [
        "| ID | Severity | Type | Category | Evidence | Impact | Proposed disposition | Human answer |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for finding in values:
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{finding.finding_id}`",
                    finding.severity.value,
                    finding.finding_type.value,
                    _text(finding.category),
                    _evidence(finding),
                    _text(finding.impact),
                    _text(finding.proposed_disposition),
                    "blocking"
                    if finding.blocking
                    else ("yes" if finding.requires_human_answer else "no"),
                )
            )
            + " |"
        )
    return lines


def render_macro_markdown(analysis: MacroAnalysis) -> str:
    """Render macro conclusions and evidence without any model-authored Markdown."""

    lines = [
        "# Macro analysis",
        "",
        f"- Analysis ID: `{analysis.analysis_id}`",
        f"- Candidate document type: {_text(analysis.candidate_document_type.value if analysis.candidate_document_type else None)}",
        f"- Candidate confidence: {_text(analysis.candidate_confidence)}",
        f"- Purpose: {_text(analysis.purpose)}",
        f"- Audience: {_text(analysis.audience)}",
        f"- Owner: {_text(analysis.owner_id)}",
        f"- Authority: {_text(analysis.authority)}",
        f"- Lifecycle status: {_text(analysis.lifecycle_status)}",
        f"- Scope: {_text(analysis.scope)}",
        f"- Template fit: {_text(analysis.template_fit)}",
        f"- Alternative templates: {_text(', '.join(analysis.alternative_templates))}",
        "",
        "## Rubric scores",
        "",
    ]
    if analysis.rubric_scores:
        lines.extend(
            [
                "| Dimension | Score | Weight | Evidence | Explanation |",
                "|---|---:|---:|---|---|",
            ]
        )
        for score in analysis.rubric_scores:
            evidence = "; ".join(
                f"`{item.span_id}`: “{_text(item.quote)}”" for item in score.evidence
            )
            lines.append(
                f"| {_text(score.dimension)} | {score.score}/4 | {score.weight:g} | "
                f"{_text(evidence)} | {_text(score.explanation)} |"
            )
    else:
        lines.append("No rubric scores were returned.")
    lines.extend(["", "## Findings", "", *_render_findings(analysis.findings)])
    return "\n".join(lines).rstrip() + "\n"


def render_section_markdown(
    analysis: SectionAnalysis, disposition_map: SourceDispositionMap
) -> str:
    lines = [
        "# Section mapping",
        "",
        f"- Analysis ID: `{analysis.analysis_id}`",
        f"- Covered source spans: {len(disposition_map.dispositions)}/{len(disposition_map.authoritative_span_ids)}",
        "",
        "## Source-span dispositions",
        "",
        "| Source span | Target section(s) | Disposition | Rationale |",
        "|---|---|---|---|",
    ]
    for item in disposition_map.dispositions:
        targets = ", ".join(f"`{value}`" for value in item.target_section_ids) or "—"
        lines.append(
            f"| `{item.span_id}` | {targets} | {item.disposition.value} | {_text(item.rationale)} |"
        )
    lines.extend(["", "## Findings", "", *_render_findings(analysis.findings)])
    return "\n".join(lines).rstrip() + "\n"


def render_discovery_markdown(analysis: DiscoveryAnalysis) -> str:
    lines = [
        "# Process and methodology discovery",
        "",
        f"- Analysis ID: `{analysis.analysis_id}`",
        f"- Candidate objects: {len(analysis.objects)}",
        f"- Candidate relationships: {len(analysis.candidate_relationships)}",
        "",
        "## Candidate objects",
        "",
        "| ID | Type | Name | Source span | Authority | Review status |",
        "|---|---|---|---|---|---|",
    ]
    for item in analysis.objects:
        lines.append(
            f"| `{item.id}` | {item.entity_type.value} | {_text(item.name)} | "
            f"`{_text(item.provenance.source_span_id)}` | {item.provenance.authority.value} | "
            f"{item.provenance.review_status.value} |"
        )
    lines.extend(
        [
            "",
            "## Candidate relationships",
            "",
            "| ID | Source | Relationship | Target | Source span |",
            "|---|---|---|---|---|",
        ]
    )
    for item in analysis.candidate_relationships:
        lines.append(
            f"| `{item.id}` | `{item.source_id}` | {item.predicate.value} | "
            f"`{item.target_id}` | `{_text(item.provenance.source_span_id)}` |"
        )
    lines.extend(["", "## Findings", "", *_render_findings(analysis.findings)])
    return "\n".join(lines).rstrip() + "\n"


def render_rag_readiness_markdown(analysis: RagReadinessAnalysis) -> str:
    lines = [
        "# RAG-readiness analysis",
        "",
        f"- Analysis ID: `{analysis.analysis_id}`",
        f"- Undefined acronyms: {_text(', '.join(analysis.undefined_acronyms))}",
        f"- Vague references: {_text(', '.join(analysis.vague_references))}",
        f"- Missing IDs: {_text(', '.join(analysis.missing_ids))}",
        f"- Missing provenance: {_text(', '.join(analysis.missing_provenance))}",
        f"- Oversized sections: {_text(', '.join(analysis.oversized_sections))}",
        f"- Mixed-topic spans: {_text(', '.join(analysis.mixed_topic_spans))}",
        "",
        "## Candidate chunks",
        "",
        "| Chunk key | Section | Objects | Source spans | Rationale |",
        "|---|---|---|---|---|",
    ]
    for chunk in analysis.candidate_chunks:
        lines.append(
            f"| `{chunk.chunk_key}` | `{_text(chunk.section_id)}` | "
            f"{_text(', '.join(chunk.object_ids))} | {_text(', '.join(chunk.source_span_ids))} | "
            f"{_text(chunk.rationale)} |"
        )
    lines.extend(["", "## Findings", "", *_render_findings(analysis.findings)])
    return "\n".join(lines).rstrip() + "\n"


def render_synthesis_markdown(
    ranked_findings: tuple[RankedFinding, ...],
    conflicts: tuple[FindingConflict, ...],
) -> str:
    lines = [
        "# Synthesized findings",
        "",
        f"- Findings: {len(ranked_findings)}",
        f"- Preserved cross-reviewer conflicts: {len(conflicts)}",
        "",
        "## Priority order",
        "",
        "| Rank | Priority | Finding | Evidence | Impact |",
        "|---:|---|---|---|---|",
    ]
    for item in ranked_findings:
        lines.append(
            f"| {item.rank} | {item.priority} | `{item.finding.finding_id}` | "
            f"{_evidence(item.finding)} | {_text(item.finding.impact)} |"
        )
    lines.extend(["", "## Preserved conflicts", ""])
    if not conflicts:
        lines.append("No exact-evidence cross-reviewer conflicts were detected.")
    else:
        lines.extend(
            [
                "| Conflict | Analyses | Findings | Differing fields | Evidence signature |",
                "|---|---|---|---|---|",
            ]
        )
        for conflict in conflicts:
            lines.append(
                f"| `{conflict.conflict_id}` | {_text(', '.join(conflict.source_analysis_ids))} | "
                f"{_text(', '.join(conflict.finding_ids))} | "
                f"{_text(', '.join(conflict.differing_fields))} | "
                f"`{conflict.evidence_signature[:16]}` |"
            )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "render_discovery_markdown",
    "render_macro_markdown",
    "render_rag_readiness_markdown",
    "render_section_markdown",
    "render_synthesis_markdown",
]
