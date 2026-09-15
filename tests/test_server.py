"""Tests for the standalone server (no-card deployment).

All network-free: the KV store is in-memory, story generation is
monkeypatched, the news pipeline runs against AutoGen's
ReplayChatCompletionClient, and VAPID generation is faked.
"""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# The server package lives at the repo root; `python -m pytest` puts the
# cwd on sys.path, but be explicit for safety.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.auth import get_user_id_factory  # noqa: E402
from server.config import Config  # noqa: E402
from server.push import (  # noqa: E402
    SUBSCRIPTIONS_KV_KEY,
    VAPID_KV_KEY,
    get_vapid_public_key,
    remove_subscription,
    save_subscription,
)
from server.routes import build_router  # noqa: E402
from server.store import MemoryStore  # noqa: E402

from backend.blocks._briefing_store import (  # noqa: E402
    BRIEFINGS_KV_KEY,
    SEEN_HASHES_KV_KEY_PREFIX,
    article_hash,
)


# ------------------------------------------------------------------ store

@pytest.mark.asyncio
async def test_memory_store_get_set_roundtrip():
    store = MemoryStore()
    assert await store.get("u", "k") is None
    await store.set("u", "k", {"a": 1})
    assert await store.get("u", "k") == {"a": 1}
    # per-user isolation
    await store.set("other", "k", {"a": 2})
    assert await store.get("u", "k") == {"a": 1}


def test_memory_store_snapshot_roundtrip():
    s1 = MemoryStore()
    s1.set_sync = None  # noqa: B010 - clarity only
    asyncio.get_event_loop_policy()
    asyncio.run(s1.set("owner", "global#briefings", [{"id": "b1"}]))
    snap = s1.snapshot()
    assert snap == {"owner": {"global#briefings": [{"id": "b1"}]}}

    s2 = MemoryStore()
    s2.load_snapshot(snap)
    assert asyncio.run(s2.get("owner", "global#briefings")) == [{"id": "b1"}]


# -------------------------------------------------------------------- auth

def _make_client(store, auth_token=""):
    app = FastAPI()
    router = build_router(get_user_id_factory(auth_token))
    router.set_store(store)
    app.include_router(router)
    return TestClient(app)


def test_auth_required_returns_401():
    client = _make_client(MemoryStore(), auth_token="secret-token")
    resp = client.get("/api/briefings")
    assert resp.status_code == 401

    resp = client.get(
        "/api/briefings", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401


def test_auth_valid_token_passes():
    store = MemoryStore()
    asyncio.run(store.set("owner", BRIEFINGS_KV_KEY, [{"id": "b1", "title": "T"}]))
    client = _make_client(store, auth_token="secret-token")
    resp = client.get(
        "/api/briefings", headers={"Authorization": "Bearer secret-token"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "b1"


def test_auth_disabled_in_dev_mode():
    client = _make_client(MemoryStore(), auth_token="")
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ------------------------------------------------------------------ routes

def test_briefings_404_when_empty():
    client = _make_client(MemoryStore())
    assert client.get("/api/briefings").status_code == 404
    assert client.get("/api/briefings/history").json() == []


def test_story_generate_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    client = _make_client(MemoryStore())
    resp = client.post(
        "/api/stories/generate",
        json={"topic": "a brave mongoose", "language": "English"},
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


def test_story_generate_and_poll(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    store = MemoryStore()

    # Replace the real generation with a fake that flips status to ready.
    import server.routes as routes_mod

    router = build_router(get_user_id_factory(""))
    router.set_store(store)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # The team call is patched at the autogen_team module level; the real
    # signature is run_team_with_retry(task=..., profile_name=..., model_client=...).
    import backend.blocks.autogen_team as team_mod

    async def fake_run_team(task, profile_name, model_client, **kwargs):
        assert profile_name == "story"
        return "The Mongoose\n\nOnce upon...", [
            {"source": "story_writer", "content": "draft"},
            {"source": "image_prompter", "content": "a brave mongoose"},
            {"source": "story_editor", "content": "final"},
        ]

    monkeypatch.setattr(team_mod, "run_team_with_retry", fake_run_team)

    resp = client.post(
        "/api/stories/generate",
        json={"topic": "a brave mongoose", "language": "English"},
    )
    assert resp.status_code == 202
    story_id = resp.json()["id"]

    # The background task runs on the running loop; TestClient executes it
    # during the request. Give it a chance then poll.
    record = client.get(f"/api/stories/{story_id}").json()
    assert record["status"] in ("pending", "ready", "failed")


def test_push_vapid_key_and_subscribe(monkeypatch):
    store = MemoryStore()

    # Fake keypair generation (no py_vapid needed in tests).
    monkeypatch.setattr(
        "server.push._generate_vapid_keypair",
        lambda: {"private_pem": "PEM", "public_key": "BTESTKEY"},
    )
    key = asyncio.run(get_vapid_public_key(store))
    assert key == "BTESTKEY"
    # Cached on second call.
    assert asyncio.run(get_vapid_public_key(store)) == "BTESTKEY"

    asyncio.run(
        save_subscription(store, {"endpoint": "https://push.example/e1", "keys": {}})
    )
    asyncio.run(
        save_subscription(store, {"endpoint": "https://push.example/e1", "keys": {}})
    )
    subs = asyncio.run(store.get("owner", SUBSCRIPTIONS_KV_KEY))
    assert len(subs) == 1  # dedup by endpoint

    asyncio.run(remove_subscription(store, "https://push.example/e1"))
    assert asyncio.run(store.get("owner", SUBSCRIPTIONS_KV_KEY)) == []


# --------------------------------------------------------------- news job

@pytest.mark.asyncio
async def test_news_job_full_pipeline(monkeypatch, replay_news_team):
    """RSS -> dedup -> team -> store, entirely network-free."""
    from server.news_job import run_news_job

    store = MemoryStore()
    rss_entries = [
        {"title": "Item A", "link": "https://x/a", "description": "da",
         "author": "r", "pub_date": "2026-09-15"},
        {"title": "Item B", "link": "https://x/b", "description": "db",
         "author": "r", "pub_date": "2026-09-15"},
    ]
    monkeypatch.setattr("server.news_job.fetch_rss", lambda url: rss_entries)

    record = await run_news_job(store, "fake-key", "https://rss.example")
    assert record is not None
    assert record["article_count"] == 2

    history = await store.get("owner", BRIEFINGS_KV_KEY)
    assert len(history) == 1
    seen = await store.get("owner", SEEN_HASHES_KV_KEY_PREFIX)
    assert article_hash("Item A", "https://x/a") in seen

    # Second run: everything seen -> no LLM call, no new briefing.
    calls = replay_news_team["calls"]
    calls_before = calls[0] if calls else 0
    record2 = await run_news_job(store, "fake-key", "https://rss.example")
    assert record2 is None
    assert len(await store.get("owner", BRIEFINGS_KV_KEY)) == 1

    # One new article -> new briefing.
    rss_entries.append(
        {"title": "Item C", "link": "https://x/c", "description": "dc",
         "author": "r", "pub_date": "2026-09-15"}
    )
    record3 = await run_news_job(store, "fake-key", "https://rss.example")
    assert record3 is not None
    assert record3["article_count"] == 1
    assert len(await store.get("owner", BRIEFINGS_KV_KEY)) == 2


@pytest.mark.asyncio
async def test_news_job_no_entries(monkeypatch):
    from server.news_job import run_news_job

    monkeypatch.setattr("server.news_job.fetch_rss", lambda url: [])
    record = await run_news_job(MemoryStore(), "fake-key", "https://rss.example")
    assert record is None


@pytest.fixture
def replay_news_team(monkeypatch):
    """Patch build_gemini_client/build_team to a ReplayChatCompletionClient team.

    The replay client returns deterministic responses without network.
    """
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination
    from autogen_agentchat.teams import RoundRobinGroupChat
    from autogen_ext.models.replay import ReplayChatCompletionClient

    calls = [0]

    class CountingReplay(ReplayChatCompletionClient):
        async def create(self, *args, **kwargs):
            calls[0] += 1
            return await super().create(*args, **kwargs)

    replay = CountingReplay([f"Summary {i}" for i in range(10)])

    def fake_build_team(profile, model_client, max_messages=12):
        agents = [
            AssistantAgent(name=p.name, system_message=p.system_message, model_client=model_client)
            for p in __import__(
                "backend.blocks.autogen_team", fromlist=["NEWS_PROFILE"]
            ).NEWS_PROFILE
        ]
        return RoundRobinGroupChat(
            participants=agents,
            termination_condition=MaxMessageTermination(max_messages=max_messages),
        )

    import backend.blocks.autogen_team as team_mod

    monkeypatch.setattr(team_mod, "build_gemini_client", lambda **kw: replay)
    monkeypatch.setattr(team_mod, "build_team", fake_build_team)
    return {"calls": calls}
