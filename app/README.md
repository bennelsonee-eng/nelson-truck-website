# Titan Truck Equipment — New Website

Replacing `titantruck.com` (the 2017 WSM build) with a modern multi-tier ecommerce platform. **Single big-bang launch in 4 weeks.**

See `../SOW_v0.1.md` and `../SOW_v0.1_addendum_*.md` for full scope, strategy, and reverse-engineered logic from the existing system.

---

## Stack

- **Backend**: FastAPI + SQLAlchemy async + PostgreSQL + Alembic
- **Frontend**: React 19 + TypeScript + Vite 7 + AG Grid + Tailwind CSS v4 + React Router 7
- **Search**: Self-hosted Typesense (Algolia-clone, free, fast, extensible)
- **Cache / Queue**: Postgres for now (Redis only if needed in Phase 2)
- **Payments**: Authorize.net (cards + ACH via eCheck.Net)
- **Email**: TBD — Postmark / SendGrid / Mailchimp
- **Hosting**: Hetzner US-West (Hillsboro, OR) Linux cloud server
- **Edge**: Cloudflare (DNS, SSL, CDN, WAF)
- **Management**: Tailscale (private SSH; no public port 22)

Mirrors the Nelson ERP stack so codebase patterns transfer cleanly. New ERP for Titan = same Nelson ERP codebase, separately deployed; both will eventually run on the same Hetzner server with localhost integration in Phase 2.

---

## Local development

### Prerequisites
- Python 3.11+
- Node 20+
- Docker Desktop (for local Postgres + Typesense)

### One-time setup
```bash
cd app
cp .env.example .env
# Edit .env with local secrets (DATABASE_URL stays as-is for Docker default)

# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### Port assignments (chosen to avoid Nelson ERP collisions)

| Service | Titan port | Nelson ERP equivalent |
|---|---|---|
| Backend (FastAPI) | **8001** | 8000 |
| Frontend (Vite dev) | **5174** | 5173 |
| Frontend (Vite preview) | **4174** | 4173 |
| Postgres (Docker host) | **5433** | 5432 (native) |
| Typesense | 8108 | (n/a) |
| maildev web | 1080 | (n/a) |
| maildev SMTP | 1025 | (n/a) |

Both projects can run simultaneously without conflict.

### Run locally
Three terminals (or use VS Code's split terminal):

```bash
# Terminal 1 — local Postgres + Typesense via Docker
cd app
docker compose up

# Terminal 2 — backend (FastAPI on port 8001)
cd app/backend
.venv\Scripts\activate
alembic upgrade head           # apply DB migrations
uvicorn app.main:app --reload --port 8001

# Terminal 3 — frontend (Vite dev server on port 5174)
cd app/frontend
npm run dev                    # serves at http://localhost:5174
```

Open `http://localhost:5174` in your browser.

---

## Project structure

```
app/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Pydantic settings
│   │   ├── database.py          # Async SQLAlchemy
│   │   ├── dependencies.py      # FastAPI deps (auth, db session)
│   │   ├── models/              # SQLAlchemy models
│   │   ├── routers/             # FastAPI route modules
│   │   ├── services/            # Business logic (pricing engine, search, fulfillment, etc.)
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── utils/               # Helpers (CSV writer, etc.)
│   ├── migrations/              # Alembic migrations
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── routes/              # React Router route components
│   │   ├── components/
│   │   ├── lib/                 # API client, hooks, utilities
│   │   └── styles/
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
├── scripts/                     # One-off scripts (PACE import, WSM migration, FACS pusher tests)
├── docker-compose.yml
├── .env.example
└── README.md (this file)
```

---

## Key Phase 1 services

| Service | Module | Description |
|---|---|---|
| **Pricing engine** | `services/pricing_engine.py` | Resolves contract pricing per customer/product/qty with priority + formula support (per-SKU, brand, group, broad-scope) |
| **Search indexer** | `services/search.py` | Pushes catalog to Typesense; stock-aware ranking |
| **Fulfillment routing** | `services/fulfillment.py` | Multi-warehouse split (Spokane → Portland → Boise → Nelson Kent → BO) |
| **IMS315 CSV writer** | `services/ims315.py` | Generates FACS-compliant order CSVs per warehouse |
| **FACS pusher** | `services/facs_pusher.py` | FTP file-drop + heartbeat monitor + reconciliation |
| **PACE import** | `services/pace_import.py` | Catalog migration from PACE/AAM |
| **WSM migration** | `services/wsm_migration.py` | Customer + order history migration from old WSM database |

---

## Warehouse routing (Phase 1)

| Code | Warehouse / Routing | Filename pattern | Inventory source |
|---|---|---|---|
| `10` | Spokane HQ | `ORDERS_TITAN_SPO_{id}_10.CSV` | `parts_onhands.spokane` |
| `19` | Boise | `ORDERS_TITAN_BOISE_{id}_19.CSV` | `parts_onhands.boise` |
| `10` | Nelson Truck Equipment (cross-company — Kent + Portland combined) | `ORDERS_TITAN_NELSON_{id}_10.CSV` | `parts_onhands.kent + parts_onhands.portland` |
| `10` | Back-order fallback | `ORDERS_TITAN_BO_{id}_10.CSV` | (none — needs to be sourced) |

**4 file types max per order.** Portland inventory (warehouse 1) is routed under the NELSON file type — Titan decides per-order how to physically move goods from Portland (direct ship, transfer to Spokane, etc.). A single web order can produce up to 4 CSVs (one per warehouse with stock); freight/discount/handling proportionally split. Full algorithm in `../SOW_v0.1_addendum_003.md`.

---

## Customer tiers

| Tier | Login | PDP price display | Cart |
|---|---|---|---|
| **Retail** | No (anonymous) | Suggested Retail / Retail (two-line, discount visible) | Standard cart + CC checkout |
| **Jobber** | Yes | MAP Retail \| Your Cost two-column + Retail View toggle | Cart + CC or PO |
| **Dealer** | Yes | Same as jobber + Phase 1 financing calculator | Cart + CC or PO |
| **Municipality** | Yes | Single computed contract price | Cart + PO (preferred) or CC; optional quote workflow |

---

## Deployment (Phase 1)

Production deployment goes to **Hetzner US-West (Hillsboro, OR) CPX21** (Ubuntu 22.04 LTS), Cloudflare-fronted, Tailscale-managed. Co-located with the Titan ERP (Nelson ERP codebase) once that comes online.

Deployment scripts under `scripts/deploy/` (TBD).

---

## See also

- `../SOW_v0.1.md` — Full statement of work
- `../SOW_v0.1_addendum_001.md` — PACE timing + FTP architecture
- `../SOW_v0.1_addendum_002.md` — IMS315 real-data pattern matching
- `../SOW_v0.1_addendum_003.md` — Full PHP reverse-engineering of fulfillment routing
- `../discovery/notes/` — Interview script + walk findings
