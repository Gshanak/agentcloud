"""API routes for the standalone server.

The same surface the AutoGPT-platform overlay exposes — /api/briefings,
/api/stories, /api/push — plus /api/health for keep-alive pingers, all
behind one bearer token (or open in local dev).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable

import fastapi
from fastapi import Security
from pydantic import BaseModel, Field

from backend.blocks._briefing_store import BRIEFINGS_KV_KEY
from backend.blocks._story_store import (
    STORIES_KV_KEY,
    add_to_story_history,
    find_in_history,
    make_story_record,
    pollinations_image_url,
    remove_from_history,
)
from server import push as push_mod
from server.news_job import run_news_job

logger = logging.getLogger(__name__)


class GenerateStoryRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    language: str = Field(default="English", max_length=50)
    style: str = Field(default="", max_length=200)
    model: str = Field(default="gemini-2.5-flash", max_length=100)
    api_key: str = Field(default="", description="Gemini key; falls back to GEMINI_API_KEY")


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict
    user_agent: str = ""


def build_router(get_user_id: Callable) -> fastapi.APIRouter:
    """Build the API router with the given auth dependency.

    Request models live at module level: with ``from __future__ import
    annotations`` FastAPI resolves stringified annotations against module
    globals, so classes defined in this closure would not be found.
    """
    router = fastapi.APIRouter()

    # ------------------------------------------------------------- health

    @router.get("/api/health", summary="Liveness probe (keep-alive pinger target)")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # --------------------------------------------------------- briefings

    @router.get("/api/briefings", summary="Latest news briefing")
    async def latest_briefing(user_id: str = Security(get_user_id)) -> dict[str, Any]:
        history = await _get_store().get(user_id, BRIEFINGS_KV_KEY) or []
        if not history:
            raise fastapi.HTTPException(
                status_code=404, detail="No briefing stored yet; wait for the first scheduled run."
            )
        return history[0]

    @router.get("/api/briefings/history", summary="Past briefings")
    async def briefing_history(user_id: str = Security(get_user_id)) -> list[dict[str, Any]]:
        return await _get_store().get(user_id, BRIEFINGS_KV_KEY) or []

    # ------------------------------------------------------------ stories

    async def _generate_and_store(
        story_id: str, user_id: str, req: GenerateStoryRequest, api_key: str
    ) -> None:
        store = _get_store()
        try:
            from backend.blocks._story_store import extract_image_prompt, parse_title
            from backend.blocks.autogen_team import (
                build_gemini_client,
                run_team_with_retry,
            )

            task = f"Write a short story about: {req.topic}. Language: {req.language}."
            if req.style:
                task += f" Style: {req.style}."
            client = build_gemini_client(api_key=api_key, model=req.model)
            story_text, transcript = await run_team_with_retry(
                task=task, profile_name="story", model_client=client
            )
            if not story_text or not story_text.strip():
                raise ValueError("The story team returned an empty story")

            image_prompt = extract_image_prompt(transcript)
            history = await store.get(user_id, STORIES_KV_KEY) or []
            pending = find_in_history(history, story_id)
            if pending is None:
                record = make_story_record(
                    topic=req.topic, language=req.language, story_text=story_text,
                    image_prompt=image_prompt, image_url=pollinations_image_url(image_prompt),
                    style=req.style,
                )
                record["id"] = story_id
                updated = add_to_story_history(history, record)
            else:
                pending.update({
                    "story": story_text, "title": parse_title(story_text),
                    "image_prompt": image_prompt,
                    "image_url": pollinations_image_url(image_prompt),
                    "status": "ready",
                })
                updated = history
            await store.set(user_id, STORIES_KV_KEY, updated)
        except Exception as e:  # noqa: BLE001 - background task must never raise
            logger.exception("Story generation failed for %s", story_id)
            history = await store.get(user_id, STORIES_KV_KEY) or []
            failed = find_in_history(history, story_id)
            if failed is not None:
                failed["status"] = "failed"
                failed["error"] = str(e)[:500]
                await store.set(user_id, STORIES_KV_KEY, history)

    @router.post("/api/stories/generate", summary="Generate a story (async)", status_code=202)
    async def generate_story(req: GenerateStoryRequest, user_id: str = Security(get_user_id)) -> dict[str, Any]:
        api_key = req.api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise fastapi.HTTPException(
                status_code=400,
                detail="No Gemini API key: pass api_key in the request or set GEMINI_API_KEY.",
            )
        store = _get_store()
        record = make_story_record(
            topic=req.topic, language=req.language, style=req.style,
            story_text="", status="pending",
        )
        history = await store.get(user_id, STORIES_KV_KEY) or []
        await store.set(user_id, STORIES_KV_KEY, add_to_story_history(history, record))
        asyncio.get_running_loop().create_task(
            _generate_and_store(record["id"], user_id, req, api_key)
        )
        return {"id": record["id"], "status": "pending"}

    @router.get("/api/stories", summary="Story library")
    async def list_stories(user_id: str = Security(get_user_id)) -> list[dict[str, Any]]:
        return await _get_store().get(user_id, STORIES_KV_KEY) or []

    @router.get("/api/stories/{story_id}", summary="Get a story")
    async def get_story(story_id: str, user_id: str = Security(get_user_id)) -> dict[str, Any]:
        history = await _get_store().get(user_id, STORIES_KV_KEY) or []
        record = find_in_history(history, story_id)
        if record is None:
            raise fastapi.HTTPException(status_code=404, detail="Story not found")
        return record

    @router.delete("/api/stories/{story_id}", summary="Delete a story", status_code=204)
    async def delete_story(story_id: str, user_id: str = Security(get_user_id)) -> None:
        store = _get_store()
        history = await store.get(user_id, STORIES_KV_KEY) or []
        if find_in_history(history, story_id) is None:
            raise fastapi.HTTPException(status_code=404, detail="Story not found")
        await store.set(user_id, STORIES_KV_KEY, remove_from_history(history, story_id))

    # --------------------------------------------------------------- push

    @router.get("/api/push/vapid-key", summary="VAPID public key")
    async def vapid_key() -> dict[str, str]:
        return {"public_key": await push_mod.get_vapid_public_key(_get_store())}

    @router.post("/api/push/subscribe", summary="Register a push subscription", status_code=204)
    async def subscribe(body: SubscribeRequest) -> None:
        await push_mod.save_subscription(
            _get_store(), {"endpoint": body.endpoint, "keys": body.keys}
        )

    @router.post("/api/push/unsubscribe", summary="Remove a push subscription", status_code=204)
    async def unsubscribe(body: dict) -> None:
        await push_mod.remove_subscription(_get_store(), body.get("endpoint", ""))

    # The store is injected by app.py at startup; late-bound through a
    # module-level accessor so routes stay testable.
    _store_holder: dict[str, Any] = {}

    def _get_store():
        return _store_holder["store"]

    def set_store(store) -> None:
        _store_holder["store"] = store

    router.set_store = set_store  # type: ignore[attr-defined]
    return router
