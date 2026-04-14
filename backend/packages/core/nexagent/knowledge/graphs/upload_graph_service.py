"""Service helpers for importing externally prepared knowledge graphs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GraphUploadPayload:
    """Validated graph upload payload."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    source: str = "manual"

    def to_graph_data(self) -> dict:
        return {"nodes": self.nodes, "edges": self.edges}


def upload_graph(kb_id: str, payload: GraphUploadPayload) -> dict:
    """Import nodes and edges into a LightRAG-backed knowledge base."""
    from nexagent.knowledge.manager import get_manager

    return get_manager().import_graph(kb_id, payload.to_graph_data(), source=payload.source)
