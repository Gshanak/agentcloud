"""Tests for the News Curator pure helpers."""

from backend.blocks._briefing_store import (
    BRIEFINGS_KV_KEY,
    HISTORY_CAP,
    MAX_SEEN_HASHES,
    add_to_history,
    article_hash,
    format_entries_as_context,
    make_briefing_record,
    merge_seen_hashes,
)


def test_article_hash_is_stable_and_distinct():
    h1 = article_hash("A", "https://x")
    h2 = article_hash("A", "https://x")
    h3 = article_hash("A", "https://y")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # sha256 hex


def test_make_briefing_record_has_required_fields():
    rec = make_briefing_record("Daily", "text...", article_count=3)
    assert set(rec) == {"id", "created_at", "title", "briefing", "article_count"}
    assert rec["title"] == "Daily"
    assert rec["briefing"] == "text..."
    assert rec["article_count"] == 3
    assert rec["id"]


def test_add_to_history_prepends_and_caps():
    r1 = make_briefing_record("a", "1")
    r2 = make_briefing_record("b", "2")
    h = add_to_history([], r1)
    assert h == [r1]
    h = add_to_history(h, r2)
    assert h[0] is r2  # newest first
    assert len(h) == 2

    big = [make_briefing_record(str(i), str(i)) for i in range(HISTORY_CAP)]
    capped = add_to_history(big, r1, cap=HISTORY_CAP)
    assert len(capped) == HISTORY_CAP
    assert capped[0] is r1


def test_merge_seen_hashes_dedups_and_caps():
    h1 = article_hash("a", "1")
    h2 = article_hash("b", "2")
    seen = {h1: "2026-01-01T00:00:00+00:00"}
    merged = merge_seen_hashes(seen, [h2], cap=10)
    assert set(merged) == {h1, h2}

    # re-adding h1 updates its timestamp, not a new entry
    again = merge_seen_hashes(merged, [h1], cap=10)
    assert len(again) == 2

    # cap prunes oldest
    many = [article_hash(f"t{i}", str(i)) for i in range(MAX_SEEN_HASHES + 50)]
    merged = merge_seen_hashes({}, many, cap=MAX_SEEN_HASHES)
    assert len(merged) == MAX_SEEN_HASHES


def test_format_entries_as_context():
    out = format_entries_as_context([
        {"title": "Hello", "link": "https://x", "author": "A", "description": "D", "pub_date": "2026-09-14"},
    ])
    assert "## Hello" in out
    assert "https://x" in out
    assert "A" in out
    assert "D" in out

    assert format_entries_as_context([]) == ""


def test_keys_are_global_prefixed():
    assert BRIEFINGS_KV_KEY == "global#briefings"
