"""Briefing store block for the AutoGPT Platform (News Curator pipeline).

Stores a finished briefing (the AutoGen team's final text) in the platform KV
store as a capped history list, so the /api/briefings route can serve both the
latest briefing and past ones. Mirrors the persistence block's KV access but
keeps a history list under one key.
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
    BRIEFINGS_KV_KEY,
    HISTORY_CAP,
    add_to_history,
    make_briefing_record,
)

logger = logging.getLogger(__name__)


class BriefingStoreBlockInput(BlockSchemaInput):
    briefing: str = SchemaField(
        description="Final briefing text from the AutoGen news team."
    )
    title: str = SchemaField(
        description="Briefing title.", default="Daily News Briefing"
    )
    article_count: int = SchemaField(
        description="Number of articles summarized (for the record).",
        default=0,
        ge=0,
    )
    history_cap: int = SchemaField(
        description="Max number of past briefings to retain.",
        default=HISTORY_CAP,
        ge=1,
        le=365,
    )


class BriefingStoreBlockOutput(BlockSchemaOutput):
    stored: dict = SchemaField(description="The briefing record that was stored.")
    status: str = SchemaField(description="'stored' on success.")


class BriefingStoreBlock(Block):
    def __init__(self):
        super().__init__(
            id="c3a1f2b3-1111-4e2a-9c1d-000000000002",
            input_schema=BriefingStoreBlockInput,
            output_schema=BriefingStoreBlockOutput,
            description=(
                "Stores a finished briefing as the latest entry in a capped "
                "history list in the platform KV store, so /api/briefings can "
                "serve the latest and past briefings."
            ),
            categories={BlockCategory.OUTPUT},
            test_input={
                "briefing": "1. Example item\n2. Example item 2",
                "title": "Daily News Briefing",
                "article_count": 2,
            },
            test_output=[
                (
                    "status",
                    "stored",
                ),
            ],
            test_mock={
                "_retrieve_history": lambda *a, **k: [],
                "_store_history": lambda *a, **k: None,
            },
        )

    async def run(
        self,
        input_data: BriefingStoreBlockInput,
        *,
        user_id: str,
        node_exec_id: str,
        **kwargs: Any,
    ) -> BlockOutput:
        if not input_data.briefing.strip():
            yield "status", "empty"
            return

        history = await self._retrieve_history(user_id=user_id) or []
        record = make_briefing_record(
            title=input_data.title,
            text=input_data.briefing,
            article_count=input_data.article_count,
        )
        updated = add_to_history(history, record, cap=input_data.history_cap)
        await self._store_history(
            user_id=user_id,
            node_exec_id=node_exec_id,
            data=updated,
        )
        yield "stored", record
        yield "status", "stored"

    async def _retrieve_history(self, user_id: str) -> list[dict] | None:
        return await get_database_manager_async_client().get_execution_kv_data(
            user_id=user_id, key=BRIEFINGS_KV_KEY
        )

    async def _store_history(
        self, user_id: str, node_exec_id: str, data: list[dict]
    ) -> Any:
        return await get_database_manager_async_client().set_execution_kv_data(
            user_id=user_id, node_exec_id=node_exec_id, key=BRIEFINGS_KV_KEY, data=data
        )
