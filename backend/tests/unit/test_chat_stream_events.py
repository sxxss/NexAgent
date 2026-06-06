from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage


class FakeAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (AIMessageChunk(content="hello"), {})
        yield "values", {"artifacts": ["/mnt/user-data/outputs/report.md"], "messages": []}
        yield "messages", (
            AIMessageChunk(content=" world", usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}),
            {},
        )


class AnomalousUsageAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (
            AIMessageChunk(
                content="answer",
                usage_metadata={"input_tokens": 15_200_000, "output_tokens": 1, "total_tokens": 15_200_001},
            ),
            {},
        )


class FinalStateOnlyAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "values", {"messages": [AIMessage(content="final answer")]}


class EmptyAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "values", {"messages": []}


class CaptureHistoryAgent:
    name = "fake"

    def __init__(self):
        self.messages = []
        self.input_context = {}

    async def stream_with_state(self, messages, input_context=None):
        self.messages = messages
        self.input_context = input_context or {}
        yield "messages", (AIMessageChunk(content="ok"), {})


class ToolLifecycleAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "read_skill",
                    "args": {"id": "demo"},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (ToolMessage(content='{"ok": true}', tool_call_id="tool-1", name="read_skill"), {})
        yield "messages", (AIMessageChunk(content="done"), {})


class ErrorToolLifecycleAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "bash",
                    "args": {"command": "bad"},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (
            ToolMessage(
                content="Error: Tool failed",
                tool_call_id="tool-1",
                name="bash",
                status="error",
            ),
            {},
        )
        yield "messages", (AIMessageChunk(content="done"), {})


class PartialToolArgsAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (
            AIMessageChunk(
                content="",
                tool_calls=[{
                    "name": "skill_manage",
                    "args": {},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (
            AIMessageChunk(
                content="",
                tool_calls=[{
                    "name": "skill_manage",
                    "args": {"action": "patch", "id": "demo"},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (ToolMessage(content='{"ok": true}', tool_call_id="tool-1", name="skill_manage"), {})
        yield "messages", (AIMessageChunk(content="done"), {})


class PartialExecutePythonArgsAgent:
    name = "fake"

    async def stream_with_state(self, messages, input_context=None):
        yield "messages", (
            AIMessageChunk(
                content="",
                tool_calls=[{
                    "name": "execute_python",
                    "args": {},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (
            AIMessageChunk(
                content="",
                tool_calls=[{
                    "name": "execute_python",
                    "args": {"code": "print('ok')"},
                    "id": "tool-1",
                }],
            ),
            {},
        )
        yield "messages", (ToolMessage(content="ok", tool_call_id="tool-1", name="execute_python"), {})
        yield "messages", (AIMessageChunk(content="done"), {})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_stamps_events_and_artifacts(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: FakeAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    statuses = [event["status"] for event in events]
    assert statuses == ["started", "loading", "state", "loading", "finished"]
    assert [event["seq"] for event in events] == [1, 2, 3, 4, 5]
    assert all(event["event_id"].startswith("req-1:") for event in events)
    assert events[2]["new_artifacts"] == ["/mnt/user-data/outputs/report.md"]
    assert events[-1]["usage"] == {
        "input_tokens": 2,
        "output_tokens": 3,
        "raw_input_tokens": 2,
        "raw_output_tokens": 3,
        "estimated": False,
        "token_estimated": False,
        "token_source": "provider_reported",
    }
    assert events[-1]["response_chars"] == len("hello world")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_estimates_anomalous_provider_usage(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: AnomalousUsageAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    usage = events[-1]["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["estimated"] is True
    assert usage["provider_anomalous"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_emits_final_state_ai_content(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: FinalStateOnlyAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    assert any(event.get("content") == "final answer" for event in events if event["status"] == "loading")
    assert events[-1]["status"] == "finished"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_rebuilds_history_without_tool_rows(monkeypatch):
    from nexagent.services import chat_service

    agent = CaptureHistoryAgent()

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: agent)
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    history = [
        {"role": "user", "content": "first"},
        {"role": "tool", "content": '{"path": "x"}', "tool_name": "read_skill"},
        {"role": "assistant", "content": "answer"},
    ]

    events = [
        event
        async for event in chat_service.stream_chat(
            "second",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo", "checkpoint_thread_id": "thread-1:run:req-1"},
            request_id="req-1",
            history_messages=history,
        )
    ]

    assert events[-1]["status"] == "finished"
    assert [message.type for message in agent.messages] == ["human", "ai", "human"]
    assert [message.content for message in agent.messages] == ["first", "answer", "second"]
    assert agent.input_context["checkpoint_thread_id"] == "thread-1:run:req-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_emits_tool_result_events(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: ToolLifecycleAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    tool_call = next(event for event in events if event["status"] == "tool_call")
    tool_result = next(event for event in events if event["status"] == "tool_result")

    assert tool_call["tool_call_id"] == "tool-1"
    assert tool_call["tool"] == "read_skill"
    assert tool_call["tool_status"] == "started"
    assert tool_result["tool_call_id"] == "tool-1"
    assert tool_result["tool"] == "read_skill"
    assert tool_result["success"] is True
    assert tool_result["tool_status"] == "completed"
    assert tool_result["output"] == '{"ok": true}'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_marks_error_tool_result_unsuccessful(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: ErrorToolLifecycleAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    tool_result = next(event for event in events if event["status"] == "tool_result")
    assert tool_result["tool"] == "bash"
    assert tool_result["success"] is False
    assert events[-1]["status"] == "finished"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_updates_partial_tool_args_before_timing(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: PartialToolArgsAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    tool_calls = [event for event in events if event["status"] == "tool_call"]
    assert [event["tool_status"] for event in tool_calls] == ["preparing", "started"]
    assert tool_calls[0]["input"] == {}
    assert tool_calls[1]["input"] == {"action": "patch", "id": "demo"}
    tool_result = next(event for event in events if event["status"] == "tool_result")
    assert tool_result["tool_elapsed_ms"] is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_waits_for_execute_python_code_before_timing(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: PartialExecutePythonArgsAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    tool_calls = [event for event in events if event["status"] == "tool_call"]
    assert [event["tool_status"] for event in tool_calls] == ["preparing", "started"]
    assert tool_calls[0]["input"] == {}
    assert tool_calls[1]["input"] == {"code": "print('ok')"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_chat_never_finishes_with_empty_response(monkeypatch):
    from nexagent.services import chat_service

    async def validate_model_name_async(model):
        return model or "demo"

    monkeypatch.setattr(chat_service, "_get_agent", lambda agent_name: EmptyAgent())
    monkeypatch.setattr("nexagent.models.factory.validate_model_name_async", validate_model_name_async)

    events = [
        event
        async for event in chat_service.stream_chat(
            "hi",
            agent_name="fake",
            thread_id="thread-1",
            context_overrides={"model": "demo"},
            request_id="req-1",
        )
    ]

    loading = [event for event in events if event["status"] == "loading"]
    assert loading
    assert "没有返回可显示内容" in loading[-1]["content"]
    assert events[-1]["status"] == "finished"
