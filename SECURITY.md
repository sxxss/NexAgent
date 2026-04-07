# Security Policy

NexAgent combines LLM calls, tool execution, web access, knowledge indexing, MCP integrations, and optional code execution. Treat every deployment as security-sensitive.

## Supported Versions

NexAgent is currently pre-1.0. Security fixes should target the default branch unless a release branch is explicitly maintained.

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities.

Use a private channel with the maintainers once the project has published one. Until then, create a minimal private reproduction and contact the repository owner directly.

Include:

- Affected commit or release.
- Clear reproduction steps.
- Expected and actual impact.
- Whether credentials, files, network access, or sandbox escape are involved.
- Suggested mitigation, if known.

## High-Risk Areas

- **Sandbox execution**: code execution must be isolated before serving untrusted users.
- **MCP tools**: MCP servers can access local or remote resources depending on configuration.
- **Web fetch/search**: fetched content can contain prompt injection or malicious instructions.
- **Knowledge ingestion**: uploaded files can contain sensitive data or malicious payloads.
- **API keys**: keys must stay in `.env` or a secure secret store and should never be returned to the frontend.
- **Channel webhooks**: public webhook endpoints need authentication, replay protection, and rate limiting before production use.

## Deployment Guidance

- Do not expose a development instance directly to the public internet.
- Use HTTPS and a reverse proxy for any shared deployment.
- Run sandbox workloads with Docker or another isolated provider, not with broad host permissions.
- Disable unused tools, MCP servers, and channels.
- Keep `.env`, `config.yaml`, local data directories, logs, and uploads out of commits.
- Rotate credentials if they were ever committed, logged, uploaded, or shared.

## Prompt Injection Guidance

Documents, webpages, chat messages, and tool outputs are untrusted content. They may include instructions that try to override system behavior, reveal secrets, or call tools. Agent code should treat those instructions as data unless they come directly from the user or trusted configuration.
