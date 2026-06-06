"""Speech services — ASR (speech-to-text) and TTS (text-to-speech).

Both call OpenAI-compatible HTTP endpoints so any provider exposing
``/audio/transcriptions`` and ``/audio/speech`` works (SiliconFlow, OpenAI,
Aliyun-compatible gateways, …). The active provider is selected in the frontend
"语音" settings card and persisted to ``config.yaml`` under ``speech:``.

The realtime full-duplex WebSocket call lives in ``realtime_call_service``; this
module covers the request/response (push-to-talk + play-message) path used by
the chat box.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from nexagent.config import SpeechConfig, get_config


class SpeechConfigError(RuntimeError):
    """Raised when a speech provider is not configured / resolvable."""


@dataclass(slots=True)
class ResolvedProvider:
    base_url: str
    api_key: str

    @property
    def transcriptions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/audio/transcriptions"

    @property
    def speech_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/audio/speech"


_FORMAT_MIME = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/ogg",
    "pcm": "audio/pcm",
    "flac": "audio/flac",
}


async def _resolve_provider(provider_id: str) -> ResolvedProvider:
    """Find base_url + api_key for the configured speech provider.

    Lookup order:
      1. The explicit ``provider_id`` from the speech settings card.
      2. The provider marked as default.
      3. The first enabled provider (so SiliconFlow seeded from config works).
    """
    from nexagent.models.factory import _get_db_providers_async

    providers = await _get_db_providers_async()
    if not providers:
        raise SpeechConfigError("尚未配置任何模型供应商，请先在「设置 → 模型」中添加供应商。")

    chosen = None
    if provider_id:
        chosen = next((p for p in providers if p["id"] == provider_id), None)
        if chosen is None:
            raise SpeechConfigError(f"找不到语音供应商 provider_id={provider_id}，请在语音设置中重新选择。")
    if chosen is None:
        chosen = next((p for p in providers if p.get("is_default")), None)
    if chosen is None:
        chosen = providers[0]

    base_url = (chosen.get("base_url") or "").strip()
    api_key = (chosen.get("api_key") or "").strip()
    if not base_url:
        raise SpeechConfigError(f"供应商「{chosen.get('name')}」未配置 base_url。")
    if not api_key:
        raise SpeechConfigError(f"供应商「{chosen.get('name')}」未配置 API Key。")
    return ResolvedProvider(base_url=base_url, api_key=api_key)


def speech_status() -> dict:
    """Lightweight status for the settings card (no network calls)."""
    cfg = get_config().speech
    return {
        "asr": {
            "enabled": cfg.asr_enabled,
            "provider_id": cfg.asr_provider_id,
            "model": cfg.asr_model,
            "language": cfg.asr_language,
        },
        "tts": {
            "enabled": cfg.tts_enabled,
            "provider_id": cfg.tts_provider_id,
            "model": cfg.tts_model,
            "voice": cfg.tts_voice,
            "format": cfg.tts_format,
            "sample_rate": cfg.tts_sample_rate,
            "speed": cfg.tts_speed,
        },
    }


async def transcribe(
    audio: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    language: str | None = None,
) -> str:
    """Transcribe an audio clip to text via /audio/transcriptions."""
    cfg: SpeechConfig = get_config().speech
    if not cfg.asr_enabled:
        raise SpeechConfigError("语音识别（ASR）未启用，请在语音设置中开启。")
    if not cfg.asr_model:
        raise SpeechConfigError("未配置语音识别模型。")

    provider = await _resolve_provider(cfg.asr_provider_id)
    data = {"model": cfg.asr_model}
    lang = (language if language is not None else cfg.asr_language) or ""
    if lang:
        data["language"] = lang

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            provider.transcriptions_url,
            headers={"Authorization": f"Bearer {provider.api_key}"},
            data=data,
            files={"file": (filename, audio, content_type)},
        )
    if resp.status_code >= 400:
        raise SpeechConfigError(f"语音识别失败（{resp.status_code}）：{resp.text[:300]}")

    try:
        payload = resp.json()
    except Exception:
        return resp.text.strip()
    return str(payload.get("text", "")).strip()


async def synthesize(
    text: str,
    *,
    voice: str | None = None,
    model: str | None = None,
    audio_format: str | None = None,
    speed: float | None = None,
) -> tuple[bytes, str]:
    """Synthesize speech from text via /audio/speech. Returns (bytes, mime)."""
    cfg: SpeechConfig = get_config().speech
    if not cfg.tts_enabled:
        raise SpeechConfigError("语音合成（TTS）未启用，请在语音设置中开启。")

    text = (text or "").strip()
    if not text:
        raise SpeechConfigError("待合成文本为空。")

    use_model = model or cfg.tts_model
    use_voice = voice or cfg.tts_voice
    use_format = (audio_format or cfg.tts_format or "mp3").lower()
    if not use_model:
        raise SpeechConfigError("未配置语音合成模型。")

    provider = await _resolve_provider(cfg.tts_provider_id)
    body = {
        "model": use_model,
        "input": text,
        "voice": use_voice,
        "response_format": use_format,
        "speed": speed if speed is not None else cfg.tts_speed,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            provider.speech_url,
            headers={"Authorization": f"Bearer {provider.api_key}"},
            json=body,
        )
    if resp.status_code >= 400:
        raise SpeechConfigError(f"语音合成失败（{resp.status_code}）：{resp.text[:300]}")

    mime = _FORMAT_MIME.get(use_format, "audio/mpeg")
    return resp.content, mime
