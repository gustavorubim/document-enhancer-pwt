from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

import pytest

from document_enhancer.artifacts.run_storage import RunStorage
from document_enhancer.domain.analysis import (
    RecoveredSection,
    StructureRecoveryProposal,
)
from document_enhancer.ingest.markdown import MarkdownParser
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.recovery import (
    StructureRecoveryConfig,
    StructureRecoveryService,
    adapt_raw_document,
    build_recovery_windows,
    validate_recovery_proposal,
)
from document_enhancer.llm import (
    CallStatus,
    FakeStructuredModel,
    GeminiGatewayConfig,
    GeminiModelGateway,
    ResponseCache,
)
from document_enhancer.prompting.composer import PromptPackComposer
from document_enhancer.prompting.loader import load_prompt_pack
from document_enhancer.references.loader import load_reference_pack

ROOT = Path(__file__).resolve().parents[3]
PROMPT_ROOT = ROOT / "prompt_packs" / "gemini_core"
REFERENCE_ROOT = ROOT / "reference_packs" / "enterprise_core"
FIXTURE_ROOT = ROOT / "fixtures" / "synthetic" / "ingest" / "m3b"


@pytest.fixture(scope="module")
def composer() -> PromptPackComposer:
    reference_pack = load_reference_pack(REFERENCE_ROOT)
    prompt_pack = load_prompt_pack(PROMPT_ROOT, reference_pack=reference_pack)
    return PromptPackComposer(prompt_pack, reference_pack=reference_pack)


def _raw(path: Path):
    return MarkdownParser().parse(path)


def _gateway(responses: list[object], *, cache: ResponseCache | None = None):
    fake = FakeStructuredModel(responses)
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, retry_backoff_seconds=0),
        model_factory=lambda *_: fake,
        cache=cache,
    )
    return gateway, fake


def _scan(raw, normalized, *, decision: str) -> dict[str, object]:
    mapping = adapt_raw_document(raw)
    from document_enhancer.ingest.recovery import _outline_digest  # noqa: PLC0415

    return {
        "scan_id": "SCAN-M3B-TEST-001",
        "document_id": mapping.domain.document_id,
        "source_digest": raw.source_digest,
        "parser_outline_digest": _outline_digest(normalized.parser_outline),
        "decision": decision,
        "confidence": 0.95 if decision == "accept_parser" else 0.25,
        "boundary_regions": [],
        "evidence_span_ids": [],
        "ambiguities": [] if decision == "accept_parser" else ["parser/model disagreement"],
        "model": "fake",
        "prompt_id": "structure.triage",
        "prompt_digest": "c" * 64,
    }


def _proposal(raw, *, span_ids: tuple[str, ...] | None = None, conflict_span: str | None = None):
    mapping = adapt_raw_document(raw)
    blocks = {block.span_id: block for block in mapping.domain.blocks}
    ids = span_ids or tuple(blocks)
    dispositions = []
    for span_id in ids:
        block = blocks[span_id]
        disposition = "heading" if span_id == conflict_span else "body"
        dispositions.append(
            {
                "span_id": span_id,
                "disposition": disposition,
                "source_text_digest": block.text_digest,
                "confidence": 0.8,
            }
        )
    return {
        "recovery_id": "RECOVERY-M3B-TEST-001",
        "document_id": mapping.domain.document_id,
        "source_digest": raw.source_digest,
        "confidence": 0.8,
        "sections": [],
        "dispositions": dispositions,
        "associations": [],
        "boundary_alternatives": [],
        "disagreements": [],
        "model": "fake",
        "prompt_id": "structure.recover-window",
    }


def test_auto_always_scans_clean_parser_and_skips_recovery(composer: PromptPackComposer) -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    normalized = normalize_document(raw)
    gateway, fake = _gateway([_scan(raw, normalized, decision="accept_parser")])

    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(normalized)

    assert result.scan is not None
    assert result.selected_view.origin == "parser"
    assert result.recovered_proposal is None
    assert len(fake.calls) == 1
    assert fake.calls[0]["route"] == "gemini-3.1-flash-lite"
    assert result.metadata is not None
    assert result.metadata.call_manifests[0].prompt_id == "structure.triage"
    assert result.metadata.call_manifests[0].input_digests


def test_auto_recovers_after_poor_scan_and_promotes_only_exact_coverage(
    composer: PromptPackComposer,
) -> None:
    raw = _raw(FIXTURE_ROOT / "mild-mess.md")
    normalized = normalize_document(raw)
    gateway, fake = _gateway(
        [
            _scan(raw, normalized, decision="recover"),
            _proposal(raw),
        ]
    )

    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)

    assert result.selected_view.origin == "llm_recovered"
    assert result.validation.passed
    assert result.recovered_proposal is not None
    assert [item.source_span_id for item in result.selected_view.blocks] == [
        block.span_id for block in raw.blocks
    ]
    assert len(fake.calls) == 2
    metadata = result.metadata
    assert metadata is not None
    assert [call.prompt_id for call in metadata.call_manifests] == [
        "structure.triage",
        "structure.recover-window",
    ]


@pytest.mark.parametrize("mode", ["off", "parser"])
def test_explicit_non_model_modes_are_deterministic(
    mode: Literal["off", "parser"],
) -> None:
    raw = _raw(FIXTURE_ROOT / "severe-mess.md")
    gateway, fake = _gateway([])
    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode=mode), gateway=gateway
    ).run(raw)
    assert result.selected_view.origin == "parser"
    assert result.metadata is not None
    assert result.metadata.call_manifests == ()
    assert fake.calls == []
    marker = "disabled" if mode == "off" else "parser_mode"
    assert marker in " ".join(result.selected_view.warnings)


def test_long_document_uses_overlapping_windows_and_one_reconciliation_call(
    tmp_path: Path, composer: PromptPackComposer
) -> None:
    source = tmp_path / "long.md"
    source.write_text(
        "# Root\n\n" + "\n\n".join(f"Paragraph {index} with stable text." for index in range(28)),
        encoding="utf-8",
    )
    raw = _raw(source)
    mapping = adapt_raw_document(raw)
    config = StructureRecoveryConfig(mode="recover", max_window_chars=400)
    windows = build_recovery_windows(mapping.domain, config)
    assert len(windows) > 1
    assert any(
        set(left.span_ids) & set(right.span_ids)
        for left, right in zip(windows, windows[1:], strict=False)
    )

    proposals = []
    shared_conflict = windows[1].span_ids[0]
    for index, window in enumerate(windows):
        proposals.append(
            _proposal(
                raw,
                span_ids=window.span_ids,
                conflict_span=shared_conflict if index == 1 else None,
            )
        )
    reconciliation_response = _proposal(raw)
    reconciliation_response["prompt_id"] = "structure.reconcile-boundaries"
    proposals.append(reconciliation_response)
    gateway, fake = _gateway(proposals)
    result = StructureRecoveryService(config=config, gateway=gateway, prompt_composer=composer).run(
        raw
    )

    assert result.reconciliation is not None
    assert result.conflicts
    assert result.validation.passed
    assert len(fake.calls) == len(windows) + 1
    assert fake.calls[-1]["route"] == "gemini-3.1-flash-lite"
    assert result.metadata is not None
    assert result.metadata.call_manifests[-1].prompt_id == "structure.reconcile-boundaries"


def test_validation_rejects_duplicate_gaps_mutation_and_crossing_sections() -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    mapping = adapt_raw_document(raw)
    ids = tuple(cast(str, block.span_id) for block in mapping.domain.blocks)
    proposal = StructureRecoveryProposal.model_validate(_proposal(raw))
    proposal = proposal.model_copy(
        update={
            "dispositions": [
                proposal.dispositions[0],
                proposal.dispositions[0].model_copy(update={"source_text_digest": "0" * 64}),
                *proposal.dispositions[2:],
            ],
            "sections": [
                RecoveredSection(
                    section_id="SEC-M3B-A",
                    label="A",
                    level=1,
                    start_span_id=ids[0],
                    end_span_id=ids[3],
                    confidence=0.8,
                ),
                RecoveredSection(
                    section_id="SEC-M3B-B",
                    label="B",
                    level=1,
                    start_span_id=ids[2],
                    end_span_id=ids[-1],
                    confidence=0.8,
                ),
            ],
        }
    )
    report = validate_recovery_proposal(proposal, mapping.domain)
    assert not report.passed
    assert any("duplicate" in error for error in report.errors)
    assert any("digest mismatch" in error for error in report.errors)
    assert any("crossing" in error for error in report.errors)


def test_invalid_model_result_cannot_promote_selected_view(composer: PromptPackComposer) -> None:
    raw = _raw(FIXTURE_ROOT / "severe-mess.md")
    normalized = normalize_document(raw)
    invalid = _proposal(raw)
    invalid["dispositions"] = invalid["dispositions"][:-1]
    gateway, _ = _gateway([_scan(raw, normalized, decision="recover"), invalid])
    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)
    assert result.selected_view.origin == "parser"
    assert not result.validation.passed
    assert result.recovered_proposal is None


def test_persistence_replaces_only_deferred_reservations_and_reconciles(
    tmp_path: Path, composer: PromptPackComposer
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Title\n\nBody\n", encoding="utf-8")
    raw = _raw(source)
    normalized = normalize_document(raw)
    storage = RunStorage.for_source(tmp_path / "runs", raw)
    storage.persist_ingest(normalized)
    gateway, _ = _gateway([_proposal(raw)])
    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="recover"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw, repository=storage)
    run_dir = storage.paths.run_dir
    assert result.metadata is not None
    assert json.loads((run_dir / "source/recovered-outline.json").read_text())["model"] == "fake"
    assert (run_dir / "source/model-calls.json").is_file()
    assert json.loads((run_dir / "manifest.json").read_text())["structure_recovery_digest"]
    assert storage.reconcile().consistent


def test_gateway_cache_bounds_retries_and_does_not_store_source(
    tmp_path: Path, composer: PromptPackComposer
) -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    normalized = normalize_document(raw)
    cache = ResponseCache(tmp_path / "cache")
    response = _scan(raw, normalized, decision="accept_parser")
    first_gateway, first_fake = _gateway([response], cache=cache)
    first = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=first_gateway,
        prompt_composer=composer,
    ).run(raw)
    second_gateway, second_fake = _gateway([], cache=cache)
    second = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=second_gateway,
        prompt_composer=composer,
    ).run(raw)
    assert first_fake.calls and second_fake.calls == []
    assert first.metadata is not None and second.metadata is not None
    assert second.metadata.call_manifests[0].status is CallStatus.CACHE_HIT
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "cache").glob("*.json")
    )
    assert raw.blocks[0].text not in serialized
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1
