"""Deterministic human-readable renderers for reviewer artifacts."""

from __future__ import annotations

from collections.abc import Iterable

from document_enhancer.domain.questions import ChecklistItem, QuestionsArtifact, RewriteChecklist


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_questions_markdown(artifact: QuestionsArtifact) -> str:
    lines = [
        "# Clarification questions",
        "",
        f"- Document ID: `{artifact.document_id}`",
        f"- Version ID: `{artifact.version_id or 'unspecified'}`",
        f"- Blocking questions: `{sum(question.blocking for question in artifact.questions)}`",
        "",
        "Questions are evidence-backed requests for reviewer input. Empty or unknown facts stay open; this file does not supply answers.",
        "",
    ]
    for question in artifact.questions:
        lines.extend(
            [
                f"## {question.question_id} — {question.category.value}",
                "",
                f"- Priority: `{question.priority.value}`",
                f"- Blocking: `{str(question.blocking).lower()}`",
                f"- Target section: `{question.target_section_id or 'unspecified'}`",
                f"- Target object: `{question.target_object_id or 'unspecified'}`",
                f"- Prerequisites: `{', '.join(question.depends_on_question_ids) or 'none'}`",
                "",
                f"**Question:** {question.question}",
                "",
                f"**Why it matters:** {question.why_it_matters}",
                "",
                f"**Expected answer shape:** {question.expected_answer_shape or 'Provide an evidence-backed decision or explicitly mark not applicable.'}",
                "",
            ]
        )
        if question.source_finding_ids:
            lines.extend(
                [
                    "**Source findings:** "
                    + ", ".join(f"`{item}`" for item in question.source_finding_ids),
                    "",
                ]
            )
        lines.append("**Evidence:**")
        if question.evidence:
            lines.extend(
                f'- `{item.span_id}`: "{_quote(item.quote)}"' for item in question.evidence
            )
        else:
            lines.append(
                "- No source quote was supplied; provide provenance before treating an answer as authoritative."
            )
        lines.append("")
    if not artifact.questions:
        lines.append("No clarification questions were synthesized.")
    return "\n".join(lines).rstrip() + "\n"


def _item_basis(item: ChecklistItem) -> str:
    values = [
        item.source_finding_id,
        item.question_id,
        item.answer_id,
        item.steering_id,
        item.reference_rule_id,
        item.audit_requirement,
    ]
    return ", ".join(f"`{value}`" for value in values if value) or "none"


def render_checklist_markdown(checklist: RewriteChecklist) -> str:
    lines = [
        "# Rewrite checklist",
        "",
        f"- Checklist ID: `{checklist.checklist_id}`",
        f"- Document ID: `{checklist.document_id}`",
        f"- Approved by: `{checklist.approved_by or 'pending'}`",
        f"- Blocking items: `{sum(item.blocking for item in checklist.items)}`",
        "",
        "Every item below is linked to a question, finding, answer, steering directive, reference rule, or audit requirement.",
        "",
    ]
    for item in checklist.items:
        lines.extend(
            [
                f"## {item.checklist_item_id} — {item.action.value}",
                "",
                f"- Status: `{item.status.value}`",
                f"- Blocking: `{str(item.blocking).lower()}`",
                f"- Basis: {_item_basis(item)}",
                f"- Target section: `{item.target_section_id or 'unspecified'}`",
                f"- Target object: `{item.target_object_id or 'unspecified'}`",
                f"- Verification: {item.verification_method}",
                f"- Acceptance criterion: {item.acceptance_criterion}",
            ]
        )
        if item.reason:
            lines.append(f"- Reason: {item.reason}")
        lines.append("")
        lines.append("**Evidence:**")
        if item.evidence:
            lines.extend(
                f'- `{evidence.span_id}`: "{_quote(evidence.quote)}"' for evidence in item.evidence
            )
        else:
            lines.append("- No direct evidence link supplied.")
        lines.append("")
    if not checklist.items:
        lines.append("No rewrite checklist items were synthesized.")
    return "\n".join(lines).rstrip() + "\n"


def render_validation_diagnostics(diagnostics: Iterable[object]) -> str:
    """Small helper used by the Rich CLI and tests without exposing model internals."""

    return "\n".join(
        f"[{getattr(item, 'severity', 'error')}] {getattr(item, 'path', '?')}: {getattr(item, 'message', item)}"
        for item in diagnostics
    )


__all__ = [
    "render_checklist_markdown",
    "render_questions_markdown",
    "render_validation_diagnostics",
]
