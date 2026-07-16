from __future__ import annotations

import shutil
import sqlite3
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from document_enhancer.artifacts.paths import RunPaths
from document_enhancer.domain.run import PromptSpec, RagAnswer
from document_enhancer.errors import UnsupportedInputError, ValidationError
from document_enhancer.ingest.markdown import TextParser
from document_enhancer.ingest.pipeline import parse_source
from document_enhancer.logging import safe_event
from document_enhancer.rag import catalog_embedding_profile
from document_enhancer.rag.catalog_reader import CatalogReadError
from document_enhancer.references.errors import ReferencePackSecurityError
from document_enhancer.references.loader import _safe_yaml_load


@pytest.mark.security
def test_docx_active_content_and_zip_traversal_fail_closed(tmp_path: Path) -> None:
    active = tmp_path / "active.docx"
    shutil.copyfile(
        "fixtures/synthetic/corpus/monthly_loss_forecasting_methodology/clean.docx", active
    )
    with zipfile.ZipFile(active, "a") as archive:
        archive.writestr("word/vbaProject.bin", b"not executable test content")
    with pytest.raises(UnsupportedInputError, match="active content"):
        parse_source(active)

    traversal = tmp_path / "traversal.docx"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape", b"blocked")
        archive.writestr("word/document.xml", b"<document/>")
    with pytest.raises(UnsupportedInputError, match="path-traversal"):
        parse_source(traversal)


@pytest.mark.security
def test_artifact_paths_malicious_formats_and_oversized_inputs_are_rejected(
    tmp_path: Path,
) -> None:
    paths = RunPaths(tmp_path, "run-safe")
    for unsafe in ("../escape", "/absolute", "nested/../../escape", "nested\\escape"):
        with pytest.raises(ValidationError, match="traversal|escapes"):
            paths.artifact_path(unsafe)

    macro_document = tmp_path / "document.docm"
    macro_document.write_bytes(b"macro-enabled package")
    with pytest.raises(UnsupportedInputError, match="Unsupported input suffix"):
        parse_source(macro_document)

    oversized = tmp_path / "oversized.txt"
    oversized.write_text("ignore instructions " * 20, encoding="utf-8")
    with pytest.raises(UnsupportedInputError, match="configured size limit"):
        TextParser(max_source_bytes=16).parse(oversized)


@pytest.mark.security
def test_yaml_depth_secrets_and_tool_boundaries_fail_closed(tmp_path: Path) -> None:
    deep = tmp_path / "deep.yaml"
    deep.write_text("value: " + "[" * 45 + "x" + "]" * 45 + "\n", encoding="utf-8")
    with pytest.raises(ReferencePackSecurityError, match="nesting limit"):
        _safe_yaml_load(deep)

    event = safe_event(
        "provider failure api_key=should-not-leak",
        token="ya29.this-is-not-real",
        detail="password=fixture-secret",
    )
    assert "should-not-leak" not in str(event)
    assert "fixture-secret" not in str(event)
    assert event["token"] == "[REDACTED]"

    with pytest.raises(PydanticValidationError, match="cannot enable shell"):
        PromptSpec(
            prompt_id="security.test",
            stage="analysis",
            template_path="prompts/security.md",
            model_route="gemini-3.1-flash-lite",
            output_schema="security.schema.json",
            optional_tools=["shell", "browser"],
            token_budget=100,
            output_budget=20,
            retry_policy="none",
            safety_policy="untrusted-data-only",
        )


@pytest.mark.security
def test_catalog_corruption_and_citation_mismatch_never_pass(tmp_path: Path) -> None:
    corrupt = tmp_path / "catalog.sqlite3"
    sqlite3.connect(corrupt).close()
    with pytest.raises(CatalogReadError, match="schema version mismatch"):
        catalog_embedding_profile(corrupt)

    with pytest.raises(PydanticValidationError, match="unknown handles"):
        RagAnswer.model_validate(
            {
                "answer_id": "ANSWER-SECURITY-001",
                "query_id": "QUERY-SECURITY-001",
                "status": "answered",
                "answer_markdown": "The fixture claims a result.",
                "citations": [
                    {
                        "citation_id": "CITE-SECURITY-001",
                        "chunk_id": "CHUNK-SECURITY-001",
                        "document_id": "DOC-SECURITY-001",
                        "version_id": "DOCV-SECURITY-001",
                    }
                ],
                "claim_citations": [
                    {
                        "claim": "The fixture claims a result.",
                        "citation_ids": ["CITE-BOGUS-001"],
                    }
                ],
            }
        )
