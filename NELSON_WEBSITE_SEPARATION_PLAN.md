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

## 🌙 OVERNIGHT BUILD (2026-07-15) — homepage + branding + SEO LIVE

Built the v20 design into the live React app on the box (deployed + verified via headless-Chrome
screenshots and curl). Screenshot loop: `titan-truck-website/app/prerender/shot.mjs <url> <out>`.

**Done & verified:**
- **Branding foundation:** Barlow + Barlow Condensed fonts (`index.html` gfonts, `.font-cond`
  utility), Nelson red `#B01F27` mapped onto Tailwind `red-700/800` via `@theme` (index.css),
  horizontal logo lockup (badge + wordmark) in the header, util bar = "✓ In stock now — pick it up
  today · Portland 503.548.9300 · Kent 253.395.3825".
- **Homepage = new `NelsonHome` component** (App.tsx; old `Home` kept as dead ref, route `/` → NelsonHome):
  rotating red hero banner (5 division slides: snow/tow/aerial/trailers/tonneau, fade, dots),
  3 value pillars (pickup / **we install everything we sell** / expert), custom-fab band, steel band
  (advertise-only), "In stock & ready today" product grid wired to real `/api/catalog/browse`, stats,
  brand marquee. Matches the mockup.
- **Division mega-nav** (`MEGA_SECTIONS` rewritten): Snow & Ice · Truck Bodies · Tow Trucks ·
  Aerial & Bucket · Trailers · Liftgates & Cranes · Accessories · Metal & Hardware. Real category
  paths where data exists; `route:/catalog` placeholders for Tow Trucks/Trailers/Metal (no catalog
  data yet).
- **Footer** rebranded (Nelson badge + white wordmark, 1937, Portland/Kent phones, © Nelson).
- **Sitewide text sweep:** ~99 Titan strings → Nelson (name, domain, 1971→1937, Spokane/Boise→
  Portland/Kent, phones) across App.tsx, ContentPages.tsx, Seo.tsx.
- **SEO/AEO (verified):** `nelson-prerender.service` (:3002, reuses Titan prerender code) + nginx
  `$nelson_is_bot` map + `@handle` bot→prerender routing (Google/Bing/GPTBot/ClaudeBot/Perplexity get
  rendered HTML). `robots.txt`/`sitemap.xml`/`llms.txt` emit nelsontruck.com; `llms.txt` rebranded with
  divisions + differentiators. **LocalBusiness (AutoPartsStore) JSON-LD × 2 branches** (Portland
  503-548-9300 / Kent 253-395-3825, est 1937) + Organization/WebSite schema on home.

## ✅ CATALOG + IMAGES REBUILT (2026-07-15, Session ~330) — LIVE

**DONE.** Nelson's catalog is now **identical to Titan's** (part numbers, images, admin) with Nelson's
own pricing/customers layered on top — exactly per Ben's directive ("part numbers and images identical
Titan→Nelson; admin the same; only Nelson's customers differ; we share `ourparts_num`; use AAIA codes
from `dci_codes` like Titan").

**Key finding that reframed the fix:** Titan's real catalog came from a **PACE/AAM ingest**
(`pace_part`→`product`, AAIA SKUs via `dci_codes.aaia_code`, 200K images, fitment). Nelson only ever got
the *pricing/inventory overlay* half (`import_initial_data.py`, 222K internal-SKU rows keyed by
`ourparts_num`, **zero images**). Nelson was missing the entire PACE-built catalog. The Nelson ERP
itself is **Kerridge**-sourced, not PACE — so there was no "Nelson PACE" to run; the source IS Titan's
already-built PACE catalog.

**Approach (chosen: stage-then-cutover; replicate, not re-ingest):**
1. Cloned `nelson_web` → `nelson_web_staging` (preserves Nelson customers/contracts/branding/config).
2. Swapped the **catalog cluster** (40 tables: `product`, `product_image`, `product_category`,
   `category`, `product_attribute`, `product_description`, `pace_part`/`pace_fitment`, `vcdb_*`/`pcdb_*`,
   `product_package`, `kit*`, `brand`, …) from `titan_web` via `pg_dump --data-only | pg_restore
   --disable-triggers`. Patched 3 drifted tables (Titan-only cols: `product_image.source_url/thumb_url`,
   `brand.prod_code`, `pcdb_part_type.category_locked/…`).
3. Copied Titan's **base `product_price`** (PIES tiers, keyed to the shared product ids), then ran
   `recompute_resolved_retail` against staging → **sentinel-9** Nelson retail (customer "9", 86 contracts).
4. Reindexed a staging Typesense collection, exercised the real browse+PDP API, then **cut over**:
   renamed `nelson_web`→`nelson_web_old_20260715` (rollback, retained), `nelson_web_staging`→`nelson_web`,
   reindexed live `nelson_products` (326,243 docs), restarted `nelson-backend`.

**Static-serving fix (was blocking all images):** Nelson's `static/product-images` etc. are **symlinks**
into Titan's shared 8.9GB library (already staged during scaffold), which resolve OUTSIDE `STATIC_DIR`.
Starlette `StaticFiles` 404s symlinks that escape the mount → added `follow_symlink=True` to the
`CachedStaticFiles` mount in `app/backend/app/main.py` (Titan doesn't need it — real dirs). Synced to box.

**Live numbers:** 326,243 products (identical AAIA SKUs: `WEST-78386`, `BUY-1704300`, `BCSQ-90840`) ·
200,555 image rows (files serve HTTP 200 via nginx; ~13% "NO IMAGE" mirrors Titan's own gaps) ·
185,839 priced via sentinel-9 (7,820 with Nelson-specific markups; PDP `BCSQ-90840` → **Retail $23.37**) ·
156,799 sellable (img+price) · 460 categories · Nelson's 1,114 customers + 111,159 contracts preserved.
Verified via headless screenshot of live `/catalog?q=plow` (real plow images render, Nelson branding).

**✅ Inventory / pickup stock WIRED (2026-07-15, same session):** `product_inventory` now populated —
**5,298 products in stock** (Spokane 14,493 units / 3,741 rows, Kent 6,537 / 1,861, Portland 1,866 / 563;
22,896 units total, 6,165 rows). Catalog cards show green "N in stock" (5,280 in-stock docs; browse
`in_stock=true`→5,280), PDP warehouse-stock returns per-branch pickup. **Inventory = identical to Titan**
(both `tte_inv_days`+`nte_inv_days`, warehouses `{10,1,2}` = Spokane+Portland+Kent) — Ben: onhands are
the same as Titan's site; only customers differ.
  - **How:** created `scripts/link_nelson_inventory.py` (copy of Titan's `link_titan_inventory_v2.py`,
    pointed at `nelson_web`; `TARGET_WAREHOUSES = {10, 1, 2}` same as Titan). It reconstructs each
    product's AAIA SKU from `*_inv_days.ourparts_num`→`*_parts_master.parts_num` + `brand.aaia_code` and
    matches `product.sku` — works without needing `tte_ourparts_num`. Run `--seed-warehouses --no-prices`
    (seeded the missing Kent warehouse code 2; never touches pricing). Reindexes changed products +
    recomputes kit stock (83 kits in stock).
  - **Match rate:** TTE 9,336 rows→6,275 matched + NTE 8,450→3,703 matched = 5,868 product-warehouse
    pairs / 5,198 products. Unmatched = stock items not in the PACE catalog / brand table — same
    "in-stock-but-not-on-website" gap Titan has; report at
    `app/data/reports/tte_inventory_missing_from_website.csv` (~3K rows).
  - **Recurring:** `nelson-inventory-sync.service`+`.timer` on the box (15-min, `OnBootSec=6min`, ordered
    `After=titan-inventory-sync.service`). Nelson has NO bridge creds — Titan's 15-min timer already keeps
    the shared symlinked `nte_inv_days.csv` fresh; Nelson's timer just loads it. `EnvironmentFile=app/.env`.
    Log: `/home/titan/nelson-inventory-sync.log`.
- **Rollback DB `nelson_web_old_20260715`** (165 MB) retained — drop once satisfied (a few days).
- **SEO anti-dup:** catalog is now byte-identical to Titan; relying on distinct domain + self-canonical +
  distinct Organization/LocalBusiness JSON-LD (all done). Content differentiation (rewritten
  descriptions via Ollama) is a later optional pass if search engines flag duplication.

**⏳ Earlier known follow-ups (still open):**
- **Git:** committed on box (`2b2c98a`, 458 files, clean). Remote =
  `git@github.com:bennelsonee-eng/nelson-truck-website.git`. Push blocked — **GitHub repo not yet
  created** (gh absent); create empty repo → `git push -u origin main`.
- **Tow Trucks / Trailers / Metal & Hardware** divisions link to `/catalog` — need real landing pages
  + product data.
- Logo wordmark slightly blurry (raster) → extract vector from `nelson_logo.svg`.
- Default OG share image; areaServed done; minor white gap under homepage marquee.
- Local `nelson truck website/` and the box are in sync for edited files (no git repo yet).

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

### ✅ PROVISIONED on titan-prod (2026-07-14/15) — LIVE, tailnet-only
Preview URL: **`https://titan-prod.tail0c2fbc.ts.net:8444/`** (tailnet only for now).
- Code at `/home/titan/nelson-truck-website` (shipped via tarball; `data/mysql_dumps`
  symlinked to Titan's shared dumps).
- **DB** `nelson_web` in the shared `titan_postgres` container (:5433). 68 tables (alembic head).
- **Data loaded:** 222,174 products+prices, 1,114 Nelson customers, **111,159 Nelson contracts**
  (606,100 Titan rows skipped). Retail sentinel customer **"9"** present w/ 86 contracts.
- **Typesense:** separate `nelson_products` collection (222,174 docs) in the shared instance —
  Titan's `products` (326,243 docs) untouched. Collection name made config-driven in `search.py`.
- **Backend:** `nelson-backend.service` (uvicorn :8002, enabled). `/api/health` → nelson_web OK.
  Pricing resolves via sentinel 9 (verified: retail $ amounts on real SKUs). Search works
  (`/api/catalog/browse?q=plow` → 275 hits).
- **Frontend:** built dist served by **nginx site `nelson`** on :8081 (proxy /api→8002).
  Nelson logo served. Titan (:8080) verified unaffected.
- Prod `.env` at `app/.env` (chmod 600, real JWT secret; TYPESENSE_API_KEY=titan_search_dev_key
  shared instance, TYPESENSE_COLLECTION=nelson_products).

### ✅ PUBLIC preview LIVE (2026-07-15): https://nelsontruckequipment.com
- Separate Cloudflare Tunnel **`nelson-preview`** (tunnel id `51178083-…`), run as its own
  `cloudflared-nelson.service` on the box (token in `/etc/cloudflared-nelson.env`, 600) —
  independent of Titan's `cloudflared.service`. Published routes: apex + `www` → `localhost:8081`.
  Verified: HTTPS 200, homepage = Nelson, `/api/health` → nelson_web through the tunnel.
- ✅ **GATED** with Cloudflare Access (email-OTP), app "Nelson Preview". apex + www redirect to
  `nte-tte-team.cloudflareaccess.com` login. Allowed: ben.nelson.ee@gmail.com. Session: 1 week.
- ✅ Backend **admin auto-login** wired: `.env` has `CF_ACCESS_TEAM_DOMAIN=nte-tte-team.cloudflareaccess.com`,
  `CF_ACCESS_AUD=a6354b7d…310d`, `CF_ADMIN_EMAILS=ben.nelson.ee@gmail.com`. Passing the Access gate
  → auto-provisioned admin on the Nelson site.

### Homepage design direction (chosen 2026-07-15)
- **"Bold Red Garage" (v6)** — dark shop-floor ground, red `#B01F27` + amber accents, condensed type.
  Light header bar with the real logo top-left (no chip). No-scroll **mega-menu** (hover dropdowns,
  depth in panels — never a horizontal scrollbar). **Big hero banner that auto-crossfades through
  featured products** (admin-editable, mirror Titan banner CMS; seasonal rotation). Products high on
  the page ("In stock & ready today" grid). Serves BOTH audiences: Work Equipment + Truck/Van Accessories.
- **PICKUP-FIRST positioning (owner directive, key differentiator):** emphasize *"pick it up today"*
  over shipping — higher margin + the moat Amazon can't match (on-the-shelf now + great price + a
  human who talks fitment/alternates at the counter). Build implications: pickup = default fulfillment
  method; per-branch stock on each product ("N in stock · Portland · ready now"); branch selector;
  checkout defaults to "Pick up at [branch]", ship is the fallback. Mockup carries it in the util bar,
  hero badges, a "why Nelson beats Amazon" value band, and product CTAs ("Pick up today →").
- **v7 refinements (Ben, 2026-07-15):** dropped the dated tan → clean white header + cool neutrals;
  fonts → **Barlow / Barlow Condensed** (self-host at build); modern outline cart icon + badge.
- **Branches/phones:** Portland **503.548.9300**, Kent **253.395.3825** (Portland OR + Kent WA).
- **Market focus = PACIFIC NORTHWEST, not national** (Ben) → local/regional SEO (PNW terms, a Google
  Business Profile per branch, LocalBusiness schema per branch), pickup + regional delivery over
  national shipping. Reinforces the pickup-first moat.
- **Value pillars (v10):** *Pick it up today · **We install everything we sell** · Talk to a real
  expert* — plus a **"We build custom, too"** invite band with a "Tell us about your project" CTA
  (opens a project-inquiry form → team). Install + custom fab = the full-service story a catalog can't
  match. **Do NOT mention Amazon / competitors** anywhere (owner directive — "don't poke the bear").
- **Divisions in nav (v12):** top-level = Snow & Ice · Bodies · **Towing** (wreckers/rollbacks/rotators/
  recovery — Jerr-Dan) · **Aerial & Bucket** (bucket trucks/aerial lifts/digger derricks — Dur-A-Lift/
  Versalift) · Liftgates & Cranes · Accessories · Brands · Deals. Towing & Aerial are full built-to-order
  equipment divisions, each also a banner slide. **Confirm actual towing/aerial brands with Ben.**
- **Logo lockup (v11):** horizontal — truck hex badge (`nelson-badge.png`, staged in brand folder) left +
  "NELSON TRUCK" wordmark right. Wordmark is live Barlow Condensed text in the mockup; use the real brand
  wordmark font/SVG at build.
- **Trailers/Landoll division (v13):** Nelson is a **Landoll dealer** — Trailers nav item (Traveling Axle,
  Detach Gooseneck, Sliding Axle, Trailer Parts, **Landoll Parts**) + banner slide + brand. **Landoll parts**
  wanted on the site.
- **Tow Truck Parts (v13):** full line wanted — Nelson is bigger in towing than Titan (Titan may have partial
  tow-parts data to build on). Emphasized in the Towing dropdown + banner. **Build/data task:** audit which
  tow-truck-parts + Landoll-parts SKUs already exist in the shared catalog; source the gaps.
- **Logo (v13):** real wordmark preserved — badge (`nelson-badge.png`) + cropped real lettering
  (`nelson-wordmark.png`), NOT a substitute font. Both staged in the site brand folder.
- **Steel/Metal (v16 — Ben's scoping):** PHASE 1 = **advertise only** — "Yes, we sell steel," buy/cut at the
  counter (Portland & Kent), NO online per-lb purchase and NO shipping cut material (avoids the "1/8-off →
  refund" problem). CTA → info page, not a cart. Per-lb online sales + cut-request flow are a *later, optional*
  add. **Versalift removed** (not a Nelson brand; confirm the real aerial brand).
- **Logo (v19):** horizontal lockup — badge (larger) + "NELSON TRUCK / EQUIPMENT CO., INC." (no "EST. 1937";
  1937 still in the stats bar). Mockup uses a raster wordmark crop → slightly blurry when scaled.
  **BUILD FIX:** extract the wordmark as VECTOR from `nelson_logo.svg` for crisp lettering at any size.
- Nav category "Towing" renamed to **"Tow Trucks"** (v20).
- Mockups: `scratchpad/nelson_bold_red_v20.html` (LATEST, approved direction). Fonts self-hosted at build. **SEO anti-dup (bots ≠ same company):** self-canonical, distinct
  Organization/LocalBusiness JSON-LD, differentiated copy/product descriptions (use Ollama), distinct
  template (done), separate GBP/socials, no cross-linking the two sites.

### ⏳ Remaining follow-ups
- **`nelsontruck.com` (launch host)** → add as a route on `nelson-preview` tunnel when ready to go live.
- **(Optional) ERP own tunnel** — `nte-sys.com` currently rides `titan-preview` (already Access-gated,
  team `nte-tte-team`); could move to its own tunnel for cleanliness. Access follows the hostname.
- **Product images** — symlink Titan's 8.9GB library + map 200K `product_image` rows to Nelson by SKU.
- **Visual restructure** — pick a direction (01 Heritage / 02 Fleet Counter / 03 Bold Red Garage).
- Real creds in `.env` (separate Authorize.net, @nelsontruck.com SMTP); prerender + inventory/reindex timers.
- **nelson-prerender** service (bot SSR, :3002) + nginx bot branch (Titan has one).
- **Timers:** `nelson-inventory-sync` + `nelson-reindex` (keep stock/index fresh) — Titan has these.
- **Backend creds:** fill real Authorize.net (SEPARATE Nelson acct), email-SMTP (@nelsontruck.com),
  Cloudflare in `.env`. Customer sync needs the bridge to expose `nte_cus190`.
- **Product images:** `backend/static` (681M) not copied — images render null until wired.
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
