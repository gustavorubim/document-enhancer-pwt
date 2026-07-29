"""Generate a polished, static reviewer for the numbered Markdown reports."""

from __future__ import annotations

import html
import re
import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def _stat_cards(review: ReviewReport, audit: AuditReport | None) -> str:
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
        ("Final audit", audit_value, "deterministic promotion result"),
    )
    return "".join(
        '<div class="stat">'
        f"<span>{html.escape(label)}</span>"
        f"<strong>{html.escape(value)}</strong>"
        f"<small>{html.escape(detail)}</small>"
        "</div>"
        for label, value, detail in cards
    )


def render_html_report(
    *,
    record: RunRecord,
    review: ReviewReport,
    documents: Sequence[tuple[str, str]],
    audit: AuditReport | None = None,
    figures: Sequence[SourceFigure] = (),
) -> str:
    """Render every available numbered Markdown artifact into one static HTML file."""

    markdown = _markdown_renderer()
    rendered = []
    for path, content in documents:
        environment: dict[str, Any] = {}
        if Path(path).name == "05-process-flow-review.md":
            environment["mermaid_svgs"] = [
                _flow_svg(review.flow_nodes, review.flow_edges, title="Inferred source process"),
                _flow_svg(
                    review.proposed_flow_nodes,
                    review.proposed_flow_edges,
                    title="Proposed reviewed process",
                ),
            ]
        rendered.append(
            (
                path,
                _display_title(content, path),
                _anchor(path),
                markdown.render(content, environment).replace(
                    'src="../assets/final/', 'src="assets/final/'
                ),
            )
        )
    navigation = "".join(
        f'<button class="report-tab" id="tab-{anchor}" role="tab" '
        f'aria-controls="{anchor}" aria-selected="false" data-target="{anchor}">'
        f'<span class="tab-number">{index:02d}</span>'
        f'<span class="tab-name">{html.escape(title)}</span></button>'
        for index, (_, title, anchor, _) in enumerate(rendered, start=1)
    )
    articles = "".join(
        f'<article id="{anchor}" class="report-card" data-report="{index}" role="tabpanel" '
        f'aria-labelledby="tab-{anchor}" hidden>'
        '<div class="report-kicker">'
        f"Report {index:02d} · {html.escape(title)} · {html.escape(path)}"
        "</div>"
        f'<div class="markdown-body">{body}</div>'
        "</article>"
        for index, (path, title, anchor, body) in enumerate(rendered, start=1)
    )
    status_class = re.sub(r"[^a-z]+", "-", record.status.lower()).strip("-")
    phase = record.phase.replace("_", " ").title()
    audit_summary = (
        audit.summary
        if audit
        else "Stage 1 is ready for human review. Read the reports in order, answer the decision "
        "file, and run Stage 2 on this exact run to produce the final document and audit."
    )
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
                '<figure class="source-figure">'
                f'<img src="{html.escape(figure.source_path)}" '
                f'alt="{html.escape(caption)}" loading="lazy">'
                f"<figcaption><strong>{html.escape(figure.figure_id)}</strong> · "
                f"{html.escape(caption)}<small>{html.escape(context)}</small></figcaption>"
                "</figure>"
            )
        figure_gallery = (
            '<section class="figure-gallery"><div class="figure-gallery-head">'
            "<h2>Source screenshots</h2>"
            "<p>These figures will be referenced from the rewritten document and preserved in "
            "its appendix when the rewrite is approved.</p></div>"
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
    .stats {{ max-width: 1120px; margin: 0 auto 24px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .stat {{ min-width: 0; padding: 20px; border: 1px solid var(--line); border-radius: 17px; background: rgba(255,253,249,.88); box-shadow: 0 8px 24px rgba(74,58,87,.05); }}
    .stat:nth-child(2) {{ background: var(--sage-soft); }} .stat:nth-child(3) {{ background: var(--rose-soft); }}
    .stat span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: .07em; }}
    .stat strong {{ display: block; margin: 4px 0; color: #74628e; font: 750 30px/1.15 Georgia, serif; }}
    .stat small {{ display: block; color: var(--muted); line-height: 1.35; }}
    .report-card {{ max-width: 1120px; margin: 0 auto 24px; padding: clamp(25px, 4vw, 56px); border: 1px solid var(--line); border-radius: 23px; background: var(--paper); box-shadow: var(--shadow); scroll-margin-top: 150px; }}
    .report-card[hidden] {{ display: none; }}
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
        <p class="eyebrow">Governed document review</p>
        <h1>{html.escape(document_label)}</h1>
        <p class="hero-summary">{html.escape(audit_summary)}</p>
        <div class="meta">
          <span class="pill status-{status_class}">{html.escape(record.status.upper())}</span>
          <span class="pill">Phase · {html.escape(phase)}</span>
          <span class="pill">Recipe · {html.escape(record.recipe)}</span>
          <span class="pill">Run · {html.escape(record.run_id)}</span>
        </div>
      </header>
      <section class="stats">{_stat_cards(review, audit)}</section>
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
        tabs.forEach((tab) => tab.setAttribute('aria-selected', String(tab === chosen)));
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
