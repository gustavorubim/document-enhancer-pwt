"""Explicit SQLite chat-session persistence without hidden reasoning."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from document_enhancer.domain.ids import validate_identifier

from .migrations import connect, migrate
from .models import ChatMessage, RagRunResult, RetrievalFilters


class SessionError(RuntimeError):
    """A saved session cannot be opened or safely advanced."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _id(prefix: str, seed: str | None = None) -> str:
    token = (
        hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
        if seed is not None
        else secrets.token_hex(10)
    )
    return f"{prefix}-{token.upper()}"


class SessionStore:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path.expanduser().resolve()

    def _connect(self):
        if not self.catalog_path.is_file():
            raise SessionError(f"catalog does not exist: {self.catalog_path}")
        connection = connect(str(self.catalog_path), catalog=True)
        migrate(connection)
        return connection

    def current_generation(self) -> int:
        connection = self._connect()
        try:
            return int(
                connection.execute(
                    "SELECT COALESCE(MAX(generation), 0) FROM catalog_generations"
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def open(
        self,
        session_id: str | None = None,
        *,
        filters: RetrievalFilters | None = None,
    ) -> tuple[str, RetrievalFilters]:
        session_id = session_id or _id("SES")
        validate_identifier(session_id, label="session id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM rag_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row:
                stored = RetrievalFilters.model_validate_json(str(row["filters_json"]))
                pinned = int(row["catalog_generation"])
                if stored.catalog_generation not in {None, pinned}:
                    raise SessionError("saved session filter generation does not match its pin")
                return session_id, stored.model_copy(update={"catalog_generation": pinned})
            generation = int(
                connection.execute(
                    "SELECT COALESCE(MAX(generation), 0) FROM catalog_generations"
                ).fetchone()[0]
            )
            if generation < 1:
                raise SessionError("cannot create a session before a catalog generation exists")
            selected = (filters or RetrievalFilters()).model_copy(
                update={"catalog_generation": generation}
            )
            now = _now()
            with connection:
                connection.execute(
                    "INSERT INTO rag_sessions VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        generation,
                        selected.model_dump_json(),
                        now,
                        now,
                    ),
                )
            self.catalog_path.chmod(0o600)
            return session_id, selected
        finally:
            connection.close()

    def refresh(self, session_id: str) -> RetrievalFilters:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT filters_json FROM rag_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None:
                raise SessionError(f"unknown session: {session_id}")
            generation = int(
                connection.execute("SELECT MAX(generation) FROM catalog_generations").fetchone()[0]
            )
            filters = RetrievalFilters.model_validate_json(str(row["filters_json"])).model_copy(
                update={"catalog_generation": generation}
            )
            with connection:
                connection.execute(
                    "UPDATE rag_sessions SET catalog_generation=?, filters_json=?, updated_at=? WHERE session_id=?",
                    (generation, filters.model_dump_json(), _now(), session_id),
                )
            return filters
        finally:
            connection.close()

    def history(self, session_id: str) -> tuple[ChatMessage, ...]:
        connection = self._connect()
        try:
            return tuple(
                ChatMessage(
                    role=cast(Literal["user", "assistant"], str(row["role"])),
                    content=str(row["content"]),
                )
                for row in connection.execute(
                    """SELECT role, content FROM rag_messages WHERE session_id=?
                       ORDER BY created_at,
                                CASE role WHEN 'user' THEN 0 ELSE 1 END,
                                message_id""",
                    (session_id,),
                )
            )
        finally:
            connection.close()

    def save_exchange(self, session_id: str, question: str, result: RagRunResult) -> None:
        answer = result.answer
        generation = result.retrieval.diagnostics.catalog_generation
        selected = set(result.retrieval.diagnostics.selected_context_ids)
        connection = self._connect()
        try:
            session = connection.execute(
                "SELECT catalog_generation FROM rag_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if session is None:
                raise SessionError(f"unknown session: {session_id}")
            if int(session[0]) != generation:
                raise SessionError(
                    "session catalog generation differs from retrieval; refresh or reopen explicitly"
                )
            now = _now()
            diagnostics = result.retrieval.diagnostics.model_dump(mode="json")
            with connection:
                connection.execute(
                    """INSERT INTO rag_queries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        answer.query_id,
                        session_id,
                        question,
                        result.rewritten_query,
                        generation,
                        result.retrieval.diagnostics.embedding_profile,
                        result.retrieval.diagnostics.filters.model_dump_json(),
                        _canonical(diagnostics),
                        answer.status.value,
                        now,
                    ),
                )
                for hit in result.retrieval.hits:
                    connection.execute(
                        "INSERT INTO rag_retrieval_hits VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            answer.query_id,
                            hit.chunk_id,
                            hit.rank,
                            hit.fused_score,
                            _canonical(hit.channel_ranks),
                            _canonical(hit.channel_scores),
                            _canonical(
                                [
                                    [step.model_dump(mode="json") for step in path]
                                    for path in hit.graph_paths
                                ]
                            ),
                            int(hit.chunk_id in selected),
                        ),
                    )
                connection.execute(
                    "INSERT INTO rag_answers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        answer.answer_id,
                        answer.query_id,
                        answer.answer_markdown,
                        answer.status.value,
                        int(result.grounding.passed),
                        _canonical(answer.caveats),
                        _canonical(answer.unsupported_claims),
                        answer.model_route,
                        now,
                    ),
                )
                for citation in answer.citations:
                    connection.execute(
                        "INSERT INTO rag_answer_citations VALUES (?, ?, ?, ?)",
                        (
                            answer.answer_id,
                            citation.citation_id,
                            citation.chunk_id,
                            citation.model_dump_json(),
                        ),
                    )
                connection.executemany(
                    "INSERT INTO rag_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            _id("MSG"),
                            session_id,
                            "user",
                            question,
                            answer.query_id,
                            None,
                            "[]",
                            "{}",
                            now,
                        ),
                        (
                            _id("MSG"),
                            session_id,
                            "assistant",
                            answer.answer_markdown,
                            answer.query_id,
                            answer.answer_id,
                            _canonical(
                                [citation.model_dump(mode="json") for citation in answer.citations]
                            ),
                            _canonical({"model_route": answer.model_route}),
                            now,
                        ),
                    ],
                )
                connection.execute(
                    "UPDATE rag_sessions SET updated_at=? WHERE session_id=?", (now, session_id)
                )
        finally:
            connection.close()

    def clear(self, session_id: str) -> None:
        connection = self._connect()
        try:
            if (
                connection.execute(
                    "SELECT 1 FROM rag_sessions WHERE session_id=?", (session_id,)
                ).fetchone()
                is None
            ):
                raise SessionError(f"unknown session: {session_id}")
            with connection:
                connection.execute("DELETE FROM rag_queries WHERE session_id=?", (session_id,))
                connection.execute("DELETE FROM rag_messages WHERE session_id=?", (session_id,))
                connection.execute(
                    "UPDATE rag_sessions SET updated_at=? WHERE session_id=?", (_now(), session_id)
                )
        finally:
            connection.close()

    def sources(self, identifier: str) -> tuple[dict[str, object], ...]:
        connection = self._connect()
        try:
            answer_id = identifier
            if identifier.startswith("SES-"):
                row = connection.execute(
                    """SELECT answer_id FROM rag_messages
                       WHERE session_id=? AND role='assistant' AND answer_id IS NOT NULL
                       ORDER BY created_at DESC, message_id DESC LIMIT 1""",
                    (identifier,),
                ).fetchone()
                if row is None:
                    return ()
                answer_id = str(row[0])
            rows = connection.execute(
                """SELECT rac.citation_json, c.text, c.section_path, d.canonical_title
                   FROM rag_answer_citations rac
                   JOIN chunks c ON c.chunk_id=rac.chunk_id
                   JOIN documents d ON d.document_id=c.document_id
                   WHERE rac.answer_id=? ORDER BY rac.citation_id""",
                (answer_id,),
            )
            return tuple(
                {
                    "citation": json.loads(str(row["citation_json"])),
                    "title": str(row["canonical_title"]),
                    "section_path": str(row["section_path"]),
                    "text": str(row["text"]),
                }
                for row in rows
            )
        finally:
            connection.close()


__all__ = ["SessionError", "SessionStore"]
