"""DFT-6 acceptance coverage for the runner's draft-first human gate."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from document_enhancer.core import CoreRunner
from document_enhancer.core.indexing import load_sealed_bundle
from document_enhancer.core.integrity import DigestMismatchError
from document_enhancer.core.layout import (
    AUDIT,
    DRAFT_AUDIT,
    DRAFT_DOCUMENT,
    DRAFT_DOCUMENT_DOCX,
    DRAFT_TRANSFORMATION,
    DRAFT_VISUAL_EXTRACTIONS,
    FINAL_MARKDOWN,
    SEAL,
)

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _approve_all(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("approve_rewrite: false", "approve_rewrite: true")
        .replace('answer: ""', "answer: approved")
        .replace("disposition: defer", "disposition: accept"),
        encoding="utf-8",
    )


@pytest.mark.e2e
def test_stage_one_materializes_candidate_and_stage_two_seals_only_after_approval(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "# Intake\n\nThe owner receives and reviews the request.\n\n"
        "# Decision\n\nThe manager records the outcome.\n",
        encoding="utf-8",
    )
    runner = CoreRunner(tmp_path / "runs")

    waiting = runner.start(source)
    run_path = tmp_path / "runs" / waiting.run_id

    assert waiting.status == "waiting"
    assert waiting.phase == "human_review"
    assert not (run_path / FINAL_MARKDOWN).exists()
    assert not (run_path / SEAL).exists()
    assert all(
        (run_path / path).is_file()
        for path in (
            DRAFT_TRANSFORMATION,
            DRAFT_DOCUMENT,
            DRAFT_DOCUMENT_DOCX,
            DRAFT_AUDIT,
            DRAFT_VISUAL_EXTRACTIONS,
        )
    )
    assert "UNAPPROVED DRAFT" in (run_path / DRAFT_DOCUMENT).read_text(encoding="utf-8")
    assert (
        json.loads((run_path / DRAFT_TRANSFORMATION).read_text())["schema_version"]
        == "core.transformation-mapping.v1"
    )

    still_waiting = runner.resume(waiting.run_id)
    assert still_waiting.status == "waiting"
    assert not (run_path / SEAL).exists()

    _approve_all(run_path / "review/decisions.yaml")
    complete = runner.resume(waiting.run_id)

    assert complete.status == "succeeded"
    seal = json.loads((run_path / SEAL).read_text(encoding="utf-8"))
    assert seal["schema_version"] == "core.seal.v2"
    assert set(
        (
            "source.original",
            "output.final_markdown",
            "audit.report",
            "output.graph",
            "output.ontology",
        )
    ) <= set(seal["artifacts"])
    assert json.loads((run_path / AUDIT).read_text(encoding="utf-8"))["status"] == "pass"
    sealed = load_sealed_bundle(run_path)
    assert sealed.run_id == waiting.run_id
    assert "UNAPPROVED DRAFT" not in sealed.final_markdown


@pytest.mark.e2e
def test_tampered_candidate_is_rejected_before_promotion(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    image = tmp_path / "figure.png"
    image.write_bytes(PNG_1X1)
    source.write_text(
        "# Process\n\nThe owner reviews the request.\n\n![Evidence](figure.png)\n",
        encoding="utf-8",
    )
    runner = CoreRunner(tmp_path / "runs")
    waiting = runner.start(source)
    run_path = tmp_path / "runs" / waiting.run_id
    visual_payload = json.loads((run_path / DRAFT_VISUAL_EXTRACTIONS).read_text(encoding="utf-8"))
    assert visual_payload["visual_extractions"][0]["status"] == "requires_review"
    assert "question-visual-FIG-001" in waiting.unresolved_question_ids
    draft = run_path / DRAFT_DOCUMENT
    draft.write_text(draft.read_text(encoding="utf-8") + "\nTampered.\n", encoding="utf-8")
    _approve_all(run_path / "review/decisions.yaml")

    with pytest.raises(DigestMismatchError):
        runner.resume(waiting.run_id)

    assert not (run_path / FINAL_MARKDOWN).exists()
    assert not (run_path / SEAL).exists()
