# agentcloud

Two free AI apps on one self-hosted cloud backend:

1. **News & Content Curator** - a daily AI-summarized news briefing, pushed to the phone.
2. **Multilingual Storyteller** - illustrated, narrated stories in major Indian languages.

Zero recurring cost: Oracle Cloud Always Free VM + Gemini free tier + Pollinations.ai
images + browser speech synthesis + Web Push notifications.

## Architecture

```
Oracle Cloud VM (Always Free, ARM 2 OCPU / 12 GB)
  └── AutoGPT Platform (Docker Compose, self-hosted)
        ├── REST API + WebSocket + Scheduler + Push notifications
        ├── Custom block: AutoGen bridge  (this repo)
        │     RoundRobinGroupChat of 3 AssistantAgents per pipeline
        │     model client -> Gemini OpenAI-compatible endpoint (free tier)
        └── Built-in blocks: RSS | HTTP | LLM | Postgres persistence
Cloudflare Tunnel -> public HTTPS (free, no domain)
Android PWA (vanilla JS + service worker) -> REST / Web Push
```

The apps are progressive web apps: installable to the home screen,
offline-capable via a service worker, and push-notified via the platform's
VAPID web-push endpoints. No Play Store fee, no native build toolchain.

Three open-source projects are combined:

| Repo | Role |
|---|---|
| significant-gravitas/AutoGPT | Cloud backend: agent graph engine, scheduler, notifications, blocks |
| microsoft/autogen | 3-agent reasoning teams, run inside a custom AutoGPT block |
| affaan-m/ecc | Development methodology: TDD, code review, Kotlin/Python standards |

## Repository layout

```
platform_overlay/backend/blocks/
  autogen_team.py          # AutoGen team factory (news + story profiles, retry)
  autogen_bridge_block.py  # AutoGPT custom block wrapping the team
  _block_shim.py           # standalone compatibility shim for all blocks
  _briefing_store.py       # pure helpers: hashing, records, history, formatting
  news_dedup_block.py      # dedup by content hash BEFORE any LLM call
  briefing_store_block.py  # stores briefings in the platform KV store
  _story_store.py        # pure helpers: story records, Pollinations URLs, image prompt extraction
  story_store_block.py   # stores stories + cover URL in the platform KV store
platform_overlay/backend/api/features/briefings/
  routes.py                # GET /api/briefings (latest) and /history
platform_overlay/backend/api/features/stories/
  routes.py                # POST /api/stories/generate, GET/DELETE /api/stories
graphs/
  news_curator.json        # importable agent graph: RSS -> dedup -> AutoGen -> store
  storyteller.json         # importable agent graph: AgentInput -> AutoGen -> StoryStore
deploy/
  customize.py             # applies the overlay onto a cloned AutoGPT repo
  vm-setup.sh              # one-shot Ubuntu VM bootstrap
  docker-compose.vm.yml    # memory limits sized for the 12 GB free VM
  schedule_news.py         # imports the graph + creates the 7 AM IST cron
  CLOUDFLARE_TUNNEL.md     # free HTTPS exposure guide
tests/                     # 83 pytest tests, network-free (replay model client)
apps/
  news-curator-pwa/       # installable PWA (Epic 3)
  storyteller-pwa/        # installable PWA with read-aloud (Epic 5)
SETUP.md                  # the manual-input checklist (accounts, keys, VM)
docs/Android_AI_Projects_Plan.pdf  # full end-to-end project plan
```

## Deploying (Epics 1-2)

On a fresh Oracle Cloud Always Free ARM VM (Ubuntu):

```bash
git clone https://github.com/Gshanak/agentcloud.git agentcloud
sudo bash agentcloud/deploy/vm-setup.sh
```

The script installs Docker, clones AutoGPT at a pinned commit, copies the
custom blocks and the /api/briefings route into the platform, adds the
autogen dependencies to the backend build, generates `.env`, and starts the
platform with memory limits sized for the free VM. Then:

1. Open `http://<vm-ip>:3000`, create your admin account, and close
   registration (`AUTH_ALLOW_NEW_ACCOUNTS=false`).
2. Expose HTTPS via Cloudflare Tunnel (`deploy/CLOUDFLARE_TUNNEL.md`).
3. Import the News Curator graph and schedule the daily 7:00 AM IST run:

```bash
python3 deploy/schedule_news.py \
  --base https://your-tunnel.trycloudflare.com \
  --token <your-token> \
  --api-key <your-gemini-key>
```

4. Set your Gemini API key on the **AutoGen Bridge** node (or pass
   `--api-key` above), and the first scheduled run stores a briefing.
5. The PWA reads `GET /api/briefings` (latest) and
   `GET /api/briefings/history`.

### Manual steps (what vm-setup.sh does)

```bash
git clone https://github.com/Significant-Gravitas/AutoGPT.git
python3 deploy/customize.py --repo ./AutoGPT     # blocks + route + deps + .env
cd AutoGPT
docker compose \
  -f autogpt_platform/docker-compose.platform.yml \
  -f ../agentcloud/deploy/docker-compose.vm.yml \
  --env-file autogpt_platform/.env \
  up -d --build
```

## Using the AutoGen Bridge block

| Input | Description |
|---|---|
| `task` | What the team should do, in plain language |
| `team_profile` | `news` (researcher -> summarizer -> editor) or `story` (writer -> image prompter -> editor) |
| `api_key` | Gemini API key (secret - set via graph credentials, never inline in shared graphs) |
| `model` | Gemini model (default `gemini-2.5-flash`; free tier is Flash/Flash-Lite only) |
| `context` | Optional supporting text, clipped to 50,000 chars |
| `max_messages` | Team termination limit (default 12) |
| `retries` | Rate-limit retries with exponential backoff (default 3) |

| Output | Description |
|---|---|
| `result` | The team's final output text |
| `transcript` | Full transcript as `{source, content}` dicts |
| `error` | Error message if the run failed |

The block auto-registers: AutoGPT's block loader scans
`backend/backend/blocks/*.py` dynamically.

## The News Curator pipeline (Epic 2)

```
RSS Reader (built-in)                       entries
  -> NewsDedupBlock            new_entries, formatted_context, new_count
     (SHA-256 of title+link vs seen-set in the platform KV store; the
      seen-set is capped at 5,000 hashes, oldest pruned first)
  -> AutoGenBridgeBlock        result        (team_profile: news)
  -> BriefingStoreBlock        stored        (history capped at 30, newest first)
```

Key free-tier decision: dedup runs **before** any LLM call, so Gemini's
~1,500 requests/day quota is never spent on a repeat article.

API (mounted by customize.py into the platform):

| Route | Description |
|---|---|
| `GET /api/briefings` | Latest briefing record (404 until the first run) |
| `GET /api/briefings/history` | Past briefings, newest first (capped at 30) |

## The News Curator PWA (Epic 3)

A progressive web app — installable to the home screen, offline-capable,
and push-notified. No app store, no build toolchain: it is a set of static
files in `apps/news-curator-pwa/`.

```
apps/news-curator-pwa/
  index.html      # app shell: Today / History / Settings tabs
  app.js          # fetches /api/briefings, push subscription, install prompt
  sw.js           # service worker: shell cache + push event -> notification
  style.css       # dark, mobile-first
  manifest.json   # installable (standalone display, maskable icons)
  nginx.conf      # serves from the VM via the news-pwa compose service
  DEPLOYMENT.md   # VM (port 8080) or Cloudflare Pages options
```

Serve it from the same VM (the compose overlay includes a `news-pwa`
nginx service on port 8080) or from Cloudflare Pages (free). Open it in
Chrome on Android, set the server URL in Settings, enable notifications,
and install it to the home screen. See `apps/news-curator-pwa/DEPLOYMENT.md`.

## The Storyteller pipeline (Epic 4)

```
AgentInput (topic, language)                     result
  -> AutoGenBridgeBlock  result, transcript     (team_profile: story:
     story_writer -> image_prompter -> story_editor)
  -> StoryStoreBlock      stored
     (extracts image_prompter's prompt from the transcript,
      builds a free Pollinations.ai cover URL, stores in KV)
```

On-demand generation via REST (the primary path for the PWA):

| Route | Description |
|---|---|
| `POST /api/stories/generate` | Start async story generation; returns `{id, status: "pending"}` (202) |
| `GET /api/stories` | Story history, newest first (capped at 50) |
| `GET /api/stories/{id}` | Single story record (poll until `status=ready`) |
| `DELETE /api/stories/{id}` | Remove a story |

The generate route runs the AutoGen story team as a background `asyncio`
task, so the PWA gets an immediate 202 with a story ID and polls until
`status` flips to `ready` or `failed`. The Gemini key is resolved from the
request body or `GEMINI_API_KEY` in `.env` (set by `customize.py`).

Cover illustrations are free: the image_prompter agent writes one English
prompt, and `pollinations_image_url(prompt)` builds a deterministic URL
that renders the image on demand — no API key, no storage cost. The PWA
just puts the URL in an `<img>` tag; the browser and service worker cache
it like any other static asset.

## The Storyteller PWA (Epic 5)

Same pattern as the News Curator PWA, in `apps/storyteller-pwa/` (port
8081): a Create tab (topic + language picker with 12 Indian languages +
optional style), a Library of past stories with cover thumbnails, and an
immersive Reader with the Pollinations cover, the story text, and **Read
Aloud** — browser `speechSynthesis` narration in the story's language,
with speed control. No cloud TTS, no cost, works offline.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q        # 83 tests, no network needed
```

Tests use AutoGen's `ReplayChatCompletionClient` for deterministic,
network-free runs of the full 3-agent pipeline, and FastAPI TestClient with
injected fakes for the routes.

### Free-tier design notes

- Dedup before LLM: hash articles in the KV store so quota is never spent twice.
- `is_rate_limit_error` detects 429s; `run_team_with_retry` backs off
  exponentially and rebuilds the team on each attempt.
- Context is clipped to 50k chars to protect the free tier's token limits.
- The Gemini key is a per-run input, not a build-time secret.
- Briefing history is capped (30) and the seen-hash set is capped (5,000) so
  KV values stay small.

## Roadmap

- [x] Epic 1 - Infrastructure: bridge block, tests, deployment kit
- [x] Epic 2 - News Curator backend (graph, schedule, /api/briefings)
- [x] Epic 3 - News Curator PWA (installable, offline, push notifications)
- [x] Epic 4 - Storyteller backend (story graph, /api/stories, Pollinations)
- [x] Epic 5 - Storyteller PWA (browser speech synthesis narration)
- [x] Epic 6 - Docs, delivery, final release

See `docs/Android_AI_Projects_Plan.pdf` for the original plan and
**`SETUP.md` for the step-by-step setup checklist** (accounts, keys, VM
creation — everything that needs your input).
