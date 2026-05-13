from __future__ import annotations

import asyncio

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logged_stream_writes_interrupted_log_in_background(monkeypatch):
    from nexagent.agents.middlewares import log_middleware

    written: list[dict] = []

    async def fake_write_log(**kwargs):
        written.append(kwargs)

    async def cancelled_generator():
        yield {"status": "tool_call", "tool": "web_search"}
        raise asyncio.CancelledError

    monkeypatch.setattr(log_middleware, "_write_log", fake_write_log)

    with pytest.raises(asyncio.CancelledError):
        async for _chunk in log_middleware.logged_stream(
            cancelled_generator(),
            agent_id="agent-1",
            agent_name="Agent",
            thread_id="thread-1",
            model_name="model-1",
        ):
            pass

    await asyncio.sleep(0)

    assert written
    assert written[0]["status"] == "interrupted"
    assert written[0]["tools_used"] == ["web_search"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_logged_stream_persists_token_source(monkeypatch):
    from nexagent.agents.middlewares import log_middleware

    written: list[dict] = []

    async def fake_write_log(**kwargs):
        written.append(kwargs)

    async def generator():
        yield {
            "status": "finished",
            "usage": {
                "input_tokens": 12,
                "output_tokens": 4,
                "raw_input_tokens": 15_200_000,
                "raw_output_tokens": 4,
                "token_source": "anomaly_corrected",
                "token_estimated": True,
            },
        }

    monkeypatch.setattr(log_middleware, "_write_log", fake_write_log)

    async for _chunk in log_middleware.logged_stream(
        generator(),
        agent_id="agent-1",
        agent_name="Agent",
        thread_id="thread-1",
        model_name="model-1",
    ):
        pass

    assert written[0]["input_tokens"] == 12
    assert written[0]["raw_input_tokens"] == 15_200_000
    assert written[0]["token_source"] == "anomaly_corrected"
    assert written[0]["token_estimated"] is True
