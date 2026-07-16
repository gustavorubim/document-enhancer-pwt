from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from document_enhancer.artifacts.manifest import RunManifest
from document_enhancer.artifacts.run_storage import RunStorage
from document_enhancer.domain.analysis import (
    RecoveredSection,
    StructureRecoveryProposal,
)
from document_enhancer.ingest.markdown import MarkdownParser
from document_enhancer.ingest.models import RecoveryThresholds
from document_enhancer.ingest.normalize import normalize_document
from document_enhancer.ingest.recovery import (
    StructureRecoveryConfig,
    StructureRecoveryService,
    adapt_raw_document,
    build_recovery_windows,
    merge_window_proposals,
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


def _gateway(responses: list[object], *, cache: ResponseCache | None = None, max_repairs: int = 0):
    fake = FakeStructuredModel(responses)
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(
            max_retries_override=0,
            max_repairs_override=max_repairs,
            retry_backoff_seconds=0,
        ),
        model_factory=lambda *_: fake,
        cache=cache,
    )
    return gateway, fake


def _scan(
    raw,
    normalized,
    *,
    decision: str,
    scan_id: str = "SCAN-M3B-TEST-001",
) -> dict[str, object]:
    mapping = adapt_raw_document(raw)
    from document_enhancer.ingest.recovery import _outline_digest  # noqa: PLC0415

    return {
        "scan_id": scan_id,
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


def _proposal(
    raw,
    *,
    span_ids: tuple[str, ...] | None = None,
    conflict_span: str | None = None,
    recovery_id: str = "RECOVERY-M3B-TEST-001",
    model: str = "fake",
    confidence: float = 0.8,
):
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
                "confidence": confidence,
            }
        )
    return {
        "recovery_id": recovery_id,
        "document_id": mapping.domain.document_id,
        "source_digest": raw.source_digest,
        "confidence": 0.8,
        "sections": [],
        "dispositions": dispositions,
        "associations": [],
        "boundary_alternatives": [],
        "disagreements": [],
        "model": model,
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


def test_service_reuse_resets_calls_resolutions_and_budgets(composer: PromptPackComposer) -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    normalized = normalize_document(raw)
    response = _scan(raw, normalized, decision="accept_parser")
    gateway, fake = _gateway([response, response])
    service = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    )

    first = service.run(raw)
    second = service.run(raw)

    assert first.metadata is not None and second.metadata is not None
    assert len(first.metadata.call_manifests) == 1
    assert len(second.metadata.call_manifests) == 1
    assert len(first.metadata.prompt_resolutions) == 1
    assert len(second.metadata.prompt_resolutions) == 1
    assert len(fake.calls) == 2


def test_auto_scan_failure_preserves_quality_recovery_route(composer: PromptPackComposer) -> None:
    raw = _raw(FIXTURE_ROOT / "severe-mess.md")
    normalized = normalize_document(raw)
    assert normalized.routing.mode == "llm_recovery"
    gateway, fake = _gateway([RuntimeError("triage unavailable"), _proposal(raw)])

    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)

    assert result.scan is None
    assert result.selected_view.origin == "llm_recovered"
    assert result.validation.passed
    assert len(fake.calls) == 2
    assert result.metadata is not None
    assert any("structure_scan_failed" in warning for warning in result.metadata.warnings)


class _PromptVariant:
    def __init__(
        self, base: PromptPackComposer, version: str, prompt_ids: set[str] | None = None
    ) -> None:
        self.base = base
        self.version = version
        self.prompt_ids = prompt_ids

    def compose_with_metadata(self, prompt_id: str, variables: Mapping[str, Any]):
        composed = self.base.compose_with_metadata(prompt_id, variables)
        if self.prompt_ids is not None and prompt_id not in self.prompt_ids:
            return composed
        resolution = composed.resolution.model_copy(
            update={
                "pack_version": self.version,
                "rendered_prompt_digest": ("a" if self.version.endswith("a") else "b") * 64,
            }
        )
        return replace(composed, resolution=resolution)


def test_structure_cache_keys_are_complete_stable_and_pre_execution(
    tmp_path: Path, composer: PromptPackComposer
) -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    normalized = normalize_document(raw)
    config = StructureRecoveryConfig(mode="auto")

    first_gateway, _ = _gateway([_scan(raw, normalized, decision="accept_parser")])
    first = StructureRecoveryService(
        config=config, gateway=first_gateway, prompt_composer=composer
    ).run(raw)
    stable_gateway, _ = _gateway([_scan(raw, normalized, decision="accept_parser")])
    stable = StructureRecoveryService(
        config=config, gateway=stable_gateway, prompt_composer=composer
    ).run(raw)
    assert first.metadata is not None and stable.metadata is not None
    assert first.metadata.cache_keys == stable.metadata.cache_keys

    changed_scan_gateway, _ = _gateway(
        [_scan(raw, normalized, decision="accept_parser", scan_id="SCAN-M3B-TEST-002")]
    )
    changed_scan = StructureRecoveryService(
        config=config, gateway=changed_scan_gateway, prompt_composer=composer
    ).run(raw)
    assert changed_scan.metadata is not None
    assert (
        changed_scan.metadata.cache_keys["structure_scan"]
        == first.metadata.cache_keys["structure_scan"]
    )

    changed_config_gateway, _ = _gateway([_scan(raw, normalized, decision="accept_parser")])
    changed_config = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto", max_window_chars=99_999),
        gateway=changed_config_gateway,
        prompt_composer=composer,
    ).run(raw)
    assert changed_config.metadata is not None
    assert (
        changed_config.metadata.cache_keys["structure_scan"]
        == first.metadata.cache_keys["structure_scan"]
    )
    assert (
        changed_config.metadata.cache_keys["structure_recovery"]
        != first.metadata.cache_keys["structure_recovery"]
    )
    assert (
        changed_config.metadata.cache_keys["selected_view"]
        != first.metadata.cache_keys["selected_view"]
    )

    changed_threshold_gateway, _ = _gateway([_scan(raw, normalized, decision="accept_parser")])
    changed_threshold = StructureRecoveryService(
        config=StructureRecoveryConfig(
            mode="auto",
            thresholds=RecoveryThresholds(minimum_structure_score=0.61),
        ),
        gateway=changed_threshold_gateway,
        prompt_composer=composer,
    ).run(raw)
    assert changed_threshold.metadata is not None
    assert (
        changed_threshold.metadata.cache_keys["structure_scan"]
        == first.metadata.cache_keys["structure_scan"]
    )
    assert (
        changed_threshold.metadata.cache_keys["selected_view"]
        != first.metadata.cache_keys["selected_view"]
    )

    changed_prompt_gateway, _ = _gateway([_scan(raw, normalized, decision="accept_parser")])
    changed_prompt = StructureRecoveryService(
        config=config,
        gateway=changed_prompt_gateway,
        prompt_composer=_PromptVariant(composer, "variant-b"),
    ).run(raw)
    assert changed_prompt.metadata is not None
    assert (
        changed_prompt.metadata.cache_keys["structure_scan"]
        != first.metadata.cache_keys["structure_scan"]
    )

    changed_source = tmp_path / "changed.md"
    changed_source.write_text("# Changed\n\nBody\n", encoding="utf-8")
    changed_raw = _raw(changed_source)
    changed_normalized = normalize_document(changed_raw)
    changed_source_gateway, _ = _gateway(
        [_scan(changed_raw, changed_normalized, decision="accept_parser")]
    )
    changed_source_result = StructureRecoveryService(
        config=config, gateway=changed_source_gateway, prompt_composer=composer
    ).run(changed_raw)
    assert changed_source_result.metadata is not None
    assert (
        changed_source_result.metadata.cache_keys["structure_scan"]
        != first.metadata.cache_keys["structure_scan"]
    )


def test_recovery_key_excludes_recovery_output_but_selected_key_tracks_upstream(
    composer: PromptPackComposer,
) -> None:
    raw = _raw(FIXTURE_ROOT / "severe-mess.md")
    config = StructureRecoveryConfig(mode="recover")
    first_gateway, _ = _gateway([_proposal(raw, recovery_id="RECOVERY-M3B-TEST-A")])
    first = StructureRecoveryService(
        config=config, gateway=first_gateway, prompt_composer=composer
    ).run(raw)
    second_gateway, _ = _gateway(
        [_proposal(raw, recovery_id="RECOVERY-M3B-TEST-B", confidence=0.2)]
    )
    second = StructureRecoveryService(
        config=config, gateway=second_gateway, prompt_composer=composer
    ).run(raw)

    assert first.metadata is not None and second.metadata is not None
    assert (
        first.metadata.cache_keys["structure_recovery"]
        == second.metadata.cache_keys["structure_recovery"]
    )
    assert first.metadata.cache_keys["selected_view"] != second.metadata.cache_keys["selected_view"]


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


def test_low_confidence_recovery_is_explicitly_uncertain(composer: PromptPackComposer) -> None:
    raw = _raw(FIXTURE_ROOT / "mild-mess.md")
    normalized = normalize_document(raw)
    gateway, _ = _gateway(
        [_scan(raw, normalized, decision="recover"), _proposal(raw, confidence=0.2)]
    )

    result = StructureRecoveryService(
        config=StructureRecoveryConfig(mode="auto"),
        gateway=gateway,
        prompt_composer=composer,
    ).run(raw)

    assert result.validation.passed
    assert result.selected_view.origin == "llm_recovered"
    assert all(block.disposition == "uncertain" for block in result.selected_view.blocks)


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


def test_reconciliation_prompt_change_invalidates_only_reconciliation_stage(
    tmp_path: Path, composer: PromptPackComposer
) -> None:
    source = tmp_path / "long.md"
    source.write_text(
        "# Root\n\n" + "\n\n".join(f"Paragraph {index}." for index in range(28)),
        encoding="utf-8",
    )
    raw = _raw(source)
    mapping = adapt_raw_document(raw)
    config = StructureRecoveryConfig(mode="recover", max_window_chars=400)
    windows = build_recovery_windows(mapping.domain, config)
    shared_conflict = windows[1].span_ids[0]

    def responses() -> list[object]:
        values = [
            _proposal(
                raw,
                span_ids=window.span_ids,
                conflict_span=shared_conflict if index == 1 else None,
            )
            for index, window in enumerate(windows)
        ]
        reconciliation = _proposal(raw)
        reconciliation["prompt_id"] = "structure.reconcile-boundaries"
        values.append(reconciliation)
        return values

    first_gateway, _ = _gateway(responses())
    first = StructureRecoveryService(
        config=config, gateway=first_gateway, prompt_composer=composer
    ).run(raw)
    changed_gateway, _ = _gateway(responses())
    changed = StructureRecoveryService(
        config=config,
        gateway=changed_gateway,
        prompt_composer=_PromptVariant(
            composer, "variant-reconciliation", {"structure.reconcile-boundaries"}
        ),
    ).run(raw)

    assert first.metadata is not None and changed.metadata is not None
    assert (
        first.metadata.cache_keys["structure_scan"] == changed.metadata.cache_keys["structure_scan"]
    )
    assert (
        first.metadata.cache_keys["structure_recovery"]
        == changed.metadata.cache_keys["structure_recovery"]
    )
    assert (
        first.metadata.cache_keys["structure_reconciliation"]
        != changed.metadata.cache_keys["structure_reconciliation"]
    )
    assert (
        first.metadata.cache_keys["selected_view"] != changed.metadata.cache_keys["selected_view"]
    )


def test_window_merge_retains_section_and_disagreement_conflicts() -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    mapping = adapt_raw_document(raw)
    ids = tuple(cast(str, block.span_id) for block in mapping.domain.blocks)
    disagreement = {
        "span_ids": [ids[0]],
        "parser_label": "body",
        "model_label": "heading",
        "resolution": None,
        "requires_review": True,
    }
    first_payload = _proposal(raw)
    first_payload["sections"] = [
        {
            "section_id": "SEC-M3B-CONFLICT",
            "label": "First",
            "level": 1,
            "start_span_id": ids[0],
            "end_span_id": ids[1],
            "confidence": 0.8,
        }
    ]
    first_payload["disagreements"] = [disagreement]
    second_payload = _proposal(raw)
    second_payload["sections"] = [
        {
            "section_id": "SEC-M3B-CONFLICT",
            "label": "Second",
            "level": 2,
            "start_span_id": ids[0],
            "end_span_id": ids[-1],
            "confidence": 0.8,
        }
    ]
    second_payload["disagreements"] = [disagreement]

    merged = merge_window_proposals(
        [
            StructureRecoveryProposal.model_validate(first_payload),
            StructureRecoveryProposal.model_validate(second_payload),
        ],
        mapping.domain,
    )

    assert len(merged.sections) == 1
    assert merged.sections[0].label == "First"
    assert merged.sections[0].end_span_id == ids[1]
    assert any(
        disagreement.model_label == "overlapping_window_section_boundary_conflict"
        for disagreement in merged.disagreements
    )
    serialized = [
        json.dumps(item.model_dump(mode="json"), sort_keys=True) for item in merged.disagreements
    ]
    assert len(serialized) == len(set(serialized))


def test_window_merge_retains_same_id_different_alternatives() -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    mapping = adapt_raw_document(raw)
    ids = tuple(cast(str, block.span_id) for block in mapping.domain.blocks)

    def payload(end_span_id: str, label: str) -> dict[str, object]:
        value = _proposal(raw)
        value["boundary_alternatives"] = [
            {
                "alternative_id": "ALT-M3B-SHARED",
                "sections": [
                    {
                        "section_id": "SEC-M3B-ALT",
                        "label": label,
                        "level": 1,
                        "start_span_id": ids[0],
                        "end_span_id": end_span_id,
                        "confidence": 0.6,
                    }
                ],
                "confidence": 0.6,
                "reason": "window ambiguity",
            }
        ]
        return value

    merged = merge_window_proposals(
        [
            StructureRecoveryProposal.model_validate(payload(ids[1], "First")),
            StructureRecoveryProposal.model_validate(payload(ids[-1], "Second")),
        ],
        mapping.domain,
    )

    assert len(merged.boundary_alternatives) == 2
    assert {item.alternative_id for item in merged.boundary_alternatives} == {
        "ALT-M3B-SHARED",
        next(
            item.alternative_id
            for item in merged.boundary_alternatives
            if item.alternative_id != "ALT-M3B-SHARED"
        ),
    }
    assert any(
        disagreement.model_label == "overlapping_window_alternative_conflict"
        for disagreement in merged.disagreements
    )


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


def test_validation_rejects_unknown_order_hierarchy_containment_and_alternatives() -> None:
    raw = _raw(FIXTURE_ROOT / "clean.md")
    mapping = adapt_raw_document(raw)
    ids = tuple(cast(str, block.span_id) for block in mapping.domain.blocks)
    base = _proposal(raw)

    unknown = [dict(item) for item in cast(list[dict[str, object]], base["dispositions"])]
    unknown[0]["span_id"] = "SPAN-UNKNOWNX"
    unknown_proposal = StructureRecoveryProposal.model_validate({**base, "dispositions": unknown})
    unknown_report = validate_recovery_proposal(unknown_proposal, mapping.domain)
    assert any("nonexistent" in error for error in unknown_report.errors)

    reordered = [dict(item) for item in cast(list[dict[str, object]], base["dispositions"])]
    reordered[0], reordered[1] = reordered[1], reordered[0]
    reordered_proposal = StructureRecoveryProposal.model_validate(
        {**base, "dispositions": reordered}
    )
    reordered_report = validate_recovery_proposal(reordered_proposal, mapping.domain)
    assert any("coverage/order" in error for error in reordered_report.errors)

    bounded = [dict(item) for item in cast(list[dict[str, object]], base["dispositions"])]
    for item in bounded:
        item["section_id"] = "SEC-M3B-SHORT"
    invalid = {
        **base,
        "dispositions": bounded,
        "sections": [
            {
                "section_id": "SEC-M3B-SHORT",
                "label": "Short",
                "level": 1,
                "start_span_id": ids[0],
                "end_span_id": ids[1],
                "confidence": 0.8,
            },
            {
                "section_id": "SEC-M3B-NESTED",
                "label": "Nested",
                "level": 1,
                "start_span_id": ids[1],
                "end_span_id": ids[3],
                "confidence": 0.8,
            },
            {
                "section_id": "SEC-M3B-REVERSED",
                "label": "Reversed",
                "level": 1,
                "start_span_id": ids[3],
                "end_span_id": ids[1],
                "confidence": 0.8,
            },
        ],
        "associations": [
            {"span_id": ids[3], "section_id": "SEC-M3B-SHORT", "association": "nearby"}
        ],
        "boundary_alternatives": [
            {
                "alternative_id": "ALT-M3B-BAD",
                "sections": [
                    {
                        "section_id": "SEC-M3B-ALT-A",
                        "label": "A",
                        "level": 1,
                        "start_span_id": ids[0],
                        "end_span_id": ids[3],
                        "confidence": 0.8,
                    },
                    {
                        "section_id": "SEC-M3B-ALT-B",
                        "label": "B",
                        "level": 1,
                        "start_span_id": ids[2],
                        "end_span_id": ids[-1],
                        "confidence": 0.8,
                    },
                ],
                "confidence": 0.5,
                "reason": "bad boundaries",
            }
        ],
    }
    report = validate_recovery_proposal(
        StructureRecoveryProposal.model_validate(invalid), mapping.domain
    )
    assert any("outside section" in error for error in report.errors)
    assert any("nesting" in error for error in report.errors)
    assert any("reversed" in error for error in report.errors)
    assert any("alternative" in error and "crossing" in error for error in report.errors)


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
    manifest = RunManifest.load(storage.paths.manifest)
    assert manifest.cache_keys["structure_scan"] == result.metadata.cache_keys["structure_scan"]
    assert (
        manifest.cache_keys["structure_reconciliation"]
        == result.metadata.cache_keys["structure_reconciliation"]
    )
    scan_stage = next(stage for stage in manifest.stages if stage.stage == "structure_scan")
    scan_record = next(
        record
        for record in manifest.artifacts
        if record.relative_path == "source/structure-scan.json"
    )
    assert scan_stage.artifact_paths == ("source/structure-scan.json",)
    assert scan_stage.artifact_digests == (scan_record.digest,)
    assert "source/model-calls.json" not in scan_stage.artifact_paths
    assert "source/prompt-resolutions.json" not in scan_stage.artifact_paths
    metadata_stage = next(stage for stage in manifest.stages if stage.stage == "structure_metadata")
    assert metadata_stage.cache_key == result.metadata.cache_keys["structure_metadata"]
    assert set(metadata_stage.artifact_paths) == {
        "source/model-calls.json",
        "source/prompt-resolutions.json",
        "source/structure-recovery-metadata.json",
    }


def test_interrupted_multi_artifact_persistence_keeps_prior_revision_and_reconciles(
    tmp_path: Path, composer: PromptPackComposer, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Title\n\nBody\n", encoding="utf-8")
    raw = _raw(source)
    storage = RunStorage.for_source(tmp_path / "runs", raw)
    storage.persist_ingest(normalize_document(raw))

    first_gateway, _ = _gateway([_proposal(raw, recovery_id="RECOVERY-M3B-PRIOR")])
    StructureRecoveryService(
        config=StructureRecoveryConfig(mode="recover"),
        gateway=first_gateway,
        prompt_composer=composer,
    ).run(raw, repository=storage)
    prior_manifest = RunManifest.load(storage.paths.manifest)
    prior_record = next(
        record
        for record in prior_manifest.artifacts
        if record.relative_path == "source/recovery/window-proposals.json"
    )
    prior_version = (
        storage.paths.versions_dir
        / prior_record.relative_path.replace("/", "__")
        / f"{prior_record.digest}.bin"
    )
    assert prior_version.is_file()

    original = storage.repository.put_json_revision
    calls = 0

    def interrupt(
        run_id: str,
        name: str,
        value: object,
        *,
        stage: str = "unknown",
        replace: bool = False,
        replace_deferred: bool = False,
    ):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated multi-artifact interruption")
        return original(
            run_id,
            name,
            value,
            stage=stage,
            replace=replace,
            replace_deferred=replace_deferred,
        )

    monkeypatch.setattr(storage.repository, "put_json_revision", interrupt)
    second_gateway, _ = _gateway([_proposal(raw, recovery_id="RECOVERY-M3B-NEW")])
    with pytest.raises(OSError, match="multi-artifact interruption"):
        StructureRecoveryService(
            config=StructureRecoveryConfig(mode="recover"),
            gateway=second_gateway,
            prompt_composer=composer,
        ).run(raw, repository=storage)

    assert RunManifest.load(storage.paths.manifest) == prior_manifest
    assert prior_version.read_bytes()
    report = storage.reconcile()
    assert report.consistent is False
    assert "structure_recovery" in report.stale_stages


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
