# Storyteller PWA — Deployment

Same two options as the News Curator PWA (it is also just static files):

## Option A: Same VM as the backend

The `deploy/docker-compose.vm.yml` overlay includes a `story-pwa` service
(nginx:alpine, 64 MB) serving the PWA on **port 8081**:

```bash
docker compose \
  -f autogpt_platform/docker-compose.platform.yml \
  -f /path/to/agentcloud/deploy/docker-compose.vm.yml \
  --env-file autogpt_platform/.env \
  up -d story-pwa
```

## Option B: Cloudflare Pages (free)

1. Cloudflare dashboard → Pages → Create a project → connect the `agentcloud` repo.
2. Build output directory: `apps/storyteller-pwa`. No build command.

## After deployment

1. Open the PWA on your phone, go to ⚙ Settings, enter the backend server
   URL, tap Save (the key is shared with the News Curator PWA, so setting
   it once configures both).
2. On Chrome (Android): menu → **Install app**.
3. The server needs `GEMINI_API_KEY` set (in `autogpt_platform/.env`) for
   on-demand story generation, or pass `api_key` per request.

## Narration (text-to-speech)

Read Aloud uses the browser's built-in `speechSynthesis` — no cloud TTS, no
cost, works offline once the page is loaded. On Android, Google TTS ships
voices for all major Indian languages. If a language's voice is missing,
install it: Settings → Accessibility → Text-to-speech output → Google TTS →
Install voice data.
