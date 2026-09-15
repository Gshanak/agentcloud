"""Tests for the Storyteller pure helpers."""

from backend.blocks._story_store import (
    STORY_HISTORY_CAP,
    STORIES_KV_KEY,
    add_to_story_history,
    extract_image_prompt,
    find_in_history,
    make_story_record,
    parse_title,
    pollinations_image_url,
    remove_from_history,
)


def test_pollinations_url_is_deterministic_and_stable():
    url1 = pollinations_image_url("a brave mongoose")
    url2 = pollinations_image_url("a brave mongoose")
    assert url1 == url2
    assert url1.startswith("https://image.pollinations.ai/prompt/")
    assert "width=768" in url1
    assert "height=768" in url1
    assert "nologo=true" in url1
    assert "seed=" in url1


def test_pollinations_url_different_prompts_different_urls():
    url1 = pollinations_image_url("a cat")
    url2 = pollinations_image_url("a dog")
    assert url1 != url2


def test_pollinations_url_empty_prompt_fallback():
    url = pollinations_image_url("")
    assert "storybook%20illustration" in url


def test_pollinations_url_custom_dimensions_and_seed():
    url = pollinations_image_url("sunset", width=512, height=512, seed=42)
    assert "width=512" in url
    assert "height=512" in url
    assert "seed=42" in url


def test_parse_title_from_first_line():
    assert parse_title("The Brave Mongoose\n\nOnce upon a time...") == "The Brave Mongoose"
    assert parse_title("# My Title\nbody") == "My Title"
    assert parse_title("## Title\nbody") == "Title"
    assert parse_title("\n\n  Spaced Title  \nbody") == "Spaced Title"
    assert parse_title("") == "Untitled Story"


def test_extract_image_prompt_from_transcript():
    transcript = [
        {"source": "story_writer", "content": "draft"},
        {"source": "image_prompter", "content": "storybook illustration of a mongoose"},
        {"source": "story_editor", "content": "final"},
    ]
    assert extract_image_prompt(transcript) == "storybook illustration of a mongoose"


def test_extract_image_prompt_takes_last():
    transcript = [
        {"source": "image_prompter", "content": "first attempt"},
        {"source": "story_editor", "content": "..."},
        {"source": "image_prompter", "content": "refined prompt"},
    ]
    assert extract_image_prompt(transcript) == "refined prompt"


def test_extract_image_prompt_empty_or_missing():
    assert extract_image_prompt([]) == ""
    assert extract_image_prompt([{"source": "story_writer", "content": "x"}]) == ""
    assert extract_image_prompt(None) == ""


def test_make_story_record():
    rec = make_story_record(
        topic="a mongoose",
        language="Telugu",
        story_text="The Mongoose\n\nOnce upon...",
        image_prompt="a brave mongoose illustration",
        image_url="https://image.pollinations.ai/prompt/x",
        style="fable",
    )
    assert rec["title"] == "The Mongoose"
    assert rec["topic"] == "a mongoose"
    assert rec["language"] == "Telugu"
    assert rec["story"] == "The Mongoose\n\nOnce upon..."
    assert rec["status"] == "ready"
    assert rec["id"]
    assert rec["created_at"]
    assert rec["image_prompt"] == "a brave mongoose illustration"


def test_add_to_story_history_prepends_and_caps():
    r1 = make_story_record("a", "en", "Story A")
    r2 = make_story_record("b", "en", "Story B")
    h = add_to_story_history([], r1)
    assert h == [r1]
    h = add_to_story_history(h, r2)
    assert h[0]["title"] == "Story B"
    assert len(h) == 2

    big = [make_story_record(str(i), "en", f"S{i}") for i in range(STORY_HISTORY_CAP)]
    capped = add_to_story_history(big, r1, cap=STORY_HISTORY_CAP)
    assert len(capped) == STORY_HISTORY_CAP
    assert capped[0] is r1


def test_find_and_remove_in_history():
    r1 = make_story_record("a", "en", "A")
    r2 = make_story_record("b", "en", "B")
    history = [r1, r2]
    assert find_in_history(history, r1["id"]) is r1
    assert find_in_history(history, "nonexistent") is None
    assert find_in_history(None, "x") is None

    remaining = remove_from_history(history, r1["id"])
    assert len(remaining) == 1
    assert remaining[0]["id"] == r2["id"]
    # remove nonexistent is a no-op
    assert len(remove_from_history(remaining, "ghost")) == 1


def test_stories_kv_key():
    assert STORIES_KV_KEY == "global#stories"
