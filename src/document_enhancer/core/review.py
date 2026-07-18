"""Deterministic review construction for the file-backed core workflow.

This module owns the review contract: rubric gaps, placeholders, flow
relationships, section assessments, dual Mermaid, and provider-result promotion.
The runner only coordinates artifacts and phase transitions.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from .models import (
    AssessmentStatus,
    Finding,
    FlowEdge,
    FlowNode,
    Question,
    ReviewReport,
    Section,
    SectionAssessment,
    SourceSpan,
)
from .recipes import Recipe

_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", re.IGNORECASE)
_FLOW_WORDS = re.compile(
    r"\b(?:first|then|next|after|before|when|if|until|owner|responsible|approve|review|submit|notify|escalat)\w*\b",
    re.IGNORECASE,
)
_PROCESS_TYPES = frozenset({"process", "desktop_procedure"})
_TITLE_ALIASES = {
    "definitions and controlled terminology": {"definitions"},
    "preconditions triggers and scheduling": {"preconditions triggers and inputs"},
    "inputs and entry criteria": {"preconditions triggers and inputs"},
    "related requirements policies standards and documents": {"appendix a source inventory"},
}


def normalise_title(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"^\d+(?: \d+)*\s+", "", normalized)


def title_matches(requirement: str, candidate: str) -> bool:
    """Match a recipe heading to a numbered, compact, or combined source heading."""

    expected = normalise_title(requirement)
    actual = normalise_title(candidate)
    if not expected or not actual:
        return False
    if expected == actual or actual in _TITLE_ALIASES.get(expected, set()):
        return True
    expected_words = set(expected.split())
    actual_words = set(actual.split())
    shared = expected_words & actual_words
    return len(shared) >= 2 and len(shared) / min(len(expected_words), len(actual_words)) >= 0.75


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


def _criteria_by_id(recipe: Recipe) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("criterion_id")): item
        for item in recipe.rubric_criteria
        if item.get("criterion_id")
    }


def _match_requirement(recipe: Recipe, section: Section) -> dict[str, Any] | None:
    for requirement in recipe.required_sections:
        heading = str(requirement.get("heading") or requirement.get("id") or "")
        if heading and title_matches(heading, section.title):
            return requirement
    return None


def _criterion_ids_for_requirement(recipe: Recipe, requirement: dict[str, Any]) -> list[str]:
    requirement_id = str(requirement.get("id") or "")
    mapped = list(recipe.criteria_for_requirement(requirement_id))
    if mapped:
        return mapped
    raw = requirement.get("rubric_criteria") or []
    return [str(item) for item in raw if str(item).strip()]


def _evidence_present(text: str, criterion: dict[str, Any]) -> bool:
    terms = [str(item).lower() for item in (criterion.get("evidence") or []) if str(item).strip()]
    if not terms:
        requirement = str(criterion.get("requirement") or "").lower()
        tokens = [token for token in re.findall(r"[a-z0-9]{4,}", requirement)]
        return bool(tokens) and any(token in text.lower() for token in tokens[:4])
    return any(term in text.lower() for term in terms)


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
    assessments: list[SectionAssessment] = []
    rubric_ids: list[str] = []
    criteria_index = _criteria_by_id(recipe) if recipe else {}
    if recipe:
        rubric_ids = [
            str(item["criterion_id"]) for item in recipe.rubric_criteria if item.get("criterion_id")
        ]
        for requirement in recipe.required_section_items:
            heading = str(requirement.get("heading") or requirement.get("id") or "")
            if not heading or any(title_matches(heading, item.title) for item in sections):
                continue
            requirement_id = str(requirement.get("id") or "unknown")
            criterion_ids = _criterion_ids_for_requirement(recipe, requirement)
            rubric_id = criterion_ids[0] if criterion_ids else f"template.{requirement_id}"
            findings.append(
                Finding(
                    finding_id=f"finding-required-{requirement_id.lower()}",
                    scope="macro",
                    severity="blocker",
                    title=f"Required section missing: {heading}",
                    detail=(
                        "The selected recipe marks this section as required, but no matching "
                        "source heading was found."
                    ),
                    rubric_id=rubric_id,
                    recommendation=(
                        "Add the section only when the document owner can provide evidence-backed "
                        "content; otherwise record an explicit waiver."
                    ),
                    disposition="missing",
                )
            )
            questions.append(
                Question(
                    question_id=f"question-required-{requirement_id.lower()}",
                    prompt=f"Should the final document include the required section {heading!r}?",
                    reason="The selected recipe requires this section for a complete governed document.",
                )
            )
        if "conflicting draft statements" in source_text.lower():
            questions.append(
                Question(
                    question_id="question-open-points-001",
                    prompt=(
                        "How should the final document handle the pilot-approval conflicts listed "
                        "in the open-points section?"
                    ),
                    reason=(
                        "The source explicitly identifies conflicting operational values that require "
                        "owner steering rather than automatic resolution."
                    ),
                )
            )
    if not any(block.block_type == "heading" for block in blocks):
        findings.append(
            Finding(
                finding_id="finding-structure-001",
                scope="macro",
                severity="warning",
                title="Document has no explicit section headings",
                detail=(
                    "The source can be reviewed, but section-level requirements and flow ownership "
                    "are less reliable without headings."
                ),
                rubric_id="structure.explicit_sections",
                evidence_span_ids=[item.span_id for item in source_spans[:3]],
                recommendation="Confirm the intended section boundaries before rewriting.",
                disposition="improve",
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
                disposition="missing",
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
        requirement = _match_requirement(recipe, section) if recipe else None
        criterion_ids = (
            _criterion_ids_for_requirement(recipe, requirement) if recipe and requirement else []
        )
        present: list[str] = []
        missing: list[str] = []
        improve_notes: list[str] = []
        for criterion_id in criterion_ids:
            criterion = criteria_index.get(criterion_id)
            if criterion is None:
                continue
            if _evidence_present(text, criterion):
                present.append(criterion_id)
            else:
                missing.append(criterion_id)
                hard_blocker = bool(criterion.get("hard_blocker", False))
                findings.append(
                    Finding(
                        finding_id=f"finding-section-{section.section_id}-{criterion_id.lower()}",
                        scope="section",
                        severity="blocker" if hard_blocker else "warning",
                        title=f"Section lacks rubric evidence: {criterion_id}",
                        detail=str(
                            criterion.get("requirement")
                            or f"No configured evidence for {criterion_id} in {section.title}."
                        ),
                        rubric_id=criterion_id,
                        section_id=section.section_id,
                        evidence_span_ids=section.span_ids[:3],
                        recommendation=(
                            "Add only source-backed detail or leave the gap visible for reviewer "
                            "steering."
                        ),
                        disposition="missing" if hard_blocker else "improve",
                    )
                )
                if hard_blocker:
                    questions.append(
                        Question(
                            question_id=(
                                f"question-section-{section.section_id}-{criterion_id.lower()}"
                            ),
                            prompt=(
                                f"Where is the evidence for rubric criterion {criterion_id} in "
                                f"{section.title!r}?"
                            ),
                            reason="The selected rubric marks this criterion as a hard blocker.",
                            section_id=section.section_id,
                        )
                    )
        if recipe and requirement and not criterion_ids:
            improve_notes.append("No rubric criteria are mapped for this requirement.")
        if recipe and not requirement:
            improve_notes.append("Section title does not match a recipe requirement heading.")
        if (
            text
            and not _FLOW_WORDS.search(text)
            and recipe
            and recipe.document_type in _PROCESS_TYPES
        ):
            improve_notes.append("No explicit sequence, owner, decision, or escalation signal.")
            findings.append(
                Finding(
                    finding_id=f"finding-flow-{section.section_id}",
                    scope="flow",
                    severity="warning",
                    title=f"Flow is implicit in {section.title}",
                    detail=(
                        "No clear sequence, owner, decision, or escalation signal was found by the "
                        "deterministic pass."
                    ),
                    rubric_id="flow.explicit_steps",
                    section_id=section.section_id,
                    evidence_span_ids=section.span_ids[:3],
                    recommendation=(
                        "Add explicit actors, transitions, and decision points if this section "
                        "describes a process."
                    ),
                    disposition="improve",
                )
            )
        status: AssessmentStatus
        if missing and not present:
            status = "missing"
        elif missing or improve_notes:
            status = "improve"
        else:
            status = "correct"
        assessments.append(
            SectionAssessment(
                section_id=section.section_id,
                title=section.title,
                requirement_id=str(requirement.get("id")) if requirement else None,
                status=status,
                criterion_ids=criterion_ids,
                evidence_span_ids=section.span_ids[:5],
                what_is_correct=(
                    f"Evidence present for: {', '.join(present)}."
                    if present
                    else ("Section content is present." if text.strip() else "")
                ),
                what_is_missing=(f"Missing evidence for: {', '.join(missing)}." if missing else ""),
                what_to_improve="; ".join(improve_notes),
            )
        )

    process_applicable = _process_applicable(recipe, sections, spans)
    flow_nodes, flow_edges = build_flow_graph(sections, spans)
    proposed_nodes, proposed_edges = build_proposed_flow(
        sections=sections,
        spans=spans,
        recipe=recipe,
        assessments=assessments,
        process_applicable=process_applicable,
    )
    if process_applicable:
        for edge in proposed_edges:
            if any(
                item.source == edge.source
                and item.target == edge.target
                and item.relation == edge.relation
                for item in flow_edges
            ):
                continue
            findings.append(
                Finding(
                    finding_id=f"finding-flow-gap-{edge.edge_id}",
                    scope="flow",
                    severity="warning",
                    title=f"Proposed transition missing from source: {edge.source} → {edge.target}",
                    detail=(
                        "The recipe-backed proposed process includes this transition, but the "
                        "inferred source graph does not."
                    ),
                    rubric_id="flow.complete_transitions",
                    section_id=edge.source if edge.source.startswith("section-") else None,
                    evidence_span_ids=list(edge.evidence_span_ids[:3]),
                    recommendation="Confirm whether the transition should be documented or waived.",
                    disposition="improve",
                )
            )
    inferred = (
        render_mermaid(flow_nodes, flow_edges)
        if process_applicable
        else 'flowchart TD\n  note["No process flow applicable for this document type"]\n'
    )
    proposed = render_mermaid(proposed_nodes, proposed_edges) if process_applicable else inferred
    return ReviewReport(
        summary=(
            f"Reviewed {len(sections)} section(s), produced {len(assessments)} assessment(s), "
            f"{len(findings)} finding(s), and {len(questions)} question(s) requiring reviewer input."
        ),
        recipe_id=recipe.recipe_id if recipe else "heuristic-default",
        rubric_ids=rubric_ids,
        sections=sections,
        section_assessments=assessments,
        flow_nodes=flow_nodes,
        flow_edges=flow_edges,
        proposed_flow_nodes=proposed_nodes,
        proposed_flow_edges=proposed_edges,
        findings=findings,
        questions=questions,
        process_applicable=process_applicable,
        mermaid=inferred,
        inferred_mermaid=inferred,
        proposed_mermaid=proposed,
    )


def _process_applicable(
    recipe: Recipe | None, sections: list[Section], spans: Mapping[str, Any]
) -> bool:
    if recipe and recipe.document_type in _PROCESS_TYPES:
        return True
    if recipe and recipe.document_type in {"methodology", "standard"}:
        return False
    joined = " ".join(
        str(getattr(spans.get(span_id), "text", ""))
        for section in sections
        for span_id in section.span_ids
    ).lower()
    return bool(re.search(r"\b(?:process step|decision rule|escalat|workflow)\b", joined))


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
            else "step"
            if re.search(r"\b(?:step|action|perform|submit|notify)\b", text, re.IGNORECASE)
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


def build_proposed_flow(
    *,
    sections: list[Section],
    spans: Mapping[str, Any],
    recipe: Recipe | None,
    assessments: list[SectionAssessment],
    process_applicable: bool,
) -> tuple[list[FlowNode], list[FlowEdge]]:
    """Build a recipe-backed proposed process graph for process document types."""

    if not process_applicable:
        return [], []
    inferred_nodes, inferred_edges = build_flow_graph(sections, spans)
    if not recipe:
        return inferred_nodes, inferred_edges
    nodes: list[FlowNode] = []
    edges: list[FlowEdge] = []
    ordered = sorted(
        (
            item
            for item in recipe.required_section_items
            if any(
                hook in {"ProcessStep", "Decision", "Trigger", "EscalationPath", "Process"}
                for hook in (item.get("ontology_hooks") or [])
            )
            or "step" in str(item.get("id") or "").lower()
            or "decision" in str(item.get("id") or "").lower()
            or "exception" in str(item.get("id") or "").lower()
            or "precondition" in str(item.get("id") or "").lower()
        ),
        key=lambda item: int(item.get("order") or 0),
    )
    if not ordered:
        ordered = sorted(
            recipe.required_section_items, key=lambda item: int(item.get("order") or 0)
        )[:8]
    assessment_by_requirement = {
        item.requirement_id: item for item in assessments if item.requirement_id
    }
    previous_id: str | None = None
    for item in ordered:
        requirement_id = str(item.get("id") or item.get("heading") or "section")
        heading = str(item.get("heading") or requirement_id)
        matched = next(
            (section for section in sections if title_matches(heading, section.title)),
            None,
        )
        node_id = matched.section_id if matched else f"proposed-{requirement_id.lower()}"
        assessment = assessment_by_requirement.get(requirement_id)
        hooks = [str(hook) for hook in (item.get("ontology_hooks") or [])]
        node_type: Literal["section", "decision", "step"] = (
            "decision"
            if "Decision" in hooks
            else "step"
            if "ProcessStep" in hooks or "Trigger" in hooks
            else "section"
        )
        label = (
            heading if assessment is None or assessment.status != "missing" else f"{heading} (gap)"
        )
        nodes.append(
            FlowNode(
                node_id=node_id,
                label=label,
                section_id=matched.section_id if matched else node_id,
                node_type=node_type,
            )
        )
        if previous_id is not None:
            evidence = list(matched.span_ids[:3]) if matched else []
            edges.append(
                FlowEdge(
                    edge_id=f"proposed-{previous_id}-{node_id}-sequence",
                    source=previous_id,
                    target=node_id,
                    relation="sequence",
                    evidence_span_ids=evidence,
                )
            )
        previous_id = node_id
    # Keep inferred edges that remain valid in the proposed node set.
    node_ids = {item.node_id for item in nodes}
    for edge in inferred_edges:
        if edge.source in node_ids and edge.target in node_ids:
            edges.append(edge)
    return nodes, edges


def render_mermaid(nodes: list[FlowNode], edges: list[FlowEdge]) -> str:
    lines = ["flowchart TD"]
    if not nodes:
        lines.append('  empty["No flow nodes"]')
        return "\n".join(lines) + "\n"
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


def _label_for_node(review: ReviewReport, node_id: str) -> str:
    for node in (*review.flow_nodes, *review.proposed_flow_nodes):
        if node.node_id == node_id:
            return node.label
    for section in review.sections:
        if section.section_id == node_id:
            return section.title
    return node_id


def _assessment_counts(review: ReviewReport) -> dict[str, int]:
    counts = {"correct": 0, "missing": 0, "improve": 0}
    for item in review.section_assessments:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def explain_flow_adjustments(review: ReviewReport) -> list[str]:
    """Explain why the proposed diagram differs from the inferred source diagram."""

    if not review.process_applicable:
        return [
            "No process-flow adjustments were made because this document type does not require "
            "a process diagram."
        ]
    inferred_nodes = {item.node_id: item for item in review.flow_nodes}
    proposed_nodes = {item.node_id: item for item in review.proposed_flow_nodes}
    inferred_edges = {(item.source, item.target, item.relation): item for item in review.flow_edges}
    proposed_edges = {
        (item.source, item.target, item.relation): item for item in review.proposed_flow_edges
    }
    reasons: list[str] = []
    for node_id, node in proposed_nodes.items():
        if node_id not in inferred_nodes:
            reasons.append(
                f"Added proposed node `{node.label}` (`{node_id}`, type `{node.node_type}`) "
                "because the recipe marks this process-relevant section as required even when "
                "the inferred source graph did not treat it as a primary flow node."
            )
            continue
        if "(gap)" in node.label.lower() or node.label.endswith(" gap"):
            reasons.append(
                f"Marked `{_label_for_node(review, node_id)}` as a gap in the proposed diagram "
                "because section assessment or rubric evidence indicates the source content is "
                "incomplete for governed process execution."
            )
    for node_id, node in inferred_nodes.items():
        if node_id not in proposed_nodes:
            reasons.append(
                f"Omitted inferred node `{node.label}` (`{node_id}`) from the proposed process "
                "because it is not part of the recipe-backed executable process spine "
                "(for example governance, definitions, appendices, or non-step sections)."
            )
    for key, edge in proposed_edges.items():
        if key in inferred_edges:
            continue
        source = _label_for_node(review, edge.source)
        target = _label_for_node(review, edge.target)
        evidence = (
            f" Evidence spans: {', '.join(edge.evidence_span_ids)}."
            if edge.evidence_span_ids
            else " No direct source-span evidence; this transition is recipe-derived."
        )
        reasons.append(
            f"Added proposed `{edge.relation}` transition from **{source}** to **{target}** "
            f"to restore the governed process sequence expected by the selected recipe.{evidence}"
        )
    for key, edge in inferred_edges.items():
        if key in proposed_edges:
            continue
        if edge.source not in proposed_nodes or edge.target not in proposed_nodes:
            continue
        source = _label_for_node(review, edge.source)
        target = _label_for_node(review, edge.target)
        reasons.append(
            f"Did not promote inferred `{edge.relation}` transition from **{source}** to "
            f"**{target}** into the proposed spine because it conflicts with or is redundant to "
            "the recipe-backed sequence."
        )
    for finding in review.findings:
        if finding.scope != "flow":
            continue
        recommendation = finding.recommendation or "Confirm with the process owner before rewrite."
        reasons.append(
            f"Flow finding `{finding.finding_id}` ({finding.severity}): {finding.title}. "
            f"{finding.detail} Recommended action: {recommendation}"
        )
    if not reasons:
        reasons.append(
            "The inferred and proposed diagrams already agree on the executable process spine; "
            "no structural adjustments were required."
        )
    return reasons


def render_macro_markdown(review: ReviewReport) -> str:
    counts = _assessment_counts(review)
    macro = [item for item in review.findings if item.scope == "macro"]
    lines = [
        "# Macro review",
        "",
        "## Executive summary",
        "",
        review.summary,
        "",
        f"Recipe: `{review.recipe_id}`",
        "",
        "This macro report explains document-level readiness against the selected rubric and "
        "template. Section-level detail lives in `sections.md`; process-flow analysis lives in "
        "`flow.md`.",
        "",
        "## Readiness snapshot",
        "",
        f"- Sections assessed: {len(review.section_assessments)}",
        f"- Correct: {counts.get('correct', 0)}",
        f"- Improve: {counts.get('improve', 0)}",
        f"- Missing: {counts.get('missing', 0)}",
        f"- Findings: {len(review.findings)} "
        f"(macro={len(macro)}, "
        f"section={sum(1 for item in review.findings if item.scope == 'section')}, "
        f"flow={sum(1 for item in review.findings if item.scope == 'flow')})",
        f"- Blocking questions: {sum(1 for item in review.questions if item.blocking)}",
        f"- Process flow applicable: {'yes' if review.process_applicable else 'no'}",
        "",
        "## Rubric criteria in scope",
        "",
    ]
    if review.rubric_ids:
        lines.extend(f"- `{item}`" for item in review.rubric_ids)
    else:
        lines.append("No rubric criteria were loaded for this run.")
    lines.extend(["", "## Macro findings", ""])
    if not macro:
        lines.extend(
            [
                "No document-level macro findings were raised.",
                "",
                "That does not mean every section is complete. Review `sections.md` for "
                "per-section correct / missing / improve outcomes.",
            ]
        )
    for finding in macro:
        lines.extend(
            [
                f"### {finding.title}",
                "",
                f"- Finding ID: `{finding.finding_id}`",
                f"- Severity: **{finding.severity}**",
                f"- Disposition: `{finding.disposition or 'n/a'}`",
                f"- Rubric: `{finding.rubric_id}`",
                f"- Evidence spans: {', '.join(finding.evidence_span_ids) or 'none'}",
                "",
                finding.detail,
                "",
            ]
        )
        if finding.recommendation:
            lines.extend([f"**Recommendation:** {finding.recommendation}", ""])
    lines.extend(["", "## Questions requiring human judgment", ""])
    if not review.questions:
        lines.append("No blocking questions. The run can continue once rewrite is approved.")
    for question in review.questions:
        lines.extend(
            [
                f"### `{question.question_id}`",
                "",
                f"- Blocking: {'yes' if question.blocking else 'no'}",
                f"- Section: `{question.section_id or 'document'}`",
                "",
                f"**Question:** {question.prompt}",
                "",
                f"**Why this was asked:** {question.reason}",
                "",
            ]
        )
    lines.extend(
        [
            "## Next step",
            "",
            "Edit `decisions.yaml`, keep `approve_rewrite: true`, then run "
            "`docenhance continue <run-id>`.",
            "",
        ]
    )
    return "\n".join(lines)


def render_sections_markdown(review: ReviewReport) -> str:
    counts = _assessment_counts(review)
    findings_by_section: dict[str, list[Finding]] = {}
    for finding in review.findings:
        if finding.section_id:
            findings_by_section.setdefault(finding.section_id, []).append(finding)
    lines = [
        "# Section review",
        "",
        "## How to read this report",
        "",
        "Each section is assessed as **correct**, **missing**, or **improve** against the "
        "criteria mapped from the selected recipe. Correct means the linked evidence terms or "
        "requirement signals were present. Missing means required evidence was not found. "
        "Improve means the section exists but needs clearer ownership, transitions, or "
        "completeness before rewrite.",
        "",
        "## Snapshot",
        "",
        f"- Correct: {counts.get('correct', 0)}",
        f"- Improve: {counts.get('improve', 0)}",
        f"- Missing: {counts.get('missing', 0)}",
        "",
    ]
    if not review.section_assessments:
        lines.append("No section assessments were produced.")
        return "\n".join(lines) + "\n"
    for item in review.section_assessments:
        lines.extend(
            [
                f"## {item.title}",
                "",
                f"- Status: **{item.status}**",
                f"- Section ID: `{item.section_id}`",
                f"- Recipe requirement: `{item.requirement_id or 'unmapped'}`",
                f"- Linked criteria: {', '.join(f'`{cid}`' for cid in item.criterion_ids) or 'none'}",
                f"- Evidence spans reviewed: {', '.join(item.evidence_span_ids) or 'none'}",
                "",
                "### What is correct",
                "",
                item.what_is_correct or "No affirmative evidence was recorded for this section.",
                "",
                "### What is missing",
                "",
                item.what_is_missing or "No missing rubric evidence was recorded for this section.",
                "",
                "### What should be improved",
                "",
                item.what_to_improve or "No improvement notes were recorded for this section.",
                "",
            ]
        )
        related = findings_by_section.get(item.section_id, [])
        if related:
            lines.extend(["### Related findings", ""])
            for finding in related:
                lines.extend(
                    [
                        f"- **{finding.severity}** `{finding.finding_id}` "
                        f"({finding.disposition or 'n/a'}): {finding.title}",
                        f"  - {finding.detail}",
                    ]
                )
                if finding.recommendation:
                    lines.append(f"  - Recommendation: {finding.recommendation}")
            lines.append("")
    return "\n".join(lines)


def render_flow_markdown(review: ReviewReport) -> str:
    lines = [
        "# Process-flow review",
        "",
        "## Summary",
        "",
        (
            "This document is treated as a process. The inferred diagram is built from source "
            "sequence, decision, escalation, and reference language. The proposed diagram is the "
            "recipe-backed executable spine after gaps and non-process sections are adjusted."
            if review.process_applicable
            else "No process flow is applicable for this document type. The diagrams below record "
            "that conclusion explicitly so reviewers do not infer a fake process."
        ),
        "",
        "Standalone Mermaid sources are also written to:",
        "",
        "- `review/flow.inferred.mmd`",
        "- `review/flow.proposed.mmd`",
        "",
        "## Inferred process (from source)",
        "",
        "```mermaid",
        review.inferred_mermaid.rstrip(),
        "```",
        "",
        "### Inferred graph inventory",
        "",
        f"- Nodes: {len(review.flow_nodes)}",
        f"- Edges: {len(review.flow_edges)}",
        "",
    ]
    if review.flow_nodes:
        lines.append("Nodes:")
        lines.append("")
        for node in review.flow_nodes:
            lines.append(f"- `{node.node_id}` ({node.node_type}): {node.label}")
        lines.append("")
    if review.flow_edges:
        lines.append("Edges:")
        lines.append("")
        for edge in review.flow_edges:
            evidence = (
                f"; evidence={', '.join(edge.evidence_span_ids)}" if edge.evidence_span_ids else ""
            )
            lines.append(f"- `{edge.source}` -{edge.relation}-> `{edge.target}`{evidence}")
        lines.append("")
    lines.extend(
        [
            "## Proposed / suggested process",
            "",
            "```mermaid",
            review.proposed_mermaid.rstrip(),
            "```",
            "",
            "### Proposed graph inventory",
            "",
            f"- Nodes: {len(review.proposed_flow_nodes)}",
            f"- Edges: {len(review.proposed_flow_edges)}",
            "",
        ]
    )
    if review.proposed_flow_nodes:
        lines.append("Nodes:")
        lines.append("")
        for node in review.proposed_flow_nodes:
            lines.append(f"- `{node.node_id}` ({node.node_type}): {node.label}")
        lines.append("")
    if review.proposed_flow_edges:
        lines.append("Edges:")
        lines.append("")
        for edge in review.proposed_flow_edges:
            evidence = (
                f"; evidence={', '.join(edge.evidence_span_ids)}"
                if edge.evidence_span_ids
                else "; recipe-derived"
            )
            lines.append(f"- `{edge.source}` -{edge.relation}-> `{edge.target}`{evidence}")
        lines.append("")
    lines.extend(
        [
            "## Why the proposed diagram was adjusted",
            "",
            "Each bullet explains a concrete difference between the inferred source diagram and "
            "the suggested process diagram.",
            "",
        ]
    )
    for reason in explain_flow_adjustments(review):
        lines.append(f"- {reason}")
    lines.extend(["", "## Flow findings", ""])
    flow_findings = [item for item in review.findings if item.scope == "flow"]
    if not flow_findings:
        lines.append("No additional flow findings beyond the adjustment notes above.")
    for finding in flow_findings:
        lines.extend(
            [
                f"### {finding.title}",
                "",
                f"- Finding ID: `{finding.finding_id}`",
                f"- Severity: **{finding.severity}**",
                f"- Disposition: `{finding.disposition or 'n/a'}`",
                f"- Section: `{finding.section_id or 'n/a'}`",
                f"- Evidence spans: {', '.join(finding.evidence_span_ids) or 'none'}",
                "",
                finding.detail,
                "",
            ]
        )
        if finding.recommendation:
            lines.extend([f"**Recommendation:** {finding.recommendation}", ""])
    return "\n".join(lines)


def render_review_index_markdown(review: ReviewReport) -> str:
    counts = _assessment_counts(review)
    return (
        "# Review index\n\n"
        f"{review.summary}\n\n"
        "## Specialist reports\n\n"
        "- [Macro report](macro.md) — document-level rubric readiness and questions\n"
        "- [Section report](sections.md) — correct / missing / improve for every section\n"
        "- [Flow report](flow.md) — inferred Mermaid, proposed Mermaid, and adjustment reasoning\n\n"
        "## Machine artifacts\n\n"
        "- [Inferred Mermaid](flow.inferred.mmd)\n"
        "- [Proposed Mermaid](flow.proposed.mmd)\n"
        "- [Decisions](decisions.yaml)\n"
        "- [Review JSON](review.json)\n\n"
        "## Snapshot\n\n"
        f"- Correct sections: {counts.get('correct', 0)}\n"
        f"- Improve sections: {counts.get('improve', 0)}\n"
        f"- Missing sections: {counts.get('missing', 0)}\n"
        f"- Process applicable: {'yes' if review.process_applicable else 'no'}\n"
        f"- Blocking questions: {sum(1 for item in review.questions if item.blocking)}\n"
    )


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
    nodes = list(base.flow_nodes) or [
        FlowNode(
            node_id=section.section_id,
            label=section.title,
            section_id=section.section_id,
        )
        for section in base.sections
    ]
    if base.process_applicable:
        inferred = render_mermaid(nodes, flow_edges)
    else:
        inferred = (
            base.inferred_mermaid
            if "No process flow applicable" in base.inferred_mermaid
            else ('flowchart TD\n  note["No process flow applicable for this document type"]\n')
        )
    return base.model_copy(
        update={
            "summary": (
                f"{base.summary} Provider enrichment added {len(candidate.findings)} finding(s) "
                f"and {len(candidate.questions)} question(s)."
            ),
            "findings": findings,
            "questions": questions,
            "flow_nodes": nodes if base.process_applicable else base.flow_nodes,
            "flow_edges": flow_edges,
            "mermaid": inferred,
            "inferred_mermaid": inferred,
        }
    )


__all__ = [
    "bounded_batches",
    "build_flow_graph",
    "build_proposed_flow",
    "build_review",
    "evidence_for_offset",
    "explain_flow_adjustments",
    "merge_provider_review",
    "normalise_title",
    "render_flow_markdown",
    "render_macro_markdown",
    "render_mermaid",
    "render_review_index_markdown",
    "render_sections_markdown",
    "title_matches",
]
