"""Optional core-bundle indexing contract."""

import json
from pathlib import Path

import pytest

from document_enhancer.core import CoreBundleIndex, CoreRunner
from document_enhancer.core.integrity import build_seal_manifest, register_artifact
from document_enhancer.core.layout import AUDIT, SEAL
from document_enhancer.core.models import ArtifactRef, RunRecord


def _approve_all(run_path: Path) -> None:
    decisions = run_path / "review/decisions.yaml"
    decisions.write_text(
        decisions.read_text(encoding="utf-8")
        .replace("approve_rewrite: false", "approve_rewrite: true")
        .replace('answer: ""', "answer: approved")
        .replace("disposition: defer", "disposition: accept"),
        encoding="utf-8",
    )


def _regenerate_v2_seal(run_path: Path, record: RunRecord) -> None:
    artifacts: dict[str, ArtifactRef] = {}
    seen_paths: set[str] = set()
    for key, reference in record.artifacts.items():
        path = run_path / reference.path
        if (
            key != "audit.seal"
            and reference.path not in seen_paths
            and path.is_file()
            and not path.is_symlink()
        ):
            artifacts[key] = register_artifact(
                run_path, reference.path, media_type=reference.media_type
            )
            seen_paths.add(reference.path)
    manifest = build_seal_manifest(
        run_id=record.run_id,
        source_digest=record.source_digest,
        recipe_id=record.recipe,
        recipe_digest=record.recipe_digest,
        configuration_digest=record.configuration_digest,
        artifacts=artifacts,
        artifact_root=run_path,
    )
    (run_path / SEAL).write_text(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )


@pytest.mark.unit
def test_core_bundle_indexer_consumes_only_sealed_output(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Intake\n\nThe owner reviews the request.\n", encoding="utf-8")
    runner = CoreRunner(tmp_path / "runs")
    result = runner.start(source)
    run_path = tmp_path / "runs" / result.run_id
    _approve_all(run_path)
    result = runner.resume(result.run_id)

    assert result.status == "succeeded"
    assert json.loads((run_path / SEAL).read_text(encoding="utf-8"))["schema_version"] == (
        "core.seal.v2"
    )

    index = CoreBundleIndex(tmp_path / "catalog.sqlite3")
    assert index.index(run_path) >= 1
    matches = index.search("owner")
    assert matches and matches[0]["section_id"] == "intake"


@pytest.mark.unit
def test_core_bundle_indexer_rejects_failed_bundle(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Intake\n\nThe owner reviews the request.\n", encoding="utf-8")
    runner = CoreRunner(tmp_path / "runs")
    result = runner.start(source)
    run_path = tmp_path / "runs" / result.run_id
    _approve_all(run_path)
    result = runner.resume(result.run_id)
    assert result.status == "succeeded"

    # Preserve a complete, digest-valid v2 manifest while making the audit fail.  This
    # exercises the consumer's failed-audit gate rather than manufacturing a legacy seal.
    audit = run_path / AUDIT
    audit.write_text(
        json.dumps({"schema_version": "core.audit.v1", "status": "fail", "checks": {}}),
        encoding="utf-8",
    )
    _regenerate_v2_seal(run_path, result)

    with pytest.raises(ValueError, match="passing"):
        CoreBundleIndex(tmp_path / "catalog.sqlite3").index(run_path)
