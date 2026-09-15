# agentcloud — Your Setup Checklist

Two ways to run it. **If you don't have a credit card, use Path A** — it
needs nothing but free accounts (Hugging Face, Google). Path B (Oracle VM)
runs the full AutoGPT platform but requires a card for verification.

Everything else is already in this repo.

---

# Path A — No card needed (Hugging Face Spaces)

**Total new accounts: 1 (Hugging Face). Total cost: ₹0. Card: never asked for.**

## A1. Create the accounts (one-time, ~10 minutes)

| Account | URL | Needed for |
|---|---|---|
| Hugging Face | https://huggingface.co/join | Hosting the server + storing your data (both free) |
| Google AI Studio | https://aistudio.google.com/ | Your Gemini API key (the AI brain) |

## A2. Get your Gemini API key

1. Go to https://aistudio.google.com/apikey → **Create API key** → copy it
   (starts with `AIza...`).
2. Free tier: ~1,500 requests/day with Gemini Flash — more than enough.

## A3. Create the Space (the server)

In huggingface.co: **Spaces → Create new Space**:

| Setting | Value |
|---|---|
| Space name | `agentcloud` |
| SDK | **Docker** → Blank template |
| Visibility | Private (recommended) or Public |

## A4. Create the state repo (your database)

**Datasets → New dataset**: name `agentcloud-state`, **Private**.
This is where your briefings/stories/subscriptions are stored so they
survive the Space restarting.

## A5. Create a write token

https://huggingface.co/settings/tokens → **New token** → type **Write** →
copy it (starts with `hf_...`).

## A6. Set the Space secrets

In the Space: **Settings → Variables and secrets → New secret** (4 of them):

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | your `AIza...` key |
| `AUTH_TOKEN` | any long random string you invent — this becomes the apps' "Access Token" |
| `HF_TOKEN` | your `hf_...` write token |
| `STATE_REPO` | `your-username/agentcloud-state` |

## A7. Push the code to the Space

On your computer (git + this repo):

```bash
git clone https://github.com/Gshanak/agentcloud.git
cd agentcloud
HF_USERNAME=your-hf-username HF_TOKEN=hf_your-token bash deploy/push_to_space.sh
```

Hugging Face builds the image for a few minutes, then your apps are live:

| App | URL |
|---|---|
| News Curator | `https://your-username-agentcloud.hf.space/news/` |
| Storyteller | `https://your-username-agentcloud.hf.space/stories/` |
| Health check | `https://your-username-agentcloud.hf.space/api/health` |

The first build also runs the news job once if no briefing exists yet, so
you have content within a couple of minutes of the first start.

## A8. Keep the Space awake (important)

Free Spaces sleep after ~48h idle — and a sleeping Space can't run the 07:00
IST briefing. Fix it with a free pinger (no card):

1. https://cron-job.org (free account) → **Create cronjob**
2. URL: `https://your-username-agentcloud.hf.space/api/health`
3. Schedule: every 30 minutes → Create.

## A9. Install the apps on your phone

1. Chrome on Android → open the two URLs above.
2. ⚙ Settings → **Access Token**: paste your `AUTH_TOKEN` → Save.
   (Leave Server URL empty — the apps are served by the same server.)
3. Chrome menu → **Install app** for both.
4. News Curator → Settings → Enable Notifications (push is built in; the
   VAPID keys were generated automatically on first boot).
5. Storyteller narration: if a language voice is missing — Settings →
   Accessibility → Text-to-speech → Google TTS → Install voice data.

## A10. Daily usage

Nothing. The briefing is generated at 07:00 IST and pushed to your phone;
stories are on demand in the Storyteller app. Recurring cost: ₹0.

---

# Path B — Oracle Cloud VM (full AutoGPT platform; card needed)

Everything below needs an Oracle account, which requires a credit card
for verification (never charged on Always Free).

## B1. Accounts

| Account | URL | Cost | Needed for |
|---|---|---|---|
| Oracle Cloud | https://www.oracle.com/cloud/free/ | Free (card for verification) | The VM |
| Google AI Studio | https://aistudio.google.com/ | Free | Gemini API key |
| Cloudflare | https://dash.cloudflare.com/sign-up | Free | HTTPS tunnel |

## B2. Gemini API key

https://aistudio.google.com/apikey → **Create API key** → copy (`AIza...`).

## B3. Create the Oracle VM

**Compute → Create Instance**:

| Setting | Value |
|---|---|
| Name | `agentcloud` |
| Image | Canonical **Ubuntu 22.04** (switch from Oracle Linux) |
| Shape | **VM.Standard.A1.Flex** (Ampere ARM) — 2 OCPUs, **12 GB** |
| Networking | New VCN + public subnet; **assign a public IPv4** |
| SSH keys | Generate in browser, **download both files** |

"Out of host capacity" → retry; free ARM capacity frees up periodically.

## B4. Open ports in the security list

Instance → subnet → **Security Lists** → ingress rules (source `0.0.0.0/0`):
TCP **3000** (close later), **8080**, **8081**.

## B5. Run the setup script

```bash
ssh -i <your-key> ubuntu@<VM_PUBLIC_IP>
sudo apt update && sudo apt install -y git
git clone https://github.com/Gshanak/agentcloud.git
sudo bash agentcloud/deploy/vm-setup.sh
```

15–30 minutes. Installs Docker, clones AutoGPT, applies the overlay, sizes
memory, starts everything.

## B6. First-run platform setup

1. `http://<VM_PUBLIC_IP>:3000` → create your admin account.
2. Close registration: `AUTH_ALLOW_NEW_ACCOUNTS=false` in
   `AutoGPT/autogpt_platform/.env`, then restart `rest_server`.

## B7. Gemini key on the VM

```bash
nano ~/AutoGPT/autogpt_platform/.env    # GEMINI_API_KEY=...
docker compose -f autogpt_platform/docker-compose.platform.yml \
  -f ~/agentcloud/deploy/docker-compose.vm.yml \
  --env-file autogpt_platform/.env up -d rest_server executor
```

## B8. Cloudflare Tunnel (free HTTPS)

```bash
cloudflared tunnel --url http://localhost:3000
```

Copy the `https://xxx.trycloudflare.com` URL. For a permanent URL create a
free named tunnel in the Cloudflare dashboard.

## B9. (Optional) VAPID keys for push

```bash
npx web-push generate-vapid-keys
```

Paste into `.env` per the platform's variable names, restart `rest_server`
and `notification_server`.

## B10. Import graphs + schedule

```bash
cd ~/agentcloud
python3 deploy/schedule_news.py \
  --base https://your-tunnel.trycloudflare.com \
  --token <your-auth-token> \
  --api-key <GEMINI_API_KEY>
```

Or: UI → Build → ⋯ → Import → `graphs/news_curator.json` / `storyteller.json`,
paste the Gemini key into the AutoGen Bridge node, add the 01:30 UTC schedule.

## B11. Install the PWAs

Open `http://<vm-ip>:8080` / `:8081` in Chrome → Settings → paste the tunnel
URL → Install app.

---

## If something breaks

**Path A (Spaces):**
- Space → Logs — build and runtime errors.
- Space stuck sleeping → check your cron-job.org pinger is running.
- 401 from the apps → the Access Token doesn't match the `AUTH_TOKEN` secret.
- Data missing after restart → `HF_TOKEN`/`STATE_REPO` secrets unset or wrong
  repo name; the state file lives in the `agentcloud-state` dataset repo.

**Path B (VM):**
- `docker compose ps` — which service is down
- `docker compose logs rest_server --tail 50` — API errors
- Gemini 429 errors are normal on the free tier; the pipeline retries
  with backoff automatically.
