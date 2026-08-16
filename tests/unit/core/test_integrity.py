"""Fail-closed regression tests for draft promotion and sealed-bundle integrity."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from document_enhancer.core.integrity import (
    ApprovalRequiredError,
    ApprovalTypeError,
    ArtifactIntegrityError,
    DigestMismatchError,
    RecipeConfigurationMismatchError,
    ResumeIdentityError,
    SealManifestError,
    artifact_ref_for_bytes,
    build_seal_manifest,
    capture_resume_identity,
    guard_promotion_identity,
    migrate_legacy_seal_manifest,
    register_artifact,
    require_explicit_approval,
    validate_recipe_configuration_digests,
    validate_seal_manifest,
    verify_artifact,
    verify_registered_artifacts,
)
from document_enhancer.core.models import ArtifactRef


def _write_authoritative_artifacts(root: Path) -> dict[str, ArtifactRef]:
    files = {
        "source.original": ("documents/original.md", b"source\n"),
        "output.final_markdown": ("markdown/07-final-document.md", b"# Final\n"),
        "audit.report": ("json/11-audit.json", b'{"status":"pass"}\n'),
        "output.graph": ("data/graph.jsonl", b'{"kind":"node","node_id":"n1"}\n'),
        "output.ontology": ("json/09-ontology.json", b'{"schema_version":"core.graph.v1"}\n'),
    }
    refs: dict[str, ArtifactRef] = {}
    for key, (relative_path, data) in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        refs[key] = register_artifact(root, relative_path)
    return refs


def _run_record(root: Path) -> dict[str, object]:
    return {
        "run_id": "run-001",
        "status": "waiting",
        "phase": "human_review",
        "source_digest": "1" * 64,
        "recipe": "enterprise_core@1/process",
        "recipe_digest": "2" * 64,
        "configuration_digest": "3" * 64,
        "unresolved_question_ids": ["question-001"],
        "artifacts": _write_authoritative_artifacts(root),
    }


@pytest.mark.unit
def test_missing_or_implicit_approval_is_rejected() -> None:
    """Regression: a missing YAML key must not inherit the old fail-open default."""

    with pytest.raises(ApprovalRequiredError, match="approve_rewrite") as missing:
        require_explicit_approval({})
    assert missing.value.code == "approval_required"

    with pytest.raises(ApprovalRequiredError):
        require_explicit_approval({"approve_rewrite": False})
    with pytest.raises(ApprovalTypeError):
        require_explicit_approval({"approve_rewrite": "true"})


@pytest.mark.unit
def test_registered_artifacts_reject_same_size_and_size_only_tampering(tmp_path: Path) -> None:
    path = tmp_path / "final.md"
    path.write_bytes(b"original")
    reference = register_artifact(tmp_path, "final.md")

    path.write_bytes(b"modified")
    with pytest.raises(DigestMismatchError, match="digest") as digest_failure:
        verify_artifact(tmp_path, reference, key="output.final_markdown")
    assert digest_failure.value.code == "artifact_digest_mismatch"

    path.write_bytes(b"changed-and-longer")
    with pytest.raises(DigestMismatchError, match="size"):
        verify_artifact(tmp_path, reference, key="output.final_markdown")


@pytest.mark.unit
def test_registry_rejects_path_escape_and_missing_required_stage_artifacts(tmp_path: Path) -> None:
    with pytest.raises(ArtifactIntegrityError):
        artifact_ref_for_bytes("../outside.txt", b"not in the bundle")

    path = tmp_path / "intermediate.json"
    path.write_bytes(b"{}")
    reference = register_artifact(tmp_path, path.name)
    assert verify_registered_artifacts(tmp_path, {"intermediate": reference}) == {
        "intermediate": reference
    }
    with pytest.raises(SealManifestError, match="missing"):
        build_seal_manifest(
            run_id="run-001",
            source_digest="1" * 64,
            recipe_id="recipe",
            recipe_digest="2" * 64,
            configuration_digest="3" * 64,
            artifacts={"intermediate": reference},
        )


@pytest.mark.unit
def test_recipe_and_configuration_changes_block_resume() -> None:
    with pytest.raises(RecipeConfigurationMismatchError, match="recipe digest"):
        validate_recipe_configuration_digests("1" * 64, "2" * 64, "3" * 64, "3" * 64)
    with pytest.raises(RecipeConfigurationMismatchError, match="configuration digest"):
        validate_recipe_configuration_digests("1" * 64, "1" * 64, "3" * 64, "4" * 64)
    with pytest.raises(RecipeConfigurationMismatchError, match="recipe id"):
        validate_recipe_configuration_digests(
            "1" * 64,
            "1" * 64,
            "3" * 64,
            "3" * 64,
            expected_recipe_id="recipe-a",
            actual_recipe_id="recipe-b",
        )


@pytest.mark.unit
def test_seal_requires_complete_authoritative_manifest_and_verifies_graph_and_ontology(
    tmp_path: Path,
) -> None:
    refs = _write_authoritative_artifacts(tmp_path)
    manifest = build_seal_manifest(
        run_id="run-001",
        source_digest=refs["source.original"].sha256,
        recipe_id="enterprise_core@1/process",
        recipe_digest="2" * 64,
        configuration_digest="3" * 64,
        artifacts=refs,
        artifact_root=tmp_path,
    )
    assert manifest.graph_digest == refs["output.graph"].sha256
    assert manifest.ontology_digest == refs["output.ontology"].sha256
    assert validate_seal_manifest(manifest, artifact_root=tmp_path) == manifest

    missing_graph = manifest.model_dump(mode="json")
    del missing_graph["artifacts"]["output.graph"]
    with pytest.raises(SealManifestError, match="missing"):
        validate_seal_manifest(missing_graph)

    wrong_ontology_digest = manifest.model_dump(mode="json")
    wrong_ontology_digest["ontology_digest"] = "f" * 64
    with pytest.raises(SealManifestError, match="ontology"):
        validate_seal_manifest(wrong_ontology_digest)

    (tmp_path / "data/graph.jsonl").write_bytes(b"tampered graph\n")
    with pytest.raises(DigestMismatchError, match="size"):
        validate_seal_manifest(manifest, artifact_root=tmp_path)


@pytest.mark.unit
def test_legacy_path_only_seal_requires_explicit_upgrade_and_complete_exports(
    tmp_path: Path,
) -> None:
    refs = _write_authoritative_artifacts(tmp_path)
    legacy = {
        "run_id": "run-001",
        "source_digest": refs["source.original"].sha256,
        "final_digest": refs["output.final_markdown"].sha256,
        "audit_digest": refs["audit.report"].sha256,
        "artifact_paths": [reference.path for reference in refs.values()],
        "sealed": True,
    }
    with pytest.raises(SealManifestError, match="core.seal.v2"):
        validate_seal_manifest(legacy)

    migrated = migrate_legacy_seal_manifest(
        legacy,
        recipe_id="enterprise_core@1/process",
        recipe_digest="2" * 64,
        configuration_digest="3" * 64,
        artifacts=refs,
        artifact_root=tmp_path,
    )
    assert migrated.schema_version == "core.seal.v2"
    assert migrated.artifacts["output.graph"].sha256 == refs["output.graph"].sha256


@pytest.mark.unit
def test_resume_and_promotion_identity_reject_changed_artifacts_or_state(tmp_path: Path) -> None:
    record = _run_record(tmp_path)
    captured = capture_resume_identity(record)
    assert guard_promotion_identity(captured, record) == captured

    changed_record = dict(record)
    changed_artifacts = dict(cast(dict[str, ArtifactRef], record["artifacts"]))
    changed_artifacts["output.graph"] = artifact_ref_for_bytes(
        "data/graph.jsonl", b"different graph"
    )
    changed_record["artifacts"] = changed_artifacts
    with pytest.raises(ResumeIdentityError, match="artifact_manifest_digest"):
        guard_promotion_identity(captured, changed_record)

    changed_status = dict(record)
    changed_status["status"] = "running"
    with pytest.raises(ResumeIdentityError, match="status"):
        guard_promotion_identity(captured, changed_status)

    changed_config = dict(record)
    changed_config["configuration_digest"] = "4" * 64
    with pytest.raises(ResumeIdentityError, match="configuration_digest"):
        guard_promotion_identity(captured, changed_config)
