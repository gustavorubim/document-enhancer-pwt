"""Deterministic final-bundle checks and audit rendering."""

from __future__ import annotations

import re
from typing import Any

from .models import AuditReport, ReviewReport
from .recipes import Recipe
from .review import title_matches


def semantic_references_valid(semantic: dict[str, Any]) -> bool:
    node_ids = {item.get("node_id") for item in semantic.get("nodes", [])}
    return all(
        edge.get("source") in node_ids and edge.get("target") in node_ids
        for edge in semantic.get("edges", [])
    )


def graph_types_valid(semantic: dict[str, Any], recipe: Recipe | None) -> bool:
    if not recipe:
        return True
    for node in semantic.get("nodes", []):
        node_type = str(node.get("node_type") or "")
        if node_type and not recipe.allows_node_type(node_type):
            return False
    for edge in semantic.get("edges", []):
        edge_type = str(edge.get("edge_type") or "")
        if edge_type and not recipe.allows_edge_type(edge_type):
            return False
    return True


def source_sections_retained(review: ReviewReport, final_text: str) -> bool:
    lower_final = final_text.lower()
    for section in review.sections:
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", section.title.lower()) if len(token) >= 3
        ]
        if tokens and not all(token in lower_final for token in tokens):
            return False
    return True


def required_sections_present(
    recipe: Recipe | None,
    final_text: str,
    *,
    waived_requirement_ids: set[str] | None = None,
) -> bool:
    if not recipe:
        return True
    waived = waived_requirement_ids or set()
    headings = [
        line.lstrip("# ").strip() for line in final_text.splitlines() if line.startswith("#")
    ]
    for requirement in recipe.required_section_items:
        requirement_id = str(requirement.get("id") or "")
        if requirement_id in waived:
            continue
        heading = str(requirement.get("heading") or requirement_id or "")
        if heading and not any(title_matches(heading, item) for item in headings):
            return False
    return True


def source_anchor_retained(source_text: str, final_text: str) -> bool:
    """Require a meaningful share of distinctive source tokens to survive rewrite."""

    source_tokens = [
        token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{4,}", source_text)
    ]
    if not source_tokens:
        return bool(final_text.strip())
    # Prefer distinctive tokens; fall back to the full set for short sources.
    counts: dict[str, int] = {}
    for token in source_tokens:
        counts[token] = counts.get(token, 0) + 1
    distinctive = [token for token, count in counts.items() if count == 1]
    sample = distinctive[:40] or list(counts)[:40]
    if not sample:
        return bool(final_text.strip())
    final_lower = final_text.lower()
    retained = sum(1 for token in sample if token in final_lower)
    return retained / len(sample) >= 0.25


def section_assessments_present(review: ReviewReport) -> bool:
    return bool(review.section_assessments) and all(
        item.status in {"correct", "missing", "improve"} for item in review.section_assessments
    )


def dual_flow_artifacts_present(review: ReviewReport) -> bool:
    if not review.process_applicable:
        return "No process flow applicable" in review.inferred_mermaid
    return bool(review.inferred_mermaid.strip()) and bool(review.proposed_mermaid.strip())


def no_unresolved_placeholders(final_text: str) -> bool:
    return re.search(r"\b(?:TBD|TODO|TBC)\b|\[\s*\?\s*\]|\?{3,}", final_text, re.IGNORECASE) is None


def deferred_decisions_resolved(deferred_ids: list[str]) -> bool:
    return not deferred_ids


def render_audit_markdown(audit: AuditReport) -> str:
    lines = [
        f"# Audit: {audit.status}",
        "",
        audit.summary,
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    lines.extend(
        f"| {name} | {'pass' if passed else 'fail'} |" for name, passed in audit.checks.items()
    )
    if audit.blockers:
        lines.extend(["", "Blockers: " + ", ".join(audit.blockers)])
    return "\n".join(lines) + "\n"


__all__ = [
    "deferred_decisions_resolved",
    "dual_flow_artifacts_present",
    "graph_types_valid",
    "no_unresolved_placeholders",
    "render_audit_markdown",
    "required_sections_present",
    "section_assessments_present",
    "semantic_references_valid",
    "source_anchor_retained",
    "source_sections_retained",
]
