---
title: agentcloud
emoji: 📰
colorFrom: indigo
colorTo: amber
sdk: docker
app_port: 7860
pinned: false
---

# agentcloud — News Curator + Storyteller

A free, self-contained AI backend + two installable phone apps:

- **News Curator** — a daily AI-summarized news briefing, pushed to your phone at 07:00 IST.
- **Storyteller** — illustrated, narrated stories in 12 Indian languages.

Everything runs in this one container: the FastAPI server, the 3-agent
AutoGen teams (news / story) on the Gemini free tier, the daily scheduler,
web push, and the two PWAs served as static files.

## App URLs (after the Space starts)

| App | URL |
|---|---|
| News Curator PWA | `https://<this-space>.hf.space/news/` |
| Storyteller PWA | `https://<this-space>.hf.space/stories/` |
| Health check | `https://<this-space>.hf.space/api/health` |

## Secrets to set (Settings → Variables and secrets)

| Secret | What it is |
|---|---|
| `GEMINI_API_KEY` | Your key from https://aistudio.google.com/apikey (free) |
| `AUTH_TOKEN` | Any long random string you invent — the PWAs' "Access Token" |
| `HF_TOKEN` | A *write* token from https://huggingface.co/settings/tokens |
| `STATE_REPO` | `your-username/agentcloud-state` (a private **dataset** repo that stores your data) |

Data (briefings, stories, push subscriptions) is saved as a JSON snapshot to
the `STATE_REPO` dataset repo, so it survives Space restarts. Without
`HF_TOKEN`/`STATE_REPO` the server still runs, but data resets on restart.

## Keep-awake (recommended)

Free Spaces sleep after ~48h of inactivity. Ping
`https://<this-space>.hf.space/api/health` every 30 minutes with a free
service like https://cron-job.org so the 07:00 IST briefing always runs.

Full setup guide: the `SETUP.md` "Path A — no card needed" section in the
[agentcloud repo](https://github.com/Gshanak/agentcloud).
