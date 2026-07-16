from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from document_enhancer.cli import app

from .helpers import catalog_with_documents

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def test_rag_search_ask_graph_stats_json_and_non_tty_snapshots(tmp_path: Path) -> None:
    catalog = catalog_with_documents(tmp_path)
    search = runner.invoke(
        app,
        [
            "rag",
            "search",
            "monthly cobalt review",
            "--catalog",
            str(catalog),
            "--offline",
            "--explain",
            "--json",
        ],
    )
    assert search.exit_code == 0, search.output
    assert not ANSI.search(search.stdout)
    search_payload = json.loads(search.stdout)
    assert search_payload["hits"]
    assert search_payload["diagnostics"]["channel_counts"]["lexical"] >= 1
    assert search_payload["hits"][0]["channel_ranks"]

    ask = runner.invoke(
        app,
        [
            "rag",
            "ask",
            "Who records the monthly cobalt review?",
            "--catalog",
            str(catalog),
            "--offline",
            "--explain",
            "--json",
        ],
    )
    assert ask.exit_code == 0, ask.output
    ask_payload = json.loads(ask.stdout)
    assert ask_payload["grounding"]["passed"] is True
    assert ask_payload["answer"]["citations"]
    assert ask_payload["retrieval"]["diagnostics"]["stages"][-1] == "finish"

    connection = sqlite3.connect(catalog)
    entity = str(
        connection.execute("SELECT node_id FROM graph_nodes ORDER BY node_id LIMIT 1").fetchone()[0]
    )
    connection.close()
    graph = runner.invoke(
        app,
        ["rag", "graph", entity, "--catalog", str(catalog), "--depth", "2", "--json"],
    )
    assert graph.exit_code == 0, graph.output
    assert json.loads(graph.stdout)["depth"] == 2

    stats = runner.invoke(app, ["rag", "stats", "--catalog", str(catalog), "--json"])
    assert stats.exit_code == 0, stats.output
    assert json.loads(stats.stdout)["catalog_generation"] == 2

    human = runner.invoke(
        app,
        [
            "--no-color",
            "rag",
            "search",
            "monthly review",
            "--catalog",
            str(catalog),
            "--offline",
            "--explain",
        ],
        env={"NO_COLOR": "1"},
    )
    assert human.exit_code == 0, human.output
    assert "Hybrid retrieval" in human.stdout
    assert "Retrieval explanation" in human.stdout
    assert not ANSI.search(human.stdout)


def test_rag_chat_session_slash_commands_sources_and_stable_json(tmp_path: Path) -> None:
    catalog = catalog_with_documents(tmp_path, count=1)
    chat = runner.invoke(
        app,
        [
            "rag",
            "chat",
            "--catalog",
            str(catalog),
            "--session",
            "SES-CLI-001",
            "--offline",
            "--json",
        ],
        input="Who records the monthly cobalt review?\n/sources\n/filters\n/session\n/exit\n",
    )
    assert chat.exit_code == 0, chat.output
    assert not ANSI.search(chat.stdout)
    payload = json.loads(chat.stdout)
    assert payload["schema_version"] == "m7.rag-chat.v1"
    assert payload["session_id"] == "SES-CLI-001"
    assert payload["saved"] is True
    assert len(payload["turns"]) == 1
    answer_id = payload["turns"][0]["answer"]["answer_id"]

    sources = runner.invoke(
        app,
        ["rag", "sources", answer_id, "--catalog", str(catalog), "--json"],
    )
    assert sources.exit_code == 0, sources.output
    source_payload = json.loads(sources.stdout)
    assert source_payload["sources"][0]["citation"]["citation_id"].startswith("CIT-")

    stats = runner.invoke(app, ["rag", "stats", "--catalog", str(catalog), "--json"])
    stats_payload = json.loads(stats.stdout)
    assert stats_payload["sessions"] == 1
    assert stats_payload["saved_queries"] == 1
    assert stats_payload["saved_answers"] == 1


def test_rag_cli_abstains_and_rejects_ambiguous_save_policy(tmp_path: Path) -> None:
    catalog = catalog_with_documents(tmp_path, count=1)
    ask = runner.invoke(
        app,
        [
            "rag",
            "ask",
            "What is the violet satellite launch mass?",
            "--catalog",
            str(catalog),
            "--offline",
            "--json",
        ],
    )
    assert ask.exit_code == 0, ask.output
    assert json.loads(ask.stdout)["answer"]["status"] == "insufficient"

    invalid = runner.invoke(
        app,
        [
            "rag",
            "chat",
            "--catalog",
            str(catalog),
            "--session",
            "SES-CLI-002",
            "--no-save",
            "--offline",
        ],
    )
    assert invalid.exit_code == 30
    assert "cannot be combined" in invalid.stderr
