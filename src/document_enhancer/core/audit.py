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


def source_sections_retained(review: ReviewReport, final_text: str) -> bool:
    lower_final = final_text.lower()
    for section in review.sections:
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", section.title.lower()) if len(token) >= 3
        ]
        if tokens and not all(token in lower_final for token in tokens):
            return False
    return True


def required_sections_present(recipe: Recipe | None, final_text: str) -> bool:
    if not recipe:
        return True
    headings = [
        line.lstrip("# ").strip() for line in final_text.splitlines() if line.startswith("#")
    ]
    for requirement in recipe.required_section_items:
        heading = str(requirement.get("heading") or requirement.get("id") or "")
        if heading and not any(title_matches(heading, item) for item in headings):
            return False
    return True


def source_anchor_retained(source_text: str, final_text: str) -> bool:
    source_tokens = {
        token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{4,}", source_text)
    }
    if not source_tokens:
        return bool(final_text.strip())
    final_lower = final_text.lower()
    return any(token in final_lower for token in source_tokens)


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
    "render_audit_markdown",
    "required_sections_present",
    "semantic_references_valid",
    "source_anchor_retained",
    "source_sections_retained",
]
