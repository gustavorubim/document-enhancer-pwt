"""Thin recipe adapter for the existing governed reference-pack format."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_enhancer.config import yaml_parser
from document_enhancer.references.loader import ReferencePack, load_reference_pack

_REQUIREMENT_CLASSES = {"required", "conditional", "recommended"}


@dataclass(frozen=True)
class Recipe:
    """Only the recipe data the core runner needs during authoring."""

    pack: ReferencePack
    document_type: str
    required_sections: tuple[dict[str, Any], ...]
    tables: tuple[dict[str, Any], ...]
    rubric_criteria: tuple[dict[str, Any], ...]
    template_text: str

    @property
    def recipe_id(self) -> str:
        return f"{self.pack.pack_id}@{self.pack.version}/{self.document_type}"

    def classify(self, item: dict[str, Any]) -> str:
        """Return the small, public requirement vocabulary used by the core runner.

        Existing packs use ``required: bool``.  New packs may use an explicit
        ``classification`` or ``applies_when`` without forcing every consumer to
        understand another schema.  The compiler normalizes both forms here.
        """

        explicit = str(item.get("classification", "")).strip().lower()
        if explicit in _REQUIREMENT_CLASSES:
            return explicit
        if bool(item.get("required")):
            return "required"
        if item.get("applies_when") or item.get("conditional"):
            return "conditional"
        return "recommended"

    @property
    def required_section_items(self) -> tuple[dict[str, Any], ...]:
        return tuple(item for item in self.required_sections if self.classify(item) == "required")

    @property
    def recipe_digest(self) -> str:
        """Stable digest for the validated pack plus the selected document type."""

        payload = {
            "pack_sha256": self.pack.pack_sha256,
            "recipe_id": self.recipe_id,
            "required_sections": self.required_sections,
            "tables": self.tables,
            "rubric_criteria": self.rubric_criteria,
            "template_text": self.template_text,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()


def load_recipe(
    root: Path,
    *,
    document_type: str,
) -> Recipe:
    """Compile one validated reference pack into the core recipe.

    The reference-pack loader remains the security boundary. This adapter only
    selects the document type, normalizes requirement classes, and exposes one
    digest that makes every run reproducible. Provider prompts are small code
    constants rather than another user-facing configuration surface.
    """

    pack = load_reference_pack(root)
    supported = pack.manifest.get("supported_document_types", {})
    if document_type not in supported:
        raise ValueError(f"reference pack does not support document type: {document_type}")
    requirements = _load_yaml(pack.requirements_path(document_type))
    rubric_path = pack.path(str(pack.manifest["rubrics"][document_type]))
    rubric = _load_yaml(rubric_path)
    raw_sections = requirements.get("sections", [])
    raw_tables = requirements.get("tables", [])
    raw_criteria = rubric.get("criteria", [])
    if (
        not isinstance(raw_sections, list)
        or not isinstance(raw_tables, list)
        or not isinstance(raw_criteria, list)
    ):
        raise ValueError("recipe sections, tables, and rubric criteria must be lists")
    return Recipe(
        pack=pack,
        document_type=document_type,
        required_sections=tuple(item for item in raw_sections if isinstance(item, dict)),
        tables=tuple(item for item in raw_tables if isinstance(item, dict)),
        rubric_criteria=tuple(item for item in raw_criteria if isinstance(item, dict)),
        template_text=pack.template_path(document_type).read_text(encoding="utf-8"),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml_parser().load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"recipe YAML must be a mapping: {path}")
    return value


__all__ = ["Recipe", "load_recipe"]
