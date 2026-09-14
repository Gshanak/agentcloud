"""Unit tests for the AutoGen team factory. Network-free: uses
AutoGen's ReplayChatCompletionClient and injected fakes."""

import pytest
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.models.replay import ReplayChatCompletionClient

from backend.blocks.autogen_team import (
    MAX_CONTEXT_CHARS,
    NEWS_PROFILE,
    STORY_PROFILE,
    build_gemini_client,
    build_team,
    compose_task,
    is_rate_limit_error,
    run_team,
    run_team_with_retry,
)


class RateLimitedError(Exception):
    """Stands in for an OpenAI SDK 429 error."""

    status_code = 429


# ---------------------------------------------------------------- profiles

def test_news_profile_has_three_roles():
    names = [spec.name for spec in NEWS_PROFILE]
    assert names == ["researcher", "summarizer", "editor"]


def test_story_profile_has_three_roles():
    names = [spec.name for spec in STORY_PROFILE]
    assert names == ["story_writer", "image_prompter", "story_editor"]


def test_build_team_rejects_unknown_profile():
    with pytest.raises(ValueError, match="Unknown team profile"):
        build_team("does-not-exist", model_client=None)


def test_build_team_returns_round_robin_team():
    client = ReplayChatCompletionClient(["unused"])
    team = build_team("news", client)
    assert isinstance(team, RoundRobinGroupChat)


# ------------------------------------------------------------- run a team

@pytest.mark.asyncio
async def test_run_team_produces_final_text_and_transcript():
    client = ReplayChatCompletionClient(
        ["facts about articles", "two summaries", "1. Final briefing"]
    )
    team = build_team("news", client, max_messages=4)
    result, transcript = await run_team(team, "Summarize today's news")

    assert result == "1. Final briefing"
    sources = {entry["source"] for entry in transcript}
    assert {"researcher", "summarizer", "editor"} <= sources
    assert all(isinstance(entry["content"], str) for entry in transcript)


# --------------------------------------------------------- retry behaviour

def test_is_rate_limit_error_detects_429():
    assert is_rate_limit_error(RateLimitedError("Too many requests")) is True


def test_is_rate_limit_error_detects_named_error():
    class RateLimitError(Exception):
        pass

    assert is_rate_limit_error(RateLimitError("quota")) is True


def test_is_rate_limit_error_ignores_other_errors():
    assert is_rate_limit_error(ValueError("bad input")) is False
    assert is_rate_limit_error(ConnectionError("reset")) is False


@pytest.mark.asyncio
async def test_retry_backs_off_on_rate_limit_then_succeeds():
    delays: list[float] = []
    calls: list[str] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    async def flaky_runner(team, task):
        calls.append(task)
        if len(calls) < 3:
            raise RateLimitedError("429")
        return ("ok", [{"source": "editor", "content": "ok"}])

    result, transcript = await run_team_with_retry(
        task="do the thing",
        profile_name="news",
        model_client=None,
        retries=2,
        base_delay=1.0,
        team_runner=flaky_runner,
        sleep=fake_sleep,
    )

    assert result == "ok"
    # attempts 1 and 2 failed -> backoffs 1.0 and 2.0
    assert delays == [1.0, 2.0]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_retry_raises_when_quota_never_recovers():
    async def fake_sleep(delay: float) -> None:
        pass

    async def always_limited(team, task):
        raise RateLimitedError("429")

    with pytest.raises(RateLimitedError):
        await run_team_with_retry(
            task="do the thing",
            profile_name="news",
            model_client=None,
            retries=2,
            base_delay=1.0,
            team_runner=always_limited,
            sleep=fake_sleep,
        )


@pytest.mark.asyncio
async def test_non_rate_limit_errors_propagate_immediately():
    attempts: list[int] = []

    async def failing(team, task):
        attempts.append(1)
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await run_team_with_retry(
            task="x",
            profile_name="news",
            model_client=None,
            retries=3,
            team_runner=failing,
        )
    assert len(attempts) == 1  # no retry on non-429 errors


# --------------------------------------------------------- task composition

def test_compose_task_without_context_is_task_alone():
    assert compose_task("summarize", None) == "summarize"
    assert compose_task("summarize", "") == "summarize"


def test_compose_task_appends_context():
    composed = compose_task("summarize", "article one")
    assert composed.startswith("summarize")
    assert "Context:" in composed
    assert "article one" in composed


def test_compose_task_clips_oversized_context():
    huge = "x" * (MAX_CONTEXT_CHARS + 5_000)
    composed = compose_task("task", huge)
    assert len(composed) <= len("task") + len("\n\nContext:\n") + MAX_CONTEXT_CHARS


# ---------------------------------------------------------- model client

def test_build_gemini_client_is_configured_for_gemini_endpoint():
    client = build_gemini_client(api_key="test-key", model="gemini-2.5-flash")
    assert isinstance(client, OpenAIChatCompletionClient)
    # The client resolves model_info on construction; family is "unknown" for
    # any non-OpenAI model name (Gemini), confirming our explicit model_info.
    assert client.model_info["family"] == "unknown"
