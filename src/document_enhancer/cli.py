"""Small CLI for the file-backed document enhancement workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import load_config
from .core import (
    CoreRunner,
    GeminiAuditProvider,
    GeminiReviewProvider,
    GeminiRewriteProvider,
    GeminiStructureProvider,
    RunRecord,
    RunStore,
)
from .core.recipes import load_recipe
from .errors import DocumentEnhancerError
from .llm.models import GeminiGatewayConfig, GeminiModelGateway
from .references.loader import bundled_reference_pack_path

app = typer.Typer(
    name="docenhance",
    help="Turn one governed document into an audited, graph-ready bundle.",
    no_args_is_help=True,
    add_completion=False,
)

_SOURCE_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".docx", ".pdf"})
_DOTENV_KEYS = frozenset(
    {
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "DOCENHANCE_BACKEND",
    }
)


def _emit_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _fail(error: Exception) -> None:
    typer.echo(f"error: {error}", err=True)


def _load_project_env() -> None:
    """Load only recognized provider settings from a repository-local `.env`."""

    path = Path(".env")
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _DOTENV_KEYS or key in os.environ:
            continue
        value = value.strip().strip("\"'")
        if value:
            os.environ[key] = value


def _reference_pack(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser()
    configured = load_config().references.reference_pack.expanduser()
    if configured.is_dir():
        return configured
    if configured == Path("reference_packs/enterprise_core"):
        return bundled_reference_pack_path("enterprise_core")
    return configured


def _select_source(source: Path) -> Path:
    """Accept a source file or a single-document inbox directory."""

    candidate = source.expanduser()
    if candidate.is_file():
        return candidate
    if not candidate.is_dir():
        raise DocumentEnhancerError(f"source is not a file or inbox directory: {source}")
    documents = sorted(
        item
        for item in candidate.iterdir()
        if item.is_file() and item.suffix.lower() in _SOURCE_SUFFIXES
    )
    if len(documents) != 1:
        detail = "empty" if not documents else f"contains {len(documents)} supported documents"
        raise DocumentEnhancerError(
            f"inbox directory must contain exactly one supported document ({detail})"
        )
    return documents[0]


def _runner(
    *,
    root: Path,
    reference_pack: Path,
    document_type: str,
    structure_mode: str,
    execution_mode: str,
) -> CoreRunner:
    if execution_mode == "offline":
        return CoreRunner(
            root,
            recipe_pack=reference_pack,
            document_type=document_type,
            structure_mode=structure_mode,
            execution_mode=execution_mode,
        )
    _load_project_env()
    config = load_config()
    gateway = GeminiModelGateway(
        GeminiGatewayConfig.from_env(
            backend=config.gemini.backend,
            project=config.gemini.project,
            location=config.gemini.location,
            allow_pro_fallback=config.gemini.allow_pro_fallback,
            max_repairs_override=1,
        )
    )
    return CoreRunner(
        root,
        recipe_pack=reference_pack,
        document_type=document_type,
        structure_mode=structure_mode,
        execution_mode=execution_mode,
        structure_provider=GeminiStructureProvider(gateway),
        review_provider=GeminiReviewProvider(gateway),
        rewrite_provider=GeminiRewriteProvider(gateway),
        audit_provider=GeminiAuditProvider(gateway),
    )


def _print_record(record: RunRecord, *, root: Path, json_output: bool) -> None:
    value = record.model_dump(mode="json")
    if json_output:
        _emit_json(value)
        return
    typer.echo(f"run {value['run_id']}")
    typer.echo(f"status: {value['status']}")
    typer.echo(f"phase: {value['phase']}")
    typer.echo(f"artifacts: {root / str(value['run_id'])}")
    if value["status"] == "waiting":
        typer.echo(f"next: edit {root / str(value['run_id']) / 'review/decisions.yaml'}")


@app.command()
def version() -> None:
    """Print the installed package version."""

    typer.echo(__version__)


@app.command("run")
def run_document(
    source: Annotated[Path, typer.Argument(help="Source file or single-document inbox directory.")],
    document_type: Annotated[str, typer.Option("--document-type")] = "process",
    structure_mode: Annotated[str, typer.Option("--structure-mode")] = "auto",
    execution_mode: Annotated[str, typer.Option("--execution-mode")] = "offline",
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    until: Annotated[str, typer.Option("--until")] = "complete",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Start one extract, review, rewrite, and audit bundle."""

    try:
        if document_type not in {"process", "methodology", "standard", "desktop_procedure"}:
            raise DocumentEnhancerError(f"unsupported document type: {document_type}")
        if structure_mode not in {"auto", "parser", "off"}:
            raise DocumentEnhancerError("--structure-mode must be auto, parser, or off")
        if execution_mode not in {"offline", "live"}:
            raise DocumentEnhancerError("--execution-mode must be offline or live")
        if until not in {"questions", "complete"}:
            raise DocumentEnhancerError("--until must be questions or complete")
        config = load_config()
        root = (run_dir or config.workspace.run_dir).expanduser()
        result = _runner(
            root=root,
            reference_pack=_reference_pack(reference_pack),
            document_type=document_type,
            structure_mode=structure_mode,
            execution_mode=execution_mode,
        ).start(_select_source(source), stop_at=until)
    except (DocumentEnhancerError, FileNotFoundError, RuntimeError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error
    _print_record(result, root=root, json_output=json_output)
    if result.status == "waiting":
        raise typer.Exit(10)
    if result.status != "succeeded":
        raise typer.Exit(20)


@app.command("continue")
def continue_document(
    run_id: Annotated[str, typer.Argument(help="Run ID waiting for reviewer decisions.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Continue a run after editing `review/decisions.yaml`."""

    try:
        config = load_config()
        root = (run_dir or config.workspace.run_dir).expanduser()
        record = RunStore(root).load_run(run_id)
        document_type = record.recipe.rsplit("/", 1)[-1]
        result = _runner(
            root=root,
            reference_pack=_reference_pack(reference_pack),
            document_type=document_type,
            structure_mode="auto",
            execution_mode=record.execution_mode,
        ).resume(run_id)
    except (DocumentEnhancerError, FileNotFoundError, RuntimeError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error
    _print_record(result, root=root, json_output=json_output)
    if result.status == "waiting":
        raise typer.Exit(10)
    if result.status != "succeeded":
        raise typer.Exit(20)


@app.command("status")
def status(
    run_id: Annotated[str, typer.Argument(help="Run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the durable state and next action for one bundle."""

    try:
        root = (run_dir or load_config().workspace.run_dir).expanduser()
        record = RunStore(root).load_run(run_id)
        payload = {
            "schema_version": "core.cli.v1",
            "command": "status",
            "run_id": record.run_id,
            "status": record.status,
            "phase": record.phase,
            "next_action": "edit review/decisions.yaml and continue"
            if record.status == "waiting"
            else "none",
            "artifacts": {
                key: value.model_dump(mode="json") for key, value in record.artifacts.items()
            },
            "errors": [record.error] if record.error else [],
        }
        if json_output:
            _emit_json(payload)
        else:
            typer.echo(f"run {record.run_id}: {record.status} ({record.phase})")
            typer.echo(f"next: {payload['next_action']}")
    except (FileNotFoundError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error


@app.command("inspect")
def inspect(
    run_id: Annotated[str, typer.Argument(help="Run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect the compact run record and final audit, when available."""

    try:
        root = (run_dir or load_config().workspace.run_dir).expanduser()
        store = RunStore(root)
        record = store.load_run(run_id)
        payload = {
            "schema_version": "core.cli.v1",
            "command": "inspect",
            "run": record.model_dump(mode="json"),
            "audit": store.read_json(run_id, "audit/audit.json")
            if store.exists(run_id, "audit/audit.json")
            else None,
        }
        if json_output:
            _emit_json(payload)
        else:
            typer.echo(f"run {record.run_id}: {record.status} ({record.phase})")
            typer.echo(f"bundle: {root / run_id}")
            typer.echo(f"artifacts: {len(record.artifacts)}")
    except (FileNotFoundError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error


@app.command("audit")
def audit(
    run_id: Annotated[str, typer.Argument(help="Run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the final audit and its promotability decision."""

    try:
        root = (run_dir or load_config().workspace.run_dir).expanduser()
        path = root / run_id / "audit" / "audit.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        payload = {
            **result,
            "schema_version": "core.cli.audit.v1",
            "run_id": run_id,
            "report": str(root / run_id / "audit" / "audit.md"),
        }
        if json_output:
            _emit_json(payload)
        else:
            typer.echo(f"{str(payload.get('status', 'fail')).upper()} audit")
            typer.echo(f"report: {payload['report']}")
    except FileNotFoundError as error:
        _fail(error)
        raise typer.Exit(20) from error
    except ValueError as error:
        _fail(error)
        raise typer.Exit(20) from error
    if payload.get("status") != "pass":
        raise typer.Exit(30)


@app.command("validate-recipe")
def validate_recipe(
    document_type: Annotated[str, typer.Option("--document-type")] = "process",
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate and fingerprint one policy, rubric, and template recipe."""

    try:
        recipe = load_recipe(_reference_pack(reference_pack), document_type=document_type)
        payload = {
            "schema_version": "core.recipe.v1",
            "recipe_id": recipe.recipe_id,
            "recipe_digest": recipe.recipe_digest,
            "sections": len(recipe.required_sections),
            "tables": len(recipe.tables),
            "rubric_criteria": len(recipe.rubric_criteria),
        }
        if json_output:
            _emit_json(payload)
        else:
            typer.echo(f"{payload['recipe_id']} ({payload['recipe_digest']})")
    except (FileNotFoundError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error


@app.command("watch-inbox")
def watch_inbox(
    inbox: Annotated[
        Path | None,
        typer.Argument(help="Inbox directory containing exactly one supported source."),
    ] = None,
    document_type: Annotated[str, typer.Option("--document-type")] = "process",
    structure_mode: Annotated[str, typer.Option("--structure-mode")] = "auto",
    execution_mode: Annotated[str, typer.Option("--execution-mode")] = "offline",
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Thin wrapper: run the single document currently in the inbox directory."""

    config = load_config()
    target = (inbox or config.workspace.inbox_dir).expanduser()
    run_document(
        source=target,
        document_type=document_type,
        structure_mode=structure_mode,
        execution_mode=execution_mode,
        run_dir=run_dir,
        reference_pack=reference_pack,
        until="complete",
        json_output=json_output,
    )


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
