from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class WikiGraphMixin:
    def get_wiki_graph(
        self,
        kb_id: str,
        *,
        max_edges: int = 80,
        include_weak: bool = False,
        q: str | None = None,
    ) -> dict:
        pages = self._iter_page_details(kb_id)
        if q:
            key = self._normalize_link_key(q)
            pages = [
                page
                for page in pages
                if key
                and (
                    key in self._normalize_link_key(page["title"])
                    or key in self._normalize_link_key(page["content"])
                )
            ]
        title_index = self._title_index(pages)
        explicit_neighbors: dict[str, set[str]] = defaultdict(set)
        edge_signals: dict[tuple[str, str], dict[str, Any]] = {}

        def edge_key(left: str, right: str) -> tuple[str, str]:
            return tuple(sorted((left, right)))

        for page in pages:
            for link_title in self._extract_wikilinks(page["content"]):
                targets = self._resolve_wikilink(link_title, title_index)
                if len(targets) != 1:
                    continue
                target_id = targets[0]["id"]
                if target_id == page["id"]:
                    continue
                explicit_neighbors[page["id"]].add(target_id)
                explicit_neighbors[target_id].add(page["id"])
                edge_signals.setdefault(edge_key(page["id"], target_id), self._empty_signals())[
                    "wikilink"
                ] = True

        pages_by_source: dict[str, list[dict]] = defaultdict(list)
        for page in pages:
            for source_id in page["frontmatter"].get("sources") or []:
                pages_by_source[source_id].append(page)
        for source_id, source_pages in pages_by_source.items():
            for index, left in enumerate(source_pages):
                for right in source_pages[index + 1 :]:
                    signals = edge_signals.setdefault(edge_key(left["id"], right["id"]), self._empty_signals())
                    if source_id not in signals["source_overlap"]:
                        signals["source_overlap"].append(source_id)

        for common_id, neighbors in explicit_neighbors.items():
            neighbor_list = sorted(neighbors)
            for index, left_id in enumerate(neighbor_list):
                for right_id in neighbor_list[index + 1 :]:
                    signals = edge_signals.setdefault(edge_key(left_id, right_id), self._empty_signals())
                    if common_id not in signals["common_neighbors"]:
                        signals["common_neighbors"].append(common_id)

        page_type_by_id = {page["id"]: page["type"] for page in pages}
        edges = []
        for (source, target), signals in edge_signals.items():
            signals["source_overlap"] = sorted(signals.get("source_overlap") or [])
            signals["common_neighbors"] = sorted(signals.get("common_neighbors") or [])
            signals["type_affinity"] = page_type_by_id.get(source) == page_type_by_id.get(target)
            weight = self._edge_weight(signals)
            if weight > 0:
                edges.append({"source": source, "target": target, "weight": weight, "signals": signals})

        display_edges = self._display_edges(edges, max_edges=max_edges, include_weak=include_weak)
        communities = self._communities([page["id"] for page in pages], display_edges)
        nodes = [
            {
                "id": page["id"],
                "label": page["title"],
                "type": page["type"],
                "sources": page["frontmatter"].get("sources") or [],
                "confidence": page["frontmatter"].get("confidence", "UNVERIFIED"),
                "community": communities.get(page["id"], 0),
            }
            for page in pages
        ]
        return {
            "nodes": nodes,
            "edges": display_edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(display_edges),
                "raw_edge_count": len(edges),
                "display_edge_count": len(display_edges),
                "communities": len(set(communities.values())) if communities else 0,
            },
        }

    def _empty_signals(self) -> dict[str, Any]:
        return {"wikilink": False, "source_overlap": [], "common_neighbors": [], "type_affinity": False}

    def _edge_weight(self, signals: dict[str, Any]) -> float:
        return (
            (3.0 if signals.get("wikilink") else 0.0)
            + (4.0 if signals.get("source_overlap") else 0.0)
            + (1.5 if signals.get("common_neighbors") else 0.0)
            + (1.0 if signals.get("type_affinity") else 0.0)
        )

    def _display_edges(self, edges: list[dict], *, max_edges: int, include_weak: bool) -> list[dict]:
        ordered = sorted(edges, key=lambda item: item.get("weight", 0), reverse=True)
        edge_limit = max(1, int(max_edges or 80))
        if include_weak:
            return ordered[:edge_limit]
        explicit = [edge for edge in ordered if edge.get("signals", {}).get("wikilink")]
        weak = [edge for edge in ordered if not edge.get("signals", {}).get("wikilink")]
        selected = explicit[:edge_limit]
        if len(selected) >= edge_limit:
            return selected

        node_counts: dict[str, int] = defaultdict(int)
        for edge in selected:
            node_counts[edge["source"]] += 1
            node_counts[edge["target"]] += 1

        selected_keys = {tuple(sorted((edge["source"], edge["target"]))) for edge in selected}
        for edge in weak:
            if len(selected) >= edge_limit:
                break
            key = tuple(sorted((edge["source"], edge["target"])))
            if key in selected_keys:
                continue
            if node_counts[edge["source"]] >= 3 or node_counts[edge["target"]] >= 3:
                continue
            selected.append(edge)
            selected_keys.add(key)
            node_counts[edge["source"]] += 1
            node_counts[edge["target"]] += 1
        return selected

    def _communities(self, node_ids: list[str], edges: list[dict]) -> dict[str, int]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            adjacency[edge["source"]].add(edge["target"])
            adjacency[edge["target"]].add(edge["source"])
        communities: dict[str, int] = {}
        community_id = 0
        for node_id in node_ids:
            if node_id in communities:
                continue
            community_id += 1
            queue = deque([node_id])
            communities[node_id] = community_id
            while queue:
                current = queue.popleft()
                for nxt in adjacency[current]:
                    if nxt not in communities:
                        communities[nxt] = community_id
                        queue.append(nxt)
        return communities
