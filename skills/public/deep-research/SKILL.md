---
name: deep-research
description: Conduct deep research on a topic using web search and knowledge bases
version: 0.1.0
tags:
  - research
  - delegation
required_tools:
  - web_search
  - web_fetch
  - delegate_subagents
---

# Deep Research

This skill enables the agent to conduct comprehensive research on a topic,
combining web search, knowledge base retrieval, and multi-step analysis.

## Capabilities

- **Web Research**: Search the web for up-to-date information
- **Knowledge Integration**: Combine web results with internal knowledge bases
- **Multi-Step Analysis**: Break complex research into sub-tasks
- **Report Generation**: Produce structured research reports

## When to Use

- When the user requests in-depth analysis on a topic
- When research requires synthesizing multiple sources
- When generating comprehensive reports or literature reviews

## How It Works

1. Decompose the research question into sub-questions
2. Search web and knowledge bases for each sub-question
3. Synthesize findings into a coherent analysis
4. Generate a structured report with citations
