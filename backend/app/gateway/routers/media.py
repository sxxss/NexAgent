"""Media analysis and generation endpoints."""

from __future__ import annotations

import base64
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None
    model: str | None = None
    format: str | None = None
    speed: float | None = None


def _artifact_dir() -> Path:
    import os

    path = Path(os.environ.get("NEXAGENT_DATA_DIR", ".nexagent")) / "artifacts" / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _capabilities_for_model(model_name: str | None) -> dict:
    from nexagent.models.factory import list_model_configs

    models = list_model_configs()
    if not model_name and models:
        return models[0].get("capabilities", {})
    for item in models:
        if item.get("name") == model_name or item.get("model") == model_name:
            return item.get("capabilities", {})
    return {}


async def _save_upload(file: UploadFile, prefix: str) -> dict:
    suffix = Path(file.filename or "").suffix or ".bin"
    artifact_id = f"{prefix}-{uuid.uuid4().hex}{suffix}"
    target = _artifact_dir() / artifact_id
    content = await file.read()
    target.write_bytes(content)
    return {
        "artifact_id": artifact_id,
        "filename": file.filename,
        "size": len(content),
        "path": str(target),
    }


@router.post("/analyze-image")
async def analyze_image(file: UploadFile = File(...), model: str | None = Form(default=None)):
    caps = _capabilities_for_model(model)
    artifact = await _save_upload(file, "image")
    if not caps.get("supports_vision"):
        return {
            "ok": False,
            "type": "image_analysis",
            "artifact": artifact,
            "message": "当前模型未声明图片识别能力，文件已保存但未调用模型分析。",
        }
    return {
        "ok": True,
        "type": "image_analysis",
        "artifact": artifact,
        "message": "图片已保存，当前模型声明支持图片识别。后续可接入真实多模态调用。",
    }


@router.post("/analyze-video")
async def analyze_video(file: UploadFile = File(...), model: str | None = Form(default=None)):
    caps = _capabilities_for_model(model)
    artifact = await _save_upload(file, "video")
    if not caps.get("supports_video_generation") and not caps.get("supports_vision"):
        return {
            "ok": False,
            "type": "video_analysis",
            "artifact": artifact,
            "message": "当前模型未声明视频或视觉理解能力，文件已保存但未调用模型分析。",
        }
    return {
        "ok": True,
        "type": "video_analysis",
        "artifact": artifact,
        "message": "视频已保存，当前模型具备可用于视频/视觉处理的能力声明。",
    }


@router.post("/generate-image")
async def generate_image(body: GenerateRequest):
    """Generate an image via a configured image-generation model."""
    from nexagent.services.image_service import ImageConfigError
    from nexagent.services.image_service import generate_image as gen

    try:
        image_bytes = await gen(body.prompt, model=body.model)
    except ImageConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    artifact_id = f"generated-image-{uuid.uuid4().hex}.png"
    target = _artifact_dir() / artifact_id
    target.write_bytes(image_bytes)
    return {
        "ok": True,
        "type": "image_generation",
        "artifact": {
            "artifact_id": artifact_id,
            "path": str(target),
            "url": f"/api/media/artifact/{artifact_id}/raw",
            "size": len(image_bytes),
        },
        "message": "图片已生成。",
    }


@router.post("/generate-video")
async def generate_video(body: GenerateRequest):
    caps = _capabilities_for_model(body.model)
    if not caps.get("supports_video_generation"):
        raise HTTPException(status_code=400, detail="当前模型未声明视频生成能力")

    artifact_id = f"generated-video-{uuid.uuid4().hex}.txt"
    target = _artifact_dir() / artifact_id
    target.write_text(f"Video generation prompt:\n{body.prompt}\n", encoding="utf-8")
    return {
        "ok": True,
        "type": "video_generation",
        "artifact": {"artifact_id": artifact_id, "path": str(target)},
        "message": "已生成视频任务 artifact。真实视频模型接入后可替换为二进制结果。",
    }


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    """Speech-to-text: upload an audio clip, get back the transcript."""
    from nexagent.services.speech import SpeechConfigError, transcribe

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="音频内容为空")
    try:
        text = await transcribe(
            audio,
            filename=file.filename or "audio.webm",
            content_type=file.content_type or "audio/webm",
            language=language,
        )
    except SpeechConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"text": text}


@router.post("/tts")
async def text_to_speech(body: TTSRequest):
    """Text-to-speech: returns the synthesized audio as a binary stream."""
    from nexagent.services.speech import SpeechConfigError, synthesize

    try:
        audio, mime = await synthesize(
            body.text,
            voice=body.voice,
            model=body.model,
            audio_format=body.format,
            speed=body.speed,
        )
    except SpeechConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=audio, media_type=mime)


@router.get("/artifact/{artifact_id}")
async def read_artifact(artifact_id: str):
    target = _artifact_dir() / artifact_id
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = target.read_bytes()
    return {
        "artifact_id": artifact_id,
        "bytes_base64": base64.b64encode(content).decode("ascii"),
        "size": len(content),
    }


@router.get("/artifact/{artifact_id}/raw")
async def read_artifact_raw(artifact_id: str):
    """Serve an artifact as raw bytes (e.g. for <img src>)."""
    import mimetypes

    target = _artifact_dir() / artifact_id
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return Response(content=target.read_bytes(), media_type=mime)
