"""Verify Phase 3 knowledge base and knowledge graph workflows."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
CORE_DIR = BACKEND_DIR / "packages" / "core"


def _configure_runtime() -> Path:
    for path in (BACKEND_DIR, CORE_DIR):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)

    data_dir = PROJECT_ROOT / ".nexagent" / "verify_phase3"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["NEXAGENT_DATA_DIR"] = str(data_dir)
    os.environ["NEXAGENT_FORCE_LOCAL_KB_FALLBACK"] = "1"
    os.environ["NEXAGENT_DISABLE_NEO4J_SYNC"] = "1"
    os.environ["NEXAGENT_SKIP_NATIVE_LIGHTRAG"] = "1"
    os.environ.setdefault("NEXAGENT_DEFAULT_MODEL", "fake")
    return data_dir


def _ok(message: str) -> None:
    print(f"[ok] {message}")


def _fail(message: str) -> None:
    raise AssertionError(message)


async def verify_milvus_rag(manager) -> str:
    kb = await manager.create_kb(
        name="Phase 3 RAG",
        description="Local fallback vector RAG verification",
        kb_type="milvus",
        chunk_size=160,
        chunk_overlap=20,
    )
    file = await manager.add_file(
        kb.kb_id,
        "nexagent-rag.txt",
        (
            "NexAgent combines flexible agent orchestration with first-class knowledge bases. "
            "The RAG layer indexes uploaded documents and retrieves relevant passages."
        ).encode("utf-8"),
    )
    parsed = await manager.parse_file(kb.kb_id, file.file_id)
    if parsed.status.value != "parsed":
        _fail(f"expected parsed status, got {parsed.status}")
    indexed = await manager.index_file(kb.kb_id, file.file_id)
    if indexed.status.value != "indexed" or indexed.chunk_count < 1:
        _fail(f"expected indexed file with chunks, got {indexed.to_dict()}")
    results = await manager.search(kb.kb_id, "NexAgent RAG uploaded documents", top_k=3)
    if not results:
        _fail("Milvus/local RAG search returned no results")
    _ok("Milvus RAG workflow works with local fallback")
    return kb.kb_id


async def verify_lightrag_graph(manager) -> str:
    kb = await manager.create_kb(
        name="Phase 3 Graph",
        description="Local LightRAG graph verification",
        kb_type="lightrag",
        chunk_size=160,
        chunk_overlap=20,
    )
    file = await manager.add_file(
        kb.kb_id,
        "nexagent-graph.md",
        (
            "# NexAgent Graph\n\n"
            "NexAgent unifies orchestration and retrieval. The agent layer plans and executes tasks. "
            "The knowledge layer provides KnowledgeBase and KnowledgeGraph capabilities."
        ).encode("utf-8"),
    )
    await manager.parse_file(kb.kb_id, file.file_id)
    indexed = await manager.index_file(kb.kb_id, file.file_id)
    if indexed.status.value != "indexed":
        _fail(f"expected graph file indexed, got {indexed.to_dict()}")

    stats = manager.graph_stats(kb.kb_id)
    if stats["local"]["nodes"] < 1:
        _fail(f"expected graph nodes, got {stats}")
    exported = manager.export_graph(kb.kb_id)
    if not exported["nodes"]:
        _fail(f"expected exported graph nodes, got {exported}")
    results = await manager.search(kb.kb_id, "DeerFlow NexAgent", top_k=3)
    if not results:
        _fail("LightRAG/local graph search returned no results")
    _ok("LightRAG knowledge graph workflow works with local fallback")
    return kb.kb_id


def verify_graph_upload(manager, kb_id: str) -> None:
    result = manager.import_graph(
        kb_id,
        {
            "nodes": [
                {"name": "ExternalSystem", "count": 2},
                {"name": "NexAgent", "count": 1},
            ],
            "edges": [
                {
                    "source": "ExternalSystem",
                    "target": "NexAgent",
                    "relation": "feeds",
                    "count": 1,
                }
            ],
        },
        source="verify_phase3",
    )
    if result["imported_nodes"] < 2 or result["imported_edges"] < 1:
        _fail(f"graph import failed: {result}")
    exported = manager.export_graph(kb_id)
    node_names = {node["name"] for node in exported["nodes"]}
    if "ExternalSystem" not in node_names:
        _fail(f"imported graph node missing: {exported}")
    _ok("manual graph upload service works")


def verify_skills_and_middleware() -> None:
    from nexagent.agents.middlewares.knowledge_middleware import make_query_kb_tool
    from nexagent.skills.loader import SkillLoader

    skills = set(SkillLoader().discover())
    for skill in ("knowledge-base", "knowledge-graph"):
        if skill not in skills:
            _fail(f"missing Phase 3 skill: {skill}")
    tool = make_query_kb_tool(["kb-example"])
    if tool.name != "query_kb":
        _fail("knowledge middleware tool was not created")
    _ok("knowledge skills and middleware are available")


def verify_http_routes() -> None:
    from fastapi.testclient import TestClient

    from app.gateway.app import app

    client = TestClient(app)
    response = client.get("/api/knowledge/status")
    if response.status_code != 200:
        _fail(f"GET /api/knowledge/status returned {response.status_code}: {response.text}")
    payload = response.json()
    if payload.get("status") != "ok":
        _fail(f"unexpected knowledge status payload: {payload}")
    _ok("knowledge HTTP status route responds")


async def main_async() -> int:
    data_dir = _configure_runtime()
    from nexagent.knowledge.manager import reset_manager

    manager = reset_manager(str(data_dir / "knowledge"))
    await verify_milvus_rag(manager)
    graph_kb_id = await verify_lightrag_graph(manager)
    verify_graph_upload(manager, graph_kb_id)
    verify_skills_and_middleware()
    verify_http_routes()
    print("Phase 3 verification passed.")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
