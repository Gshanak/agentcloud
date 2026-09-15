"""KV storage for the standalone server.

Three interchangeable backends behind one tiny interface
(``await store.get(user_id, key)`` / ``await store.set(user_id, key, value)``)
— mirroring the AutoGPT platform's execution KV store the same keys work:

* ``MemoryStore``    — plain dict; local dev and tests.
* ``HubStateStore``  — memory plus a JSON snapshot synced to a private
                       Hugging Face dataset repo (default in production;
                       no extra account beyond the HF one the Space needs).
* ``PostgresStore``  — any hosted Postgres (Neon/Supabase/...) via asyncpg;
                       used when DATABASE_URL is set.

The data is tiny (< 5 MB for personal use), so a full-state JSON snapshot
is perfectly adequate for the Hub backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

STATE_FILENAME = "agentcloud-state.json"


class KVStore(Protocol):
    async def get(self, user_id: str, key: str) -> Any | None: ...

    async def set(self, user_id: str, key: str, value: Any) -> None: ...


class MemoryStore:
    """In-memory store; data lost on restart. Base for the Hub store."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Any] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: str, key: str) -> Any | None:
        return self._data.get((user_id, key))

    async def set(self, user_id: str, key: str, value: Any) -> None:
        async with self._lock:
            self._data[(user_id, key)] = value

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Serialize to {user_id: {key: value}} for JSON persistence."""
        out: dict[str, dict[str, Any]] = {}
        for (user_id, key), value in self._data.items():
            out.setdefault(user_id, {})[key] = value
        return out

    def load_snapshot(self, snap: dict[str, dict[str, Any]]) -> None:
        for user_id, keys in (snap or {}).items():
            for key, value in keys.items():
                self._data[(user_id, key)] = value


class HubStateStore(MemoryStore):
    """Memory + JSON snapshot synced to a private HF dataset repo.

    The snapshot is uploaded after every write (our write rate is a few
    per day, well within Hub limits) and downloaded once on connect.
    Failures to sync are logged and never break a request — the in-memory
    copy is always authoritative for the running process.
    """

    def __init__(self, token: str, repo_id: str) -> None:
        super().__init__()
        self._token = token
        self._repo_id = repo_id

    async def connect(self) -> None:
        """Download the latest state snapshot (best-effort)."""
        try:
            state = await asyncio.to_thread(self._download)
            self.load_snapshot(state)
            logger.info("Loaded state from %s (%d keys)", self._repo_id, len(self._data))
        except Exception as e:  # noqa: BLE001 - startup must not crash
            logger.warning("Could not load state from the Hub (%s); starting empty", e)

    def _download(self) -> dict:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(
            repo_id=self._repo_id,
            filename=STATE_FILENAME,
            repo_type="dataset",
            token=self._token,
        )
        return json.loads(Path(path).read_text(encoding="utf-8"))

    async def set(self, user_id: str, key: str, value: Any) -> None:
        await super().set(user_id, key, value)
        try:
            await asyncio.to_thread(self._upload)
        except Exception as e:  # noqa: BLE001 - sync failure is non-fatal
            logger.warning("State sync to the Hub failed (will retry on next write): %s", e)

    def _upload(self) -> None:
        from huggingface_hub import HfApi

        api = HfApi(token=self._token)
        api.upload_file(
            path_or_fileobj=json.dumps(self.snapshot()).encode("utf-8"),
            path_in_repo=STATE_FILENAME,
            repo_id=self._repo_id,
            repo_type="dataset",
        )


class PostgresStore:
    """Single-table KV over any hosted Postgres (asyncpg)."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._pool = None

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(self._url, min_size=1, max_size=4)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (user_id, key)
                )
                """
            )
        logger.info("Connected to Postgres store")

    async def get(self, user_id: str, key: str) -> Any | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT value FROM kv WHERE user_id = $1 AND key = $2", user_id, key
            )
        return json.loads(row["value"]) if row else None

    async def set(self, user_id: str, key: str, value: Any) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO kv (user_id, key, value)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (user_id, key)
                DO UPDATE SET value = $3::jsonb, updated_at = now()
                """,
                user_id,
                key,
                json.dumps(value),
            )


async def create_store(config) -> KVStore:
    """Pick the store from config; returns a connected store."""
    if config.DATABASE_URL:
        store = PostgresStore(config.DATABASE_URL)
        await store.connect()
        return store
    if config.HF_TOKEN and config.STATE_REPO:
        store = HubStateStore(config.HF_TOKEN, config.STATE_REPO)
        await store.connect()
        return store
    if config.HF_TOKEN or config.STATE_REPO:
        logger.warning("HF_TOKEN or STATE_REPO missing; using in-memory store")
    else:
        logger.warning("No persistence configured; using in-memory store")
    return MemoryStore()
