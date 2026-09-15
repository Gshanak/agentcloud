# News Curator PWA — Deployment

The PWA is a set of static files — no build step. Two ways to serve it:

## Option A: Same VM as the backend (via Docker Compose)

The `deploy/docker-compose.vm.yml` overlay already includes a `news-pwa`
service (nginx:alpine, 64 MB) that serves the PWA on **port 8080**:

```bash
docker compose \
  -f autogpt_platform/docker-compose.platform.yml \
  -f /path/to/agentcloud/deploy/docker-compose.vm.yml \
  --env-file autogpt_platform/.env \
  up -d news-pwa
```

The PWA is then at `http://<vm-ip>:8080`. If you have a Cloudflare Tunnel
set up, add a route for port 8080 to expose it over HTTPS.

## Option B: Cloudflare Pages (free, no VM resource)

1. Push the `apps/news-curator-pwa/` directory to a GitHub repo (or use the
   same `agentcloud` repo with the build output directory set to
   `apps/news-curator-pwa`).
2. In the Cloudflare dashboard → Pages → Create a project → Connect the
   GitHub repo.
3. Build command: (none — it's static).
4. Build output directory: `apps/news-curator-pwa`.
5. Deploy. The PWA is live at `<project>.pages.dev` (HTTPS, CDN-backed).

## After deployment

1. Open the PWA URL on your phone.
2. Go to ⚙ Settings, enter your backend server URL (e.g.
   `https://your-tunnel.trycloudflare.com`), and tap Save.
3. Tap **Enable Notifications** to subscribe to push notifications (the
   platform will notify you when a new briefing is ready).
4. On Chrome (Android): tap the menu → **Install app** to add the PWA to
   your home screen.

## How push notifications work

The PWA subscribes via the Web Push API using the platform's VAPID key:
1. `GET /api/push/vapid-key` — fetches the public VAPID key.
2. `pushManager.subscribe({ applicationServerKey })` — creates a push
   subscription in the browser.
3. `POST /api/push/subscribe` — sends the subscription endpoint and keys to
   the platform.

When the News Curator graph completes a scheduled run, the platform sends a
push notification to all subscribed users. The service worker
(`sw.js`) handles the `push` event and displays a notification.
