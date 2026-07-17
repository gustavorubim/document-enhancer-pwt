"""The narrow, fakeable Gemini model gateway and its call contracts."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar, cast

import pydantic
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from document_enhancer.contracts import ModelGateway
from document_enhancer.errors import ConfigurationError, ProviderError
from document_enhancer.logging import redact

from .caching import CacheKey, ResponseCache, canonical_json, digest_bytes, digest_json
from .callbacks import UsageCallbackHandler, UsageMetadata
from .profiles import ROUTE_FLASH, ROUTE_PRO_PREVIEW, GeminiRoute, resolve_route
from .structured import (
    StructuredOutputError,
    artifact_json,
    gemini_schema,
    schema_for,
    validate_artifact,
)

ArtifactT = TypeVar("ArtifactT")
ResultT = TypeVar("ResultT")

_SAFE_ERROR_TOKEN = re.compile(r"[^A-Za-z0-9_.-]+")
_REPAIR_FEEDBACK_MARKER = "DOCUMENT_ENHANCER_VALIDATION_FEEDBACK"


class BackendName(StrEnum):
    DEVELOPER_API = "developer_api"
    VERTEX_AI = "vertex_ai"


class RetryClass(StrEnum):
    RETRYABLE = "retryable"
    LIFECYCLE = "lifecycle"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    SAFETY = "safety"
    UNKNOWN = "unknown"


class BudgetExceededError(ProviderError):
    """The provider response exceeded an explicit stage budget."""


class ModelLifecycleError(ProviderError):
    """The exact configured model is unavailable, retired, or deprecated."""


class GatewayConfigurationError(ConfigurationError):
    """The selected backend cannot be initialized from configured credentials."""


class GeminiGatewayConfig(BaseModel):
    """Non-prompt gateway settings. API keys are excluded from all dumps."""

    model_config = ConfigDict(extra="forbid")

    backend: BackendName = BackendName.DEVELOPER_API
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    project: str | None = None
    location: str | None = None
    cache_dir: Path | None = None
    max_retries_override: int | None = Field(default=None, ge=0, le=8)
    max_repairs_override: int | None = Field(default=None, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.1, ge=0, le=10)
    allow_pro_fallback: bool = False

    @classmethod
    def from_env(cls, **overrides: Any) -> GeminiGatewayConfig:
        backend = overrides.pop("backend", os.getenv("DOCENHANCE_BACKEND", "developer_api"))
        api_key = overrides.pop("api_key", None)
        if api_key is None and backend == BackendName.DEVELOPER_API:
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if isinstance(api_key, str) and not api_key.strip():
            api_key = None
        project = overrides.pop("project", None) or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = overrides.pop("location", None) or os.getenv("GOOGLE_CLOUD_LOCATION")
        return cls(
            backend=backend,
            api_key=api_key,
            project=project,
            location=location,
            **overrides,
        )

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"api_key"})
        data["api_key_configured"] = self.api_key is not None
        return data


class CallStatus(StrEnum):
    SUCCESS = "success"
    CACHE_HIT = "cache_hit"
    FAILED = "failed"
    FALLBACK = "fallback"


class CallManifest(BaseModel):
    """Safe model-call evidence: digests and usage, never prompt/source text."""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    stage: str
    provider: str = "google"
    backend: BackendName
    requested_route_id: str
    effective_route_id: str
    model: str
    parameters: dict[str, object]
    schema_name: str
    schema_digest: str
    prompt_id: str | None = None
    prompt_version: str | None = None
    prompt_digest: str
    attempt_prompt_digests: list[str] = Field(default_factory=list)
    input_digests: list[str] = Field(default_factory=list)
    result_schema_name: str | None = None
    result_schema_digest: str | None = None
    cache_key: str
    status: CallStatus
    attempts: int = Field(ge=0)
    retries: int = Field(ge=0)
    structured_repairs: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    usage: UsageMetadata | None = None
    response_digest: str | None = None
    token_budget: int
    output_budget: int
    cost_budget_usd: float | None
    error_class: RetryClass | None = None
    error_type: str | None = None
    error_message: str | None = None
    fallback_from: str | None = None
    fallback_reason: str | None = None


class StructuredCall[ArtifactT]:
    def __init__(self, artifact: ArtifactT, manifest: CallManifest) -> None:
        self.artifact = artifact
        self.manifest = manifest


def _error_text(exc: BaseException) -> str:
    text = redact(str(exc)).replace("\n", " ").strip()
    return text[:240] if text else type(exc).__name__


def _safe_error_token(value: object, *, fallback: str) -> str:
    token = _SAFE_ERROR_TOKEN.sub("_", str(value)).strip("_.-")[:80]
    return token or fallback


def _schema_field_names(schema: type[Any]) -> set[str]:
    names: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, Mapping):
            properties = node.get("properties")
            if isinstance(properties, Mapping):
                names.update(str(name) for name in properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema_for(schema))
    return names


def _safe_error_location(location: Sequence[object], *, allowed_fields: set[str]) -> str:
    parts: list[str] = []
    for part in location:
        if isinstance(part, int):
            parts.append(str(part))
            continue
        token = str(part)
        parts.append(token if token in allowed_fields else "field")
    return ".".join(parts) if parts else "$"


def _safe_validation_message(error_type: str) -> str:
    """Map validation codes to corrective text without copying provider-controlled values."""

    if error_type == "missing":
        return "Required field is missing."
    if error_type.startswith("literal") or error_type.startswith("enum"):
        return "Value must match one of the permitted values."
    if error_type.startswith("extra"):
        return "Field is not permitted by the result contract."
    if error_type.startswith(("string", "bytes")):
        return "Value does not satisfy the required text contract."
    if error_type.startswith(("int", "float", "decimal", "finite_number")):
        return "Value does not satisfy the required numeric contract."
    if error_type.startswith(("list", "tuple", "set", "dict")):
        return "Value does not satisfy the required collection contract."
    if error_type.startswith("bool"):
        return "Value does not satisfy the required boolean contract."
    if error_type.startswith(("date", "time", "datetime")):
        return "Value does not satisfy the required date or time contract."
    if error_type in {"structured_output_error", "json_invalid"}:
        return "Response must be one JSON object matching the provider schema."
    if error_type == "promotion_validation_error":
        return "Parsed output does not satisfy deterministic promotion rules."
    return "Value does not satisfy the required validation rule."


def _validation_feedback(exc: BaseException, *, allowed_fields: set[str]) -> list[dict[str, str]]:
    """Return only allow-listed validation metadata; never echo inputs or exception text."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, pydantic.ValidationError):
            feedback: list[dict[str, str]] = []
            for item in current.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )[:20]:
                error_type = _safe_error_token(
                    item.get("type", "validation_error"), fallback="validation_error"
                )
                raw_location = item.get("loc", ())
                location = (
                    _safe_error_location(raw_location, allowed_fields=allowed_fields)
                    if isinstance(raw_location, (list, tuple))
                    else "$"
                )
                feedback.append(
                    {
                        "location": location,
                        "error_type": error_type,
                        "message": _safe_validation_message(error_type),
                    }
                )
            if feedback:
                return feedback
        current = current.__cause__ or current.__context__

    error_type = (
        "structured_output_error"
        if isinstance(exc, StructuredOutputError)
        else "promotion_validation_error"
    )
    return [
        {
            "location": "$",
            "error_type": error_type,
            "message": _safe_validation_message(error_type),
        }
    ]


def _repair_prompt(base_prompt: str, exc: BaseException, *, allowed_fields: set[str]) -> str:
    feedback = canonical_json(_validation_feedback(exc, allowed_fields=allowed_fields))
    return (
        f"{base_prompt}\n\n{_REPAIR_FEEDBACK_MARKER}\n"
        "Correct only the validation failures below and return one complete JSON object.\n"
        f"{feedback}"
    )


class _PromotionValidationError(ValueError):
    """Internal marker for deterministic post-parse promotion failures."""


def is_model_lifecycle_error(exc: BaseException) -> bool:
    text = _error_text(exc).lower()
    return any(
        marker in text
        for marker in (
            "not found",
            "does not exist",
            "unknown model",
            "model unavailable",
            "deprecated",
            "retired",
            "unsupported model",
            "model is not available",
        )
    )


def classify_provider_error(exc: BaseException) -> RetryClass:
    if isinstance(exc, ModelLifecycleError) or is_model_lifecycle_error(exc):
        return RetryClass.LIFECYCLE
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return RetryClass.RETRYABLE
    text = _error_text(exc).lower()
    if any(
        marker in text
        for marker in ("429", "rate limit", "too many requests", "temporarily unavailable")
    ):
        return RetryClass.RETRYABLE
    if any(
        marker in text
        for marker in ("500", "502", "503", "504", "deadline exceeded", "unavailable")
    ):
        return RetryClass.RETRYABLE
    if any(
        marker in text for marker in ("401", "403", "unauthorized", "permission denied", "api key")
    ):
        return RetryClass.AUTHENTICATION
    if any(marker in text for marker in ("safety", "blocked", "recitation")):
        return RetryClass.SAFETY
    if any(marker in text for marker in ("400", "invalid argument", "bad request", "schema")):
        return RetryClass.INVALID_REQUEST
    return RetryClass.UNKNOWN


def _extract_parsed(response: object) -> object:
    if isinstance(response, Mapping) and "parsed" in response:
        parsed = response.get("parsed")
        if parsed is None:
            error = response.get("parsing_error")
            raise StructuredOutputError(
                f"provider returned no schema-validated object ({type(error).__name__ if error else 'unknown error'})"
            )
        return parsed
    if isinstance(response, BaseModel):
        return response
    if isinstance(response, Mapping):
        return response
    content = getattr(response, "content", None)
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError("provider returned non-JSON structured content") from exc
    raise StructuredOutputError("provider returned no structured object")


def _factory_model(
    factory: Callable[..., Any], route: GeminiRoute, config: GeminiGatewayConfig
) -> Any:
    try:
        return factory(route, config)
    except TypeError as first_error:
        try:
            return factory(route)
        except TypeError:
            raise first_error from None


class GeminiModelGateway:
    """Stage-routed Gemini gateway with native schema and fail-closed promotion."""

    def __init__(
        self,
        config: GeminiGatewayConfig | None = None,
        *,
        model_factory: Callable[..., Any] | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        self.config = config or GeminiGatewayConfig.from_env()
        self._model_factory = model_factory
        self._cache = cache or (
            ResponseCache(self.config.cache_dir) if self.config.cache_dir is not None else None
        )
        self.last_manifest: CallManifest | None = None

    def _build_chat_model(self, route: GeminiRoute) -> Any:
        if self._model_factory is not None:
            model = _factory_model(self._model_factory, route, self.config)
            if hasattr(model, "with_route"):
                model = model.with_route(route)
            return model
        ChatGoogleGenerativeAI = importlib.import_module(
            "langchain_google_genai"
        ).ChatGoogleGenerativeAI

        kwargs: dict[str, Any] = {
            "model": route.model,
            "temperature": route.temperature,
            "top_p": route.top_p,
            "top_k": route.top_k,
            "max_tokens": route.max_output_tokens,
            "retries": 0,
            "request_timeout": route.timeout_seconds,
            "disable_streaming": True,
            "include_thoughts": False,
            "seed": route.seed,
            "response_mime_type": "application/json",
            "model_kwargs": {},
        }
        if route.thinking_level is not None:
            kwargs["thinking_level"] = route.thinking_level
        if self.config.backend == BackendName.DEVELOPER_API:
            api_key = self.config.api_key.get_secret_value() if self.config.api_key else None
            if not api_key:
                raise GatewayConfigurationError("Gemini Developer API credentials are unavailable")
            kwargs["api_key"] = SecretStr(api_key)
        else:
            if not self.config.project or not self.config.location:
                raise GatewayConfigurationError("Vertex AI requires project and location")
            kwargs.update(
                {"vertexai": True, "project": self.config.project, "location": self.config.location}
            )
        return ChatGoogleGenerativeAI(**kwargs)

    def _cache_key(
        self,
        route: GeminiRoute,
        *,
        prompt: str,
        schema_digest: str,
        input_digests: Sequence[str],
        prompt_digest: str,
        token_budget: int,
        output_budget: int,
    ) -> CacheKey:
        parameters = route.parameters()
        parameters["call_token_budget"] = token_budget
        parameters["call_output_budget"] = output_budget
        return CacheKey(
            provider="google",
            backend=self.config.backend.value,
            model=route.model,
            parameters=parameters,
            prompt_digest=prompt_digest or digest_bytes(prompt.encode("utf-8")),
            schema_digest=schema_digest,
            input_digests=tuple(input_digests),
        )

    def _manifest_base(
        self,
        *,
        call_id: str,
        stage: str,
        requested: GeminiRoute,
        effective: GeminiRoute,
        schema: type[Any],
        schema_digest: str,
        prompt_digest: str,
        attempt_prompt_digests: Sequence[str] = (),
        prompt_id: str | None,
        prompt_version: str | None,
        input_digests: Sequence[str],
        result_schema_name: str | None = None,
        result_schema_digest: str | None = None,
        cache_key: CacheKey,
        status: CallStatus,
        attempts: int,
        retries: int,
        repairs: int,
        started: float,
        token_budget: int,
        output_budget: int,
        usage: UsageMetadata | None = None,
        response_digest: str | None = None,
        error: BaseException | None = None,
        fallback_from: str | None = None,
        fallback_reason: str | None = None,
    ) -> CallManifest:
        error_class = classify_provider_error(error) if error else None
        return CallManifest(
            call_id=call_id,
            stage=stage,
            backend=self.config.backend,
            requested_route_id=requested.route_id,
            effective_route_id=effective.route_id,
            model=effective.model,
            parameters=effective.parameters(),
            schema_name=getattr(schema, "__name__", str(schema)),
            schema_digest=schema_digest,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_digest=prompt_digest,
            attempt_prompt_digests=list(attempt_prompt_digests),
            input_digests=list(input_digests),
            result_schema_name=result_schema_name,
            result_schema_digest=result_schema_digest,
            cache_key=cache_key.digest,
            status=status,
            attempts=attempts,
            retries=retries,
            structured_repairs=repairs,
            duration_ms=(time.perf_counter() - started) * 1000,
            usage=usage,
            response_digest=response_digest,
            token_budget=token_budget,
            output_budget=output_budget,
            cost_budget_usd=effective.cost_budget_usd,
            error_class=error_class,
            error_type=type(error).__name__ if error else None,
            error_message=_error_text(error) if error else None,
            fallback_from=fallback_from,
            fallback_reason=fallback_reason,
        )

    def invoke(
        self,
        *,
        route: str,
        schema: type[ArtifactT],
        prompt: str,
        stage: str | None = None,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        prompt_digest: str | None = None,
        input_digests: Sequence[str] = (),
        use_cache: bool = True,
        input_token_budget: int | None = None,
        output_token_budget: int | None = None,
        promote: Callable[[ArtifactT], ResultT] | None = None,
        result_schema: type[ResultT] | None = None,
    ) -> StructuredCall[ArtifactT] | StructuredCall[ResultT]:
        resolved = resolve_route(route)
        if (input_token_budget is None) != (output_token_budget is None):
            raise ValueError("input and output token budgets must be supplied together")
        if input_token_budget is None or output_token_budget is None:
            call_token_budget = resolved.token_budget
            call_output_budget = resolved.output_budget
        else:
            if input_token_budget < 1 or output_token_budget < 1:
                raise ValueError("input and output token budgets must be positive")
            call_token_budget = input_token_budget + output_token_budget
            call_output_budget = output_token_budget
            if call_token_budget > resolved.token_budget:
                raise ValueError(
                    "prompt input-plus-output budget exceeds the exact route token cap"
                )
            if call_output_budget > resolved.output_budget:
                raise ValueError("prompt output budget exceeds the exact route output cap")
        actual_stage = stage or (resolved.stage if route == resolved.route_id else route)
        native_schema = gemini_schema(schema)
        schema_digest = digest_json(native_schema)
        resolved_result_schema: type[Any] = result_schema or schema
        result_schema_digest = digest_json(schema_for(resolved_result_schema))
        cache_contract_digest = digest_json(
            {
                "provider_schema_digest": schema_digest,
                "result_schema_digest": result_schema_digest,
            }
        )
        resolved_prompt_digest = prompt_digest or digest_bytes(prompt.encode("utf-8"))
        key = self._cache_key(
            resolved,
            prompt=prompt,
            schema_digest=cache_contract_digest,
            input_digests=input_digests,
            prompt_digest=resolved_prompt_digest,
            token_budget=call_token_budget,
            output_budget=call_output_budget,
        )
        call_id = uuid.uuid4().hex
        started = time.perf_counter()
        if use_cache and self._cache is not None:
            record = self._cache.get(key)
            if record is not None:
                artifact = validate_artifact(resolved_result_schema, record.response)
                cached_effective = resolved
                cached_effective_id = record.manifest.get("effective_route_id")
                if isinstance(cached_effective_id, str):
                    try:
                        cached_effective = resolve_route(cached_effective_id)
                    except ValueError:
                        cached_effective = resolved
                cached_fallback_from = record.manifest.get("fallback_from")
                cached_fallback_reason = record.manifest.get("fallback_reason")
                if not isinstance(cached_fallback_from, str):
                    cached_fallback_from = None
                if not isinstance(cached_fallback_reason, str):
                    cached_fallback_reason = None
                manifest = self._manifest_base(
                    call_id=call_id,
                    stage=actual_stage,
                    requested=resolved,
                    effective=cached_effective,
                    schema=schema,
                    schema_digest=schema_digest,
                    prompt_digest=resolved_prompt_digest,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    input_digests=input_digests,
                    result_schema_name=getattr(
                        resolved_result_schema, "__name__", str(resolved_result_schema)
                    ),
                    result_schema_digest=result_schema_digest,
                    cache_key=key,
                    status=CallStatus.CACHE_HIT,
                    attempts=0,
                    retries=0,
                    repairs=0,
                    started=started,
                    response_digest=record.response_digest,
                    fallback_from=cached_fallback_from,
                    fallback_reason=cached_fallback_reason,
                    token_budget=call_token_budget,
                    output_budget=call_output_budget,
                )
                self.last_manifest = manifest
                return StructuredCall(artifact, manifest)
        try:
            result = self._invoke_route(
                requested=resolved,
                effective=resolved,
                schema=schema,
                result_schema=resolved_result_schema,
                promote=promote,
                native_schema=native_schema,
                prompt=prompt,
                stage=actual_stage,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                prompt_digest=resolved_prompt_digest,
                input_digests=input_digests,
                key=key,
                call_id=call_id,
                started=started,
                token_budget=call_token_budget,
                output_budget=call_output_budget,
            )
        except ProviderError as exc:
            if resolved.route_id != ROUTE_PRO_PREVIEW or not self.config.allow_pro_fallback:
                raise
            if classify_provider_error(exc) != RetryClass.LIFECYCLE:
                raise
            fallback = resolve_route(ROUTE_FLASH)
            result = self._invoke_route(
                requested=resolved,
                effective=fallback,
                schema=schema,
                result_schema=resolved_result_schema,
                promote=promote,
                native_schema=native_schema,
                prompt=prompt,
                stage=actual_stage,
                prompt_id=prompt_id,
                prompt_version=prompt_version,
                prompt_digest=resolved_prompt_digest,
                input_digests=input_digests,
                key=key,
                call_id=call_id,
                started=started,
                fallback_from=resolved.route_id,
                fallback_reason=_error_text(exc),
                token_budget=call_token_budget,
                output_budget=call_output_budget,
            )
            result.manifest.status = CallStatus.FALLBACK
            if self._cache is not None:
                self._cache.put(
                    key,
                    artifact_json(resolved_result_schema, result.artifact),
                    manifest={
                        "call_id": call_id,
                        "status": result.manifest.status.value,
                        "requested_route_id": resolved.route_id,
                        "effective_route_id": result.manifest.effective_route_id,
                        "fallback_from": result.manifest.fallback_from,
                        "fallback_reason": result.manifest.fallback_reason,
                    },
                )
        self.last_manifest = result.manifest
        return result

    def structured(
        self,
        *,
        route: str,
        schema: type[ArtifactT],
        prompt: str,
        prompt_id: str | None = None,
        prompt_version: str | None = None,
        prompt_digest: str | None = None,
        input_digests: Sequence[str] = (),
    ) -> ArtifactT:
        return self.invoke(
            route=route,
            schema=schema,
            prompt=prompt,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            prompt_digest=prompt_digest,
            input_digests=input_digests,
        ).artifact

    def _invoke_route(
        self,
        *,
        requested: GeminiRoute,
        effective: GeminiRoute,
        schema: type[ArtifactT],
        result_schema: type[ResultT],
        promote: Callable[[ArtifactT], ResultT] | None,
        native_schema: dict[str, Any],
        prompt: str,
        stage: str,
        prompt_id: str | None,
        prompt_version: str | None,
        prompt_digest: str,
        input_digests: Sequence[str],
        key: CacheKey,
        call_id: str,
        started: float,
        token_budget: int,
        output_budget: int,
        fallback_from: str | None = None,
        fallback_reason: str | None = None,
    ) -> StructuredCall[ArtifactT] | StructuredCall[ResultT]:
        repairs = 0
        provider_retries = 0
        attempts = 0
        usage: UsageMetadata | None = None
        attempt_prompt = prompt
        attempt_prompt_digests: list[str] = []
        result_schema_name = getattr(result_schema, "__name__", str(result_schema))
        result_schema_digest = digest_json(schema_for(result_schema))
        allowed_feedback_fields = _schema_field_names(schema) | _schema_field_names(result_schema)
        while True:
            attempts += 1
            attempt_prompt_digests.append(digest_bytes(attempt_prompt.encode("utf-8")))
            try:
                model = self._build_chat_model(effective)
                native_model = model.with_structured_output(
                    native_schema,
                    method="json_schema",
                    include_raw=True,
                )
                callback = UsageCallbackHandler()
                response = native_model.invoke(
                    attempt_prompt,
                    config={
                        "callbacks": [callback],
                        "metadata": {
                            "document_enhancer_route": effective.route_id,
                            "document_enhancer_stage": stage,
                            "tools": [],
                        },
                    },
                )
                usage = callback.usage or UsageMetadata.from_response(response)
                provider_artifact = validate_artifact(schema, _extract_parsed(response))
                provider_artifact_payload = artifact_json(schema, provider_artifact)
                if promote is None:
                    promoted: object = provider_artifact
                else:
                    try:
                        promoted = promote(provider_artifact)
                    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                        raise
                    except Exception as exc:
                        raise _PromotionValidationError(
                            "deterministic post-parse promotion failed"
                        ) from exc
                artifact = validate_artifact(result_schema, promoted)
                artifact_payload = artifact_json(result_schema, artifact)
                self._enforce_budget(
                    effective,
                    usage,
                    provider_artifact_payload,
                    token_budget=token_budget,
                    output_budget=output_budget,
                )
            except (StructuredOutputError, ValueError) as exc:
                if repairs >= min(
                    effective.structured_repairs,
                    self.config.max_repairs_override
                    if self.config.max_repairs_override is not None
                    else effective.structured_repairs,
                ):
                    manifest = self._manifest_base(
                        call_id=call_id,
                        stage=stage,
                        requested=requested,
                        effective=effective,
                        schema=schema,
                        schema_digest=digest_json(native_schema),
                        prompt_digest=prompt_digest,
                        attempt_prompt_digests=attempt_prompt_digests,
                        prompt_id=prompt_id,
                        prompt_version=prompt_version,
                        input_digests=input_digests,
                        result_schema_name=result_schema_name,
                        result_schema_digest=result_schema_digest,
                        cache_key=key,
                        status=CallStatus.FAILED,
                        attempts=attempts,
                        retries=provider_retries,
                        repairs=repairs,
                        started=started,
                        usage=usage,
                        error=exc,
                        fallback_from=fallback_from,
                        fallback_reason=fallback_reason,
                        token_budget=token_budget,
                        output_budget=output_budget,
                    )
                    self.last_manifest = manifest
                    raise ProviderError(
                        "native structured output failed after bounded repairs"
                    ) from exc
                repairs += 1
                corrective_prompt = _repair_prompt(
                    prompt,
                    exc,
                    allowed_fields=allowed_feedback_fields,
                )
                if digest_bytes(corrective_prompt.encode("utf-8")) in attempt_prompt_digests:
                    manifest = self._manifest_base(
                        call_id=call_id,
                        stage=stage,
                        requested=requested,
                        effective=effective,
                        schema=schema,
                        schema_digest=digest_json(native_schema),
                        prompt_digest=prompt_digest,
                        attempt_prompt_digests=attempt_prompt_digests,
                        prompt_id=prompt_id,
                        prompt_version=prompt_version,
                        input_digests=input_digests,
                        result_schema_name=result_schema_name,
                        result_schema_digest=result_schema_digest,
                        cache_key=key,
                        status=CallStatus.FAILED,
                        attempts=attempts,
                        retries=provider_retries,
                        repairs=repairs,
                        started=started,
                        usage=usage,
                        error=exc,
                        fallback_from=fallback_from,
                        fallback_reason=fallback_reason,
                        token_budget=token_budget,
                        output_budget=output_budget,
                    )
                    self.last_manifest = manifest
                    raise ProviderError(
                        "native structured output failed because the bounded repair prompt "
                        "would repeat unchanged"
                    ) from exc
                attempt_prompt = corrective_prompt
                continue
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit, asyncio.CancelledError)):
                    raise
                classification = classify_provider_error(exc)
                if classification == RetryClass.LIFECYCLE:
                    lifecycle = ModelLifecycleError(
                        "configured Gemini model is unavailable or retired"
                    )
                    manifest = self._manifest_base(
                        call_id=call_id,
                        stage=stage,
                        requested=requested,
                        effective=effective,
                        schema=schema,
                        schema_digest=digest_json(native_schema),
                        prompt_digest=prompt_digest,
                        attempt_prompt_digests=attempt_prompt_digests,
                        prompt_id=prompt_id,
                        prompt_version=prompt_version,
                        input_digests=input_digests,
                        result_schema_name=result_schema_name,
                        result_schema_digest=result_schema_digest,
                        cache_key=key,
                        status=CallStatus.FAILED,
                        attempts=attempts,
                        retries=provider_retries,
                        repairs=repairs,
                        started=started,
                        usage=usage,
                        error=lifecycle,
                        fallback_from=fallback_from,
                        fallback_reason=fallback_reason,
                        token_budget=token_budget,
                        output_budget=output_budget,
                    )
                    self.last_manifest = manifest
                    raise lifecycle from exc
                max_retries = self.config.max_retries_override
                allowed_retries = effective.provider_retries
                if max_retries is not None:
                    allowed_retries = min(max_retries, allowed_retries)
                if classification != RetryClass.RETRYABLE or provider_retries >= allowed_retries:
                    manifest = self._manifest_base(
                        call_id=call_id,
                        stage=stage,
                        requested=requested,
                        effective=effective,
                        schema=schema,
                        schema_digest=digest_json(native_schema),
                        prompt_digest=prompt_digest,
                        attempt_prompt_digests=attempt_prompt_digests,
                        prompt_id=prompt_id,
                        prompt_version=prompt_version,
                        input_digests=input_digests,
                        result_schema_name=result_schema_name,
                        result_schema_digest=result_schema_digest,
                        cache_key=key,
                        status=CallStatus.FAILED,
                        attempts=attempts,
                        retries=provider_retries,
                        repairs=repairs,
                        started=started,
                        usage=usage,
                        error=exc,
                        fallback_from=fallback_from,
                        fallback_reason=fallback_reason,
                        token_budget=token_budget,
                        output_budget=output_budget,
                    )
                    self.last_manifest = manifest
                    raise ProviderError(
                        "Gemini provider call failed under the configured retry policy"
                    ) from exc
                provider_retries += 1
                time.sleep(self.config.retry_backoff_seconds * (2 ** (provider_retries - 1)))
                continue
            else:
                response_digest = digest_json(artifact_payload)
                manifest = self._manifest_base(
                    call_id=call_id,
                    stage=stage,
                    requested=requested,
                    effective=effective,
                    schema=schema,
                    schema_digest=digest_json(native_schema),
                    prompt_digest=prompt_digest,
                    attempt_prompt_digests=attempt_prompt_digests,
                    prompt_id=prompt_id,
                    prompt_version=prompt_version,
                    input_digests=input_digests,
                    result_schema_name=result_schema_name,
                    result_schema_digest=result_schema_digest,
                    cache_key=key,
                    status=CallStatus.SUCCESS,
                    attempts=attempts,
                    retries=provider_retries,
                    repairs=repairs,
                    started=started,
                    usage=usage,
                    response_digest=response_digest,
                    fallback_from=fallback_from,
                    fallback_reason=fallback_reason,
                    token_budget=token_budget,
                    output_budget=output_budget,
                )
                if self._cache is not None:
                    self._cache.put(
                        key,
                        artifact_payload,
                        manifest={"call_id": call_id, "status": manifest.status.value},
                    )
                return StructuredCall(artifact, manifest)

    @staticmethod
    def _enforce_budget(
        route: GeminiRoute,
        usage: UsageMetadata | None,
        artifact: Mapping[str, Any],
        *,
        token_budget: int | None = None,
        output_budget: int | None = None,
    ) -> None:
        bounded_tokens = route.token_budget if token_budget is None else token_budget
        bounded_output = route.output_budget if output_budget is None else output_budget
        bounded_input = bounded_tokens - bounded_output
        if usage is not None:
            observed_total = usage.total_tokens
            if (
                observed_total is None
                and usage.input_tokens is not None
                and usage.output_tokens is not None
            ):
                observed_total = usage.input_tokens + usage.output_tokens
            if usage.input_tokens is not None and usage.input_tokens > bounded_input:
                raise BudgetExceededError("model request exceeded the stage input token budget")
            if observed_total is not None and observed_total > bounded_tokens:
                raise BudgetExceededError("model response exceeded the stage token budget")
            if usage.output_tokens is not None and usage.output_tokens > bounded_output:
                raise BudgetExceededError("model response exceeded the stage output budget")
            if (
                usage.cost_usd is not None
                and route.cost_budget_usd is not None
                and usage.cost_usd > route.cost_budget_usd
            ):
                raise BudgetExceededError("model response exceeded the stage cost budget")
        estimated_output_tokens = max(1, len(canonical_json(artifact)) // 4)
        if estimated_output_tokens > bounded_output:
            raise BudgetExceededError(
                "serialized structured artifact exceeded the stage output budget"
            )

    async def ainvoke(self, **kwargs: Any) -> StructuredCall[Any]:
        """Async boundary with cancellation propagation and an explicit timeout."""

        route = resolve_route(str(kwargs["route"]))
        try:
            async with asyncio.timeout(route.timeout_seconds):
                return await asyncio.to_thread(self.invoke, **kwargs)
        except asyncio.CancelledError:
            raise


class FakeStructuredModel:
    """Deterministic native-structured fake used by offline workflow tests."""

    def __init__(self, responses: Sequence[object] | Mapping[str, Sequence[object]]) -> None:
        self._responses: list[object] | dict[str, list[object]]
        if isinstance(responses, Mapping):
            self._responses = {
                str(key): list(cast(Sequence[object], value)) for key, value in responses.items()
            }
        else:
            self._responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self._route_id = "fake"

    def with_route(self, route: GeminiRoute) -> FakeStructuredModel:
        self._route_id = route.route_id
        return self

    def with_structured_output(self, schema: Mapping[str, Any], **_: Any) -> Any:
        parent = self

        class Runnable:
            def invoke(self, prompt: str, **__: Any) -> dict[str, object]:
                digest = digest_bytes(prompt.encode())
                parent.calls.append({"route": parent._route_id, "prompt_digest": digest})
                if isinstance(parent._responses, dict):
                    values = parent._responses.get(parent._route_id, [])
                else:
                    values = parent._responses
                if not values:
                    raise RuntimeError("fake structured model has no recorded response")
                response = values.pop(0)
                return {"parsed": response, "raw": {"fake": True}}

        return Runnable()


class RecordedStructuredModel(FakeStructuredModel):
    """Replay/record fake; files contain prompt digests and structured responses only."""

    def __init__(self, path: Path | str, responses: Sequence[object] | None = None) -> None:
        self.path = Path(path)
        self._recorded: dict[str, object] = {}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._recorded = loaded
        super().__init__(list(responses or []))

    def with_structured_output(self, schema: Mapping[str, Any], **kwargs: Any) -> Any:
        parent = self
        base = super().with_structured_output(schema, **kwargs)

        class Runnable:
            def invoke(self, prompt: str, **call_kwargs: Any) -> dict[str, object]:
                digest = digest_bytes(prompt.encode())
                if digest in parent._recorded:
                    parent.calls.append({"route": parent._route_id, "prompt_digest": digest})
                    return {"parsed": parent._recorded[digest], "raw": {"recorded": True}}
                try:
                    response = base.invoke(prompt, **call_kwargs)
                except RuntimeError:
                    raise
                parent._recorded[digest] = response["parsed"]
                parent.path.parent.mkdir(parents=True, exist_ok=True)
                parent.path.write_text(canonical_json(parent._recorded) + "\n", encoding="utf-8")
                return response

        return Runnable()


__all__ = [
    "BackendName",
    "BudgetExceededError",
    "CallManifest",
    "CallStatus",
    "FakeStructuredModel",
    "GeminiGatewayConfig",
    "GeminiModelGateway",
    "GatewayConfigurationError",
    "ModelGateway",
    "ModelLifecycleError",
    "RecordedStructuredModel",
    "RetryClass",
    "StructuredCall",
    "classify_provider_error",
    "is_model_lifecycle_error",
]
