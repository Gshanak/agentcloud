"""Tests for the News Curator PWA configuration files.

Validates that the PWA assets are structurally correct: the manifest is valid
JSON with the required PWA fields, the service worker caches the expected
shell assets, and the index.html references all the expected resources.
"""

import json
from pathlib import Path

PWA_DIR = Path(__file__).resolve().parent.parent / "apps" / "news-curator-pwa"


def load_pwa_file(name):
    return (PWA_DIR / name).read_text(encoding="utf-8")


def test_manifest_is_valid_json():
    data = json.loads(load_pwa_file("manifest.json"))
    assert data["name"] == "News Curator"
    assert data["short_name"] == "News"
    assert data["display"] == "standalone"
    assert data["start_url"] == "./index.html"
    assert data["background_color"] == "#0f1117"
    assert data["theme_color"] == "#0f1117"


def test_manifest_has_icons():
    data = json.loads(load_pwa_file("manifest.json"))
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert "192x192" in sizes
    assert "512x512" in sizes


def test_index_html_references_all_assets():
    html = load_pwa_file("index.html")
    assert "manifest.json" in html
    assert "style.css" in html
    assert "app.js" in html
    assert "sw.js" not in html or "serviceWorker" in html  # SW registered in app.js


def test_service_worker_caches_shell():
    sw = load_pwa_file("sw.js")
    assert "CACHE_VERSION" in sw
    assert "index.html" in sw
    assert "style.css" in sw
    assert "app.js" in sw
    assert "manifest.json" in sw
    # Push event handler
    assert "addEventListener(\"push\"" in sw
    assert "showNotification" in sw


def test_app_js_has_api_and_push_logic():
    js = load_pwa_file("app.js")
    assert "/api/briefings" in js
    assert "/api/push/vapid-key" in js
    assert "/api/push/subscribe" in js
    assert "pushManager.subscribe" in js
    assert "beforeinstallprompt" in js


def test_nginx_conf_exists_and_serves_html():
    conf = load_pwa_file("nginx.conf")
    assert "listen 80" in conf
    assert "try_files" in conf
    assert "no-cache" in conf  # index.html and sw.js must not be cached


def test_icons_exist():
    assert (PWA_DIR / "icons" / "icon-192.png").is_file()
    assert (PWA_DIR / "icons" / "icon-512.png").is_file()
    assert (PWA_DIR / "icons" / "icon.svg").is_file()
