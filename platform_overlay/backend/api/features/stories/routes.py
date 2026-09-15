"""REST routes for the Storyteller: /api/stories.

On-demand story generation backed by the AutoGen story team (story_writer ->
image_prompter -> story_editor) on the Gemini free tier, with a free
Pollinations.ai cover illustration URL built from the image prompter's
message.

Routes (authenticated like the platform's own feature routes):
    POST /api/stories/generate  -> {id, status: "pending"}; generation runs
                                   as a background task, the client polls
                                   GET /api/stories/{id} until status=ready
    GET  /api/stories           -> story history, newest first (capped)
    GET  /api/stories/{id}      -> single story record (404 if unknown)
    DELETE /api/stories/{id}    -> remove a story from history

Gemini key resolution: request body ``api_key`` -> ``GEMINI_API_KEY`` env var
(set it in autogpt_platform/.env; docker compose passes it to the server).
Never embed the key in the PWA.

Standalone testing: platform-only imports are guarded, and tests monkeypatch
``_generate_story_content`` plus the KV client on this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Annotated, Any

import fastapi
from fastapi import Security
from pydantic import BaseModel, Field

from backend.blocks._story_store import (
    STORIES_KV_KEY,
    add_to_story_history,
    find_in_history,
    make_story_record,
    pollinations_image_url,
    remove_from_history,
)

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


class GenerateStoryRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    language: str = Field(default="English", max_length=50)
    style: str = Field(default="", max_length=200)
    model: str = Field(default="gemini-2.5-flash", max_length=100)
    api_key: str = Field(default="", description="Gemini API key; falls back to GEMINI_API_KEY env")


async def _generate_story_content(
    topic: str, language: str, style: str, api_key: str, model: str
) -> tuple[str, list[dict]]:
    """Run the AutoGen story team; return (story_text, transcript).

    Imports lazily so this module (and its tests) import without the
    autogen packages installed.
    """
    from backend.blocks.autogen_team import (
        build_gemini_client,
        build_team,
        run_team_with_retry,
    )

    task = f"Write a short story about: {topic}. Language: {language}."
    if style:
        task += f" Style: {style}."

    client = build_gemini_client(api_key=api_key, model=model)
    team = build_team("story", model_client=client)
    story_text, transcript = await run_team_with_retry(team, task=task)
    return story_text, transcript


async def _get_history(user_id: str) -> list[dict] | None:
    return await get_database_manager_async_client().get_execution_kv_data(
        user_id=user_id, key=STORIES_KV_KEY
    )


async def _set_history(user_id: str, data: list[dict]) -> None:
    # Note: set_execution_kv_data needs a node_exec_id in some platform
    # versions; outside a block execution we pass an empty string, which
    # the KV store accepts for user-scoped keys.
    await get_database_manager_async_client().set_execution_kv_data(
        user_id=user_id, node_exec_id="", key=STORIES_KV_KEY, data=data
    )


async def _generate_and_store(
    story_id: str, user_id: str, req: GenerateStoryRequest, api_key: str
) -> None:
    """Background task: run the team, then flip the pending record to ready/failed."""
    try:
        story_text, transcript = await _generate_story_content(
            topic=req.topic,
            language=req.language,
            style=req.style,
            api_key=api_key,
            model=req.model,
        )
        if not story_text or not story_text.strip():
            raise ValueError("The story team returned an empty story")

        # Extract the image prompt from the transcript and build the URL.
        from backend.blocks._story_store import extract_image_prompt

        image_prompt = extract_image_prompt(transcript)
        image_url = pollinations_image_url(image_prompt)

        history = await _get_history(user_id) or []
        pending = find_in_history(history, story_id)
        if pending is None:
            # History was capped and the pending record fell out; re-insert.
            record = make_story_record(
                topic=req.topic,
                language=req.language,
                story_text=story_text,
                image_prompt=image_prompt,
                image_url=image_url,
                style=req.style,
            )
            record["id"] = story_id  # keep the id the client is polling
            updated = add_to_story_history(history, record)
        else:
            pending.update(
                {
                    "story": story_text,
                    "image_prompt": image_prompt,
                    "image_url": image_url,
                    "status": "ready",
                }
            )
            # refresh the title from the actual story text
            from backend.blocks._story_store import parse_title

            pending["title"] = parse_title(story_text)
            updated = history
        await _set_history(user_id, updated)
    except Exception as e:  # noqa: BLE001 - background task must never raise
        logger.exception("Story generation failed for %s", story_id)
        history = await _get_history(user_id) or []
        failed = find_in_history(history, story_id)
        if failed is not None:
            failed["status"] = "failed"
            failed["error"] = str(e)[:500]
            await _set_history(user_id, history)


@router.post(
    "/generate",
    summary="Generate a new story (async)",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
    status_code=202,
)
async def generate_story(
    req: GenerateStoryRequest,
    user_id: Annotated[str, Security(get_user_id)],
) -> dict[str, Any]:
    """Start story generation in the background; poll GET /api/stories/{id}."""
    api_key = req.api_key.strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise fastapi.HTTPException(
            status_code=400,
            detail="No Gemini API key: pass api_key in the request or set "
            "GEMINI_API_KEY in the server environment.",
        )

    record = make_story_record(
        topic=req.topic,
        language=req.language,
        style=req.style,
        story_text="",
        status="pending",
    )
    history = await _get_history(user_id) or []
    updated = add_to_story_history(history, record)
    await _set_history(user_id, updated)

    asyncio.get_running_loop().create_task(
        _generate_and_store(record["id"], user_id, req, api_key)
    )
    return {"id": record["id"], "status": "pending"}


@router.get(
    "",
    summary="List stories",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
)
async def list_stories(
    user_id: Annotated[str, Security(get_user_id)],
) -> list[dict[str, Any]]:
    """Return the story history, newest first (capped)."""
    return await _get_history(user_id) or []


@router.get(
    "/{story_id}",
    summary="Get a story",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
)
async def get_story(
    story_id: str,
    user_id: Annotated[str, Security(get_user_id)],
) -> dict[str, Any]:
    """Return a single story record."""
    history = await _get_history(user_id) or []
    record = find_in_history(history, story_id)
    if record is None:
        raise fastapi.HTTPException(status_code=404, detail="Story not found")
    return record


@router.delete(
    "/{story_id}",
    summary="Delete a story",
    tags=["agentcloud", "private"],
    dependencies=[Security(requires_user)],
    status_code=204,
)
async def delete_story(
    story_id: str,
    user_id: Annotated[str, Security(get_user_id)],
) -> None:
    """Remove a story from history."""
    history = await _get_history(user_id) or []
    if find_in_history(history, story_id) is None:
        raise fastapi.HTTPException(status_code=404, detail="Story not found")
    await _set_history(user_id, remove_from_history(history, story_id))
