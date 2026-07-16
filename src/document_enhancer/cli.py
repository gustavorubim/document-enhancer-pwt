"""Typer CLI for the WT0 foundation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console

from . import __version__
from .config import config_as_public_dict, load_config
from .doctor import doctor_json, run_doctor
from .domain.audit import Audit
from .domain.enums import DocumentType
from .domain.run import ExportBundleManifest
from .errors import DocumentEnhancerError
from .export import validate_export_bundle
from .llm import EmbeddingProfile, GeminiEmbeddingAdapter
from .logging import configure_logging, get_logger
from .prompting import ComposedPrompt, PromptPack, list_prompts, load_prompt_pack, show_prompt
from .prompting import validate as validate_prompts
from .rag import (
    OfflineDeterministicEmbedder,
    RagBuildError,
    build_package,
    ingest_package,
    inspect_package,
    verify_package,
)
from .references.loader import load_reference_pack
from .workflow import (
    DocumentWorkflow,
    WorkflowServices,
    WorkflowSnapshot,
    workflow_input_fingerprints,
)

app = typer.Typer(
    name="docenhance",
    help="Governed, local-first document enhancement.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect non-secret configuration.")
app.add_typer(config_app, name="config")
prompts_app = typer.Typer(help="Inspect and validate the selected versioned prompt pack.")
app.add_typer(prompts_app, name="prompts")
rag_app = typer.Typer(help="Build and inspect sealed SQLite RAG packages and catalogs.")
app.add_typer(rag_app, name="rag")
console = Console()
logger = get_logger("cli")


def _emit_error(error: DocumentEnhancerError) -> None:
    typer.echo(f"error: {error.message}", err=True)
    if error.detail:
        logger.debug("error detail: %s", error.detail)


def _emit_json(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))


@app.callback()
def main_callback(
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable diagnostic logging.")] = False,
) -> None:
    configure_logging(verbose=verbose)


@app.command()
def version() -> None:
    """Print the installed package version."""

    typer.echo(__version__)


@config_app.command("show")
def config_show(
    json_output: Annotated[bool, typer.Option("--json", help="Emit stable JSON.")] = False,
) -> None:
    """Show resolved non-secret configuration."""

    try:
        payload = config_as_public_dict(load_config())
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for section, values in payload.items():
            console.print(f"[bold]{section}[/bold]")
            for key, value in values.items():
                console.print(f"  {key} = {value}")


@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Emit stable JSON.")] = False,
) -> None:
    """Check WT0 runtime capabilities without making provider calls."""

    try:
        checks = run_doctor(load_config())
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error
    if json_output:
        typer.echo(json.dumps(doctor_json(checks), indent=2, sort_keys=True))
    else:
        for check in checks:
            style = {"pass": "green", "warn": "yellow", "fail": "red", "info": "cyan"}.get(
                check.status, "white"
            )
            console.print(f"[{style}]{check.status:>4}[/{style}] {check.name}: {check.detail}")
    if any(check.status == "fail" for check in checks):
        raise typer.Exit(50)


@app.command("run")
def run_workflow(
    source: Annotated[Path, typer.Argument(help="Markdown, text, DOCX, or text-based PDF source.")],
    document_type: Annotated[
        str, typer.Option("--document-type", help="Target document type.")
    ] = "process",
    structure_mode: Annotated[
        str, typer.Option("--structure-mode", help="parser, auto, recover, force, or off.")
    ] = "parser",
    until: Annotated[
        str, typer.Option("--until", help="Stop at questions, checklist, or complete.")
    ] = "complete",
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    gate2: Annotated[
        bool, typer.Option("--gate2/--no-gate2", help="Enable the second human gate.")
    ] = True,
    catalog_ingest: Annotated[
        bool,
        typer.Option(
            "--catalog-ingest/--no-catalog-ingest",
            help="Ingest the validated package into the cumulative catalog.",
        ),
    ] = True,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit stable machine-readable JSON.")
    ] = False,
) -> None:
    """Run the local, resumable M5 enhancement workflow."""

    try:
        if not source.is_file():
            raise DocumentEnhancerError(f"source is not a regular file: {source}")
        if document_type not in {item.value for item in DocumentType}:
            raise DocumentEnhancerError(f"unsupported document type: {document_type}")
        if until not in {"questions", "checklist", "complete"}:
            raise DocumentEnhancerError("--until must be questions, checklist, or complete")
        config = load_config()
        root = (run_dir or config.workspace.run_dir).expanduser()
        services = WorkflowServices(
            run_root=root,
            source=source.expanduser().resolve(),
            document_type=DocumentType(document_type),
            structure_mode=structure_mode,
            stop_after=until if until in {"questions", "checklist"} else None,
            gate2_enabled=gate2,
            offline=True,
            input_fingerprints=workflow_input_fingerprints(
                prompt_pack=config.references.prompt_pack,
                reference_pack=config.references.reference_pack,
            ),
            prompt_pack=config.references.prompt_pack,
            reference_pack=config.references.reference_pack,
            auto_catalog_ingest=catalog_ingest,
            catalog_path=config.workspace.catalog_path,
            embedding_profile=EmbeddingProfile(
                model=config.gemini.embedding_model,
                dimensions=config.gemini.embedding_dimensions,
                backend=config.gemini.backend,
            ),
        )
        result = DocumentWorkflow(services).run()
        payload = result.model_dump(mode="json")
        if json_output:
            _emit_json(payload)
        else:
            console.print(f"[bold]run {result.run_id}[/bold]")
            console.print(f"status: {result.status}")
            console.print(f"current stage: {result.current_stage}")
            console.print(f"next action: {result.next_action}")
            console.print(f"artifacts: {root / result.run_id}")
        if result.exit_code:
            raise typer.Exit(result.exit_code)
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error


def _load_snapshot(run_dir: Path, run_id: str) -> WorkflowSnapshot:
    path = run_dir.expanduser() / run_id / "workflow-state.json"
    if not path.is_file():
        raise DocumentEnhancerError(f"no workflow snapshot found for run {run_id}")
    try:
        return WorkflowSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DocumentEnhancerError(f"workflow snapshot is invalid for run {run_id}") from exc


def _status_payload(snapshot: WorkflowSnapshot, *, command: str) -> dict[str, object]:
    return {
        "schema_version": "m7.cli.v1",
        "command": command,
        "run_id": snapshot.run_id,
        "status": snapshot.status,
        "current_stage": snapshot.current_stage,
        "next_action": snapshot.next_action,
        "exit_code": 10
        if snapshot.status == "waiting"
        else 0
        if snapshot.status == "succeeded"
        else 20,
        "completed_stages": snapshot.completed_stages,
        "cache_keys": snapshot.cache_keys,
        "errors": snapshot.errors,
    }


@app.command("status")
def workflow_status(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit stable machine-readable JSON.")
    ] = False,
) -> None:
    """Show run status, current stage, and next human action."""

    try:
        snapshot = _load_snapshot(run_dir or load_config().workspace.run_dir, run_id)
        payload = _status_payload(snapshot, command="status")
        if json_output:
            _emit_json(payload)
        else:
            console.print(f"[bold]run {snapshot.run_id}[/bold]")
            console.print(f"status: {snapshot.status}")
            console.print(f"current stage: {snapshot.current_stage}")
            console.print(f"next action: {snapshot.next_action}")
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error


@app.command("current-stage")
def workflow_current_stage(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print only the persisted current stage."""

    snapshot = _load_snapshot(run_dir or load_config().workspace.run_dir, run_id)
    if json_output:
        _emit_json(_status_payload(snapshot, command="current-stage"))
    else:
        typer.echo(snapshot.current_stage)


@app.command("next-action")
def workflow_next_action(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print the next safe action for a persisted run."""

    snapshot = _load_snapshot(run_dir or load_config().workspace.run_dir, run_id)
    if json_output:
        _emit_json(_status_payload(snapshot, command="next-action"))
    else:
        typer.echo(snapshot.next_action)


@app.command("resume")
def resume_workflow(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID to resume.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit stable machine-readable JSON.")
    ] = False,
) -> None:
    """Validate edited reviewer artifacts and resume a waiting run."""

    try:
        root = (run_dir or load_config().workspace.run_dir).expanduser()
        snapshot = _load_snapshot(root, run_id)
        config = load_config()
        services = WorkflowServices(
            run_root=root,
            source=Path(),
            run_id=run_id,
            document_type=DocumentType(snapshot.document_type),
            structure_mode="parser",
            gate2_enabled=snapshot.gate2_enabled,
            offline=True,
            input_fingerprints=workflow_input_fingerprints(
                prompt_pack=config.references.prompt_pack,
                reference_pack=config.references.reference_pack,
            ),
            prompt_pack=config.references.prompt_pack,
            reference_pack=config.references.reference_pack,
            auto_catalog_ingest=True,
            catalog_path=config.workspace.catalog_path,
            embedding_profile=EmbeddingProfile(
                model=config.gemini.embedding_model,
                dimensions=config.gemini.embedding_dimensions,
                backend=config.gemini.backend,
            ),
        )
        result = DocumentWorkflow(services).resume()
        if json_output:
            _emit_json(result.model_dump(mode="json"))
        else:
            console.print(f"[bold]run {result.run_id}[/bold]")
            console.print(f"status: {result.status}")
            console.print(f"current stage: {result.current_stage}")
            console.print(f"next action: {result.next_action}")
        if result.exit_code:
            raise typer.Exit(result.exit_code)
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error


@app.command("audit")
def inspect_audit(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect the final fail-closed audit result for a run."""

    root = (run_dir or load_config().workspace.run_dir).expanduser() / run_id
    path = root / "audit/audit.json"
    if not path.is_file():
        raise typer.Exit(20)
    try:
        audit = Audit.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        typer.echo(f"error: invalid audit artifact: {exc}", err=True)
        raise typer.Exit(20) from exc
    payload = {
        "schema_version": "m7.cli.audit.v1",
        "run_id": run_id,
        "status": audit.status.value,
        "route": audit.routing.route,
        "blocker_ids": audit.routing.blocker_ids,
        "independent_audit_status": audit.independent_audit.status,
        "passed_checks": sum(item.passed for item in audit.deterministic_checks),
        "failed_checks": sum(not item.passed for item in audit.deterministic_checks),
        "report": str(root / "audit/report.md"),
    }
    if json_output:
        _emit_json(payload)
    else:
        style = "green" if audit.status.value == "pass" else "red"
        console.print(f"[{style}]{audit.status.value.upper()}[/{style}] audit {audit.audit_id}")
        console.print(f"route: {audit.routing.route}")
        console.print(f"independent: {audit.independent_audit.status}")
        console.print(f"blockers: {', '.join(audit.routing.blocker_ids) or 'none'}")
        console.print(f"report: {root / 'audit/report.md'}")
    if audit.status.value != "pass":
        raise typer.Exit(30)


@app.command("export")
def inspect_export(
    run_id: Annotated[str, typer.Argument(help="Persisted run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect and reconcile a completed JSONL export bundle."""

    directory = (run_dir or load_config().workspace.run_dir).expanduser() / run_id / "export"
    errors = validate_export_bundle(directory)
    manifest_path = directory / "bundle-manifest.json"
    if not manifest_path.is_file():
        typer.echo("error: export bundle is incomplete", err=True)
        raise typer.Exit(30)
    try:
        manifest = ExportBundleManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        typer.echo(f"error: invalid export manifest: {exc}", err=True)
        raise typer.Exit(30) from exc
    payload = {
        "schema_version": "m7.cli.export.v1",
        "run_id": run_id,
        "bundle_id": manifest.bundle_id,
        "valid": not errors,
        "errors": list(errors),
        "counts": manifest.artifact_counts,
        "digests": manifest.artifact_digests,
    }
    if json_output:
        _emit_json(payload)
    else:
        console.print(
            f"[{'green' if not errors else 'red'}]{'VALID' if not errors else 'INVALID'}[/] export {manifest.bundle_id}"
        )
        for name, count in sorted(manifest.artifact_counts.items()):
            console.print(f"{name}: {count}")
        for error in errors:
            console.print(f"- {error}")
    if errors:
        raise typer.Exit(30)


def _rag_database(value: str, run_dir: Path) -> tuple[Path, Path | None]:
    candidate = Path(value).expanduser()
    if candidate.is_file():
        return candidate.resolve(), None
    run_path = run_dir.expanduser() / value
    return run_path / "rag/document-rag.sqlite3", run_path / "export"


@rag_app.command("build")
def rag_build(
    run_id: Annotated[str, typer.Argument(help="Completed, audit-passing run ID.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir", help="Run artifact root.")] = None,
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Use the deterministic fake embedding provider."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build a sealed package only; this command performs no retrieval or answer generation."""

    config = load_config()
    root = (run_dir or config.workspace.run_dir).expanduser()
    profile = EmbeddingProfile(
        model=config.gemini.embedding_model,
        dimensions=config.gemini.embedding_dimensions,
        backend=config.gemini.backend,
    )
    adapter = None
    if offline:
        adapter = GeminiEmbeddingAdapter(
            profile=profile,
            embedder=OfflineDeterministicEmbedder(profile.dimensions),
        )
    try:
        manifest = build_package(root / run_id, profile=profile, adapter=adapter)
    except RagBuildError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(30) from exc
    payload = {
        "schema_version": "m7.cli.rag-build.v1",
        "run_id": run_id,
        "rag_build_id": manifest.rag_build_id,
        "database": str(root / run_id / "rag/document-rag.sqlite3"),
        "manifest": str(root / run_id / "rag/build-manifest.json"),
        "promotion_status": manifest.promotion_status,
        "row_counts": manifest.row_counts,
        "embedding": {
            "model": manifest.embedding_model,
            "backend": manifest.embedding_backend,
            "dimension": manifest.embedding_dimension,
            "format_version": manifest.embedding_input_format_version,
        },
    }
    if json_output:
        _emit_json(payload)
    else:
        console.print(f"[green]PROMOTED[/green] RAG build {manifest.rag_build_id}")
        console.print(f"database: {payload['database']}")
        console.print(f"chunks/vectors: {manifest.vector_count}")


@rag_app.command("verify")
def rag_verify(
    target: Annotated[str, typer.Argument(help="Run ID or SQLite package path.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Verify schema, integrity, counts, graph, FTS, and embeddings without retrieval."""

    database, export_dir = _rag_database(target, run_dir or load_config().workspace.run_dir)
    result = verify_package(database, export_dir=export_dir)
    payload = result.as_dict() | {"database": str(database)}
    if json_output:
        _emit_json(payload)
    else:
        style = "green" if result.valid else "red"
        console.print(f"[{style}]{'VALID' if result.valid else 'INVALID'}[/{style}] {database}")
        console.print(f"schema: {result.schema_version}; build: {result.rag_build_id}")
        for name, count in sorted(result.row_counts.items()):
            console.print(f"{name}: {count}")
        for error in result.errors:
            console.print(f"- {error}")
    if not result.valid:
        raise typer.Exit(30)


@rag_app.command("inspect")
def rag_inspect(
    target: Annotated[str, typer.Argument(help="Run ID or SQLite package path.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Render stable package metadata and human-readable row summaries."""

    database, _export_dir = _rag_database(target, run_dir or load_config().workspace.run_dir)
    payload = inspect_package(database)
    if json_output:
        _emit_json(payload)
    else:
        console.print(f"[bold]RAG package[/bold] {database}")
        console.print(f"valid: {payload['valid']}")
        console.print(f"build: {payload['rag_build_id']}")
        for name, count in sorted(cast(dict[str, int], payload["row_counts"]).items()):
            console.print(f"{name}: {count}")
    if not payload["valid"]:
        raise typer.Exit(30)


@rag_app.command("ingest")
def rag_ingest(
    run_id: Annotated[str, typer.Argument(help="Run ID with a validated RAG package.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Atomically ingest one sealed package into the cumulative catalog."""

    config = load_config()
    root = (run_dir or config.workspace.run_dir).expanduser()
    run_path = root / run_id
    try:
        receipt = ingest_package(
            run_path / "rag/document-rag.sqlite3",
            catalog or config.workspace.catalog_path,
            receipt_path=run_path / "rag/catalog-ingestion.json",
        )
    except RagBuildError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(30) from exc
    payload = receipt.as_dict()
    if json_output:
        _emit_json(payload)
    else:
        suffix = " (idempotent)" if receipt.idempotent else ""
        console.print(
            f"[green]PROMOTED[/green] catalog generation {receipt.catalog_generation}{suffix}"
        )
        console.print(f"catalog: {receipt.catalog_path}")


def _prompt_variables(pack: PromptPack, prompt_id: str, document_type: str) -> dict[str, object]:
    prompt = pack.prompt(prompt_id)
    values: dict[str, object] = {}
    for variable in prompt.variables:
        if variable.name == "document_type":
            values[variable.name] = document_type
        elif variable.default is not None:
            values[variable.name] = variable.default
        elif variable.value_type.lower() in {"mapping", "object", "dict", "json"}:
            values[variable.name] = {}
        elif variable.value_type.lower() in {"list", "array", "list[str]", "array[str]"}:
            values[variable.name] = []
        else:
            values[variable.name] = ""
    return values


@prompts_app.command("list")
def prompts_list(
    prompt_pack: Annotated[Path | None, typer.Option("--prompt-pack")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List prompt IDs, routes, schemas, and governed reference scope."""

    config = load_config()
    pack_path = prompt_pack or config.references.prompt_pack
    ref_path = reference_pack or config.references.reference_pack
    values = list_prompts(pack_path, reference_pack=ref_path)
    if json_output:
        _emit_json({"schema_version": "m5.prompts.v1", "prompts": values})
    else:
        for item in values:
            console.print(f"{item['prompt_id']}  {item['model_route']}  {item['output_schema']}")


@prompts_app.command("show")
def prompts_show(
    prompt_id: Annotated[str, typer.Argument(help="Immutable prompt ID.")],
    composed: Annotated[
        bool,
        typer.Option(
            "--composed", help="Compose with governed references and visible data boundaries."
        ),
    ] = False,
    document_type: Annotated[str, typer.Option("--document-type")] = "process",
    prompt_pack: Annotated[Path | None, typer.Option("--prompt-pack")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show prompt metadata or a deterministic resolved prompt composition."""

    config = load_config()
    pack_path = prompt_pack or config.references.prompt_pack
    ref_path = reference_pack or config.references.reference_pack
    pack = load_prompt_pack(pack_path)
    variables = _prompt_variables(pack, prompt_id, document_type)
    value = show_prompt(
        pack,
        prompt_id,
        composed=composed,
        variables=variables,
        reference_pack=load_reference_pack(ref_path),
        document_type=document_type,
    )
    if json_output:
        if isinstance(value, str):
            value = {"prompt_id": prompt_id, "text": value}
        if isinstance(value, ComposedPrompt):
            value = {
                "prompt_id": value.prompt_id,
                "text": value.text,
                "resolution": value.resolution.model_dump(mode="json"),
                "resolved_references": [item.snapshot() for item in value.resolved_references],
            }
        _emit_json(value)
    elif isinstance(value, str):
        typer.echo(value)
    elif isinstance(value, ComposedPrompt):
        typer.echo(value.text)
    else:
        for key, item in value.items():
            console.print(f"{key}: {item}")


@prompts_app.command("validate")
def prompts_validate(
    prompt_pack: Annotated[Path | None, typer.Option("--prompt-pack")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate the selected prompt pack before any provider call."""

    config = load_config()
    report = validate_prompts(
        prompt_pack or config.references.prompt_pack,
        reference_pack=reference_pack or config.references.reference_pack,
    )
    if json_output:
        _emit_json(report)
    else:
        console.print("valid" if report["ok"] else "invalid")
        for error in cast(list[object], report["errors"]):
            console.print(f"- {error}")
    if not report["ok"]:
        raise typer.Exit(20)


def main() -> None:
    """Console-script entry point with safe error conversion."""

    try:
        app()
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error
