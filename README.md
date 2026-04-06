# NexAgent

English | [简体中文](./README_zh.md)

NexAgent is a knowledge-enhanced AI agent platform that combines graph-based agent orchestration with first-class knowledge bases and knowledge graphs. It is designed to be a self-hostable workbench for chat, deep research, RAG, knowledge graph reasoning, skills, MCP tools, memory, evaluation, and multi-channel agent delivery.

> Status: active early product. The repository already contains the core platform surface, but the public API and deployment defaults may still change before v1.0.

## Why NexAgent

Most agent demos stop at a single chat loop. NexAgent aims to provide the missing product layer around agents:

- **Agent workbench**: chat, deep research, agent profiles, model selection, reasoning modes, tool binding, and conversation history.
- **Knowledge system**: RAG knowledge bases, document parsing, vector retrieval, LightRAG-style graph workflows, and Neo4j/Milvus production backends with local fallbacks.
- **Extensibility**: built-in tools, custom skills, MCP server registry, sub-agents, and channel webhooks.
- **Operations surface**: FastAPI gateway, health/readiness probes, Docker Compose services, config templates, and verification scripts.
- **Product feedback loops**: dashboard, memory view, evaluation page, settings, and runtime diagnostics.

## Current Features

| Area | What is available |
| --- | --- |
| Agent runtime | LangGraph-based chat and deep research agents with streaming responses |
| Tools | Knowledge search, web search/fetch, Python code execution, MCP tools, sub-agent delegation |
| Knowledge | Milvus-compatible vector store, LightRAG/Neo4j-style graph store, local development fallback |
| Frontend | Next.js workbench for chat, dashboard, agents, knowledge, memory, MCP, skills, channels, eval, creator, and settings |
| API | FastAPI gateway with OpenAPI docs, health checks, system info, and modular routers |
| Deployment | Local PowerShell startup, Docker Compose, optional knowledge services profile |

## Quick Start

### 1. Prepare configuration

```powershell
cd D:\tools\agents\NexAgent
Copy-Item .env.example .env -ErrorAction SilentlyContinue
Copy-Item config.example.yaml config.yaml -ErrorAction SilentlyContinue
```

Edit `.env` and provide at least one model provider key. The default template uses `SILICONFLOW_API_KEY`, and also includes placeholders for OpenAI, Anthropic, Google, Tavily, Milvus, Neo4j, PostgreSQL, and Redis.

### 2. Check your machine

```powershell
.\scripts\doctor.ps1
```

The doctor script checks Python, Node.js, npm, uv, Docker, config files, key environment variables, common ports, and backend readiness hints.

### 3. Run locally

```powershell
.\start.ps1
```

If Windows blocks PowerShell scripts, use the command wrapper instead:

```powershell
.\start.cmd -kb
```

Open:

- Frontend: http://localhost:3000
- Backend: http://localhost:8001
- API docs: http://localhost:8001/docs

To enable Milvus and the knowledge-base services during startup:

```powershell
.\start.ps1 -kb
```

To stop background jobs started by the script:

```powershell
.\start.ps1 -stop
```

## Manual Development

Backend:

```powershell
cd backend
$env:UV_CACHE_DIR='.uv-cache'
uv sync
uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## Docker

Start the core backend stack:

```powershell
docker compose up -d
```

Start optional knowledge services:

```powershell
docker compose --profile kb up -d
```

Milvus uses the dense + BM25 schema and defaults to `milvusdb/milvus:v2.6.12`. If the container repeatedly logs stale `collection not found` errors, follow [docs/milvus-recovery.zh-CN.md](./docs/milvus-recovery.zh-CN.md) before reprocessing indexed files.

Stop services:

```powershell
docker compose down
```

## Verification

```powershell
python scripts\verify_phase1.py --skip-docker
python scripts\verify_phase2.py
python scripts\verify_phase3.py
python scripts\verify_phase4.py
python scripts\verify_phase5.py
cd backend; uv run ruff check .; uv run pytest
cd ..\frontend; npm run lint; npm run build
```

## Roadmap Toward a Strong Open Source Release

The next high-impact work is tracked in [docs/launch-roadmap.zh-CN.md](./docs/launch-roadmap.zh-CN.md). The short version:

1. **First-run excellence**: setup wizard, doctor hints, seed demo data, and clear error recovery.
2. **Agent reliability**: middleware pipeline for retries, loop detection, summarization, token usage, and tracing.
3. **Sandbox and artifacts**: safer execution, virtual file paths, file preview/download, and artifact presentation.
4. **Knowledge quality**: stronger parsing, hybrid retrieval, reranking, knowledge graph inspection, and evaluation datasets.
5. **GitHub launch readiness**: screenshots, demo video, architecture docs, examples, security notes, contribution guide, and issue templates.

## Contributing

Contributions are welcome. Start with [CONTRIBUTING.md](./CONTRIBUTING.md) for setup, quality checks, PR expectations, and security-sensitive areas.

## Security Notes

- Do not expose a development deployment directly to the public internet.
- Keep API keys in `.env`; do not commit `.env` or `config.yaml` with secrets.
- Treat code execution, web fetch, MCP tools, and channel webhooks as privileged features.
- Use Docker or a dedicated runtime account before enabling sandbox execution for untrusted users.

For vulnerability reporting and deployment guidance, see [SECURITY.md](./SECURITY.md).

## Acknowledgements

NexAgent is inspired by the architecture and product ideas in:

- [LangGraph](https://github.com/langchain-ai/langgraph) for graph-based agent orchestration.
- [LightRAG](https://github.com/HKUDS/LightRAG) for knowledge-graph retrieval, and the broader open-source agent ecosystem.

## License

MIT. See [LICENSE](./LICENSE).
