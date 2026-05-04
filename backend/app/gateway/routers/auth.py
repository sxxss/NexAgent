"""API key management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class APIKeyCreate(BaseModel):
    user_id: str
    name: str
    scopes: list[str] = ["*"]
    expires_at: str | None = None


@router.get("/api-keys")
async def list_keys(user_id: str | None = Query(default=None)):
    from app.gateway.auth.manager import list_api_keys

    return {"api_keys": list_api_keys(user_id=user_id)}


@router.post("/api-keys", status_code=201)
async def create_key(body: APIKeyCreate):
    from app.gateway.auth.manager import create_api_key

    return create_api_key(
        user_id=body.user_id,
        name=body.name,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: str):
    from app.gateway.auth.manager import revoke_api_key

    if not revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
