"""Configuration for the agentcloud standalone server (no-card deployment).

All settings come from environment variables — HF Space "Secrets". The
server reuses the pure helpers and the AutoGen team factory from
platform_overlay via PYTHONPATH, so it runs the same pipelines as the
AutoGPT-platform deployment without the platform.
"""

from __future__ import annotations

import os


class Config:
    """Environment-driven settings; safe defaults for local development."""

    # --- Persistence -----------------------------------------------------
    # Option A (default, zero extra accounts): sync state as a JSON file to
    # a private Hugging Face dataset repo. Needs HF_TOKEN (a HF write token)
    # and STATE_REPO ("username/agentcloud-state").
    HF_TOKEN: str = os.environ.get("HF_TOKEN", "")
    STATE_REPO: str = os.environ.get("STATE_REPO", "")

    # Option B: any hosted Postgres (Neon / Supabase / etc.) via asyncpg.
    # Takes precedence over the Hub file store when set.
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

    # --- AI ---------------------------------------------------------------
    # Gemini API key (required for story generation + the daily news run).
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

    # --- Auth ---------------------------------------------------------------
    # Shared access token: the PWAs send it as "Authorization: Bearer <token>".
    # If unset, auth is disabled (local development only).
    AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "")

    # --- News ---------------------------------------------------------------
    NEWS_RSS_URL: str = os.environ.get(
        "NEWS_RSS_URL", "https://feeds.arstechnica.com/arstechnica/index"
    )
    # Daily briefing time: 01:30 UTC = 07:00 IST.
    NEWS_CRON_UTC: str = os.environ.get("NEWS_CRON_UTC", "30 1 * * *")
    NEWS_TIMEZONE: str = os.environ.get("NEWS_TIMEZONE", "Asia/Kolkata")
    RUN_NEWS_ON_STARTUP: bool = (
        os.environ.get("RUN_NEWS_ON_STARTUP", "true").lower() == "true"
    )

    # --- Serving ---------------------------------------------------------------
    # HF Spaces requires listening on port 7860.
    PORT: int = int(os.environ.get("PORT", "7860"))

    # Where the PWA static files live (the Dockerfile fills this from apps/).
    STATIC_DIR: str = os.environ.get("STATIC_DIR", "static")
