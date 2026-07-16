from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from document_enhancer.references.errors import ReferencePackSecurityError
from document_enhancer.references.loader import ReferencePackValidator, _safe_yaml_load

PACK = Path("reference_packs/enterprise_core")


def copy_pack(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    destination = tmp_path / "pack"
    shutil.copytree(PACK, destination)
    return destination


def test_default_pack_has_no_validation_errors() -> None:
    report = ReferencePackValidator().report(PACK)
    assert report.ok, report.errors
    assert report.details["file_count"] == 27


def test_path_traversal_in_manifest_is_rejected(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    manifest = pack / "manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "path: ontology/entity_types.yaml", "path: ../outside.yaml"
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("traversal" in error or "escapes" in error for error in errors)

    pack = copy_pack(tmp_path / "dot")
    manifest = pack / "manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "path: ontology/entity_types.yaml", "path: ./ontology/entity_types.yaml"
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("non-canonical" in error for error in errors)


def test_absolute_and_backslash_paths_are_rejected(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    manifest = pack / "manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "path: ontology/entity_types.yaml", "path: C:\\\\outside.yaml"
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("Backslash" in error or "Unsafe or invalid YAML" in error for error in errors)


def test_missing_digest_and_digest_mismatch_are_rejected(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    manifest = pack / "manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "sha256: 028d32889c2a7b1474d5b5ddfc8fe80d3e661883ac08b37cbdbb4022689aaeb1",
            "sha256: PLACEHOLDER",
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("missing valid sha256" in error for error in errors)

    pack = copy_pack(tmp_path / "mismatch")
    style = pack / "context/style_guides/enterprise_style.md"
    style.write_text(style.read_text(encoding="utf-8") + "\nDrift.\n", encoding="utf-8")
    errors = ReferencePackValidator().validate(pack)
    assert any("digest mismatch" in error for error in errors)


def test_unresolved_rubric_template_mapping_is_rejected(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    rubric = pack / "rubrics/process.yaml"
    rubric.write_text(
        rubric.read_text(encoding="utf-8").replace(
            "requirement_id: SEC-PROC-METADATA", "requirement_id: SEC-NOT-REAL"
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("unresolved rubric/template mapping" in error for error in errors)


def test_unresolved_template_heading_is_rejected(tmp_path: Path) -> None:
    pack = copy_pack(tmp_path)
    requirements = pack / "templates/process/requirements.yaml"
    requirements.write_text(
        requirements.read_text(encoding="utf-8").replace(
            'heading: "Purpose"', 'heading: "Not a rendered heading"'
        ),
        encoding="utf-8",
    )
    errors = ReferencePackValidator().validate(pack)
    assert any("heading not found" in error for error in errors)


def test_safe_yaml_rejects_duplicate_keys_and_python_tags(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("name: one\nname: two\n", encoding="utf-8")
    with pytest.raises(ReferencePackSecurityError, match="Unsafe or invalid YAML"):
        _safe_yaml_load(duplicate)

    tagged = tmp_path / "tagged.yaml"
    tagged.write_text("value: !!python/object/apply:os.system ['echo unsafe']\n", encoding="utf-8")
    with pytest.raises(ReferencePackSecurityError, match="Unsafe or invalid YAML"):
        _safe_yaml_load(tagged)

    cyclic = tmp_path / "cyclic.yaml"
    cyclic.write_text("value: &loop [*loop]\n", encoding="utf-8")
    with pytest.raises(ReferencePackSecurityError, match="aliases or cycles"):
        _safe_yaml_load(cyclic)
