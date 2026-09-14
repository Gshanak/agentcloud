"""Unit tests for the AutoGen bridge block (standalone shim mode).

These tests exercise the block's contract: schema, output names, validation
of the api key, error surfacing, and a full end-to-end run against a
replay model client (no network).
"""

from typing import Any

import pytest
from autogen_ext.models.replay import ReplayChatCompletionClient

import backend.blocks.autogen_bridge_block as bridge_module
from backend.blocks.autogen_bridge_block import (
    AutoGenBridgeBlock,
    AutoGenBridgeBlockInput,
)


def make_input(**overrides: Any) -> AutoGenBridgeBlockInput:
    values = {
        "task": "Summarize today's technology news.",
        "team_profile": "news",
        "api_key": "test-key",
        "model": "gemini-2.5-flash",
        "context": "",
        "max_messages": 12,
        "retries": 3,
    }
    values.update(overrides)
    return AutoGenBridgeBlockInput(**values)


async def collect_outputs(block: AutoGenBridgeBlock, input_data) -> list[tuple[str, Any]]:
    return [item async for item in block.run(input_data)]


# ----------------------------------------------------------------- schema

def test_block_metadata():
    block = AutoGenBridgeBlock()
    assert block.id == "8f2c1a54-9d7e-4b6a-a3f2-1c5e8b7d9a40"
    assert "AutoGen" in block.description
    assert block.test_input is not None
    assert block.test_output is not None
    assert "_execute" in (block.test_mock or {})


def test_input_schema_has_expected_fields():
    fields = set(AutoGenBridgeBlockInput.model_fields)
    assert {
        "task",
        "team_profile",
        "api_key",
        "model",
        "context",
        "max_messages",
        "retries",
    } <= fields


def test_defaults_applied():
    data = make_input()
    assert data.model == "gemini-2.5-flash"
    assert data.max_messages == 12
    assert data.retries == 3
    assert data.context == ""


def test_invalid_profile_rejected():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AutoGenBridgeBlockInput(
            task="t", team_profile="finance", api_key="k"
        )


# ------------------------------------------------------------------- run

@pytest.mark.asyncio
async def test_run_requires_api_key():
    block = AutoGenBridgeBlock()
    outputs = await collect_outputs(block, make_input(api_key="  "))
    assert [name for name, _ in outputs] == ["error"]
    assert "api_key" in outputs[0][1]


@pytest.mark.asyncio
async def test_run_uses_mocked_execute():
    block = AutoGenBridgeBlock()

    async def fake_execute(input_data):
        return "final text", [{"source": "editor", "content": "final text"}]

    block._execute = fake_execute  # platform-style test_mock injection
    outputs = await collect_outputs(block, make_input())

    assert outputs[0] == ("result", "final text")
    assert outputs[1] == (
        "transcript",
        [{"source": "editor", "content": "final text"}],
    )


@pytest.mark.asyncio
async def test_run_surfaces_error_output_on_failure():
    block = AutoGenBridgeBlock()

    async def exploding_execute(input_data):
        raise RuntimeError("model endpoint unreachable")

    block._execute = exploding_execute
    outputs = await collect_outputs(block, make_input())

    assert [name for name, _ in outputs] == ["error"]
    assert "RuntimeError" in outputs[0][1]
    assert "model endpoint unreachable" in outputs[0][1]


@pytest.mark.asyncio
async def test_run_end_to_end_with_replay_client(monkeypatch):
    monkeypatch.setattr(
        bridge_module,
        "build_gemini_client",
        lambda api_key, model, timeout=120.0: ReplayChatCompletionClient(
            ["facts", "summaries", "1. Final briefing"]
        ),
    )
    block = AutoGenBridgeBlock()
    outputs = await collect_outputs(block, make_input(max_messages=4))

    names = [name for name, _ in outputs]
    assert names == ["result", "transcript"]
    result = dict(outputs)["result"]
    transcript = dict(outputs)["transcript"]
    assert result == "1. Final briefing"
    sources = {entry["source"] for entry in transcript}
    assert {"researcher", "summarizer", "editor"} <= sources


@pytest.mark.asyncio
async def test_context_is_passed_into_task(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_run_team_with_retry(task, **kwargs):
        captured["task"] = task
        return "ok", []

    monkeypatch.setattr(
        bridge_module, "run_team_with_retry", fake_run_team_with_retry
    )

    block = AutoGenBridgeBlock()
    outputs = await collect_outputs(
        block, make_input(context="Article one: something happened.")
    )

    assert dict(outputs)["result"] == "ok"
    assert "Article one: something happened." in captured["task"]
    assert "Context:" in captured["task"]
