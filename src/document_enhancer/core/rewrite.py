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
from .review import normalise_title


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
        present_titles = {normalise_title(item.title): item.section_id for item in review.sections}
        for requirement in recipe.required_section_items:
            heading = str(requirement.get("heading") or requirement.get("id") or "")
            section_id = present_titles.get(normalise_title(heading))
            if section_id:
                required_section_ids.append(section_id)
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
        updated = re.sub(
            r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", answer, text, count=1, flags=re.IGNORECASE
        )
        if updated != text:
            changes.append(
                f"Replaced one unresolved marker with the accepted answer for {decision.question_id}."
            )
        text = updated
    return text, changes


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


def semantic_graph(review: ReviewReport, final_text: str) -> dict[str, Any]:
    ir = DocumentIR(
        sections=review.sections,
        nodes=[
            SemanticNode(
                node_id=section.section_id,
                label=section.title,
                node_type="section",
                properties={
                    "level": section.level,
                    "parent_id": section.parent_id,
                },
                provenance_span_ids=list(section.span_ids),
            )
            for section in review.sections
        ],
        edges=[
            SemanticEdge(
                source=edge.source,
                target=edge.target,
                edge_type=edge.relation,
                properties={"relation": edge.relation},
                provenance_span_ids=list(edge.evidence_span_ids),
            )
            for edge in review.flow_edges
        ],
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
    "compile_rewrite_plan",
    "graph_json_lines",
    "render_docx",
    "semantic_diff",
    "semantic_graph",
    "source_target_csv",
]
