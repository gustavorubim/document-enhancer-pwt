"""Deterministic final-bundle checks and audit rendering."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Any

from .figures import final_figure_path
from .models import AuditReport, ReviewReport, SourceFigure
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


def figure_references_valid(final_text: str, figures: list[SourceFigure]) -> bool:
    expected = {figure.figure_id for figure in figures}
    observed = set(re.findall(r"\[(FIG-\d{3})\]", final_text))
    return observed == expected and all(
        final_text.count(f"[{figure_id}]") >= 2 for figure_id in expected
    )


def figure_appendix_complete(final_text: str, figures: list[SourceFigure]) -> bool:
    if not figures:
        return True
    if not re.search(r"^## Appendix [A-Z] — Source screenshots$", final_text, re.MULTILINE):
        return False
    return all(
        final_text.count(f"### [{figure.figure_id}]") == 1
        and final_text.count(f"](../{final_figure_path(figure)})") == 1
        for figure in figures
    )


def figure_asset_digests_match(run_path: Path, figures: list[SourceFigure]) -> bool:
    for figure in figures:
        path = (run_path / final_figure_path(figure)).resolve()
        if run_path.resolve() not in path.parents or not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != figure.sha256:
            return False
    return True


def final_docx_figures_embedded(docx_bytes: bytes, figures: list[SourceFigure]) -> bool:
    if not figures:
        return True
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            media_digests = {
                hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist()
                if name.startswith("word/media/")
            }
    except (OSError, KeyError, zipfile.BadZipFile):
        return False
    return all(figure.sha256 in media_digests for figure in figures)


def render_audit_markdown(audit: AuditReport) -> str:
    descriptions = {
        "final_markdown_nonempty": "The final Markdown contains reviewable document content.",
        "source_digest_preserved": "The recorded source identity still matches the original input.",
        "questions_resolved": "No blocking human-review question remains unresolved.",
        "no_unresolved_placeholders": "No TBD, TODO, TBC, or equivalent placeholder remains.",
        "deferred_decisions_resolved": "The rewrite plan contains no deferred business decision.",
        "source_anchor_retained": "Distinctive source language survives at the required fidelity floor.",
        "source_sections_accounted_for": "Every source section remains represented in the result.",
        "required_sections_present": "Required recipe sections are present or explicitly waived.",
        "section_assessments_present": "Every reviewed section has a valid readiness assessment.",
        "dual_flow_artifacts_present": "Applicable process work includes inferred and proposed flows.",
        "semantic_references_valid": "Semantic graph edges reference existing graph nodes.",
        "graph_types_valid": "Graph node and edge types conform to the selected ontology recipe.",
        "independent_content_audit": "The optional independent provider audit also passed.",
        "figure_references_valid": "Every source figure has a body reference and no unknown figure ID appears.",
        "figure_appendix_complete": "Every source figure appears exactly in the governed screenshot appendix.",
        "figure_asset_digests_match": "Final appendix image bytes match the extracted source figures.",
        "final_docx_figures_embedded": "The final DOCX contains every referenced source figure.",
    }
    passed = sum(1 for value in audit.checks.values() if value)
    failed = len(audit.checks) - passed
    lines = [
        f"# Final audit: {audit.status}",
        "",
        "## Executive conclusion",
        "",
        audit.summary,
        "",
        (
            "The bundle passed its promotion gate and is sealed for downstream use. The result "
            "below means the deterministic checks found no unresolved condition that would block "
            "delivery. A passing audit is evidence of workflow completeness and traceability; it "
            "does not replace the accountable owner's approval of business meaning."
            if audit.status == "pass"
            else "The bundle did not pass its promotion gate and has not been sealed. Review the "
            "failed checks and blockers below before treating the final document as approved."
        ),
        "",
        "## Verification summary",
        "",
        f"- Overall result: **{audit.status.upper()}**",
        f"- Checks passed: **{passed}** of **{len(audit.checks)}**",
        f"- Checks failed: **{failed}**",
        f"- Blocking items recorded: **{len(audit.blockers)}**",
        "",
        "## Detailed checks",
        "",
        "| Check | Result | What the check establishes |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| `{name}` | **{'pass' if check_passed else 'fail'}** | "
        f"{descriptions.get(name, 'The named deterministic bundle condition was evaluated.')} |"
        for name, check_passed in audit.checks.items()
    )
    if audit.blockers:
        lines.extend(["", "## Blocking items", ""])
        lines.extend(f"- `{item}`" for item in audit.blockers)
        lines.extend(
            [
                "",
                "Resolve these items, regenerate the affected artifacts, and rerun verification. "
                "Do not distribute the bundle as sealed while any blocker remains.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Blocking items",
                "",
                "None. All evaluated promotion conditions passed.",
            ]
        )
    lines.extend(
        [
            "",
            "## Delivered evidence",
            "",
            "The final bundle includes the rewritten Markdown and DOCX, the accepted decision "
            "record, a source-to-target map, a detailed change explanation, inferred and proposed "
            "process diagrams, and portable semantic and ontology exports. Together these files "
            "allow a reviewer to trace what changed and allow downstream systems to consume the "
            "sealed result without depending on the authoring runtime.",
            "",
            "## Reviewer guidance",
            "",
            "Read `07-final-document.md` alongside `08-change-explanation.md`. Confirm that the "
            "accepted decisions were applied as intended and that no approved nuance was lost. "
            "Use this audit as the final technical control record for the run.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "deferred_decisions_resolved",
    "dual_flow_artifacts_present",
    "figure_appendix_complete",
    "figure_asset_digests_match",
    "figure_references_valid",
    "final_docx_figures_embedded",
    "graph_types_valid",
    "no_unresolved_placeholders",
    "render_audit_markdown",
    "required_sections_present",
    "section_assessments_present",
    "semantic_references_valid",
    "source_anchor_retained",
    "source_sections_retained",
]
