"""FastAPI dependencies for API key auth."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.gateway.auth.manager import verify_api_key

bearer = HTTPBearer(auto_error=False)


def require_api_key(scope: str | None = None):
    async def _dependency(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        key = verify_api_key(credentials.credentials, required_scope=scope)
        if key is None:
            raise HTTPException(status_code=403, detail="Invalid API key or missing scope")
        return key.public_dict()

    return _dependency
