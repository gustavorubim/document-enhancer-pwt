"""Bounded Gemini structured-output gateway."""

from .caching import CacheKey, ResponseCache
from .callbacks import UsageMetadata
from .models import (
    BackendName,
    BudgetExceededError,
    CallManifest,
    CallStatus,
    FakeStructuredModel,
    GatewayConfigurationError,
    GeminiGatewayConfig,
    GeminiModelGateway,
    ModelLifecycleError,
    RecordedStructuredModel,
    RetryClass,
    StructuredCall,
    classify_provider_error,
    is_model_lifecycle_error,
)
from .profiles import (
    ROUTE_FLASH,
    ROUTE_FLASH_LITE,
    ROUTE_PRO_PREVIEW,
    GeminiRoute,
    resolve_route,
)
from .structured import GeminiSchemaError, StructuredOutputError, gemini_schema, validate_artifact

__all__ = [
    "BackendName",
    "BudgetExceededError",
    "CacheKey",
    "CallManifest",
    "CallStatus",
    "FakeStructuredModel",
    "GeminiGatewayConfig",
    "GeminiModelGateway",
    "GeminiRoute",
    "GeminiSchemaError",
    "GatewayConfigurationError",
    "ModelLifecycleError",
    "ROUTE_FLASH",
    "ROUTE_FLASH_LITE",
    "ROUTE_PRO_PREVIEW",
    "RecordedStructuredModel",
    "ResponseCache",
    "RetryClass",
    "StructuredCall",
    "StructuredOutputError",
    "UsageMetadata",
    "classify_provider_error",
    "gemini_schema",
    "is_model_lifecycle_error",
    "resolve_route",
    "validate_artifact",
]
