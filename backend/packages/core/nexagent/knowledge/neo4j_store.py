"""Optional Neo4j synchronization for knowledge graphs."""

from __future__ import annotations

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Neo4jGraphStore:
    """Thin Neo4j writer for LocalGraphStore exports."""

    def __init__(self) -> None:
        from nexagent.config import get_config

        cfg = get_config().knowledge
        self.uri = cfg.neo4j_uri
        self.user = cfg.neo4j_user
        self.password = cfg.neo4j_password

    @contextmanager
    def _driver(self):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError("neo4j package is not installed") from exc

        driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        try:
            yield driver
        finally:
            driver.close()

    def ping(self) -> dict:
        with self._driver() as driver:
            driver.verify_connectivity()
        return {"status": "ok", "uri": self.uri}

    def sync(self, kb_id: str, graph_data: dict) -> dict:
        """Upsert graph nodes and co-occurrence edges into Neo4j."""
        with self._driver() as driver:
            with driver.session() as session:
                session.run(
                    "CREATE CONSTRAINT nexagent_entity_id IF NOT EXISTS "
                    "FOR (n:NexAgentEntity) REQUIRE n.id IS UNIQUE"
                )
                for node in graph_data.get("nodes", []):
                    session.run(
                        """
                        MERGE (n:NexAgentEntity {id: $id})
                        SET n.name = $name,
                            n.kb_id = $kb_id,
                            n.count = $count,
                            n.files = $files
                        """,
                        id=f"{kb_id}:{node['name']}",
                        name=node["name"],
                        kb_id=kb_id,
                        count=node.get("count", 0),
                        files=node.get("files", []),
                    )
                for edge in graph_data.get("edges", []):
                    session.run(
                        """
                        MATCH (s:NexAgentEntity {id: $source_id})
                        MATCH (t:NexAgentEntity {id: $target_id})
                        MERGE (s)-[r:NEXAGENT_RELATION {kb_id: $kb_id, relation: $relation}]->(t)
                        SET r.count = $count,
                            r.files = $files
                        """,
                        source_id=f"{kb_id}:{edge['source']}",
                        target_id=f"{kb_id}:{edge['target']}",
                        kb_id=kb_id,
                        relation=edge.get("relation", "co_occurs"),
                        count=edge.get("count", 0),
                        files=edge.get("files", []),
                    )
        return {
            "status": "ok",
            "synced_nodes": len(graph_data.get("nodes", [])),
            "synced_edges": len(graph_data.get("edges", [])),
        }

    def delete_kb(self, kb_id: str) -> None:
        with self._driver() as driver:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (n:NexAgentEntity {kb_id: $kb_id})
                    DETACH DELETE n
                    """,
                    kb_id=kb_id,
                )

    def export_kb(self, kb_id: str, limit: int = 200) -> dict:
        """Export semantic graph records for a KB from Neo4j.

        Supports both NexAgent's normalized labels and LightRAG/Neo4j
        properties when present. Local co-occurrence data is not generated here;
        callers should report degraded status if this export is empty.
        """
        with self._driver() as driver:
            with driver.session() as session:
                node_rows = session.run(
                    """
                    MATCH (n)
                    WHERE n.kb_id = $kb_id OR n.workspace = $kb_id OR n.source_id = $kb_id
                    RETURN n
                    LIMIT $limit
                    """,
                    kb_id=kb_id,
                    limit=limit,
                )
                nodes = []
                for row in node_rows:
                    node = dict(row["n"])
                    name = str(node.get("name") or node.get("entity_id") or node.get("id") or "")
                    if not name:
                        continue
                    nodes.append(
                        {
                            "id": str(node.get("id") or node.get("entity_id") or name),
                            "name": name,
                            "entity_type": node.get("entity_type") or node.get("type") or "entity",
                            "description": node.get("description") or "",
                            "count": int(node.get("count") or node.get("mentions") or 1),
                            "source_chunks": _as_list(node.get("source_chunks") or node.get("chunks")),
                            "source_files": _as_list(node.get("source_files") or node.get("files")),
                        }
                    )
                edge_rows = session.run(
                    """
                    MATCH (s)-[r]->(t)
                    WHERE r.kb_id = $kb_id OR r.workspace = $kb_id
                       OR s.kb_id = $kb_id OR t.kb_id = $kb_id
                       OR s.workspace = $kb_id OR t.workspace = $kb_id
                    RETURN s, r, t
                    LIMIT $limit
                    """,
                    kb_id=kb_id,
                    limit=limit,
                )
                edges = []
                for index, row in enumerate(edge_rows):
                    source = dict(row["s"])
                    rel = dict(row["r"])
                    target = dict(row["t"])
                    source_name = str(source.get("name") or source.get("entity_id") or source.get("id") or "")
                    target_name = str(target.get("name") or target.get("entity_id") or target.get("id") or "")
                    if not source_name or not target_name:
                        continue
                    relation = rel.get("relation") or rel.get("keywords") or row["r"].type
                    if isinstance(relation, list):
                        relation = ", ".join(str(item) for item in relation)
                    edges.append(
                        {
                            "id": str(rel.get("id") or f"{source_name}:{relation}:{target_name}:{index}"),
                            "source": source_name,
                            "target": target_name,
                            "relation": str(relation or "related_to"),
                            "keywords": _as_list(rel.get("keywords")),
                            "weight": float(rel.get("weight") or rel.get("count") or 1),
                            "description": rel.get("description") or "",
                            "source_chunks": _as_list(rel.get("source_chunks") or rel.get("chunks")),
                            "source_files": _as_list(rel.get("source_files") or rel.get("files")),
                        }
                    )
        return {"nodes": nodes, "edges": edges, "stats": {"nodes": len(nodes), "edges": len(edges), "files": []}}


def try_sync_to_neo4j(kb_id: str, graph_data: dict) -> dict:
    try:
        return Neo4jGraphStore().sync(kb_id, graph_data)
    except Exception as exc:
        logger.info("Neo4j sync skipped for KB %s: %s", kb_id, exc)
        return {"status": "skipped", "reason": str(exc)}


def neo4j_status() -> dict:
    try:
        return Neo4jGraphStore().ping()
    except Exception as exc:
        return {"status": "unavailable", "reason": str(exc)}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    return [str(value)]
