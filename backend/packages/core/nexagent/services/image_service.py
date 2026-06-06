"""Image generation — OpenAI-compatible ``/images/generations``.

Resolves an image-capable model from the configured providers (a provider whose
``capabilities`` include ``image`` or whose ``model_configs`` has an entry of
``type: image``) and calls its image endpoint. Works with SiliconFlow
(Kwai-Kolors/Kolors, FLUX, …), OpenAI (gpt-image / dall-e) and compatible
gateways.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx


class ImageConfigError(RuntimeError):
    """Raised when no image generation model is configured / resolvable."""


@dataclass(slots=True)
class ResolvedImageModel:
    base_url: str
    api_key: str
    model: str


def _model_is_image(mc: dict) -> bool:
    return str(mc.get("type", "")).lower() in {"image", "image_generation"}


def image_status() -> dict:
    """Lightweight status for the settings card (no network calls, key masked)."""
    from nexagent.config import get_config

    cfg = get_config().image
    return {
        "enabled": cfg.enabled,
        "base_url": cfg.base_url,
        "api_key": "••••••" if cfg.api_key else "",
        "api_key_configured": bool(cfg.api_key),
        "model": cfg.model,
        "size": cfg.size,
    }


async def resolve_image_model(model: str | None = None) -> ResolvedImageModel:
    """Resolve base_url + api_key + model for image generation.

    Prefers the independent image card's own ``base_url`` + ``api_key`` + ``model``.
    When credentials are empty, falls back to a provider that declares the image
    capability (or an image-typed model config).
    """
    from nexagent.config import get_config

    cfg = get_config().image
    use_model = model or cfg.model
    base_url = (cfg.base_url or "").strip()
    api_key = (cfg.api_key or "").strip()
    if base_url and api_key and use_model:
        return ResolvedImageModel(base_url=base_url, api_key=api_key, model=use_model)

    from nexagent.models.factory import _get_db_providers_async

    providers = await _get_db_providers_async()
    if not providers:
        raise ImageConfigError("尚未配置图片生成：请在「设置 → 语音与图像」填写 Base URL、API Key 与模型。")

    # 1. Explicit model id — find the owning provider.
    if model:
        for p in providers:
            ids = {str(mc.get("id")) for mc in (p.get("model_configs") or [])} | set(p.get("models") or [])
            if model in ids:
                return _build(p, model)

    # 2. Any provider with an image-typed model config.
    for p in providers:
        for mc in p.get("model_configs") or []:
            if _model_is_image(mc):
                return _build(p, str(mc.get("id")))

    # 3. Any provider declaring the image capability — use its first model.
    for p in providers:
        if "image" in (p.get("capabilities") or []):
            models = p.get("models") or [str(mc.get("id")) for mc in (p.get("model_configs") or [])]
            if models:
                return _build(p, models[0])

    raise ImageConfigError("未配置图片生成模型。请在「设置 → 语音与图像」里填写 Base URL、API Key 与模型。")


def _build(provider: dict, model: str) -> ResolvedImageModel:
    base_url = (provider.get("base_url") or "").strip()
    api_key = (provider.get("api_key") or "").strip()
    if not base_url:
        raise ImageConfigError(f"供应商「{provider.get('name')}」未配置 base_url。")
    if not api_key:
        raise ImageConfigError(f"供应商「{provider.get('name')}」未配置 API Key。")
    return ResolvedImageModel(base_url=base_url, api_key=api_key, model=model)


async def generate_image(
    prompt: str,
    *,
    model: str | None = None,
    size: str | None = None,
) -> bytes:
    """Generate an image from a prompt; returns the image bytes (PNG/JPEG)."""
    from nexagent.config import get_config

    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageConfigError("图片描述为空。")

    image_cfg = get_config().image
    if not image_cfg.enabled:
        raise ImageConfigError("图片生成未启用，请在「设置 → 语音与图像」中开启。")
    size = size or image_cfg.size or "1024x1024"

    target = await resolve_image_model(model)
    body = {
        "model": target.model,
        "prompt": prompt,
        "image_size": size,  # SiliconFlow style
        "size": size,         # OpenAI style (ignored by providers that don't use it)
        "batch_size": 1,
        "n": 1,
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{target.base_url.rstrip('/')}/images/generations",
            headers={"Authorization": f"Bearer {target.api_key}"},
            json=body,
        )
    if resp.status_code >= 400:
        raise ImageConfigError(f"图片生成失败（{resp.status_code}）：{resp.text[:300]}")

    payload = resp.json()
    items = payload.get("images") or payload.get("data") or []
    if not items:
        raise ImageConfigError(f"图片生成返回为空：{str(payload)[:200]}")
    first = items[0]

    if isinstance(first, dict) and first.get("b64_json"):
        return base64.b64decode(first["b64_json"])

    url = first.get("url") if isinstance(first, dict) else str(first)
    if not url:
        raise ImageConfigError("图片生成结果缺少 url。")
    async with httpx.AsyncClient(timeout=120.0) as client:
        img = await client.get(url)
    if img.status_code >= 400:
        raise ImageConfigError(f"下载生成图片失败（{img.status_code}）。")
    return img.content
