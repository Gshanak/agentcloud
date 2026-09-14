# agentcloud

Two free Android AI apps on one self-hosted cloud backend:

1. **News & Content Curator** - a daily AI-summarized news briefing, pushed to the phone.
2. **Multilingual Storyteller** - illustrated, narrated stories in major Indian languages.

Zero recurring cost: Oracle Cloud Always Free VM + Gemini free tier + Pollinations.ai
images + Android on-device TTS + Firebase Cloud Messaging.

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
Android apps (Kotlin + Compose) -> REST / WebSocket / FCM
```

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
deploy/
  customize.py             # applies the overlay onto a cloned AutoGPT repo
  vm-setup.sh              # one-shot Ubuntu VM bootstrap
  docker-compose.vm.yml    # memory limits sized for the 12 GB free VM
  CLOUDFLARE_TUNNEL.md     # free HTTPS exposure guide
tests/                     # 27 pytest tests, network-free (replay model client)
docs/Android_AI_Projects_Plan.pdf  # full end-to-end project plan
```

## Deploying (Epic 1)

On a fresh Oracle Cloud Always Free ARM VM (Ubuntu):

```bash
git clone https://github.com/Gshanak/agentcloud.git agentcloud
sudo bash agentcloud/deploy/vm-setup.sh
```

The script installs Docker, clones AutoGPT at a pinned commit, copies the
AutoGen bridge block into the platform, adds the autogen dependencies to the
backend build, generates `.env`, and starts the platform with memory limits
sized for the free VM. Then:

1. Open `http://<vm-ip>:3000`, create your admin account, and close
   registration (`AUTH_ALLOW_NEW_ACCOUNTS=false`).
2. Expose HTTPS via Cloudflare Tunnel (`deploy/CLOUDFLARE_TUNNEL.md`).
3. In the Build canvas, the **AutoGen Bridge** block appears alongside the
   built-in blocks.

### Manual steps (what vm-setup.sh does)

```bash
git clone https://github.com/Significant-Gravitas/AutoGPT.git
python3 deploy/customize.py --repo ./AutoGPT     # copy block + deps + .env
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

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q        # 27 tests, no network needed
```

Tests use AutoGen's `ReplayChatCompletionClient` for deterministic,
network-free runs of the full 3-agent pipeline.

### Free-tier design notes

- Dedup before LLM: hash articles in Postgres so quota is never spent twice.
- `is_rate_limit_error` detects 429s; `run_team_with_retry` backs off
  exponentially and rebuilds the team on each attempt.
- Context is clipped to 50k chars to protect the free tier's token limits.
- The Gemini key is a per-run input, not a build-time secret.

## Roadmap

- [x] Epic 1 - Infrastructure: bridge block, tests, deployment kit
- [ ] Epic 2 - News Curator backend (graph, schedule, /api/briefings)
- [ ] Epic 3 - News Curator Android app
- [ ] Epic 4 - Storyteller backend (story graph, Pollinations queue)
- [ ] Epic 5 - Storyteller Android app (on-device TTS)
- [ ] Epic 6 - Docs, delivery, APK releases

See `docs/Android_AI_Projects_Plan.pdf` for the full plan.
