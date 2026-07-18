from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from document_enhancer.cli import app
from document_enhancer.retrieval.models import (
    AnswerClaim,
    AnswerResult,
    SourceCitation,
    TraceEvent,
)

from .helpers import write_bundle

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
def test_rag_index_and_inspect_json_cli(tmp_path: Path) -> None:
    write_bundle(
        tmp_path / "runs",
        "run-cli",
        "# CLI Document\n\n## Overview\n\nThe owner reviews the control monthly.\n",
    )
    catalog = tmp_path / "catalog"

    indexed = runner.invoke(
        app,
        [
            "rag",
            "index",
            "run-cli",
            "--run-dir",
            str(tmp_path / "runs"),
            "--catalog",
            str(catalog),
            "--offline",
            "--json",
        ],
    )
    inspected = runner.invoke(app, ["rag", "inspect", "--catalog", str(catalog), "--json"])

    assert indexed.exit_code == 0, indexed.output
    index_payload = json.loads(indexed.stdout)
    assert index_payload["counts"]["bundles"] == 1
    assert index_payload["selection"] == {
        "mode": "explicit",
        "rejected": 0,
        "run_ids": ["run-cli"],
        "selected": 1,
    }
    assert inspected.exit_code == 0, inspected.output
    payload = json.loads(inspected.stdout)
    assert payload["schema_version"] == "document-enhancer.rag.catalog.v1"
    assert payload["embedding_profile"]["provider"] == "offline"
    assert "\x1b[" not in inspected.stdout


@pytest.mark.unit
def test_rag_ask_rich_and_json_render_validated_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bundle(
        tmp_path / "runs",
        "run-cli",
        "# CLI Document\n\n## Overview\n\nThe owner reviews the control monthly.\n",
    )
    catalog = tmp_path / "catalog"
    indexed = runner.invoke(
        app,
        [
            "rag",
            "index",
            "run-cli",
            "--run-dir",
            str(tmp_path / "runs"),
            "--catalog",
            str(catalog),
            "--offline",
            "--json",
        ],
    )
    assert indexed.exit_code == 0

    source = SourceCitation(
        evidence_id="E1",
        chunk_id="CHK-CLI",
        run_id="run-cli",
        document_title="CLI Document",
        heading_path=("CLI Document", "Overview"),
        bundle_path=str(tmp_path / "runs" / "run-cli"),
    )
    answer = AnswerResult(
        status="answered",
        claims=(AnswerClaim(text="The owner reviews it monthly.", citation_ids=("E1",)),),
        sources=(source,),
        trace=(TraceEvent(tool="search_evidence", input={"query": "owner"}, evidence_ids=("E1",)),),
    )

    class FakeAnswerer:
        def __init__(self, catalog: object, model: object) -> None:
            assert catalog and model

        def answer(self, question: str, **_: object) -> AnswerResult:
            assert question
            return answer

    import document_enhancer.retrieval.agent as agent_module

    monkeypatch.setattr(agent_module, "RagAnswerer", FakeAnswerer)
    monkeypatch.setattr(agent_module, "gemini_chat_model", lambda config: object())

    rich = runner.invoke(
        app,
        ["rag", "ask", "Who reviews it?", "--catalog", str(catalog), "--show-trace"],
    )
    machine = runner.invoke(
        app,
        ["rag", "ask", "Who reviews it?", "--catalog", str(catalog), "--json"],
    )

    assert rich.exit_code == 0, rich.output
    assert "The owner reviews it monthly" in rich.stdout
    assert "[S1]" in rich.stdout
    assert "Sources" in rich.stdout
    assert "Retrieval trace" in rich.stdout
    assert machine.exit_code == 0
    assert json.loads(machine.stdout)["sources"][0]["run_id"] == "run-cli"


@pytest.mark.unit
def test_rag_ask_renders_insufficient_without_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bundle(tmp_path / "runs", "run-cli", "# Doc\n\n## Overview\n\nEvidence.\n")
    catalog = tmp_path / "catalog"
    assert (
        runner.invoke(
            app,
            [
                "rag",
                "index",
                "run-cli",
                "--run-dir",
                str(tmp_path / "runs"),
                "--catalog",
                str(catalog),
                "--offline",
                "--json",
            ],
        ).exit_code
        == 0
    )
    import document_enhancer.retrieval.agent as agent_module

    class FakeAnswerer:
        def __init__(self, catalog: object, model: object) -> None:
            assert catalog and model

        def answer(self, question: str, **_: object) -> AnswerResult:
            return AnswerResult(status="insufficient", claims=(), sources=(), trace=())

    monkeypatch.setattr(agent_module, "RagAnswerer", FakeAnswerer)
    monkeypatch.setattr(agent_module, "gemini_chat_model", lambda config: object())

    result = runner.invoke(app, ["rag", "ask", "Unknown?", "--catalog", str(catalog)])

    assert result.exit_code == 0, result.output
    assert "Insufficient evidence" in result.stdout
    assert "Sources" not in result.stdout


@pytest.mark.unit
def test_rag_chat_supports_all_slash_commands_and_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_bundle(tmp_path / "runs", "run-cli", "# Doc\n\n## Overview\n\nEvidence.\n")
    catalog = tmp_path / "catalog"
    assert (
        runner.invoke(
            app,
            [
                "rag",
                "index",
                "run-cli",
                "--run-dir",
                str(tmp_path / "runs"),
                "--catalog",
                str(catalog),
                "--offline",
                "--json",
            ],
        ).exit_code
        == 0
    )
    import document_enhancer.retrieval.agent as agent_module

    answer = AnswerResult(
        status="answered",
        claims=(AnswerClaim(text="Grounded answer.", citation_ids=("E1",)),),
        sources=(
            SourceCitation(
                evidence_id="E1",
                chunk_id="CHK-CHAT",
                run_id="run-cli",
                document_title="Doc",
                heading_path=("Doc", "Overview"),
                bundle_path=str(tmp_path / "runs" / "run-cli"),
            ),
        ),
        trace=(TraceEvent(tool="search_evidence", input={"query": "Evidence"}),),
    )

    class FakeAnswerer:
        def __init__(self, catalog: object, model: object) -> None:
            assert catalog and model

        def answer(self, question: str, **_: object) -> AnswerResult:
            assert question == "What is documented?"
            return answer

    monkeypatch.setattr(agent_module, "RagAnswerer", FakeAnswerer)
    monkeypatch.setattr(agent_module, "gemini_chat_model", lambda config: object())
    result = runner.invoke(
        app,
        ["rag", "chat", "--catalog", str(catalog)],
        input=("/sources\n/help\nWhat is documented?\n/sources\n/trace\n/clear\n/sources\n/exit\n"),
    )

    assert result.exit_code == 0, result.output
    transcript = (ROOT / "fixtures/rag/chat_transcript.txt").read_text(encoding="utf-8")
    assert all(line in result.stdout for line in transcript.splitlines())
    assert result.stdout.count("Ask a question first") == 2


@pytest.mark.unit
@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_rag_chat_closes_cleanly_on_eof_and_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: type[BaseException],
) -> None:
    write_bundle(tmp_path / "runs", "run-cli", "# Doc\n\n## Overview\n\nEvidence.\n")
    catalog = tmp_path / "catalog"
    assert (
        runner.invoke(
            app,
            [
                "rag",
                "index",
                "run-cli",
                "--run-dir",
                str(tmp_path / "runs"),
                "--catalog",
                str(catalog),
                "--offline",
                "--json",
            ],
        ).exit_code
        == 0
    )
    import document_enhancer.retrieval.agent as agent_module

    monkeypatch.setattr(agent_module, "gemini_chat_model", lambda config: object())
    monkeypatch.setattr(
        "typer.prompt", lambda *_args, **_kwargs: (_ for _ in ()).throw(interruption)
    )

    result = runner.invoke(app, ["rag", "chat", "--catalog", str(catalog)])

    assert result.exit_code == 0, result.output
    assert "Conversation closed" in result.stdout
