"""Realtime voice call — turn-based full-duplex over a single WebSocket.

Flow per turn:
  1. Browser streams one spoken utterance (binary audio) and signals end-of-turn.
  2. Server transcribes it (ASR), echoes the transcript, runs the agent, then
     synthesizes the reply (TTS) and streams the audio back.
  3. Messages are persisted to the same conversation thread as the text chat, so
     a call and a typed conversation share history.

SiliconFlow-style providers expose request/response ASR/TTS (not a streaming WS),
so turns are utterance-based rather than word-streaming — functionally a phone
call with push-to-talk / VAD on the client.

Client → server messages (JSON text frames):
  {"type": "start", "agent": "chatbot", "thread_id": "...", "model": "..."}
  {"type": "utterance", "format": "webm"}   # followed by one binary audio frame
  {"type": "text", "message": "..."}        # typed turn, skips ASR
  {"type": "bye"}

Server → client messages:
  {"type": "ready", "thread_id": "..."}
  {"type": "transcript", "text": "..."}
  {"type": "reply", "text": "..."}
  {"type": "audio_start", "mime": "audio/mpeg"} + one binary frame + {"type": "audio_end"}
  {"type": "error", "message": "..."}
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.gateway.routers.chat import ChatRequest, build_context_overrides, resolve_agent_runtime

router = APIRouter()


async def run_voice_turn(
    *,
    transcript: str,
    agent: str,
    thread_id: str,
    model: str | None,
    user_id: str | None,
) -> str:
    """Run one agent turn from a transcript; persist messages; return reply text."""
    from nexagent.services.chat_service import stream_chat
    from nexagent.services.conversation_service import append_message, ensure_conversation, list_messages

    request = ChatRequest(message=transcript, agent=agent, thread_id=thread_id, model=model, user_id=user_id)
    runtime = await resolve_agent_runtime(agent)
    request_id = str(uuid.uuid4())
    context_overrides = build_context_overrides(request, runtime, thread_id)
    context_overrides["checkpoint_thread_id"] = f"{thread_id}:run:{request_id}"

    await ensure_conversation(
        conversation_id=thread_id,
        user_id=user_id,
        agent_id=runtime["agent_config_id"],
        agent_name=runtime["agent_name"],
        model_name=context_overrides.get("model"),
        first_message=transcript,
    )
    history_messages = await list_messages(thread_id)
    await append_message(conversation_id=thread_id, role="user", content=transcript)

    parts: list[str] = []
    async for chunk in stream_chat(
        message=transcript,
        agent_name=runtime["runtime_agent"],
        thread_id=thread_id,
        context_overrides=context_overrides,
        request_id=request_id,
        history_messages=history_messages,
    ):
        if chunk.get("status") == "loading" and chunk.get("content"):
            parts.append(str(chunk["content"]))

    reply = "".join(parts).strip()
    if reply:
        await append_message(conversation_id=thread_id, role="assistant", content=reply)
    return reply


@router.websocket("/call")
async def voice_call(websocket: WebSocket) -> None:
    from nexagent.services.speech import SpeechConfigError, synthesize, transcribe

    await websocket.accept()
    session: dict[str, Any] = {"agent": "chatbot", "thread_id": str(uuid.uuid4()), "model": None, "user_id": None}

    async def send_error(message: str) -> None:
        await websocket.send_json({"type": "error", "message": message})

    try:
        while True:
            event = await websocket.receive()
            if event.get("type") == "websocket.disconnect":
                break

            # Binary frame: an utterance's audio, transcribe + run a turn.
            if event.get("bytes") is not None:
                audio = event["bytes"]
                if not audio:
                    continue
                fmt = session.pop("pending_format", "webm")
                try:
                    transcript = await transcribe(audio, filename=f"turn.{fmt}", content_type=f"audio/{fmt}")
                except SpeechConfigError as exc:
                    await send_error(str(exc))
                    continue
                if not transcript.strip():
                    await send_error("没有识别到语音内容")
                    continue
                await websocket.send_json({"type": "transcript", "text": transcript})
                await _handle_turn(websocket, session, transcript, synthesize)
                continue

            # Text frame: a control / typed message.
            raw = event.get("text")
            if raw is None:
                continue
            import json

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await send_error("无效的消息格式")
                continue

            mtype = payload.get("type")
            if mtype == "start":
                session["agent"] = payload.get("agent") or "chatbot"
                session["thread_id"] = payload.get("thread_id") or session["thread_id"]
                session["model"] = payload.get("model") or None
                session["user_id"] = payload.get("user_id") or None
                await websocket.send_json({"type": "ready", "thread_id": session["thread_id"]})
            elif mtype == "utterance":
                session["pending_format"] = (payload.get("format") or "webm").replace("audio/", "")
            elif mtype == "text":
                message = str(payload.get("message") or "").strip()
                if not message:
                    continue
                await websocket.send_json({"type": "transcript", "text": message})
                await _handle_turn(websocket, session, message, synthesize)
            elif mtype == "bye":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — surface any failure to the client before closing
        try:
            await send_error(str(exc))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _handle_turn(websocket: WebSocket, session: dict[str, Any], transcript: str, synthesize) -> None:
    from nexagent.services.speech import SpeechConfigError

    reply = await run_voice_turn(
        transcript=transcript,
        agent=session["agent"],
        thread_id=session["thread_id"],
        model=session["model"],
        user_id=session["user_id"],
    )
    await websocket.send_json({"type": "reply", "text": reply})
    if not reply:
        return
    try:
        audio, mime = await synthesize(reply)
    except SpeechConfigError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        return
    await websocket.send_json({"type": "audio_start", "mime": mime})
    await websocket.send_bytes(audio)
    await websocket.send_json({"type": "audio_end"})
