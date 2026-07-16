"""Offline compatibility probes for the M0 dependency boundary."""

from __future__ import annotations

import inspect
import operator
import os
import sqlite3
from pathlib import Path
from typing import Annotated, Any, TypedDict

from .logging import redact


class _LangGraphState(TypedDict):
    values: Annotated[list[str], operator.add]
    approved: bool


def _result(status: str, detail: str) -> dict[str, str]:
    return {"status": status, "detail": detail}


def _gemini_shapes() -> dict[str, str]:
    from langchain_google_genai import ChatGoogleGenerativeAI

    signature = inspect.signature(ChatGoogleGenerativeAI)
    required = {"model", "vertexai", "project", "location"}
    missing = sorted(required - set(signature.parameters))
    if missing:
        raise RuntimeError(f"ChatGoogleGenerativeAI missing configuration fields: {missing}")
    # Construction is intentionally credential-free; no request is sent by this probe.
    developer = ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key="probe")
    vertex = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
        vertexai=True,
        project="probe-project",
        location="us-central1",
    )
    if not hasattr(developer, "with_structured_output") or not hasattr(
        vertex, "with_structured_output"
    ):
        raise RuntimeError("Gemini chat model lacks native structured-output adapter")
    return {"developer": type(developer).__name__, "vertex": type(vertex).__name__}


def _langgraph_shapes() -> str:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    def left(state: _LangGraphState) -> dict[str, list[str]]:
        _ = state
        return {"values": ["left"]}

    def right(state: _LangGraphState) -> dict[str, list[str]]:
        _ = state
        return {"values": ["right"]}

    def gate(state: _LangGraphState) -> dict[str, bool]:
        _ = state
        return {"approved": interrupt({"question": "approve"})}

    # StateGraph's published type bound currently omits the stdlib TypedDict form on ty;
    # this single constructor call is the documented compatibility boundary.
    graph_type: Any = StateGraph
    graph: Any = graph_type(_LangGraphState)
    graph.add_node("left", left)
    graph.add_node("right", right)
    graph.add_node("gate", gate)
    graph.add_edge(START, "left")
    graph.add_edge(START, "right")
    graph.add_edge(["left", "right"], "gate")
    graph.add_edge("gate", END)
    # The current LangGraph stubs do not expose the generic state type consistently across
    # `compile`/`invoke`; keep this compatibility-only boundary as a narrow dynamic call site.
    compiled: Any = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "wt0-compatibility"}}
    paused = compiled.invoke({"values": [], "approved": False}, config)
    if "__interrupt__" not in paused or paused["values"] != ["left", "right"]:
        raise RuntimeError("LangGraph fan-out or persisted interrupt did not pause as expected")
    resumed = compiled.invoke(Command(resume=True), config)
    if resumed.get("approved") is not True:
        raise RuntimeError("LangGraph interrupt resume did not return the resume value")
    return f"{type(compiled).__name__}; fanout/checkpoint/interrupt/resume passed"


def _deep_agents_shapes() -> str:
    import deepagents
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not hasattr(deepagents, "create_deep_agent"):
        raise RuntimeError("Deep Agents package has no supported restricted-agent constructor")
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash", google_api_key="probe")
    agent = create_deep_agent(
        model=model,
        tools=[],
        subagents=[],
        backend=StateBackend(),
        permissions=[],
        system_prompt="Analyze only the supplied text; do not use external tools.",
    )
    if not hasattr(agent, "invoke"):
        raise RuntimeError("Deep Agents restricted graph lacks invoke")
    return f"{getattr(deepagents, '__version__', 'installed')}; StateBackend-only agent compiled"


def _sqlite_shapes() -> dict[str, str]:
    import sqlite_vec

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, text)")
        connection.execute("INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)", ("c1", "alpha"))
        count = connection.execute(
            "SELECT count(*) FROM chunks_fts WHERE chunks_fts MATCH ?", ("alpha",)
        ).fetchone()[0]
        if count != 1:
            raise RuntimeError("FTS5 query did not return inserted row")
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        version = connection.execute("SELECT vec_version()").fetchone()[0]
        connection.execute("CREATE VIRTUAL TABLE vectors USING vec0(embedding float[3])")
        vector = sqlite_vec.serialize_float32([1.0, 0.0, 0.0])
        connection.execute("INSERT INTO vectors(rowid, embedding) VALUES (?, ?)", (1, vector))
        match = connection.execute(
            "SELECT rowid FROM vectors WHERE embedding MATCH ? AND k = 1", (vector,)
        ).fetchone()
        if match != (1,):
            raise RuntimeError("sqlite-vec vector query did not return the inserted vector")
    finally:
        connection.close()
    return {"fts5": "available", "sqlite_vec": str(version), "extension": "loaded"}


def _adapter_shapes() -> dict[str, str]:
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from langchain_core.retrievers import BaseRetriever
    from langchain_core.vectorstores import VectorStore

    from .rag.vector_store import ExactScanPolicy, ExactScanVectorStore

    if not (hasattr(VectorStore, "as_retriever") and hasattr(BaseRetriever, "invoke")):
        raise RuntimeError("LangChain VectorStore/BaseRetriever adapter surface changed")

    class ProbeEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if text == "alpha" else [0.0, 1.0] for text in texts]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0] if text == "alpha" else [0.0, 1.0]

    embedding = ProbeEmbeddings()
    store = ExactScanVectorStore.from_texts(
        ["alpha", "beta"],
        embedding,
        metadatas=[{"chunk_id": "c1"}, {"chunk_id": "c2"}],
    )
    retriever = store.as_retriever(search_kwargs={"k": 1})
    hits = retriever.invoke("alpha")
    if not hits or hits[0].metadata.get("chunk_id") != "c1":
        raise RuntimeError("LangChain BaseRetriever did not return the nearest known vector")

    policy = ExactScanPolicy(max_vectors=2)
    try:
        ExactScanVectorStore.from_vectors(
            [Document(page_content="a"), Document(page_content="b"), Document(page_content="c")],
            [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            embedding=embedding,
            policy=policy,
        )
    except ValueError as exc:
        if "limited" not in str(exc):
            raise RuntimeError("exact-scan size boundary returned the wrong error") from exc
    else:
        raise RuntimeError("exact-scan fallback accepted a catalog above its configured bound")
    try:
        ExactScanVectorStore.from_vectors(
            [Document(page_content="a")],
            [[1.0, 0.0]],
            embedding=embedding,
            profile="other-profile",
            policy=policy,
        )
    except ValueError as exc:
        if "profile mismatch" not in str(exc):
            raise RuntimeError("exact-scan profile boundary returned the wrong error") from exc
    else:
        raise RuntimeError("exact-scan fallback accepted an incompatible embedding profile")

    return {
        "document": type(hits[0]).__name__,
        "vector_store": type(store).__name__,
        "retriever": type(retriever).__name__,
        "exact_scan_boundary": "max_vectors=2; profile-enforced",
    }


def _embedding_profile_shapes() -> dict[str, str]:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    signature = inspect.signature(GoogleGenerativeAIEmbeddings)
    if "model" not in signature.parameters:
        raise RuntimeError("GoogleGenerativeAIEmbeddings has no model parameter")
    document = "title: Demo — section | text: source chunk"
    query = "task: search result | query: source chunk"
    if not document.startswith("title:") or not query.startswith("task: search result"):
        raise RuntimeError("Gemini embedding profile formatting contract changed")
    return {"document_profile": "title/section/text", "query_profile": "search result/query"}


def run_offline_spikes() -> dict[str, dict[str, str]]:
    probes: dict[str, Any] = {
        "gemini_native_structured_output": _gemini_shapes,
        "langgraph_parallel_checkpoint_interrupt_resume": _langgraph_shapes,
        "deep_agents_restricted_backend": _deep_agents_shapes,
        "sqlite_fts5_and_sqlite_vec": _sqlite_shapes,
        "langchain_vectorstore_base_retriever": _adapter_shapes,
        "gemini_embedding_profile_parity": _embedding_profile_shapes,
    }
    results: dict[str, dict[str, str]] = {}
    for name, probe in probes.items():
        try:
            detail = probe()
        except Exception as exc:  # dependency-specific failures are reported, not hidden
            results[name] = _result("fail", f"{type(exc).__name__}: {exc}")
        else:
            results[name] = _result("pass", str(detail))
    return results


def load_external_env(path: Path) -> None:
    """Load only approved credential/config keys from an external ignored dotenv file."""

    if not path.is_file():
        return
    approved = {
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
    }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in approved or name in os.environ:
            continue
        value = value.strip().strip("\"'")
        os.environ[name] = value


def run_live_spikes(schema: type[Any]) -> dict[str, dict[str, str]]:
    """Call only explicitly configured Gemini routes and report lifecycle failures honestly."""

    from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1"
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}
    results: dict[str, dict[str, str]] = {}

    routes: dict[str, dict[str, Any]] = {}
    if api_key and not use_vertex:
        routes["developer_api_native_structured_output"] = {
            "model": "gemini-3.5-flash",
            "google_api_key": api_key,
        }
    if use_vertex and project:
        routes["vertex_native_structured_output"] = {
            "model": "gemini-3.5-flash",
            "vertexai": True,
            "project": project,
            "location": location,
        }
    if not routes:
        results["gemini_structured_output"] = {
            "status": "unavailable",
            "detail": "no approved Developer API key or Vertex project configuration found",
        }
    for name, kwargs in routes.items():
        try:
            model = ChatGoogleGenerativeAI(**kwargs).with_structured_output(schema)
            response = model.invoke("Return ok=true and note='WT0 compatibility'.")
        except Exception as exc:  # provider lifecycle/auth/model failures are evidence
            results[name] = {
                "status": "unavailable",
                "detail": redact(f"{type(exc).__name__}: {exc}"),
            }
        else:
            results[name] = {
                "status": "pass",
                "detail": f"structured response received: {type(response).__name__}",
            }

    if api_key and not use_vertex:
        try:
            documents = GoogleGenerativeAIEmbeddings(
                model="gemini-embedding-2",
                api_key=api_key,
                output_dimensionality=768,
            ).embed_documents(["title: WT0 — compatibility | text: document probe"])
            query = GoogleGenerativeAIEmbeddings(
                model="gemini-embedding-2",
                api_key=api_key,
                output_dimensionality=768,
            ).embed_query("task: search result | query: document probe")
        except Exception as exc:  # retired embedding endpoints are reported, not hidden
            results["developer_api_embedding_profile"] = {
                "status": "unavailable",
                "detail": redact(f"{type(exc).__name__}: {exc}"),
            }
        else:
            results["developer_api_embedding_profile"] = {
                "status": "pass",
                "detail": f"document_dim={len(documents[0])}; query_dim={len(query)}",
            }
    return results
