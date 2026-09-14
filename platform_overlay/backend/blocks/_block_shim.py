"""Standalone compatibility shim for agentcloud blocks.

When running inside the AutoGPT Platform, the real ``backend.blocks._base``
classes and ``backend.util.clients`` helpers are used. Outside the platform
(local dev and unit tests) this module provides the same API surface, so
block files import and test cleanly without a platform installation.

Each block module imports the names it needs from here, keeping a single
source of truth for the shim.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

try:  # pragma: no cover - exercised only inside the AutoGPT Platform
    from backend.blocks._base import (  # type: ignore[attr-defined]
        Block,
        BlockCategory,
        BlockOutput,
        BlockSchemaInput,
        BlockSchemaOutput,
    )
    from backend.data.model import SchemaField  # type: ignore[attr-defined]
    from backend.util.clients import (  # type: ignore[attr-defined]
        get_database_manager_async_client,
    )

    IN_PLATFORM = True
except ImportError:  # standalone / local development
    IN_PLATFORM = False

    class BlockCategory(Enum):  # minimal mirror of the platform enum
        AI = "Block that leverages AI to perform a task."
        DATA = "Block that interacts with structured data."
        OUTPUT = "Block that interacts with output of the graph."
        INPUT = "Block that interacts with input of the graph."

    BlockOutput = AsyncIterator[tuple[str, Any]]

    class BlockSchemaInput(BaseModel):
        """Standalone mirror of the platform's block input schema base."""

        model_config = {"extra": "forbid"}

    class BlockSchemaOutput(BaseModel):
        """Standalone mirror of the platform's block output schema base."""

        model_config = {"extra": "forbid"}

    def SchemaField(**kwargs: Any) -> Any:  # noqa: N802 - mirrors platform name
        kwargs.pop("placeholder", None)
        return Field(**kwargs)

    class Block:  # minimal mirror of the platform Block base
        def __init__(
            self,
            id: str,
            input_schema: type,
            output_schema: type,
            description: str,
            categories: set[BlockCategory] | None = None,
            test_input: dict | None = None,
            test_output: list | None = None,
            test_mock: dict | None = None,
            **_kwargs: Any,
        ) -> None:
            self.id = id
            self.input_schema = input_schema
            self.output_schema = output_schema
            self.description = description
            self.categories = categories or set()
            self.test_input = test_input
            self.test_output = test_output
            self.test_mock = test_mock

    # No platform database in standalone mode; tests inject a fake by
    # monkeypatching this name on the block module that uses it.
    def get_database_manager_async_client() -> Any:  # pragma: no cover
        raise RuntimeError(
            "get_database_manager_async_client is only available inside the "
            "AutoGPT Platform; inject a fake in tests"
        )
