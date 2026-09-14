"""Pure helpers for the News Curator pipeline. No platform imports.

Shared by the dedup/store blocks and the /api/briefings route, so all three
agree on key names, record shapes, and history capping.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

# KV keys mirror the platform's persistence block scope prefix
# (persistence.py: scope "across_agents" -> "global#{key}").
BRIEFINGS_KV_KEY = "global#briefings"
SEEN_HASHES_KV_KEY_PREFIX = "global#news_seen_hashes"

# Cap the dedup set and the briefing history so the KV values stay small.
HISTORY_CAP = 30
MAX_SEEN_HASHES = 5000


def article_hash(title: str, link: str) -> str:
    """Stable content hash for an RSS article (SHA-256 of title + link)."""
    return hashlib.sha256(f"{title}\n{link}".encode("utf-8")).hexdigest()


def make_briefing_record(
    title: str,
    text: str,
    article_count: int | None = None,
) -> dict:
    """Build one briefing record for storage and API responses."""
    return {
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "briefing": text,
        "article_count": article_count,
    }


def add_to_history(
    history: list[dict] | None, record: dict, cap: int = HISTORY_CAP
) -> list[dict]:
    """Prepend a record to the briefing history, capped at ``cap`` entries."""
    updated = list(history or [])
    updated.insert(0, record)
    return updated[:cap]


def merge_seen_hashes(
    seen: dict[str, str] | None, new_hashes: list[str], cap: int = MAX_SEEN_HASHES
) -> dict[str, str]:
    """Merge new article hashes into the seen-set, pruning oldest first.

    ``seen`` maps hash -> ISO timestamp; entries beyond ``cap`` are dropped
    oldest-first so the stored value stays bounded.
    """
    merged = dict(seen or {})
    now = datetime.now(timezone.utc).isoformat()
    for h in new_hashes:
        merged[h] = now
    if len(merged) <= cap:
        return merged
    # Sort by stored timestamp ascending, keep the most recent ``cap``.
    ordered = sorted(merged.items(), key=lambda kv: kv[1], reverse=True)
    return dict(ordered[:cap])


def format_entries_as_context(entries: list[dict]) -> str:
    """Render RSS entries as the text context for the AutoGen team."""
    if not entries:
        return ""
    parts = []
    for entry in entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        author = (entry.get("author") or "").strip()
        description = (entry.get("description") or "").strip()
        pub_date = (entry.get("pub_date") or entry.get("published") or "").strip()
        header = f"## {title}" if title else "## (untitled)"
        byline = " - ".join(part for part in (author, pub_date) if part)
        block_lines = [header]
        if byline:
            block_lines.append(byline)
        if link:
            block_lines.append(link)
        if description:
            block_lines.append("")
            block_lines.append(description)
        parts.append("\n".join(block_lines))
    return "\n\n".join(parts)
