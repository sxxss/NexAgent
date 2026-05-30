---
name: knowledge-graph
description: Query and explore knowledge graphs for entity relationships
version: 0.1.0
tags:
  - knowledge
  - graph
required_tools:
  - knowledge_search
---

# Knowledge Graph Query

This skill enables the agent to query knowledge graphs built from
documents, extracting entity relationships and structured knowledge.

## Capabilities

- **Entity Extraction**: Identify entities and relationships in queries
- **Graph Traversal**: Navigate entity relationships to find answers
- **Visual Context**: Provide graph structure context for complex queries
- **Hybrid Search**: Combine graph-based and vector-based retrieval

## When to Use

- When the user asks about relationships between concepts or entities
- When exploring connections and dependencies in a knowledge domain
- When the question requires multi-hop reasoning across entities

## How It Works

1. Parse the user's question to identify entities and relationship types
2. Use the `query_knowledge_graph` tool to traverse the graph
3. Combine graph context with RAG results for comprehensive answers
4. Explain entity relationships when relevant to the user's question
