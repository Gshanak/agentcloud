"""Pure helpers for the Storyteller pipeline. No platform imports.

Shared by the StoryStoreBlock and the /api/stories route, so both agree on
record shapes, KV keys, the Pollinations URL scheme, and how the image
prompt is extracted from the AutoGen team transcript.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

STORIES_KV_KEY = "global#stories"
STORY_HISTORY_CAP = 50

# Pollinations.ai free image API — a GET URL that renders an image from a
# text prompt. No key, no quota; the URL itself IS the image.
POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"


def pollinations_image_url(
    prompt: str,
    width: int = 768,
    height: int = 768,
    seed: int | None = None,
) -> str:
    """Build a deterministic Pollinations image URL from a text prompt.

    A stable seed (derived from the prompt hash) keeps the image consistent
    across refetches so the browser/service worker can cache it reliably.
    """
    if not prompt or not prompt.strip():
        prompt = "storybook illustration"
    if seed is None:
        seed = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8], 16)
    return (
        f"{POLLINATIONS_BASE}{quote(prompt.strip())}"
        f"?width={width}&height={height}&nologo=true&seed={seed}"
    )


def parse_title(story_text: str) -> str:
    """Extract the title (first non-empty line) from the story text."""
    for line in (story_text or "").splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return "Untitled Story"


def extract_image_prompt(transcript: list[dict] | None) -> str:
    """Find the image prompter's last message in the team transcript.

    The story team's transcript is a list of {source, content} dicts.
    The image_prompter agent produces a single English image-generation
    prompt; we take its last (most refined) occurrence.
    """
    if not transcript:
        return ""
    for msg in reversed(transcript):
        if msg.get("source") == "image_prompter":
            content = (msg.get("content") or "").strip()
            if content:
                return content
    return ""


def make_story_record(
    topic: str,
    language: str,
    story_text: str,
    image_prompt: str = "",
    image_url: str = "",
    style: str = "",
    status: str = "ready",
) -> dict:
    """Build one story record for storage and API responses."""
    title = parse_title(story_text)
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "topic": topic,
        "language": language,
        "style": style,
        "story": story_text,
        "image_prompt": image_prompt,
        "image_url": image_url,
        "status": status,
    }


def add_to_story_history(
    history: list[dict] | None, record: dict, cap: int = STORY_HISTORY_CAP
) -> list[dict]:
    """Prepend a record to the story history, capped at ``cap`` entries."""
    updated = list(history or [])
    updated.insert(0, record)
    return updated[:cap]


def find_in_history(history: list[dict] | None, story_id: str) -> dict | None:
    """Find a single story record by id."""
    for record in history or []:
        if record.get("id") == story_id:
            return record
    return None


def remove_from_history(history: list[dict] | None, story_id: str) -> list[dict]:
    """Return a copy of history with the given story id removed."""
    return [r for r in (history or []) if r.get("id") != story_id]
