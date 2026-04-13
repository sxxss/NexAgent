"""Local graph store for Phase 3 knowledge-graph verification.

Production deployments can use native LightRAG and Neo4j. This store keeps the
core graph workflow deterministic without external services.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_ENTITY_RE = re.compile(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_-]{1,31}")
_SENTENCE_RE = re.compile("[\n.!?;\u3002\uff01\uff1f\uff1b]+")
_LATIN_STOPWORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "that",
    "the",
    "this",
    "with",
}


@dataclass
class GraphNode:
    name: str
    count: int = 0
    files: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {"name": self.name, "count": self.count, "files": sorted(self.files)}

    @classmethod
    def from_dict(cls, data: dict) -> GraphNode:
        return cls(name=data["name"], count=int(data.get("count", 0)), files=set(data.get("files", [])))


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str = "co_occurs"
    count: int = 0
    files: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "relation": self.relation,
            "count": self.count,
            "files": sorted(self.files),
        }

    @classmethod
    def from_dict(cls, data: dict) -> GraphEdge:
        return cls(
            source=data["source"],
            target=data["target"],
            relation=data.get("relation", "co_occurs"),
            count=int(data.get("count", 0)),
            files=set(data.get("files", [])),
        )


class LocalGraphStore:
    """Small JSON-backed entity-relation graph."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self._load()

    def add_document(self, text: str, *, file_id: str, filename: str = "") -> int:
        entities = extract_entities(text)
        if not entities:
            self._save()
            return 0

        for name, count in Counter(entities).items():
            node = self.nodes.setdefault(name, GraphNode(name=name))
            node.count += count
            node.files.add(file_id or filename)

        seen_edges: set[tuple[str, str]] = set()
        for sentence in split_sentences(text):
            sentence_entities = unique_preserve_order(extract_entities(sentence))[:8]
            for index, source in enumerate(sentence_entities):
                for target in sentence_entities[index + 1 :]:
                    if source == target:
                        continue
                    seen_edges.add(tuple(sorted((source, target))))

        for source, target in seen_edges:
            key = f"{source}\tco_occurs\t{target}"
            edge = self.edges.setdefault(key, GraphEdge(source=source, target=target))
            edge.count += 1
            edge.files.add(file_id or filename)

        self._save()
        return len(entities)

    def import_graph(self, graph_data: dict, *, source: str = "manual") -> dict:
        """Merge externally supplied nodes and edges into the local graph."""
        imported_nodes = 0
        imported_edges = 0

        for raw_node in graph_data.get("nodes", []):
            name = str(raw_node.get("name") or raw_node.get("id") or "").strip()
            if not name:
                continue
            node = self.nodes.setdefault(name, GraphNode(name=name))
            node.count += int(raw_node.get("count", 1) or 1)
            for file_id in raw_node.get("files") or [source]:
                node.files.add(str(file_id))
            imported_nodes += 1

        for raw_edge in graph_data.get("edges", []):
            source_name = str(raw_edge.get("source") or "").strip()
            target_name = str(raw_edge.get("target") or "").strip()
            if not source_name or not target_name:
                continue
            relation = str(raw_edge.get("relation") or "related_to").strip() or "related_to"
            self.nodes.setdefault(source_name, GraphNode(name=source_name)).files.add(source)
            self.nodes.setdefault(target_name, GraphNode(name=target_name)).files.add(source)
            key = f"{source_name}\t{relation}\t{target_name}"
            edge = self.edges.setdefault(key, GraphEdge(source=source_name, target=target_name, relation=relation))
            edge.count += int(raw_edge.get("count", 1) or 1)
            for file_id in raw_edge.get("files") or [source]:
                edge.files.add(str(file_id))
            imported_edges += 1

        self._save()
        return {"imported_nodes": imported_nodes, "imported_edges": imported_edges, "stats": self.stats()}

    def delete_file(self, file_id: str) -> None:
        self.nodes = {
            name: node
            for name, node in self.nodes.items()
            if file_id not in node.files
        }
        self.edges = {
            key: edge
            for key, edge in self.edges.items()
            if file_id not in edge.files
        }
        self._save()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_terms = set(extract_entities(query)) or {query.strip()}
        scored = []
        for node in self.nodes.values():
            score = score_node(node.name, query_terms) + min(node.count, 10) * 0.01
            if score > 0:
                scored.append((score, node))
        scored.sort(key=lambda item: item[0], reverse=True)

        results = []
        for score, node in scored[:top_k]:
            relations = [
                edge
                for edge in self.edges.values()
                if edge.source == node.name or edge.target == node.name
            ]
            relations.sort(key=lambda edge: edge.count, reverse=True)
            neighbor_text = ", ".join(
                f"{edge.source} -[{edge.relation}]-> {edge.target}"
                for edge in relations[:5]
            )
            results.append(
                {
                    "entity": node.name,
                    "score": round(score, 4),
                    "content": (
                        f"Entity: {node.name}\n"
                        f"Mentions: {node.count}\n"
                        f"Relations: {neighbor_text or '(none)'}"
                    ),
                    "metadata": {
                        "files": sorted(node.files),
                        "degree": len(relations),
                    },
                }
            )
        return results

    def stats(self) -> dict:
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "files": sorted({file_id for node in self.nodes.values() for file_id in node.files}),
        }

    def export(self, limit: int = 200) -> dict:
        nodes = sorted(self.nodes.values(), key=lambda node: node.count, reverse=True)[:limit]
        edges = sorted(self.edges.values(), key=lambda edge: edge.count, reverse=True)[:limit]
        return {
            "nodes": [node.to_dict() for node in nodes],
            "edges": [edge.to_dict() for edge in edges],
            "stats": self.stats(),
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.nodes = {name: GraphNode.from_dict(node) for name, node in data.get("nodes", {}).items()}
        self.edges = {key: GraphEdge.from_dict(edge) for key, edge in data.get("edges", {}).items()}

    def _save(self) -> None:
        data = {
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "edges": {key: edge.to_dict() for key, edge in self.edges.items()},
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]


def extract_entities(text: str) -> list[str]:
    entities = []
    for match in _ENTITY_RE.findall(text):
        token = match.strip(" _-").strip()
        if len(token) < 2:
            continue
        if token.isascii() and token.lower() in _LATIN_STOPWORDS:
            continue
        if token.isascii() and token.islower() and len(token) < 4:
            continue
        entities.append(token[:32])
    return entities


def unique_preserve_order(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def score_node(name: str, query_terms: set[str]) -> float:
    lowered = name.lower()
    score = 0.0
    for term in query_terms:
        term = term.lower().strip()
        if not term:
            continue
        if lowered == term:
            score = max(score, 1.0)
        elif term in lowered or lowered in term:
            score = max(score, 0.75)
    return score
