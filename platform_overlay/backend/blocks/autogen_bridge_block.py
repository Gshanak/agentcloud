"""AutoGen bridge block for the AutoGPT Platform.

Drop-in custom block that runs a Microsoft AutoGen 3-agent team
(``RoundRobinGroupChat``) inside an AutoGPT agent graph.  The team's model
client points at Gemini's OpenAI-compatible endpoint, so the reasoning runs
on Gemini's free tier.

Import compatibility: when running inside the AutoGPT Platform the real
``backend.blocks._base`` classes are used.  Outside the platform (local dev
and unit tests) a minimal standalone shim keeps the same API surface, so
this file works in both places unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import Field

from backend.blocks.autogen_team import (
    DEFAULT_MAX_MESSAGES,
    DEFAULT_MODEL,
    DEFAULT_RETRIES,
    build_gemini_client,
    compose_task,
    run_team_with_retry,
)

try:  # pragma: no cover - exercised only inside the AutoGPT Platform
    from backend.blocks._base import (  # type: ignore[attr-defined]
        Block,
        BlockCategory,
        BlockOutput,
        BlockSchemaInput,
        BlockSchemaOutput,
    )
    from backend.data.model import SchemaField  # type: ignore[attr-defined]

    _IN_PLATFORM = True
except ImportError:  # standalone / local development
    from enum import Enum
    from typing import AsyncIterator

    _IN_PLATFORM = False

    from pydantic import BaseModel

    class BlockCategory(Enum):  # minimal mirror of the platform enum
        AI = "Block that leverages AI to perform a task."

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

logger = logging.getLogger(__name__)


async def _test_execute(input_data: "AutoGenBridgeBlockInput") -> tuple[str, list[dict]]:
    """Deterministic stand-in used by the platform's block self-test."""
    return (
        "1. Example item\n2. Example item 2",
        [
            {"source": "user", "content": "Summarize today's technology news."},
            {"source": "researcher", "content": "facts"},
            {"source": "summarizer", "content": "summaries"},
            {"source": "editor", "content": "1. Example item\n2. Example item 2"},
        ],
    )


class AutoGenBridgeBlockInput(BlockSchemaInput):
    task: str = SchemaField(
        description="What the agent team should do, in plain language.",
    )
    team_profile: Literal["news", "story"] = SchemaField(
        description="Which 3-agent team to run: 'news' (researcher, "
        "summarizer, editor) or 'story' (writer, image prompter, editor).",
        default="news",
    )
    api_key: str = SchemaField(
        description="LLM API key for the Gemini OpenAI-compatible endpoint. "
        "Secret: set it via graph credentials, never inline in a shared graph.",
    )
    model: str = SchemaField(
        description="Model name on the Gemini endpoint.",
        default=DEFAULT_MODEL,
    )
    context: str = SchemaField(
        description="Optional supporting text (article batch, story brief) "
        "appended to the task. Clipped to 50,000 characters.",
        default="",
    )
    max_messages: int = SchemaField(
        description="Termination limit on team messages.",
        default=DEFAULT_MAX_MESSAGES,
        ge=4,
        le=40,
    )
    retries: int = SchemaField(
        description="Retries (with exponential backoff) on rate-limit errors.",
        default=DEFAULT_RETRIES,
        ge=0,
        le=6,
    )


class AutoGenBridgeBlockOutput(BlockSchemaOutput):
    result: str = SchemaField(description="The team's final output text.")
    transcript: list[dict] = SchemaField(
        description="Full team transcript as {source, content} dicts."
    )
    error: str = SchemaField(description="Error message if the run failed.")


class AutoGenBridgeBlock(Block):
    def __init__(self):
        super().__init__(
            id="8f2c1a54-9d7e-4b6a-a3f2-1c5e8b7d9a40",
            input_schema=AutoGenBridgeBlockInput,
            output_schema=AutoGenBridgeBlockOutput,
            description=(
                "Runs a 3-agent AutoGen team (RoundRobinGroupChat) on the "
                "Gemini OpenAI-compatible endpoint and returns the final "
                "output plus the full transcript. Profiles: 'news' and "
                "'story'."
            ),
            categories={BlockCategory.AI},
            test_input={
                "task": "Summarize today's technology news for me.",
                "team_profile": "news",
                "api_key": "test-key",
            },
            test_output=[
                ("result", "1. Example item\n2. Example item 2"),
                (
                    "transcript",
                    [
                        {"source": "user", "content": "Summarize today's technology news."},
                        {"source": "researcher", "content": "facts"},
                        {"source": "summarizer", "content": "summaries"},
                        {"source": "editor", "content": "1. Example item\n2. Example item 2"},
                    ],
                ),
            ],
            test_mock={
                "_execute": _test_execute,
            },
        )

    async def run(self, input_data: AutoGenBridgeBlockInput, **kwargs: Any) -> BlockOutput:
        if not input_data.api_key or not input_data.api_key.strip():
            yield "error", "api_key is required (set it via graph credentials)"
            return

        try:
            result, transcript = await self._execute(input_data)
            yield "result", result
            yield "transcript", transcript
        except Exception as exc:  # noqa: BLE001 - surfaced as block output
            logger.exception("AutoGen bridge run failed")
            yield "error", f"{type(exc).__name__}: {exc}"

    async def _execute(
        self, input_data: AutoGenBridgeBlockInput
    ) -> tuple[str, list[dict]]:
        model_client = build_gemini_client(
            api_key=input_data.api_key,
            model=input_data.model,
        )
        task = compose_task(input_data.task, input_data.context or None)
        return await run_team_with_retry(
            task=task,
            profile_name=input_data.team_profile,
            model_client=model_client,
            max_messages=input_data.max_messages,
            retries=input_data.retries,
        )
