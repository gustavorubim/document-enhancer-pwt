"""Foundation capability checks used by ``docenhance doctor``."""

from __future__ import annotations

import importlib
import os
import sqlite3
from dataclasses import dataclass

from .compatibility import run_offline_spikes
from .config import AppConfig


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _credential_status(config: AppConfig) -> Check:
    if config.gemini.backend == "vertex_ai":
        present = bool(config.gemini.project and config.gemini.location)
        return Check(
            "vertex_configuration",
            "pass" if present else "warn",
            "project/location configured" if present else "project/location not configured",
        )
    present = bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    return Check(
        "developer_api_credentials",
        "pass" if present else "warn",
        "configured without revealing credential values"
        if present
        else "not configured; live calls disabled",
    )


def run_doctor(config: AppConfig) -> list[Check]:
    checks = [
        Check("python", "pass", "running on a supported Python interpreter"),
        Check(
            "configuration",
            "pass",
            f"backend={config.gemini.backend}; data_handling={config.policy.data_handling}",
        ),
        Check(
            "gemini_model_routes",
            "info",
            ""
            f"structure={config.gemini.structure_model}; analysis={config.gemini.developer_model}; "
            f"rewrite={config.gemini.rewrite_model}; embedding={config.gemini.embedding_model}; "
            "live availability requires explicit opt-in",
        ),
        _credential_status(config),
    ]
    connection = sqlite3.connect(":memory:")
    try:
        try:
            connection.execute("CREATE VIRTUAL TABLE doctor_fts USING fts5(text)")
        except sqlite3.DatabaseError as exc:
            checks.append(Check("sqlite_fts5", "fail", str(exc)))
        else:
            checks.append(Check("sqlite_fts5", "pass", "FTS5 virtual tables available"))
    finally:
        connection.close()

    for module in ("sqlite_vec", "langchain_google_genai", "langgraph", "deepagents"):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            checks.append(Check(module, "fail", f"import failed: {exc}"))
        else:
            checks.append(Check(module, "pass", "import available"))

    for name, result in run_offline_spikes().items():
        checks.append(Check(f"spike:{name}", result["status"], result["detail"]))

    checks.append(
        Check(
            "future_milestones",
            "info",
            "doctor validates WT0 capabilities only; no later workflow is claimed",
        )
    )
    return checks


def doctor_json(checks: list[Check]) -> list[dict[str, str]]:
    return [
        {"name": check.name, "status": check.status, "detail": check.detail} for check in checks
    ]
