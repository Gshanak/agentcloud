#!/usr/bin/env bash
# One-shot bootstrap for an Oracle Cloud Always Free ARM VM (Ubuntu 22.04/24.04).
#
# Installs Docker, clones the AutoGPT Platform at a pinned commit, applies the
# agentcloud overlay (custom AutoGen bridge block + deps + .env), and starts
# the platform with memory limits sized for the 12 GB free tier.
#
# Usage (as a normal user with sudo):
#   sudo bash deploy/vm-setup.sh
#
# Environment overrides:
#   AUTO_GPT_REF      commit/branch to deploy (default: pinned below)
#   ANDROID_AI_REPO   path to this repo (default: alongside the script)

set -euo pipefail

AUTO_GPT_REF="${AUTO_GPT_REF:-98381ab27f733468bfe1f9c4f4942b4b416d9a8b}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_AI_REPO="${ANDROID_AI_REPO:-$(dirname "$SCRIPT_DIR")}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/agentcloud}"
AUTO_GPT_DIR="$INSTALL_ROOT/AutoGPT"

log() { printf '\033[0;34m[vm-setup]\033[0m %s\n' "$*"; }

# ------------------------------------------------------------------ docker
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  log "Added $USER to the docker group. If this script fails on permissions,"
  log "log out and back in (or run 'newgrp docker') and re-run this script."
fi

# ------------------------------------------------------------- clone autogpt
if [ ! -d "$AUTO_GPT_DIR/.git" ]; then
  log "Cloning AutoGPT at $AUTO_GPT_REF ..."
  mkdir -p "$INSTALL_ROOT"
  git clone https://github.com/Significant-Gravitas/AutoGPT.git "$AUTO_GPT_DIR"
fi
git -C "$AUTO_GPT_DIR" fetch --all --tags
git -C "$AUTO_GPT_DIR" checkout --force "$AUTO_GPT_REF"
log "AutoGPT checked out at $AUTO_GPT_REF"

# ------------------------------------------------------------- apply overlay
log "Applying agentcloud overlay..."
python3 "$ANDROID_AI_REPO/deploy/customize.py" --repo "$AUTO_GPT_DIR"

# ----------------------------------------------------------------- compose up
log "Building and starting the platform (this builds images; expect 10-20 min)..."
cd "$AUTO_GPT_DIR"
docker compose \
  -f autogpt_platform/docker-compose.platform.yml \
  -f "$ANDROID_AI_REPO/deploy/docker-compose.vm.yml" \
  --env-file autogpt_platform/.env \
  up -d --build

log "Done. Services:"
docker compose \
  -f autogpt_platform/docker-compose.platform.yml \
  -f "$ANDROID_AI_REPO/deploy/docker-compose.vm.yml" \
  --env-file autogpt_platform/.env \
  ps

log "Next steps:"
log "  1. Open http://<vm-ip>:3000 and create your admin account."
log "  2. Expose HTTPS via Cloudflare Tunnel - see deploy/CLOUDFLARE_TUNNEL.md."
log "  3. In the Build canvas, the 'AutoGen Bridge' block should now appear."
