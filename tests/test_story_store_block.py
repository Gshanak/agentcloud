"""Tests for the StoryStoreBlock (standalone shim mode).

KV access is faked by overriding the block's _retrieve_history/_store_history
methods, matching the platform's test_mock injection pattern.
"""

import pytest

from backend.blocks._story_store import STORIES_KV_KEY
from backend.blocks.story_store_block import StoryStoreBlock, StoryStoreBlockInput


TRANSCRIPT = [
    {"source": "story_writer", "content": "draft"},
    {"source": "image_prompter", "content": "storybook illustration of a brave mongoose"},
    {"source": "story_editor", "content": "The Mongoose\n\nOnce upon a time..."},
]


def make_block(kv_store):
    """Build a StoryStoreBlock wired to an in-memory KV dict."""
    block = StoryStoreBlock()

    async def fake_retrieve(user_id):
        return kv_store.get("history")

    async def fake_store(user_id, node_exec_id, data):
        kv_store["history"] = data
        return data

    block._retrieve_history = fake_retrieve
    block._store_history = fake_store
    return block


@pytest.mark.asyncio
async def test_store_block_extracts_image_and_stores():
    kv = {}
    block = make_block(kv)

    outputs = {
        name: value
        async for name, value in block.run(
            StoryStoreBlockInput(
                story="The Mongoose\n\nOnce upon a time...",
                transcript=TRANSCRIPT,
                topic="a brave mongoose",
                language="English",
            ),
            user_id="u1",
            node_exec_id="n1",
        )
    }
    assert outputs["status"] == "stored"
    record = outputs["stored"]
    assert record["title"] == "The Mongoose"
    assert record["topic"] == "a brave mongoose"
    assert record["image_prompt"] == "storybook illustration of a brave mongoose"
    assert record["image_url"].startswith("https://image.pollinations.ai/prompt/")
    assert record["status"] == "ready"
    assert len(kv["history"]) == 1


@pytest.mark.asyncio
async def test_store_block_prepends_to_existing_history():
    kv = {"history": [
        {"id": "old", "title": "Old Story", "story": "old", "status": "ready"},
    ]}
    block = make_block(kv)

    outputs = {
        name: value
        async for name, value in block.run(
            StoryStoreBlockInput(
                story="New Story\n\nText...",
                transcript=TRANSCRIPT,
                topic="new topic",
                language="Hindi",
            ),
            user_id="u1",
            node_exec_id="n1",
        )
    }
    assert len(kv["history"]) == 2
    assert kv["history"][0]["title"] == "New Story"
    assert kv["history"][1]["title"] == "Old Story"
    assert kv["history"][0]["language"] == "Hindi"


@pytest.mark.asyncio
async def test_store_block_empty_story_skips():
    kv = {}
    block = make_block(kv)

    async def fake_store(user_id, node_exec_id, data):  # pragma: no cover
        raise AssertionError("must not store on empty story")

    block._store_history = fake_store

    outputs = [
        item
        async for item in block.run(
            StoryStoreBlockInput(story="   ", transcript=[]),
            user_id="u1",
            node_exec_id="n1",
        )
    ]
    assert outputs == [("status", "empty")]


@pytest.mark.asyncio
async def test_store_block_missing_image_prompt_still_works():
    kv = {}
    block = make_block(kv)

    outputs = {
        name: value
        async for name, value in block.run(
            StoryStoreBlockInput(
                story="A Story\n\nBody",
                transcript=[{"source": "story_writer", "content": "just a draft"}],
                topic="test",
                language="English",
            ),
            user_id="u1",
            node_exec_id="n1",
        )
    }
    assert outputs["status"] == "stored"
    assert outputs["stored"]["image_prompt"] == ""
    # fallback prompt used for the URL
    assert "storybook" in outputs["stored"]["image_url"]


def test_store_block_metadata():
    block = StoryStoreBlock()
    assert block.id == "c3a1f2b3-1111-4e2a-9c1d-000000000003"
    assert "_retrieve_history" in (block.test_mock or {})
    assert "_store_history" in (block.test_mock or {})
