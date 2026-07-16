"""Configuration loading with explicit, testable precedence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from .errors import ConfigurationError


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_dir: Path = Path(".document-enhancer/runs")
    catalog_path: Path = Path(".document-enhancer/rag/catalog.sqlite3")


class ReferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_pack: Path = Path("reference_packs/enterprise_core")
    prompt_pack: Path = Path("prompt_packs/gemini_core")


class GeminiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str = Field(default="developer_api", pattern="^(developer_api|vertex_ai)$")
    developer_model: str = "gemini-3.5-flash"
    structure_model: str = "gemini-3.1-flash-lite"
    rewrite_model: str = "gemini-3.1-pro-preview"
    embedding_model: str = "gemini-embedding-2"
    embedding_dimensions: int = Field(default=768, ge=1)
    allow_pro_fallback: bool = False
    project: str | None = None
    location: str | None = None


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_handling: str = Field(default="local_first", pattern="^local_first$")
    external_tracing: bool = False
    live_provider_checks: bool = False


class AppConfig(BaseModel):
    """Non-secret application configuration.

    Credential values are deliberately absent. Provider SDKs read credentials through their
    native environment/ADC mechanisms, while this model only records whether checks are enabled.
    """

    model_config = ConfigDict(extra="forbid")

    workspace: WorkspaceConfig = WorkspaceConfig()
    references: ReferenceConfig = ReferenceConfig()
    gemini: GeminiConfig = GeminiConfig()
    policy: PolicyConfig = PolicyConfig()


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import tomllib

        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"Unable to read configuration file: {path}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError(f"Configuration file must contain a table: {path}")
    return data


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _env_overrides(environ: dict[str, str]) -> dict[str, Any]:
    """Parse the stable env surface; secret env vars are never copied."""

    mapping: dict[str, tuple[str, str]] = {
        "DOCENHANCE_BACKEND": ("gemini", "backend"),
        "DOCENHANCE_DEVELOPER_MODEL": ("gemini", "developer_model"),
        "DOCENHANCE_STRUCTURE_MODEL": ("gemini", "structure_model"),
        "DOCENHANCE_REWRITE_MODEL": ("gemini", "rewrite_model"),
        "DOCENHANCE_EMBEDDING_MODEL": ("gemini", "embedding_model"),
        "DOCENHANCE_EMBEDDING_DIMENSIONS": ("gemini", "embedding_dimensions"),
        "DOCENHANCE_VERTEX_PROJECT": ("gemini", "project"),
        "DOCENHANCE_VERTEX_LOCATION": ("gemini", "location"),
        "DOCENHANCE_RUN_DIR": ("workspace", "run_dir"),
        "DOCENHANCE_CATALOG_PATH": ("workspace", "catalog_path"),
        "DOCENHANCE_LIVE_PROVIDER_CHECKS": ("policy", "live_provider_checks"),
        "DOCENHANCE_EXTERNAL_TRACING": ("policy", "external_tracing"),
    }
    result: dict[str, Any] = {}
    for variable, (section, field) in mapping.items():
        if variable not in environ:
            continue
        value: Any = environ[variable]
        if field == "embedding_dimensions":
            try:
                value = int(value)
            except ValueError as exc:
                raise ConfigurationError(f"{variable} must be an integer") from exc
        elif field in {"live_provider_checks", "external_tracing"}:
            if value.lower() not in {"0", "1", "false", "true", "no", "yes"}:
                raise ConfigurationError(f"{variable} must be boolean")
            value = value.lower() in {"1", "true", "yes"}
        result.setdefault(section, {})[field] = value
    return result


def load_config(
    *,
    project_path: Path | None = None,
    user_path: Path | None = None,
    environ: dict[str, str] | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AppConfig:
    """Load defaults, user config, project config, env, and CLI overrides in that order."""

    project_path = project_path or Path("document-enhancer.toml")
    user_path = user_path or Path.home() / ".config" / "document-enhancer" / "config.toml"
    data: dict[str, Any] = {}
    data = _deep_merge(data, _read_toml(user_path))
    data = _deep_merge(data, _read_toml(project_path))
    data = _deep_merge(data, _env_overrides(environ or dict(os.environ)))
    data = _deep_merge(data, cli_overrides or {})
    try:
        return AppConfig.model_validate(data)
    except ValueError as exc:
        raise ConfigurationError("Configuration validation failed") from exc


def config_as_public_dict(config: AppConfig) -> dict[str, Any]:
    """Return a JSON-safe view that contains no provider credentials."""

    return config.model_dump(mode="json")


def yaml_parser() -> YAML:
    """Return a safe YAML parser for later artifact contracts."""

    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    return yaml
