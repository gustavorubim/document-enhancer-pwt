from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.run_governed_dod_proof import run_proof
from typer.testing import CliRunner

from document_enhancer.cli import app

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.e2e
def test_four_governed_examples_complete_actual_offline_cli_and_rag(tmp_path: Path) -> None:
    result = run_proof(tmp_path / "proof")
    assert result["status"] == "passed"
    assert result["provider_calls"] == 0
    assert result["public_downloads"] == 0
    assert set(result["documents"]) == {
        "process",
        "methodology",
        "standard",
        "desktop_procedure",
    }
    assert [item["catalog"]["generation"] for item in result["documents"].values()] == [
        1,
        2,
        3,
        4,
    ]
    for item in result["documents"].values():
        assert item["reference_pack"] == {"id": "enterprise_core", "version": "1.0.0"}
        assert item["review_gates"] == {
            "gate1_completed": True,
            "gate2_pause": "gate2",
            "gate2_approved": True,
        }
        assert item["audit_status"] == "pass"
        assert item["rag_package"]["valid"] is True
        assert item["search"]["result_count"] > 0
        assert item["answer"]["status"] in {"answered", "partial"}
        assert item["answer"]["grounding_passed"] is True
        assert item["answer"]["citations"] > 0


@pytest.mark.e2e
def test_incomplete_governed_document_still_fails_all_observed_audit_codes(
    tmp_path: Path,
) -> None:
    complete = ROOT / "reference_packs" / "enterprise_core" / "templates" / "process" / "example.md"
    incomplete = tmp_path / "incomplete-process.md"
    incomplete.write_text(
        "\n".join(complete.read_text(encoding="utf-8").splitlines()[:30]) + "\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "runs"
    result = CliRunner().invoke(
        app,
        [
            "run",
            str(incomplete),
            "--execution-mode",
            "offline",
            "--document-type",
            "process",
            "--run-dir",
            str(run_root),
            "--no-gate2",
            "--json",
        ],
        env={"DOCENHANCE_CATALOG_PATH": str(tmp_path / "catalog.sqlite3")},
    )
    assert result.exit_code == 10
    payload = json.loads(result.stdout)
    audit = json.loads(
        (run_root / payload["run_id"] / "audit" / "audit.json").read_text(encoding="utf-8")
    )
    assert audit["status"] == "waiting"
    assert set(audit["routing"]["blocker_ids"]) == {
        "CHECK-TEMPLATE-TABLES",
        "CHECK-DOCUMENT-LINT",
        "INDEPENDENT-AUDIT-NOT-PASSED",
    }
    assert not (run_root / payload["run_id"] / "rag" / "document-rag.sqlite3").exists()
