"""Offline promoted-catalog fixtures shared by query-time RAG tests."""

from __future__ import annotations

from pathlib import Path

from document_enhancer.rag import ingest_package
from document_enhancer.workflow import DocumentWorkflow, WorkflowServices


def add_document(root: Path, catalog: Path, name: str, text: str) -> tuple[str, str]:
    source = root / f"{name}.md"
    source.write_text(f"# {name.replace('_', ' ').title()}\n\n{text}\n", encoding="utf-8")
    services = WorkflowServices(
        run_root=root / "runs",
        source=source,
        gate2_enabled=False,
        offline=True,
        auto_catalog_ingest=False,
    )
    result = DocumentWorkflow(services).run()
    assert result.status == "succeeded", result.errors
    run_path = root / "runs" / result.run_id
    receipt = ingest_package(run_path / "rag/document-rag.sqlite3", catalog)
    return receipt.document_id, receipt.version_id


def catalog_with_documents(root: Path, *, count: int = 2) -> Path:
    catalog = root / "catalog.sqlite3"
    add_document(
        root,
        catalog,
        "monthly_review",
        "The approved analyst records the monthly cobalt review result in the evidence register.",
    )
    if count > 1:
        add_document(
            root,
            catalog,
            "incident_escalation",
            "The incident owner escalates a critical amber event to the duty manager within fifteen minutes.",
        )
    return catalog
