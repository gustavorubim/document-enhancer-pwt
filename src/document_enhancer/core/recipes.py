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
    template_mappings: tuple[dict[str, Any], ...]
    entity_types: tuple[str, ...]
    relationship_types: tuple[str, ...]
    template_text: str

    @property
    def recipe_id(self) -> str:
        return f"{self.pack.pack_id}@{self.pack.version}/{self.document_type}"

    def classify(self, item: dict[str, Any]) -> str:
        """Return the small, public requirement vocabulary used by the core runner."""

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

    def criteria_for_requirement(self, requirement_id: str) -> tuple[str, ...]:
        for mapping in self.template_mappings:
            if str(mapping.get("requirement_id") or "") == requirement_id:
                return tuple(
                    str(item) for item in (mapping.get("criterion_ids") or []) if str(item).strip()
                )
        return ()

    def allows_node_type(self, node_type: str) -> bool:
        return not self.entity_types or node_type in self.entity_types or node_type == "section"

    def allows_edge_type(self, edge_type: str) -> bool:
        return (
            not self.relationship_types
            or edge_type in self.relationship_types
            or edge_type in {"sequence", "reference", "branch", "escalation", "contains"}
        )

    @property
    def recipe_digest(self) -> str:
        """Stable digest for the validated pack plus the selected document type."""

        payload = {
            "pack_sha256": self.pack.pack_sha256,
            "recipe_id": self.recipe_id,
            "required_sections": self.required_sections,
            "tables": self.tables,
            "rubric_criteria": self.rubric_criteria,
            "template_mappings": self.template_mappings,
            "entity_types": self.entity_types,
            "relationship_types": self.relationship_types,
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
    """Compile one validated reference pack into the core recipe."""

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
    raw_mappings = rubric.get("template_mappings", [])
    if (
        not isinstance(raw_sections, list)
        or not isinstance(raw_tables, list)
        or not isinstance(raw_criteria, list)
        or not isinstance(raw_mappings, list)
    ):
        raise ValueError("recipe sections, tables, rubric criteria, and mappings must be lists")
    entity_types, relationship_types = _load_ontology(pack)
    return Recipe(
        pack=pack,
        document_type=document_type,
        required_sections=tuple(item for item in raw_sections if isinstance(item, dict)),
        tables=tuple(item for item in raw_tables if isinstance(item, dict)),
        rubric_criteria=tuple(item for item in raw_criteria if isinstance(item, dict)),
        template_mappings=tuple(item for item in raw_mappings if isinstance(item, dict)),
        entity_types=entity_types,
        relationship_types=relationship_types,
        template_text=pack.template_path(document_type).read_text(encoding="utf-8"),
    )


def _load_ontology(pack: ReferencePack) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ontology = pack.manifest.get("ontology") or {}
    entity_path = ontology.get("entity_types")
    relationship_path = ontology.get("relationship_types")
    entity_types: list[str] = []
    relationship_types: list[str] = []
    if entity_path:
        payload = _load_yaml(pack.path(str(entity_path)))
        for item in payload.get("entity_types") or []:
            if isinstance(item, dict) and item.get("type_id"):
                entity_types.append(str(item["type_id"]))
    if relationship_path:
        payload = _load_yaml(pack.path(str(relationship_path)))
        for item in payload.get("relationship_types") or []:
            if not isinstance(item, dict):
                continue
            identifier = item.get("relationship_id") or item.get("type_id")
            if identifier:
                relationship_types.append(str(identifier))
    return tuple(entity_types), tuple(relationship_types)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml_parser().load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"recipe YAML must be a mapping: {path}")
    return value


__all__ = ["Recipe", "load_recipe"]
