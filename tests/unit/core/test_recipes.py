"""Recipe adapter tests."""

from pathlib import Path

import pytest

from document_enhancer.core.recipes import load_recipe


@pytest.mark.unit
def test_enterprise_recipe_exposes_requirements_and_rubric() -> None:
    root = Path(__file__).resolve().parents[3] / "reference_packs" / "enterprise_core"

    recipe = load_recipe(root, document_type="process")

    assert recipe.recipe_id == "enterprise_core@2.0.0/process"
    assert len(recipe.required_sections) >= 10
    assert "PROC-STEP-001" in {str(item["criterion_id"]) for item in recipe.rubric_criteria}
    assert "{{" not in recipe.template_text or "}}" in recipe.template_text
    assert len(recipe.recipe_digest) == 64
    assert recipe.recipe_digest == load_recipe(root, document_type="process").recipe_digest


@pytest.mark.unit
def test_recipe_exposes_tables_and_requirement_classes() -> None:
    root = Path(__file__).resolve().parents[3] / "reference_packs" / "enterprise_core"
    recipe = load_recipe(root, document_type="process")

    assert len(recipe.tables) >= 1
    assert len(recipe.recipe_digest) == 64
    assert all(recipe.classify(item) == "required" for item in recipe.required_section_items)
