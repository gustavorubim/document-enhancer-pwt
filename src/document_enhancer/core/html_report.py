"""Generate a polished, static reviewer for the numbered Markdown reports."""

from __future__ import annotations

import html
import re
import textwrap
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from .models import AuditReport, FlowEdge, FlowNode, ReviewReport, RunRecord


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
            (path, _title(content, path), _anchor(path), markdown.render(content, environment))
        )
    navigation = "".join(
        f'<a href="#{anchor}"><span>{index:02d}</span>{html.escape(title)}</a>'
        for index, (_, title, anchor, _) in enumerate(rendered, start=1)
    )
    articles = "".join(
        f'<article id="{anchor}" class="report-card" data-report="{index}">'
        '<div class="report-kicker">'
        f"Report {index:02d} · {html.escape(path)}"
        "</div>"
        f'<div class="markdown-body">{body}</div>'
        "</article>"
        for index, (path, _, anchor, body) in enumerate(rendered, start=1)
    )
    status_class = re.sub(r"[^a-z]+", "-", record.status.lower()).strip("-")
    phase = record.phase.replace("_", " ").title()
    audit_summary = (
        audit.summary
        if audit
        else "Stage 1 is ready for human review. Read the reports in order, answer the decision "
        "file, and continue this exact run to produce the final document and audit."
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
      --ink: #17202a; --muted: #667085; --line: #dce3e9; --paper: #ffffff;
      --canvas: #f3f6f4; --nav: #102a2e; --nav-soft: #173b40; --accent: #d46b3c;
      --teal: #167d75; --gold: #a56a08; --danger: #b42318; --shadow: 0 18px 48px rgba(16,42,46,.10);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; background: var(--canvas); color: var(--ink); font: 16px/1.68 Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .shell {{ display: grid; grid-template-columns: 290px minmax(0, 1fr); min-height: 100vh; }}
    aside {{ position: sticky; top: 0; height: 100vh; overflow-y: auto; padding: 32px 24px; background: var(--nav); color: white; }}
    .brand {{ display: flex; gap: 12px; align-items: center; margin-bottom: 32px; }}
    .brand-mark {{ width: 42px; height: 42px; display: grid; place-items: center; border-radius: 13px; background: var(--accent); font-weight: 800; }}
    .brand strong {{ display: block; letter-spacing: -.02em; }}
    .brand small {{ color: #afc7c9; }}
    nav p {{ margin: 0 0 10px; color: #86a9ad; font-size: 11px; font-weight: 800; letter-spacing: .13em; text-transform: uppercase; }}
    nav a {{ display: grid; grid-template-columns: 28px 1fr; gap: 9px; align-items: start; padding: 10px 8px; border-radius: 10px; color: #d9e7e8; text-decoration: none; font-size: 13px; line-height: 1.35; }}
    nav a:hover {{ background: var(--nav-soft); color: white; }}
    nav a span {{ color: #f3a17c; font: 700 11px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .aside-note {{ margin-top: 28px; padding: 16px; border: 1px solid #2b5054; border-radius: 12px; color: #b9cdcf; font-size: 12px; }}
    main {{ min-width: 0; padding: 42px clamp(22px, 5vw, 76px) 96px; }}
    .hero {{ max-width: 1100px; margin: 0 auto 28px; padding: clamp(28px, 5vw, 56px); overflow: hidden; position: relative; border-radius: 24px; color: white; background: linear-gradient(130deg, #123b3e 0%, #17675f 67%, #21867a 100%); box-shadow: var(--shadow); }}
    .hero:after {{ content: ""; position: absolute; width: 300px; height: 300px; right: -120px; top: -150px; border: 52px solid rgba(255,255,255,.08); border-radius: 50%; }}
    .eyebrow {{ margin: 0 0 10px; color: #9dd8d0; font-weight: 800; font-size: 12px; letter-spacing: .14em; text-transform: uppercase; }}
    .hero h1 {{ position: relative; margin: 0; max-width: 780px; font: 750 clamp(32px, 5vw, 55px)/1.05 Georgia, "Times New Roman", serif; letter-spacing: -.035em; }}
    .hero-summary {{ max-width: 820px; margin: 20px 0 0; color: #d8ece9; font-size: 17px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 9px; margin-top: 24px; }}
    .pill {{ padding: 7px 11px; border: 1px solid rgba(255,255,255,.24); border-radius: 999px; background: rgba(255,255,255,.08); font-size: 12px; }}
    .pill.status-succeeded {{ background: rgba(134,239,172,.18); border-color: rgba(134,239,172,.5); }}
    .pill.status-waiting {{ background: rgba(253,230,138,.16); border-color: rgba(253,230,138,.48); }}
    .stats {{ max-width: 1100px; margin: 0 auto 28px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .stat {{ min-width: 0; padding: 20px; border: 1px solid var(--line); border-radius: 16px; background: var(--paper); box-shadow: 0 8px 24px rgba(16,42,46,.05); }}
    .stat span {{ display: block; color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; letter-spacing: .07em; }}
    .stat strong {{ display: block; margin: 4px 0; color: var(--teal); font: 750 30px/1.15 Georgia, serif; }}
    .stat small {{ display: block; color: var(--muted); line-height: 1.35; }}
    .report-card {{ max-width: 1100px; margin: 0 auto 24px; padding: clamp(25px, 4vw, 55px); border: 1px solid var(--line); border-radius: 20px; background: var(--paper); box-shadow: var(--shadow); scroll-margin-top: 20px; }}
    .report-kicker {{ margin-bottom: 28px; padding-bottom: 13px; border-bottom: 1px solid var(--line); color: var(--accent); font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .markdown-body {{ max-width: 860px; margin: 0 auto; }}
    .markdown-body h1, .markdown-body h2, .markdown-body h3 {{ color: #163b3e; font-family: Georgia, "Times New Roman", serif; letter-spacing: -.022em; line-height: 1.2; }}
    .markdown-body h1 {{ margin: 0 0 26px; font-size: clamp(32px, 4vw, 46px); }}
    .markdown-body h2 {{ margin: 42px 0 16px; padding-top: 10px; font-size: 28px; }}
    .markdown-body h3 {{ margin: 30px 0 12px; font-size: 21px; }}
    .markdown-body p {{ margin: 0 0 17px; }}
    .markdown-body a {{ color: var(--teal); text-decoration-thickness: 1px; text-underline-offset: 3px; }}
    .markdown-body ul, .markdown-body ol {{ padding-left: 24px; }}
    .markdown-body li {{ margin: 6px 0; }}
    .markdown-body code {{ padding: 2px 6px; border-radius: 6px; background: #edf3f2; color: #1b5a55; font-size: .88em; }}
    pre {{ overflow-x: auto; padding: 18px; border-radius: 12px; background: #132d31; color: #e8f1ef; }}
    pre code {{ padding: 0 !important; background: transparent !important; color: inherit !important; }}
    table {{ width: 100%; margin: 22px 0; border-collapse: collapse; font-size: 14px; }}
    th {{ background: #eaf2f1; color: #174b48; text-align: left; }}
    th, td {{ padding: 11px 13px; border: 1px solid #d5e0df; vertical-align: top; }}
    blockquote {{ margin: 22px 0; padding: 13px 19px; border-left: 4px solid var(--accent); background: #fff7f1; color: #5d4c42; }}
    .diagram-shell {{ margin: 24px 0; padding: 18px; overflow-x: auto; border: 1px solid #cddcda; border-radius: 16px; background: linear-gradient(180deg, #fbfdfd, #eef5f4); }}
    .diagram-label {{ margin-bottom: 12px; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
    .flow-svg {{ display: block; width: 100%; min-width: 620px; height: auto; }}
    .mermaid-source {{ margin-top: 12px; text-align: left; }}
    details {{ margin-top: 12px; }} details summary {{ cursor: pointer; color: var(--teal); font-size: 12px; font-weight: 750; }}
    @media (max-width: 900px) {{ .shell {{ display: block; }} aside {{ position: relative; width: auto; height: auto; }} nav {{ columns: 2; }} nav p {{ column-span: all; }} main {{ padding: 24px 14px 64px; }} .stats {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 560px) {{ nav {{ columns: 1; }} .stats {{ grid-template-columns: 1fr; }} .report-card {{ padding: 24px 18px; }} }}
    @media print {{ aside {{ display: none; }} .shell {{ display: block; }} main {{ padding: 0; }} .hero, .report-card, .stat {{ box-shadow: none; break-inside: avoid; }} .report-card {{ border: 0; border-radius: 0; page-break-before: always; }} }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <div class="brand"><div class="brand-mark">DE</div><div><strong>Document Enhancer</strong><small>Review bundle</small></div></div>
      <nav><p>Read in order</p>{navigation}</nav>
      <div class="aside-note">This viewer is generated from the numbered Markdown files. The YAML decision file remains the only human-editable input between stages.</div>
    </aside>
    <main>
      <header class="hero">
        <p class="eyebrow">Governed document review</p>
        <h1>{html.escape(record.source_name)}</h1>
        <p class="hero-summary">{html.escape(audit_summary)}</p>
        <div class="meta">
          <span class="pill status-{status_class}">{html.escape(record.status.upper())}</span>
          <span class="pill">Phase · {html.escape(phase)}</span>
          <span class="pill">Recipe · {html.escape(record.recipe)}</span>
          <span class="pill">Run · {html.escape(record.run_id)}</span>
        </div>
      </header>
      <section class="stats">{_stat_cards(review, audit)}</section>
      {articles}
    </main>
  </div>
</body>
</html>
"""


__all__ = ["render_html_report"]
