"""Story store block for the AutoGPT Platform (Storyteller pipeline).

Takes the story team's final text and full transcript, extracts the cover
image prompt (the image_prompter agent's last message), builds the free
Pollinations.ai image URL, and stores the finished story in the platform KV
store as a capped history list for /api/stories.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.blocks._block_shim import (
    Block,
    BlockCategory,
    BlockOutput,
    BlockSchemaInput,
    BlockSchemaOutput,
    SchemaField,
    get_database_manager_async_client,
)
from backend.blocks._story_store import (
    STORY_HISTORY_CAP,
    STORIES_KV_KEY,
    add_to_story_history,
    extract_image_prompt,
    make_story_record,
    pollinations_image_url,
)

logger = logging.getLogger(__name__)


class StoryStoreBlockInput(BlockSchemaInput):
    story: str = SchemaField(
        description="Final story text from the AutoGen story team (title on the first line)."
    )
    transcript: list[dict] = SchemaField(
        description="Full team transcript ({source, content} dicts); the "
        "image_prompter's message becomes the cover illustration prompt.",
        default=[],
    )
    topic: str = SchemaField(
        description="The topic the story was requested for.", default=""
    )
    language: str = SchemaField(
        description="Language the story was written in.", default="English"
    )
    image_width: int = SchemaField(
        description="Cover image width (px).", default=768, ge=64, le=2048
    )
    image_height: int = SchemaField(
        description="Cover image height (px).", default=768, ge=64, le=2048
    )
    history_cap: int = SchemaField(
        description="Max number of stories to retain.",
        default=STORY_HISTORY_CAP,
        ge=1,
        le=500,
    )


class StoryStoreBlockOutput(BlockSchemaOutput):
    stored: dict = SchemaField(description="The story record that was stored.")
    status: str = SchemaField(description="'stored' on success.")


class StoryStoreBlock(Block):
    def __init__(self):
        super().__init__(
            id="c3a1f2b3-1111-4e2a-9c1d-000000000003",
            input_schema=StoryStoreBlockInput,
            output_schema=StoryStoreBlockOutput,
            description=(
                "Finalizes a story: extracts the cover image prompt from the "
                "AutoGen transcript, builds a free Pollinations.ai image URL, "
                "and stores the story in the KV store for /api/stories."
            ),
            categories={BlockCategory.OUTPUT},
            test_input={
                "story": "The Mongoose and the Cobra\n\nOnce upon a time...",
                "transcript": [
                    {"source": "story_writer", "content": "draft"},
                    {
                        "source": "image_prompter",
                        "content": "storybook illustration of a brave mongoose facing a cobra, warm colors",
                    },
                    {"source": "story_editor", "content": "final"},
                ],
                "topic": "a brave mongoose",
                "language": "English",
            },
            test_output=[
                ("status", "stored"),
            ],
            test_mock={
                "_retrieve_history": lambda *a, **k: [],
                "_store_history": lambda *a, **k: None,
            },
        )

    async def run(
        self,
        input_data: StoryStoreBlockInput,
        *,
        user_id: str,
        node_exec_id: str,
        **kwargs: Any,
    ) -> BlockOutput:
        if not input_data.story.strip():
            yield "status", "empty"
            return

        image_prompt = extract_image_prompt(input_data.transcript)
        image_url = pollinations_image_url(
            image_prompt,
            width=input_data.image_width,
            height=input_data.image_height,
        )

        history = await self._retrieve_history(user_id=user_id) or []
        record = make_story_record(
            topic=input_data.topic,
            language=input_data.language,
            story_text=input_data.story,
            image_prompt=image_prompt,
            image_url=image_url,
        )
        updated = add_to_story_history(history, record, cap=input_data.history_cap)
        await self._store_history(
            user_id=user_id,
            node_exec_id=node_exec_id,
            data=updated,
        )
        yield "stored", record
        yield "status", "stored"

    async def _retrieve_history(self, user_id: str) -> list[dict] | None:
        return await get_database_manager_async_client().get_execution_kv_data(
            user_id=user_id, key=STORIES_KV_KEY
        )

    async def _store_history(
        self, user_id: str, node_exec_id: str, data: list[dict]
    ) -> Any:
        return await get_database_manager_async_client().set_execution_kv_data(
            user_id=user_id, node_exec_id=node_exec_id, key=STORIES_KV_KEY, data=data
        )
