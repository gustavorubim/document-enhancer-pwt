"""Mermaid generation from validated structured objects and relationships only."""

from __future__ import annotations

import re

from .models import MermaidDiagram

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_mermaid(diagram: MermaidDiagram) -> tuple[str, ...]:
    """Return syntax and cross-reference errors without invoking a Mermaid runtime."""

    errors: list[str] = []
    node_ids = {node.node_id for node in diagram.nodes}
    for node in diagram.nodes:
        if not _ID_RE.fullmatch(node.node_id):
            errors.append(f"invalid Mermaid node ID: {node.node_id}")
    for edge in diagram.edges:
        if edge.source_node_id not in node_ids:
            errors.append(f"edge {edge.edge_id} has unknown source {edge.source_node_id}")
        if edge.target_node_id not in node_ids:
            errors.append(f"edge {edge.edge_id} has unknown target {edge.target_node_id}")
    return tuple(errors)


def _escape_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ").strip() or "TBD"


def generate_mermaid(diagram: MermaidDiagram) -> str:
    """Render a syntax-safe flowchart from the diagram's already-validated inputs."""

    errors = validate_mermaid(diagram)
    if errors:
        raise ValueError("Mermaid validation failed: " + "; ".join(errors))
    lines = ["flowchart TD"]
    for node in diagram.nodes:
        lines.append(f'    {node.node_id}["{_escape_label(node.label)}"]')
    for edge in diagram.edges:
        label = f"|{_escape_label(edge.label)}|" if edge.label else ""
        lines.append(f"    {edge.source_node_id} -->{label} {edge.target_node_id}")
    if not diagram.nodes:
        lines.append('    TBD_FLOW["No approved structured flow"]')
    return "\n".join(lines) + "\n"


__all__ = ["generate_mermaid", "validate_mermaid"]
