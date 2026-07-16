"""Typer CLI for the WT0 foundation."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from rich.console import Console

from . import __version__
from .config import config_as_public_dict, load_config
from .doctor import doctor_json, run_doctor
from .errors import DocumentEnhancerError
from .logging import configure_logging, get_logger

app = typer.Typer(
    name="docenhance",
    help="Governed, local-first document enhancement.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Inspect non-secret configuration.")
app.add_typer(config_app, name="config")
console = Console()
logger = get_logger("cli")


def _emit_error(error: DocumentEnhancerError) -> None:
    typer.echo(f"error: {error.message}", err=True)
    if error.detail:
        logger.debug("error detail: %s", error.detail)


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


def main() -> None:
    """Console-script entry point with safe error conversion."""

    try:
        app()
    except DocumentEnhancerError as error:
        _emit_error(error)
        raise typer.Exit(int(error.exit_code)) from error
