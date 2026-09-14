# Exposing the platform over HTTPS with Cloudflare Tunnel (free, no domain)

The AutoGPT Platform listens on the VM's port 3000 by default. Android apps
need a public HTTPS endpoint; Cloudflare Tunnel provides one at no cost, without
opening any inbound firewall port or buying a domain.

## 1. Install cloudflared

```bash
# On the VM (ARM):
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /usr/local/bin/cloudflared
sudo chmod +x /usr/local/bin/cloudflared
```

## 2. Run a quick tunnel (instant, no account needed)

This gives you a random `*.trycloudflare.com` URL — fine for development:

```bash
cloudflared tunnel --url http://localhost:3000
```

Copy the printed URL (e.g. `https://random-words-xxxx.trycloudflare.com`).
Your Android app connects to `<that-url>/api/...` over HTTPS.

The quick tunnel dies when you stop `cloudflared`. For a persistent URL:

## 3. Named tunnel (stable URL, free Cloudflare account)

```bash
cloudflared tunnel login          # authenticate (associates with your account)
cloudflared tunnel create agentcloud
# Edit the config below, then:
cloudflared tunnel route dns agentcloud agent.yourdomain.com
cloudflared tunnel run agentcloud
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/ubuntu/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: agent.yourdomain.com
    service: http://localhost:3000
  - service: http_status:404
```

Run as a service so it survives reboots:

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
```

## 4. Point the Android app at it

In the app's Settings screen, set the server URL to the tunnel URL (no
trailing slash). All REST and WebSocket calls then go over HTTPS.

## Security

- The VM's firewall stays closed to inbound traffic; only `cloudflared` makes
  an outbound connection to Cloudflare.
- After creating your admin account on the platform, set
  `AUTH_ALLOW_NEW_ACCOUNTS=false` in `autogpt_platform/.env` and recreate the
  containers to close registration.
