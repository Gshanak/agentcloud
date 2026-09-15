"""FastAPI app assembly for the agentcloud standalone server.

Wires together: the KV store, bearer auth, the API router, the daily
scheduler (07:00 IST), an optional first-run news job, and the two PWAs
served as static files — one container, zero recurring cost.

Run (HF Spaces Dockerfile does this):
    uvicorn server.app:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import fastapi
from fastapi.staticfiles import StaticFiles

from server import push as push_mod
from server.auth import get_user_id_factory
from server.config import Config
from server.news_job import run_news_job
from server.routes import build_router
from server.store import create_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = Config()
router = build_router(get_user_id_factory(config.AUTH_TOKEN))


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    # 1. Storage (HF Hub state file / Postgres / memory).
    store = await create_store(config)
    router.set_store(store)
    app.state.store = store

    # 2. VAPID keys (auto-generated once, stored in the KV store).
    await push_mod.get_vapid_public_key(store)

    # 3. Scheduler: the daily 7:00 AM IST news run.
    scheduler = None
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        hour, minute = config.NEWS_CRON_UTC.split()[1], config.NEWS_CRON_UTC.split()[0]

        async def news_job() -> None:
            if not config.GEMINI_API_KEY:
                logger.warning("GEMINI_API_KEY not set; skipping scheduled news run")
                return
            await run_news_job(store, config.GEMINI_API_KEY, config.NEWS_RSS_URL)

        scheduler = AsyncIOScheduler(timezone=config.NEWS_TIMEZONE)
        scheduler.add_job(
            news_job,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=config.NEWS_TIMEZONE),
            id="daily_news",
        )
        scheduler.start()
        logger.info("Scheduler started: news run at %s %s (%s)", hour, minute, config.NEWS_TIMEZONE)
    except Exception as e:  # noqa: BLE001 - scheduler failure must not kill the app
        logger.warning("Scheduler unavailable (%s); daily news run disabled", e)

    # 4. First-run convenience: generate a briefing immediately if none yet.
    if config.RUN_NEWS_ON_STARTUP and config.GEMINI_API_KEY:
        from backend.blocks._briefing_store import BRIEFINGS_KV_KEY

        if not await store.get("owner", BRIEFINGS_KV_KEY):
            logger.info("No briefing yet; running the news job once on startup")
            await run_news_job(store, config.GEMINI_API_KEY, config.NEWS_RSS_URL)

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


app = fastapi.FastAPI(
    title="agentcloud",
    description="News Curator + Storyteller backend (standalone, no-card deployment)",
    lifespan=lifespan,
)
app.include_router(router)

# Serve the PWAs as static apps (filled by the Dockerfile from apps/).
_static = Path(config.STATIC_DIR)
if (_static / "news").is_dir():
    app.mount("/news", StaticFiles(directory=_static / "news", html=True), name="news")
if (_static / "stories").is_dir():
    app.mount("/stories", StaticFiles(directory=_static / "stories", html=True), name="stories")


@app.get("/", summary="Index")
async def index() -> dict[str, str]:
    return {
        "app": "agentcloud",
        "news_pwa": "/news/",
        "stories_pwa": "/stories/",
        "health": "/api/health",
    }
