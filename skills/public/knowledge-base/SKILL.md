---
name: knowledge-base
description: Search and retrieve information from RAG knowledge bases
version: 0.1.0
tags:
  - knowledge
  - rag
required_tools:
  - knowledge_search
---

# Knowledge Base Search

This skill enables the agent to search and retrieve relevant information
from connected RAG (Retrieval-Augmented Generation) knowledge bases.

## Capabilities

- **Semantic Search**: Find relevant documents using vector similarity
- **Multi-KB Support**: Search across multiple knowledge bases simultaneously
- **Source Attribution**: Return source documents with citations

## When to Use

- When the user asks questions that may be answered by uploaded documents
- When the agent needs factual information from the organization's knowledge base
- When research tasks require domain-specific knowledge

## How It Works

1. Extract the search query from the user's message
2. Use the `search_knowledge_base` tool to retrieve relevant chunks
3. Incorporate the retrieved context into the response
4. Cite sources when providing information from the knowledge base
