# Titan Truck Website — Operations Notes

**Purpose:** Running record of every setup decision, command, config, and credential location. This is the source-of-truth document for someone who needs to maintain, debug, or rebuild the system.

**Status:** Living document — updated as we build. Will be converted to a polished `.docx` at Phase 1 launch.

**Owner:** Ben Nelson
**Project start:** 2026-04-25

---

## Table of Contents
1. [Architecture overview](#1-architecture-overview)
2. [Hetzner Cloud server](#2-hetzner-cloud-server)
3. [Tailscale](#3-tailscale)
4. [User accounts on the server](#4-user-accounts-on-the-server)
5. [Software stack installed on server](#5-software-stack-installed-on-server)
6. [Firewall + intrusion protection](#6-firewall--intrusion-protection)
7. [Local development environment (Windows laptop)](#7-local-development-environment-windows-laptop)
8. [Project layout](#8-project-layout)
9. [Database](#9-database)
10. [Search engine (Typesense)](#10-search-engine-typesense)
11. [Email service](#11-email-service)
12. [Payments (Authorize.net)](#12-payments-authorizenet)
13. [DNS + SSL (Cloudflare)](#13-dns--ssl-cloudflare)
14. [Order push to FACS (FTP)](#14-order-push-to-facs-ftp)
15. [Backups](#15-backups)
16. [Monitoring + alerting](#16-monitoring--alerting)
17. [Deployment workflow](#17-deployment-workflow)
18. [Credentials inventory](#18-credentials-inventory)
19. [Common operations](#19-common-operations)
20. [Troubleshooting](#20-troubleshooting)

---

## 1. Architecture overview

| Layer | Component | Where | Why |
|---|---|---|---|
| Edge / DNS | Cloudflare | cloud | DDoS protection, SSL, CDN, WAF |
| Web server | nginx (TBD — to be installed) | Hetzner Linux server | Reverse proxy, routes traffic to FastAPI + serves static frontend |
| Backend | FastAPI + SQLAlchemy + Python 3.12 | Hetzner Linux server | API for catalog, cart, checkout, account |
| Frontend | React 19 + Vite + TypeScript | Hetzner Linux server | Customer-facing UI |
| Database | PostgreSQL 16 (Docker) | Hetzner Linux server | Catalog, customer, order, contract data |
| Search | Typesense (Docker) | Hetzner Linux server | Fast catalog search + autocomplete |
| Payments | Authorize.net (cards + ACH) | external SaaS | Process credit card transactions |
| Email | Postmark/SendGrid (TBD) | external SaaS | Order confirmations, transactional, marketing |
| Order pickup | Spokane Computer FACS via FTP | external | Receives order CSVs to fulfill |
| Source data | Titan MySQL | external (current PHP-managed) | Pricing, inventory, customer master |
| Future | Titan ERP (Nelson ERP codebase) | Hetzner Linux server (same box) | Replaces Spokane Computer over Phase 2 |

---

## 2. Hetzner Cloud server

### Account
- **Provider:** Hetzner Cloud (`console.hetzner.cloud`)
- **Project name:** `titan`
- **Server name:** `titan-prod`

### Specs (rescaled 2026-05-13 to CCX33 for Nelson ERP co-tenancy)
- **Type:** CCX33 (8 dedicated vCPU AMD, 32 GB RAM, 240 GB SSD)
  - Originally provisioned 2026-04-25 as CPX21 (3 vCPU AMD, 4 GB RAM, 80 GB SSD).
  - Rescaled to CCX33 when Nelson ERP was co-located on the same box — needed
    dedicated CPU + more RAM for two ERPs + two websites + Postgres + Typesense.
    See `nelson-erp/CLOUD_DEPLOYMENT_PLAN.md` Section 4.1.
- **Location:** Hillsboro, OR (US-West)
- **Image:** Ubuntu 24.04 LTS
- **Public IPv4:** `5.78.197.15`
- **Public IPv6:** (in Hetzner UI)
- **Tailscale IP:** `100.106.251.97`
- **Backups:** ENABLED (~20% surcharge, daily snapshots, 7-day retention)
- **Cost:** ~€57.30/mo CCX33 + ~20% backups ≈ ~$75 USD/mo total

### Upgrading the server later
Hetzner UI → Servers → titan-prod → "Rescale" tab. Two cases:
- **Within same CPU class** (e.g. CCX33 → CCX43): ~30 sec reboot, data preserved.
- **Crossing CPU classes** (shared CPX ↔ dedicated CCX): Hetzner requires powering
  off the server first. Power off → Rescale → Power on. ~1-2 min total. Data preserved.

### Console access (out-of-band, if SSH ever fails)
Hetzner UI → Servers → titan-prod → "Console" tab → opens a web-based VNC console. Useful if SSH config gets borked.

---

## 3. Tailscale

### Setup
- Same Tailscale account as the Linux llama (`100.85.94.57`) — single tailnet
- Tailscale 1.96.4 installed via official script: `curl -fsSL https://tailscale.com/install.sh | sh`
- Joined tailnet via: `tailscale up --ssh` (interactive auth in browser)
- `--ssh` flag enables Tailscale SSH (key-free SSH between tailnet nodes)

### Tailnet inventory (as of 2026-04-25)
| Hostname | Tailscale IP | Role |
|---|---|---|
| (Windows laptop) | (varies) | Dev workstation |
| nte (Linux llama) | 100.85.94.57 | Interview app, Ollama, ComfyUI |
| titan-prod | 100.106.251.97 | Titan website + future ERP |
| (Windows ERP, OFFLINE) | 100.117.35.14 | Old Nelson ERP — retired |

### How to SSH to the server
- **Public:** `ssh root@5.78.197.15` or `ssh titan@5.78.197.15`
- **Tailscale:** `ssh root@100.106.251.97` or `ssh titan@100.106.251.97`
- **Tailscale SSH (no key needed):** `ssh root@titan-prod` (if your laptop is also on Tailscale and Tailscale SSH is configured)

### Future: lock down public SSH
Once we're confident on Tailscale-only access, edit `/etc/ssh/sshd_config` to bind SSH only to the Tailscale interface:
```
ListenAddress 100.106.251.97
```
Then `systemctl restart sshd`. Hetzner Cloud Firewall can also block port 22 inbound from public.

---

## 4. User accounts on the server

| User | Purpose | Auth | Sudo |
|---|---|---|---|
| `root` | Initial setup, emergency access | SSH key (Ben's `id_ed25519`) | n/a (is root) |
| `titan` | Runs the website + ERP processes | SSH key (same key, copied from root) | yes (password-required) |

App processes should run as `titan`, NOT root. SSH key for titan is the same as root's (copied from `/root/.ssh/authorized_keys`).

---

## 5. Software stack installed on server

| Tool | Version | Install method |
|---|---|---|
| Ubuntu | 24.04 LTS | Hetzner image |
| Linux kernel | 6.8 | (default) |
| Tailscale | 1.96.4 | Official install script |
| Docker Engine | 29.4.1 | get.docker.com official script |
| Docker Compose | v5.1.3 | (bundled with Docker Engine plugin) |
| Python | 3.12.3 | apt (default on 24.04) |
| python3-venv, python3-pip, libpq-dev | (latest) | apt |
| Node.js | 20.20.2 (LTS) | NodeSource apt repo |
| npm | 10.8.2 | (bundled with Node) |
| psql (PostgreSQL client) | 16.13 | apt |
| UFW (firewall) | (default) | apt |
| fail2ban | (default) | apt |
| build-essential, curl, git, vim, htop | (latest) | apt |

### Installation commands (replay if rebuilding)
```bash
# (As root, fresh Ubuntu 24.04 install)

# 1. System update + base packages
apt update && apt upgrade -y
apt install -y curl wget git build-essential ca-certificates gnupg lsb-release \
    ufw fail2ban htop unzip vim nano

# 2. Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --ssh   # (interactive — click URL, authorize in browser)

# 3. titan user
adduser titan --disabled-password --gecos ""
usermod -aG sudo titan
mkdir -p /home/titan/.ssh
cp /root/.ssh/authorized_keys /home/titan/.ssh/
chown -R titan:titan /home/titan/.ssh
chmod 700 /home/titan/.ssh
chmod 600 /home/titan/.ssh/authorized_keys

# 4. Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker titan
systemctl enable --now docker

# 5. Python deps for FastAPI/SQLAlchemy
apt install -y python3 python3-venv python3-pip python3-dev libpq-dev

# 6. Node 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# 7. Postgres client
apt install -y postgresql-client-16
```

---

## 6. Firewall + intrusion protection

### UFW (host-level firewall)
- Default: deny incoming, allow outgoing
- Allowed inbound: 22/tcp (SSH), 80/tcp (HTTP), 443/tcp (HTTPS)
- Tailscale interface bypasses UFW (nodes on the tailnet can reach any port)

### fail2ban
- Watches `/var/log/auth.log` for SSH brute-force attempts
- Bans IP after 5 failed attempts for 10 minutes (default)
- Status: `fail2ban-client status sshd`
- Unban an IP: `fail2ban-client set sshd unbanip <IP>`

### Hetzner Cloud Firewall (TBD)
Optional second layer at the cloud network level (before traffic even hits the server). Can be configured later via Hetzner UI → Firewalls.

---

## 7. Local development environment (Windows laptop)

### Required tools (verified versions on Ben's laptop, 2026-04-25)
| Tool | Required | Ben's version | Install link |
|---|---|---|---|
| **VS Code** | latest | (TBD — installer downloaded `VSCodeUserSetup-x64-1.117.0.exe`) | `code.visualstudio.com` |
| **Claude Code** extension | latest | TBD | VS Code marketplace |
| **Docker Desktop for Windows** | 4.x AMD64 | (just installed) | `docker.com/products/docker-desktop` |
| **Python** | 3.11+ | 3.12.10 ✅ | `python.org/downloads/` |
| **Node.js** | 20+ | 24.14.0 ✅ (newer than LTS, fully fine) | `nodejs.org` |
| **Git** | latest | installed ✅ | `git-scm.com` |
| **PowerShell** | 5.1+ | built-in ✅ | Windows |

### Architecture confirmed
- `$env:PROCESSOR_ARCHITECTURE` returns `AMD64` → standard Intel/AMD 64-bit (NOT Snapdragon ARM64)
- AMD64 Docker installer is the right one (the "AMD" in AMD64 is historical — works on Intel too)

### SSH key location
- Private: `C:\Users\Ben\.ssh\id_ed25519`
- Public: `C:\Users\Ben\.ssh\id_ed25519.pub`
- This same key authorizes both `root` and `titan` on the Hetzner server

### Project location
- `C:\Users\Ben\titan truck website\` — root (git repo)
- `C:\Users\Ben\titan truck website\app\` — code (backend + frontend + scripts + docker-compose)
- `C:\Users\Ben\titan truck website\discovery\` — interview notes, walk findings, design intent log
- `C:\Users\Ben\titan truck website\SOW_v0.1.md` + addenda — statement of work
- `C:\Users\Ben\titan truck website\OPERATIONS_NOTES.md` — this file

### Docker Desktop install — gotchas encountered (2026-04-25)

**Issue 1: "For security reasons C:\ProgramData\DockerDesktop must be owned by an elevated account"**
- Cause: leftover folder from a previous failed install attempt with wrong ownership
- Fix: open PowerShell as **Administrator**, then:
  ```powershell
  Remove-Item -Path "C:\ProgramData\DockerDesktop" -Recurse -Force
  ```
  Then re-run the installer with right-click → "Run as administrator"

**Issue 2: "Another instance is running, please wait for it to finish"**
- Cause: stuck installer process from a prior attempt
- Fix:
  ```powershell
  Get-Process | Where-Object { $_.ProcessName -like "*docker*" -or $_.ProcessName -eq "msiexec" }
  Stop-Process -Name "Docker Desktop Installer" -Force -ErrorAction SilentlyContinue
  Stop-Process -Name "msiexec" -Force -ErrorAction SilentlyContinue
  ```
  If still stuck, restart Windows.

**Install option to UNCHECK during setup:** "Use Windows containers instead of Linux containers" — we run Linux software (Postgres, Typesense, our Python app, Node frontend), so we want Linux containers (default).

**Install options to KEEP CHECKED:** "Use WSL 2 instead of Hyper-V (recommended)".

**After install:** restart Windows, then launch Docker Desktop normally (not as admin), wait for whale icon in system tray to be solid (not animating) — means daemon is fully ready.

### First-time scaffold run (local development)

```powershell
cd "C:\Users\Ben\titan truck website\app"
copy .env.example .env

# Start local Postgres + Typesense + maildev (background)
docker compose up -d

# --- Terminal 1: backend ---
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8001

# --- Terminal 2: frontend (new PowerShell window) ---
cd "C:\Users\Ben\titan truck website\app\frontend"
npm install
npm run dev
```

Open `http://localhost:5174`. Should see "Titan Truck Equipment" placeholder home + clickable "API Health Check" link that confirms FastAPI ↔ Postgres wired correctly.

### Common Windows-specific issues
- **Docker Desktop won't start** → make sure WSL2 is enabled (`wsl --install` if missing)
- **Port already in use** → another service grabbed our port. Find with `netstat -ano | findstr :8001` and kill the PID via Task Manager
- **`pip install` fails with SSL errors** → corporate VPN/proxy can interfere. Try `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt`
- **`npm install` very slow** → normal first time (~3-5 min). If consistently slow, check for corporate proxy

---

## 8. Project layout

See `app/README.md` for full directory tree. Highlights:

```
app/
├── backend/                FastAPI + SQLAlchemy + Alembic
├── frontend/               React 19 + Vite + TypeScript
├── scripts/                One-off migrations + utilities
├── docker-compose.yml      Local Postgres + Typesense + maildev
├── .env.example
└── README.md
```

### Port assignments
| Service | Titan | Nelson ERP (don't collide) |
|---|---|---|
| Backend (FastAPI) | 8001 | 8000 |
| Frontend (Vite dev) | 5174 | 5173 |
| Frontend (Vite preview) | 4174 | 4173 |
| Postgres (Docker) | host 5433 → container 5432 | 5432 (native) |
| Typesense | 8108 | (n/a) |
| maildev web / SMTP | 1080 / 1025 | (n/a) |

---

## 9. Database

### Local (development)
- Postgres 16 in Docker (`titan_postgres` container)
- Connection: `postgresql://postgres:titan2026@localhost:5433/titan_web`
- Data persisted in Docker volume `titan_postgres_postgres_data`

### Production (Hetzner) — TBD
- Will run Postgres 16 in Docker on the Hetzner server (same docker-compose pattern)
- Production password will be different from `titan2026` — to be set in `.env` on server
- Daily backups via `pg_dump` to Backblaze B2

### Migrations
- Alembic-managed (`backend/alembic.ini`, `backend/migrations/`)
- Apply: `alembic upgrade head`
- Generate new migration after model changes: `alembic revision --autogenerate -m "description"`

---

## 10. Search engine (Typesense)

- Self-hosted Typesense 0.25.2 in Docker
- Local API key: `titan_search_dev_key` (dev only — production gets a real one in `.env`)
- Local port: 8108
- Data persisted in Docker volume

### Why Typesense (not Algolia)
- Open source, self-hosted = no monthly bill
- Algolia-comparable speed (sub-100ms)
- Extensible (build/extend over vendor-managed — DI-016)
- Hybrid search support for future Phase 2 AI rerank

### Index management
- Catalog index gets pushed via `services/search.py` (TBD — Week 1 work)
- Reindex full catalog: `python scripts/reindex.py` (TBD)

---

## 11. Email service

**Status:** TBD — choose between Postmark, SendGrid, Mailchimp before Week 2.

Once chosen:
- API key in `.env` as `EMAIL_API_KEY`
- Sender address: `sales@titantruck.com` (must be verified with provider)
- Templates in `backend/app/services/email_templates/`

---

## 12. Payments (Authorize.net)

**Existing Authorize.net merchant account** — credentials TBD (Ben needs to dig out from records).

Required values:
- API Login ID (`AUTHNET_API_LOGIN_ID`)
- Transaction Key (`AUTHNET_TRANSACTION_KEY`)
- Public Client Key (`AUTHNET_PUBLIC_CLIENT_KEY`) — for Accept.js client-side tokenization

Sandbox vs production: switch with `AUTHNET_ENVIRONMENT=sandbox|production` in `.env`. Sandbox is free; production processes real transactions.

PCI scope: Accept.js handles tokenization in the browser; our server never sees raw card numbers. Keeps PCI-DSS scope to "SAQ A" (lightest tier).

---

## 13. DNS + SSL (Cloudflare)

- titantruck.com is already on Cloudflare
- DNS records currently point to old WSM site
- During cutover (week 4): change A record to point to Hetzner server (`5.78.197.15`)
- Cloudflare provides SSL automatically (Universal SSL)
- Origin pull cert configured so only Cloudflare can hit our server (TBD)

---

## 14. Order push to FACS (FTP)

See `SOW_v0.1_addendum_003.md` for full algorithm (reverse-engineered from existing PHP).

- FACS pulls files from FTP folder (one-way; we drop, FACS picks up)
- File naming: `ORDERS_TITAN_{TYPE}_{ORDER#}_{WAREHOUSE#}.CSV`
- Active routes: SPO (Spokane), BOISE, NELSON (Kent + Portland combined), BO (back-order)
- One web order can produce up to 4 CSVs depending on stock split

### FTP credentials
- Host, port, user, pass: TBD (Ben to provide)
- Dropbox path: TBD (current PHP uses `/var/www/html/ne/nelsontruck.com/titan_orders/`)

---

## 15. Backups

### Hetzner snapshots
- Daily auto-snapshot at 02:00 UTC (when backups are enabled)
- 7-day retention
- Restore: Hetzner UI → Server → "Backups" tab → select snapshot → "Restore"

### Database (TBD)
- Nightly `pg_dump` to Backblaze B2 (~$6/TB/mo, encrypted at rest)
- Retention: TBD (probably 30 days daily, then weekly for 90 days)
- Monthly restore test (verify backup is valid)

### Application code
- Git repository (push to GitHub TBD)
- Local copy on Ben's laptop at `C:\Users\Ben\titan truck website\`

---

## 16. Monitoring + alerting

**TBD** — to be configured Phase 1:
- **Uptime:** UptimeRobot (free tier) hits `/api/health` every 5 min, alerts on failure
- **Errors:** Self-hosted GlitchTip (or Sentry) for application exceptions
- **Logs:** journalctl on Hetzner server; rotate via systemd
- **Disk space:** weekly check via cron, alert if >80%
- **FACS pickup lag:** custom alert if order CSV sits unpicked > 30 min

---

## 17. Deployment workflow

### Source-of-truth: GitHub
- **Private repo:** https://github.com/bennelsonee-eng/titan-truck-website
- Created via `gh repo create titan-truck-website --private --source=. --remote=origin --push`
- Branch: `main` (only branch — no feature branches yet)
- Push from anywhere: `git push` (origin remote already configured)
- Clone fresh: `git clone https://github.com/bennelsonee-eng/titan-truck-website.git`

### Deploy to Hetzner (verified working — first-light 2026-04-25)

**Repo lives at:** `/home/titan/titan-truck-website/` on the server.
**Code dir:** `/home/titan/titan-truck-website/app/`.
**Background-process PIDs:** `/home/titan/uvicorn.pid`, `/home/titan/vite.pid`.
**Logs:** `/home/titan/uvicorn.log`, `/home/titan/vite.log`.

#### First-time setup (already done, but documented for rebuild)
```bash
# As titan user
cd /home/titan
ssh-keygen -t ed25519 -f /home/titan/.ssh/github_deploy -N '' -C 'titan-prod-deploy-key'
# Configure git to use the deploy key for github.com
cat > /home/titan/.ssh/config <<'EOF'
Host github.com
  HostName github.com
  User git
  IdentityFile /home/titan/.ssh/github_deploy
  IdentitiesOnly yes
EOF
chmod 600 /home/titan/.ssh/config
ssh-keyscan github.com >> /home/titan/.ssh/known_hosts

# Add the deploy public key to the GitHub repo (Settings → Deploy keys → Add):
cat /home/titan/.ssh/github_deploy.pub
# Title: "titan-prod (Hetzner)" — check "Allow write access"

# Clone (use a clean directory name to avoid confusion with the app/ subdirectory)
git clone git@github.com:bennelsonee-eng/titan-truck-website.git titan-truck-website
cd titan-truck-website/app
cp .env.example .env
# Edit .env for production secrets when ready (currently using dev defaults)
```

#### Updating after a `git push` from local
```bash
cd /home/titan/titan-truck-website
git pull

# Restart backend
kill $(cat /home/titan/uvicorn.pid) 2>/dev/null || true
cd app/backend
.venv/bin/pip install -r requirements.txt   # only if requirements changed
.venv/bin/alembic upgrade head
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 > /home/titan/uvicorn.log 2>&1 &
echo $! > /home/titan/uvicorn.pid

# Restart frontend
kill $(cat /home/titan/vite.pid) 2>/dev/null || true
cd ../frontend
npm install                                # only if package.json changed
nohup npm run dev > /home/titan/vite.log 2>&1 &
echo $! > /home/titan/vite.pid
```

#### Stop everything
```bash
kill $(cat /home/titan/uvicorn.pid /home/titan/vite.pid) 2>/dev/null
cd /home/titan/titan-truck-website/app
docker compose down
```

#### Access (during dev / first-light)
- **Tailscale (preferred):** `http://100.106.251.97:5174` (frontend) and `http://100.106.251.97:8001/api/health` (backend)
- **SSH:** `ssh titan@100.106.251.97` (or `ssh titan@5.78.197.15` via public IP)
- **Public IPs of 5174/8001 are blocked by UFW** — only 22/80/443 are reachable from the internet
- **Tailscale interface is allowed via** `ufw allow in on tailscale0`

**TBD: Production deployment (Phase 1):**
- nginx reverse proxy + Let's Encrypt SSL via certbot
- systemd service for uvicorn (`titan-backend.service`)
- Static frontend served by nginx from `/var/www/titan/`
- Cloudflare in front (DNS already on Cloudflare)
- Auto-deploy on `git push` (TBD: GitHub Actions workflow)

Tentative plan:
1. Develop locally on laptop
2. Commit to git, push to GitHub (private repo)
3. SSH to Hetzner: `cd /home/titan/app && git pull`
4. Backend: `pip install -r requirements.txt && alembic upgrade head && systemctl restart titan-backend`
5. Frontend: `npm install && npm run build && systemctl restart nginx` (or `cp dist/ /var/www/...`)

systemd service files for backend will be in `app/scripts/deploy/`.

---

### Truck-body manufacturer content — ported from Titan, live on nelson-prod 2026-09-22

Knapheide, CM Truck Beds, Rugby and Dur-A-Lift images, specs, standard features (FEA), optional
equipment (OPT, shown as "Available Options -- not included"), spec tables and literature PDFs for the
77 bodies/lifts, the Knapheide-based Truck Bodies category tree, and the parts listed under the body
they fit. Code and data came from Titan commits `8faca8f` + `7160739`; Titan's own write-up is its
OPERATIONS_NOTES section 17. The 77 products have the same ids on nelson_web and titan_web (checked
2026-09-21), so the model maps in `discovery/manufacturer_data/` are shared as-is.

**Rules (Ben, 2026-09-20):** everything on these pages is served from our own server (no hotlinked
images/PDFs, no YouTube/Vimeo players) and no manufacturer customer stories.
`check_manufacturer_content_local.py` counts nelsontruck.com / nelsontruckequipment.com as ours and
titantruck.com as off-site.

Nelson-specific differences from Titan:
- The two migrations (`b6t0u4v8w2x6` product_spec_table, `c7u1v5w9x3y7` product_accessory) are
  re-parented onto Nelson's `m2p5q9r3s7t1`. If Titan's intermediate migrations are ever ported, put
  them before these two.
- `app/backend/static/` is git-ignored here and `static/category-images` is a symlink on the box, so
  the category tiles live in `discovery/manufacturer_data/truck_body_tiles/` and are copied by hand.
- Nelson has no post-merge hook: every step below is manual. No nightly reindex timer either.
- `/products/{sku}/accessories` counts stock with Nelson's `on_hand_map` (total on hand).

As run on nelson-prod 2026-09-22 (from `app/backend/`, after `git pull`):
1. Backup first: `pg_dump nelson_web | gzip > /home/titan/backup-nelson_web-pre-truck-bodies-<ts>.sql.gz`.
2. `.venv/bin/python -m alembic upgrade head`, then `sudo systemctl restart nelson-backend.service`.
3. `cp -n ../../discovery/manufacturer_data/truck_body_tiles/* static/category-images/truck-bodies/`
4. `.venv/bin/python ../scripts/restructure_truck_body_categories.py --apply` (dry run first).
5. `.venv/bin/python ../scripts/import_manufacturer_body_images.py --brand <b> --apply` for
   knapheide, cm, rugby, duralift (downloads from the manufacturers; resized into static/product-images).
6. `.venv/bin/python ../scripts/import_manufacturer_body_content.py --brand <b> --apply`, same four
   brands, AFTER step 5. PDFs land in static/product-resources/<source>/.
7. `.venv/bin/python ../scripts/link_truck_body_parts.py --apply` (8,145 links; KNP-33670260 unmatched).
8. `.venv/bin/python ../scripts/check_manufacturer_content_local.py` must print OK. On 2026-09-22 it
   flagged 36 Dur-A-Lift YouTube rows (`source='duralift_harvest_2026_07'`), removed with a JSON backup
   in `discovery/manufacturer_data/product_resource_backup_duralift_youtube_20260922.json` (on the box).
9. Reindex from `app/` so settings read `app/.env`: `backend/.venv/bin/python scripts/reindex_typesense.py`.
10. `cd ../frontend && npm run build`, then `sudo systemctl restart nelson-prerender.service`.

Per-run backups (images, content, categories, accessory links) are written to
`discovery/manufacturer_data/*_backup_*.json` on the box; they are git-ignored.

---

## 18. Credentials inventory

⚠️ **Never commit credentials to git.** Stored in `.env` on each environment (gitignored). Master copies kept in a password manager (1Password / Bitwarden / similar).

| Credential | Where used | Where to find / set |
|---|---|---|
| Hetzner Cloud API token | Provisioning automation (TBD) | Hetzner UI → Security → API tokens |
| SSH private key | Laptop → server | `C:\Users\Ben\.ssh\id_ed25519` |
| Tailscale account | All tailnet nodes | (your Tailscale login) |
| Postgres password (prod) | Backend `.env` on server | Set in `.env`, never in code |
| Typesense API key (prod) | Backend `.env` on server | Set in `.env` |
| Authorize.net API Login + Trans Key | Backend `.env` on server | Authorize.net merchant portal |
| Authorize.net Public Client Key | Frontend env (built into bundle) | Authorize.net merchant portal |
| Email service API key | Backend `.env` on server | Provider portal (Postmark/SendGrid) |
| Cloudflare API token | DNS/cache automation (TBD) | Cloudflare dashboard → API Tokens |
| FACS FTP creds | Backend `.env` on server | (Spokane Computer team) |
| Titan MySQL creds (read-only) | Backend `.env` on server | (current PHP infrastructure) |
| PACE / AAM Group API key | Backend `.env` on server | (per the PACE agreement, ~Wednesday) |
| Backblaze B2 keys (backups) | Backend `.env` on server | b2 console → Application Keys |

---

## 19. Common operations

### SSH to the server
```powershell
ssh root@100.106.251.97       # via Tailscale
ssh titan@100.106.251.97      # via Tailscale, app user
ssh root@5.78.197.15           # via public IP (fallback)
```

### Check if services are running
```bash
docker compose ps              # in /home/titan/app/
systemctl status titan-backend
systemctl status nginx
```

### View logs
```bash
journalctl -u titan-backend -f         # backend logs (live)
journalctl -u nginx -f                 # nginx logs (live)
docker compose logs postgres           # postgres logs
docker compose logs typesense          # typesense logs
```

### Update from git + restart
```bash
cd /home/titan/app
git pull
cd backend
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
sudo systemctl restart titan-backend
cd ../frontend
npm install
npm run build
sudo systemctl reload nginx
```

### Restart everything (panic button)
```bash
sudo systemctl restart titan-backend nginx
docker compose restart
```

---

## 20. Troubleshooting

### Can't SSH (Permission denied)
- Verify SSH key is at `C:\Users\Ben\.ssh\id_ed25519`
- Verify the public key is in `/root/.ssh/authorized_keys` on server (use Hetzner web console if locked out)
- Test with verbose: `ssh -v root@5.78.197.15`

### Site is down
1. Hit `https://titantruck.com/api/health` — does it respond?
2. SSH to server, check `journalctl -u titan-backend -f` for errors
3. Check `docker compose ps` — is Postgres/Typesense up?
4. Check Cloudflare status (https://www.cloudflarestatus.com)
5. If Hetzner server is down: Hetzner UI → server status

### Database connection errors
- Verify Postgres container is up: `docker compose ps`
- Check `.env` for correct `DATABASE_URL`
- Test connection: `psql -h localhost -p 5433 -U postgres titan_web`

### Order didn't reach FACS
1. Check application logs for IMS315 push attempt
2. Check FTP folder on server: did the file get written?
3. SSH to FACS server (or ask Spokane Computer team) — did file appear there?
4. Check FACS pickup logs (Spokane Computer team)
5. Manual replay: admin UI → orders → find order → "Re-push to FACS"

---

## Document history

| Date | Change |
|---|---|
| 2026-04-25 | Initial creation. Captured server provisioning + Tailscale + Docker/Python/Node + UFW/fail2ban + scaffold layout. Many sections still TBD pending Week 1 work. |
| 2026-04-25 (later) | Added Docker install gotchas (ProgramData ownership, stuck installer process, Linux-vs-Windows containers choice). Confirmed Ben's laptop architecture = AMD64. Initialized git repo at project root, created private GitHub repo (https://github.com/bennelsonee-eng/titan-truck-website), pushed first commit (`f96bc5f`). Docker Desktop installed (29.4.0). Local docker-compose stack verified working: Postgres healthy on port 5433, Typesense healthy on port 8108, maildev on 1080/1025. Added deployment workflow section. |
| 2026-04-25 (evening) | **First-light deployment to Hetzner verified.** Set up GitHub deploy key for server (`titan-prod (Hetzner)` with read+write), cloned repo to `/home/titan/titan-truck-website/`. Added UFW rule `allow in on tailscale0` so frontend/backend ports are reachable via Tailscale only (public still gated to 22/80/443). Granted titan NOPASSWD sudo for ops convenience. Vite config updated to bind `host: true` and `allowedHosts: true` for Tailscale/cloud access. Docker stack up on server (postgres/typesense/maildev). Backend running as nohup background process (PID stored in `/home/titan/uvicorn.pid`). Frontend Vite dev server running as nohup (PID in `/home/titan/vite.pid`). Verified end-to-end: `http://100.106.251.97:5174` returns 200, `http://100.106.251.97:8001/api/health` returns `{db_ok: true}`. **Local + Hetzner both running side-by-side, same codebase.** Custom md_to_docx.py converter built (`app/scripts/md_to_docx.py`); regenerates OPERATIONS_NOTES.docx anytime via `python app/scripts/md_to_docx.py OPERATIONS_NOTES.md OPERATIONS_NOTES.docx --title "..." --subtitle "..."`. |
| 2026-04-25 (later evening) | **Week 1 build started.** WSM catalog CSVs (4 product files + categories file) moved to `app/data/wsm_export/` (gitignored). Built streaming CSV analyzer (`app/scripts/analyze_wsm_export.py`) — analyzed the 366 MB / 118,072-product file in seconds. Findings logged to `discovery/notes/07_wsm_catalog_analysis.md`: 125 brands (Currie + WeatherTech = 30% of catalog), 1,645 categories, 94.9% have images (all hosted at nelsontruck.com), 22% are HIDDEN, 23% have SHIP QUOTE flag set. **Two key user decisions captured: DI-029** (image hosting Phase 1 = Nelson cross-domain, migrate to Hetzner pre-launch) and **DI-030** (import all 125 brands — preserves URL/SEO continuity). **First SQLAlchemy schema deployed.** 8 model files (`catalog`, `warehouse`, `pricing`, `customer`, `order`, `auth`, `audit` + base) → 17 tables in Postgres. First Alembic migration `f5d215d1f6f6_initial_schema` generated and applied to BOTH local and Hetzner Postgres. Verified via SQL count + `/api/health` still returns `db_ok:true`. |
| 2026-04-25 (night) | **MySQL data extraction pipeline established.** Built `app/scripts/dump_titan_tables.php` — token-protected PHP endpoint that streams MySQL tables as CSV. Uploaded to TigerTech web root via cPanel. Reach via direct hostname `https://nelsontruck.com.customers.tigertech.net/dump_titan_tables.php?token=...&table=...` (the public `nelsontruck.com` redirects to `www.` and 404s; TigerTech's customer-subdomain hostname bypasses the redirect). Three tables grabbed into `app/data/mysql_dumps/`: **dci_codes** (132 rows — brand code mapping: dci_code/aaia_code/prod_code/cat_id/manu_title), **nte_parts_master** (331,201 rows / 65 MB — full Titan ERP parts master with P1-P5 tier prices, on-hand stock, status, location), and **contracts_copy** (717,260 rows / 25 MB — fresh refresh of the contract pricing rules). Also tried SSH key install via `ssh-copy-id`-style PowerShell pipe but Windows OpenSSH has a known bug with stdin pipes during password auth — pivoted to PHP endpoint approach which worked first try. **PHP file is intentionally a temporary tool — delete from server after Phase 1 imports stabilize.** |
| 2026-04-25 (Week 1 build, late evening) | **MASSIVE Week 1 milestone — pricing engine + catalog browse end-to-end.** Built and tested: (1) **Pricing formula parser** in `app/backend/app/services/pricing_formula.py` — handles all 4 production formula classes (P3, P3*.83, P5/.65, fixed). (2) **Pricing engine** in `app/backend/app/services/pricing_engine.py` — full resolution pipeline: contract scope match → priority ASC sort → formula application → tier-default fallback → aging-discount overlay (FS-080) → MAP enforcement clamp. **70 tests, all pass.** (3) **6 idempotent importers** in `app/scripts/import_initial_data.py` — `--all` runs in ~3 min and loads 4 warehouses, 131 brands, 2,879 customers, 221,768 products + prices (P1-P5), 3,486 inventory rows, 606,100 Titan contract rules. Re-runnable via UPSERT. (4) **End-to-end test** in `app/scripts/test_pricing_end_to_end.py` proves real customers + real products + real contracts resolve to real prices with MAP clamping and traceability. (5) **IMS315 FACS CSV writer** in `app/backend/app/services/ims315.py` — generates `ORDERS_TITAN_{TYPE}_{ORDER#}_{WAREHOUSE#}.CSV` with header + lines + FREIGHT/DISCOUNT/HANDLING synthetic rows. **17 tests, all pass.** (6) **FACS push pipeline** in `app/backend/app/services/facs_pusher.py` — FTP upload via aioftp, with local-mode fallback (writes to `app/data/facs_dropbox/`) when no FTP host configured. (7) **Typesense indexer** in `app/backend/app/services/search.py` — bulk-indexed all 221,768 products in 17 seconds with stock-aware ranking. (8) **Catalog API routes** in `app/backend/app/routers/catalog.py`: `/api/catalog/browse` (Typesense-powered, 4-8ms search response), `/api/catalog/products/{sku}` (DB-direct PDP), `/api/catalog/brands`. (9) **Frontend UI** in `app/frontend/src/App.tsx` — fully wired catalog browse with brand facets + in-stock filter + paginated grid + PDP page with two-line Suggested-Retail/Retail pricing + multi-warehouse stock display. **Total now: 87 passing tests, 221K live searchable products, 606K real contract rules, working /catalog at `localhost:5174`.** Hetzner side has the schema but doesn't yet have the new code — will sync via `git pull + alembic upgrade head + restart uvicorn + reindex` next session. |
| 2026-04-25 (Week 1 build, night) | **Cart + Auth went online.** Argon2 + JWT-cookie auth (`app/backend/app/services/auth_service.py`) with `POST /api/auth/signup|login|logout|link-customer` and `GET /api/auth/me`. Anonymous-cart cookie via `get_or_issue_session_token`. Cart endpoints in `app/backend/app/routers/cart.py`: GET, POST /lines, PATCH/DELETE /lines/{id}, DELETE /. Frontend `App.tsx` got AppProvider context, Header with cart badge, Home, Catalog, Product, Cart, Login, Signup pages. Working sign-up → log-in → add-to-cart → cart UI flow verified end-to-end. |
| 2026-04-26 (Week 1, visual polish — Option B) | **Mega-menu nav + PDP tabs + home-page widgets + recently viewed + trust + newsletter.** **Mega-menu nav** — replaced the flat `CategoryNavStrip` with a hover-reveal panel: each top category surfaces a 4-column grid of its immediate children plus the first 6 grandchildren each (with "+ N more" overflow link).  Pure CSS hover with React state for the open panel; closes on mouseleave or any link click.  Filters out zero-product / "Deprecated" tops automatically.  Added a "Brands A-Z" quick link on the right of the strip. **Subcategory drill-down** (committed earlier) — `CatalogBrowse` now resolves the current category node from category_top + (optional) category_path, renders a breadcrumb (Home / All products / Truck Equipment / Snow Plows) and "Shop by subcategory" tile grid above the product grid whenever the current node has children.  Filter chips distinguish "Category: X" vs "Subcategory: Y" and clearing the top also clears any active subcategory path. **PDP tabs** — new `ProductDetailTabs` component with Description / Specs / Stock by warehouse / Fitment tabs.  Specs pulls weight, length, width, height, freight class, brand prefix from the existing model.  Fitment tab shows the user's currently-set YMM (or a "Set your vehicle" prompt) and explains real-time fitment validation lands Phase 1.5 with the PACE/AAM feed import. **Hot Products widget** — new `GET /api/catalog/hot-products?limit=N` returns in-stock + has-image products from Typesense (over-fetches by 8x and filters since not every in-stock SKU has an image yet).  `HotProductsWidget` renders thumbnail + name + stock badge in a card.  Mounted in the home-page hero (right side, replacing the static 4-image collage) and as a sticky sidebar block on `CatalogBrowse`. **Recently Viewed** — pure `loadRecentlyViewed`/`pushRecentlyViewed` localStorage helpers, capped at 12 items.  `useRecentlyViewed` hook listens for `titan:recently-viewed-updated` custom event so all open tabs stay in sync.  PDP pushes the current product on view; new `RecentlyViewedStrip` shows up to 8 tiles on the home page (above value-props), at the bottom of every PDP, and inside the empty-cart state.  "Clear" button removes the localStorage key. **YMM fitment badge** — `YmmFitmentBadge` on PDP reads the user's YMM and shows a blue "Verify for your 2018 Ford F-150" pill, or a "Set your vehicle" link when nothing's set. **Newsletter signup** — new `NewsletterSignup` form in a dark gray strip above the footer (Phase 1: stores email in localStorage, Phase 1.5 will POST to /api/marketing/newsletter once the email provider lands).  Email validation + green confirmation state. **Trust strip** — new 4-column horizontal trust bar between hero and category tiles: Same-day shipping, Family-owned since 1971, Price match, Real humans. **Empty-state polish** — empty cart now shows a bordered dashed card with cart icon + 3 quick-link CTAs (Browse / Brands / In stock) plus the Recently Viewed strip; empty orders shows a bordered dashed card with package icon + browse CTA. **Verified end-to-end:** mega menu reveals the full Truck Equipment / Truck Accessories / Towing / etc. subcategory tree, PDP shows tabs, home shows live hot products from Typesense (8 in-stock items with images), recently viewed persists across reloads. **248/248 backend tests still green.** |
| 2026-04-26 (Week 1, deep PACE-style overnight build) | **Major UX expansion modeled on PACE / titantruck.com / elitetruck.com.** Surveyed all three reference sites (PACE via Chrome MCP + 22 demo screenshots, titantruck.com + elitetruck.com via WebFetch) to identify gap features. Implemented end-to-end: **YMM (Year/Make/Model) selector** — new `app/services/ymm_data.py` static seed (38 years × 22 makes × ~120 models covering trucks/vans/SUVs/chassis-cabs), new `routers/ymm.py` exposes `/api/ymm/years`, `/api/ymm/makes`, `/api/ymm/makes/{slug}/models`, `/api/ymm/resolve`. Frontend `YmmModal` lets users pick Y/M/M, persisted to `localStorage` and surfaced as a blue "Shopping for: 2018 Ford F-150" strip below the header (with change/clear). Phase 1.5 will wire actual fitment filtering once PACE/AAM fitment feed is imported. **Search autocomplete (PACE-style 3-col dropdown)** — new `/api/catalog/autocomplete` returns parts/categories/brands from a single Typesense query in <100ms. Frontend `HeaderSearchBar` debounces 180ms, shows part thumbnails + SKU + name + in-stock badge, plus category and brand pills. Keyboard nav (arrow keys, Esc) wired. **Brands A-Z directory** — `/api/catalog/brands/index` groups all 131 active brands by first letter. New `/brands` page renders sticky A-Z anchor strip + per-letter sections + featured badges. **Category landing pages** — `/api/catalog/categories/tree` returns the full nested category hierarchy with product counts; `/api/catalog/category/{slug}` returns one category + breadcrumb + immediate children. New `/categories/:slug` route renders subcategory tiles + a "Browse" CTA into the filtered catalog. **Warehouse stock table on PDP** — new `/api/catalog/products/{sku}/warehouse-stock` returns per-warehouse on-hand + lead-time + next-day cutoff, replaces the old simple list. **Quick Order modal** — header yellow CTA opens a 5-row paste form for SKU+qty bulk add (extends to N rows on demand), wires through `POST /api/cart/lines` per row with success/fail per-row indicators. **Lost Sale modal** — new `lost_sale` table + `POST /api/signals/lost-sale` records sales-team visibility into why a customer abandoned. PDP "Not what you're looking for?" link opens the modal. **Price Match modal** — new `price_match_request` table + `POST /api/signals/price-match` records competitor name/URL/price + customer notes. PDP "Request price match" link surfaces it. **Reorder endpoint** — `POST /api/orders/{web_order_number}/reorder` clones a past order's lines back into the current cart (skips discontinued/hidden products with reasons). Wired to "Reorder" button in `/orders` table. **Multi-column footer** — Shop / Account / Company / Contact columns matching elitetruck.com style. **YMM strip + Quick Order CTA** added to `Header`. Total endpoints: **32** (was 20). **Test count: 248** (was 212): 14 YMM router/service tests + 36 signals + reorder integration tests. Outstanding from this overnight scope: actual fitment data import (Phase 1.5), Returns/RMA modal (queued), Stock Notifications (queued), Engine Family selector (Phase 1.5), Kit Builder (Phase 2), Admin Control Panel (Phase 2). |
| 2026-04-26 (Week 1 build, late night, A+B hardening + image catalog + visual polish) | **Closed out 9 hardening items + WSM image/category import + PACE-style visual upgrade.** **Anonymous-cart merge:** new `cart_service.py` with a pure planner (`compute_merge_plan`) and async DB wrapper (`merge_anonymous_into_customer_cart`) — wired into signup, login, and link-customer; verified end-to-end (anon adds → log in → cart preserved + re-priced at tier). 13 pure planner tests + 5 DB integration tests. **MAP-clamp UX:** `TierPricingDisplay` gained `map_clamped` + `original_amount` fields, threaded through `build_tier_display`; frontend `PricingDisplay` now renders a collapsed "MAP-floor enforced" view with the pre-clamp price line-through instead of the confusing duplicate $200/$200. **Front Counter markup:** `Customer.retail_view_markup_percent` now fully wired — `POST /api/auth/front-counter-markup` to set, exposed in `UserOut.front_counter_markup_pct`, account page has a markup form for jobber/dealer tiers, `front_counter_quote()` pure helper computes `max(MAP, cost × (1 + markup/100))`. **Cart Front Counter re-pricing:** cart endpoint now returns `map_retail` per line; frontend recomputes line totals + subtotal at the marked-up price when toggle is on. **Backfill tests:** 25 tests for `pricing_service` (pure quote math + DB tier-aware resolution + MAP-clamp signal), 21 tests for `fulfillment_service` (proportional split, IMS315 builder, multi-warehouse plan against seeded test DB), 16 tests for `orders` router (checkout happy path, multi-warehouse split, BO routing, address handling, cart cleared, push-failure marks failed, list/detail permission gates), plus 4 new replay tests. **Test infrastructure:** new `conftest.py` with a session-scoped `titan_test` Postgres database (auto drop+create, NullPool to avoid event-loop reuse), `db` and `clean_db` per-test fixtures. **WSM image + category import:** new `app/scripts/import_wsm_details.py` walks the WSM CSVs, maps WSM STOCKID (e.g. `BGND:38302`) → our SKU via `brand.legacy_wsm_prefix` + product `prod_code` prefix matching (99.1% hit rate), upserts ProductImage rows from the semicolon-delimited IMAGE column, materializes the `>`-delimited CATEGORYTREE into the recursive Category tree (2,360 nodes), and backfills `extended_description` + meta + `legacy_wsm_stockid`. Result: **131,381 image rows across 48,406 products** + **50,895 category links + 2,360 categories**. **Typesense schema** gained `image_url`, `category_path`, `category_top` fields; reindexed all 221,768 products in ~50 seconds. Catalog browse + PDP API both return images + category. Catalog router added `category_top` + `category_path` query params. **Visual polish (PACE-style):** new dark utility bar (3 location phone numbers), redesigned main header with prominent search bar + cart badge with item count, new `CategoryNavStrip` component shows top categories from facets cache, redesigned home page with red/dark hero gradient + 4-image collage + category tiles + brand grid + 3-tier value props panel, new `ProductCard` shows product image + brand + sku + name + stock badge, new `FacetGroup` component for categories + brands sidebars, active-filter chip bar with clear-all, new `ImageGallery` for PDP with thumbnail strip. **Freight + tax services:** new `freight_service.py` (Phase 1 weight-tier table — 10/50/150/500 lb tiers + quote-required over 500), new `tax_service.py` (WA destination flat 8.9% combined rate, tax-exempt customer support, x1000 integer rate for IMS315), both wired into checkout — orders now ship with real freight + tax, FACS files include the tax block on the Spokane bucket. New `POST /api/orders/estimate` endpoint returns live freight + tax + grand total without placing the order. 18 freight/tax tests. **Order confirmation email:** new `email_service.py` with `compose_order_confirmation()` pure builder + 3 sender backends (console/maildev/postmark stub), checkout calls send_email() best-effort (never fails the order). 12 email tests. **FACS replay:** new `POST /api/orders/{web_order_number}/replay/{routing_type}` admin-only endpoint re-pushes the stored CSV via `push_csv()`, updates push_status + attempts + last_error, can re-promote order status from PLACED back to PUSHED_TO_FACS. 4 replay tests. **FACS pickup heartbeat:** new `facs_heartbeat.py` background task (5-min interval, owned engine), polls dropbox files, marks PUSHED → PICKED_UP when a file disappears, warns when files sit longer than `facs_pickup_lag_alert_minutes`. Wired into `main.py` lifespan with `DISABLE_BACKGROUND_TASKS=1` opt-out for tests. 11 heartbeat tests (4 pure planner + 4 DB integration + plus shared). **Final test count: 212 passing** (was 87 at end of cart+auth). Test runtime ~2 min (mostly DB integration). Authorize.Net wiring is the only remaining Phase 1 backend gap. |
| 2026-04-26 (Week 1 build, night, A+B complete) | **Tier-aware pricing + Front Counter Mode + Order Checkout/IMS315 push all live.** **(A) Tier-aware pricing:** New service `app/backend/app/services/pricing_service.py` exposes `TierPricingDisplay` plus `anonymous_retail_display()`, `resolve_for_customer()`, `build_tier_display()`. `catalog.py` PDP and `cart.py` (GET/POST/PATCH/DELETE — all 4 call sites updated) now use `_customer_for_user()` to resolve the viewer's tier and run the pricing engine per line for logged-in B2B customers. Response shape changed: `pricing` is now `{tier, primary_label, primary_amount, secondary_label, secondary_amount, savings_amount, contract_id, contract_name, notes}` plus a top-level `viewer_tier`. Frontend `PricingDisplay` component renders 4 tier-specific layouts: retail (line-through suggested + bold retail + savings), jobber/dealer (two-column "MAP Retail | Your Cost" with contract attribution + notes), municipality (single "Contract Price"). **Front Counter Mode** toggle in header (only shown to jobber/dealer tiers, persisted in `localStorage`) flips the PDP view to a retail-customer-facing presentation that hides their wholesale cost and promotes MAP Retail — designed for in-shop walk-up quoting. Cart shows a Front Counter banner when active. Signup form gained an optional `customer_number` field; new `/account` page lets already-signed-up users link a customer record after the fact via `POST /api/auth/link-customer`. **(B) Checkout + IMS315 push:** New service `app/backend/app/services/fulfillment_service.py` walks each cart line through warehouses in priority order (Spokane→Boise→Nelson Kent→Portland→back-order), allocating qty as available, and groups results into `FulfillmentBucket` per routing destination. `build_csvs_from_plan()` materializes one IMS315 CSV per bucket with proportional freight/discount/handling splits and Spokane-only tax assignment per existing PHP convention. New router `app/backend/app/routers/orders.py` exposes `POST /api/orders/checkout`, `GET /api/orders`, `GET /api/orders/{web_order_number}`. Checkout requires login + linked customer (anonymous on Phase 2 backlog). Orders persist with `Order` + `OrderLine` (per-warehouse split) + `OrderFulfillment` (one per CSV, with raw `csv_content` stored for audit/replay) and CSVs flush to FACS via local-mode dropbox (`app/data/facs_dropbox/`). Frontend gained `/checkout` (full ship/bill/contact/payment form), `/orders` (history table), `/orders/{web_order_number}` (detail with routing tiles + per-line breakdown). Web order numbers `TTW{0000001…}`. **End-to-end smoke verified:** TTW0000001 (single OOS line → routed to BO bucket → 1 CSV) and TTW0000002 (qty 25 of multi-warehouse SKU split 23 SPO + 2 NELSON → 2 CSVs, both ship-via labels correct: `04/25 PPD` + `PAL`). Authorize.Net wiring still pending sandbox creds (option in checkout form is disabled until then). |
