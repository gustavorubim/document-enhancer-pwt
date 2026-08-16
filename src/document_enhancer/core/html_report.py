"""Generate a polished, static reviewer for the numbered Markdown reports."""

from __future__ import annotations

import html
import json
import re
import textwrap
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from markdown_it import MarkdownIt

from .models import AuditReport, FlowEdge, FlowNode, ReviewReport, RunRecord, SourceFigure


def _fence_renderer(
    _: Any, tokens: list[Any], index: int, __: Any, environment: dict[str, Any]
) -> str:
    token = tokens[index]
    language = str(token.info or "").strip().split(maxsplit=1)[0]
    content = html.escape(str(token.content))
    if language == "mermaid":
        diagrams = environment.get("mermaid_svgs", [])
        diagram = diagrams.pop(0) if diagrams else f'<pre class="mermaid-source">{content}</pre>'
        return (
            '<div class="diagram-shell">'
            '<div class="diagram-label">Rendered process diagram</div>'
            f"{diagram}"
            "<details><summary>Show Mermaid source</summary>"
            f'<pre class="mermaid-source">{content}</pre></details>'
            "</div>"
        )
    class_name = f' class="language-{html.escape(language)}"' if language else ""
    return f"<pre><code{class_name}>{content}</code></pre>"


def _markdown_renderer() -> MarkdownIt:
    renderer = MarkdownIt("commonmark", {"html": False, "typographer": True}).enable("table")
    renderer.add_render_rule("fence", _fence_renderer)
    return renderer


def _title(markdown: str, path: str) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
    if match:
        return match.group(1).strip()
    return Path(path).stem.replace("-", " ").title()


def _display_title(markdown: str, path: str) -> str:
    """Use operator-oriented tab labels where the Markdown heading is document content."""

    overrides = {
        "01-source-normalized.md": "Original Normalized Document",
        "02-review-overview.md": "Review Overview",
        "03-macro-review.md": "Macro Review",
        "04-section-review.md": "Section Review",
        "05-process-flow-review.md": "Process Flow Review",
        "06-review-questions.md": "Review Questions",
        "07-final-document.md": "Enhanced Document",
        "08-change-explanation.md": "Change Explanation",
        "09-final-audit.md": "Final Audit",
    }
    return overrides.get(Path(path).name, _title(markdown, path))


def _anchor(path: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", Path(path).stem.lower()).strip("-")


_DRAFT_DOCUMENT_PATH = "draft/document.md"
_DRAFT_TRANSFORMATION_PATH = "draft/transformation.json"
_DRAFT_VISUAL_EXTRACTIONS_PATH = "draft/visual-extractions.json"
_GAP_ID_RE = re.compile(r"\bGAP-\d{3,}\b")


@dataclass(frozen=True)
class _DraftReviewContext:
    """Renderer-owned view of the optional frozen Stage 1 draft artifacts."""

    path: str
    markdown: str
    transformation: object | None
    visual_extractions: tuple[object, ...]


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_items(value: object) -> list[object]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    if not isinstance(value, Iterable):
        return []
    return list(cast(Iterable[object], value))


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _is_draft_document_path(path: str) -> bool:
    normalised = path.replace("\\", "/").strip().lower()
    return normalised == _DRAFT_DOCUMENT_PATH or normalised.endswith(f"/{_DRAFT_DOCUMENT_PATH}")


def _is_draft_artifact_path(path: str, artifact_name: str) -> bool:
    normalised = path.replace("\\", "/").strip().lower()
    return normalised == artifact_name or normalised.endswith(f"/{artifact_name}")


def _markdown_from_candidate(value: object) -> tuple[str | None, str | None]:
    """Extract candidate Markdown and an optional artifact path without reading files."""

    if isinstance(value, str):
        return value, None
    if isinstance(value, tuple) and len(value) == 2:
        path, content = value
        if isinstance(content, str):
            return content, str(path)
    if isinstance(value, Mapping):
        path = value.get("path") or value.get("artifact_path")
        for key in ("markdown", "document_markdown", "content", "document"):
            content = value.get(key)
            if isinstance(content, str):
                return content, str(path) if path else None
    renderer = getattr(value, "render_markdown", None)
    if callable(renderer):
        rendered = renderer()
        if isinstance(rendered, str):
            return rendered, None
    return None, None


def _transformation_from_candidate(value: object) -> object | None:
    if isinstance(value, Mapping):
        candidate = value.get("transformation")
        if candidate is not None:
            return candidate
    if any(
        _field(value, name) is not None
        for name in ("template_sections", "draft_sections", "gaps", "questions")
    ):
        return value
    return None


def _artifact_mapping(
    documents: Sequence[tuple[str, str]], draft_artifacts: Mapping[str, object] | None
) -> dict[str, object]:
    artifacts = {str(path): content for path, content in (draft_artifacts or {}).items()}
    artifacts.update({str(path): content for path, content in documents})
    return artifacts


def _artifact_for_path(artifacts: Mapping[str, object], artifact_name: str) -> object | None:
    for path, content in artifacts.items():
        if _is_draft_artifact_path(path, artifact_name):
            return content
    return None


def _visual_extractions_from(value: object) -> tuple[object, ...]:
    value = _json_value(value)
    if isinstance(value, Mapping):
        value = value.get("visual_extractions", value.get("extractions", []))
    return tuple(_as_items(value))


def _draft_context(
    *,
    documents: Sequence[tuple[str, str]],
    draft: object | None,
    candidate_draft: object | None,
    candidate: object | None,
    draft_markdown: str | None,
    transformation: object | None,
    visual_extractions: Sequence[object],
    draft_artifacts: Mapping[str, object] | None,
) -> tuple[_DraftReviewContext | None, list[tuple[str, str]]]:
    """Resolve an optional candidate from caller-owned content, never from the filesystem."""

    artifact_map = _artifact_mapping(documents, draft_artifacts)
    candidate_value = draft if draft is not None else candidate_draft
    if candidate_value is None:
        candidate_value = candidate

    resolved_markdown: str | None = draft_markdown
    resolved_path = _DRAFT_DOCUMENT_PATH
    candidate_transformation = transformation
    if candidate_value is not None:
        candidate_markdown, candidate_path = _markdown_from_candidate(candidate_value)
        if resolved_markdown is None:
            resolved_markdown = candidate_markdown
        if candidate_path:
            resolved_path = candidate_path
        if candidate_transformation is None:
            candidate_transformation = _transformation_from_candidate(candidate_value)

    remaining: list[tuple[str, str]] = []
    document_candidate: tuple[str, str] | None = None
    for path, content in documents:
        path_string = str(path)
        if _is_draft_document_path(path_string):
            document_candidate = (path_string, content)
            continue
        # The JSON and DOCX draft artifacts are supporting inputs, not report tabs.
        normalised_path = path_string.replace("\\", "/").lower()
        if normalised_path.startswith("draft/") or "/draft/" in normalised_path:
            continue
        remaining.append((path_string, content))
    if resolved_markdown is None and document_candidate is not None:
        resolved_path, resolved_markdown = document_candidate
    if resolved_markdown is None:
        artifact_document = _artifact_for_path(artifact_map, _DRAFT_DOCUMENT_PATH)
        if isinstance(artifact_document, str):
            resolved_markdown = artifact_document

    if candidate_transformation is None:
        transformation_artifact = _artifact_for_path(artifact_map, _DRAFT_TRANSFORMATION_PATH)
        if transformation_artifact is not None:
            candidate_transformation = _json_value(transformation_artifact)
            if isinstance(candidate_transformation, Mapping):
                candidate_transformation = candidate_transformation.get(
                    "transformation", candidate_transformation
                )
    extraction_items = list(visual_extractions)
    if not extraction_items and candidate_transformation is not None:
        extraction_items.extend(
            _visual_extractions_from(_field(candidate_transformation, "visual_extractions"))
        )
    if not extraction_items:
        visual_artifact = _artifact_for_path(artifact_map, _DRAFT_VISUAL_EXTRACTIONS_PATH)
        if visual_artifact is not None:
            extraction_items.extend(_visual_extractions_from(visual_artifact))

    if resolved_markdown is None and candidate_transformation is not None:
        resolved_markdown, _ = _markdown_from_candidate(candidate_transformation)
    if resolved_markdown is None:
        return None, remaining
    return (
        _DraftReviewContext(
            path=resolved_path,
            markdown=resolved_markdown,
            transformation=candidate_transformation,
            visual_extractions=tuple(extraction_items),
        ),
        remaining,
    )


def _fragment(prefix: str, value: object) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-") or "item"
    return f"{prefix}-{safe}"


def _unique_strings(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _reference_context(
    *,
    review: ReviewReport,
    draft: _DraftReviewContext | None,
    figures: Sequence[SourceFigure],
) -> tuple[
    list[tuple[str, object]],
    list[object],
    dict[str, str],
    list[str],
    list[str],
]:
    """Collect stable IDs and their renderer-only targets from draft and review contracts."""

    transformation = draft.transformation if draft is not None else None
    questions: list[tuple[str, object]] = []
    seen_questions: set[str] = set()
    for item in list(_as_items(_field(review, "questions", []))) + list(
        _as_items(_field(transformation, "questions", []))
    ):
        question_id = str(_field(item, "question_id", "")).strip()
        if question_id and question_id not in seen_questions:
            seen_questions.add(question_id)
            questions.append((question_id, item))

    gaps = _as_items(_field(transformation, "gaps", []))
    candidate_markdown = draft.markdown if draft is not None else ""
    gap_ids = _unique_strings(
        [*_field_values(gaps, "gap_id"), *_GAP_ID_RE.findall(candidate_markdown)]
    )
    gap_to_question: dict[str, str] = {}
    gap_by_id = {
        str(_field(item, "gap_id", "")): item for item in gaps if str(_field(item, "gap_id", ""))
    }
    for gap_id in gap_ids:
        gap = gap_by_id.get(gap_id)
        question_id = str(_field(gap, "question_id", "") or "").strip()
        if not question_id:
            question_id = _fragment("question", gap_id)
            synthetic = {
                "question_id": question_id,
                "prompt": f"Review the candidate gap {gap_id}.",
                "reason": str(
                    _field(gap, "description", "A structured gap remains in the candidate.")
                ),
                "context": "This candidate marker is review metadata, not a source fact.",
                "blocking": bool(_field(gap, "blocking", True)) if gap is not None else True,
                "evidence_span_ids": list(_as_items(_field(gap, "evidence_span_ids", [])))
                if gap is not None
                else [],
                "figure_ids": list(_as_items(_field(gap, "figure_ids", [])))
                if gap is not None
                else [],
                "suggestion": None,
            }
            if question_id not in seen_questions:
                seen_questions.add(question_id)
                questions.append((question_id, synthetic))
        if question_id:
            gap_to_question[gap_id] = question_id
            if question_id not in seen_questions:
                # A malformed or incomplete artifact should still produce a visible, anchored
                # reviewer context rather than an unlinked GAP marker.
                synthetic = {
                    "question_id": question_id,
                    "prompt": f"Review the decision associated with {gap_id}.",
                    "reason": "The candidate references this decision ID but supplied no question body.",
                    "context": "No additional question context was supplied in the draft artifacts.",
                    "blocking": bool(_field(gap, "blocking", True)) if gap is not None else True,
                    "evidence_span_ids": list(_as_items(_field(gap, "evidence_span_ids", [])))
                    if gap is not None
                    else [],
                    "figure_ids": list(_as_items(_field(gap, "figure_ids", [])))
                    if gap is not None
                    else [],
                    "suggestion": None,
                }
                seen_questions.add(question_id)
                questions.append((question_id, synthetic))

    question_markers = set(re.findall(r"\b(?:Q|QUESTION)-\d{3,}\b", candidate_markdown, re.I))
    for question_id in sorted(question_markers):
        if question_id not in seen_questions:
            seen_questions.add(question_id)
            questions.append(
                (
                    question_id,
                    {
                        "question_id": question_id,
                        "prompt": f"Review decision {question_id}.",
                        "reason": "The candidate contains a stable decision marker.",
                        "context": "No additional question context was supplied in the draft artifacts.",
                        "blocking": True,
                        "evidence_span_ids": [],
                        "figure_ids": [],
                        "suggestion": None,
                    },
                )
            )

    visual_extractions = list(draft.visual_extractions) if draft is not None else []
    figure_ids = _unique_strings([item.figure_id for item in figures])
    figure_ids.extend(
        [
            str(item)
            for item in _field_values(visual_extractions, "figure_id")
            if str(item) not in figure_ids
        ]
    )
    for collection_name in ("visual_references", "visual_extractions"):
        for item in _as_items(_field(transformation, collection_name, [])):
            figure_id = str(_field(item, "figure_id", ""))
            if figure_id and figure_id not in figure_ids:
                figure_ids.append(figure_id)
    for collection_name in ("gaps", "questions", "template_sections"):
        for item in _as_items(_field(transformation, collection_name, [])):
            for figure_id in _as_items(_field(item, "figure_ids", [])):
                if str(figure_id) and str(figure_id) not in figure_ids:
                    figure_ids.append(str(figure_id))

    source_span_ids: list[str] = []
    source_span_ids.extend(
        _unique_strings(_as_items(_field(transformation, "source_span_ids", [])))
    )
    for collection_name in (
        "source_dispositions",
        "template_sections",
        "gaps",
        "questions",
        "visual_references",
        "visual_extractions",
    ):
        for item in _as_items(_field(transformation, collection_name, [])):
            for field_name in ("source_span_id", "source_span_ids", "evidence_span_ids"):
                values = _field(item, field_name, [])
                if field_name == "source_span_id":
                    values = [values] if values else []
                source_span_ids.extend(_unique_strings(_as_items(values)))
    for _, item in questions:
        source_span_ids.extend(_unique_strings(_as_items(_field(item, "evidence_span_ids", []))))
    source_span_ids = _unique_strings(source_span_ids)
    figure_ids = _unique_strings(figure_ids)
    return questions, gaps, gap_to_question, source_span_ids, figure_ids


def _field_values(items: Sequence[object], field_name: str) -> list[object]:
    return [_field(item, field_name, "") for item in items if _field(item, field_name, "")]


def _question_anchor(question_id: object) -> str:
    return _fragment("question", question_id)


def _gap_anchor(gap_id: object) -> str:
    return _fragment("gap", gap_id)


def _span_anchor(span_id: object) -> str:
    return _fragment("source-span", span_id)


def _figure_anchor(figure_id: object) -> str:
    return _fragment("figure", figure_id)


def _visual_anchor(figure_id: object) -> str:
    return _fragment("visual", figure_id)


def _inside_html_tag(value: str, index: int) -> bool:
    return value.rfind("<", 0, index) > value.rfind(">", 0, index)


def _inside_html_anchor(value: str, index: int) -> bool:
    return value.rfind("<a", 0, index) > value.rfind("</a", 0, index)


def _linkify_references(
    rendered_body: str,
    *,
    gap_to_question: Mapping[str, str],
    question_ids: Sequence[str],
    figure_ids: Sequence[str],
    source_span_ids: Sequence[str],
) -> str:
    """Link known stable IDs in already escaped Markdown HTML without trusting source HTML."""

    targets: dict[str, tuple[str, str]] = {}
    for gap_id, question_id in gap_to_question.items():
        targets[gap_id] = (_question_anchor(question_id), "reference-gap")
    for question_id in question_ids:
        targets.setdefault(question_id, (_question_anchor(question_id), "reference-question"))
    for figure_id in figure_ids:
        targets.setdefault(figure_id, (_figure_anchor(figure_id), "reference-figure"))
    for span_id in source_span_ids:
        targets.setdefault(span_id, (_span_anchor(span_id), "reference-span"))
    if not targets:
        return rendered_body
    pattern = re.compile(
        "|".join(re.escape(value) for value in sorted(targets, key=len, reverse=True))
    )

    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        if _inside_html_tag(rendered_body, match.start()) or _inside_html_anchor(
            rendered_body, match.start()
        ):
            return token
        target, class_name = targets[token]
        return (
            f'<a class="{class_name}" href="#{html.escape(target, quote=True)}" '
            f'aria-label="Review evidence {html.escape(token, quote=True)}">'
            f"{html.escape(token)}</a>"
        )

    return pattern.sub(replace, rendered_body)


def _evidence_links(
    values: Sequence[object], *, kind: str, figure_targets: Mapping[str, str] | None = None
) -> str:
    links: list[str] = []
    for value in _unique_strings(values):
        if kind == "figure":
            target = (figure_targets or {}).get(value, _figure_anchor(value))
            label = value
        else:
            target = _span_anchor(value)
            label = value
        links.append(
            f'<a class="evidence-reference" href="#{html.escape(target, quote=True)}">'
            f"{html.escape(label)}</a>"
        )
    return ", ".join(links) or "none recorded"


def _render_question_context(
    *,
    questions: Sequence[tuple[str, object]],
    gaps: Sequence[object],
    gap_to_question: Mapping[str, str],
    figure_targets: Mapping[str, str],
) -> str:
    if not questions and not gaps:
        return ""
    gaps_by_question: dict[str, list[object]] = {}
    for gap in gaps:
        question_id = gap_to_question.get(str(_field(gap, "gap_id", "")))
        if question_id:
            gaps_by_question.setdefault(question_id, []).append(gap)
    cards: list[str] = []
    for question_id, question in questions:
        evidence_spans = list(_as_items(_field(question, "evidence_span_ids", [])))
        evidence_figures = list(_as_items(_field(question, "figure_ids", [])))
        for gap in gaps_by_question.get(question_id, []):
            evidence_spans.extend(_as_items(_field(gap, "evidence_span_ids", [])))
            evidence_figures.extend(_as_items(_field(gap, "figure_ids", [])))
        gap_badges = "".join(
            f'<a class="gap-badge" id="{html.escape(_gap_anchor(_field(gap, "gap_id", "")), quote=True)}" '
            f'href="#{html.escape(_question_anchor(question_id), quote=True)}">'
            f"{html.escape(str(_field(gap, 'gap_id', '')))}</a>"
            for gap in gaps_by_question.get(question_id, [])
        )
        suggestion = _field(question, "suggestion")
        suggestion_basis = _field(question, "suggestion_basis", "none")
        suggestion_html = (
            '<div class="question-suggestion"><strong>Suggestion for review only</strong>'
            f"<span>{html.escape(str(suggestion))}</span>"
            f"<small>Basis: {html.escape(str(suggestion_basis))}</small></div>"
            if suggestion
            else '<div class="question-suggestion empty"><strong>No safe suggestion</strong>'
            "<span>Supply an accountable, source-backed answer if one is needed.</span></div>"
        )
        cards.append(
            f'<article class="question-card" id="{html.escape(_question_anchor(question_id), quote=True)}" '
            f'data-question-id="{html.escape(question_id, quote=True)}">'
            f'<div class="question-card-head"><span class="question-id"><code>{html.escape(question_id)}</code></span>'
            f'<span class="question-state">{html.escape("BLOCKING" if _field(question, "blocking", True) else "NON-BLOCKING")}</span>'
            f"{gap_badges}</div>"
            f"<h3>{html.escape(str(_field(question, 'prompt', question_id)))}</h3>"
            f"<p><strong>Context:</strong> {html.escape(str(_field(question, 'context', '') or 'No additional context recorded.'))}</p>"
            f"<p><strong>Why this needs a decision:</strong> {html.escape(str(_field(question, 'reason', 'No reason recorded.')))}</p>"
            f'<p class="evidence-row"><strong>Evidence spans:</strong> '
            f"{_evidence_links(evidence_spans, kind='span')}<br><strong>Evidence figures:</strong> "
            f"{_evidence_links(evidence_figures, kind='figure', figure_targets=figure_targets)}</p>"
            f"{suggestion_html}"
            "</article>"
        )
    if not cards:
        return ""
    return (
        '<section class="question-context" aria-labelledby="question-context-heading">'
        '<div class="section-eyebrow">Linked decision context</div>'
        '<h2 id="question-context-heading">Questions, gaps, and evidence</h2>'
        "<p>These IDs are review metadata. They are not accepted facts, approvals, or final content. "
        "Use the editable decisions file to resolve them.</p>"
        f'<div class="question-card-grid">{"".join(cards)}</div>'
        "</section>"
    )


def _render_source_evidence_index(source_span_ids: Sequence[str]) -> str:
    if not source_span_ids:
        return ""
    items = "".join(
        f'<li id="{html.escape(_span_anchor(span_id), quote=True)}"><code>{html.escape(span_id)}</code>'
        " — source evidence anchor</li>"
        for span_id in source_span_ids
    )
    return (
        '<aside class="evidence-index" aria-label="Source evidence anchors">'
        "<h2>Linked source evidence</h2>"
        "<p>Stable span IDs below are navigation anchors for reviewer questions and candidate callouts; "
        "the source text remains unchanged.</p>"
        f"<ul>{items}</ul></aside>"
    )


def _visual_content_html(extraction: object) -> str:
    content = _field(extraction, "structured_content", {})
    cells = _field(content, "cells")
    if cells:
        rows = [list(_as_items(row)) for row in _as_items(cells)]
        rows = [[str(cell) for cell in row] for row in rows if row]
        if rows:
            header, *body = rows
            head_html = "".join(f"<th>{html.escape(cell)}</th>" for cell in header)
            body_html = "".join(
                "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
                for row in body
            )
            return (
                '<div class="visual-candidate-content"><div class="candidate-label">Candidate table conversion</div>'
                f'<table class="visual-table"><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table></div>'
            )
    mermaid = _field(content, "mermaid")
    if mermaid:
        return (
            '<div class="visual-candidate-content"><div class="candidate-label">Candidate diagram conversion</div>'
            f"<details><summary>Show candidate Mermaid</summary><pre>{html.escape(str(mermaid))}</pre></details></div>"
        )
    chart_values = _as_items(_field(content, "chart_values", []))
    if chart_values:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(_field(item, 'label', '')))}</td>"
            f"<td>{html.escape(str(_field(item, 'value', '')))}</td>"
            f"<td>{html.escape(str(_field(item, 'unit', '') or ''))}</td>"
            "</tr>"
            for item in chart_values
        )
        return (
            '<div class="visual-candidate-content"><div class="candidate-label">Candidate chart values</div>'
            '<table class="visual-table"><thead><tr><th>Label</th><th>Value</th><th>Unit</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
    summary = _field(content, "summary", "")
    return (
        f'<div class="visual-candidate-content"><div class="candidate-label">Candidate interpretation</div>'
        f"<p>{html.escape(str(summary or 'No structured conversion was supplied.'))}</p></div>"
    )


def _safe_asset_src(value: object) -> str:
    """Allow only caller-owned relative assets in the static report."""

    path = str(value or "")
    if (
        not path
        or "\\" in path
        or "?" in path
        or "#" in path
        or "%" in path
        or path.startswith("/")
        or re.match(r"^[a-z][a-z0-9+.-]*:", path, re.IGNORECASE)
    ):
        return ""
    parts = path.split("/")
    if (
        len(parts) < 3
        or any(part in {"", ".", ".."} for part in parts)
        or parts[:2] not in (["assets", "source"], ["assets", "final"])
    ):
        return ""
    return html.escape(path, quote=True)


def _render_visual_review(
    *,
    visual_extractions: Sequence[object],
    figure_targets: Mapping[str, str],
) -> str:
    if not visual_extractions:
        return ""
    cards: list[str] = []
    seen: set[str] = set()
    for extraction in visual_extractions:
        figure_id = str(_field(extraction, "figure_id", "")).strip()
        if not figure_id or figure_id in seen:
            continue
        seen.add(figure_id)
        status = str(_field(extraction, "status", "requires_review"))
        status_class = re.sub(r"[^a-z]+", "-", status.lower()).strip("-")
        kind = str(_field(extraction, "kind", "unknown")).replace("_", " ")
        warnings = list(_as_items(_field(extraction, "warnings", [])))
        content_warnings = _field(_field(extraction, "structured_content", {}), "warnings", [])
        warnings.extend(_as_items(content_warnings))
        warning_html = (
            '<ul class="visual-warnings">'
            + "".join(
                f"<li>{html.escape(str(item))}</li>" for item in dict.fromkeys(map(str, warnings))
            )
            + "</ul>"
            if warnings
            else ""
        )
        non_authoritative = (
            bool(_field(extraction, "non_authoritative", False)) or kind == "ui screenshot"
        )
        action = (
            "Compare this candidate conversion with the original figure, then explicitly accept or reject it."
            if status in {"best_effort", "requires_review", "extracted"}
            else "Retain the original figure; no converted content is available for acceptance."
        )
        authority_note = (
            "This visual is not authoritative source evidence; it is guidance only and is not an accepted source fact. It is not accepted or sealed."
            if non_authoritative or status in {"best_effort", "requires_review"}
            else "This remains a candidate conversion and is not accepted or sealed."
        )
        target = figure_targets.get(figure_id, _figure_anchor(figure_id))
        cards.append(
            f'<article class="visual-review-card status-{html.escape(status_class)}" '
            f'id="{html.escape(_visual_anchor(figure_id), quote=True)}">'
            f'<div class="visual-card-head"><h3><a href="#{html.escape(target, quote=True)}">'
            f"{html.escape(figure_id)}</a> · {html.escape(kind)}</h3>"
            f'<span class="visual-status">{html.escape(status.upper())}</span></div>'
            f'<p class="visual-authority-note"><strong>Reviewer action:</strong> {html.escape(action)} '
            f"{html.escape(authority_note)}</p>"
            f"{_visual_content_html(extraction)}{warning_html}</article>"
        )
    if not cards:
        return ""
    return (
        '<section class="visual-review" aria-labelledby="visual-review-heading">'
        '<div class="section-eyebrow">Source figure review</div>'
        '<h2 id="visual-review-heading">Converted visual candidates</h2>'
        "<p>Original source figures remain unchanged. Every conversion below is a bounded, unapproved "
        "candidate and must be checked against its linked <code>FIG-###</code> source.</p>"
        f'<div class="visual-review-grid">{"".join(cards)}</div></section>'
    )


def _render_candidate_status(
    *,
    gaps: Sequence[object],
    gap_to_question: Mapping[str, str],
    questions: Sequence[tuple[str, object]],
) -> str:
    def gap_target(gap: object) -> str:
        gap_id = str(_field(gap, "gap_id", ""))
        question_id = gap_to_question.get(gap_id)
        return _question_anchor(question_id) if question_id else _gap_anchor(gap_id)

    gap_items = "".join(
        f'<li><a class="gap-badge" href="#{html.escape(gap_target(gap), quote=True)}">'
        f"{html.escape(str(_field(gap, 'gap_id', '')))}</a> "
        f"{html.escape(str(_field(gap, 'description', 'Structured review marker.')))}</li>"
        for gap in gaps
        if _field(gap, "gap_id", "")
    )
    return (
        '<section class="candidate-status" aria-labelledby="candidate-status-heading">'
        '<div class="section-eyebrow">Stage 1 review gate</div>'
        '<h2 id="candidate-status-heading">Unapproved candidate draft</h2>'
        "<p>This draft is a proposed rewrite for human review. It is not final, not approved, not "
        "sealed, and must not be treated as authoritative or sent to retrieval consumers.</p>"
        + (
            f'<div class="candidate-gaps"><h3>Structured gaps ({len(gaps)})</h3><ul>{gap_items}</ul></div>'
            if gaps
            else '<p class="candidate-gaps">No structured gap artifacts were supplied; explicit rewrite approval is still required.</p>'
        )
        + (
            f'<p class="candidate-question-count">Linked decision contexts: {len(questions)}.</p>'
            if questions
            else ""
        )
        + "</section>"
    )


def _flow_svg(nodes: list[FlowNode], edges: list[FlowEdge], *, title: str) -> str:
    if not nodes:
        return (
            '<svg class="flow-svg" viewBox="0 0 900 150" role="img" '
            f'aria-label="{html.escape(title)}"><rect x="1" y="1" width="898" height="148" '
            'rx="18" fill="#f8fbfa" stroke="#cddcda"/><text x="450" y="82" '
            'text-anchor="middle" fill="#58706f" font-size="16">No process flow applicable</text></svg>'
        )
    node_width, node_height = 330, 82
    x_positions = (70, 500)
    row_gap = 118
    rows = (len(nodes) + 1) // 2
    height = max(210, 80 + rows * row_gap)
    positions: dict[str, tuple[int, int]] = {}
    node_parts: list[str] = []
    for index, node in enumerate(nodes):
        row = index // 2
        slot = index % 2
        column = slot if row % 2 == 0 else 1 - slot
        x, y = x_positions[column], 55 + row * row_gap
        positions[node.node_id] = (x, y)
        label_lines = textwrap.wrap(node.label, width=38, break_long_words=False)[:3] or [
            node.label
        ]
        line_start = y + 34 - (len(label_lines) - 1) * 9
        texts = "".join(
            f'<text x="{x + 18}" y="{line_start + line * 19}" fill="#173f40" '
            f'font-size="14" font-weight="650">{html.escape(value)}</text>'
            for line, value in enumerate(label_lines)
        )
        node_parts.append(
            f'<g><rect x="{x}" y="{y}" width="{node_width}" height="{node_height}" rx="14" '
            'fill="#ffffff" stroke="#83aaa6" stroke-width="1.5" filter="url(#shadow)"/>'
            f'<rect x="{x}" y="{y}" width="7" height="{node_height}" rx="4" fill="#d46b3c"/>'
            f"{texts}"
            f'<text x="{x + node_width - 15}" y="{y + node_height - 12}" text-anchor="end" '
            'fill="#718a88" font-size="10" font-weight="700" letter-spacing=".8">'
            f"{html.escape(node.node_type.upper())}</text></g>"
        )
    edge_parts: list[str] = []
    relation_colors = {
        "sequence": "#4f7774",
        "branch": "#a56a08",
        "escalation": "#b42318",
        "reference": "#6b6f91",
    }
    for edge in edges:
        if edge.source not in positions or edge.target not in positions:
            continue
        source_x, source_y = positions[edge.source]
        target_x, target_y = positions[edge.target]
        start_x, start_y = source_x + node_width / 2, source_y + node_height
        end_x, end_y = target_x + node_width / 2, target_y
        if target_y <= source_y:
            start_x, start_y = source_x + node_width, source_y + node_height / 2
            end_x, end_y = target_x, target_y + node_height / 2
        bend_y = (start_y + end_y) / 2
        color = relation_colors.get(edge.relation, "#4f7774")
        dash = ' stroke-dasharray="7 6"' if edge.relation == "reference" else ""
        edge_parts.append(
            f'<path d="M {start_x} {start_y} C {start_x} {bend_y}, {end_x} {bend_y}, '
            f'{end_x} {end_y}" fill="none" stroke="{color}" stroke-width="2"{dash} '
            'marker-end="url(#arrow)"/>'
        )
        if edge.relation != "sequence":
            edge_parts.append(
                f'<text x="{(start_x + end_x) / 2}" y="{bend_y - 6}" text-anchor="middle" '
                f'fill="{color}" font-size="10" font-weight="750">'
                f"{html.escape(edge.relation.upper())}</text>"
            )
    return (
        f'<svg class="flow-svg" viewBox="0 0 900 {height}" role="img" '
        f'aria-label="{html.escape(title)}">'
        "<defs>"
        '<filter id="shadow" x="-10%" y="-20%" width="120%" height="150%">'
        '<feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#123b3e" flood-opacity=".10"/>'
        "</filter>"
        '<marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" '
        'fill="#527b78"/></marker></defs>'
        f'<text x="450" y="26" text-anchor="middle" fill="#173f40" font-size="15" '
        f'font-weight="750">{html.escape(title)}</text>'
        f"{''.join(edge_parts)}{''.join(node_parts)}</svg>"
    )


def _stat_cards(
    review: ReviewReport, audit: AuditReport | None, *, candidate_present: bool = False
) -> str:
    counts = {"correct": 0, "improve": 0, "missing": 0}
    for item in review.section_assessments:
        counts[item.status] = counts.get(item.status, 0) + 1
    blocking = sum(1 for item in review.questions if item.blocking)
    audit_value = audit.status.upper() if audit else "PENDING"
    cards = (
        ("Sections", str(len(review.section_assessments)), "mapped to the selected recipe"),
        ("Correct", str(counts["correct"]), "sections meeting the mapped criteria"),
        ("Improve", str(counts["improve"]), "sections needing clearer evidence"),
        ("Missing", str(counts["missing"]), "required sections not yet supported"),
        ("Questions", str(blocking), "blocking decisions for the reviewer"),
        (
            "Draft audit" if candidate_present else "Final audit",
            audit_value,
            "preliminary candidate evidence; not a seal"
            if candidate_present
            else "deterministic promotion result",
        ),
    )
    return "".join(
        '<div class="stat">'
        f"<span>{html.escape(label)}</span>"
        f"<strong>{html.escape(value)}</strong>"
        f"<small>{html.escape(detail)}</small>"
        "</div>"
        for label, value, detail in cards
    )


def _tab_title(markdown: str, path: str, *, draft_first: bool, candidate: bool = False) -> str:
    if candidate:
        return "Candidate draft"
    if draft_first:
        compact = {
            "01-source-normalized.md": "Source",
            "03-macro-review.md": "Macro",
            "04-section-review.md": "Sections",
            "05-process-flow-review.md": "Flow",
            "06-review-questions.md": "Questions",
            "07-final-document.md": "Final document",
        }
        if Path(path).name in compact:
            return compact[Path(path).name]
    return _display_title(markdown, path)


def _ordered_documents(
    documents: Sequence[tuple[str, str]], *, draft_first: bool
) -> list[tuple[str, str]]:
    if not draft_first:
        return list(documents)
    rank = {
        "01-source-normalized.md": 10,
        "03-macro-review.md": 20,
        "04-section-review.md": 30,
        "05-process-flow-review.md": 40,
        "06-review-questions.md": 50,
    }
    return [
        item
        for _, item in sorted(
            enumerate(documents),
            key=lambda entry: (rank.get(Path(entry[1][0]).name, 100), entry[0]),
        )
    ]


def render_html_report(
    *,
    record: RunRecord,
    review: ReviewReport,
    documents: Sequence[tuple[str, str]],
    audit: AuditReport | None = None,
    figures: Sequence[SourceFigure] = (),
    draft: object | None = None,
    candidate_draft: object | None = None,
    candidate: object | None = None,
    draft_markdown: str | None = None,
    transformation: object | None = None,
    visual_extractions: Sequence[object] = (),
    draft_artifacts: Mapping[str, object] | None = None,
) -> str:
    """Render the draft-first reviewer and all available supporting reports.

    Existing callers can continue passing only ``documents``. Stage 1 callers may pass candidate
    Markdown, a transformation bundle with ``render_markdown``, or caller-owned frozen draft
    artifact content. This renderer never opens paths or fetches images.
    """

    draft_context, supporting_documents = _draft_context(
        documents=documents,
        draft=draft,
        candidate_draft=candidate_draft,
        candidate=candidate,
        draft_markdown=draft_markdown,
        transformation=transformation,
        visual_extractions=visual_extractions,
        draft_artifacts=draft_artifacts,
    )
    candidate_present = draft_context is not None
    supporting_documents = _ordered_documents(supporting_documents, draft_first=candidate_present)
    question_items, gaps, gap_to_question, source_span_ids, figure_ids = _reference_context(
        review=review,
        draft=draft_context,
        figures=figures,
    )
    figure_targets = {figure_id: _figure_anchor(figure_id) for figure_id in figure_ids}
    visual_items = draft_context.visual_extractions if draft_context is not None else ()
    source_figure_ids = {figure.figure_id for figure in figures}
    for extraction in visual_items:
        figure_id = str(_field(extraction, "figure_id", ""))
        if figure_id and figure_id not in source_figure_ids:
            figure_targets[figure_id] = _visual_anchor(figure_id)

    markdown = _markdown_renderer()
    rendered: list[tuple[str, str, str, str]] = []
    if draft_context is not None:
        candidate_body = markdown.render(draft_context.markdown, {})
        candidate_body = _linkify_references(
            candidate_body,
            gap_to_question=gap_to_question,
            question_ids=[item[0] for item in question_items],
            figure_ids=figure_ids,
            source_span_ids=source_span_ids,
        )
        candidate_body = (
            _render_candidate_status(
                gaps=gaps,
                gap_to_question=gap_to_question,
                questions=question_items,
            )
            + f'<div class="candidate-markdown">{candidate_body}</div>'
            + _render_visual_review(
                visual_extractions=visual_items,
                figure_targets=figure_targets,
            )
        )
        rendered.append((draft_context.path, "Candidate draft", "candidate-draft", candidate_body))

    question_document_present = False
    for path, content in supporting_documents:
        path_name = Path(path).name
        question_document_present = (
            question_document_present or path_name == "06-review-questions.md"
        )
        environment: dict[str, Any] = {}
        if path_name == "05-process-flow-review.md":
            environment["mermaid_svgs"] = [
                _flow_svg(review.flow_nodes, review.flow_edges, title="Inferred source process"),
                _flow_svg(
                    review.proposed_flow_nodes,
                    review.proposed_flow_edges,
                    title="Proposed reviewed process",
                ),
            ]
        body = markdown.render(content, environment).replace(
            'src="../assets/final/', 'src="assets/final/'
        )
        body = _linkify_references(
            body,
            gap_to_question=gap_to_question,
            question_ids=[item[0] for item in question_items],
            figure_ids=figure_ids,
            source_span_ids=source_span_ids,
        )
        if path_name == "01-source-normalized.md":
            body = _render_source_evidence_index(source_span_ids) + body
        if path_name == "06-review-questions.md":
            body = (
                _render_question_context(
                    questions=question_items,
                    gaps=gaps,
                    gap_to_question=gap_to_question,
                    figure_targets=figure_targets,
                )
                + body
            )
        rendered.append(
            (path, _tab_title(content, path, draft_first=candidate_present), _anchor(path), body)
        )

    if candidate_present and question_items and not question_document_present:
        question_path = "markdown/06-review-questions.md"
        rendered.append(
            (
                question_path,
                "Questions",
                _anchor(question_path),
                _render_question_context(
                    questions=question_items,
                    gaps=gaps,
                    gap_to_question=gap_to_question,
                    figure_targets=figure_targets,
                ),
            )
        )

    navigation = "".join(
        f'<button type="button" class="report-tab" id="tab-{anchor}" role="tab" '
        f'aria-controls="{anchor}" aria-selected="{str(index == 1).lower()}" '
        f'tabindex="{0 if index == 1 else -1}" data-target="{anchor}">'
        f'<span class="tab-number">{index:02d}</span>'
        f'<span class="tab-name">{html.escape(title)}</span></button>'
        for index, (_, title, anchor, _) in enumerate(rendered, start=1)
    )
    articles = "".join(
        f'<article id="{anchor}" class="report-card" data-report="{index}" role="tabpanel" '
        f'aria-labelledby="tab-{anchor}" tabindex="0"{"" if index == 1 else " hidden"}>'
        '<div class="report-kicker">'
        + (
            f"Candidate draft · UNAPPROVED · {html.escape(path)}"
            if anchor == "candidate-draft"
            else f"Report {index:02d} · {html.escape(title)} · {html.escape(path)}"
        )
        + "</div>"
        f'<div class="markdown-body">{body}</div>'
        "</article>"
        for index, (path, title, anchor, body) in enumerate(rendered, start=1)
    )
    status_class = re.sub(r"[^a-z]+", "-", record.status.lower()).strip("-")
    phase = record.phase.replace("_", " ").title()
    if candidate_present:
        status_class = "draft"
        audit_summary = (
            "This is an unapproved Stage 1 candidate draft. It is not final, sealed, or authoritative. "
            + (
                audit.summary
                if audit
                else "Review the candidate, answer the decision file, and run Stage 2 on this exact run."
            )
        )
        hero_eyebrow = "Stage 1 candidate · human review required"
        status_label = "DRAFT · UNAPPROVED"
    else:
        audit_summary = (
            audit.summary
            if audit
            else "Stage 1 is ready for human review. Read the reports in order, answer the decision "
            "file, and run Stage 2 on this exact run to produce the final document and audit."
        )
        hero_eyebrow = "Governed document review"
        status_label = record.status.upper()
    document_label = re.sub(r"[_-]+", " ", Path(record.source_name).stem).title()
    document_label = re.sub(r"\bAi\b", "AI", document_label)
    figure_gallery = ""
    if figures:
        cards = []
        for figure in figures:
            caption = figure.caption or "Source screenshot"
            section_ids = sorted(
                {
                    occurrence.section_id
                    for occurrence in figure.occurrences
                    if occurrence.section_id
                }
            )
            context = ", ".join(section_ids) or "source document"
            cards.append(
                f'<figure id="{html.escape(_figure_anchor(figure.figure_id), quote=True)}" class="source-figure">'
                f'<img src="{_safe_asset_src(figure.source_path)}" '
                f'alt="{html.escape(caption)}" loading="lazy">'
                f"<figcaption><strong>{html.escape(figure.figure_id)}</strong> · "
                f"{html.escape(caption)}<small>{html.escape(context)} · source evidence; "
                "any conversion remains unapproved</small></figcaption>"
                "</figure>"
            )
        figure_gallery = (
            '<section class="figure-gallery"><div class="figure-gallery-head">'
            "<h2>Source screenshots</h2>"
            "<p>These original figures are preserved source evidence. Any converted table, chart, "
            "or diagram remains a candidate for reviewer acceptance.</p></div>"
            f'<div class="figure-grid">{"".join(cards)}</div></section>'
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Document Enhancer · {html.escape(record.source_name)}</title>
  <style>
    :root {{
      --ink: #403a49; --muted: #766f80; --line: #e7dfeb; --paper: #fffdf9;
      --canvas: #f7f4fa; --lavender: #8c7baa; --lavender-soft: #eee8f5;
      --sage: #7faaa0; --sage-soft: #e7f1ed; --rose: #c98f96; --rose-soft: #f7e8e8;
      --peach: #d6a178; --peach-soft: #faeee3; --butter: #eadcae; --danger: #a85e69;
      --shadow: 0 18px 48px rgba(73, 57, 87, .09);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background: radial-gradient(circle at top left, #fbf1f3 0, transparent 32rem), var(--canvas); color: var(--ink); font: 16px/1.68 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .shell {{ min-height: 100vh; }}
    .workspace-bar {{ position: sticky; top: 0; z-index: 20; padding: 14px clamp(18px, 4vw, 54px) 13px; border-bottom: 1px solid var(--line); background: rgba(255, 253, 249, .94); box-shadow: 0 8px 28px rgba(74, 58, 87, .07); backdrop-filter: blur(18px); }}
    .workspace-head {{ max-width: 1240px; margin: 0 auto 12px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }}
    .brand {{ display: flex; gap: 11px; align-items: center; color: var(--ink); }}
    .brand-mark {{ width: 40px; height: 40px; display: grid; place-items: center; border-radius: 14px; background: linear-gradient(145deg, var(--lavender-soft), #dfd4ec); color: #66557f; font-weight: 850; box-shadow: inset 0 0 0 1px #d5c9e2; }}
    .brand strong {{ display: block; letter-spacing: -.02em; }}
    .brand small {{ display: block; color: var(--muted); font-size: 12px; }}
    .tab-intro {{ color: var(--muted); font-size: 12px; text-align: right; }}
    .tabs {{ max-width: 1240px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 8px; padding: 2px 2px 7px; }}
    .report-tab {{ min-width: 0; min-height: 64px; display: grid; grid-template-columns: 25px minmax(0, 1fr); gap: 6px; align-items: center; padding: 8px 9px; border: 1px solid #ddd3e6; border-radius: 13px; background: var(--lavender-soft); color: #665b72; cursor: pointer; font: inherit; text-align: left; transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; }}
    .report-tab:nth-child(3n+2) {{ background: var(--sage-soft); border-color: #d0e2dc; }}
    .report-tab:nth-child(3n) {{ background: var(--rose-soft); border-color: #ead3d5; }}
    .report-tab:hover {{ transform: translateY(-2px); box-shadow: 0 7px 18px rgba(87, 68, 100, .09); }}
    .report-tab[aria-selected="true"] {{ border-color: var(--lavender); background: #fff; color: #564663; box-shadow: 0 0 0 2px #ded4e8, 0 8px 20px rgba(87, 68, 100, .12); }}
    .tab-number {{ color: var(--lavender); font: 800 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .tab-name {{ display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 3; font-size: 10.5px; font-weight: 750; line-height: 1.2; }}
    main {{ min-width: 0; padding: 32px clamp(18px, 5vw, 64px) 96px; }}
    .hero {{ max-width: 1120px; margin: 0 auto 24px; padding: clamp(28px, 5vw, 52px); overflow: hidden; position: relative; border: 1px solid #dfd4e6; border-radius: 27px; color: #4f4559; background: linear-gradient(135deg, #eee7f5 0%, #f6e7e7 50%, #e7f1ed 100%); box-shadow: var(--shadow); }}
    .hero:after {{ content: ""; position: absolute; width: 310px; height: 310px; right: -125px; top: -165px; border: 48px solid rgba(255,255,255,.42); border-radius: 50%; }}
    .eyebrow {{ margin: 0 0 10px; color: #7d6a96; font-weight: 800; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; }}
    .hero h1 {{ position: relative; margin: 0; max-width: 820px; overflow-wrap: anywhere; color: #493f52; font: 750 clamp(32px, 5vw, 55px)/1.05 Georgia, "Times New Roman", serif; letter-spacing: -.035em; }}
    .hero-summary {{ max-width: 850px; margin: 20px 0 0; color: #6d6474; font-size: 17px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 24px; }}
    .pill {{ padding: 7px 11px; border: 1px solid rgba(119,101,132,.18); border-radius: 999px; background: rgba(255,255,255,.5); color: #675c70; font-size: 12px; }}
    .pill.status-succeeded {{ background: #dcece5; border-color: #b8d4ca; color: #476f65; }}
    .pill.status-waiting {{ background: #f5eac6; border-color: #e4d39a; color: #7d6b33; }}
    .pill.status-draft {{ background: #f8e2d5; border-color: #e2b99f; color: #9b4f2f; font-weight: 850; }}
    .stats {{ max-width: 1120px; margin: 0 auto 24px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .stat {{ min-width: 0; padding: 20px; border: 1px solid var(--line); border-radius: 17px; background: rgba(255,253,249,.88); box-shadow: 0 8px 24px rgba(74,58,87,.05); }}
    .stat:nth-child(2) {{ background: var(--sage-soft); }} .stat:nth-child(3) {{ background: var(--rose-soft); }}
    .stat span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: .07em; }}
    .stat strong {{ display: block; margin: 4px 0; color: #74628e; font: 750 30px/1.15 Georgia, serif; }}
    .stat small {{ display: block; color: var(--muted); line-height: 1.35; }}
    .report-card {{ max-width: 1120px; margin: 0 auto 24px; padding: clamp(25px, 4vw, 56px); border: 1px solid var(--line); border-radius: 23px; background: var(--paper); box-shadow: var(--shadow); scroll-margin-top: 150px; }}
    .report-card[hidden] {{ display: none; }}
    .candidate-status, .question-context, .visual-review, .evidence-index {{ margin: 0 0 28px; padding: 22px; border: 1px solid #e4d7e8; border-radius: 17px; background: #fbf5fa; }}
    .candidate-status {{ border-color: #e2b99f; background: #fff5ed; }}
    .candidate-status h2, .question-context h2, .visual-review h2, .evidence-index h2 {{ margin: 0 0 10px; color: #554760; font: 750 27px/1.2 Georgia, serif; }}
    .candidate-status h3 {{ margin: 22px 0 8px; color: #754b3c; font-size: 17px; }}
    .candidate-status p, .question-context > p, .visual-review > p, .evidence-index > p {{ margin: 0 0 14px; color: var(--muted); }}
    .section-eyebrow {{ margin-bottom: 6px; color: #9b4f2f; font-size: 11px; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }}
    .candidate-markdown {{ padding: 22px; border: 2px solid #e2b99f; border-radius: 17px; background: #fffdfa; }}
    .candidate-markdown:before {{ content: "UNAPPROVED CANDIDATE CONTENT"; display: block; margin-bottom: 16px; color: #9b4f2f; font-size: 11px; font-weight: 850; letter-spacing: .12em; }}
    .candidate-gaps ul, .visual-warnings, .evidence-index ul {{ margin: 8px 0 0; padding-left: 22px; }}
    .gap-badge {{ display: inline-block; padding: 2px 7px; border: 1px solid #e2b99f; border-radius: 999px; background: #fff0e6; color: #984a2d; font: 750 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; text-decoration: none; }}
    .question-card-grid, .visual-review-grid {{ display: grid; gap: 14px; }}
    .question-card, .visual-review-card {{ padding: 17px; border: 1px solid #e4d7e8; border-radius: 14px; background: #fffdfa; }}
    .question-card-head, .visual-card-head {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 7px; }}
    .question-id {{ color: #74628e; font-weight: 800; }}
    .question-state, .visual-status {{ padding: 3px 7px; border-radius: 999px; background: #f5eac6; color: #7d6b33; font-size: 10px; font-weight: 850; letter-spacing: .08em; }}
    .question-card h3, .visual-review-card h3 {{ margin: 7px 0 10px; color: #554760; font: 700 20px/1.25 Georgia, serif; }}
    .question-card p, .visual-review-card p {{ margin: 8px 0; }}
    .question-suggestion {{ display: grid; gap: 3px; margin-top: 13px; padding: 10px 12px; border-left: 3px solid var(--sage); background: var(--sage-soft); color: #49645f; }}
    .question-suggestion.empty {{ border-left-color: var(--rose); background: var(--rose-soft); color: #76565c; }}
    .question-suggestion small {{ color: var(--muted); font-size: 11px; }}
    .evidence-row {{ color: var(--muted); font-size: 13px; }}
    .evidence-reference, .evidence-index a {{ color: #74628e; font-weight: 750; }}
    .visual-review {{ border-color: #d0e2dc; background: var(--sage-soft); }}
    .visual-review-card {{ border-color: #b7d2ca; background: #fbfffd; }}
    .visual-card-head {{ justify-content: space-between; }}
    .visual-authority-note {{ color: #556e69; }}
    .visual-candidate-content {{ margin-top: 14px; padding: 12px; border: 1px dashed #b7d2ca; border-radius: 10px; background: #fff; }}
    .candidate-label {{ margin-bottom: 6px; color: #4f7774; font-size: 11px; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; }}
    .visual-table {{ margin: 10px 0 0; }}
    .visual-warnings {{ color: #8b4e3f; font-size: 13px; }}
    .evidence-index {{ padding: 15px 18px; background: #f7f4fa; }}
    .evidence-index h2 {{ font-size: 20px; }}
    .evidence-index li {{ margin: 4px 0; color: var(--muted); font-size: 13px; }}
    .report-kicker {{ margin-bottom: 28px; padding-bottom: 13px; border-bottom: 1px solid var(--line); color: var(--rose); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .markdown-body {{ max-width: 900px; margin: 0 auto; }}
    .markdown-body h1, .markdown-body h2, .markdown-body h3 {{ color: #554760; font-family: Georgia, "Times New Roman", serif; letter-spacing: -.022em; line-height: 1.2; }}
    .markdown-body h1 {{ margin: 0 0 26px; font-size: clamp(32px, 4vw, 46px); }}
    .markdown-body h2 {{ margin: 42px 0 16px; padding-top: 10px; font-size: 28px; }}
    .markdown-body h3 {{ margin: 30px 0 12px; font-size: 21px; }}
    .markdown-body p {{ margin: 0 0 17px; }}
    .markdown-body a {{ color: #74628e; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .markdown-body ul, .markdown-body ol {{ padding-left: 24px; }}
    .markdown-body li {{ margin: 6px 0; }}
    .markdown-body code {{ padding: 2px 6px; border-radius: 6px; background: var(--lavender-soft); color: #65527c; font-size: .88em; }}
    pre {{ overflow-x: auto; padding: 18px; border-radius: 12px; background: #4c4355; color: #fffaf5; }}
    pre code {{ padding: 0 !important; background: transparent !important; color: inherit !important; }}
    table {{ width: 100%; margin: 22px 0; border-collapse: collapse; font-size: 14px; }}
    th {{ background: var(--lavender-soft); color: #554760; text-align: left; }}
    th, td {{ padding: 11px 13px; border: 1px solid #ded5e4; vertical-align: top; }}
    tr:nth-child(even) td {{ background: #fcf8fb; }}
    blockquote {{ margin: 22px 0; padding: 13px 19px; border-left: 4px solid var(--rose); background: var(--rose-soft); color: #6a555b; }}
    .diagram-shell {{ margin: 24px 0; padding: 18px; overflow-x: auto; border: 1px solid #d8d0e0; border-radius: 16px; background: linear-gradient(180deg, #fffdfb, var(--sage-soft)); }}
    .figure-gallery {{ max-width: 1120px; margin: 0 auto 24px; padding: 28px; border: 1px solid var(--line); border-radius: 23px; background: var(--paper); box-shadow: var(--shadow); }}
    .figure-gallery-head h2 {{ margin: 0 0 8px; color: #554760; font-family: Georgia, serif; }}
    .figure-gallery-head p {{ margin: 0 0 20px; color: var(--muted); }}
    .figure-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
    .source-figure {{ margin: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 14px; background: #fff; }}
    .source-figure img {{ display: block; width: 100%; max-height: 260px; object-fit: contain; background: #f7f4f8; }}
    .source-figure figcaption {{ display: block; padding: 12px; color: #554760; }}
    .source-figure figcaption small {{ display: block; margin-top: 4px; color: var(--muted); }}
    .diagram-label {{ margin-bottom: 12px; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .flow-svg {{ display: block; width: 100%; min-width: 620px; height: auto; }}
    .mermaid-source {{ margin-top: 12px; text-align: left; }}
    details {{ margin-top: 12px; }} details summary {{ cursor: pointer; color: #74628e; font-size: 12px; font-weight: 750; }}
    @media (max-width: 900px) {{ .tabs {{ display: flex; overflow-x: auto; scrollbar-color: #cfc3da transparent; }} .report-tab {{ flex: 0 0 145px; }} }}
    @media (max-width: 760px) {{ .workspace-head {{ align-items: flex-start; }} .tab-intro {{ display: none; }} main {{ padding: 22px 12px 64px; }} .stats {{ grid-template-columns: 1fr 1fr; }} }}
    @media (max-width: 520px) {{ .stats {{ grid-template-columns: 1fr; }} .report-card {{ padding: 24px 18px; }} .brand small {{ display: none; }} }}
    @media print {{ .workspace-bar {{ display: none; }} main {{ padding: 0; }} .hero, .report-card, .stat {{ box-shadow: none; }} .report-card, .report-card[hidden] {{ display: block !important; border: 0; border-radius: 0; page-break-before: always; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="workspace-bar">
      <div class="workspace-head">
        <div class="brand"><div class="brand-mark">DE</div><div><strong>Document Enhancer</strong><small>Review workspace</small></div></div>
        <div class="tab-intro">Choose a report tab · read left to right</div>
      </div>
      <nav class="tabs" role="tablist" aria-label="Numbered document reports">{navigation}</nav>
    </header>
    <main>
      <header class="hero">
        <p class="eyebrow">{html.escape(hero_eyebrow)}</p>
        <h1>{html.escape(document_label)}</h1>
        <p class="hero-summary">{html.escape(audit_summary)}</p>
        <div class="meta">
          <span class="pill status-{status_class}">{html.escape(status_label)}</span>
          <span class="pill">Phase · {html.escape(phase)}</span>
          <span class="pill">Recipe · {html.escape(record.recipe)}</span>
          <span class="pill">Run · {html.escape(record.run_id)}</span>
        </div>
      </header>
      <section class="stats">{_stat_cards(review, audit, candidate_present=candidate_present)}</section>
      {figure_gallery}
      {articles}
    </main>
  </div>
  <script>
    (() => {{
      const tabs = Array.from(document.querySelectorAll('.report-tab'));
      const panels = Array.from(document.querySelectorAll('.report-card'));
      function selectTab(target, updateHash = true) {{
        const chosen = tabs.find((tab) => tab.dataset.target === target) || tabs[0];
        if (!chosen) return;
        tabs.forEach((tab) => {{
          const selected = tab === chosen;
          tab.setAttribute('aria-selected', String(selected));
          tab.setAttribute('tabindex', selected ? '0' : '-1');
        }});
        panels.forEach((panel) => {{ panel.hidden = panel.id !== chosen.dataset.target; }});
        if (updateHash) window.history.replaceState(null, '', '#' + chosen.dataset.target);
      }}
      tabs.forEach((tab, index) => {{
        tab.addEventListener('click', () => selectTab(tab.dataset.target));
        tab.addEventListener('keydown', (event) => {{
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          let next = index;
          if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
          if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
          if (event.key === 'Home') next = 0;
          if (event.key === 'End') next = tabs.length - 1;
          tabs[next].focus();
          selectTab(tabs[next].dataset.target);
        }});
      }});
      selectTab(window.location.hash.slice(1), false);
      window.addEventListener('hashchange', () => selectTab(window.location.hash.slice(1), false));
    }})();
  </script>
</body>
</html>
"""


__all__ = ["render_html_report"]
