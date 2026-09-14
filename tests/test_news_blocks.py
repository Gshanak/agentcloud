"""Tests for the NewsDedupBlock and BriefingStoreBlock (standalone shim mode).

KV access is faked by overriding the blocks' _retrieve_seen/_store_seen and
_retrieve_history/_store_history methods, matching the platform's test_mock
injection pattern.
"""

import pytest

from backend.blocks._briefing_store import BRIEFINGS_KV_KEY
from backend.blocks.briefing_store_block import (
    BriefingStoreBlock,
    BriefingStoreBlockInput,
)
from backend.blocks.news_dedup_block import NewsDedupBlock, NewsDedupBlockInput
from backend.blocks._briefing_store import article_hash


def entry(title: str, link: str, description: str = "desc") -> dict:
    return {
        "title": title,
        "link": link,
        "description": description,
        "author": "Reporter",
        "pub_date": "2026-09-14T00:00:00+00:00",
    }


async def run_dedup(entries, seen=None):
    """Run the dedup block with an in-memory KV dict; return outputs + KV."""
    block = NewsDedupBlock()
    kv: dict = {"seen": seen or {}}

    async def fake_retrieve(user_id, key):
        return kv["seen"]

    async def fake_store(user_id, node_exec_id, key, data):
        kv["seen"] = data
        return data

    block._retrieve_seen = fake_retrieve
    block._store_seen = fake_store
    outputs = {
        name: value
        async for name, value in block.run(
            NewsDedupBlockInput(entries=entries),
            user_id="u1",
            node_exec_id="n1",
        )
    }
    return outputs, kv["seen"]


# ------------------------------------------------------------------ dedup

@pytest.mark.asyncio
async def test_dedup_passes_all_entries_first_time():
    outputs, seen = await run_dedup([entry("A", "https://a"), entry("B", "https://b")])
    assert outputs["new_count"] == 2
    assert outputs["total_count"] == 2
    assert len(outputs["new_entries"]) == 2
    assert len(seen) == 2
    assert "## A" in outputs["formatted_context"]
    assert "## B" in outputs["formatted_context"]


@pytest.mark.asyncio
async def test_dedup_drops_previously_seen_entries():
    seen = {article_hash("A", "https://a"): "2026-09-13T00:00:00+00:00"}
    outputs, seen_after = await run_dedup(
        [entry("A", "https://a"), entry("B", "https://b")], seen=seen
    )
    assert outputs["new_count"] == 1
    assert [e["title"] for e in outputs["new_entries"]] == ["B"]
    assert "## A" not in outputs["formatted_context"]
    assert len(seen_after) == 2


@pytest.mark.asyncio
async def test_dedup_all_seen_yields_empty_context():
    seen = {article_hash("A", "https://a"): "2026-09-13T00:00:00+00:00"}
    outputs, _ = await run_dedup([entry("A", "https://a")], seen=seen)
    assert outputs["new_count"] == 0
    assert outputs["formatted_context"] == ""
    assert outputs["total_count"] == 1


@pytest.mark.asyncio
async def test_dedup_handles_empty_input():
    outputs, seen = await run_dedup([])
    assert outputs["new_count"] == 0
    assert outputs["total_count"] == 0
    assert outputs["formatted_context"] == ""
    assert seen == {}


def test_dedup_block_metadata():
    block = NewsDedupBlock()
    assert block.id == "c3a1f2b3-1111-4e2a-9c1d-000000000001"
    assert "_retrieve_seen" in (block.test_mock or {})
    assert "_store_seen" in (block.test_mock or {})


# ------------------------------------------------------------------ store

@pytest.mark.asyncio
async def test_store_block_records_latest_and_history():
    block = BriefingStoreBlock()
    kv: dict = {"history": []}

    async def fake_retrieve(user_id):
        return kv["history"]

    async def fake_store(user_id, node_exec_id, data):
        kv["history"] = data
        return data

    block._retrieve_history = fake_retrieve
    block._store_history = fake_store

    run_kwargs = {"user_id": "u1", "node_exec_id": "n1"}

    outputs1 = {
        name: value
        async for name, value in block.run(
            BriefingStoreBlockInput(briefing="first briefing", article_count=2),
            **run_kwargs,
        )
    }
    assert outputs1["status"] == "stored"
    assert outputs1["stored"]["briefing"] == "first briefing"
    assert len(kv["history"]) == 1

    outputs2 = {
        name: value
        async for name, value in block.run(
            BriefingStoreBlockInput(briefing="second briefing", article_count=5),
            **run_kwargs,
        )
    }
    assert len(kv["history"]) == 2
    assert kv["history"][0]["briefing"] == "second briefing"  # newest first
    assert kv["history"][1]["briefing"] == "first briefing"
    assert outputs2["stored"]["article_count"] == 5


@pytest.mark.asyncio
async def test_store_block_skips_empty_briefing():
    block = BriefingStoreBlock()

    async def fake_retrieve(user_id):
        return None

    async def fake_store(user_id, node_exec_id, data):  # pragma: no cover
        raise AssertionError("must not store on empty briefing")

    block._retrieve_history = fake_retrieve
    block._store_history = fake_store

    outputs = [
        item
        async for item in block.run(
            BriefingStoreBlockInput(briefing="   "),
            user_id="u1",
            node_exec_id="n1",
        )
    ]
    assert outputs == [("status", "empty")]


def test_store_block_metadata():
    block = BriefingStoreBlock()
    assert block.id == "c3a1f2b3-1111-4e2a-9c1d-000000000002"
    assert "_retrieve_history" in (block.test_mock or {})
    assert "_store_history" in (block.test_mock or {})
