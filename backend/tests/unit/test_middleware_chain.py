from __future__ import annotations

import pytest


@pytest.mark.unit
def test_default_middleware_chain_contains_safety_layers():
    from nexagent.agents.middlewares import build_agent_middlewares

    names = [middleware.__class__.__name__ for middleware in build_agent_middlewares()]

    assert "DanglingToolCallMiddleware" in names
    assert "SandboxMiddleware" in names
    assert "ToolErrorHandlingMiddleware" in names
    assert "LLMErrorHandlingMiddleware" in names
    assert "LoopDetectionMiddleware" in names
