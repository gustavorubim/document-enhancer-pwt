from __future__ import annotations

import json
from pathlib import Path

import pytest

from document_enhancer.export import validate_export_bundle
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices


@pytest.mark.e2e
def test_offline_graph_executes_audit_diff_chunk_and_export_idempotently(tmp_path: Path) -> None:
    source = tmp_path / "approved.md"
    source.write_text(
        "# Approved content\n\nThe approved analyst records the monthly review result.\n",
        encoding="utf-8",
    )
    services = WorkflowServices(
        run_root=tmp_path / "runs",
        source=source,
        gate2_enabled=False,
        offline=True,
    )
    result = DocumentWorkflow(services).run()
    assert result.status == "succeeded"
    assert result.current_stage == "complete"
    assert result.completed_stages[-5:] == ["audit", "diff", "chunk", "export", "complete"]

    run_dir = tmp_path / "runs" / result.run_id
    assert validate_export_bundle(run_dir / "export") == ()
    audit = json.loads((run_dir / "audit/audit.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "export/bundle-manifest.json").read_text(encoding="utf-8"))
    assert audit["status"] == "pass"
    assert audit["independent_audit"]["provider"] == "offline-deterministic-fake"
    assert manifest["validation_passed"] is True
    assert manifest["chunks_count"] > 0

    resumed = DocumentWorkflow(
        WorkflowServices(
            run_root=tmp_path / "runs",
            source=Path(),
            run_id=result.run_id,
            gate2_enabled=False,
            offline=True,
        )
    ).resume()
    assert resumed.status == "succeeded"
    assert validate_export_bundle(run_dir / "export") == ()
