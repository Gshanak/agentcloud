"""Tests for the /api/briefings routes (standalone shim mode).

Uses FastAPI TestClient with the get_user_id dependency overridden and the
KV client monkeypatched on the routes module.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.features.briefings.routes as routes_mod
from backend.api.features.briefings.routes import get_user_id, router


def make_app(kv_data):
    """Build an app mounting the briefings router with a fake KV client."""
    app = FastAPI()
    app.include_router(router, prefix="/api/briefings")

    class FakeKV:
        async def get_execution_kv_data(self, user_id, key):
            return kv_data.get(key)

    routes_mod.get_database_manager_async_client = lambda: FakeKV()
    app.dependency_overrides[get_user_id] = lambda: "user-123"
    return app


def client_for(kv_data):
    return TestClient(make_app(kv_data))


def test_latest_returns_404_when_nothing_stored():
    resp = client_for({"global#briefings": None}).get("/api/briefings")
    assert resp.status_code == 404
    assert "No briefing" in resp.json()["detail"]


def test_latest_returns_newest_briefing():
    records = [
        {"id": "r2", "title": "second", "briefing": "B", "article_count": 2},
        {"id": "r1", "title": "first", "briefing": "A", "article_count": 3},
    ]
    resp = client_for({"global#briefings": records}).get("/api/briefings")
    assert resp.status_code == 200
    assert resp.json()["id"] == "r2"
    assert resp.json()["title"] == "second"


def test_history_returns_full_list():
    records = [
        {"id": "r2", "title": "second", "briefing": "B"},
        {"id": "r1", "title": "first", "briefing": "A"},
    ]
    resp = client_for({"global#briefings": records}).get("/api/briefings/history")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["id"] for r in body] == ["r2", "r1"]


def test_history_returns_empty_list_when_none():
    resp = client_for({"global#briefings": None}).get("/api/briefings/history")
    assert resp.status_code == 200
    assert resp.json() == []
