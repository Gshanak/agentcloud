# agentcloud — Your Setup Checklist

Everything here is something **only you can do** — accounts to create, keys
to obtain, and one-time decisions. Everything else is already in this repo
(`deploy/vm-setup.sh` and `deploy/customize.py` automate the rest).

---

## 1. Accounts to create (one-time)

| Account | URL | Cost | Needed for |
|---|---|---|---|
| Oracle Cloud | https://www.oracle.com/cloud/free/ | Free (credit card required for verification, not charged) | The VM that runs everything |
| Google AI Studio | https://aistudio.google.com/ | Free | Gemini API key (the AI brain) |
| Cloudflare | https://dash.cloudflare.com/sign-up | Free | HTTPS tunnel (no domain needed) |

## 2. Get your Gemini API key

1. Go to https://aistudio.google.com/apikey
2. Click **Create API key** → pick the default project
3. Copy the key (starts with `AIza...`)
4. Free tier: ~1,500 requests/day with Gemini Flash models — more than
   enough for daily briefings + a few stories per day.

## 3. Create the Oracle VM

In the Oracle Cloud console: **Compute → Create Instance**. Use these
exact settings:

| Setting | Value |
|---|---|
| Name | `agentcloud` |
| Image | Canonical **Ubuntu 22.04** (click "Edit" next to Image and switch from Oracle Linux) |
| Shape | **VM.Standard.A1.Flex** (Ampere ARM) — 2 OCPUs, **12 GB** memory |
| Networking | New VCN + public subnet; **make sure "Assign a public IPv4 address" is checked** |
| SSH keys | Generate a key pair in the browser and **download both files** (you need them to log in) |

After clicking Create: if you see **"Out of host capacity"**, retry — free
ARM capacity in some regions (especially India) frees up periodically.
Retrying at off-peak hours usually succeeds within a few attempts.

When the VM is running, note its **public IP**.

## 4. Open these ports in the security list

In the console: your instance → subnet → **Security Lists** → Add Ingress
Rules for (Source `0.0.0.0/0`):

- TCP **3000** (AutoGPT web UI — close this after Cloudflare Tunnel works)
- TCP **8080** (News Curator PWA)
- TCP **8081** (Storyteller PWA)

## 5. Run the setup script on the VM

From your own computer:

```bash
ssh -i <your-key-file> ubuntu@<VM_PUBLIC_IP>
```

Then on the VM (copy-paste):

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/Gshanak/agentcloud.git
sudo bash agentcloud/deploy/vm-setup.sh
```

Wait 15-30 minutes (Docker image builds). This does everything: installs
Docker, clones AutoGPT, applies the overlay, sizes memory limits, starts
all services.

## 6. First-run platform setup (browser)

1. Open `http://<VM_PUBLIC_IP>:3000`
2. **Create your admin account** (email + password of your choice)
3. Close registration so nobody else can sign up: edit
   `AutoGPT/autogpt_platform/.env`, set `AUTH_ALLOW_NEW_ACCOUNTS=false`,
   then `docker compose -f autogpt_platform/docker-compose.platform.yml -f
   ~/agentcloud/deploy/docker-compose.vm.yml --env-file
   autogpt_platform/.env up -d rest_server` to apply.

## 7. Fill in your Gemini key on the VM

```bash
nano ~/AutoGPT/autogpt_platform/.env
# Find GEMINI_API_KEY= and paste your key after the =
# Save with Ctrl+O, Enter, Ctrl+X
docker compose -f autogpt_platform/docker-compose.platform.yml \
  -f ~/agentcloud/deploy/docker-compose.vm.yml \
  --env-file autogpt_platform/.env up -d rest_server executor
```

## 8. Set up Cloudflare Tunnel (free HTTPS)

The PWAs need HTTPS for install + push. On the VM:

```bash
# Install cloudflared (already done by vm-setup.sh if you used it) then:
cloudflared tunnel --url http://localhost:3000
```

Copy the printed `https://xxx.trycloudflare.com` URL — that is your
platform's public HTTPS address. Add routes for the PWAs too (ports 8080
and 8081), or host the PWAs on Cloudflare Pages instead (see
`apps/news-curator-pwa/DEPLOYMENT.md`).

Notes:
- The free quick tunnel URL changes each time `cloudflared` restarts. For a
  permanent URL, create a free named tunnel in the Cloudflare dashboard and
  point it at `localhost:3000`.
- Always access the platform over the HTTPS URL from your phone.

## 9. (Optional) Push notifications for the News Curator

Web push needs a VAPID key pair on the server:

```bash
# On the VM (or any machine with node installed):
npx web-push generate-vapid-keys
```

Put the printed public/private keys into
`AutoGPT/autogpt_platform/.env` as `VAPID_PUBLIC_KEY=...` and
`VAPID_PRIVATE_KEY=...` (check the exact variable names the platform
expects in its .env.default), then restart `rest_server` and
`notification_server`. In the News Curator PWA: Settings → Enable
Notifications.

## 10. Import the graphs and schedule the news run

In the AutoGPT web UI (Build → import, or run `deploy/schedule_news.py`):

```bash
cd ~/agentcloud
python3 deploy/schedule_news.py \
  --base https://your-tunnel.trycloudflare.com \
  --token <your-auth-token> \
  --api-key <GEMINI_API_KEY>
```

Or in the UI: Build → ⋯ → Import → pick `graphs/news_curator.json` (or
`graphs/storyteller.json`), then on the **AutoGen Bridge** node paste your
Gemini key into the `api_key` input, and create a schedule (01:30 UTC =
07:00 IST) on the news graph.

## 11. Install the PWAs on your phone

1. Open `https://<your-pwa-url>` in Chrome on Android
2. Settings → paste the platform URL → Save
3. Chrome menu → **Install app** (or **Add to Home screen**)
4. For Storyteller narration: if a language's voice is missing on your
   phone, install it under Settings → Accessibility → Text-to-speech
   output → Google TTS → Install voice data.

---

## Daily usage

Nothing. The news graph runs at 07:00 IST by itself; stories are generated
on demand from the Storyteller PWA. Total recurring cost: ₹0.

## If something breaks

- `docker compose ps` — see which service is down
- `docker compose logs rest_server --tail 50` — API errors
- `docker compose logs executor --tail 50` — block/agent execution errors
- Gemini 429 errors are normal on the free tier; the pipeline retries with
  backoff automatically.
