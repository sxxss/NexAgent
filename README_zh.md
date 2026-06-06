# NexAgent

[English](./README.md) | 简体中文

NexAgent 是一个知识增强型 AI Agent 平台，融合基于图的智能体编排能力与一流的知识库/知识图谱能力。目标是提供一个可自部署、可扩展、具备完整产品体验的 Agent 工作台，覆盖对话、深度研究、RAG、知识图谱、Skills、MCP、记忆、评估和多渠道接入。

> 当前状态：早期产品化阶段。核心功能面已经展开，但 v1.0 前公开 API、部署默认值和页面细节仍可能调整。

## 为什么做 NexAgent

很多 Agent Demo 停留在单轮聊天或单个流程。NexAgent 想补齐真实产品需要的外围能力：

- **Agent 工作台**：对话、深度研究、Agent 配置、模型选择、推理模式、工具绑定和历史会话。
- **知识系统**：RAG 知识库、文档解析、向量检索、LightRAG 风格图谱流程，以及 Neo4j/Milvus 生产后端和本地降级。
- **扩展体系**：内置工具、自定义 Skills、MCP 服务注册、Sub-Agent 和渠道 webhook。
- **运维入口**：FastAPI 网关、健康检查、Docker Compose、配置模板和验证脚本。
- **产品闭环**：仪表盘、记忆、评估、设置和运行时诊断。

## 当前能力

| 模块 | 已具备能力 |
| --- | --- |
| Agent 运行时 | 基于 LangGraph 的聊天与深度研究 Agent，支持流式响应 |
| 工具 | 知识库搜索、Web 搜索/抓取、Python 代码执行、MCP 工具、Sub-Agent 委派 |
| 语音 | ASR 语音输入、TTS 语音播报、实时语音通话（按住说话）；供应商在「设置 → 语音」卡片可配 |
| LLM Wiki | 一键把对话沉淀成结构化 Wiki 知识页面，可写入知识库参与向量/图谱检索 |
| 知识系统 | Milvus 兼容向量库、LightRAG/Neo4j 风格图谱库、本地开发降级 |
| 前端工作台 | Next.js 页面：对话、仪表盘、Agent、知识库、记忆、MCP、Skills、渠道、评估、创建、设置 |
| API | FastAPI 网关、OpenAPI 文档、健康检查、系统信息和模块化路由 |
| 部署 | PowerShell 一键启动、Docker Compose、可选知识服务 profile |

## 快速开始

### 1. 准备配置

```powershell
cd D:\tools\agents\NexAgent
Copy-Item .env.example .env -ErrorAction SilentlyContinue
Copy-Item config.example.yaml config.yaml -ErrorAction SilentlyContinue
```

编辑 `.env`，至少填入一个模型服务商 API Key。默认模板优先使用 `SILICONFLOW_API_KEY`，也预留了 OpenAI、Anthropic、Google、Tavily、Milvus、Neo4j、PostgreSQL、Redis 等配置。

### 2. 运行本机诊断

```powershell
.\scripts\doctor.ps1
```

诊断脚本会检查 Python、Node.js、npm、uv、Docker、配置文件、关键环境变量、常见端口和后端 readiness 状态。

### 3. 本地启动

```powershell
.\start.ps1
```

访问：

- 前端：http://localhost:3000
- 后端：http://localhost:8001
- API 文档：http://localhost:8001/docs

如果需要同时启动 Milvus 等知识库服务：

```powershell
.\start.ps1 -kb
```

停止后台任务：

```powershell
.\start.ps1 -stop
```

## 手动开发

后端：

```powershell
cd backend
$env:UV_CACHE_DIR='.uv-cache'
uv sync
uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

## 数据库（生产配置）

NexAgent 默认使用 **PostgreSQL**（关系数据）+ **Milvus**（向量）+ **Neo4j**（知识图谱）。
本地开发前先拉起基础设施：

```bash
docker compose up -d postgres redis milvus neo4j minio
```

连接串由 `DATABASE_URL` 决定（未设置时默认连本机 `postgresql+asyncpg://nexagent:nexagent@localhost:5432/nexagent`）。
应用启动时会自动建表并初始化内置 Agent / 模型供应商，无需手动迁移。

- 想完全离线、用 SQLite 跑：设置 `NEXAGENT_DB_BACKEND=sqlite` 且 `NEXAGENT_KB_STORAGE=legacy`。
- 已有旧的 SQLite 数据要迁到 Postgres：

  ```bash
  uv run python scripts/migrate_sqlite_to_postgres.py
  ```

## Docker

启动核心后端服务：

```powershell
docker compose up -d
```

启动可选知识库服务：

```powershell
docker compose --profile kb up -d
```

停止服务：

```powershell
docker compose down
```

## 验证

```powershell
python scripts\verify_phase1.py --skip-docker
python scripts\verify_phase2.py
python scripts\verify_phase3.py
python scripts\verify_phase4.py
python scripts\verify_phase5.py
cd backend; uv run ruff check .; uv run pytest
cd ..\frontend; npm run lint; npm run build
```

## 面向 GitHub 发布的路线图

下一阶段高优先级工作记录在 [docs/launch-roadmap.zh-CN.md](./docs/launch-roadmap.zh-CN.md)。简版如下：

1. **首次运行体验**：setup wizard、doctor 诊断、演示数据和错误恢复提示。
2. **Agent 可靠性**：中间件管道、重试、死循环检测、上下文摘要、token 统计和 tracing。
3. **沙盒与产物**：更安全的执行环境、虚拟路径、文件预览/下载和产物展示。
4. **知识质量**：更强文档解析、混合检索、rerank、知识图谱巡检和评估集。
5. **开源发布门面**：截图、演示视频、架构文档、示例、安全说明、贡献指南和 issue 模板。

## 参与贡献

欢迎贡献。请先阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，其中包含开发环境、质量检查、PR 要求和安全敏感改动说明。

## 安全说明

- 不要把开发部署直接暴露在公网。
- API Key 放在 `.env` 中，不要提交带密钥的 `.env` 或 `config.yaml`。
- 代码执行、Web 抓取、MCP 工具和渠道 webhook 都应视为高权限功能。
- 面向不可信用户开放沙盒前，请优先使用 Docker 或专用运行账户隔离。

漏洞报告和部署安全建议见 [SECURITY.md](./SECURITY.md)。

## 致谢

NexAgent 的设计受到以下开源项目启发：

- [LangGraph](https://github.com/langchain-ai/langgraph)：基于图的 Agent 编排。
- [LightRAG](https://github.com/HKUDS/LightRAG)：知识图谱检索，以及更广泛的 Agent 开源生态。

## 许可证

MIT。见 [LICENSE](./LICENSE)。
