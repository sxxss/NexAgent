from __future__ import annotations

import importlib

import pytest


@pytest.mark.unit
def test_chat_stream_idle_timeout_defaults_to_long_runs(monkeypatch):
    monkeypatch.delenv("NEXAGENT_CHAT_STREAM_IDLE_TIMEOUT_S", raising=False)
    from nexagent.services import chat_service

    reloaded = importlib.reload(chat_service)

    assert reloaded.STREAM_IDLE_TIMEOUT_SECONDS == 30 * 60
    assert reloaded.STREAM_HEARTBEAT_SECONDS == 15


@pytest.mark.unit
def test_chat_stream_idle_timeout_can_be_overridden(monkeypatch):
    monkeypatch.setenv("NEXAGENT_CHAT_STREAM_IDLE_TIMEOUT_S", "2400")
    monkeypatch.setenv("NEXAGENT_CHAT_STREAM_HEARTBEAT_S", "10")
    from nexagent.services import chat_service

    reloaded = importlib.reload(chat_service)

    assert reloaded.STREAM_IDLE_TIMEOUT_SECONDS == 2400
    assert reloaded.STREAM_HEARTBEAT_SECONDS == 10
