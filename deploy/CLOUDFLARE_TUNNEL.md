# Agora_UI_Run Public Deployment With Cloudflare Tunnel

Recommended public hostname: `agora.dell.ing`

This deployment publishes the local FastAPI service through Cloudflare Tunnel.
No inbound port needs to be opened on the server.

## What Is Being Published

The local origin serves one product surface:

- `/macro`
- `/pixel`
- `/api/*`

In practice, the origin is the `agora-macro-ui.service` FastAPI process listening on:

- `http://127.0.0.1:8125`

Useful health check:

- `http://127.0.0.1:8125/api/health`

## systemd Services

The current user services are:

- `agora-macro-ui.service`
- `cloudflared-agora.service`

Recommended install path:

- `~/.config/systemd/user/agora-macro-ui.service`
- `~/.config/systemd/user/cloudflared-agora.service`

Reference templates live under:

- `/home/yz_wang/yz_main/Agora_UI_Run/deploy/systemd/`

## Macro UI / FastAPI Service

Install and start the local origin:

```bash
mkdir -p ~/.config/systemd/user
cp /home/yz_wang/yz_main/Agora_UI_Run/deploy/systemd/agora-macro-ui.service ~/.config/systemd/user/agora-macro-ui.service
systemctl --user daemon-reload
systemctl --user enable --now agora-macro-ui.service
systemctl --user status agora-macro-ui.service
```

Expected local behavior:

- `/macro` loads
- `/pixel` loads
- `/api/health` returns `200 OK`

## Cloudflare Tunnel Service

Install the matching tunnel service file:

```bash
mkdir -p ~/.config/systemd/user
cp /home/yz_wang/yz_main/Agora_UI_Run/deploy/systemd/cloudflared-agora.service ~/.config/systemd/user/cloudflared-agora.service
systemctl --user daemon-reload
systemctl --user enable --now cloudflared-agora.service
systemctl --user status cloudflared-agora.service
```

The service should publish the local FastAPI origin to the chosen Cloudflare hostname.

## Important Runtime Detail

`cloudflared-agora.service` should be run with `--no-autoupdate`.

Reason:

- unattended self-update can terminate the tunnel process
- the service will usually restart, but this creates avoidable public churn
- disabling self-update makes the long-running tunnel more stable under systemd

## Cloudflare Dashboard Setup

In the Cloudflare dashboard:

1. create a named tunnel
2. choose the `cloudflared` connector flow
3. configure the public hostname
4. point the service URL at `http://127.0.0.1:8125`

Recommended published route:

- hostname: `agora.dell.ing`
- service: `http://127.0.0.1:8125`

## DNS And Access

Cloudflare can create the proxied DNS route automatically from the tunnel flow.

Recommended setup:

- use a dedicated subdomain such as `agora.dell.ing`
- optionally place Cloudflare Access in front of it

Expected external behavior when Access is enabled:

- the public URL returns a Cloudflare Access redirect or login page
- after login, `/macro` and `/pixel` are reachable through the same host

## Quick Diagnosis Checklist

If the site appears down, check in this order:

1. `systemctl --user status agora-macro-ui.service`
2. `curl -I http://127.0.0.1:8125/api/health`
3. `systemctl --user status cloudflared-agora.service`
4. `journalctl --user -u agora-macro-ui.service -n 100`
5. `journalctl --user -u cloudflared-agora.service -n 100`

Typical failure pattern:

- tunnel is healthy
- local FastAPI origin is hung or not responding

In that case, restart the origin service first.
