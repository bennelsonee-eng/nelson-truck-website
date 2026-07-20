# Catalog Visibility Tree + Admin Message Board — Build Plan

**Repo:** Titan Truck Website (`C:\Users\Ben\titan truck website`, this app) — build here first, then clone to the Nelson site.
**Goal:** Give admins a Windows-explorer-style tree of the catalog with show/hide toggles at every level, so a whole manufacturer line can be turned on/off completely or partially from the admin control panel only. Hidden products are suppressed from the website at the nightly re-index (with an on-demand "Apply now"), kept out of sitemaps, and served as `410 Gone` to bots. A new admin-only message board warns when a hidden part breaks a kit and surfaces major site-health issues.

> Authored in the `nelson-erp` Claude session, 2026-07-16. Copy into the website repo root before the build session.

---

## 0. Key finding — the plumbing mostly exists

Every website surface already respects **`Product.is_hidden`**:
- **Typesense search** — indexed with `is_hidden`; query filters `is_hidden:false` + `is_for_sale:true` (`app/backend/app/services/search.py`, query at line ~428).
- **DB browse fallback** — `_browse_via_pace` filters `is_hidden == False, is_for_sale == True, Brand.is_active == True` (`app/backend/app/routers/catalog.py:338`).
- **Sitemap** — `_visible_products()` already excludes hidden/for-sale/login-gated products (`app/backend/app/routers/seo.py:57`).
- **Product page `noindex`** — `ProductDetail` renders `<Seo noindex={data.is_hidden || !data.is_for_sale} />` (`App.tsx:4974`, `components/Seo.tsx`).
- **Nightly re-index** — systemd `titan-reindex.timer` at 04:30 UTC → `reindex_typesense.py` → `reindex_all_products` re-reads `is_hidden` from the DB. **So flipping the flag and letting the nightly job run IS the "takes effect at night" behavior, with zero pipeline change.**

So the design drives one source of truth — `Product.is_hidden` — from a cascade/override model. Nothing downstream needs a new concept.

**Confirmed gaps to close:**
1. No tree UI, no override/cascade model, no resolver.
2. Hidden product pages return `200` today (not `410`); the prerenderer (`app/prerender/server.mjs`) always returns `200`.
3. No admin message board / notifications table exists (only `error_reports`, which is out-of-band and purpose-built for recorded bug reports).
4. `request_log` telemetry (4xx/5xx, cart/checkout failures, JS errors) is written but **read only by a nightly Word-doc job** — nothing surfaces it live in-app.

---

## 1. Design decisions (locked with owner)

- **Tree hierarchy:** Manufacturer line (Brand, keyed by AAIA code) → Category → Subcategory (deeper `category` levels) → **Filters (curated)** → Part numbers.
- **Toggle at every level**, including filter-values (bulk-hide every matching part), plus individual parts.
- **The tree drives TWO fields, not just visibility** (owner ask 2026-07-16): each node can set `hidden` AND `shipping_mode`. The override model is generalized to `(scope, field, value)` so future product fields slot in for free. See §1a.
- **When it applies:** override saved instantly; website changes at the nightly 04:30 re-index by default, with an **"Apply now"** button to re-index on demand.
- **Message board surfaces:** (a) kit-conflict warnings (hidden part used in an active kit) AND (b) live site-health issues (page 5xx, cart/checkout failures, JS errors) read live from `request_log`.
- **Filters come from the CURATED list only** — `AttributeValueAlias` (raw PIES value → admin-approved `canonical_value`, `source='manual'`) folded through `bucket_by_canonical` / `attribute_key_alias` group labels. This is the exact pipeline behind the storefront left rail (`/api/catalog/category-attributes`, `catalog.py:1705`). Never raw `product_attribute` values.
- **No part is ever orphaned — default catch-all at every level:**
  - Under a manufacturer line: parts with **no category** → **"Uncategorized"** bucket.
  - Under a category: parts with **no curated attribute** → **"No filters"** bucket.
  - Final safety net: any part a scope claims but no child node claims → the node's **catch-all** (defined by *subtraction*: "every part under this scope no child claimed"), so incomplete cataloging can never hide a part from the admin.
  - Parts are listed **directly from the category→product resolver** (`_category_product_ids_subq` / `_browse_via_pace`), independent of filters — filters are an optional narrowing lens, not a gate.

## 1a. Shipping mode (ship / truck freight / will call)

A second overridable field, applied through the exact same tree/cascade/nightly-apply machinery as `hidden`.

- **`Product.shipping_mode`** ∈ `ship | truck_freight | will_call` (effective, resolver-derived) + **`base_shipping_mode`** baseline (importers/seed write this). Same derived/baseline split as `is_hidden`/`base_hidden`.
  - **Ship** — normal parcel/ground.
  - **Truck Freight** — LTL freight; *shippable*, heavy. Storefront badge "Truck Freight". **Seed:** `weight_lb > 500 OR cta_mode='QUOTE_SHIPPING'`.
  - **Will Call** — *pickup only, not shippable*; unit comes from its current stocking area. Storefront badge "Will Call — Pickup Only". Set manually via the tree.
- **Global will-call pickup (NOT a per-product hide):** any **in-stock** product offers Will-Call pickup at the branch where it's stocked — checkout behavior for in-stock items regardless of `shipping_mode`. `will_call` mode is just the case where pickup is the *only* option.
- **Labels/badges:** show on product cards + PDP for `truck_freight` and `will_call`; in-stock items can show "Available for pickup at {branch}".
- **Checkout wiring** (later phase): `truck_freight` → LTL/quote flow (today's freight path); `will_call` → suppress shipping, pickup-only at stocking branch; in-stock any-mode → offer pickup option.

## 1b. Flat-rate shipping (owner ask 2026-07-16)

A THIRD overridable field on the same tree — demonstrates the generalization payoff.

- **`Product.flat_ship_amount`** (effective, resolver-derived) + **`base_flat_ship_amount`** (baseline), both **nullable** `Numeric(10,2)`.
  - **NULL** → normal weight-tiered freight (today's behavior).
  - **`0.00`** → free shipping.
  - **`> 0`** → charge that flat amount instead of the computed rate.
- Field spec cast = `Decimal`; the override `value` stores the amount as text (e.g. `"19.00"`) or empty for NULL.
- **Not wired today:** legacy `shipping_amount` / `handling_amount` / `free_ground` columns exist but `freight_service.py` ignores them (freight is purely weight-tiered). Flat-rate is new at checkout.
- **Checkout wiring** (later phase): `freight_service` honors `flat_ship_amount` before weight tiers; `will_call` ignores it. Open detail: flat amount is per-unit vs per-line vs per-order — decide when wiring.

> **RETAIL ONLY (owner ask 2026-07-16):** `shipping_mode` freight handling + `flat_ship_amount` apply to **retail** customers only. B2B customers (jobber / dealer / municipality tiers) use a **separate freight program** — their checkout ignores flat-rate and the retail freight calc. So these fields are still set per product in the tree, but their *effect* is gated to the retail context at checkout. Badges may still show to everyone (informational); the freight math is retail-gated. Settle exact B2B behavior when wiring `freight_service`.

---

## 2. Data model — one Alembic migration

Alembic head is `f4g8h2j6k0m3_build_idea.py`; next revision starts with `g…`, `down_revision = "f4g8h2j6k0m3"`. (Verify with `alembic heads` before writing.) Models in `app/backend/app/models/`, re-exported in `models/__init__.py`.

### `catalog_visibility_override`
- `id`, timestamps (from `Base`).
- `scope_type` ENUM(`brand`, `category`, `product`, `filter`).
- `brand_id` (nullable FK), `category_id` (nullable FK), `product_id` (nullable FK).
- Filter scope: `attr_key`, `attr_value` (the **canonical** value), bounded by the `brand_id`/`category_id` context it was set within.
- `hidden` BOOLEAN — `True` = hide, `False` = explicit **show** (punches through an ancestor hide, e.g. "hide the whole line except this one category").
- `note`, `updated_by` (user id), `updated_at`, `created_at`.
- Partial unique indexes per scope so a scope has at most one active override.

### `admin_message`
- `id`, timestamps.
- `kind` ENUM(`kit_conflict`, `site_error`, `cart_failure`, `js_error`, `page_down`, `info`).
- `severity` (info/warning/critical), `title`, `body`, `context` JSONB.
- `status` ENUM(`open`, `ack`, `resolved`).
- `dedupe_key` (e.g. `kit_conflict:<kit_id>:<product_id>`), `first_seen`, `last_seen`, `count`.
- `resolved_by`, `resolved_at`.

---

## 3. Resolver service — `app/backend/app/services/catalog_visibility.py`

`resolve_effective_hidden(db) -> ResolveResult`:
1. Load all overrides.
2. For each affected product, compute effective hidden by **precedence, most-specific wins**:
   `product override → filter-value override → subcategory → category → manufacturer line → default visible`.
   - Filter-value override maps the **canonical** value back to its raw PIES values via `AttributeValueAlias` (the reverse map already in `catalog.py:538–556`) to select the matching product set within the scope.
3. Write `Product.is_hidden` where changed. For **full-scope** hides (whole line / whole category), also mirror `Brand.is_active` / `Category.is_active` so brand/category **landing pages** drop too.
4. Return the changed set + the current hidden product set (for kit-conflict detection).

`detect_kit_conflicts(db, hidden_pids)`:
- `kit_component ⋈ kit` where `component.product_id ∈ hidden_pids` AND `kit.is_active`.
- Upsert `admin_message(kind=kit_conflict, dedupe_key=kit_conflict:<kit_id>:<product_id>)`; clear/resolve stale ones when the part is shown again.

Admin-scoped facet helper (reuses curation, drops the visibility gate):
- Variant of the `/category-attributes` query that omits `is_hidden == False AND is_for_sale == True` so **hidden parts still appear** in the tree's Filters level and remain toggleable. Same `AttributeValueAlias` + `bucket_by_canonical` curation as the storefront.

---

## 4. Backend API — `app/backend/app/routers/admin_catalog_visibility.py`

Prefix `/api/admin/catalog-visibility`, every route `Depends(require_admin)` (`app/backend/app/dependencies.py:55`).

- `GET /tree/roots` — manufacturer lines (brands + AAIA code, part counts, effective visibility, pending flag).
- `GET /tree/children` — lazy children for a node (`scope=brand|category`): categories/subcategories, then the **Filters** group, the **No filters** bucket, the **Uncategorized** bucket, and the node catch-all — each with counts + effective state.
- `GET /tree/parts` — paginated part numbers for a scope (category / filter-value / no-filters / uncategorized / catch-all), each with per-part effective visibility.
- `POST /override` — set hidden/show at a scope; writes the override **immediately**, runs an instant kit-conflict check, returns pending + any new warnings.
- `DELETE /override/{id}` — clear an override (revert to inherited).
- `GET /pending` — count of overrides changed since the last successful re-index (drives the "pending until tonight" badge).
- `POST /apply-now` — background task: `resolve_effective_hidden` → `index_products`/reindex → `detect_kit_conflicts`; clears pending.

Wire `resolve_effective_hidden()` into the top of `reindex_typesense.py main()` so the **nightly** job applies overrides before re-indexing.

---

## 5. Admin message board — `app/backend/app/routers/admin_messages.py`

Prefix `/api/admin/messages`, `Depends(require_admin)`.
- `GET /` — list persistent `admin_message` rows (filter by kind/status).
- `POST /{id}/ack`, `POST /{id}/resolve`.
- `GET /site-health` — **live** rollup over `request_log` (last 24–48h): recent 5xx, cart/checkout failures (`/api/cart% /api/checkout% /api/order% %payment%` 4xx/5xx), JS errors (`kind='js_error'`), page-down signals. Not materialized — computed on read to avoid noise.
- `GET /stats` — open count, to fold into the existing header badge.

---

## 6. Frontend

Both pages as **new lazy-loaded files** (keep them out of the 16k-line `App.tsx`, mirroring `AdminKits.tsx`):

- `app/frontend/src/pages/AdminCatalogVisibility.tsx` — the tree: expand/collapse nodes, per-node eye toggle (hide / show / inherited), pending badges, **Apply now** button, search box to jump to a brand or part number. Lazy `import`, `<Route path="/admin/catalog-visibility">` (~`App.tsx:16193`), tile in the `adminTools` array (~`App.tsx:5801`).
- `app/frontend/src/pages/AdminMessages.tsx` — two panels: **Alerts** (persistent kit-conflict / hide warnings, ack/resolve) + **Site Health** (live `request_log` rollup). Route + admin tile as above.
- Header badge: fold `admin_messages` open count into `AdminIssuesBadge` (`App.tsx:1291`) alongside the error-reports count (or a sibling badge).

---

## 7. Bot / broken-link suppression (close the gaps)

Sitemap already excludes hidden; PDP already emits `noindex`. Remaining:
- `catalog.py::product_detail` (~line 974, right after the `product is None` check): return **HTTP 410 Gone** for hidden / not-for-sale products to anonymous/bot requests (authenticated admins still preview). Tells bots to drop the URL.
- `app/prerender/server.mjs`: propagate that `410` (today it always returns `200`) by reading a status signal the page sets (e.g. `window.prerenderStatus`) — so Googlebot/GPTBot/ClaudeBot get a real "gone".
- SPA `ProductDetail` error state (`App.tsx:4912`): render `<Seo noindex>` + a clean "no longer available" message on 404/410.

---

## 8. Verify + record

- Verify end-to-end on the Titan **local** dev servers (do NOT touch prod): hide a part → after Apply-now it's gone from search + browse, its page 410s for bots, and a kit-conflict message appears if it's in an active kit; show it again → message resolves, part returns.
- Log overrides via the existing `admin_audit` service.
- Update `BUILD_AUDIT_LOG.md` and note the flow in `OPERATIONS_NOTES.md`.

---

## 9. Clone to Nelson

After Titan is dialed in, port the migration, models, services, routers, and the two admin pages into `nelson truck website/` (identical schema; the Nelson site is already a structural clone). Nelson dev ports 8002/5175.

---

## Build order

1. **Phase 1** — migration + models + resolver + kit-conflict detection.
2. **Phase 2** — visibility API + reindex wiring + Apply-now.
3. **Phase 3** — tree UI (brand/category/part first, then curated filter-values on the same override model).
4. **Phase 4** — message board (table already in Phase 1) + router + badge.
5. **Phase 5** — 410-for-bots + prerender status + SPA error noindex.
6. **Phase 6** — verify, audit log, docs.
7. **Phase 7** — clone to Nelson.

**Branch:** feature branch off `main` in the Titan repo. No prod changes until the owner has seen it working locally.
