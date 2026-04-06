# Contributing to NexAgent

Thanks for helping improve NexAgent. This project is still early, so the best contributions are changes that make the product easier to run, easier to understand, or more reliable in real agent workflows.

## Good First Contributions

- Improve setup and troubleshooting docs.
- Add clearer empty, loading, and error states in the frontend.
- Add focused tests for config loading, agent runtime behavior, knowledge parsing, and API routers.
- Add examples for skills, MCP servers, knowledge-base workflows, or deep research prompts.
- Fix issues found by `scripts\doctor.ps1`, backend tests, frontend lint, or CI.

## Development Setup

```powershell
cd D:\tools\agents\NexAgent
Copy-Item .env.example .env -ErrorAction SilentlyContinue
Copy-Item config.example.yaml config.yaml -ErrorAction SilentlyContinue
.\scripts\doctor.ps1
```

Backend:

```powershell
cd backend
uv sync
uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

## Quality Checks

Run the checks that match your change:

```powershell
cd backend
uv run ruff check .
uv run pytest
```

```powershell
cd frontend
npm run lint
npm run build
```

For larger platform changes:

```powershell
python scripts\verify_phase1.py --skip-docker
python scripts\verify_phase2.py
python scripts\verify_phase3.py
python scripts\verify_phase4.py
python scripts\verify_phase5.py
```

## Pull Request Expectations

- Keep changes focused. Avoid mixing product, refactor, formatting, and dependency changes in one PR.
- Explain the user-visible behavior change and the verification you ran.
- Do not commit secrets, local `.env`, local `config.yaml`, generated caches, or local data directories.
- Add or update tests when behavior changes.
- Preserve existing patterns unless the PR is explicitly a refactor.

## Architecture Notes

- Backend gateway code lives under `backend/app/gateway`.
- Core agent, knowledge, tools, skills, sandbox, memory, tracing, and model code lives under `backend/packages/core/nexagent`.
- Frontend routes live under `frontend/src/app`.
- Shared frontend components live under `frontend/src/components`.
- Built-in public skills live under `skills/public`.

## Security-Sensitive Changes

Treat the following areas as security-sensitive and document the risk in the PR:

- Sandbox execution and file access.
- Web fetch/search behavior.
- MCP server installation or execution.
- API key handling and settings pages.
- Channel webhooks and external integrations.
- Authentication, authorization, and sharing behavior.
