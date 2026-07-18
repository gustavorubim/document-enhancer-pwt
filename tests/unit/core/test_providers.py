"""Provider seam tests use the existing structured fake and never call the network."""

from types import SimpleNamespace
from typing import Any

import pytest

from document_enhancer.core.models import ReviewReport
from document_enhancer.core.providers import (
    GeminiAuditProvider,
    GeminiReviewProvider,
    GeminiRewriteProvider,
    GeminiStructureProvider,
)
from document_enhancer.llm import FakeStructuredModel, GeminiGatewayConfig, GeminiModelGateway


@pytest.mark.unit
def test_gemini_review_provider_promotes_only_typed_review_bundle() -> None:
    fake = FakeStructuredModel(
        [
            {
                "summary": "one provider finding",
                "findings": [],
                "questions": [],
                "sections": [],
                "mermaid": "flowchart TD\n",
            }
        ]
    )
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )

    result = GeminiReviewProvider(gateway).review(
        source_text="# Heading\n\nBody",
        source_digest="a" * 64,
        recipe=None,
    )

    assert result.summary == "one provider finding"
    assert fake.calls


@pytest.mark.unit
def test_gemini_rewrite_provider_returns_text_and_change_ledger() -> None:
    fake = FakeStructuredModel(
        [{"final_markdown": "# Final\n\nApproved.", "changes": ["clarified owner"]}]
    )
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )

    text, changes = GeminiRewriteProvider(gateway).rewrite(
        source_text="# Source\n\nTBD",
        review=ReviewReport(summary="review"),
        decisions=[{"question_id": "q-1", "answer": "Approved"}],
        source_digest="b" * 64,
    )

    assert text == "# Final\n\nApproved.\n"
    assert changes == ["clarified owner"]


@pytest.mark.unit
def test_gemini_rewrite_prompt_treats_the_template_as_structure_only() -> None:
    class CapturingGateway:
        prompt = ""

        def structured(self, **kwargs: object) -> object:
            self.prompt = str(kwargs["prompt"])
            return SimpleNamespace(final_markdown="# Final", changes=[])

    gateway: Any = CapturingGateway()

    GeminiRewriteProvider(gateway).rewrite(
        source_text="# Source\n\nSupported content.",
        review=ReviewReport(summary="review"),
        decisions=[],
        source_digest="b" * 64,
        template_text="# Template\n\nTBD",
    )

    prompt = gateway.prompt
    assert "template as a structural guide" in prompt
    assert "never copy template placeholders" in prompt
    assert "Preserve all source sections" in prompt


@pytest.mark.unit
def test_gemini_structure_provider_returns_typed_sections() -> None:
    fake = FakeStructuredModel(
        [
            {
                "sections": [
                    {
                        "section_id": "section-1",
                        "title": "Recovered",
                        "level": 1,
                        "span_ids": ["span-1"],
                    }
                ],
                "rationale": "heading boundary was implicit",
            }
        ]
    )
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )

    sections = GeminiStructureProvider(gateway).recover(
        source_text="Recovered\nBody",
        source_digest="c" * 64,
        spans=[{"span_id": "span-1", "text": "Recovered\nBody"}],
        recipe=None,
    )

    assert sections[0].section_id == "section-1"


@pytest.mark.unit
def test_gemini_audit_provider_returns_independent_audit() -> None:
    fake = FakeStructuredModel(
        [
            {
                "status": "pass",
                "checks": [{"name": "owner_supported", "passed": True}],
                "blockers": [],
                "summary": "content is supported",
            }
        ]
    )
    gateway = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=0, max_repairs_override=0),
        model_factory=lambda *_: fake,
    )

    result = GeminiAuditProvider(gateway).audit(
        source_text="# Source\nOwner reviews.",
        final_text="# Source\nOwner reviews.",
        review=ReviewReport(summary="review"),
        decisions=[],
        source_digest="d" * 64,
    )

    assert result.status == "pass"
    assert result.checks == {"owner_supported": True}


@pytest.mark.unit
def test_provider_finding_promotion_recovers_rubric_and_disposition_mixups() -> None:
    from document_enhancer.core.providers import _promote_finding, _ProviderFinding

    promoted = _promote_finding(
        _ProviderFinding(
            finding_id="f-1",
            scope="PROC-TRIGGER-001",
            severity="correct",
            title="Triggers look complete",
            detail="Entry criteria are present in the source.",
            rubric_id="ignored",
            section_id="section-007",
            evidence_span_ids=["span-1"],
        )
    )

    assert promoted is not None
    assert promoted.scope == "section"
    assert promoted.severity == "warning"
    assert promoted.disposition == "correct"
    assert promoted.rubric_id == "PROC-TRIGGER-001"
