"""Embedded Python SDK for NexAgent Gateway."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class NexAgentClient:
    """Small async client for embedding NexAgent in Python applications."""

    base_url: str = "http://localhost:8001"
    timeout: float = 60.0

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get("/health")
            response.raise_for_status()
            return response.json()

    async def models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get("/api/models")
            response.raise_for_status()
            return response.json().get("models", [])

    async def chat(
        self,
        message: str,
        *,
        agent: str = "chatbot",
        model: str | None = None,
        thread_id: str | None = None,
        tools: list[str] | None = None,
        kb_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "message": message,
            "agent": agent,
            "model": model,
            "thread_id": thread_id,
            "tools": tools or [],
            "kb_ids": kb_ids or [],
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/api/chat/", json=payload)
            response.raise_for_status()
            return response.json()

    async def stream_chat(
        self,
        message: str,
        *,
        agent: str = "chatbot",
        model: str | None = None,
        thread_id: str | None = None,
        tools: list[str] | None = None,
        kb_ids: list[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {
            "message": message,
            "agent": agent,
            "model": model,
            "thread_id": thread_id,
            "tools": tools or [],
            "kb_ids": kb_ids or [],
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            async with client.stream("POST", "/api/chat/stream", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield json.loads(line)

    async def list_knowledge_bases(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get("/api/knowledge/")
            response.raise_for_status()
            return response.json().get("knowledge_bases", [])

    async def create_knowledge_base(
        self,
        name: str,
        *,
        kb_type: str = "milvus",
        description: str = "",
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        chunk_preset_id: str = "general",
        chunk_parser_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "kb_type": kb_type,
            "description": description,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "chunk_preset_id": chunk_preset_id,
            "chunk_parser_config": chunk_parser_config or {},
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/api/knowledge/", json=payload)
            response.raise_for_status()
            return response.json()

    async def upload_text_file(self, kb_id: str, filename: str, content: str) -> dict[str, Any]:
        files = {"file": (filename, content.encode("utf-8"), "text/plain")}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post(f"/api/knowledge/{kb_id}/files", files=files)
            response.raise_for_status()
            return response.json()

    async def process_file(self, kb_id: str, file_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post(f"/api/knowledge/{kb_id}/files/{file_id}/process")
            response.raise_for_status()
            return response.json()

    async def search_knowledge_base(self, kb_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post(
                f"/api/knowledge/{kb_id}/search",
                json={"query": query, "top_k": top_k},
            )
            response.raise_for_status()
            return response.json().get("results", [])

    async def channels(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get("/api/channels/")
            response.raise_for_status()
            return response.json().get("channels", [])

    async def send_channel_message(
        self,
        channel: str,
        text: str,
        *,
        user_id: str = "sdk",
        agent: str = "chatbot",
        model: str | None = None,
    ) -> dict[str, Any]:
        payload = {"text": text, "user_id": user_id, "agent": agent, "model": model}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post(f"/api/channels/{channel}/webhook", json=payload)
            response.raise_for_status()
            return response.json()

    async def memory(self, user_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.get(f"/api/memory/{user_id}")
            response.raise_for_status()
            return response.json().get("memory", {})

    async def set_memory(self, user_id: str, key: str, value: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post(f"/api/memory/{user_id}", json={"key": key, "value": value})
            response.raise_for_status()
            return response.json()

    async def run_subagents(self, tasks: list[dict[str, Any]], max_concurrency: int = 3) -> dict[str, Any]:
        payload = {"tasks": tasks, "max_concurrency": max_concurrency}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            response = await client.post("/api/agents/subagents/run", json=payload)
            response.raise_for_status()
            return response.json()
