"""Simple bearer-token auth for the standalone server.

Single-user personal deployment: one shared token set as the AUTH_TOKEN
secret. The PWAs send it as "Authorization: Bearer <token>". If AUTH_TOKEN
is unset (local dev), auth is disabled and every request is treated as the
owner.
"""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)
OWNER_USER_ID = "owner"


def get_user_id_factory(auth_token: str):
    """Build a FastAPI dependency that validates the shared token."""

    async def get_user_id(
        creds: HTTPAuthorizationCredentials | None = Security(_bearer),
    ) -> str:
        if not auth_token:
            return OWNER_USER_ID  # dev mode: auth disabled
        if creds is None or creds.credentials != auth_token:
            raise HTTPException(status_code=401, detail="Invalid or missing token")
        return OWNER_USER_ID

    return get_user_id
