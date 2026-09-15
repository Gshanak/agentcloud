"""The daily news pipeline for the standalone server.

Reuses the exact same logic as the AutoGPT-platform graph — the pure
helpers from ``backend.blocks._briefing_store`` (dedup by content hash,
formatting, capped history) and the 3-agent AutoGen news team from
``backend.blocks.autogen_team`` — just orchestrated directly instead of
through a graph.

Order matters for the free tier: dedup happens BEFORE the LLM call.
"""

from __future__ import annotations

import asyncio
import logging

from backend.blocks._briefing_store import (
    BRIEFINGS_KV_KEY,
    SEEN_HASHES_KV_KEY_PREFIX,
    add_to_history,
    article_hash,
    format_entries_as_context,
    make_briefing_record,
    merge_seen_hashes,
)
from backend.blocks.autogen_team import (
    build_gemini_client,
    run_team_with_retry,
)

logger = logging.getLogger(__name__)

NEWS_TASK = (
    "Summarize today's news for me. Rank the articles by relevance and "
    "write a clear 2-paragraph summary for each. Keep each summary under "
    "120 words."
)


def fetch_rss(url: str) -> list[dict]:
    """Fetch and normalize RSS entries (title/link/description/...)."""
    import feedparser

    parsed = feedparser.parse(url)
    entries = []
    for e in parsed.entries:
        entries.append(
            {
                "title": getattr(e, "title", "") or "",
                "link": getattr(e, "link", "") or "",
                "description": getattr(e, "description", "") or getattr(e, "summary", "") or "",
                "author": getattr(e, "author", "") or "",
                "pub_date": getattr(e, "published", "") or "",
            }
        )
    return entries


async def run_news_job(store, api_key: str, rss_url: str) -> dict | None:
    """Run one news cycle: RSS -> dedup -> team -> store -> push.

    Returns the stored briefing record, or None when there was nothing new
    or the run failed (failures are logged, never raised — the scheduler
    must survive them).
    """
    user_id = "owner"
    try:
        entries = await asyncio.to_thread(fetch_rss, rss_url)
        if not entries:
            logger.warning("RSS feed returned no entries: %s", rss_url)
            return None

        seen = await store.get(user_id, SEEN_HASHES_KV_KEY_PREFIX) or {}
        new_entries, new_hashes = [], []
        for entry in entries:
            digest = article_hash(entry.get("title", ""), entry.get("link", ""))
            if digest in seen:
                continue
            new_entries.append(entry)
            new_hashes.append(digest)

        if not new_entries:
            logger.info("No new articles; skipping LLM call (quota protected)")
            return None

        # Dedup BEFORE the LLM call: quota is never spent on a repeat.
        await store.set(
            user_id, SEEN_HASHES_KV_KEY_PREFIX, merge_seen_hashes(seen, new_hashes)
        )

        context = format_entries_as_context(new_entries)
        client = build_gemini_client(api_key=api_key)
        task = f"{NEWS_TASK}\n\nContext:\n{context}"
        briefing_text, _transcript = await run_team_with_retry(
            task=task, profile_name="news", model_client=client
        )

        record = make_briefing_record(
            title="Daily News Briefing",
            text=briefing_text,
            article_count=len(new_entries),
        )
        history = await store.get(user_id, BRIEFINGS_KV_KEY) or []
        await store.set(user_id, BRIEFINGS_KV_KEY, add_to_history(history, record))

        # Best-effort push notification.
        from server.push import send_push

        try:
            await send_push(store, "News Curator", "Your daily briefing is ready")
        except Exception as e:  # noqa: BLE001
            logger.warning("Push after briefing failed: %s", e)

        logger.info("Briefing stored (%d new articles)", len(new_entries))
        return record
    except Exception:  # noqa: BLE001 - scheduled job must never crash the app
        logger.exception("News job failed")
        return None
