"""Optional core-bundle indexing contract."""

from pathlib import Path

import pytest

from document_enhancer.core import CoreBundleIndex, CoreRunner


@pytest.mark.unit
def test_core_bundle_indexer_consumes_only_sealed_output(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Intake\n\nThe owner reviews the request.\n", encoding="utf-8")
    result = CoreRunner(tmp_path / "runs").start(source)

    index = CoreBundleIndex(tmp_path / "catalog.sqlite3")
    assert index.index(tmp_path / "runs" / result.run_id) == 1
    matches = index.search("owner")
    assert matches and matches[0]["section_id"] == "intake"


@pytest.mark.unit
def test_core_bundle_indexer_rejects_failed_bundle(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# Intake\n\nThe owner reviews the request.\n", encoding="utf-8")
    result = CoreRunner(tmp_path / "runs").start(source)
    audit = tmp_path / "runs" / result.run_id / "audit/audit.json"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text('{"status":"fail"}', encoding="utf-8")

    with pytest.raises(ValueError, match="passing"):
        CoreBundleIndex(tmp_path / "catalog.sqlite3").index(tmp_path / "runs" / result.run_id)
