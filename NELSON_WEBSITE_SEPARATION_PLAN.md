# Nelson Truck Website — Separation Plan (clone of Titan Truck Equipment site)

**Goal:** Stand up a Nelson Truck website by cloning the Titan Truck Equipment site
(`C:/Users/Ben/titan truck website`) into `C:/Users/Ben/nelson truck website`, then
change only the things that make it a *separate company*. Nelson takes over
**nelsontruck.com** at launch; **nelsontruckequipment.com** is the optional
pre-launch preview host (mirrors the Titan `titantruckequipment.com` → `titantruck.com`
strategy).

Status: **SCAFFOLDED.** Code cloned + core company-split applied 2026-07-14.
Decisions locked: **co-host on titan-prod**, **restructured layout**, **scaffold now**.

---

## SCAFFOLD STATUS (2026-07-14)

### ✅ Done
- **Folder cloned** `titan truck website` → `nelson truck website` (code only; excluded
  `.git`, `.venv`, `node_modules`, `dist`, `backend/static` images 681M, and the
  `data/` staging dirs ~1.5G. Kept code + `data/contracts/`). ~41 MB.
- **`app/.env`** rewritten for Nelson: `nelson_web` DB, `nelson_search_dev_key`,
  `sales@nelsontruck.com`, `/nelson_orders`.
- **`config.py`** defaults → `app_name="Nelson Truck Equipment"`, `database_url=nelson_web`,
  typesense key, `facs_dropbox_path=/nelson_orders`, `email_from`, `canonical_base_url=https://nelsontruck.com`,
  `cf_access_team_domain=nelson-preview-team...`.
- **Company data split (the key change):**
  - `scripts/import_initial_data.py` — contracts filter and customer-extraction filter
    both switched `"titan"` → `"nelson"` (loads the 113,408 Nelson contract rows + Nelson customers).
  - `services/customer_sync.py` — `SOURCE_TABLE = "nte_cus190"` (was `tte_cus190`).
- **Local dev ports** (run alongside Titan + ERP): frontend **5175**, preview **4175**,
  backend **8002** (`vite.config.ts`, `.claude/launch.json`, `restart_nelson.bat`).
  Local DB override: `postgres:nelson2026@localhost:5432/nelson_web`.
- **`restart_titan.bat`** → **`restart_nelson.bat`** (Nelson ports + DB).
- **`index.html`** no-JS/crawler fallback → Nelson name, `sales@nelsontruck.com`,
  Portland OR & Kent WA.
- All edited Python files pass `py_compile`.

### ✅ Resolved
- **Retail sentinel customer number = "9"** (Ben, 2026-07-14; verified: 86 `company='nelson'`
  contract rows under sentinel contract `9999999` with brand-level markup formulas). Wired
  into `pricing_service.py` (`RETAIL_SENTINEL_CUSTOMER_NUMBER`) and `import_initial_data.py`.
  Note: cust "9" is also present in the nelson contract set, so it loads as a normal customer
  and its contracts drive the retail book (tier label doesn't affect resolution).
- **Preview domain `nelsontruckequipment.com` PURCHASED** (Ben, 2026-07-14). Mirrors Titan:
  build/preview host (put behind Cloudflare Access), canonical stays `nelsontruck.com` for
  launch. `config.py` already emits nelsontruck.com canonically and names the preview host.
- **Customer table confirmed:** `nte_cus190` is correct for Nelson (Ben) — matches the
  `customer_sync.py` change.
- **Accounts (Ben, 2026-07-14):** Authorize.net = **separate** Nelson account (own keys).
  Email-SMTP = **nelsontruck.com just like Titan** (mail.tigertech.net, `@nelsontruck.com`
  mailbox). Cloudflare = **own zone, same setup as Titan**. All are "fill in Nelson's own
  creds in `.env` at deploy" — no code change needed.
- **Logo assets copied** into `app/frontend/public/brand/`: `nelson-logo.svg` (true vector,
  red primary), `nelson-logo.png` (raster), `nelson-logo-white.svg` (navy/white badge for a
  dark header). Titan's `titan-logo.png` removed. Brand identity: red vintage pickup in a hex
  badge, "NELSON TRUCK EQUIPMENT CO., INC. — EST. 1937". **Brand red = `#B01F27`.**
  (`titan-footer.png` still in the folder — replace with the white variant during restructure.)

### ⏳ Not started (need decisions/assets)
- **Server provisioning** on titan-prod: `nelson_web` DB, Nelson Typesense collection,
  `nelson-*` systemd units, nginx site, ports, Tailscale/Cloudflare edge → nelsontruck.com.
- **Data load + Typesense reindex** (runs server-side from `data/mysql_dumps/` + the bridge;
  those dumps were NOT copied locally by design).
- **Visual restructure** (chosen): new logo, new palette (`styles/index.css` via the
  `@tailwindcss/vite` plugin — Titan is navy `#1e3a8a`/`#0b1f3a` + red `#b91c1c`), and a
  restructured header/homepage layout (mine `HomepageMockups.tsx` / `MarketplaceVariants.tsx`).
  **Needs the Nelson logo asset + design direction.**
- **`npm install`** in `app/frontend` (node_modules not copied) before the site can run.

### 📝 Newly-found follow-ups (documented, not yet changed)
- **Featured / top-sellers** = a STATIC hardcoded list of Titan's top-sellers baked from
  `tte_rcv390` (`services/snow_top_sellers.py`, and featured logic in `routers/catalog.py`).
  Nelson should have its own (from `nte_rcv390`) — content curation, not fabricated here.
- **`tte_ourparts_num`** column name in `models/catalog.py` — cosmetic (the value is the
  shared parts-master SKU). Rename needs a migration; low priority.
- **`titan_*` config field names** kept as-is (they just mean "the source bridge"); values
  are Nelson's. Optional future rename to `source_*`.
- **`sync_customers_from_tte_cus190()`** function name kept (no callers); reads `nte_cus190`.

---

---

## 0. The one-line summary of how the two companies actually differ

The Titan and Nelson storefronts are **near-identical** because they draw from the
**same legacy source data** (the MySQL bridge on nelsontruck.com's TigerTech host,
and the shared `nte_parts_master` base price list). The *only* real data difference
is **which customers and which contract-pricing rows each site loads**:

| Concern | Titan | Nelson | Shared? |
|---|---|---|---|
| Base price list (P1–P5) | `nte_parts_master` | `nte_parts_master` | ✅ SHARED (already Nelson's table) |
| Product catalog / categories | PACE/AWDA/Meyer/Western feeds | same | ✅ SHARED |
| Inventory on-hand / days | `tte_inv_days` | `nte_inv_days` | Both already pulled by one sync |
| **Customers** | `tte_cus190` | `nte_cus190` | ❌ company-specific |
| **Contract pricing** | `contracts_copy.csv` rows where `company='titan'` (605,710) | rows where `company='nelson'` (113,408) | Same file, filtered by `company` column |
| Order write-back | `tte_rcv390` / `/titan_orders` | `nte_rcv390` / `/nelson_orders` | ❌ company-specific |
| Branding, domain, contact | Titan | Nelson | ❌ company-specific |

**The backend change Ben named** ("retrieve contract pricing choosing nelson not titan")
lives at exactly one line:
`app/scripts/import_initial_data.py:622-624` →
```python
company = (r.get("company") or "").strip().lower()
if company != "titan":     # ← change to "nelson"
    continue
```
Confirmed: `contracts_copy.csv` is semicolon-delimited and contains **both** companies,
tagged by a `company` column (titan=605,710 rows, nelson=113,408 rows).

---

## 1. Deployment / infrastructure (separate instance)

Titan prod runs as its own box: `ssh titan@100.106.251.97`, app at
`/home/titan/titan-truck-website`. Services observed:

| Service | Titan | Nelson needs |
|---|---|---|
| Backend (uvicorn) | `titan-backend.service` :8001 | own unit + port |
| Frontend (vite) | `titan-frontend.service` | own unit + port |
| Prerender (bot SSR) | `titan-prerender.service` :3001 | own unit + port |
| Inventory sync | `titan-inventory-sync.service` (pulls `tte/nte_inv_days`) | own unit (pull `nte_inv_days`) |
| Reindex | `titan-reindex.service` | own unit |
| Daily backup | `backup-titan.service` | own unit |
| Postgres | Docker, `titan_web` on **:5433**, pw `titan2026` | `nelson_web` on new port/db |
| Typesense | Docker :8108, key `titan_search_dev_key` | own instance/collection + key |
| nginx site | `/etc/nginx/sites-enabled/titan` (listen :8080, bot-prerender map) | own site + port |
| Public edge | Tailscale serve :443/:8443 (+ Cloudflare tunnel planned) | own serve/tunnel → nelsontruck.com |

**Open decision (see §8): dedicated new server for Nelson, or co-host on the titan-prod
box with namespaced services + ports + separate DB.** Everything below assumes a clean
namespace either way (`nelson-*` units, `nelson_web` DB, distinct ports).

---

## 2. Backend config — `app/backend/app/config.py`

Every line below is a per-company change:

| Setting | Titan value | Nelson value |
|---|---|---|
| `app_name` | `"Titan Truck Equipment"` | `"Nelson Truck ..."` (confirm exact name) |
| `database_url` | `...titan2026@localhost:5433/titan_web` | `nelson_web` (own db/port/pw) |
| `typesense_api_key` | `titan_search_dev_key` | new key |
| Typesense collection name | (titan products) | nelson collection |
| `titan_bridge_url` | `https://nelsontruck.com.customers.tigertech.net/dump_titan_tables.php` | **SAME host** — but pull `nte_*` tables; likely a `dump_nelson_tables.php` sibling or a `?table=nte_cus190` param |
| `titan_bridge_token` | `ttn-...` | own token |
| `facs_dropbox_path` | `/titan_orders` | `/nelson_orders` |
| `email_from` | `sales@titantruck.com` | `sales@nelsontruck.com` (needs mailbox) |
| SMTP (winterwatch@titantruck.com) | TigerTech | Nelson mailbox equivalent |
| `cf_access_team_domain` | `titan-preview-team.cloudflareaccess.com` | nelson preview team (if using preview gate) |
| `cf_admin_emails` | — | Nelson admin emails |
| `public_url` | localhost:5173 | own dev port |
| `canonical_base_url` | `https://titantruck.com` | `https://nelsontruck.com` |
| Authorize.net / PACE / Anthropic keys | Titan accounts | Nelson accounts (or shared PACE — confirm) |

> Note: the config *class names* still say `titan_*` (e.g. `titan_bridge_url`,
> `titan_mysql_*`). In the clone these are just field names — rename to `source_*`
> or leave as-is; low priority, but rename improves clarity.

---

## 3. Company data split (the substantive backend work)

1. **Contracts** — `import_initial_data.py:622` filter `company == "nelson"`.
   Loads 113,408 Nelson contract rows into the `Contract` table. (§0)
2. **Customers** — `app/backend/app/services/customer_sync.py`, `SOURCE_TABLE = "tte_cus190"`
   → `nte_cus190`. Pulls Nelson's ~customer set via the same bridge. Also the
   `import_initial_data.py` customer-extraction step (distinct `cust_id`s from
   `contracts_copy` — the company filter there handles this automatically once §0 is done).
3. **Retail price sentinel** — `pricing_service.py:36`
   `RETAIL_SENTINEL_CUSTOMER_NUMBER = "106415"` is the **"TITAN WEBSITE SALES"** sentinel
   customer whose contracts ARE the public retail price book. **Nelson needs its own
   sentinel customer number** whose `company='nelson'` contracts define Nelson's retail
   markups. ⚠️ **Must be supplied** — without it, retail resolution falls back to raw
   `ProductPrice.retail_price`. (Open item §8.)
4. **Inventory days** — the sync already pulls both `tte_inv_days` and `nte_inv_days`;
   the Nelson site consumes `nte_inv_days` (drives the FS-080 aging discount in the
   pricing engine). Point Nelson's sync/consumer at `nte_inv_days`.
5. **Order write-back** — Titan writes web orders to `tte_rcv390`; Nelson → `nte_rcv390`.
   Nelson's warehouse(s), freight regions, and tax treatment differ from Titan's
   single Kent tax-exempt warehouse — confirm Nelson's fulfillment config (open item §8).
6. **Parts master / catalog / images** — **no change.** `nte_parts_master`, the
   408-node category tree, PACE/AWDA feeds, and localized product images are shared.
   (For a fully independent DB, Nelson gets its own *copy* of the product/category/image
   tables, loaded from the same feeds.)

---

## 4. Branding & visual identity (make it look like a different company)

| Item | Location | Change |
|---|---|---|
| Logo | `app/frontend/public/brand/titan-logo.png` | replace with `nelson-logo.png` (needs asset) |
| Favicon | frontend `index.html` / public | Nelson favicon |
| App/site name, hero copy | `App.tsx`, `pages/ContentPages.tsx`, `pages/HomepageMockups.tsx`, `pages/MarketplaceVariants.tsx` | Nelson name/taglines |
| `<title>` / meta / OG | `components/Seo.tsx` (per-route) + `index.html` noscript block | Nelson |
| Contact info | `index.html` noscript (`sales@titantruck.com`, `#b91c1c`), ContentPages | Nelson email / phone / address |
| Theme colors | `styles/index.css` — Titan leans navy (`#1e3a8a`, `#0b1f3a`) w/ red accent (`#b91c1c`) | **new Nelson palette** to visually distinguish |
| Layout / homepage structure | `App.tsx` (header/footer/nav inline), `HomepageMockups.tsx`, `MarketplaceVariants.tsx` | restructure so the two don't look co-owned |
| localStorage keys | `App.tsx` uses `titan_front_counter`, `titan_showroom`, `titan_ymm`, `titan_compare` | rename to `nelson_*` (avoids cross-site collision if ever same origin) |
| ErrorReporter labels | `components/ErrorReporter.tsx` | Nelson |

There are **no separate Header/Footer/Nav component files** — layout is inline in
`App.tsx`, and there's **no tailwind.config** (colors live in `styles/index.css` and
inline styles). So visual differentiation = edit `styles/index.css` palette + the inline
layout in `App.tsx` + swap the logo. The homepage/marketplace *variant* pages
(`HomepageMockups.tsx`, `MarketplaceVariants.tsx`) are existing alternate layouts we can
mine to give Nelson a genuinely different look with low effort.

---

## 5. SEO / domain

- `canonical_base_url` → `https://nelsontruck.com`; sitemap, robots.txt, `llms.txt`,
  OG URLs all rebuild from that one value (single source of truth — good).
- OG/share images: swap Titan imagery for Nelson.
- nginx bot-prerender `map` var `$titan_is_bot` → rename `$nelson_is_bot` (cosmetic).
- Domain takeover: nelsontruck.com currently points at the legacy TigerTech site
  (the MySQL bridge lives there). Cutover plan needed so the bridge host stays reachable
  while the public site moves. ⚠️ **The bridge URL literally lives on
  `nelsontruck.com.customers.tigertech.net`** — confirm the DNS/hosting cutover does not
  break the data bridge both sites depend on.
- Optional preview host nelsontruckequipment.com behind Cloudflare Access (mirror Titan).

---

## 6. Explicitly SHARED — do NOT duplicate the source

- MySQL source bridge & host (nelsontruck.com TigerTech) — one source, both sites read it.
- `nte_parts_master` base price list.
- Product category taxonomy (408-node tree).
- PACE / AWDA / Meyer / Western product & fitment feeds.
- The `contracts_copy.csv` export (one file, filtered per company).

Each website keeps its **own Postgres DB + Typesense** (independent copies loaded from
the shared sources) so the two deployments are isolated.

---

## 7. Suggested build order (once decisions in §8 are made)

1. Clone the folder (git-level copy of `titan truck website` → `nelson truck website`),
   drop Titan-only local artifacts (.venv, node_modules, dist, backups, big PDFs).
2. Provision Nelson services on the chosen host (DB `nelson_web`, Typesense, ports, units).
3. Config pass (§2) + company data split (§3) — get data loading for `company='nelson'`.
4. Load data: customers (`nte_cus190`), contracts (nelson filter), products from feeds,
   Typesense reindex.
5. Verify pricing: pick a known Nelson jobber customer, confirm contract pricing resolves
   to Nelson terms (not Titan). Confirm retail sentinel drives public prices.
6. Branding/visual pass (§4) — logo, palette, layout differentiation.
7. SEO/domain (§5), preview host, then launch cutover to nelsontruck.com.

---

## 8. Open decisions / items needed from Ben

1. **Hosting:** dedicated new server for Nelson, or co-host on the titan-prod box?
2. **Exact Nelson site name** ("Nelson Truck", "Nelson Truck Equipment", ...) + tagline.
3. **Nelson logo asset** (file) — do you have one, or should we generate/adapt?
4. **Nelson retail-sentinel customer number** (the equivalent of Titan's `106415`
   "TITAN WEBSITE SALES") whose `company='nelson'` contracts define website retail markups.
5. **Nelson fulfillment config:** warehouse(s), freight regions, tax treatment, and the
   order write-back table (`nte_rcv390`?) — Titan is single Kent tax-exempt; Nelson likely
   Portland + Kent.
6. **Visual direction:** same layout w/ new palette+logo, or a restructured layout so the
   two clearly don't look co-owned?
7. **Shared vs separate accounts:** PACE catalog API, Authorize.net, email/SMTP,
   Cloudflare — reuse Titan's or set up Nelson's own?
8. **Bridge for `nte_` tables:** does the TigerTech bridge already expose `nte_cus190`
   etc., or does it need a `dump_nelson_tables.php` (or a table param)?
