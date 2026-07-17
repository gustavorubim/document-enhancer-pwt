"""Deterministic review construction for the file-backed core workflow.

This module owns the review contract: rubric gaps, placeholders, flow
relationships, and provider-result promotion.  The runner only coordinates
artifacts and phase transitions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from .models import (
    Finding,
    FlowEdge,
    FlowNode,
    Question,
    ReviewReport,
    Section,
    SourceSpan,
)
from .recipes import Recipe

_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", re.IGNORECASE)
_FLOW_WORDS = re.compile(
    r"\b(?:first|then|next|after|before|when|if|until|owner|responsible|approve|review|submit|notify|escalat)\w*\b",
    re.IGNORECASE,
)


def normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def evidence_for_offset(blocks: tuple[Any, ...], offset: int) -> list[str]:
    for block in blocks:
        start = block.location.char_start or 0
        end = block.location.char_end or start
        if start <= offset <= end:
            return [block.span_id]
    return []


def bounded_batches(items: list[Section], *, size: int) -> list[list[Section]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    return [items[index : index + size] for index in range(0, len(items), size)]


def build_review(
    *,
    blocks: tuple[Any, ...],
    source_spans: list[SourceSpan],
    sections: list[Section],
    recipe: Recipe | None,
) -> ReviewReport:
    """Build macro, section, flow, rubric, and question views in one bundle."""

    spans = {block.span_id: block for block in blocks}
    source_text = "\n".join(block.text for block in blocks)
    findings: list[Finding] = []
    questions: list[Question] = []
    rubric_ids: list[str] = []
    if recipe:
        rubric_ids = [
            str(item["criterion_id"]) for item in recipe.rubric_criteria if item.get("criterion_id")
        ]
        present_titles = {normalise_title(item.title) for item in sections}
        for requirement in recipe.required_section_items:
            heading = str(requirement.get("heading") or requirement.get("id") or "")
            if not heading or normalise_title(heading) in present_titles:
                continue
            requirement_id = str(requirement.get("id") or "unknown")
            criteria = requirement.get("rubric_criteria") or []
            rubric_id = str(criteria[0]) if criteria else f"template.{requirement_id}"
            findings.append(
                Finding(
                    finding_id=f"finding-required-{requirement_id.lower()}",
                    scope="macro",
                    severity="blocker",
                    title=f"Required section missing: {heading}",
                    detail="The selected recipe marks this section as required, but no matching source heading was found.",
                    rubric_id=rubric_id,
                    recommendation="Add the section only when the document owner can provide evidence-backed content; otherwise record an explicit waiver.",
                )
            )
            questions.append(
                Question(
                    question_id=f"question-required-{requirement_id.lower()}",
                    prompt=f"Should the final document include the required section {heading!r}?",
                    reason="The selected recipe requires this section for a complete governed document.",
                )
            )
        lower_source = source_text.lower()
        for criterion in recipe.rubric_criteria:
            criterion_id = str(criterion.get("criterion_id") or "")
            evidence_terms = [
                str(item).lower() for item in (criterion.get("evidence") or []) if str(item).strip()
            ]
            if (
                not criterion_id
                or not evidence_terms
                or any(term in lower_source for term in evidence_terms)
            ):
                continue
            hard_blocker = bool(criterion.get("hard_blocker", False))
            findings.append(
                Finding(
                    finding_id=f"finding-rubric-{criterion_id.lower()}",
                    scope="macro",
                    severity="blocker" if hard_blocker else "warning",
                    title=f"Rubric evidence not found: {criterion_id}",
                    detail=str(
                        criterion.get("requirement")
                        or "Required rubric evidence is not visible in the source."
                    ),
                    rubric_id=criterion_id,
                    recommendation="Add source-backed evidence or record a reviewer-approved exception.",
                )
            )
            if hard_blocker:
                questions.append(
                    Question(
                        question_id=f"question-rubric-{criterion_id.lower()}",
                        prompt=f"Where is the evidence for rubric criterion {criterion_id}?",
                        reason="The selected rubric marks this criterion as a hard blocker.",
                    )
                )
    if not any(block.block_type == "heading" for block in blocks):
        findings.append(
            Finding(
                finding_id="finding-structure-001",
                scope="macro",
                severity="warning",
                title="Document has no explicit section headings",
                detail="The source can be reviewed, but section-level requirements and flow ownership are less reliable without headings.",
                rubric_id="structure.explicit_sections",
                evidence_span_ids=[item.span_id for item in source_spans[:3]],
                recommendation="Confirm the intended section boundaries before rewriting.",
            )
        )
        questions.append(
            Question(
                question_id="question-structure-001",
                prompt="What are the intended major sections for this document?",
                reason="A section map is required for section-by-section review and graph export.",
            )
        )
    for match_index, match in enumerate(_PLACEHOLDER_RE.finditer(source_text), start=1):
        findings.append(
            Finding(
                finding_id=f"finding-placeholder-{match_index:03d}",
                scope="section",
                severity="blocker",
                title="Unresolved placeholder",
                detail=f"The source contains the unresolved marker {match.group(0)!r}.",
                rubric_id="completeness.no_placeholders",
                evidence_span_ids=evidence_for_offset(blocks, match.start()),
                recommendation="Answer the corresponding reviewer question before rewrite.",
            )
        )
        questions.append(
            Question(
                question_id=f"question-placeholder-{match_index:03d}",
                prompt=f"What should replace {match.group(0)!r}?",
                reason="The placeholder would otherwise be promoted into the final document.",
            )
        )
    for section in sections:
        text = " ".join(spans[span_id].text for span_id in section.span_ids if span_id in spans)
        if text and not _FLOW_WORDS.search(text):
            findings.append(
                Finding(
                    finding_id=f"finding-flow-{section.section_id}",
                    scope="flow",
                    severity="warning",
                    title=f"Flow is implicit in {section.title}",
                    detail="No clear sequence, owner, decision, or escalation signal was found by the deterministic pass.",
                    rubric_id="flow.explicit_steps",
                    section_id=section.section_id,
                    evidence_span_ids=section.span_ids[:3],
                    recommendation="Add explicit actors, transitions, and decision points if this section describes a process.",
                )
            )
        if not recipe:
            continue
        lower_section = text.lower()
        for criterion in recipe.rubric_criteria:
            criterion_id = str(criterion.get("criterion_id") or "")
            evidence_terms = [
                str(item).lower() for item in (criterion.get("evidence") or []) if str(item).strip()
            ]
            if (
                not criterion_id
                or not evidence_terms
                or any(term in lower_section for term in evidence_terms)
            ):
                continue
            findings.append(
                Finding(
                    finding_id=f"finding-section-{section.section_id}-{criterion_id.lower()}",
                    scope="section",
                    severity="blocker" if bool(criterion.get("hard_blocker", False)) else "warning",
                    title=f"Section lacks rubric evidence: {criterion_id}",
                    detail=f"No configured evidence term for {criterion_id} was found in {section.title}.",
                    rubric_id=criterion_id,
                    section_id=section.section_id,
                    evidence_span_ids=section.span_ids[:3],
                    recommendation="Add only source-backed detail or leave the gap visible for reviewer steering.",
                )
            )
    flow_nodes, flow_edges = build_flow_graph(sections, spans)
    return ReviewReport(
        summary=(
            f"Reviewed {len(sections)} section(s), produced {len(findings)} finding(s), "
            f"and identified {len(questions)} question(s) requiring reviewer input."
        ),
        recipe_id=recipe.recipe_id if recipe else "heuristic-default",
        rubric_ids=rubric_ids,
        sections=sections,
        flow_nodes=flow_nodes,
        flow_edges=flow_edges,
        findings=findings,
        questions=questions,
        mermaid=render_mermaid(flow_nodes, flow_edges),
    )


def build_flow_graph(
    sections: list[Section], spans: Mapping[str, Any]
) -> tuple[list[FlowNode], list[FlowEdge]]:
    nodes: list[FlowNode] = []
    section_text: dict[str, str] = {}
    for section in sections:
        text = " ".join(
            str(getattr(spans.get(span_id), "text", ""))
            for span_id in section.span_ids
            if span_id in spans
        ).strip()
        section_text[section.section_id] = text
        node_type: Literal["section", "decision", "step"] = (
            "decision"
            if re.search(
                r"\b(?:if|unless|when|decision|approve|reject|else|branch)\b",
                text,
                re.IGNORECASE,
            )
            else "section"
        )
        nodes.append(
            FlowNode(
                node_id=section.section_id,
                label=section.title,
                section_id=section.section_id,
                node_type=node_type,
            )
        )
    title_tokens = {section.section_id: normalise_title(section.title) for section in sections}
    edges: list[FlowEdge] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(
        source: str,
        target: str,
        relation: Literal["sequence", "reference", "branch", "escalation"],
        evidence: list[str],
    ) -> None:
        if source == target or not evidence:
            return
        key = (source, target, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            FlowEdge(
                edge_id=f"flow-{source}-{target}-{relation}",
                source=source,
                target=target,
                relation=relation,
                evidence_span_ids=list(dict.fromkeys(evidence)),
            )
        )

    for index, section in enumerate(sections):
        text = section_text[section.section_id]
        lower_text = text.lower()
        evidence = section.span_ids[:3]
        normalized_text = normalise_title(text)
        for target in sections:
            if target.section_id == section.section_id:
                continue
            title = title_tokens[target.section_id]
            if title and len(title) >= 3 and title in normalized_text:
                add_edge(section.section_id, target.section_id, "reference", evidence)
        if index + 1 >= len(sections):
            continue
        target = sections[index + 1]
        if not re.search(
            r"\b(?:first|then|next|after(?:wards)?|before|until|proceed|continue|follow|submit|notify|review|approve)\w*\b",
            lower_text,
        ):
            continue
        if re.search(r"\b(?:escalat|raise to|send to)\w*\b", lower_text):
            relation: Literal["sequence", "reference", "branch", "escalation"] = "escalation"
        elif re.search(r"\b(?:if|unless|when|else|otherwise|branch)\b", lower_text):
            relation = "branch"
        else:
            relation = "sequence"
        add_edge(section.section_id, target.section_id, relation, evidence)
    return nodes, edges


def render_mermaid(nodes: list[FlowNode], edges: list[FlowEdge]) -> str:
    lines = ["flowchart TD"]
    for node in nodes:
        label = re.sub(r"[\[\]{}()\"`]", "", node.label).strip() or "Section"
        shape = f'{{"{label}"}}' if node.node_type == "decision" else f'["{label}"]'
        lines.append(f"  {node.node_id}{shape}")
    for edge in edges:
        if edge.relation == "reference":
            lines.append(f"  {edge.source} -.-> {edge.target}")
        elif edge.relation == "branch":
            lines.append(f"  {edge.source} -->|branch| {edge.target}")
        elif edge.relation == "escalation":
            lines.append(f"  {edge.source} -->|escalate| {edge.target}")
        else:
            lines.append(f"  {edge.source} --> {edge.target}")
    return "\n".join(lines) + "\n"


def merge_provider_review(
    base: ReviewReport,
    candidate: ReviewReport,
    *,
    allowed_span_ids: set[str],
) -> ReviewReport:
    """Promote provider judgments only after deterministic evidence filtering."""

    seen_findings = {item.finding_id for item in base.findings}
    findings = list(base.findings)
    for finding in candidate.findings:
        evidence = [item for item in finding.evidence_span_ids if item in allowed_span_ids]
        if finding.evidence_span_ids and not evidence:
            continue
        finding = finding.model_copy(update={"evidence_span_ids": evidence})
        if finding.finding_id in seen_findings:
            finding = finding.model_copy(update={"finding_id": f"llm-{finding.finding_id}"})
        seen_findings.add(finding.finding_id)
        findings.append(finding)
    seen_questions = {item.question_id for item in base.questions}
    questions = list(base.questions)
    for question in candidate.questions:
        if question.question_id in seen_questions:
            question = question.model_copy(update={"question_id": f"llm-{question.question_id}"})
        seen_questions.add(question.question_id)
        questions.append(question)
    section_ids = {item.section_id for item in base.sections}
    seen_edges = {(item.source, item.target, item.relation) for item in base.flow_edges}
    flow_edges = list(base.flow_edges)
    for edge in candidate.flow_edges:
        evidence = [item for item in edge.evidence_span_ids if item in allowed_span_ids]
        key = (edge.source, edge.target, edge.relation)
        if (
            edge.source not in section_ids
            or edge.target not in section_ids
            or not evidence
            or key in seen_edges
        ):
            continue
        flow_edges.append(
            edge.model_copy(
                update={
                    "edge_id": f"llm-{edge.edge_id}",
                    "evidence_span_ids": list(dict.fromkeys(evidence)),
                }
            )
        )
        seen_edges.add(key)
    return base.model_copy(
        update={
            "summary": f"{base.summary} Provider enrichment added {len(candidate.findings)} finding(s) and {len(candidate.questions)} question(s).",
            "findings": findings,
            "questions": questions,
            "flow_edges": flow_edges,
            "mermaid": render_mermaid(base.flow_nodes, flow_edges),
        }
    )


__all__ = [
    "bounded_batches",
    "build_flow_graph",
    "build_review",
    "evidence_for_offset",
    "merge_provider_review",
    "normalise_title",
    "render_mermaid",
]
