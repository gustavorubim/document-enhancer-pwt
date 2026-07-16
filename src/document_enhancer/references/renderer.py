"""Safe rendering for reference-pack Markdown templates."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")


def _lookup(data: Mapping[str, Any], dotted_key: str) -> Any:
    value: Any = data
    for part in dotted_key.split("."):
        if isinstance(value, Mapping) and part in value:
            value = value[part]
        else:
            return None
    return value


def _safe_value(value: Any) -> str:
    """Turn data into Markdown text without allowing template control markers."""

    if value is None or value == "":
        return "TBD"
    if isinstance(value, bool):
        rendered = "true" if value else "false"
    elif isinstance(value, Mapping):
        rendered = "; ".join(f"{key}: {item}" for key, item in value.items())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rendered = "\n".join(f"- {item}" for item in value) or "TBD"
    else:
        rendered = str(value)
    return rendered.replace("<!--", "&lt;!--").replace("-->", "--&gt;")


def render_template_text(template: str, data: Mapping[str, Any] | None = None) -> str:
    """Render a Markdown template while removing all authoring-only controls.

    The renderer intentionally supports only dotted lookups. It never evaluates Python,
    Jinja, YAML, shell, or Markdown expressions. Missing values become visible ``TBD``
    markers so a rendered document cannot silently look complete.
    """

    values = data or {}
    without_comments = _COMMENT_RE.sub("", template)

    def replace(match: re.Match[str]) -> str:
        return _safe_value(_lookup(values, match.group(1)))

    rendered = _PLACEHOLDER_RE.sub(replace, without_comments)
    # A malformed control marker is safer as visible content than as a hidden instruction.
    rendered = rendered.replace("{{", "\\{\\{").replace("}}", "\\}\\}")
    return rendered.strip() + "\n"


def render_template(path: Path, data: Mapping[str, Any] | None = None) -> str:
    """Read and safely render a template from a caller-validated path."""

    return render_template_text(path.read_text(encoding="utf-8"), data)


class TemplateRenderer:
    """Small object wrapper useful to downstream render and test code."""

    def render(self, template: Path | str, data: Mapping[str, Any] | None = None) -> str:
        if isinstance(template, Path):
            return render_template(template, data)
        return render_template_text(template, data)


ReferencePackRenderer = TemplateRenderer


def render_reference_template(template: Path | str, data: Mapping[str, Any] | None = None) -> str:
    """Compatibility-friendly function name for downstream rendering code."""

    return TemplateRenderer().render(template, data)
