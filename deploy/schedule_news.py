#!/usr/bin/env python3
"""Import the News Curator graph and schedule it for 7:00 AM IST daily.

Run this once after the platform is up and you have an admin account:

    python3 deploy/schedule_news.py --base https://your-tunnel.trycloudflare.com \
        --token <ADMIN_JWT_OR_API_TOKEN> --api-key <GEMINI_API_KEY>

It:
  1. POSTs graphs/news_curator.json to /api/graphs (import), printing the
     new graph id.
  2. (Optional) patches the AutoGen Bridge node's api_key input with the
     provided --api-key, if the platform supports node input updates.
  3. Creates a daily cron schedule at 01:30 UTC (07:00 IST) for that graph.

If your platform uses a different auth flow (cookie vs bearer), pass --token
as the raw bearer value; the script sends `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

CRON_UTC_0130 = "30 1 * * *"  # 01:30 UTC = 07:00 IST (IST = UTC+5:30)
IST_TIMEZONE = "Asia/Kolkata"

GRAPHS_DIR = Path(__file__).resolve().parent.parent / "graphs"


def api(base: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read().decode()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        print(f"HTTP {e.code} on {method} {path}: {detail}", file=sys.stderr)
        raise SystemExit(1) from e


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", required=True, help="Platform base URL (with https)")
    p.add_argument("--token", required=True, help="Bearer auth token (JWT or API key)")
    p.add_argument("--api-key", default="", help="Gemini API key to set on the bridge node")
    p.add_argument("--graph-file", default=str(GRAPHS_DIR / "news_curator.json"))
    args = p.parse_args(argv)

    graph = json.loads(Path(args.graph_file).read_text(encoding="utf-8"))
    if args.api_key:
        for node in graph.get("nodes", []):
            if node.get("block_id") == "8f2c1a54-9d7e-4b6a-a3f2-1c5e8b7d9a40":
                node.setdefault("input_default", {})["api_key"] = args.api_key

    created = api(args.base, args.token, "POST", "/api/graphs", graph)
    graph_id = created.get("id") or graph.get("id")
    version = created.get("version", 1)
    print(f"Imported graph {graph_id} v{version}")

    schedule = api(
        args.base,
        args.token,
        "POST",
        f"/api/graphs/{graph_id}/schedules",
        {
            "cron": CRON_UTC_0130,
            "graph_version": version,
            "input_data": {},
            "timezone": IST_TIMEZONE,
        },
    )
    print(f"Scheduled daily run at {CRON_UTC_0130} UTC ({IST_TIMEZONE}): {schedule}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
