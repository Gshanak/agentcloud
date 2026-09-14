"""News dedup block for the AutoGPT Platform (News Curator pipeline).

Takes a list of RSS entry dicts, drops articles already seen in previous
runs (by SHA-256 of title + link, persisted in the platform KV store), and
outputs only the new entries plus a formatted text context for the AutoGen
team. Dedup runs BEFORE any LLM call so free-tier quota is never spent on a
repeat article.
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
from backend.blocks._briefing_store import (
    SEEN_HASHES_KV_KEY_PREFIX,
    article_hash,
    format_entries_as_context,
    merge_seen_hashes,
)

logger = logging.getLogger(__name__)


class NewsDedupBlockInput(BlockSchemaInput):
    entries: list[dict] = SchemaField(
        description="RSS entries (list of dicts with title/link/description) "
        "to filter against previously seen articles.",
    )
    dedup_key: str = SchemaField(
        description="KV key suffix for the seen-hash set.",
        default="news_seen_hashes",
    )
    max_hashes: int = SchemaField(
        description="Cap on stored article hashes (oldest pruned first).",
        default=5000,
        ge=100,
        le=50_000,
    )


class NewsDedupBlockOutput(BlockSchemaOutput):
    new_entries: list[dict] = SchemaField(
        description="Entries not seen in any previous run."
    )
    formatted_context: str = SchemaField(
        description="New entries rendered as text for the AutoGen team context."
    )
    new_count: int = SchemaField(description="Number of new entries.")
    total_count: int = SchemaField(description="Number of entries received.")


class NewsDedupBlock(Block):
    def __init__(self):
        super().__init__(
            id="c3a1f2b3-1111-4e2a-9c1d-000000000001",
            input_schema=NewsDedupBlockInput,
            output_schema=NewsDedupBlockOutput,
            description=(
                "Filters RSS entries against previously seen articles "
                "(SHA-256 of title + link, persisted across runs) and formats "
                "the new ones as context text for the AutoGen news team. "
                "Run this BEFORE the LLM step so no quota is wasted on repeats."
            ),
            categories={BlockCategory.DATA},
            test_input={
                "entries": [
                    {
                        "title": "Example item",
                        "link": "https://example.com/a",
                        "description": "Something happened.",
                        "author": "Reporter",
                        "pub_date": "2026-09-14T00:00:00+00:00",
                    }
                ],
            },
            test_output=[
                ("new_count", 1),
                ("total_count", 1),
            ],
            test_mock={
                "_retrieve_seen": lambda *a, **k: {},
                "_store_seen": lambda *a, **k: None,
            },
        )

    async def run(
        self,
        input_data: NewsDedupBlockInput,
        *,
        user_id: str,
        node_exec_id: str,
        **kwargs: Any,
    ) -> BlockOutput:
        storage_key = f"global#{input_data.dedup_key}"
        if input_data.dedup_key.startswith("global#"):
            storage_key = input_data.dedup_key
        # Default suffix matches the shared helper prefix for consistency.
        if not input_data.dedup_key.startswith("global#"):
            if input_data.dedup_key == "news_seen_hashes":
                storage_key = SEEN_HASHES_KV_KEY_PREFIX

        seen = await self._retrieve_seen(user_id=user_id, key=storage_key) or {}

        new_entries: list[dict] = []
        new_hashes: list[str] = []
        for entry in input_data.entries or []:
            digest = article_hash(
                str(entry.get("title") or ""), str(entry.get("link") or "")
            )
            if digest in seen:
                continue
            new_entries.append(entry)
            new_hashes.append(digest)

        if new_hashes:
            updated = merge_seen_hashes(seen, new_hashes, cap=input_data.max_hashes)
            await self._store_seen(
                user_id=user_id,
                node_exec_id=node_exec_id,
                key=storage_key,
                data=updated,
            )
        else:
            logger.info("No new articles; seen set unchanged")

        yield "new_entries", new_entries
        yield "formatted_context", format_entries_as_context(new_entries)
        yield "new_count", len(new_entries)
        yield "total_count", len(input_data.entries or [])

    async def _retrieve_seen(self, user_id: str, key: str) -> dict | None:
        return await get_database_manager_async_client().get_execution_kv_data(
            user_id=user_id, key=key
        )

    async def _store_seen(
        self, user_id: str, node_exec_id: str, key: str, data: dict
    ) -> Any:
        return await get_database_manager_async_client().set_execution_kv_data(
            user_id=user_id, node_exec_id=node_exec_id, key=key, data=data
        )
