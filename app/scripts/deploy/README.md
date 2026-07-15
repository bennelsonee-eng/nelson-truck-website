# Hetzner deployment artifacts

Files in this directory are the live `/etc/systemd/system/` unit files
that run the Titan website on the Hetzner server `titan-prod`
(`5.78.197.15` / Tailscale `100.106.251.97`).

## Install / refresh

After editing a unit file, sync to the server and reload systemd:

```bash
# from laptop (Tailscale-tailnet)
scp app/scripts/deploy/titan-backend.service titan@100.106.251.97:/tmp/
scp app/scripts/deploy/titan-frontend.service titan@100.106.251.97:/tmp/

# on the server
ssh titan@100.106.251.97
sudo install -m 644 /tmp/titan-backend.service /etc/systemd/system/
sudo install -m 644 /tmp/titan-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart titan-backend titan-frontend
```

## Status check

```bash
sudo systemctl is-active  titan-backend titan-frontend   # → active / active
sudo systemctl is-enabled titan-backend titan-frontend   # → enabled / enabled
sudo journalctl -u titan-backend -n 50 --no-pager
sudo journalctl -u titan-frontend -n 50 --no-pager
# or the rolling logs we point them at
sudo tail -f /var/log/titan-backend.log
sudo tail -f /var/log/titan-frontend.log
```

## Why these exist

Before 2026-05-13 the backend ran via `nohup` and the frontend via
`systemd-run --user --unit=titan-vite-test`.  Neither survived a
reboot.  When the Hetzner box was rescaled (CPX21 → CPX31 to make
room for the Nelson ERP), the rescale reboot took the site down.
These unit files make both services auto-start at boot.

Docker containers (postgres / typesense / maildev) already auto-restart
via `restart: unless-stopped` in `app/docker-compose.yml`, so the DB
side has always been reboot-safe.

Tailscale Serve config is persisted by Tailscale itself (1.50+ feature)
so the public URL `https://titan-prod.tail0c2fbc.ts.net/` survives
reboots without any extra wiring.
