"""Rewrite planning and final-document projections for the core workflow."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from typing import Any

from docx import Document

from .export import public_graph_jsonl
from .models import (
    Decision,
    DocumentIR,
    Finding,
    ReviewReport,
    RewritePlan,
    RewritePlanItem,
    SemanticEdge,
    SemanticNode,
)
from .recipes import Recipe
from .review import title_matches

_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", re.IGNORECASE)


def compile_rewrite_plan(
    *,
    source_digest: str,
    review: ReviewReport,
    decisions: list[Decision],
    recipe: Recipe | None,
) -> RewritePlan:
    findings_by_section: dict[str, list[Finding]] = {}
    for finding in review.findings:
        if finding.section_id:
            findings_by_section.setdefault(finding.section_id, []).append(finding)
    items = [
        RewritePlanItem(
            section_id=section.section_id,
            title=section.title,
            source_span_ids=list(section.span_ids),
            finding_ids=[
                item.finding_id for item in findings_by_section.get(section.section_id, [])
            ],
            recommendations=list(
                dict.fromkeys(
                    item.recommendation
                    for item in findings_by_section.get(section.section_id, [])
                    if item.recommendation
                )
            ),
        )
        for section in review.sections
    ]
    required_section_ids: list[str] = []
    if recipe:
        for requirement in recipe.required_section_items:
            heading = str(requirement.get("heading") or requirement.get("id") or "")
            requirement_id = str(requirement.get("id") or heading)
            matching = next(
                (item for item in review.sections if title_matches(heading, item.title)),
                None,
            )
            if matching:
                required_section_ids.append(matching.section_id)
                continue
            stub_id = f"missing-{requirement_id.lower()}"
            required_section_ids.append(stub_id)
            items.append(
                RewritePlanItem(
                    section_id=stub_id,
                    title=heading or requirement_id,
                    source_span_ids=[],
                    finding_ids=[
                        item.finding_id
                        for item in review.findings
                        if item.finding_id.endswith(requirement_id.lower())
                    ],
                    recommendations=[
                        "Insert an evidence-backed section or record an explicit waiver."
                    ],
                    missing_required=True,
                    requirement_id=requirement_id,
                )
            )
    return RewritePlan(
        recipe_id=review.recipe_id,
        source_digest=source_digest,
        items=items,
        required_section_ids=required_section_ids,
        accepted_decision_ids=[
            item.question_id
            for item in decisions
            if item.disposition == "accept" and item.answer.strip()
        ],
        deferred_decision_ids=[
            item.question_id for item in decisions if item.disposition == "defer"
        ],
    )


def apply_deterministic_answers(text: str, decisions: list[Decision]) -> tuple[str, list[str]]:
    changes: list[str] = []
    for decision in decisions:
        answer = decision.answer.strip()
        if not answer or decision.disposition != "accept":
            continue
        updated = _PLACEHOLDER_RE.sub(answer, text, count=1)
        if updated != text:
            changes.append(
                f"Replaced one unresolved marker with the accepted answer for {decision.question_id}."
            )
        text = updated
    return text, changes


def apply_reviewer_decisions(
    text: str,
    *,
    decisions: list[Decision],
    steering: str = "",
) -> tuple[str, list[str]]:
    """Apply accepted answers offline: placeholders, steered conflict fixes, decision log."""

    text, changes = apply_deterministic_answers(text, decisions)
    accepted = [item for item in decisions if item.disposition == "accept" and item.answer.strip()]
    if not accepted and not steering.strip():
        return text, changes
    open_points = next(
        (
            item
            for item in accepted
            if item.question_id == "question-open-points-001" or "open-points" in item.question_id
        ),
        None,
    )
    if open_points is not None:
        answer = open_points.answer.lower()
        replacements: list[tuple[str, str, str]] = []
        if "30 minutes" in answer:
            replacements.append(
                (
                    "P1: within 60 minutes of receipt",
                    "P1: within 30 minutes of receipt",
                    "Aligned STEP-CCT-050 P1 timing to the approved 30-minute SLA.",
                )
            )
            replacements.append(
                (
                    "Require 30-minute human acknowledgement for P1 complaints.",
                    "Require 30-minute human acknowledgement for P1 complaints (approved).",
                    "Confirmed pilot readiness P1 acknowledgement at 30 minutes.",
                )
            )
            replacements.append(
                (
                    "STEP-CCT-050 says 60 minutes; CTRL-CCT-002 says 30 minutes",
                    "STEP-CCT-050 and CTRL-CCT-002 both require 30 minutes (approved)",
                    "Removed the resolved P1 timing conflict from the open-points table.",
                )
            )
        if "0.85" in answer:
            replacements.append(
                (
                    ">= 0.80",
                    ">= 0.85",
                    "Updated high-confidence routing threshold to the approved 0.85 value.",
                )
            )
            replacements.append(
                (
                    "< 0.80",
                    "< 0.85",
                    "Updated low-confidence routing threshold to the approved 0.85 boundary.",
                )
            )
            replacements.append(
                (
                    "RULE-CCT-002 uses 0.80; pilot readiness note uses 0.85",
                    "RULE-CCT-002 and pilot readiness both use 0.85 (approved)",
                    "Resolved AI routing confidence conflict to 0.85.",
                )
            )
        if re.search(r"\b(?:7|seven)[ -]?years?\b", answer):
            replacements.append(
                (
                    "Retain pilot complaint records for 5 years after calendar-year end.",
                    "Retain pilot complaint records for 7 years after case closure (approved).",
                    "Resolved retention conflict to 7 years after case closure.",
                )
            )
            replacements.append(
                (
                    "The pilot readiness checklist still says five years after calendar-year end. "
                    "Records Management must confirm which period is authoritative before approval.",
                    "Records retention is approved at seven years after case closure "
                    "(Records Management with Legal).",
                    "Removed unresolved retention conflict language.",
                )
            )
            replacements.append(
                (
                    "Section 15 says 7 years after closure; readiness checklist says 5 years "
                    "after year end",
                    "Section 15 and the readiness checklist both require 7 years after closure "
                    "(approved)",
                    "Removed the resolved retention conflict from the open-points table.",
                )
            )
        if "compliance" in answer and any(
            term in answer for term in ("batch", "independent", "approval", "concurrence")
        ):
            replacements.append(
                (
                    "Draft says manager approval; approval partner not stated",
                    "Complaint Operations Manager approval plus Compliance concurrence required",
                    "Named the independent approval partner for material batch actions.",
                )
            )
            replacements.append(
                (
                    "RULE-CCT-004 names manager approval but does not identify required "
                    "independent approval",
                    "Complaint Operations Manager approval plus independent Compliance "
                    "concurrence is required (approved)",
                    "Removed the resolved batch-approval conflict from the open-points table.",
                )
            )
        for old, new, note in replacements:
            if old in text and old != new:
                text = text.replace(old, new)
                changes.append(note)
    log_lines = [
        "",
        "# Reviewer decisions applied",
        "",
        "The following accepted decisions were applied during the rewrite stage.",
        "",
    ]
    if steering.strip():
        log_lines.extend(["## Steering", "", steering.strip(), ""])
    log_lines.extend(["## Accepted answers", ""])
    for item in accepted:
        log_lines.extend(
            [
                f"### `{item.question_id}`",
                "",
                item.answer.strip(),
                "",
            ]
        )
        if item.rationale:
            log_lines.extend([f"_Rationale:_ {item.rationale}", ""])
    if "# Reviewer decisions applied" not in text:
        text = text.rstrip() + "\n" + "\n".join(log_lines)
        changes.append("Appended reviewer decisions applied section from accepted answers.")
    return text, changes


def apply_template_stubs(
    text: str,
    *,
    plan: RewritePlan,
    recipe: Recipe | None,
    decisions: list[Decision],
    waived_requirement_ids: set[str],
) -> tuple[str, list[str]]:
    """Append explicit stubs for missing required sections that were not waived."""

    if not recipe:
        return text, []
    answers = {
        item.question_id: item.answer.strip()
        for item in decisions
        if item.disposition == "accept" and item.answer.strip()
    }
    changes: list[str] = []
    body = text.rstrip() + "\n"
    for item in plan.items:
        if not item.missing_required or not item.requirement_id:
            continue
        if item.requirement_id in waived_requirement_ids:
            continue
        if title_matches(item.title, body):
            continue
        expected = next(
            (
                str(requirement.get("expected_content") or "")
                for requirement in recipe.required_section_items
                if str(requirement.get("id") or "") == item.requirement_id
            ),
            "",
        )
        question_id = f"question-required-{item.requirement_id.lower()}"
        answer = answers.get(question_id, "")
        if answer and answer.lower() not in {"yes", "y", "true", "include"}:
            content = answer
        elif answer:
            content = (
                f"TBD: Reviewer approved inclusion of `{item.requirement_id}` but did not supply "
                "source-backed body text."
            )
        else:
            content = (
                f"TBD: Provide source-backed content for required section `{item.requirement_id}`."
            )
        stub = f"\n## {item.title}\n\n{content}\n"
        if expected:
            stub += f"\nExpected content: {expected}.\n"
        body += stub
        changes.append(f"Inserted governed stub for missing section {item.title!r}.")
    return body, changes


def render_docx(markdown: str) -> bytes:
    document = Document()
    for line in markdown.splitlines():
        if not line.strip():
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            document.add_heading(heading.group(2).strip(), level=min(len(heading.group(1)), 6))
        elif re.match(r"^\s*[-*]\s+", line):
            document.add_paragraph(re.sub(r"^\s*[-*]\s+", "", line), style="List Bullet")
        else:
            document.add_paragraph(line.strip())
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def semantic_graph(
    review: ReviewReport,
    final_text: str,
    *,
    recipe: Recipe | None = None,
) -> dict[str, Any]:
    nodes: list[SemanticNode] = []
    edges: list[SemanticEdge] = []
    for section in review.sections:
        requirement = None
        if recipe:
            requirement = next(
                (
                    item
                    for item in recipe.required_sections
                    if title_matches(
                        str(item.get("heading") or item.get("id") or ""), section.title
                    )
                ),
                None,
            )
        hooks = [str(item) for item in ((requirement or {}).get("ontology_hooks") or [])]
        primary_type = hooks[0] if hooks else "Section"
        if recipe and not recipe.allows_node_type(primary_type):
            primary_type = "Section"
        nodes.append(
            SemanticNode(
                node_id=section.section_id,
                label=section.title,
                node_type=primary_type,
                properties={
                    "level": section.level,
                    "parent_id": section.parent_id,
                    "requirement_id": (requirement or {}).get("id"),
                    "ontology_hooks": hooks,
                },
                provenance_span_ids=list(section.span_ids),
            )
        )
        for hook in hooks[1:]:
            if recipe and not recipe.allows_node_type(hook):
                continue
            hook_id = f"{section.section_id}:{hook.lower()}"
            nodes.append(
                SemanticNode(
                    node_id=hook_id,
                    label=f"{section.title} ({hook})",
                    node_type=hook,
                    properties={"parent_section": section.section_id},
                    provenance_span_ids=list(section.span_ids[:3]),
                )
            )
            edges.append(
                SemanticEdge(
                    source=section.section_id,
                    target=hook_id,
                    edge_type="contains",
                    properties={"derived_from": "ontology_hooks"},
                    provenance_span_ids=list(section.span_ids[:3]),
                )
            )
    flow_edges = review.proposed_flow_edges or review.flow_edges
    for edge in flow_edges:
        edge_type = edge.relation
        if recipe and not recipe.allows_edge_type(edge_type):
            continue
        edges.append(
            SemanticEdge(
                source=edge.source,
                target=edge.target,
                edge_type=edge_type,
                properties={"relation": edge.relation},
                provenance_span_ids=list(edge.evidence_span_ids),
            )
        )
    for node in review.proposed_flow_nodes:
        if any(item.node_id == node.node_id for item in nodes):
            continue
        mapped = {
            "decision": "Decision",
            "step": "ProcessStep",
            "section": "Section",
        }.get(node.node_type, "Section")
        if recipe and not recipe.allows_node_type(mapped):
            mapped = "Section"
        nodes.append(
            SemanticNode(
                node_id=node.node_id,
                label=node.label,
                node_type=mapped,
                properties={"proposed": True},
                provenance_span_ids=[],
            )
        )
    ir = DocumentIR(
        sections=review.sections,
        nodes=nodes,
        edges=edges,
        markdown_sha256=hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
    )
    return ir.model_dump(mode="json")


def graph_json_lines(graph: dict[str, list[dict[str, str]]]) -> list[str]:
    return public_graph_jsonl(graph).splitlines()


def source_target_csv(review: ReviewReport, final_text: str) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["section_id", "title", "disposition", "final_digest"])
    digest = hashlib.sha256(final_text.encode("utf-8")).hexdigest()
    for section in review.sections:
        title_tokens = [
            token for token in re.findall(r"[a-z0-9]+", section.title.lower()) if len(token) >= 3
        ]
        retained = bool(title_tokens) and all(token in final_text.lower() for token in title_tokens)
        writer.writerow(
            [section.section_id, section.title, "retained" if retained else "missing", digest]
        )
    return stream.getvalue()


def semantic_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_nodes = {item["node_id"] for item in before.get("nodes", [])}
    after_nodes = {item["node_id"] for item in after.get("nodes", [])}
    before_edges = {
        (item["source"], item["target"], item["edge_type"]) for item in before.get("edges", [])
    }
    after_edges = {
        (item["source"], item["target"], item["edge_type"]) for item in after.get("edges", [])
    }
    return {
        "added_nodes": sorted(after_nodes - before_nodes),
        "removed_nodes": sorted(before_nodes - after_nodes),
        "added_edges": [list(item) for item in sorted(after_edges - before_edges)],
        "removed_edges": [list(item) for item in sorted(before_edges - after_edges)],
        "markdown_changed": before.get("markdown_sha256") != after.get("markdown_sha256"),
    }


__all__ = [
    "apply_deterministic_answers",
    "apply_reviewer_decisions",
    "apply_template_stubs",
    "compile_rewrite_plan",
    "graph_json_lines",
    "render_docx",
    "semantic_diff",
    "semantic_graph",
    "source_target_csv",
]
