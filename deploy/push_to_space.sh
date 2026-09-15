#!/usr/bin/env bash
# Push agentcloud to a Hugging Face Space (the no-card deployment).
#
# One-time prep (browser, ~5 minutes):
#   1. huggingface.co → sign up / log in (free, no card)
#   2. Create a new Space:  Spaces → Create → name: agentcloud, SDK: Docker
#      (Docker template) — visibility: Private is fine.
#   3. Create the state repo: Datasets → New dataset → name: agentcloud-state
#      → make it Private.
#   4. Create a write token: Settings → Access Tokens → New token
#      (type: Write). Copy it.
#   5. In the Space: Settings → Variables and secrets → add:
#        GEMINI_API_KEY, AUTH_TOKEN, HF_TOKEN, STATE_REPO
#
# Then run from the agentcloud repo root:
#   HF_USERNAME=you HF_TOKEN=hf_xxx bash deploy/push_to_space.sh
#
# Afterwards, keep the Space awake with a free pinger (cron-job.org) hitting
#   https://<you>-agentcloud.hf.space/api/health  every 30 minutes.

set -euo pipefail

: "${HF_USERNAME:?Set HF_USERNAME (your Hugging Face username)}"
: "${HF_TOKEN:?Set HF_TOKEN (a Hugging Face WRITE token)}"

SPACE_NAME="${SPACE_NAME:-agentcloud}"
SPACE_URL="https://huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"
GIT_URL="https://${HF_USERNAME}:${HF_TOKEN}@huggingface.co/spaces/${HF_USERNAME}/${SPACE_NAME}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Cloning the Space repo (must already exist: ${SPACE_URL})"
if ! git clone --depth 1 "$GIT_URL" "$WORK/space" 2>/dev/null || [ ! -d "$WORK/space" ]; then
  echo "ERROR: could not clone ${SPACE_URL}" >&2
  echo "Create the Space first (Docker SDK), then re-run." >&2
  exit 1
fi

echo "==> Copying server, overlay, PWAs and the Space README"
cd "$WORK/space"
rm -rf server platform_overlay apps
mkdir -p apps
cp -r "$REPO_ROOT/server" ./server
cp -r "$REPO_ROOT/platform_overlay" ./platform_overlay
cp -r "$REPO_ROOT/apps/news-curator-pwa" ./apps/news-curator-pwa
cp -r "$REPO_ROOT/apps/storyteller-pwa" ./apps/storyteller-pwa
# The Space README carries the HF metadata; keep the local one under server/.
cp "$REPO_ROOT/server/README.md" ./README.md
# HF Spaces requires the Dockerfile at the repo root; its COPY paths already
# reference server/, platform_overlay/ and apps/ relative to the root.
cp "$REPO_ROOT/server/Dockerfile" ./Dockerfile

echo "==> Committing and pushing"
git add -A
git -c user.name="agentcloud" -c user.email="agentcloud@users.noreply.hf.co" \
  commit -m "agentcloud: server + overlay + PWAs" >/dev/null
git push origin main 2>/dev/null || git push origin master

echo ""
echo "Done. Hugging Face is now building the image (takes a few minutes)."
echo "Apps:  https://${HF_USERNAME}-${SPACE_NAME}.hf.space/news/"
echo "       https://${HF_USERNAME}-${SPACE_NAME}.hf.space/stories/"
echo "Health: https://${HF_USERNAME}-${SPACE_NAME}.hf.space/api/health"
echo ""
echo "Reminder: set the Space secrets (GEMINI_API_KEY, AUTH_TOKEN, HF_TOKEN,"
echo "STATE_REPO) and set up a keep-awake pinger — see SETUP.md."
