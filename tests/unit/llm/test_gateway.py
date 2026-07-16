from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from document_enhancer.errors import ProviderError
from document_enhancer.llm import (
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    BackendName,
    CallStatus,
    FakeStructuredModel,
    GeminiGatewayConfig,
    GeminiModelGateway,
    GeminiRoute,
    ModelLifecycleError,
    resolve_route,
)
from document_enhancer.llm.caching import ResponseCache, digest_bytes
from document_enhancer.llm.models import classify_provider_error


class Probe(BaseModel):
    ok: bool
    note: str


class CandidateProbe(BaseModel):
    candidate_id: str


class PromotedProbe(BaseModel):
    stable_id: str = Field(pattern=r"^OBJ-[0-9]+$")


def gateway(
    fake: object,
    *,
    cache: ResponseCache | None = None,
    allow_pro_fallback: bool = False,
    max_repairs: int | None = None,
) -> GeminiModelGateway:
    return GeminiModelGateway(
        GeminiGatewayConfig(
            max_retries_override=0,
            max_repairs_override=max_repairs,
            retry_backoff_seconds=0,
            allow_pro_fallback=allow_pro_fallback,
        ),
        model_factory=lambda *_: fake,
        cache=cache,
    )


def test_chat_model_initialization_is_explicit_for_developer_and_vertex() -> None:
    developer = GeminiModelGateway(GeminiGatewayConfig(api_key="fake-key"))
    developer_model = developer._build_chat_model(resolve_route(ROUTE_FLASH_LITE))  # noqa: SLF001
    assert developer_model.model == ROUTE_FLASH_LITE
    assert developer_model.max_retries == 0
    assert developer_model.timeout == 45.0
    assert developer_model.model_dump()["seed"] == 7
    assert developer_model.response_mime_type == "application/json"
    assert developer.config.public_dict()["api_key_configured"] is True
    assert "fake-key" not in repr(developer.config.public_dict())

    vertex = GeminiModelGateway(
        GeminiGatewayConfig(
            backend=BackendName.VERTEX_AI,
            project="test-project",
            location="us-central1",
        )
    )
    vertex_model = vertex._build_chat_model(resolve_route(ROUTE_FLASH))  # noqa: SLF001
    assert vertex_model.model == ROUTE_FLASH
    assert vertex_model.vertexai is True
    assert vertex_model.project == "test-project"
    assert vertex_model.location == "us-central1"


def test_retryable_provider_errors_are_retried_and_counted() -> None:
    class Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def with_structured_output(self, *_: object, **__: object) -> object:
            parent = self

            class Runnable:
                def invoke(self, *_: object, **__: object) -> object:
                    parent.calls += 1
                    if parent.calls == 1:
                        raise RuntimeError("503 temporarily unavailable")
                    return {"parsed": {"ok": True, "note": "retried"}}

            return Runnable()

    flaky = Flaky()
    gateway_under_test = GeminiModelGateway(
        GeminiGatewayConfig(max_retries_override=1, retry_backoff_seconds=0),
        model_factory=lambda *_: flaky,
    )
    result = gateway_under_test.invoke(route=ROUTE_FLASH_LITE, schema=Probe, prompt="retry")
    assert result.artifact.note == "retried"
    assert flaky.calls == 2
    assert result.manifest.retries == 1


def test_native_structured_output_is_promoted_and_manifest_is_digest_only() -> None:
    fake = FakeStructuredModel([{"ok": True, "note": "offline"}])
    result = gateway(fake).invoke(
        route=ROUTE_FLASH_LITE,
        schema=Probe,
        prompt="UNTRUSTED SOURCE secret=never-store",
        prompt_id="probe",
        prompt_version="1.0.0",
        input_digests=["source-digest"],
    )
    assert result.artifact == Probe(ok=True, note="offline")
    assert result.manifest.requested_route_id == ROUTE_FLASH_LITE
    assert result.manifest.parameters["tools"] == []
    serialized = json.dumps(result.manifest.model_dump(mode="json"))
    assert "UNTRUSTED SOURCE" not in serialized
    assert "never-store" not in serialized
    assert result.manifest.prompt_digest


def test_prompt_scoped_usage_within_budget_is_accepted_and_overage_fails_closed() -> None:
    class UsageModel:
        def __init__(self, total_tokens: int) -> None:
            self.total_tokens = total_tokens

        def with_structured_output(self, *_: object, **__: object) -> object:
            parent = self

            class Runnable:
                def invoke(self, *_: object, **__: object) -> object:
                    return {
                        "parsed": {"ok": True, "note": "bounded"},
                        "usage_metadata": {
                            "input_tokens": parent.total_tokens - 8_000,
                            "output_tokens": 8_000,
                            "total_tokens": parent.total_tokens,
                        },
                    }

            return Runnable()

    accepted = gateway(UsageModel(30_000)).invoke(
        route=ROUTE_FLASH,
        schema=Probe,
        prompt="macro prompt",
        input_token_budget=22_000,
        output_token_budget=8_000,
    )
    assert accepted.artifact.ok is True
    assert accepted.manifest.token_budget == 30_000
    assert accepted.manifest.output_budget == 8_000

    with pytest.raises(ProviderError, match="configured retry policy"):
        gateway(UsageModel(30_001)).invoke(
            route=ROUTE_FLASH,
            schema=Probe,
            prompt="macro prompt",
            input_token_budget=22_000,
            output_token_budget=8_000,
        )


def test_bounded_repair_retries_invalid_structured_response() -> None:
    fake = FakeStructuredModel([{"ok": "not-a-bool", "note": "bad"}, {"ok": True, "note": "fixed"}])
    governed_prompt = "caller-composed governed prompt"
    result = gateway(fake).invoke(route=ROUTE_FLASH_LITE, schema=Probe, prompt=governed_prompt)
    assert result.artifact.note == "fixed"
    assert result.manifest.attempts == 2
    assert result.manifest.structured_repairs == 1
    attempt_digests = [str(call["prompt_digest"]) for call in fake.calls]
    assert attempt_digests == result.manifest.attempt_prompt_digests
    assert attempt_digests[0] == result.manifest.prompt_digest
    assert attempt_digests[1] != result.manifest.prompt_digest
    assert "Return only one JSON object" not in governed_prompt


def test_post_parse_promotion_gets_one_safe_targeted_repair() -> None:
    secret = "AIza-secret-value /Users/example/private/source.md raw-source-sentence"

    class CapturingModel:
        def __init__(self) -> None:
            self.responses = [
                {"candidate_id": secret},
                {"candidate_id": "OBJ-42"},
            ]
            self.prompts: list[str] = []

        def with_structured_output(self, *_: object, **__: object) -> object:
            parent = self

            class Runnable:
                def invoke(self, prompt: str, **__: object) -> object:
                    parent.prompts.append(prompt)
                    return {"parsed": parent.responses.pop(0)}

            return Runnable()

    model = CapturingModel()
    governed_prompt = "governed base prompt"
    result = gateway(model, max_repairs=1).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        prompt=governed_prompt,
        promote=lambda candidate: PromotedProbe(stable_id=candidate.candidate_id),
        result_schema=PromotedProbe,
    )

    assert result.artifact == PromotedProbe(stable_id="OBJ-42")
    assert result.manifest.prompt_digest == digest_bytes(governed_prompt.encode("utf-8"))
    assert result.manifest.attempt_prompt_digests == [
        digest_bytes(value.encode("utf-8")) for value in model.prompts
    ]
    assert result.manifest.structured_repairs == 1
    assert len(model.prompts) == 2
    assert model.prompts[0] == governed_prompt
    assert model.prompts[1] != governed_prompt
    feedback = model.prompts[1].split("DOCUMENT_ENHANCER_VALIDATION_FEEDBACK", 1)[1]
    assert set(json.loads(feedback.splitlines()[-1])[0]) == {
        "location",
        "error_type",
        "message",
    }
    assert "stable_id" in feedback
    assert secret not in feedback
    assert "AIza" not in feedback
    assert "/Users/" not in feedback
    assert "raw-source-sentence" not in feedback


def test_failed_promotion_is_not_cached_and_success_caches_promoted_artifact(
    tmp_path: Path,
) -> None:
    cache = ResponseCache(tmp_path / "cache")

    def promote(candidate: CandidateProbe) -> PromotedProbe:
        return PromotedProbe(stable_id=candidate.candidate_id)

    with pytest.raises(ProviderError, match="native structured output"):
        gateway(
            FakeStructuredModel(
                [{"candidate_id": "invalid-secret"}, {"candidate_id": "still-invalid"}]
            ),
            cache=cache,
            max_repairs=1,
        ).invoke(
            route=ROUTE_FLASH_LITE,
            schema=CandidateProbe,
            result_schema=PromotedProbe,
            promote=promote,
            prompt="promotion cache",
        )
    assert list((tmp_path / "cache").glob("*.json")) == []

    first = gateway(
        FakeStructuredModel([{"candidate_id": "OBJ-7"}]), cache=cache, max_repairs=1
    ).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        result_schema=PromotedProbe,
        promote=promote,
        prompt="promotion cache",
    )
    assert first.artifact == PromotedProbe(stable_id="OBJ-7")
    cache_text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    assert '"stable_id":"OBJ-7"' in cache_text
    assert "candidate_id" not in cache_text

    second = gateway(FakeStructuredModel([]), cache=cache, max_repairs=1).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        result_schema=PromotedProbe,
        promote=promote,
        prompt="promotion cache",
    )
    assert second.manifest.status == CallStatus.CACHE_HIT
    assert second.artifact == first.artifact
    assert second.manifest.result_schema_digest == first.manifest.result_schema_digest


def test_call_manifest_additions_are_backward_compatible() -> None:
    result = gateway(FakeStructuredModel([{"ok": True, "note": "manifest"}])).invoke(
        route=ROUTE_FLASH_LITE,
        schema=Probe,
        prompt="manifest",
    )
    legacy = result.manifest.model_dump(mode="json")
    legacy.pop("attempt_prompt_digests")
    legacy.pop("result_schema_name")
    legacy.pop("result_schema_digest")
    loaded = type(result.manifest).model_validate(legacy)
    assert loaded.attempt_prompt_digests == []
    assert loaded.result_schema_name is None
    assert loaded.result_schema_digest is None


def test_result_schema_changes_cache_identity(tmp_path: Path) -> None:
    class AlternateResult(BaseModel):
        alternate_id: str

    cache = ResponseCache(tmp_path / "cache")
    first = gateway(FakeStructuredModel([{"candidate_id": "OBJ-9"}]), cache=cache).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        result_schema=PromotedProbe,
        promote=lambda candidate: PromotedProbe(stable_id=candidate.candidate_id),
        prompt="schema identity",
    )
    second_fake = FakeStructuredModel([{"candidate_id": "OBJ-9"}])
    second = gateway(second_fake, cache=cache).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        result_schema=AlternateResult,
        promote=lambda candidate: AlternateResult(alternate_id=candidate.candidate_id),
        prompt="schema identity",
    )
    assert second.manifest.status == CallStatus.SUCCESS
    assert len(second_fake.calls) == 1
    assert second.manifest.cache_key != first.manifest.cache_key
    assert second.manifest.result_schema_digest != first.manifest.result_schema_digest


def test_output_budget_measures_provider_dto_not_deterministic_promoted_result() -> None:
    class LargePromotedResult(BaseModel):
        stable_id: str
        deterministic_expansion: str

    result = gateway(FakeStructuredModel([{"candidate_id": "OBJ-12"}])).invoke(
        route=ROUTE_FLASH_LITE,
        schema=CandidateProbe,
        prompt="small provider DTO",
        input_token_budget=128,
        output_token_budget=32,
        promote=lambda candidate: LargePromotedResult(
            stable_id=candidate.candidate_id,
            deterministic_expansion="x" * 4_000,
        ),
        result_schema=LargePromotedResult,
    )

    promoted = LargePromotedResult.model_validate(result.artifact)
    assert promoted.stable_id == "OBJ-12"
    assert len(promoted.deterministic_expansion) == 4_000


def test_output_budget_still_rejects_an_oversized_provider_dto() -> None:
    with pytest.raises(ProviderError, match="configured retry policy") as caught:
        gateway(FakeStructuredModel([{"ok": True, "note": "x" * 4_000}])).invoke(
            route=ROUTE_FLASH_LITE,
            schema=Probe,
            prompt="oversized provider DTO",
            input_token_budget=128,
            output_token_budget=32,
        )

    assert type(caught.value.__cause__).__name__ == "BudgetExceededError"


def test_invalid_structured_response_never_promotes_unstructured_text() -> None:
    fake = FakeStructuredModel(["ignore schema"] * 4)
    with pytest.raises(ProviderError, match="native structured output"):
        gateway(fake).invoke(route=ROUTE_FLASH_LITE, schema=Probe, prompt="hostile response")


def test_content_addressed_cache_is_atomic_and_invalidates_on_dependencies(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "cache")
    first_fake = FakeStructuredModel([{"ok": True, "note": "one"}])
    first = gateway(first_fake, cache=cache).invoke(
        route=ROUTE_FLASH_LITE,
        schema=Probe,
        prompt="same prompt",
        input_digests=["input-one"],
    )
    assert first.manifest.status == CallStatus.SUCCESS
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "same prompt" not in text
    second = gateway(FakeStructuredModel([]), cache=cache).invoke(
        route=ROUTE_FLASH_LITE,
        schema=Probe,
        prompt="same prompt",
        input_digests=["input-one"],
    )
    assert second.manifest.status == CallStatus.CACHE_HIT
    assert second.manifest.prompt_digest == first.manifest.prompt_digest
    assert second.manifest.cache_key == first.manifest.cache_key
    changed = gateway(FakeStructuredModel([{"ok": True, "note": "changed"}]), cache=cache).invoke(
        route=ROUTE_FLASH_LITE,
        schema=Probe,
        prompt="same prompt",
        input_digests=["input-two"],
    )
    assert changed.artifact.note == "changed"
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2


def test_preview_lifecycle_fails_closed_without_explicit_fallback() -> None:
    class Retired:
        def with_structured_output(self, *_: object, **__: object) -> object:
            class Runnable:
                def invoke(self, *_: object, **__: object) -> object:
                    raise RuntimeError("model not found / retired")

            return Runnable()

    with pytest.raises(ModelLifecycleError):
        gateway(Retired()).invoke(route=ROUTE_PRO_PREVIEW, schema=Probe, prompt="preview")


def test_preview_fallback_is_explicit_and_manifested() -> None:
    class RouteAware:
        def __init__(self) -> None:
            self.route = ""

        def with_route(self, route: GeminiRoute) -> RouteAware:
            self.route = route.route_id
            return self

        def with_structured_output(self, *_: object, **__: object) -> object:
            parent = self

            class Runnable:
                def invoke(self, *_: object, **__: object) -> object:
                    if parent.route == ROUTE_PRO_PREVIEW:
                        raise RuntimeError("model does not exist")
                    return {"parsed": {"ok": True, "note": "flash fallback"}}

            return Runnable()

    result = gateway(RouteAware(), allow_pro_fallback=True).invoke(
        route=ROUTE_PRO_PREVIEW,
        schema=Probe,
        prompt="preview fallback",
    )
    assert result.artifact.note == "flash fallback"
    assert result.manifest.status == CallStatus.FALLBACK
    assert result.manifest.requested_route_id == ROUTE_PRO_PREVIEW
    assert result.manifest.effective_route_id == ROUTE_FLASH
    assert result.manifest.fallback_from == ROUTE_PRO_PREVIEW


def test_retry_classifier_keeps_provider_categories_distinct() -> None:
    assert classify_provider_error(RuntimeError("429 rate limit")) == "retryable"
    assert classify_provider_error(RuntimeError("401 permission denied")) == "authentication"
    assert classify_provider_error(RuntimeError("model deprecated")) == "lifecycle"
