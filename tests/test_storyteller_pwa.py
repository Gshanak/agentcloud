"""Tests for the Storyteller PWA configuration files."""

import json
from pathlib import Path

PWA_DIR = Path(__file__).resolve().parent.parent / "apps" / "storyteller-pwa"


def load_pwa_file(name):
    return (PWA_DIR / name).read_text(encoding="utf-8")


def test_manifest_is_valid_json():
    data = json.loads(load_pwa_file("manifest.json"))
    assert data["name"] == "Storyteller"
    assert data["short_name"] == "Stories"
    assert data["display"] == "standalone"
    assert data["theme_color"] == "#120f17"


def test_manifest_has_icons():
    data = json.loads(load_pwa_file("manifest.json"))
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_index_html_has_language_options():
    html = load_pwa_file("index.html")
    for lang_code in ("hi-IN", "te-IN", "ta-IN", "bn-IN", "mr-IN", "gu-IN",
                      "kn-IN", "ml-IN", "pa-IN", "or-IN", "as-IN", "ur-IN"):
        assert lang_code in html, f"missing language option {lang_code}"


def test_app_js_has_generate_poll_and_tts():
    js = load_pwa_file("app.js")
    assert "/api/stories/generate" in js
    assert "/api/stories/" in js
    assert "speechSynthesis" in js
    assert "SpeechSynthesisUtterance" in js
    assert "speak(" in js
    assert "beforeinstallprompt" in js
    # polling loop
    assert "setInterval" in js


def test_sw_caches_shell_and_pollinations():
    sw = load_pwa_file("sw.js")
    assert "index.html" in sw
    assert "app.js" in sw
    assert "image.pollinations.ai" in sw  # cache-first for images


def test_nginx_conf_exists():
    conf = load_pwa_file("nginx.conf")
    assert "listen 80" in conf
    assert "no-cache" in conf


def test_icons_exist():
    assert (PWA_DIR / "icons" / "icon-192.png").is_file()
    assert (PWA_DIR / "icons" / "icon-512.png").is_file()
    assert (PWA_DIR / "icons" / "icon.svg").is_file()


def test_compose_has_story_pwa_service():
    compose = (
        Path(__file__).resolve().parent.parent / "deploy" / "docker-compose.vm.yml"
    ).read_text()
    assert "story-pwa:" in compose
    assert '"8081:80"' in compose
    assert "storyteller-pwa" in compose
