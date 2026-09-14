"""REST routes for the News Curator: /api/briefings.

Serves briefings stored by the BriefingStoreBlock from the platform KV store
(per user). Mounted by deploy/customize.py patching rest_api.py:

    app.include_router(router, tags=["agentcloud"], prefix="/api/briefings")

Routes:
    GET /api/briefings         -> latest briefing record (404 if none yet)
    GET /api/briefings/history -> capped list of past briefings, newest first

Standalone testing: platform-only imports (autogpt_libs, backend.util.clients)
are guarded; tests inject a fake KV client by monkeypatching
``get_database_manager_async_client`` on this module and override the
``get_user_id`` dependency.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import fastapi
from fastapi import Security

from backend.blocks._briefing_store import BRIEFINGS_KV_KEY

logger = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only inside the AutoGPT Platform
    from autogpt_libs.auth import get_user_id, requires_user
    from backend.util.clients import get_database_manager_async_client
except ImportError:  # standalone / local development
    async def get_user_id() -> str:
        return "test-user"

    def requires_user() -> None:  # noqa: D401 - matches platform signature
        return None

    def get_database_manager_async_client() -> Any:  # pragma: no cover
        raise RuntimeError(
            "get_database_manager_async_client is only available inside the "
            "AutoGPT Platform; inject a fake in tests"
        )


router = fastapi.APIRouter()


async def _get_briefings(user_id: str) -> list[dict] | None:
    """Read the user's briefing history from the KV store."""
    return await get_database_manager_async_client().get_execution_kv_data(
        user_id=user_id, key=BRIEFINGS_KV_KEY
    )


@router.get(
    "",
    summary="Get the latest news briefing",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
)
async def get_latest_briefing(
    user_id: Annotated[str, Security(get_user_id)],
) -> dict[str, Any]:
    """Return the most recent briefing record for the authenticated user."""
    history = await _get_briefings(user_id) or []
    if not history:
        raise fastapi.HTTPException(
            status_code=404,
            detail="No briefing stored yet; wait for the first scheduled run.",
        )
    return history[0]


@router.get(
    "/history",
    summary="Get past news briefings",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
)
async def get_briefing_history(
    user_id: Annotated[str, Security(get_user_id)],
) -> list[dict[str, Any]]:
    """Return past briefings, newest first (capped by the store block)."""
    return await _get_briefings(user_id) or []
