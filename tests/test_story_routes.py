"""Tests for the /api/stories routes (standalone shim mode).

Uses FastAPI TestClient with the get_user_id dependency overridden, the KV
client monkeypatched, and the generation coroutine replaced with a fake so
no network or AutoGen import is needed.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.features.stories.routes as routes_mod
from backend.api.features.stories.routes import get_user_id, router


class FakeKV:
    """In-memory KV store keyed by (user_id, key)."""

    def __init__(self):
        self.data = {}

    async def get_execution_kv_data(self, user_id, key):
        return self.data.get((user_id, key))

    async def set_execution_kv_data(self, user_id, node_exec_id, key, data):
        self.data[(user_id, key)] = data


def make_app(kv):
    """Build an app with a fake KV and a faked generation coroutine."""
    app = FastAPI()
    app.include_router(router, prefix="/api/stories")

    fake_kv = FakeKV()
    fake_kv.data = kv
    routes_mod.get_database_manager_async_client = lambda: fake_kv
    app.dependency_overrides[get_user_id] = lambda: "user-1"
    return app, fake_kv


@pytest.fixture
def setup():
    kv = {}
    app, fake_kv = make_app(kv)
    client = TestClient(app)
    return client, fake_kv, kv


def test_generate_requires_api_key():
    app, _ = make_app({})
    resp = TestClient(app).post(
        "/api/stories/generate",
        json={"topic": "a brave mongoose", "language": "English"},
    )
    assert resp.status_code == 400
    assert "API key" in resp.json()["detail"]


def test_generate_with_env_key(setup, monkeypatch):
    client, fake_kv, _ = setup
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    # Replace the generation coroutine with a fake that writes a story.
    async def fake_generate(story_id, user_id, req, api_key):
        history = fake_kv.data.get((user_id, "global#stories"), [])
        for r in history:
            if r["id"] == story_id:
                r["story"] = "The Mongoose\n\nOnce upon a time..."
                r["title"] = "The Mongoose"
                r["image_prompt"] = "a brave mongoose"
                r["image_url"] = "https://image.pollinations.ai/prompt/x"
                r["status"] = "ready"
        fake_kv.data[(user_id, "global#stories")] = history

    monkeypatch.setattr(routes_mod, "_generate_and_store", fake_generate)

    resp = client.post(
        "/api/stories/generate",
        json={"topic": "a brave mongoose", "language": "English"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    story_id = body["id"]

    # The background task ran synchronously in the fake; verify the record.
    resp = client.get(f"/api/stories/{story_id}")
    assert resp.status_code == 200
    record = resp.json()
    assert record["status"] == "ready"
    assert record["title"] == "The Mongoose"
    assert record["image_url"].startswith("https://image.pollinations.ai/prompt/")


def test_list_stories(setup, monkeypatch):
    client, fake_kv, _ = setup
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        routes_mod,
        "_generate_and_store",
        lambda *a, **k: asyncio.sleep(0),  # no-op coroutine
    )

    client.post("/api/stories/generate", json={"topic": "topic one", "language": "English"})
    client.post("/api/stories/generate", json={"topic": "topic two", "language": "Hindi"})

    resp = client.get("/api/stories")
    assert resp.status_code == 200
    stories = resp.json()
    assert len(stories) == 2
    assert stories[0]["topic"] == "topic two"
    assert stories[1]["topic"] == "topic one"


def test_get_story_not_found(setup):
    client, _, _ = setup
    resp = client.get("/api/stories/nonexistent-id")
    assert resp.status_code == 404


def test_delete_story(setup, monkeypatch):
    client, fake_kv, _ = setup
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        routes_mod,
        "_generate_and_store",
        lambda *a, **k: asyncio.sleep(0),
    )

    resp = client.post(
        "/api/stories/generate",
        json={"topic": "to be deleted", "language": "English"},
    )
    story_id = resp.json()["id"]

    # Verify it exists.
    assert client.get(f"/api/stories/{story_id}").status_code == 200

    # Delete it.
    resp = client.delete(f"/api/stories/{story_id}")
    assert resp.status_code == 204

    # Now 404.
    assert client.get(f"/api/stories/{story_id}").status_code == 404

    # Delete again -> 404.
    assert client.delete(f"/api/stories/{story_id}").status_code == 404


def test_list_stories_empty():
    app, _ = make_app({})
    resp = TestClient(app).get("/api/stories")
    assert resp.status_code == 200
    assert resp.json() == []
