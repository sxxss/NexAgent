from types import SimpleNamespace

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_probe_accepts_chat_models(monkeypatch):
    from app.gateway.routers import settings
    from nexagent.db import crypto as db_crypto
    from nexagent.db import models as db_models
    from nexagent.db import session as db_session

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, _model, provider_id):
            return SimpleNamespace(
                id=provider_id,
                name="Provider A",
                provider_type="openai",
                base_url="https://example.test/v1",
                api_key_env="",
                api_key_enc="encrypted",
                models=["chat-model"],
                model_configs=[{"id": "chat-model", "type": "chat"}],
            )

    calls = {}

    async def fake_probe(provider_type, model, api_key, base_url):
        calls["probe"] = (provider_type, model, api_key, base_url)
        return "ok"

    monkeypatch.setattr(db_session, "AsyncSessionLocal", lambda: FakeSession())
    monkeypatch.setattr(db_models, "ModelProvider", object)
    monkeypatch.setattr(db_crypto, "decrypt_key", lambda value: f"plain-{value}")
    monkeypatch.setattr(settings, "_probe_model", fake_probe)

    result = await settings.test_provider_model(
        settings.ModelProbeRequest(provider_id="provider-a", model_id="chat-model", capability="chat")
    )

    assert result["ok"] is True
    assert result["capability"] == "chat"
    assert result["message"] == "ok"
    assert calls["probe"] == ("openai", "chat-model", "plain-encrypted", "https://example.test/v1")
