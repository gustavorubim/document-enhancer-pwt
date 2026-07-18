"""Small CLI for the file-backed document enhancement workflow."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

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
from .core.layout import AUDIT, AUDIT_MARKDOWN, DECISIONS_YAML, FINAL_MARKDOWN, HTML_REPORT
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
rag_app = typer.Typer(
    name="rag",
    help="Index sealed bundles and ask cited questions over their text and graph.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(rag_app, name="rag")

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


def _console() -> Console:
    """Create a console at call time so Typer tests and redirected output are respected."""

    return Console(highlight=False)


def _step(console: Console, number: int, total: int, title: str, detail: str) -> None:
    heading = Text()
    heading.append(f"STEP {number}/{total}  ", style="bold bright_cyan")
    heading.append(title, style="bold white")
    body = Table.grid(padding=(0, 1))
    body.add_row(heading)
    body.add_row(Text(detail, style="bright_black"))
    console.print(Panel(body, border_style="cyan", padding=(1, 2)))


def _success(console: Console, message: str) -> None:
    console.print(Text.assemble(("✓ ", "bold green"), (message, "green")))


def _inspection_payload(root: Path, run_id: str) -> dict[str, object]:
    store = RunStore(root)
    record = store.load_run(run_id)
    return {
        "schema_version": "core.cli.v1",
        "command": "inspect",
        "run": record.model_dump(mode="json"),
        "audit": store.read_json(run_id, AUDIT) if store.exists(run_id, AUDIT) else None,
    }


def _audit_payload(root: Path, run_id: str) -> dict[str, object]:
    result = json.loads((root / run_id / AUDIT).read_text(encoding="utf-8"))
    return {
        **result,
        "schema_version": "core.cli.audit.v1",
        "run_id": run_id,
        "report": str(root / run_id / AUDIT_MARKDOWN),
    }


def _render_inspection(console: Console, payload: dict[str, object], *, root: Path) -> None:
    run = payload["run"]
    assert isinstance(run, dict)
    table = Table(title="Bundle inspection", box=box.ROUNDED, border_style="bright_cyan")
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value", style="white")
    artifacts = run.get("artifacts")
    table.add_row("Run", str(run.get("run_id", "unknown")))
    table.add_row("Status", str(run.get("status", "unknown")).upper())
    table.add_row("Phase", str(run.get("phase", "unknown")).replace("_", " ").title())
    table.add_row("Artifacts", str(len(artifacts) if isinstance(artifacts, dict) else 0))
    table.add_row("Bundle", str(root / str(run.get("run_id", ""))))
    table.add_row("HTML reviewer", str(root / str(run.get("run_id", "")) / HTML_REPORT))
    console.print(table)


def _render_audit(console: Console, payload: dict[str, object]) -> None:
    checks = payload.get("checks")
    check_values = checks if isinstance(checks, dict) else {}
    table = Table(title="Final audit", box=box.ROUNDED, border_style="green")
    table.add_column("Check", style="bold")
    table.add_column("Result", justify="center")
    for name, passed in check_values.items():
        label = str(name).replace("_", " ").title()
        result = Text("PASS", style="bold green") if passed else Text("FAIL", style="bold red")
        table.add_row(label, result)
    console.print(table)
    summary = str(payload.get("summary") or "No audit summary was provided.")
    status = str(payload.get("status") or "fail").upper()
    color = "green" if status == "PASS" else "red"
    console.print(Panel(summary, title=f"[bold {color}]{status}[/] audit", border_style=color))
    console.print(f"[bold]Audit report:[/] {payload.get('report')}")


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


def _rag_embeddings(*, offline: bool, profile: object | None = None) -> Any:
    """Resolve the optional embedding client lazily so authoring imports remain independent."""

    from .retrieval.embeddings import DeterministicEmbeddings, gemini_embeddings
    from .retrieval.models import EmbeddingProfile

    selected = profile if isinstance(profile, EmbeddingProfile) else None
    if offline or (selected is not None and selected.provider == "offline"):
        dimensions = selected.dimensions if selected is not None else 64
        return DeterministicEmbeddings(dimensions=dimensions)
    _load_project_env()
    config = load_config()
    gateway = GeminiGatewayConfig.from_env(
        backend=config.gemini.backend,
        project=config.gemini.project,
        location=config.gemini.location,
    )
    model = selected.model if selected is not None else config.rag.embedding_model
    dimensions = selected.dimensions if selected is not None else config.rag.embedding_dimensions
    kwargs: dict[str, object] = {}
    if gateway.backend.value == "developer_api":
        if gateway.api_key is None:
            raise DocumentEnhancerError("Gemini credentials are required for RAG embeddings")
        kwargs["api_key"] = gateway.api_key
    else:
        if not gateway.project or not gateway.location:
            raise DocumentEnhancerError("Vertex AI requires project and location")
        kwargs.update({"vertexai": True, "project": gateway.project, "location": gateway.location})
    return gemini_embeddings(model=model, dimensions=dimensions, **kwargs)


def _render_rag_answer(console: Console, result: object, *, show_trace: bool) -> None:
    from .retrieval.models import AnswerResult

    answer = AnswerResult.model_validate(result)
    if answer.status == "insufficient":
        console.print(
            Panel(
                "The indexed evidence is insufficient or conflicting, so no answer was asserted.",
                title="[bold yellow]Insufficient evidence[/]",
                border_style="yellow",
            )
        )
    else:
        source_markers = {
            source.evidence_id: f"S{index}" for index, source in enumerate(answer.sources, 1)
        }
        lines = [
            f"{claim.text} {' '.join(f'[{source_markers[item]}]' for item in claim.citation_ids)}"
            for claim in answer.claims
        ]
        console.print(Panel(Markdown("\n\n".join(lines)), title="Answer", border_style="green"))
    if answer.sources:
        table = Table(title="Sources", box=box.ROUNDED, border_style="bright_cyan")
        table.add_column("ID", style="bold cyan")
        table.add_column("Document")
        table.add_column("Section")
        table.add_column("Run")
        table.add_column("Chunk")
        for index, source in enumerate(answer.sources, 1):
            table.add_row(
                f"S{index}",
                source.document_title,
                " > ".join(source.heading_path),
                source.run_id,
                source.chunk_id,
            )
        console.print(table)
    if show_trace and answer.trace:
        table = Table(title="Retrieval trace", box=box.SIMPLE, border_style="bright_black")
        table.add_column("Tool")
        table.add_column("Status")
        table.add_column("Evidence")
        table.add_column("Graph path")
        table.add_column("Time")
        for event in answer.trace:
            paths = "; ".join(" → ".join(path.node_ids) for path in event.graph_paths)
            table.add_row(
                event.tool,
                event.status,
                ", ".join(event.evidence_ids) or "—",
                paths or "—",
                f"{event.duration_ms:.1f} ms",
            )
        console.print(table)


def _render_corpus_answer(console: Console, result: object, *, show_trace: bool) -> None:
    from .retrieval.models import CorpusResult

    answer = CorpusResult.model_validate(result)
    coverage = answer.coverage
    color = "green" if answer.status == "answered" and not coverage.failed_run_ids else "yellow"
    console.print(
        Panel(
            f"Scope: [bold]{answer.plan.scope}[/]  •  Intent: [bold]{answer.plan.intent}[/]  •  "
            f"Coverage: [bold]{coverage.mode}[/]\n"
            f"Documents: {coverage.documents_scanned}/{coverage.documents_requested}  •  "
            f"Chunks examined: {coverage.chunks_examined}/{coverage.chunks_available}  •  "
            f"Documents with matches: {coverage.documents_with_matches}  •  "
            f"Truncated: {'yes' if coverage.truncated else 'no'}",
            title="Corpus coverage",
            border_style=color,
        )
    )
    marker_by_evidence = {
        source.evidence_id: f"S{index}" for index, source in enumerate(answer.sources, 1)
    }
    if answer.items:
        table = Table(title="Corpus results", box=box.ROUNDED, border_style="green")
        table.add_column("#", style="bold cyan", no_wrap=True)
        table.add_column("Item")
        table.add_column("Attributes")
        table.add_column("Run")
        table.add_column("Sources", style="cyan")
        source_by_id = {source.evidence_id: source for source in answer.sources}
        for index, item in enumerate(answer.items, 1):
            attributes = "\n".join(f"{value.name}: {value.value}" for value in item.attributes)
            run_values = sorted(
                {
                    source_by_id[evidence_id].run_id
                    for evidence_id in item.citation_ids
                    if evidence_id in source_by_id
                }
            )
            markers = " ".join(
                f"[{marker_by_evidence[evidence_id]}]"
                for evidence_id in item.citation_ids
                if evidence_id in marker_by_evidence
            )
            table.add_row(
                str(index),
                item.statement,
                attributes or "—",
                ", ".join(run_values),
                markers,
            )
        console.print(table)
    else:
        console.print(
            Panel(
                "No cited corpus items were supported by the examined evidence.",
                title="Insufficient evidence",
                border_style="yellow",
            )
        )
    if answer.sources:
        table = Table(title="Sources", box=box.ROUNDED, border_style="bright_cyan")
        table.add_column("ID", style="bold cyan")
        table.add_column("Document")
        table.add_column("Section")
        table.add_column("Run")
        table.add_column("Chunk")
        for index, source in enumerate(answer.sources, 1):
            table.add_row(
                f"S{index}",
                source.document_title,
                " > ".join(source.heading_path),
                source.run_id,
                source.chunk_id,
            )
        console.print(table)
    if show_trace and answer.trace:
        table = Table(title="Corpus map trace", box=box.SIMPLE, border_style="bright_black")
        table.add_column("Run")
        table.add_column("Batch")
        table.add_column("Status")
        table.add_column("Chunks")
        table.add_column("Time")
        for event in answer.trace:
            table.add_row(
                str(event.input.get("run_id", "—")),
                str(event.input.get("batch", "—")),
                event.status,
                str(event.input.get("chunks", 0)),
                f"{event.duration_ms:.1f} ms",
            )
        console.print(table)


def _render_rag_result(console: Console, result: object, *, show_trace: bool) -> None:
    from .retrieval.models import CorpusResult

    if isinstance(result, CorpusResult):
        _render_corpus_answer(console, result, show_trace=show_trace)
    else:
        _render_rag_answer(console, result, show_trace=show_trace)


def _open_rag_catalog(catalog_path: Path) -> Any:
    from .retrieval.catalog import RagCatalog, read_catalog_profile

    profile = read_catalog_profile(catalog_path)
    embeddings = _rag_embeddings(offline=profile.provider == "offline", profile=profile)
    return RagCatalog.open(catalog_path, embeddings)


def _print_record(record: RunRecord, *, root: Path, json_output: bool) -> None:
    value = record.model_dump(mode="json")
    if json_output:
        _emit_json(value)
        return
    console = _console()
    status = str(value["status"])
    color = "green" if status == "succeeded" else "yellow" if status == "waiting" else "red"
    table = Table(box=box.ROUNDED, border_style=color, title="Document Enhancer run")
    table.add_column("Field", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Run", str(value["run_id"]))
    table.add_row("Status", Text(status.upper(), style=f"bold {color}"))
    table.add_row("Phase", str(value["phase"]).replace("_", " ").title())
    table.add_row("Bundle", str(root / str(value["run_id"])))
    table.add_row("HTML reviewer", str(root / str(value["run_id"]) / HTML_REPORT))
    console.print(table)
    if value["status"] == "waiting":
        console.print(
            Panel(
                "Read the numbered review reports, answer every blocking decision, set "
                "[bold]approve_rewrite: true[/], save the YAML file, and run "
                f"[bold cyan]docenhance stage-two {value['run_id']}[/].\n\n"
                f"Decision file: {root / str(value['run_id']) / DECISIONS_YAML}",
                title="[bold yellow]Human review required[/]",
                border_style="yellow",
            )
        )


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
        selected_source = _select_source(source)
        selected_reference_pack = _reference_pack(reference_pack)
        workflow = _runner(
            root=root,
            reference_pack=selected_reference_pack,
            document_type=document_type,
            structure_mode=structure_mode,
            execution_mode=execution_mode,
        )
        if json_output:
            result = workflow.start(selected_source, stop_at=until)
        else:
            console = _console()
            _step(
                console,
                1,
                2,
                "Validate the Stage 1 configuration",
                f"Source: {selected_source}\n"
                f"Document type: {document_type}  •  Execution: {execution_mode}  •  "
                f"Structure recovery: {structure_mode}\n"
                f"Run workspace: {root}",
            )
            _success(console, "Source, recipe, execution mode, and output workspace are ready.")
            _step(
                console,
                2,
                2,
                "Analyze the source and prepare the review gate",
                "The runner will extract and normalize source evidence, evaluate the document "
                "against the selected recipe, review every section, infer and propose process "
                "flows, generate questions with safe suggestions where appropriate, and write "
                "the numbered Markdown, JSON, Mermaid, and HTML review artifacts.",
            )
            with console.status("[bold cyan]Building the Stage 1 review bundle…[/]"):
                result = workflow.start(selected_source, stop_at=until)
            _success(
                console,
                "Stage 1 analysis, enhanced decision file, and HTML reviewer were generated.",
            )
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
    """Continue a run after editing the generated decisions YAML file."""

    try:
        config = load_config()
        root = (run_dir or config.workspace.run_dir).expanduser()
        record = RunStore(root).load_run(run_id)
        document_type = record.recipe.rsplit("/", 1)[-1]
        workflow = _runner(
            root=root,
            reference_pack=_reference_pack(reference_pack),
            document_type=document_type,
            structure_mode="auto",
            execution_mode=record.execution_mode,
        )
        if json_output:
            result = workflow.resume(run_id)
        else:
            console = _console()
            _step(
                console,
                1,
                1,
                "Apply decisions and produce the final bundle",
                "Validating the human decision contract, compiling the rewrite plan, applying "
                "approved answers, exporting graph artifacts, and running deterministic checks.",
            )
            console.print(f"[bold]Decision file:[/] {root / run_id / DECISIONS_YAML}")
            with console.status("[bold cyan]Rewriting, exporting, and verifying…[/]"):
                result = workflow.resume(run_id)
            if result.status == "succeeded":
                _success(console, "Rewrite and deterministic verification completed.")
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
            "next_action": f"edit {DECISIONS_YAML} and run stage-two"
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
        payload = _inspection_payload(root, run_id)
        if json_output:
            _emit_json(payload)
        else:
            console = _console()
            _step(
                console,
                1,
                1,
                "Inspect the completed bundle",
                "Reading durable run state, counting registered artifacts, and locating the "
                "human-readable HTML reviewer and final audit.",
            )
            _render_inspection(console, payload, root=root)
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
        payload = _audit_payload(root, run_id)
        if json_output:
            _emit_json(payload)
        else:
            console = _console()
            _step(
                console,
                1,
                1,
                "Review the final promotion audit",
                "Displaying every deterministic check and the bundle's final promotability "
                "decision. A passing audit is required before the seal is trusted.",
            )
            _render_audit(console, payload)
    except FileNotFoundError as error:
        _fail(error)
        raise typer.Exit(20) from error
    except ValueError as error:
        _fail(error)
        raise typer.Exit(20) from error
    if payload.get("status") != "pass":
        raise typer.Exit(30)


@app.command("stage-two")
def stage_two(
    run_id: Annotated[str, typer.Argument(help="Run ID with completed reviewer decisions.")],
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    reference_pack: Annotated[Path | None, typer.Option("--reference-pack")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Continue, inspect, and audit one run as a narrated Stage 2 workflow."""

    try:
        root = (run_dir or load_config().workspace.run_dir).expanduser()
        current = RunStore(root).load_run(run_id)
        document_type = current.recipe.rsplit("/", 1)[-1]
        workflow = _runner(
            root=root,
            reference_pack=_reference_pack(reference_pack),
            document_type=document_type,
            structure_mode="auto",
            execution_mode=current.execution_mode,
        )
        console = None if json_output else _console()
        if console:
            console.rule("[bold bright_cyan]Document Enhancer · Stage 2[/]")
            console.print(
                "This command applies the saved human decisions, inspects the completed bundle, "
                "and presents the final audit in one continuous workflow.\n"
            )
            _step(
                console,
                1,
                3,
                "Continue the reviewed run",
                "Validating question IDs and immutable question context, resolving accepted "
                "suggestions, rewriting the document, exporting portable artifacts, and sealing "
                "only after deterministic checks pass.",
            )
            console.print(f"[bold]Decision file:[/] {root / run_id / DECISIONS_YAML}")
            with console.status("[bold cyan]Applying decisions and building final outputs…[/]"):
                result = workflow.resume(run_id)
        else:
            result = workflow.resume(run_id)

        if result.status == "waiting":
            payload = {
                "schema_version": "core.cli.stage-two.v1",
                "command": "stage-two",
                "run": result.model_dump(mode="json"),
                "inspection": None,
                "audit": None,
            }
            if json_output:
                _emit_json(payload)
            else:
                assert console is not None
                console.print(
                    Panel(
                        "Stage 2 remains paused. Resolve every blocking question, choose a "
                        "non-deferred disposition, and set [bold]approve_rewrite: true[/].\n\n"
                        f"Unresolved: {', '.join(result.unresolved_question_ids) or 'review approval'}",
                        title="[bold yellow]Human decisions still required[/]",
                        border_style="yellow",
                    )
                )
            raise typer.Exit(10)
        if console:
            if result.status == "succeeded":
                _success(console, "The rewrite and export phases completed successfully.")
            else:
                console.print(
                    Text.assemble(
                        ("! ", "bold red"),
                        (
                            "The rewrite completed, but verification blocked promotion. "
                            "Inspecting the bundle and failed checks now.",
                            "red",
                        ),
                    )
                )
            _step(
                console,
                2,
                3,
                "Inspect the generated bundle",
                "Confirming durable run state, artifact registration, final output locations, "
                "and the regenerated HTML reviewer.",
            )
        inspection_payload = _inspection_payload(root, run_id)
        if console:
            _render_inspection(console, inspection_payload, root=root)
            if result.status == "succeeded":
                _success(console, "The final bundle is complete and internally registered.")
            else:
                console.print(
                    Text(
                        "The unsealed outputs are registered for diagnosis and correction.",
                        style="yellow",
                    )
                )
            _step(
                console,
                3,
                3,
                "Present the final audit",
                "Reading the promotion decision and showing each deterministic quality, "
                "traceability, decision, flow, and graph check.",
            )
        audit_payload = _audit_payload(root, run_id)
        if json_output:
            _emit_json(
                {
                    "schema_version": "core.cli.stage-two.v1",
                    "command": "stage-two",
                    "run": result.model_dump(mode="json"),
                    "inspection": inspection_payload,
                    "audit": audit_payload,
                }
            )
        else:
            assert console is not None
            _render_audit(console, audit_payload)
            color = "green" if audit_payload.get("status") == "pass" else "red"
            console.print(
                Panel(
                    f"Stage 2 finished with audit status "
                    f"[bold {color}]{str(audit_payload.get('status', 'fail')).upper()}[/].\n\n"
                    f"Bundle: {root / run_id}\n"
                    f"HTML reviewer: {HTML_REPORT}\n"
                    f"Final document: {FINAL_MARKDOWN}",
                    title="[bold]Stage 2 complete[/]",
                    border_style=color,
                )
            )
    except typer.Exit:
        raise
    except (DocumentEnhancerError, FileNotFoundError, RuntimeError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error
    if audit_payload.get("status") != "pass":
        raise typer.Exit(30)


@rag_app.command("index")
def rag_index(
    run_ids: Annotated[
        list[str] | None,
        typer.Argument(help="One or more sealed run IDs to replace the local catalog with."),
    ] = None,
    all_sealed: Annotated[bool, typer.Option("--all-sealed")] = False,
    run_dir: Annotated[Path | None, typer.Option("--run-dir")] = None,
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline", help="Use deterministic test embeddings, not semantic Gemini embeddings."
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build one atomic FAISS, FTS5, and graph catalog from sealed final documents."""

    try:
        from .retrieval.catalog import RagCatalogBuilder, resolve_bundle_paths

        config = load_config()
        root = (run_dir or config.workspace.run_dir).expanduser()
        catalog_path = (catalog or config.rag.catalog_dir).expanduser()
        bundles = resolve_bundle_paths(root, run_ids or [], all_sealed=all_sealed)
        candidate_count = (
            sum(path.is_dir() for path in root.iterdir())
            if all_sealed and root.is_dir()
            else len(bundles)
        )
        embeddings = _rag_embeddings(offline=offline)
        builder = RagCatalogBuilder(
            catalog_path,
            embeddings,
            chunk_size=config.rag.chunk_size,
            chunk_overlap=config.rag.chunk_overlap,
        )
        console = None if json_output else _console()
        if console:
            console.rule("[bold bright_cyan]Document Enhancer · RAG index[/]")
            console.print(
                f"Selected [bold]{len(bundles)}[/] candidate bundle(s). Each must pass sealed-bundle "
                "validation before a new local catalog can replace the current one."
            )
            if offline:
                console.print(
                    "[yellow]Offline feature-hash embeddings are for tests and demonstrations only.[/]"
                )
            with console.status("[bold cyan]Chunking, embedding, indexing, and validating…[/]"):
                payload = builder.build(bundles)
        else:
            payload = builder.build(bundles)
        payload = {
            **payload,
            "selection": {
                "mode": "all_sealed" if all_sealed else "explicit",
                "selected": len(bundles),
                "rejected": candidate_count - len(bundles),
                "run_ids": [path.name for path in bundles],
            },
        }
        if json_output:
            _emit_json(payload)
        else:
            assert console is not None
            counts = cast(dict[str, object], payload["counts"])
            table = Table(title="RAG catalog", box=box.ROUNDED, border_style="green")
            table.add_column("Field", style="bold cyan")
            table.add_column("Value")
            table.add_row("Catalog", str(payload["catalog"]))
            table.add_row("Bundles", str(counts["bundles"]))
            selection = cast(dict[str, object], payload["selection"])
            table.add_row("Rejected candidates", str(selection["rejected"]))
            table.add_row("Chunks", str(counts["chunks"]))
            table.add_row("Graph nodes", str(counts["nodes"]))
            table.add_row("Graph edges", str(counts["edges"]))
            console.print(table)
            _success(console, "The validated catalog was promoted atomically.")
    except (
        DocumentEnhancerError,
        FileNotFoundError,
        ImportError,
        RuntimeError,
        ValueError,
    ) as error:
        _fail(error)
        raise typer.Exit(20) from error


@rag_app.command("inspect")
def rag_inspect(
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate and summarize the promoted local RAG catalog without a provider call."""

    try:
        from .retrieval.catalog import RagCatalog, read_catalog_profile
        from .retrieval.embeddings import IdentityEmbeddings

        config = load_config()
        catalog_path = (catalog or config.rag.catalog_dir).expanduser()
        profile = read_catalog_profile(catalog_path)
        with RagCatalog.open(catalog_path, IdentityEmbeddings(profile)) as opened:
            payload = opened.inspect()
        if json_output:
            _emit_json(payload)
        else:
            console = _console()
            counts = cast(dict[str, object], payload["counts"])
            run_id_values = cast(list[object], payload["run_ids"])
            table = Table(title="RAG catalog inspection", box=box.ROUNDED, border_style="cyan")
            table.add_column("Field", style="bold cyan")
            table.add_column("Value")
            table.add_row("Catalog", str(payload["catalog"]))
            table.add_row("Runs", ", ".join(str(item) for item in run_id_values))
            table.add_row("Bundles", str(counts["bundles"]))
            table.add_row("Chunks", str(counts["chunks"]))
            table.add_row("Nodes / edges", f"{counts['nodes']} / {counts['edges']}")
            linking = cast(dict[str, object], payload["linking"])
            table.add_row(
                "Graph links",
                f"{linking['linked_chunks']} linked / {linking['unmatched_chunks']} unmatched / "
                f"{linking['ambiguous_chunks']} ambiguous",
            )
            profile_payload = cast(dict[str, object], payload["embedding_profile"])
            table.add_row(
                "Embedding",
                f"{profile_payload['provider']}/{profile_payload['model']} "
                f"({profile_payload['dimensions']}d)",
            )
            table.add_row("Digest", str(payload["catalog_digest"]))
            console.print(table)
    except (FileNotFoundError, ImportError, RuntimeError, ValueError) as error:
        _fail(error)
        raise typer.Exit(20) from error


@rag_app.command("ask")
def rag_ask(
    question: Annotated[str, typer.Argument(help="Question to answer from indexed evidence.")],
    run_ids: Annotated[list[str] | None, typer.Option("--run")] = None,
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    scope: Annotated[str, typer.Option("--scope", help="auto, focused, or corpus")] = "auto",
    coverage: Annotated[
        str,
        typer.Option("--coverage", help="retrieval or exhaustive; exhaustive scans every chunk."),
    ] = "retrieval",
    show_trace: Annotated[bool, typer.Option("--show-trace")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ask one bounded multi-hop question and render validated source citations."""

    try:
        from .retrieval.agent import RagAnswerer, gemini_chat_model
        from .retrieval.corpus import AdaptiveRagAnswerer

        _load_project_env()
        config = load_config()
        catalog_path = (catalog or config.rag.catalog_dir).expanduser()
        with _open_rag_catalog(catalog_path) as opened:
            answerer = AdaptiveRagAnswerer(
                opened,
                gemini_chat_model(config),
                focused_factory=RagAnswerer,
            )
            result = answerer.answer(
                question,
                run_ids=run_ids,
                scope=cast(Any, scope),
                coverage=cast(Any, coverage),
            )
        if json_output:
            _emit_json(result.model_dump(mode="json"))
        else:
            _render_rag_result(_console(), result, show_trace=show_trace)
    except (
        DocumentEnhancerError,
        FileNotFoundError,
        ImportError,
        RuntimeError,
        ValueError,
    ) as error:
        _fail(error)
        raise typer.Exit(20) from error


@rag_app.command("chat")
def rag_chat(
    run_ids: Annotated[list[str] | None, typer.Option("--run")] = None,
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    scope: Annotated[str, typer.Option("--scope", help="auto, focused, or corpus")] = "auto",
    coverage: Annotated[
        str,
        typer.Option("--coverage", help="retrieval or exhaustive; exhaustive scans every chunk."),
    ] = "retrieval",
    show_trace: Annotated[bool, typer.Option("--show-trace")] = False,
) -> None:
    """Open a bounded in-memory Rich conversation over the local catalog."""

    try:
        from .retrieval.agent import RagAnswerer, gemini_chat_model
        from .retrieval.corpus import AdaptiveRagAnswerer
        from .retrieval.models import CorpusResult

        _load_project_env()
        config = load_config()
        catalog_path = (catalog or config.rag.catalog_dir).expanduser()
        console = _console()
        history: list[tuple[str, str]] = []
        last_result: object | None = None
        console.print(
            Panel(
                "Ask about the selected sealed documents. Commands: [bold]/sources[/], "
                "[bold]/trace[/], [bold]/clear[/], [bold]/help[/], [bold]/exit[/].",
                title="[bold bright_cyan]Document Enhancer RAG[/]",
                border_style="cyan",
            )
        )
        with _open_rag_catalog(catalog_path) as opened:
            answerer = AdaptiveRagAnswerer(
                opened,
                gemini_chat_model(config),
                focused_factory=RagAnswerer,
            )
            while True:
                try:
                    question = typer.prompt("You").strip()
                except (EOFError, KeyboardInterrupt, typer.Abort):
                    console.print("\n[bright_black]Conversation closed.[/]")
                    break
                if not question:
                    continue
                command = question.lower()
                if command == "/exit":
                    break
                if command == "/clear":
                    history.clear()
                    last_result = None
                    console.print("[green]Conversation context cleared.[/]")
                    continue
                if command == "/help":
                    console.print("/sources  /trace  /clear  /help  /exit")
                    continue
                if command in {"/sources", "/trace"}:
                    if last_result is None:
                        console.print("[yellow]Ask a question first.[/]")
                    else:
                        _render_rag_result(
                            console,
                            last_result,
                            show_trace=command == "/trace" or show_trace,
                        )
                    continue
                with console.status("[bold cyan]Retrieving grounded evidence…[/]"):
                    result = answerer.answer(
                        question,
                        run_ids=run_ids,
                        history=history,
                        scope=cast(Any, scope),
                        coverage=cast(Any, coverage),
                    )
                _render_rag_result(console, result, show_trace=show_trace)
                if isinstance(result, CorpusResult):
                    assistant_text = "; ".join(item.statement for item in result.items[:8])
                else:
                    assistant_text = (
                        " ".join(claim.text for claim in result.claims)
                        if result.status == "answered"
                        else "Insufficient evidence."
                    )
                history.append((question, assistant_text))
                history = history[-4:]
                last_result = result
    except (
        DocumentEnhancerError,
        FileNotFoundError,
        ImportError,
        RuntimeError,
        ValueError,
    ) as error:
        _fail(error)
        raise typer.Exit(20) from error


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
