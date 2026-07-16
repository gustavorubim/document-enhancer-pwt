#!/usr/bin/env python3
"""Run the four-document governed offline Definition-of-Done proof through the CLI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from document_enhancer.clarification import load_yaml
from document_enhancer.clarification.artifacts import write_yaml
from document_enhancer.domain.questions import RewriteChecklist

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PACK = ROOT / "reference_packs" / "enterprise_core"
DOCUMENTS = {
    "process": "What action does STEP-AURORA-001 perform?",
    "methodology": "How does the methodology begin validating its inputs?",
    "standard": "What MUST a controlled exchange record?",
    "desktop_procedure": "What happens when approval fields do not match?",
}


def _run_json(
    command: list[str], *, env: dict[str, str], expected_codes: tuple[int, ...] = (0,)
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in expected_codes:
        raise RuntimeError(
            f"CLI command failed ({completed.returncode}): {' '.join(command)}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI did not emit JSON: {' '.join(command)}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"CLI emitted a non-object JSON result: {' '.join(command)}")
    return value


def run_proof(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    executable = shutil.which("docenhance")
    if executable is None:
        raise RuntimeError("docenhance console script is not available on PATH")
    run_root = root / "runs"
    catalog = root / "catalog.sqlite3"
    env = dict(os.environ)
    env["DOCENHANCE_CATALOG_PATH"] = str(catalog)
    env["DOCENHANCE_RUN_DIR"] = str(run_root)
    results: dict[str, Any] = {}
    for document_type, question in DOCUMENTS.items():
        source = REFERENCE_PACK / "templates" / document_type / "example.md"
        waiting = _run_json(
            [
                executable,
                "run",
                str(source),
                "--document-type",
                document_type,
                "--run-dir",
                str(run_root),
                "--until",
                "checklist",
                "--json",
            ],
            env=env,
            expected_codes=(10,),
        )
        run_id = str(waiting["run_id"])
        run_path = run_root / run_id
        if (
            waiting.get("status") != "waiting"
            or waiting.get("current_stage") != "gate2"
            or "gate1" not in waiting.get("completed_stages", [])
        ):
            raise RuntimeError(
                f"governed DoD proof did not cross Gate 1 and pause at Gate 2 for {document_type}"
            )
        checklist_path = run_path / "clarification" / "rewrite-checklist.yaml"
        checklist = load_yaml(checklist_path, RewriteChecklist)
        write_yaml(
            checklist_path,
            checklist.model_copy(
                update={
                    "approved_by": "governed-dod-reviewer@example.invalid",
                    "approved_at": datetime(2026, 1, 1, tzinfo=UTC),
                }
            ),
        )
        workflow = _run_json(
            [
                executable,
                "resume",
                run_id,
                "--run-dir",
                str(run_root),
                "--json",
            ],
            env=env,
        )
        audit = json.loads((run_path / "audit" / "audit.json").read_text(encoding="utf-8"))
        enhanced = json.loads(
            (run_path / "output" / "enhanced-model.json").read_text(encoding="utf-8")
        )
        package = _run_json(
            [
                executable,
                "rag",
                "verify",
                run_id,
                "--run-dir",
                str(run_root),
                "--json",
            ],
            env=env,
        )
        ingestion = json.loads(
            (run_path / "rag" / "catalog-ingestion.json").read_text(encoding="utf-8")
        )
        search = _run_json(
            [
                executable,
                "rag",
                "search",
                question,
                "--catalog",
                str(catalog),
                "--offline",
                "--json",
            ],
            env=env,
        )
        answer = _run_json(
            [
                executable,
                "rag",
                "ask",
                question,
                "--catalog",
                str(catalog),
                "--offline",
                "--json",
            ],
            env=env,
        )
        answer_payload = answer["answer"]
        grounding = answer["grounding"]
        if (
            workflow.get("status") != "succeeded"
            or audit.get("status") != "pass"
            or not package.get("valid")
            or ingestion.get("status") != "promoted"
            or not search.get("hits")
            or answer_payload.get("status") not in {"answered", "partial"}
            or not answer_payload.get("citations")
            or not grounding.get("passed")
            or enhanced.get("reference_pack_id") != "enterprise_core"
        ):
            raise RuntimeError(f"governed DoD proof failed for {document_type}")
        results[document_type] = {
            "run_id": run_id,
            "run_path": str(run_path),
            "reference_pack": {
                "id": enhanced["reference_pack_id"],
                "version": enhanced["reference_pack_version"],
            },
            "audit_status": audit["status"],
            "review_gates": {
                "gate1_completed": True,
                "gate2_pause": waiting["current_stage"],
                "gate2_approved": True,
            },
            "rag_package": {
                "valid": package["valid"],
                "database": package["database"],
                "row_counts": package["row_counts"],
            },
            "catalog": {
                "path": ingestion["catalog_path"],
                "generation": ingestion["catalog_generation"],
                "status": ingestion["status"],
            },
            "search": {"query": question, "result_count": len(search["hits"])},
            "answer": {
                "status": answer_payload["status"],
                "grounding_passed": grounding["passed"],
                "citations": len(answer_payload["citations"]),
            },
            "provider_calls": 0,
            "public_downloads": 0,
        }
    return {
        "schema_version": "m8.governed-dod-proof.v1",
        "status": "passed",
        "reference_pack": str(REFERENCE_PACK),
        "catalog": str(catalog),
        "documents": results,
        "provider_calls": 0,
        "public_downloads": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".document-enhancer/governed-dod"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        if not args.force:
            parser.error(f"output exists; use --force to replace it: {args.output}")
        shutil.rmtree(args.output)
    result = run_proof(args.output)
    summary = args.output / "governed-dod-result.json"
    summary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": str(summary), "status": "passed"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
