# NexAgent Frontend

Next.js workbench for NexAgent. It provides the user-facing product surface for chat, deep research, agents, knowledge bases, memory, MCP, skills, channels, evaluation, creation workflows, dashboard, and settings.

## Development

```powershell
cd D:\tools\agents\NexAgent\frontend
npm install
npm run dev
```

Open http://localhost:3000.

The frontend proxies `/api/*` to the backend URL configured by `NEXT_PUBLIC_API_URL`; if it is not set, it uses `http://localhost:8001`.

## Useful Commands

```powershell
npm run lint
npm run build
```

## Product Guidelines

- The first screen should be the working product, not a marketing landing page.
- Empty, loading, and error states should tell users what to do next.
- Agent runs should expose progress: thinking, tool calls, research steps, writing, completion, and errors.
- Knowledge results should show source evidence and file context.
- Settings pages should avoid exposing secret values; show only whether a key is configured.
