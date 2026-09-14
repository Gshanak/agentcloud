"""AutoGen team factory for the AutoGPT bridge block.

Builds the 3-agent teams used by the two apps:

* ``news``  - researcher, summarizer, editor (News & Content Curator)
* ``story`` - story_writer, image_prompter, story_editor (Multilingual Storyteller)

All teams are ``RoundRobinGroupChat`` instances whose model client points at
Gemini's OpenAI-compatible endpoint (free tier).  Every function here is
pure/dependency-light so it can be unit-tested with AutoGen's
``ReplayChatCompletionClient`` and no network access.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

logger = logging.getLogger(__name__)

# Gemini exposes an OpenAI-compatible endpoint; the free tier works with
# Flash / Flash-Lite class models (~1,500 requests/day, 30 requests/min).
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_MAX_MESSAGES = 12  # task message + up to ~3 rounds of 3 agents
DEFAULT_RETRIES = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0

# Cap the free-form context block so a huge article batch cannot blow the
# 1M-token-per-minute free-tier limit in a single call.
MAX_CONTEXT_CHARS = 50_000


@dataclass(frozen=True)
class AgentSpec:
    """Immutable description of one AssistantAgent in a team."""

    name: str
    system_message: str


NEWS_PROFILE: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="researcher",
        system_message=(
            "You are a news researcher. Given a task and a batch of raw "
            "article text, extract the key facts for each article: title, "
            "source, and the 3-5 most important facts. Be factual and terse. "
            "Never invent facts that are not in the provided text."
        ),
    ),
    AgentSpec(
        name="summarizer",
        system_message=(
            "You are a news summarizer. Given the researcher's extracted "
            "facts, write a clear 2-paragraph summary per article in the "
            "user's requested language. Keep each summary under 120 words."
        ),
    ),
    AgentSpec(
        name="editor",
        system_message=(
            "You are a news editor. Review the summaries, rank them by "
            "relevance to the user's stated interests, and produce the final "
            "briefing: a ranked list of the day's articles with their "
            "summaries. Output plain text only."
        ),
    ),
)

STORY_PROFILE: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="story_writer",
        system_message=(
            "You are a storyteller. Given a topic and a language, write a "
            "complete short story (300-500 words) entirely in that language. "
            "Give it a title on the first line. Make it warm and engaging."
        ),
    ),
    AgentSpec(
        name="image_prompter",
        system_message=(
            "You are an image prompt engineer. Given the story, write ONE "
            "concise English image-generation prompt (under 40 words) that "
            "captures the story's mood as a storybook cover illustration. "
            "Output only the prompt text."
        ),
    ),
    AgentSpec(
        name="story_editor",
        system_message=(
            "You are a story editor. Polish the story for grammar and flow "
            "without changing its language or length, and output the final "
            "story with its title on the first line. Output the story only."
        ),
    ),
)

TEAM_PROFILES: dict[str, tuple[AgentSpec, ...]] = {
    "news": NEWS_PROFILE,
    "story": STORY_PROFILE,
}


def build_gemini_client(
    api_key: str,
    model: str = DEFAULT_MODEL,
    timeout: float = 120.0,
) -> OpenAIChatCompletionClient:
    """Model client pointed at Gemini's OpenAI-compatible endpoint.

    Gemini is not a known OpenAI model, so we supply ``model_info`` explicitly
    (required by the AutoGen OpenAI client for any non-OpenAI model name).
    """
    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=GEMINI_OPENAI_BASE_URL,
        timeout=timeout,
        model_info={
            "vision": True,
            "function_calling": True,
            "json_output": True,
            "family": "unknown",
        },
    )


def build_team(
    profile_name: str,
    model_client: Any,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> RoundRobinGroupChat:
    """Assemble the 3-agent round-robin team for a named profile."""
    try:
        specs = TEAM_PROFILES[profile_name]
    except KeyError:
        valid = ", ".join(sorted(TEAM_PROFILES))
        raise ValueError(
            f"Unknown team profile {profile_name!r}; valid profiles: {valid}"
        ) from None

    agents = [
        AssistantAgent(
            name=spec.name,
            system_message=spec.system_message,
            model_client=model_client,
        )
        for spec in specs
    ]
    return RoundRobinGroupChat(
        participants=agents,
        termination_condition=MaxMessageTermination(max_messages=max_messages),
    )


def compose_task(task: str, context: str | None = None) -> str:
    """Combine the task text with an optional context block, size-capped."""
    if not context:
        return task
    clipped = context[:MAX_CONTEXT_CHARS]
    if len(context) > MAX_CONTEXT_CHARS:
        logger.warning(
            "Context clipped from %d to %d chars", len(context), MAX_CONTEXT_CHARS
        )
    return f"{task}\n\nContext:\n{clipped}"


def _content_to_text(content: Any) -> str:
    """Normalize a chat message body (str or structured list) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)


async def run_team(team: RoundRobinGroupChat, task: str) -> tuple[str, list[dict]]:
    """Run a team to completion; return (final_text, transcript)."""
    result = await team.run(task=task)
    transcript = [
        {"source": msg.source, "content": _content_to_text(msg.content)}
        for msg in result.messages
    ]
    final = transcript[-1]["content"] if transcript else ""
    return final, transcript


def is_rate_limit_error(exc: BaseException) -> bool:
    """Detect a 429 / rate-limit style error across SDK versions."""
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    name = type(exc).__name__.lower()
    return "ratelimit" in name


async def run_team_with_retry(
    task: str,
    profile_name: str,
    model_client: Any,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    retries: int = DEFAULT_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    team_runner: Callable[[RoundRobinGroupChat, str], Awaitable[tuple[str, list[dict]]]] = run_team,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[str, list[dict]]:
    """Run a team, retrying with exponential backoff on rate-limit errors.

    The team is rebuilt on every attempt so a partially-consumed conversation
    never leaks into the next try.  ``team_runner`` and ``sleep`` are
    injectable for deterministic tests.
    """
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        team = build_team(profile_name, model_client, max_messages=max_messages)
        try:
            return await team_runner(team, task)
        except Exception as exc:  # noqa: BLE001 - inspect, then re-raise
            if not (attempt < retries and is_rate_limit_error(exc)):
                raise
            last_exc = exc
            delay = base_delay * (2**attempt)
            logger.warning(
                "Rate limit on attempt %d/%d; backing off %.1fs",
                attempt + 1, retries + 1, delay,
            )
            await sleep(delay)
    # Unreachable when retries >= 0, but keeps the type checker happy.
    raise RuntimeError(f"Retry loop exhausted: {last_exc}")  # pragma: no cover
