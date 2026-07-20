import { Fragment, lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useState, createContext, useContext, useRef } from 'react'
import type { ReactNode } from 'react'
import { Routes, Route, Link, useParams, useSearchParams, useNavigate, useLocation, useNavigationType } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import ErrorReporter from './components/ErrorReporter'
import { RotatingBanner } from './pages/HomepageMockups'
// Lazy-loaded: the admin-kits pages (/admin/kits/*) — not on the public critical
// path, so they load on demand rather than in the initial bundle.
const AdminKitsListPage = lazy(() => import('./AdminKits').then((m) => ({ default: m.AdminKitsListPage })))
const AdminCatalogVisibilityPage = lazy(() => import('./pages/AdminCatalogVisibility').then((m) => ({ default: m.AdminCatalogVisibilityPage })))
const AdminMessagesPage = lazy(() => import('./pages/AdminMessages').then((m) => ({ default: m.AdminMessagesPage })))
const AdminKitWizardPage = lazy(() => import('./AdminKits').then((m) => ({ default: m.AdminKitWizardPage })))
// Static content + trust pages (low-traffic → lazy-loaded off the main bundle).
const FaqPage = lazy(() => import('./pages/ContentPages').then((m) => ({ default: m.FaqPage })))
const AboutPage = lazy(() => import('./pages/ContentPages').then((m) => ({ default: m.AboutPage })))
const ReturnsPage = lazy(() => import('./pages/ContentPages').then((m) => ({ default: m.ReturnsPage })))
const ShippingPage = lazy(() => import('./pages/ContentPages').then((m) => ({ default: m.ShippingPage })))
const PrivacyPage = lazy(() => import('./pages/ContentPages').then((m) => ({ default: m.PrivacyPage })))
const AdminContentPage = lazy(() => import('./pages/AdminContent').then((m) => ({ default: m.AdminContentPage })))
import { Seo, absoluteUrl, clamp, ORGANIZATION_JSONLD, WEBSITE_JSONLD, LOCALBUSINESS_JSONLD, CANONICAL_BASE_URL } from './components/Seo'

// ============================================================================
// Display helpers
// ============================================================================

/**
 * Format a SKU for customer-facing display as "BrandName: partNum".
 *
 * Our internal SKU is `{AAIA_brand_code}-{parts_num}` (e.g. "BHTJ-110001").
 * For end users we show the human-readable brand name + the manufacturer
 * part number, so "BHTJ-110001" with brand "WeatherTech" renders as
 * "WeatherTech: 110001". When brand isn't available, falls back to the
 * raw SKU so we never render an empty or weird value.
 */
function formatPartNumber(sku: string | null | undefined, brand: string | null | undefined): string {
  if (!sku) return ''
  const idx = sku.indexOf('-')
  if (idx < 0 || !brand) return sku
  return `${brand}: ${sku.substring(idx + 1)}`
}

// Derive the 400px thumbnail from a full-size product image. Images are stored
// as {hash}_1280.jpg with a pre-generated {hash}_400.jpg sibling, so grid cards
// load ~400px instead of 1280px — a big LCP + bandwidth win (matters for slow
// government/enterprise networks too). Falls back to the original if it doesn't
// match the naming convention.
function thumbUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined
  return url.replace(/_1280\.(jpe?g|png|webp)$/i, '_400.$1')
}

// ============================================================================
// API types
// ============================================================================

interface User {
  id: number
  email: string
  role: string
  display_name: string | null
  customer_id: number | null
  customer_number: string | null
  customer_name: string | null
  customer_tier: string | null
  front_counter_markup_pct: number | null
  // Retail Showroom Mode (white-label kiosk) config — account-wide.
  showroom_enabled: boolean
  showroom_logo_url: string | null
  showroom_display_name: string | null
  is_verified: boolean
}

// Admin "Shop as Customer" (A4.28). Mirrors the backend ImpersonationState +
// CustomerSearchHit schemas in app/backend/app/routers/admin.py.
interface ImpersonationState {
  impersonating: boolean
  customer_id: number | null
  customer_number: string | null
  customer_name: string | null
  tier: string | null
}

interface CustomerSearchHit {
  id: number
  customer_number: string
  name: string
  tier: string
  default_ship_to: string | null
}

interface YMM {
  year: number
  make_slug: string
  make_name: string
  model_slug: string
  model_name: string
  base_vehicle_id?: number  // populated when /api/ymm/resolve is called against the new PACE-backed endpoint
}

interface YmmMake { slug: string; name: string; is_featured: boolean }
interface YmmModel { slug: string; name: string; body_type: string; year_start: number; year_end: number | null }

interface AutocompleteResult {
  query: string
  parts: { id: number; sku: string; name: string; brand: string | null; image_url: string | null; in_stock: boolean }[]
  // `path` is the full ancestor chain ("Truck Accessories > Automotive
  // Lighting > Emergency and Warning Lighting"); `name` is the leaf
  // segment used as the chip label. The click navigates by full path
  // so we land on the right shelf, not the top-level department.
  categories: { name: string; path?: string; count: number }[]
  brands: { name: string; count: number }[]
  found: number
}

interface BrandsIndex {
  letters: string[]
  groups: { letter: string; brands: { name: string; slug: string; product_count: number; is_featured: boolean; logo_url: string | null }[] }[]
}

interface CategoryNode {
  id: number
  name: string
  slug: string
  full_path: string
  depth: number
  parent_id: number | null
  product_count: number
  image_url?: string | null
  image_inherited?: boolean
  children: CategoryNode[]
}

interface CategoryDetail {
  id: number
  name: string
  slug: string
  full_path: string
  depth: number
  image_url?: string | null
  breadcrumb: { name: string; slug: string; full_path: string }[]
  children: { id: number; name: string; slug: string; full_path: string; image_url?: string | null }[]
}

interface WarehouseStock {
  sku: string
  total_on_hand: number
  locations: {
    warehouse_code: number
    warehouse_name: string
    on_hand: number
    in_stock: boolean
    lead_time: string
    next_day_cutoff: string
    facs_route: string
  }[]
}

interface HotProduct {
  sku: string
  name: string
  brand: string | null
  image_url: string
  in_stock: boolean
  stock_total: number
}

interface RecentlyViewedItem {
  sku: string
  name: string
  brand: string | null
  image_url: string | null
  visited_at: number
}

/** Pure helper mirroring the backend front_counter_quote() math. */
function frontCounterQuote(
  primaryAmount: string | null,
  originalAmount: string | null,
  mapRetail: string | null,
  markupPct: number | null,
): string | null {
  const cost = originalAmount ? parseFloat(originalAmount) : (primaryAmount ? parseFloat(primaryAmount) : null)
  const map = mapRetail ? parseFloat(mapRetail) : null
  if (!markupPct) return mapRetail || (cost !== null ? cost.toFixed(2) : null)
  if (cost === null) return mapRetail
  const marked = +(cost * (1 + markupPct / 100)).toFixed(2)
  if (map === null) return marked.toFixed(2)
  return Math.max(marked, map).toFixed(2)
}

interface CartLine {
  id: number
  product_id: number
  sku: string
  name: string
  brand: string
  quantity: number
  unit_price: string | null
  line_total: string | null
  map_retail: string | null
}

interface CartResponse {
  id: number
  line_count: number
  item_count: number
  subtotal: string
  lines: CartLine[]
}

interface TierPricingBlock {
  tier: string                          // 'jobber' | 'dealer' | 'retail' | 'municipality'
  primary_label: string                 // 'Your Cost' for B2B, 'Retail' for anon-retail fallback
  primary_amount: string | null         // formatted decimal string like "189.99"
  secondary_label: string | null
  secondary_amount: string | null
  savings_amount?: string | null
  contract_id?: number | null
  contract_name?: string | null
  notes?: string[]
  map_clamped?: boolean
  original_amount?: string | null
}

interface BrowseHit {
  id: number
  sku: string
  name: string
  brand: string | null
  in_stock: boolean
  stock_total: number
  cta_mode: string
  shipping_mode?: string | null
  image_url: string | null
  category_top: string | null
  description?: string | null
  series?: string | null
  locations_count?: number
  retail_price?: number | null
  sale_price?: number | null
  tier_pricing?: TierPricingBlock | null
  fitment_summary?: string[]
  fitment_group_count?: number
  fitment_universal?: boolean
  special_order_lead_time_min_days?: number | null
  special_order_lead_time_max_days?: number | null
}

// Render "typically X-Y business days" / "up to Y business days" / "X business days"
// from brand lead-time fields. Returns null when neither bound is set so callers
// can fall back to just "Special order" without a lead-time clause. L9.
function formatLeadTime(minDays: number | null | undefined, maxDays: number | null | undefined): string | null {
  if (minDays && maxDays && minDays !== maxDays) return `typically ${minDays}-${maxDays} business days`
  const d = maxDays || minDays
  if (!d) return null
  return `typically ${d} business day${d === 1 ? '' : 's'}`
}

interface FitmentGroup {
  make: string
  models: {
    model: string
    year_start: number | null
    year_end: number | null
    fitment_count: number
  }[]
}

interface FitmentResponse {
  sku: string
  universal: boolean
  make_count: number
  model_count: number
  groups: FitmentGroup[]
}

interface BrowseResponse {
  hits: BrowseHit[]
  found: number
  in_stock_count?: number
  page: number
  per_page: number
  search_time_ms: number
  facets: Record<string, { value: string; count: number }[]>
  // Set when a Year/Make/Model was parsed out of the free-text query
  // (e.g. "2023 f-250 tonneau cover"). Threaded into the in-stock-substitute
  // callout so it suggests a part that fits THIS vehicle, not just any
  // in-stock cousin in the category.
  resolved_vehicle?: { base_vehicle_id: number; label: string } | null
}

interface PricingBlock {
  tier: string
  primary_label: string
  primary_amount: string | null
  secondary_label: string | null
  secondary_amount: string | null
  savings_amount: string | null
  contract_id: number | null
  contract_name: string | null
  notes: string[]
  map_clamped: boolean
  original_amount: string | null
}

interface AddressOut {
  name: string | null
  company: string | null
  addr1: string | null
  addr2: string | null
  city: string | null
  state: string | null
  zip: string | null
}

interface FulfillmentOut {
  routing_type: string
  facs_warehouse_code: number
  file_name: string
  push_status: string
  item_subtotal: string
  line_count: number
}

interface OrderLineOut {
  line_number: number
  sku: string
  description: string | null
  quantity: number
  backorder_quantity: number
  unit_price: string
  line_total: string
  routing: string | null
  is_freight: boolean
  is_discount: boolean
  is_handling: boolean
}

interface OrderOut {
  id: number
  web_order_number: string
  status: string
  payment_type: string
  customer_po_number: string | null
  contact_email: string | null
  contact_phone: string | null
  item_total: string
  shipping_total: string
  handling_total: string
  discount_total: string
  tax_total: string
  grand_total: string
  order_date: string | null
  required_date: string | null
  placed_at: string
  shipping: AddressOut
  billing: AddressOut
  fulfillments: FulfillmentOut[]
  lines: OrderLineOut[]
}

interface OrderSummary {
  id: number
  web_order_number: string
  status: string
  item_count: number
  grand_total: string
  placed_at: string
  fulfillment_count: number
}

interface ProductDetail {
  id: number
  sku: string
  name: string
  description: string | null
  extended_description: string | null
  brand: { id: number; name: string; slug: string; special_order_lead_time_min_days?: number | null; special_order_lead_time_max_days?: number | null }
  reseller_alternate?: { sku: string; name: string; brand: string | null; retail_price: number; savings: number } | null
  prod_code: string | null
  weight_lb: number | null
  dimensions: { length_in: number | null; width_in: number | null; height_in: number | null }
  freight_class: string | null
  cta_mode: string
  shipping_mode: string | null
  flat_ship_amount: number | null
  is_for_sale: boolean
  is_hidden: boolean
  images: { url: string; alt: string | null; sort_order: number }[]
  inventory: { warehouse_code: number; warehouse_name: string; on_hand: number }[]
  total_on_hand: number
  pricing: PricingBlock | null
  viewer_tier: string
  // Categorized text content from PIES + scraped feature blocks.
  // descriptions: typed prose grouped by PIES code (FEA = features,
  // DES = description, INL = installation, etc.). FEA rows ordered by
  // sequence preserve the source page's render order (Layout B carousel
  // OR Layout C/D hero bullets — text may be a single sentence OR
  // "HEADING\n\nbody paragraph" depending on the source PDP layout).
  // attributes: key/value/uom spec rows from Layout B premium-plow PDPs.
  descriptions: { code: string; language_code: string; sequence: number; text: string }[]
  attributes: { key: string; value: string | null; uom: string | null }[]
  // Downloadable resources (install guides, datasheets, parts sheets).
  resources?: { kind: string; url: string; title: string | null }[]
  // Kit / package bill-of-materials (WeatherGuard van packages). Each
  // component links to its own PDP when `sku` resolves to a catalog product.
  kit?: {
    sku: string
    trade: string | null
    vehicle_make: string | null
    vehicle_model: string | null
    wheelbase: string | null
    hand: string | null
    components: { part_number: string; quantity: number; description: string | null; product_id: number | null; sku: string | null }[]
  } | null
}

// ============================================================================
// Auth + Cart context
// ============================================================================

interface AppCtx {
  user: User | null
  cart: CartResponse | null
  frontCounter: boolean
  setFrontCounter: (v: boolean) => void
  // Retail Showroom Mode — white-label kiosk (per-device lock).
  showroom: boolean
  setShowroom: (v: boolean) => void
  ymm: YMM | null
  setYmm: (v: YMM | null) => void
  quickOrderOpen: boolean
  setQuickOrderOpen: (v: boolean) => void
  ymmOpen: boolean
  setYmmOpen: (v: boolean) => void
  compareSkus: string[]
  toggleCompare: (sku: string) => void
  clearCompare: () => void
  isInCompare: (sku: string) => boolean
  recentSkus: Set<string>
  refreshRecentSkus: () => Promise<void>
  cfIdentity: { email: string; can_report: boolean } | null
  refreshUser: () => Promise<void>
  refreshCart: () => Promise<void>
  logout: () => Promise<void>
  addToCart: (sku: string, qty: number) => Promise<void>
  updateQty: (lineId: number, qty: number) => Promise<void>
  removeLine: (lineId: number) => Promise<void>
  // Admin "Shop as Customer" impersonation
  impersonation: ImpersonationState | null
  impersonateOpen: boolean
  setImpersonateOpen: (v: boolean) => void
  refreshImpersonation: () => Promise<void>
  startImpersonation: (customerId: number) => Promise<void>
  exitImpersonation: () => Promise<void>
}

const COMPARE_MAX = 4

const Ctx = createContext<AppCtx | null>(null)

function useApp() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useApp outside provider')
  return c
}

function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [cfIdentity, setCfIdentity] = useState<{ email: string; can_report: boolean } | null>(null)
  const [cart, setCart] = useState<CartResponse | null>(null)
  const [frontCounter, setFrontCounterState] = useState<boolean>(() => {
    try { return localStorage.getItem('titan_front_counter') === '1' } catch { return false }
  })
  // Retail Showroom Mode is a per-device kiosk lock (survives reload).
  const [showroom, setShowroomState] = useState<boolean>(() => {
    try { return localStorage.getItem('titan_showroom') === '1' } catch { return false }
  })
  const [ymm, setYmmState] = useState<YMM | null>(() => {
    try {
      const raw = localStorage.getItem('titan_ymm')
      return raw ? JSON.parse(raw) as YMM : null
    } catch { return null }
  })
  const [quickOrderOpen, setQuickOrderOpen] = useState<boolean>(false)
  const [ymmOpen, setYmmOpen] = useState<boolean>(false)
  const [impersonation, setImpersonation] = useState<ImpersonationState | null>(null)
  const [impersonateOpen, setImpersonateOpen] = useState<boolean>(false)
  const [compareSkus, setCompareSkus] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem('titan_compare')
      return raw ? JSON.parse(raw) as string[] : []
    } catch { return [] }
  })

  function persistCompare(next: string[]) {
    setCompareSkus(next)
    try { localStorage.setItem('titan_compare', JSON.stringify(next)) } catch {}
  }

  const [recentSkus, setRecentSkus] = useState<Set<string>>(new Set())

  async function refreshRecentSkus() {
    try {
      const r = await fetch('/api/account/recent-skus', { credentials: 'include' })
      if (!r.ok) { setRecentSkus(new Set()); return }
      const data = await r.json()
      setRecentSkus(new Set<string>(Array.isArray(data?.skus) ? data.skus : []))
    } catch { setRecentSkus(new Set()) }
  }

  function toggleCompare(sku: string) {
    setCompareSkus((prev) => {
      const next = prev.includes(sku) ? prev.filter((s) => s !== sku) : (prev.length >= COMPARE_MAX ? prev : [...prev, sku])
      try { localStorage.setItem('titan_compare', JSON.stringify(next)) } catch {}
      return next
    })
  }
  function clearCompare() { persistCompare([]) }
  function isInCompare(sku: string) { return compareSkus.includes(sku) }

  function setFrontCounter(v: boolean) {
    setFrontCounterState(v)
    try { localStorage.setItem('titan_front_counter', v ? '1' : '0') } catch {}
  }

  function setShowroom(v: boolean) {
    setShowroomState(v)
    try { localStorage.setItem('titan_showroom', v ? '1' : '0') } catch {}
  }

  function setYmm(v: YMM | null) {
    setYmmState(v)
    try {
      if (v) localStorage.setItem('titan_ymm', JSON.stringify(v))
      else localStorage.removeItem('titan_ymm')
    } catch {}
  }

  async function refreshUser() {
    const r = await fetch('/api/auth/me', { credentials: 'include' })
    setUser(r.ok ? await r.json() : null)
  }

  async function refreshCart() {
    const r = await fetch('/api/cart', { credentials: 'include' })
    setCart(r.ok ? await r.json() : null)
  }

  async function logout() {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
    setUser(null)
    setImpersonation(null)
    await refreshCart()
  }

  // ---- Admin "Shop as Customer" (A4.28) ----
  // The impersonation state lives in the admin's JWT cookie (imp_cust claim).
  // We read it on boot / identity change so the banner + switcher reflect it.
  async function refreshImpersonation() {
    if (!user || user.role !== 'admin') { setImpersonation(null); return }
    try {
      const r = await fetch('/api/admin/impersonate/current', { credentials: 'include' })
      setImpersonation(r.ok ? await r.json() : null)
    } catch { setImpersonation(null) }
  }

  async function startImpersonation(customerId: number) {
    const r = await fetch(`/api/admin/impersonate/${customerId}`, {
      method: 'POST', credentials: 'include',
    })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : `HTTP ${r.status}`)
    }
    // The re-issued JWT now carries imp_cust. Reload so every priced component
    // (catalog, product pages, cart) re-resolves against the customer's
    // effective context — matches how the standalone page behaved.
    window.location.reload()
  }

  async function exitImpersonation() {
    await fetch('/api/admin/impersonate/exit', { method: 'POST', credentials: 'include' }).catch(() => {})
    window.location.reload()
  }

  async function addToCart(sku: string, qty: number) {
    const r = await fetch('/api/cart/lines', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sku, quantity: qty }),
    })
    if (r.ok) setCart(await r.json())
  }

  async function updateQty(lineId: number, qty: number) {
    const r = await fetch(`/api/cart/lines/${lineId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ quantity: qty }),
    })
    if (r.ok) setCart(await r.json())
  }

  async function removeLine(lineId: number) {
    const r = await fetch(`/api/cart/lines/${lineId}`, {
      method: 'DELETE',
      credentials: 'include',
    })
    if (r.ok) setCart(await r.json())
  }

  useEffect(() => {
    (async () => {
      // 1) Existing app session?
      const meRes = await fetch('/api/auth/me', { credentials: 'include' })
      if (meRes.ok) setUser(await meRes.json())
      // 2) Resolve any Cloudflare Access identity (drives the report tool + SSO).
      let cf: { authenticated?: boolean; email?: string; can_report?: boolean } | null = null
      try {
        const r = await fetch('/api/auth/cf-identity', { credentials: 'include' })
        cf = r.ok ? await r.json() : null
      } catch { cf = null }
      setCfIdentity(cf?.authenticated ? { email: cf.email!, can_report: !!cf.can_report } : null)
      // 3) No app session but a Cloudflare Access (OTP) session exists → try the
      //    passwordless admin sign-in. Succeeds only for allow-listed emails.
      if (!meRes.ok && cf?.authenticated) {
        try {
          const login = await fetch('/api/auth/cf-login', { method: 'POST', credentials: 'include' })
          if (login.ok) setUser(await login.json())
        } catch { /* not provisioned for admin → stay anonymous */ }
      }
    })()
    refreshCart()
  }, [])

  // Refresh "Reordered" badge SKU set whenever the user identity changes.
  // Anonymous users get an empty set (backend returns []), so no chips.
  useEffect(() => { refreshRecentSkus() }, [user?.id, user?.customer_id])

  // Keep the impersonation banner/switcher in sync with the signed-in admin.
  useEffect(() => { refreshImpersonation() }, [user?.id, user?.role])

  return (
    <Ctx.Provider value={{ user, cfIdentity, cart, frontCounter, setFrontCounter, showroom, setShowroom, ymm, setYmm, quickOrderOpen, setQuickOrderOpen, ymmOpen, setYmmOpen, compareSkus, toggleCompare, clearCompare, isInCompare, recentSkus, refreshRecentSkus, refreshUser, refreshCart, logout, addToCart, updateQty, removeLine, impersonation, impersonateOpen, setImpersonateOpen, refreshImpersonation, startImpersonation, exitImpersonation }}>
      {children}
    </Ctx.Provider>
  )
}

// ============================================================================
// Layout
// ============================================================================

// Shared signal: true while the header search autocomplete dropdown is open.
// The category mega-menu reads this when a hover fires and SUPPRESSES hover-open,
// so dragging the cursor from the search box down to the results doesn't pop the
// menu open over them. Module-level (not React state) because the nav only needs
// the value at the moment a hover happens — no re-render required.
let _searchDropdownOpen = false

// Retail Showroom Mode locks the whole storefront (nav + search + browse) to
// this single top-level category so a jobber's walk-in only sees accessories.
const SHOWROOM_CATEGORY = 'Truck Accessories'

// Browsers can't hide their own URL bar from a page, but the Fullscreen API
// does (real kiosk chrome). Must be invoked from a user gesture; survives SPA
// navigation but not a hard reload — hence the manual button too.
function enterFullscreen() {
  try { const p = document.documentElement.requestFullscreen?.(); if (p && typeof p.catch === 'function') p.catch(() => {}) } catch { /* unsupported / blocked */ }
}
function exitFullscreen() {
  try { if (document.fullscreenElement) { const p = document.exitFullscreen?.(); if (p && typeof p.catch === 'function') p.catch(() => {}) } } catch { /* ignore */ }
}
function toggleFullscreen() { if (document.fullscreenElement) exitFullscreen(); else enterFullscreen() }

function HeaderSearchBar() {
  const navigate = useNavigate()
  const { showroom } = useApp()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<AutocompleteResult | null>(null)
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState<number>(-1)
  const debounceRef = useRef<number | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  // Mirror dropdown-open state to the module flag the mega-menu checks.
  const dropdownVisible = open && !!results &&
    (results.parts.length > 0 || results.categories.length > 0 || results.brands.length > 0)
  useEffect(() => {
    _searchDropdownOpen = dropdownVisible
    return () => { _searchDropdownOpen = false }
  }, [dropdownVisible])

  useEffect(() => {
    if (q.trim().length < 2) {
      setResults(null); return
    }
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    debounceRef.current = window.setTimeout(() => {
      const scope = showroom ? `&category_top=${encodeURIComponent(SHOWROOM_CATEGORY)}` : ''
      const url = `/api/catalog/autocomplete?q=${encodeURIComponent(q.trim())}&parts_limit=8${scope}`
      fetch(url).then((r) => r.json()).then(setResults).catch(() => setResults(null))
    }, 180)
  }, [q, showroom])

  // Close on outside click
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  function submit(e: React.FormEvent) {
    e.preventDefault()
    const v = q.trim()
    setOpen(false)
    const scope = showroom ? `&category_top=${encodeURIComponent(SHOWROOM_CATEGORY)}` : ''
    if (v) navigate(`/catalog?q=${encodeURIComponent(v)}${scope}`)
  }

  function pickPart(sku: string) {
    setOpen(false)
    setQ('')
    navigate(`/product/${sku}`)
  }
  // A CATEGORY click is a "browse this category" intent — it must land on the
  // category's single canonical page (the same page the mega-menu opens), NOT
  // a text-filtered slice of it. So we DROP the typed query here. (The chip
  // count is computed full-category server-side to match this landing — see
  // _autocomplete_db_counts.) Example: searching "cargo rack" and clicking
  // "Van Cargo Racks" lands on all of Van Cargo Racks, not the 3 products
  // whose name literally contains "cargo rack".
  // Brands keep the query (see pickBrand) — a brand chip is "filter my search
  // by this brand", a different intent.
  // Dropdown gives a `path` for subcategory chips; fall back to `name` as
  // the top-level filter for legacy / no-path cases.
  function pickCategory(name: string, path?: string) {
    setOpen(false)
    setQ('')
    const qp = new URLSearchParams()
    if (path && path.includes('>')) {
      qp.set('category_top', path.split('>', 1)[0].trim())
      qp.set('category_path', path)
    } else {
      qp.set('category_top', name)
    }
    navigate(`/catalog?${qp.toString()}`)
  }
  function pickBrand(name: string) {
    const tail = q.trim()
    setOpen(false)
    setQ('')
    const qp = new URLSearchParams({ brand: name })
    if (tail) qp.set('q', tail)
    navigate(`/catalog?${qp.toString()}`)
  }

  function onKey(e: React.KeyboardEvent) {
    if (!results || !open) return
    const flatN = (results.parts.length) + (results.categories.length) + (results.brands.length)
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlight((h) => Math.min(h + 1, flatN - 1)) }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setHighlight((h) => Math.max(h - 1, -1)) }
    if (e.key === 'Escape')    { setOpen(false) }
  }

  return (
    <div ref={wrapRef} className="flex-1 max-w-2xl relative">
      <form onSubmit={submit}>
        <div className="relative">
          <input
            type="search"
            placeholder="Search part #, name, or brand…"
            value={q}
            onChange={(e) => { setQ(e.target.value); setOpen(true); setHighlight(-1) }}
            onFocus={() => q.trim().length >= 2 && setOpen(true)}
            onKeyDown={onKey}
            className="w-full bg-white border border-gray-300 rounded-md pl-10 pr-4 py-2 text-sm focus:outline-none focus:border-red-700 focus:ring-1 focus:ring-red-700"
          />
          <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </div>
      </form>
      {open && results && (results.parts.length > 0 || results.categories.length > 0 || results.brands.length > 0) && (
        // Single column on phones — 3 narrow columns crammed into a 250px
        // dropdown was unreadable.  Switch to side-by-side at sm+ where
        // the dropdown gets the full search bar width.
        <div className="absolute left-0 right-0 mt-1 bg-white border border-gray-200 rounded-md shadow-xl z-30 grid grid-cols-1 sm:grid-cols-3 gap-0 max-h-[80vh] sm:max-h-96 overflow-auto">
          {/* Parts */}
          <div className="border-b sm:border-b-0 sm:border-r p-2">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1 px-2">Parts</div>
            {results.parts.length === 0 ? <div className="text-xs text-gray-400 px-2 py-1">No matches</div> : (
              <div className="space-y-0.5 max-h-80 overflow-auto">
                {results.parts.map((p, i) => (
                  <button
                    key={p.id}
                    onClick={() => pickPart(p.sku)}
                    className={`w-full flex items-center gap-2 text-left px-2 py-1 rounded hover:bg-gray-100 ${highlight === i ? 'bg-gray-100' : ''}`}
                  >
                    {p.image_url ? (
                      <img src={p.image_url} alt="" className="w-8 h-8 object-contain bg-white border rounded" />
                    ) : (
                      <div className="w-8 h-8 bg-gray-100 border rounded" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="font-mono text-[10px] text-gray-500">{formatPartNumber(p.sku, p.brand)}</div>
                      <div className="text-xs text-gray-900 truncate">{p.name}</div>
                    </div>
                    {p.in_stock && <span className="text-[10px] text-green-700 font-semibold whitespace-nowrap">In stock</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
          {/* Categories */}
          <div className="border-b sm:border-b-0 sm:border-r p-2">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1 px-2">Categories</div>
            {results.categories.length === 0 ? <div className="text-xs text-gray-400 px-2 py-1">No matches</div> : (
              <div className="space-y-1">
                {/* Group results under their top-level department (the mega-menu
                    title) so a category reads "Van Equipment › Cargo Racks", not
                    a bare "Van Cargo Racks". The "Van " prefix is dropped from
                    van leaf names since the department header already says it. */}
                {(() => {
                  const groups = new Map<string, { name: string; path?: string; count: number }[]>()
                  for (const c of results.categories) {
                    const dept = c.path && c.path.includes('>') ? c.path.split('>')[0].trim() : 'Other'
                    if (!groups.has(dept)) groups.set(dept, [])
                    groups.get(dept)!.push(c)
                  }
                  return [...groups.entries()].map(([dept, items]) => (
                    <div key={dept}>
                      <div className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold px-2 pt-0.5">{dept}</div>
                      {items.map((c) => {
                        const leaf = dept === 'Van Equipment' ? c.name.replace(/^van\s+/i, '') : c.name
                        return (
                          <button
                            key={c.path || c.name}
                            onClick={() => pickCategory(c.name, c.path)}
                            title={c.path || c.name}
                            className="block w-full text-left text-xs text-red-700 hover:bg-gray-100 px-2 py-1 rounded"
                          >
                            {leaf}
                            {c.count > 0 && <span className="text-gray-400 ml-1">({c.count})</span>}
                          </button>
                        )
                      })}
                    </div>
                  ))
                })()}
              </div>
            )}
          </div>
          {/* Brands */}
          <div className="p-2">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1 px-2">Brands</div>
            {results.brands.length === 0 ? <div className="text-xs text-gray-400 px-2 py-1">No matches</div> : (
              <div className="space-y-0.5">
                {results.brands.map((b) => (
                  <button
                    key={b.name}
                    onClick={() => pickBrand(b.name)}
                    className="block w-full text-left text-xs text-red-700 hover:bg-gray-100 px-2 py-1 rounded"
                  >
                    {b.name}
                    {b.count > 0 && <span className="text-gray-400 ml-1">({b.count})</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
          {results.found > results.parts.length && (
            <div className="sm:col-span-3 px-3 py-2 border-t text-xs text-gray-600 bg-gray-50">
              Showing {results.parts.length} of {results.found.toLocaleString()} matches —{' '}
              <button onClick={submit as any} className="text-red-700 hover:underline">see all results →</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

type PopularVehicle = {
  family: string
  make: { slug: string; name: string }
  model: { slug: string; name: string }
  year: number
  base_vehicle_id: number
  label: string
}

type VehicleTypeTab = 'All' | 'Truck' | 'SUV' | 'Van'

function YmmModal({ onClose }: { onClose: () => void }) {
  const { setYmm } = useApp()
  const [years, setYears] = useState<number[]>([])
  const [makes, setMakes] = useState<YmmMake[]>([])
  const [models, setModels] = useState<YmmModel[]>([])
  const [year, setYear] = useState<number | ''>('')
  const [makeSlug, setMakeSlug] = useState<string>('')
  const [modelSlug, setModelSlug] = useState<string>('')
  const [busy, setBusy] = useState(false)
  // Three vehicle-class tabs (plus "All") down-select Make + Model and
  // surface a one-click rail of popular models for that class.
  const [vehicleType, setVehicleType] = useState<VehicleTypeTab>('All')
  const [popularTrucks, setPopularTrucks] = useState<PopularVehicle[]>([])
  const [popularSuvs, setPopularSuvs] = useState<PopularVehicle[]>([])
  const [popularVans, setPopularVans] = useState<PopularVehicle[]>([])

  useEffect(() => {
    fetch('/api/ymm/years').then((r) => r.json()).then(setYears)
    fetch('/api/ymm/popular-trucks').then((r) => r.json()).then(setPopularTrucks).catch(() => {})
    fetch('/api/ymm/popular-suvs').then((r) => r.json()).then(setPopularSuvs).catch(() => {})
    fetch('/api/ymm/popular-vans').then((r) => r.json()).then(setPopularVans).catch(() => {})
  }, [])

  const popularForActive = vehicleType === 'Truck' ? popularTrucks
    : vehicleType === 'SUV' ? popularSuvs
    : vehicleType === 'Van' ? popularVans
    : []

  // Refetch Makes whenever the type tab changes
  useEffect(() => {
    const url = vehicleType === 'All' ? '/api/ymm/makes' : `/api/ymm/makes?vehicle_type=${vehicleType}`
    fetch(url).then((r) => r.json()).then((ms: YmmMake[]) => {
      setMakes(ms)
      // If the previously-selected make is no longer in the filtered set, clear it
      if (makeSlug && !ms.find((m) => m.slug === makeSlug)) {
        setMakeSlug('')
        setModelSlug('')
      }
    })
  }, [vehicleType])

  useEffect(() => {
    if (!makeSlug) { setModels([]); return }
    const qs = new URLSearchParams()
    if (year) qs.set('year', String(year))
    if (vehicleType !== 'All') qs.set('vehicle_type', vehicleType)
    const url = `/api/ymm/makes/${encodeURIComponent(makeSlug)}/models${qs.toString() ? '?' + qs : ''}`
    fetch(url).then((r) => r.json()).then(setModels)
  }, [makeSlug, year, vehicleType])

  async function save() {
    if (!year || !makeSlug || !modelSlug) return
    setBusy(true)
    const r = await fetch(`/api/ymm/resolve?year=${year}&make_slug=${makeSlug}&model_slug=${modelSlug}`)
    setBusy(false)
    if (!r.ok) return
    const data = await r.json()
    setYmm({
      year: data.year,
      make_slug: data.make.slug, make_name: data.make.name,
      model_slug: data.model.slug, model_name: data.model.name,
      base_vehicle_id: data.base_vehicle_id,  // PACE fitment key for catalog filtering
    })
    onClose()
  }

  // One-click jump from any Popular-<class> tile straight to a resolved YMM.
  function pickPopular(v: PopularVehicle) {
    setYmm({
      year: v.year,
      make_slug: v.make.slug, make_name: v.make.name,
      model_slug: v.model.slug, model_name: v.model.name,
      base_vehicle_id: v.base_vehicle_id,
    })
    onClose()
  }

  const TYPE_TABS: { value: VehicleTypeTab; label: string }[] = [
    { value: 'All',   label: 'All vehicles' },
    { value: 'Truck', label: '🛻 Trucks' },
    { value: 'SUV',   label: '🚙 SUVs' },
    { value: 'Van',   label: '🚐 Vans' },
  ]

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-8 sm:pt-20 overflow-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg">
        <div className="p-5 border-b flex items-center justify-between">
          <h2 className="text-lg font-bold">Find parts for your vehicle</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        <div className="p-5 space-y-4">
          {/* Vehicle-class tabs — drops Makes + Models to that class's set */}
          <div className="flex gap-1 border-b border-gray-200 -mx-1 overflow-x-auto">
            {TYPE_TABS.map((t) => (
              <button
                key={t.value}
                onClick={() => setVehicleType(t.value)}
                className={`px-3 py-2 text-sm font-semibold border-b-2 -mb-px transition whitespace-nowrap ${
                  vehicleType === t.value
                    ? 'border-red-700 text-red-700'
                    : 'border-transparent text-gray-600 hover:text-gray-900'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Popular-<class> rail — shown when a specific class tab is active */}
          {vehicleType !== 'All' && popularForActive.length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
                Popular {vehicleType === 'Truck' ? 'trucks' : vehicleType === 'SUV' ? 'SUVs' : 'vans'} · one-click pick
              </div>
              <div className="grid grid-cols-2 gap-2 max-h-72 overflow-y-auto pr-1">
                {popularForActive.map((v) => (
                  <button
                    key={v.base_vehicle_id}
                    onClick={() => pickPopular(v)}
                    className="text-left px-3 py-2 border border-gray-200 rounded hover:border-red-700 hover:bg-red-50 transition"
                  >
                    <div className="text-sm font-semibold text-gray-900 truncate">{v.family}</div>
                    <div className="text-[11px] text-gray-500 truncate">{v.label}</div>
                  </button>
                ))}
              </div>
              <div className="text-xs text-gray-500 mt-3 mb-2 text-center">— or pick year/make/model below —</div>
            </div>
          )}

          {vehicleType === 'All' && (
            <p className="text-sm text-gray-600">Set your year, make, and model so we can highlight compatible parts. Saved to this device.</p>
          )}
          <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold">
            Year
            <select value={year} onChange={(e) => { setYear(e.target.value ? parseInt(e.target.value) : ''); setModelSlug('') }}
                    className="mt-1 block w-full border rounded px-3 py-2 normal-case font-normal text-sm text-gray-900">
              <option value="">Select year…</option>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold">
            Make
            <select value={makeSlug} onChange={(e) => { setMakeSlug(e.target.value); setModelSlug('') }}
                    className="mt-1 block w-full border rounded px-3 py-2 normal-case font-normal text-sm text-gray-900">
              <option value="">Select make…</option>
              {makes.filter((m) => m.is_featured).length > 0 && (
                <optgroup label="Featured">
                  {makes.filter((m) => m.is_featured).map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
                </optgroup>
              )}
              <optgroup label="All makes">
                {makes.filter((m) => !m.is_featured).map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
              </optgroup>
            </select>
          </label>
          <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold">
            Model
            <select value={modelSlug} onChange={(e) => setModelSlug(e.target.value)}
                    disabled={!makeSlug || models.length === 0}
                    className="mt-1 block w-full border rounded px-3 py-2 normal-case font-normal text-sm text-gray-900 disabled:bg-gray-100 disabled:text-gray-400">
              <option value="">{makeSlug ? (models.length ? 'Select model…' : 'No models for this year') : 'Pick a make first'}</option>
              {models.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}
            </select>
          </label>
          <button
            onClick={save}
            disabled={!year || !makeSlug || !modelSlug || busy}
            className="w-full py-2.5 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Set my vehicle'}
          </button>
        </div>
      </div>
    </div>
  )
}

function QuickOrderModal({ onClose }: { onClose: () => void }) {
  const { addToCart } = useApp()
  const [rows, setRows] = useState<{ sku: string; qty: string }[]>(
    Array.from({ length: 5 }, () => ({ sku: '', qty: '1' }))
  )
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<{ sku: string; status: string; message?: string }[]>([])

  function setRow(i: number, field: 'sku' | 'qty', v: string) {
    setRows((r) => r.map((row, j) => j === i ? { ...row, [field]: v } : row))
  }
  function addRow() { setRows((r) => [...r, { sku: '', qty: '1' }]) }

  async function submit() {
    setBusy(true)
    setResults([])
    const out: { sku: string; status: string; message?: string }[] = []
    for (const row of rows) {
      const sku = row.sku.trim()
      const qty = parseInt(row.qty, 10) || 0
      if (!sku || qty <= 0) continue
      try {
        const r = await fetch('/api/cart/lines', {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sku, quantity: qty }),
        })
        if (r.ok) {
          out.push({ sku, status: 'ok' })
          // Refresh cart globally — easiest is just trigger a reload through addToCart helper
          await addToCart(sku, 0).catch(() => {}) // 0 is invalid; just to force a cart refresh
        } else {
          const body = await r.json().catch(() => ({}))
          out.push({ sku, status: 'fail', message: body.detail || `HTTP ${r.status}` })
        }
      } catch (e: any) {
        out.push({ sku, status: 'fail', message: e?.message || 'network error' })
      }
    }
    setResults(out)
    setBusy(false)
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-8 sm:pt-16 overflow-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl">
        <div className="p-5 border-b flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">Quick Order</h2>
            <p className="text-xs text-gray-500 mt-0.5">Paste your part numbers and quantities. Hits the catalog directly — no browsing.</p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        <div className="p-5">
          <table className="w-full text-sm">
            <thead className="text-xs uppercase tracking-wider text-gray-500">
              <tr>
                <th className="text-left pb-2 w-2/3">SKU / Part #</th>
                <th className="text-left pb-2 w-1/4">Qty</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const result = results.find((x) => x.sku === r.sku.trim())
                return (
                  <tr key={i} className="border-t">
                    <td className="py-1.5">
                      <input value={r.sku} onChange={(e) => setRow(i, 'sku', e.target.value)} placeholder="e.g. BUYB1237PPB"
                             className="w-full border rounded px-2 py-1.5 font-mono text-sm" />
                    </td>
                    <td className="py-1.5">
                      <input type="number" min={1} max={999} value={r.qty} onChange={(e) => setRow(i, 'qty', e.target.value)}
                             className="w-20 border rounded px-2 py-1.5 text-sm" />
                    </td>
                    <td className="py-1.5 pl-2 w-32">
                      {result?.status === 'ok' && <span className="text-xs text-green-700 font-semibold">✓ Added</span>}
                      {result?.status === 'fail' && <span className="text-xs text-red-700">✗ {result.message}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <button onClick={addRow} className="mt-3 text-sm text-red-700 hover:underline">+ Add another row</button>
          <div className="mt-5 flex items-center justify-end gap-3">
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-700 hover:text-gray-900">Close</button>
            <button onClick={submit} disabled={busy} className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50">
              {busy ? 'Adding…' : 'Add to cart'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// Admin "Shop as Customer" picker. Reuses /api/admin/customers/search and the
// context start/exit helpers so admins never have to leave the storefront.
function ImpersonationModal({ onClose }: { onClose: () => void }) {
  const { startImpersonation, exitImpersonation, impersonation } = useApp()
  const [q, setQ] = useState('')
  const [results, setResults] = useState<CustomerSearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const timer = useRef<number | null>(null)

  async function search(query: string) {
    setSearching(true); setError(null)
    try {
      const r = await fetch('/api/admin/customers/search?q=' + encodeURIComponent(query) + '&limit=50', { credentials: 'include' })
      if (!r.ok) throw new Error(r.status === 403 ? 'Admin role required' : `Search failed (HTTP ${r.status})`)
      setResults(await r.json())
    } catch (e: any) {
      setError(e?.message || 'Search failed'); setResults([])
    } finally {
      setSearching(false)
    }
  }

  useEffect(() => { search('') }, [])

  function onInput(v: string) {
    setQ(v)
    if (timer.current) window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => search(v), 250)
  }

  async function pick(id: number) {
    setBusyId(id); setError(null)
    try {
      await startImpersonation(id)  // reloads the page on success
    } catch (e: any) {
      setError(e?.message || 'Could not start impersonation'); setBusyId(null)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-8 sm:pt-16 overflow-auto"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="p-5 border-b flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold">Shop as Customer</h2>
            <p className="text-xs text-gray-500 mt-0.5">Search a Nelson customer to act on their behalf — placing an order or filing an RMA over the phone. Carts and orders are tagged with your user id for audit.</p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none">×</button>
        </div>

        {impersonation?.impersonating && (
          <div className="px-5 pt-4">
            <div className="flex items-center gap-3 bg-amber-50 border border-amber-300 rounded px-3 py-2 text-sm">
              <span className="text-amber-900">Currently shopping as <strong>{impersonation.customer_name}</strong> <span className="font-mono opacity-70">(#{impersonation.customer_number})</span></span>
              <button onClick={exitImpersonation} className="ml-auto text-amber-800 text-xs font-semibold hover:underline">Exit impersonation</button>
            </div>
          </div>
        )}

        <div className="p-5">
          <input
            autoFocus
            type="search"
            value={q}
            onChange={(e) => onInput(e.target.value)}
            placeholder="Search by customer #, name, or city…"
            className="w-full border rounded px-3 py-2 text-sm"
          />
          {error && <div className="text-red-700 text-sm mt-2">{error}</div>}

          <div className="mt-3 max-h-[50vh] overflow-auto flex flex-col gap-1.5">
            {searching && <div className="text-center text-gray-500 text-sm py-6">Searching…</div>}
            {!searching && results.length === 0 && (
              <div className="text-center text-gray-500 text-sm py-6">
                {q.trim() ? `No matches for "${q}".` : 'Start typing to find a customer.'}
              </div>
            )}
            {results.map((hit) => (
              <div key={hit.id} className="border rounded px-3 py-2.5 grid grid-cols-[90px_1fr_auto] gap-3 items-center hover:border-gray-400">
                <div className="font-mono font-bold text-gray-900 text-sm">{hit.customer_number}</div>
                <div>
                  <div>
                    <span className="font-semibold text-gray-900 text-sm">{hit.name}</span>
                    <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase bg-gray-100 text-gray-600">{hit.tier}</span>
                  </div>
                  <div className="text-gray-500 text-xs mt-0.5">
                    {hit.default_ship_to ? `→ ${hit.default_ship_to}` : '(no default ship-to on file)'}
                  </div>
                </div>
                <button
                  onClick={() => pick(hit.id)}
                  disabled={busyId !== null}
                  className="px-3 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded disabled:opacity-50"
                >
                  {busyId === hit.id ? 'Loading…' : 'Shop as →'}
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// Admin-only alert: how many issue reports are still unresolved (open +
// in_progress). Polls /api/error-reports/stats and shows a red count badge in
// the header so Ben sees new problems the moment he's logged in. Clicking it
// pops the Issue Recorder straight to its Reports queue (via a window event the
// ErrorReporter listens for). Refreshes on a 60s poll, on tab focus, and when a
// new report is filed (titan:reports-changed).
function AdminIssuesBadge() {
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/error-reports/stats', { credentials: 'include' })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (alive && d) setCount(d.unresolved || 0) })
        .catch(() => {})
    }
    load()
    const timer = window.setInterval(load, 60000)
    const onFocus = () => load()
    window.addEventListener('focus', onFocus)
    window.addEventListener('titan:reports-changed', load)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('titan:reports-changed', load)
    }
  }, [])
  const n = count ?? 0
  return (
    <button
      onClick={() => window.dispatchEvent(new CustomEvent('titan:open-reports'))}
      className={`relative flex items-center gap-1 hover:text-white ${n > 0 ? 'text-amber-300 font-semibold' : ''}`}
      title={n > 0 ? `${n} unresolved issue${n === 1 ? '' : 's'} — click to review` : 'No open issues'}
    >
      <span className="text-sm leading-none">&#9888;</span>
      <span className="hidden sm:inline">Issues</span>
      {n > 0 && (
        <span className="absolute -top-2 -right-2 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
          {n > 99 ? '99+' : n}
        </span>
      )}
    </button>
  )
}

// Admin "Alerts" badge — open admin_message count (kit conflicts + system
// warnings). Links to the message board. Refreshes on titan:alerts-changed.
function AdminAlertsBadge() {
  const [count, setCount] = useState<number | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => {
      fetch('/api/admin/messages/stats', { credentials: 'include' })
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => { if (alive && d) setCount(d.open || 0) })
        .catch(() => {})
    }
    load()
    const timer = window.setInterval(load, 60000)
    const onFocus = () => load()
    window.addEventListener('focus', onFocus)
    window.addEventListener('titan:alerts-changed', load)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('titan:alerts-changed', load)
    }
  }, [])
  const n = count ?? 0
  return (
    <Link
      to="/admin/messages"
      className={`relative flex items-center gap-1 hover:text-white ${n > 0 ? 'text-amber-300 font-semibold' : ''}`}
      title={n > 0 ? `${n} open alert${n === 1 ? '' : 's'} — open the message board` : 'No open alerts'}
    >
      <span className="text-sm leading-none">&#128226;</span>
      <span className="hidden sm:inline">Alerts</span>
      {n > 0 && (
        <span className="absolute -top-2 -right-2 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
          {n > 99 ? '99+' : n}
        </span>
      )}
    </Link>
  )
}

// Password-gated exit from a locked Showroom kiosk. Verifies the CURRENT
// session's account password (the jobber's, or the admin's when admin-armed)
// via POST /api/auth/verify-password before unlocking.
function ShowroomExitModal({ onClose, onExit }: { onClose: () => void; onExit: () => void }) {
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      const r = await fetch('/api/auth/verify-password', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: pw }),
      })
      if (r.status === 403) { setErr('Incorrect password'); return }
      if (!r.ok) { setErr(`Error (${r.status})`); return }
      onExit()
    } catch { setErr('Network error') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1 text-lg font-bold text-gray-900">Exit Showroom Mode</h2>
        <p className="mb-3 text-sm text-gray-600">Staff only. Enter your account password to leave the customer-facing view.</p>
        <form onSubmit={submit}>
          <input
            type="password" autoFocus value={pw} onChange={(e) => setPw(e.target.value)}
            placeholder="Account password"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
          {err && <div className="mt-2 text-sm font-semibold text-red-600">{err}</div>}
          <div className="mt-4 flex gap-2">
            <button type="submit" disabled={busy || !pw} className="flex-1 rounded bg-red-700 py-2 text-sm font-bold text-white hover:bg-red-800 disabled:bg-gray-400">{busy ? 'Checking…' : 'Exit Showroom'}</button>
            <button type="button" onClick={onClose} className="rounded border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">Cancel</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Header() {
  const { user, cart, frontCounter, setFrontCounter, showroom, setShowroom, setQuickOrderOpen, ymmOpen, setYmmOpen, logout, impersonation, setImpersonateOpen, exitImpersonation } = useApp()
  // Quick Order + Front Counter are B2B-only (jobber/dealer). Hidden for retail
  // (B2C) and anonymous shoppers, and for an admin who isn't impersonating a B2B
  // customer (their effective tier resolves to none). Report #11: Quick Order was
  // showing to everyone.
  const isB2B = user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer'
  const showFrontCounter = isB2B
  const isAdmin = user?.role === 'admin'
  const shoppingAs = isAdmin && impersonation?.impersonating ? impersonation : null
  // Retail Showroom Mode is only live for a B2B (jobber/dealer) session — the
  // per-device flag is meaningless without an effective B2B customer behind it.
  const showroomActive = showroom && isB2B
  const [showroomExitOpen, setShowroomExitOpen] = useState(false)
  const navigate = useNavigate()
  return (
    <header className="bg-white border-b shadow-sm sticky top-0 z-20">
      {/* Top utility bar — in Showroom Mode it collapses to a minimal bar with a
          password-gated staff exit so a walk-in never sees back-office chrome. */}
      {showroomActive ? (
        <div className="bg-gray-900 text-gray-300 text-xs">
          <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-1.5 flex items-center gap-3">
            <span className="font-semibold text-gray-200">{user?.showroom_display_name || user?.customer_name || 'Online Catalog'}</span>
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={toggleFullscreen}
                className="rounded bg-gray-700 px-2 py-0.5 text-[11px] font-semibold text-gray-200 hover:bg-gray-600"
                title="Toggle fullscreen (hides the browser address bar)"
              >
                ⛶ Fullscreen
              </button>
              <button
                onClick={() => { if (isAdmin) { exitFullscreen(); setShowroom(false) } else { setShowroomExitOpen(true) } }}
                className="rounded bg-gray-700 px-2 py-0.5 text-[11px] font-semibold text-gray-200 hover:bg-gray-600"
                title={isAdmin ? 'Exit Showroom Mode' : 'Staff only — exit Showroom Mode (password required)'}
              >
                {isAdmin ? 'Exit showroom' : '🔒 Staff exit'}
              </button>
            </div>
          </div>
        </div>
      ) : (
      <div className="bg-gray-900 text-gray-300 text-xs">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-1.5 flex items-center gap-3">
          <div className="hidden sm:flex gap-3 items-center">
            <span className="text-emerald-400 font-semibold">✓ In stock now — pick it up today</span>
            <span className="text-gray-600">·</span>
            <span>Portland 503.548.9300</span>
            <span className="text-gray-600">·</span>
            <span>Kent 253.395.3825</span>
          </div>
          {/* Shop-as-Customer chip (admin only, when impersonating) — tucked
              between the Kent phone and the account link, sized to sit inside
              the navy bar without making it any taller. */}
          {shoppingAs && (
            <div
              className="flex items-center gap-1.5 rounded bg-amber-400 px-2 py-0.5 leading-none text-amber-950"
              title="Cart, checkout & RMA actions route to this customer. Orders record you as the staff actor."
            >
              <span className="text-[10px] font-bold uppercase tracking-wide">Shopping as</span>
              <span className="whitespace-nowrap text-[11px] font-semibold">
                {shoppingAs.customer_name}
                <span className="ml-1 font-mono opacity-70">#{shoppingAs.customer_number}</span>
              </span>
              {(shoppingAs.tier === 'jobber' || shoppingAs.tier === 'dealer') && (
                <button
                  onClick={() => { enterFullscreen(); setShowroom(true); navigate('/') }}
                  className="rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 hover:bg-emerald-50"
                  title="Open this customer's white-label Showroom view"
                >
                  ▶ Showroom
                </button>
              )}
              <button
                onClick={exitImpersonation}
                className="rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-amber-900 hover:bg-amber-50"
                title="Exit impersonation"
              >
                Exit
              </button>
            </div>
          )}
          <div className="flex items-center gap-3 ml-auto">
            {user ? (
              <>
                {isAdmin && <AdminIssuesBadge />}
                {isAdmin && <AdminAlertsBadge />}
                <Link to="/account" className="hover:text-white">
                  {user.display_name || user.email}
                  {user.customer_tier && (
                    <span className="ml-2 px-1.5 py-0.5 bg-blue-700 text-white rounded text-[10px] uppercase">
                      {user.customer_tier}
                    </span>
                  )}
                </Link>
                <Link to="/orders" className="hover:text-white">Orders</Link>
                {isAdmin && (
                  <button
                    onClick={() => setImpersonateOpen(true)}
                    className={`hover:text-white ${shoppingAs ? 'text-amber-300 font-semibold' : ''}`}
                    title="Search a customer and act on their behalf"
                  >
                    {shoppingAs ? '↺ Switch customer' : 'Shop as Customer'}
                  </button>
                )}
                <button onClick={logout} className="hover:text-white">Log out</button>
              </>
            ) : (
              <>
                <Link to="/login" className="hover:text-white">Log in</Link>
                <Link to="/signup" className="hover:text-white">Open an account</Link>
              </>
            )}
          </div>
        </div>
      </div>
      )}
      {/* Main bar: logo + search + cart */}
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center gap-3 md:gap-6">
        <Link to="/" className="flex-shrink-0">
          {showroomActive ? (
            user?.showroom_logo_url
              ? <img src={user.showroom_logo_url} alt={user.showroom_display_name || 'Online Catalog'} className="h-10 md:h-14 w-auto max-w-[220px] object-contain" />
              : <span className="text-xl md:text-2xl font-extrabold tracking-tight text-gray-900">{user?.showroom_display_name || 'Online Catalog'}</span>
          ) : (
            <span className="flex items-center gap-2.5">
              <img src="/brand/nelson-badge.png" alt="" className="h-11 md:h-14 w-auto" />
              <img src="/brand/nelson-wordmark.png" alt="Nelson Truck Equipment" className="h-6 md:h-8 w-auto" />
            </span>
          )}
        </Link>
        <HeaderSearchBar />
        <div className="flex items-center gap-2 text-sm">
          {/* Quick Order + Cost/Counter toggle are back-office controls — hidden in
              Showroom Mode (pricing is auto retail-facing there). */}
          {isB2B && !showroomActive && (
            <button
              onClick={() => setQuickOrderOpen(true)}
              className="hidden md:flex px-3 py-2 bg-yellow-400 hover:bg-yellow-300 text-gray-900 text-xs font-bold uppercase tracking-wide rounded shadow-sm items-center gap-1"
              title="Quickly add multiple SKUs to your cart"
            >
              ⚡ Quick Order
            </button>
          )}
          {showFrontCounter && !showroomActive && (
            <button
              onClick={() => setFrontCounter(!frontCounter)}
              title="Switch between Your Cost view (back office) and Front Counter (retail-facing) view"
              className={`px-3 py-2 rounded text-xs font-semibold uppercase tracking-wide transition ${
                frontCounter ? 'bg-orange-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
            >
              {frontCounter ? '🛍️ Counter' : '🔧 Cost'}
            </button>
          )}
          {showroomActive && (
            <Link to="/showroom/receipts" className="px-2 py-2 text-xs font-semibold text-gray-600 hover:text-red-700 whitespace-nowrap" title="Customer receipts">
              🧾 Receipts
            </Link>
          )}
          <Link to="/cart" className="relative px-4 py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded">
            🛒 Cart
            {cart && cart.item_count > 0 && (
              <span className="absolute -top-2 -right-2 w-5 h-5 bg-yellow-400 text-gray-900 text-xs font-bold rounded-full flex items-center justify-center">{cart.item_count}</span>
            )}
          </Link>
        </div>
      </div>
      {/* Vehicle selector moved into the category nav as "Shop your vehicle". */}
      {ymmOpen && <YmmModal onClose={() => setYmmOpen(false)} />}
      {showroomExitOpen && (
        <ShowroomExitModal onClose={() => setShowroomExitOpen(false)} onExit={() => { exitFullscreen(); setShowroom(false); setShowroomExitOpen(false) }} />
      )}
      {/* Category nav strip */}
      <CategoryNavStrip />
    </header>
  )
}

// 4 macro-sections curated to match the existing nelsontruck.com megamenu.
// Each entry's `category_top` or `category_path` resolves a node in the loaded
// category tree at render time. Sub-sections without a tree match are still
// listed but become a flat link with no leaf list.
type MegaSubSection = {
  name: string
  category_top?: string
  category_path?: string
  route?: string  // direct route override (e.g. /snow-plows)
  // Van-exclusive categories (e.g. Van Packages) don't need the truck-bleed
  // vehicle_type=Van filter; skipping it keeps the category-navigation sidebar
  // (with the trade subcategory tiles) instead of swapping to the vehicle
  // picker — matches the search/landing page layout.
  skip_vehicle_filter?: boolean
}
type MegaSection = {
  label: string
  slug: string
  sub_sections: MegaSubSection[]
  // Where the "View All <Label>" header link goes. Defaults to
  // /catalog?category_top=<label> which now resolves to a real parent
  // category after the 2026-05-10 re-parenting migration (Truck
  // Accessories, Truck Equipment, Trailer & RV, Van Equipment are now
  // real DB cats parenting the existing top-levels).
  view_all_route?: string
}
// Nelson divisions. Sub-sections resolve against the loaded category tree where
// real catalog data exists (Snow & Ice, Bodies, Aerial, Liftgates, Accessories);
// the heavy divisions still being sourced (Tow Trucks, Trailers, Metal & Hardware)
// use `route` links so they always render — swap to real category paths / landing
// pages as their product data lands.
const MEGA_SECTIONS: MegaSection[] = [
  {
    label: "Snow & Ice",
    slug: "snow-ice",
    view_all_route: "/snow-plows",
    sub_sections: [
      { name: "Snow Plows", category_path: "Truck Equipment > Snow Plows" },
      { name: "Find My Plow (Wizard)", route: "/snow-plows" },
      { name: "Salt Spreaders & Hoppers", category_path: "Truck Equipment > Salt Spreaders and Hoppers" },
      { name: "Plow Parts & Hydraulics", category_path: "Truck Equipment > Hydraulic Pump Kits" },
    ],
  },
  {
    label: "Truck Bodies",
    slug: "truck-bodies",
    sub_sections: [
      { name: "All Truck Bodies", category_path: "Truck Equipment > Truck Bodies" },
      { name: "Service / Utility Bodies", category_path: "Truck Equipment > Truck Bodies > Service / Utility Bodies" },
      { name: "Dump Bodies", category_path: "Truck Equipment > Truck Bodies > Dump Bodies" },
      { name: "Flatbeds", category_path: "Truck Equipment > Truck Bodies > Flatbeds" },
      { name: "Stake Bodies", category_path: "Truck Equipment > Truck Bodies > Stake Bodies" },
      { name: "Van / Box Bodies", category_path: "Truck Equipment > Truck Bodies > Van / Box Bodies" },
      { name: "Dump Beds & Hoists", category_path: "Utility Truck Equipment > Truck Dump Beds and Accessories" },
    ],
  },
  {
    label: "Tow Trucks",
    slug: "tow-trucks",
    view_all_route: "/catalog",
    sub_sections: [
      { name: "Wreckers", route: "/catalog" },
      { name: "Rollbacks & Carriers", route: "/catalog" },
      { name: "Rotators", route: "/catalog" },
      { name: "Wheel Lifts", route: "/catalog" },
      { name: "Recovery Equipment", route: "/catalog" },
      { name: "Tow Truck Parts", route: "/catalog" },
    ],
  },
  {
    label: "Aerial & Bucket",
    slug: "aerial-bucket",
    view_all_route: "/aerial-lifts",
    sub_sections: [
      { name: "Bucket Trucks", route: "/aerial-lifts" },
      { name: "Aerial Lifts", route: "/aerial-lifts" },
      { name: "Digger Derricks", route: "/aerial-lifts" },
      { name: "Parts & Service", route: "/aerial-lifts" },
    ],
  },
  {
    label: "Trailers",
    slug: "trailers",
    view_all_route: "/catalog",
    sub_sections: [
      { name: "Landoll Traveling Axle", route: "/catalog" },
      { name: "Detach Gooseneck", route: "/catalog" },
      { name: "Sliding Axle", route: "/catalog" },
      { name: "Trailer Parts", route: "/catalog" },
      { name: "Landoll Parts", route: "/catalog" },
    ],
  },
  {
    label: "Liftgates & Cranes",
    slug: "liftgates-cranes",
    sub_sections: [
      { name: "Truck Lift Gates", category_path: "Utility Truck Equipment > Truck Lift Gates and Accessories" },
      { name: "Winches", category_top: "Winches and Accessories" },
      { name: "Hydraulic Components", category_path: "Utility Truck Equipment > Hydraulic Valves" },
      { name: "Tarp Systems", category_path: "Utility Truck Equipment > Pull Tarp Systems and Accessories" },
      { name: "Van Shelving & Upfit", category_path: "Van Equipment > Van Shelving" },
    ],
  },
  {
    label: "Accessories",
    slug: "accessories",
    view_all_route: "/catalog?category_top=Truck+Accessories",
    sub_sections: [
      { name: "Tonneau & Bed Covers", category_top: "Truck Bed Covers" },
      { name: "Bed Liners & Tailgate", category_top: "Truck Bed and Tailgate" },
      { name: "Running Boards & Steps", category_top: "Running Boards and Steps" },
      { name: "Floor Liners & Interior", category_top: "Interior" },
      { name: "Grille Guards & Bumpers", category_top: "Bumpers and Grille Guards" },
      { name: "Lighting & Electrical", category_top: "Automotive Lighting" },
      { name: "Toolboxes & Cargo", category_top: "Cargo Management" },
      { name: "Towing & Hitches", category_top: "Towing and Accessories" },
      { name: "Wheels & Tires", category_top: "Wheels and Tires" },
      { name: "Exterior Accessories", category_top: "Exterior" },
    ],
  },
  {
    label: "Metal & Hardware",
    slug: "metal-hardware",
    view_all_route: "/catalog",
    sub_sections: [
      { name: "Steel Stock (per lb)", route: "/catalog" },
      { name: "Aluminum Stock (per lb)", route: "/catalog" },
      { name: "Bar · Tube · Angle", route: "/catalog" },
      { name: "Plate & Sheet", route: "/catalog" },
      { name: "Nuts, Bolts & Fasteners", route: "/catalog" },
      { name: "Cut-to-Size Service", route: "/catalog" },
    ],
  },
]

function findCategoryByName(nodes: CategoryNode[], name: string): CategoryNode | null {
  for (const n of nodes) {
    if (n.name === name) return n
    const hit = findCategoryByName(n.children, name)
    if (hit) return hit
  }
  return null
}

function resolveSubSection(s: MegaSubSection, tree: CategoryNode[]): CategoryNode | null {
  if (s.category_path) return findCategoryByPath(tree, s.category_path)
  if (s.category_top) {
    // Walk the whole tree by name — after the 2026-05-10 re-parenting,
    // "Exterior" lives under "Truck Accessories" so a simple
    // tree.find at depth=0 misses it.
    return findCategoryByName(tree, s.category_top)
  }
  return null
}

function subSectionLink(s: MegaSubSection, sectionLabel?: string): string {
  if (s.route) return s.route
  // Van Equipment subcategories live under Cargo Management but should only
  // show van-fitting + universal products. Append vehicle_type=Van so the
  // backend filters out the F-150 / Tacoma / Wrangler bleed — except for
  // van-exclusive categories (skip_vehicle_filter), which keep the category
  // navigation sidebar instead of the vehicle picker.
  const vt = (sectionLabel === 'Van Equipment' && !s.skip_vehicle_filter) ? '&vehicle_type=Van' : ''
  // Include category_top alongside category_path (the parent department, the
  // path's first segment) so the landing page renders the category-navigation
  // sidebar + subcategory tiles + "Category: X" chip — same as a search-result
  // or home-page category click (homeCatPath). Without it the sidebar collapses
  // to just the leaf and the subcategory tiles disappear.
  if (s.category_path) {
    const top = s.category_path.split('>')[0].trim()
    return `/catalog?category_top=${encodeURIComponent(top)}&category_path=${encodeURIComponent(s.category_path)}${vt}`
  }
  if (s.category_top) return `/catalog?category_top=${encodeURIComponent(s.category_top)}${vt}`
  return "/catalog"
}

function MegaPanel({
  section,
  tree,
  onClose,
  anchorLeft,
}: {
  section: MegaSection
  tree: CategoryNode[]
  onClose: () => void
  anchorLeft: number
}) {
  // Position the dropdown box's left edge under the hovered tab (anchorLeft,
  // measured by CategoryNavStrip), but clamp so it never runs off the right edge.
  const boxRef = useRef<HTMLDivElement>(null)
  const [left, setLeft] = useState(anchorLeft)
  useLayoutEffect(() => {
    const box = boxRef.current
    const container = box?.parentElement  // the absolute left-0/right-0 wrapper = nav width
    if (!box || !container) { setLeft(anchorLeft); return }
    const clamped = Math.max(8, Math.min(anchorLeft, container.offsetWidth - box.offsetWidth - 8))
    setLeft(clamped)
  }, [anchorLeft, section])
  // Pre-resolve every sub-section once. Drop any sub_section that the API
  // pruned (no products in that category). Direct-route subsections like
  // "/snow-plows" always pass through since they don't depend on the tree.
  const allResolved = section.sub_sections.map((s) => ({
    sub: s,
    node: resolveSubSection(s, tree),
  }))
  const liveItems = allResolved.filter(({ sub, node }) => {
    if (sub.route) return true  // direct route (e.g. /snow-plows) always shown
    return node !== null && (node.product_count || 0) > 0
  })
  // Nothing selected until the user hovers a left-column category — the right
  // rail stays blank (with a prompt) until then, rather than auto-showing the
  // first category's subcategories.
  return (
    <div className="absolute left-0 right-0 top-full z-30">
      {/* The dropdown box is anchored under the hovered tab (left, clamped to stay
          on-screen) so it lines up with its parent tab instead of always sitting
          under the logo. data-mega-keep keeps the menu open while hovering it. */}
        <div data-mega-keep ref={boxRef} style={{ marginLeft: left }} className="inline-block max-w-[calc(100%-16px)] rounded-b-lg border border-t-0 border-gray-200 bg-white px-6 py-4 shadow-xl">
          <Link
            to={section.view_all_route || `/catalog?category_top=${encodeURIComponent(section.label)}`}
            onClick={onClose}
            className="mb-2 inline-block text-xs font-bold uppercase tracking-wider text-gray-500 hover:text-red-700"
          >
            View All <span className="text-gray-700">{section.label}</span> »
          </Link>
          {liveItems.length === 0 ? (
            <div className="py-3 text-sm italic text-gray-500">Coming soon — feeds being ingested.</div>
          ) : (
            <div className="grid grid-cols-[repeat(2,max-content)] gap-x-10 gap-y-0.5 sm:grid-cols-[repeat(3,max-content)] lg:grid-cols-[repeat(4,max-content)]">
              {liveItems.map(({ sub: s }, i) => (
                <Link
                  key={i}
                  to={subSectionLink(s, section.label)}
                  onClick={onClose}
                  className="block rounded px-2 py-1.5 text-sm text-gray-800 transition hover:bg-gray-50 hover:text-red-700"
                >
                  {s.name}
                </Link>
              ))}
            </div>
          )}
        </div>
    </div>
  )
}

// Shared category-tree loader. Three components need the tree (nav strip,
// catalog sidebar, catalog browse). Previously each kept its own cache (or none),
// so the tree was fetched up to 3x per page — and React StrictMode double-invokes
// effects in dev, doubling that again. This dedupes to a single in-flight request:
// every caller awaits the same promise, and the resolved value is reused for the
// rest of the session. On failure the promise is cleared so a later mount retries.
let _categoryTree: CategoryNode[] | null = null
let _categoryTreePromise: Promise<CategoryNode[]> | null = null
function loadCategoryTree(): Promise<CategoryNode[]> {
  if (_categoryTree) return Promise.resolve(_categoryTree)
  if (!_categoryTreePromise) {
    _categoryTreePromise = fetch('/api/catalog/categories/tree')
      .then((r) => r.json())
      .then((t: CategoryNode[]) => { _categoryTree = t; return t })
      .catch((e) => { _categoryTreePromise = null; throw e })
  }
  return _categoryTreePromise
}

function CategoryNavStrip() {
  const { ymm, setYmm, setYmmOpen, user, showroom } = useApp()
  const showroomActive = showroom && (user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer')
  const [tree, setTree] = useState<CategoryNode[]>(_categoryTree || [])
  const [openSection, setOpenSection] = useState<number | null>(null)
  const navRef = useRef<HTMLElement>(null)
  const tabRefs = useRef<(HTMLDivElement | null)[]>([])
  const [anchorLeft, setAnchorLeft] = useState(0)
  // hover-intent: only open after the cursor DWELLS on a tab for a beat, and
  // only on real mouse devices. This kills the "menu flies open every time the
  // cursor crosses the nav on its way to the search results" annoyance — a
  // deliberate drag passes a tab in <<200ms and never triggers. Touch devices
  // (no real hover) ignore this entirely and use tap-to-toggle below.
  const hoverTimer = useRef<number | null>(null)
  const closeTimer = useRef<number | null>(null)
  const showroomStripRef = useRef<HTMLDivElement>(null)
  const canHover = typeof window !== 'undefined' &&
    window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const HOVER_OPEN_MS = 320  // require a deliberate dwell so it doesn't pop open while navigating past
  const HOVER_CLOSE_MS = 120  // grace period to cross the tab→panel gap

  function cancelHoverOpen() {
    if (hoverTimer.current) { window.clearTimeout(hoverTimer.current); hoverTimer.current = null }
  }
  function cancelClose() {
    if (closeTimer.current) { window.clearTimeout(closeTimer.current); closeTimer.current = null }
  }
  function scheduleOpen(i: number) {
    if (!canHover) return                 // touch/coarse pointer → tap only
    if (_searchDropdownOpen) return       // don't fight the search results
    cancelHoverOpen()
    cancelClose()                         // moving onto a tab cancels any pending close
    // If a panel is already open, switch sections immediately (expected nav feel);
    // otherwise require dwell so a pass-through doesn't pop it open.
    if (openSection !== null) { setOpenSection(i); return }
    hoverTimer.current = window.setTimeout(() => {
      if (!_searchDropdownOpen) setOpenSection(i)
    }, HOVER_OPEN_MS)
  }
  // Leaving a tab sideways stays INSIDE <nav> (full-width strip), so the nav's
  // own onMouseLeave never fires. Schedule a close on tab-leave; entering an
  // adjacent tab or the panel cancels it. This closes the menu when the cursor
  // moves left of the first tab / right past the last tab, while tolerating the
  // 1px gap between the tab row and the panel below it.
  function scheduleClose() {
    if (!canHover) return
    cancelHoverOpen()
    cancelClose()
    closeTimer.current = window.setTimeout(() => setOpenSection(null), HOVER_CLOSE_MS)
  }
  useEffect(() => () => { cancelHoverOpen(); cancelClose() }, [])
  // Measure the open tab's left offset (relative to the nav) so the dropdown
  // anchors under its parent tab rather than under the logo.
  useLayoutEffect(() => {
    if (openSection === null) return
    const nav = navRef.current
    const tab = tabRefs.current[openSection]
    if (!nav || !tab) return
    setAnchorLeft(Math.max(8, tab.getBoundingClientRect().left - nav.getBoundingClientRect().left))
  }, [openSection])

  // Load the category tree, RETRYING on transient failure. Previously a single
  // failed fetch (backend restart on deploy, DB/Typesense blip, network stutter)
  // left tree=[] forever and silently wiped the whole nav until a manual reload.
  // Now we retry with backoff so the menu self-heals.
  useEffect(() => {
    if (_categoryTree) { setTree(_categoryTree); return }
    let cancelled = false
    let attempt = 0
    const tryLoad = () => {
      loadCategoryTree()
        .then((t) => { if (!cancelled) setTree(t) })
        .catch(() => {
          if (cancelled) return
          if (attempt++ < 4) {
            // loadCategoryTree() already clears its cached promise on failure,
            // so each retry issues a fresh fetch. Backoff: 2s, 4s, 8s, 8s.
            window.setTimeout(tryLoad, Math.min(1000 * 2 ** attempt, 8000))
          }
        })
    }
    tryLoad()
    return () => { cancelled = true }
  }, [])
  // Parent tabs render IMMEDIATELY on first paint — they're a fixed, curated
  // set (MEGA_SECTIONS), so there's no reason to wait on the category-tree
  // fetch to show them. The ~2.8s tree load (panel contents: live counts +
  // thumbnails) happens behind the scenes; by the time a user hovers a tab the
  // data is almost always there. Once the tree HAS loaded we prune any whole
  // section whose entire sub_section list resolves to dead categories (as PACE
  // feeds get ingested for empty branches, those sections auto-light up). While
  // the tree is still loading (or a transient fetch failed), we show ALL parent
  // tabs rather than a blank strip — the menu never disappears.
  const treeReady = tree.length > 0
  const liveSections = !treeReady
    ? MEGA_SECTIONS.map((sec) => ({ sec, liveCount: 0 }))
    : MEGA_SECTIONS.map((sec) => {
        const liveCount = sec.sub_sections.filter((s) => {
          if (s.route) return true
          const node = resolveSubSection(s, tree)
          return node !== null && (node.product_count || 0) > 0
        }).length
        return { sec, liveCount }
      }).filter((x) => x.liveCount > 0)
  // Showroom Mode: collapse the whole nav to the Truck Accessories sub-category
  // links (filling the strip) + Shop Your Vehicle. Everything else is hidden.
  const showroomSubs = (() => {
    if (!showroomActive) return []
    const acc = MEGA_SECTIONS.find((s) => s.slug === 'truck-accessories')
    if (!acc) return []
    return acc.sub_sections.filter((s) => {
      if (!treeReady || s.route) return true
      const node = resolveSubSection(s, tree)
      return node !== null && (node.product_count || 0) > 0
    })
  })()

  // Showroom nav: a single full-width strip of accessory sub-category links +
  // Shop Your Vehicle, paged by arrow buttons at each end (like the banner).
  if (showroomActive) {
    const scrollStrip = (dir: number) => {
      const el = showroomStripRef.current
      if (el) el.scrollBy({ left: dir * el.clientWidth * 0.8, behavior: 'smooth' })
    }
    const arrowCls = 'absolute top-1/2 z-20 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full border border-slate-200 bg-white text-lg leading-none text-slate-700 shadow hover:bg-slate-50'
    return (
      <nav className="bg-gray-50 border-t">
        <div className="relative mx-auto max-w-[1600px] px-4 sm:px-6 lg:px-8">
          <button type="button" onClick={() => scrollStrip(-1)} aria-label="Scroll left" className={`${arrowCls} left-1`}>‹</button>
          <div ref={showroomStripRef} className="flex flex-nowrap items-center gap-1 overflow-x-auto scroll-smooth px-9 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {showroomSubs.map((s) => (
              <Link key={s.name} to={subSectionLink(s, 'Truck Accessories')} className="whitespace-nowrap px-3 py-3 text-xs font-semibold uppercase tracking-wide text-gray-800 hover:text-red-700 md:text-sm">
                {s.name}
              </Link>
            ))}
            <span className="mx-1 h-5 w-px shrink-0 bg-gray-300" />
            <button type="button" onClick={() => setYmmOpen(true)} className="flex shrink-0 items-center gap-1.5 whitespace-nowrap px-3 py-3 text-xs font-bold italic uppercase tracking-wide text-gray-600 underline decoration-gray-400 underline-offset-4 hover:text-red-700 md:text-sm">
              🚚 {ymm ? `${ymm.year} ${ymm.make_name} ${ymm.model_name}` : 'Shop your vehicle'}
            </button>
            {ymm && <button type="button" onClick={() => setYmm(null)} aria-label="Clear vehicle" className="px-1 text-gray-400 hover:text-red-700">✕</button>}
          </div>
          <button type="button" onClick={() => scrollStrip(1)} aria-label="Scroll right" className={`${arrowCls} right-1`}>›</button>
        </div>
      </nav>
    )
  }
  // Delegated keep-open test: the panel renders INSIDE <nav> but is full-width
  // with centered content, and the nav strip is full-width with the tabs offset
  // from the left — so there's lots of EMPTY nav/panel area (left of "Truck
  // Accessories", the panel's left/right margins, the spacer) that should NOT
  // keep the menu open. A single onMouseOver on <nav> decides: cursor over a
  // real tab or real panel CONTENT (marked data-mega-keep) → cancel close;
  // anywhere else inside nav → arm close. This replaces per-element leave
  // handlers, which couldn't see "still in nav but over empty space."
  function onNavMouseOver(e: React.MouseEvent) {
    if (!canHover) return
    const t = e.target as HTMLElement
    if (t.closest('[data-mega-keep]')) cancelClose()
    else scheduleClose()
  }
  return (
    <nav ref={navRef} className="bg-gray-50 border-t relative"
      onMouseOver={onNavMouseOver}
      onMouseLeave={() => { cancelHoverOpen(); cancelClose(); setOpenSection(null) }}>
      {/* flex-nowrap keeps the divisions on one line (a recognizable horizontal
          nav strip). overflow-x-auto still allows swipe-scroll on very narrow
          phones, but the scrollbar itself is hidden on every browser so it never
          shows the ugly track (design rule: no visible horizontal scrollbar). */}
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 flex items-center flex-nowrap overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {showroomActive ? (
          /* Showroom: Truck Accessories sub-category quick-links fill the strip. */
          showroomSubs.map((s) => (
            <Link
              key={s.name}
              to={subSectionLink(s, 'Truck Accessories')}
              className="px-2.5 md:px-3 py-3 text-xs md:text-sm font-semibold uppercase tracking-wide text-gray-800 hover:text-red-700 whitespace-nowrap"
            >
              {s.name}
            </Link>
          ))
        ) : (
          liveSections.map(({ sec }, i) => (
          <div
            key={i}
            ref={(el) => { tabRefs.current[i] = el }}
            data-mega-keep
            onMouseEnter={() => scheduleOpen(i)}
            onClick={() => { cancelHoverOpen(); cancelClose(); setOpenSection(openSection === i ? null : i) }}
            className="flex"
          >
            <button
              type="button"
              className={`px-3 md:px-5 py-3 text-xs md:text-sm font-bold uppercase tracking-wide transition border-b-2 whitespace-nowrap ${
                openSection === i
                  ? 'text-red-700 border-red-700 bg-white'
                  : 'text-gray-800 border-transparent hover:text-red-700'
              }`}
            >
              {sec.label}
              <svg className="inline-block w-3 h-3 ml-1" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="6 9 12 15 18 9"/>
              </svg>
            </button>
          </div>
          ))
        )}
        {/* Shop your vehicle — opens the YMM picker; sits right of the category tabs */}
        <div className="ml-1 flex shrink-0 items-center whitespace-nowrap">
          <button type="button" onClick={() => setYmmOpen(true)} className="flex items-center gap-1.5 px-2 py-3 text-xs md:text-sm font-bold italic uppercase tracking-wide text-gray-600 underline decoration-gray-400 underline-offset-4 transition hover:text-red-700">
            <svg className="w-5 h-5 text-red-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M2.5 14V9a1 1 0 0 1 1-1h4.5l2.5 3.5h2.5V14" />
              <path d="M13 11.5h7.5a1 1 0 0 1 1 1V14h-8.5z" />
              <circle cx="6.5" cy="16" r="1.9" />
              <circle cx="16.5" cy="16" r="1.9" />
            </svg>
            {ymm ? `${ymm.year} ${ymm.make_name} ${ymm.model_name}` : 'Shop your vehicle'}
          </button>
          {ymm && (
            <button type="button" onClick={() => setYmm(null)} aria-label="Clear vehicle" className="px-1 text-gray-400 transition hover:text-red-700">✕</button>
          )}
        </div>
        <div className="flex-1 min-w-2" />
        {!showroomActive && (
          <>
            <Link to="/snow-plows" className="px-2 md:px-3 py-3 text-xs font-semibold uppercase tracking-wide text-blue-800 hover:text-red-700 whitespace-nowrap">
              ❄️ Snow Plows
            </Link>
            <Link to="/brands" className="px-2 md:px-3 py-3 text-xs font-semibold uppercase tracking-wide text-gray-700 hover:text-red-700 whitespace-nowrap">
              Brands A-Z
            </Link>
          </>
        )}
      </div>
      {!showroomActive && openSection !== null && liveSections[openSection] && (
        <MegaPanel
          section={liveSections[openSection].sec}
          tree={tree}
          anchorLeft={anchorLeft}
          onClose={() => setOpenSection(null)}
        />
      )}
    </nav>
  )
}

// ============================================================================
// Pages
// ============================================================================

// ---- Deal Warehouse homepage (live) -------------------------------------
// (The former HomeLeftRail/HomeRightRail 3-column rails were replaced by the
//  Deal Warehouse layout below — deals sidebar + Rebate Center + product grid.)
interface DealProductCard {
  id: number; sku: string; name: string; brand: string | null; image_url: string | null
  retail_price: number | null; in_stock: boolean; stock_total: number
  badge_label: string | null; badge_tone: string | null; cta_mode: string
}
interface DealHighlightRow { id: number; label: string | null; sublabel: string | null; icon: string | null; link_url: string | null }
interface DealsHome { collection: { id: number; name: string; ends_at: string | null } | null; highlights: DealHighlightRow[]; products: DealProductCard[] }
interface RebateRow { id: number; brand: string | null; amount_label: string; terms: string | null; threshold_label: string | null; claim_method: string; ends_at: string | null }

function dealBadgeClass(tone: string | null): string {
  switch (tone) {
    case 'rebate': return 'bg-blue-600'
    case 'clearance': return 'bg-red-600'
    case 'free_shipping': return 'bg-emerald-600'
    case 'pro_price': return 'bg-violet-600'
    case 'limited': return 'bg-amber-600'
    case 'sale': return 'bg-rose-600'
    default: return 'bg-slate-700'
  }
}

function fmtRetail(price: number | null): string {
  if (price == null) return 'Call for price'
  return `Retail $${price.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`
}

function HomeCountdown({ endsAt }: { endsAt: string | null }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    if (!endsAt) return
    const tick = () => setSecs(Math.max(0, Math.floor((new Date(endsAt).getTime() - Date.now()) / 1000)))
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [endsAt])
  if (!endsAt) return null
  const p = (n: number) => String(n).padStart(2, '0')
  return <span className="tabular-nums">{p(Math.floor(secs / 3600))}:{p(Math.floor((secs % 3600) / 60))}:{p(secs % 60)}</span>
}

function DealProductTile({ p }: { p: DealProductCard }) {
  const { addToCart } = useApp()
  const [adding, setAdding] = useState(false)
  return (
    <div className="group flex flex-col rounded-lg border border-slate-200 bg-white p-3 transition hover:shadow-md">
      <Link to={`/product/${encodeURIComponent(p.sku)}`} className="relative mb-2 block aspect-square overflow-hidden rounded bg-gradient-to-br from-slate-100 to-slate-200">
        {p.image_url
          ? <img src={p.image_url} alt={p.name} loading="lazy" className="h-full w-full object-contain" />
          : <span className="grid h-full w-full place-items-center text-3xl text-slate-400">📦</span>}
        {p.badge_label && <span className={`absolute left-1 top-1 rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase text-white ${dealBadgeClass(p.badge_tone)}`}>{p.badge_label}</span>}
      </Link>
      <div className="text-[10px] font-bold uppercase text-blue-700">{p.brand}</div>
      <Link to={`/product/${encodeURIComponent(p.sku)}`} className="line-clamp-2 text-xs font-medium text-slate-800 hover:text-blue-700">{p.name}</Link>
      <div className="mt-1 text-sm font-black text-slate-900">{fmtRetail(p.retail_price)}</div>
      <div className={`text-[10px] font-semibold ${p.in_stock ? 'text-emerald-700' : 'text-gray-400'}`}>
        {p.in_stock ? '✓ In stock · ships today' : 'Special order'}
      </div>
      {p.cta_mode === 'add_to_cart'
        ? <button disabled={adding} onClick={async () => { setAdding(true); try { await addToCart(p.sku, 1) } finally { setAdding(false) } }}
            className="mt-2 rounded bg-yellow-400 py-1.5 text-[11px] font-extrabold text-gray-900 hover:bg-yellow-300 disabled:opacity-60">{adding ? 'Adding…' : 'Add to Cart'}</button>
        : <Link to={`/product/${encodeURIComponent(p.sku)}`} className="mt-2 rounded bg-slate-800 py-1.5 text-center text-[11px] font-extrabold text-white hover:bg-slate-900">View details</Link>}
    </div>
  )
}

// Homepage featured tiles (variant-2 "overlap" redesign). Real product photo
// where we have a good one; emoji icon otherwise — swap `img` in as photos are
// sourced. Tiles scroll horizontally and overlap the banner's bottom edge.
// Pre-filtered catalog landing-page URLs for a category.
const homeCat = (fullPath: string) => `/catalog?category_path=${encodeURIComponent(fullPath)}`
const homeCatTop = (name: string) => `/catalog?category_top=${encodeURIComponent(name)}`
const homeCatPath = (top: string, fullPath: string) => `/catalog?category_top=${encodeURIComponent(top)}&category_path=${encodeURIComponent(fullPath)}`
// Brand chip lands on the card's category page, then adds the brand filter.
const appendBrand = (url: string, brand: string) => `${url}${url.includes('?') ? '&' : '?'}brand=${encodeURIComponent(brand)}`

// `brandBase` overrides where the brand chips filter (used for cards whose `to`
// is a curated route like /snow-plows or /vans that ignores ?brand=).
const HOME_PROMO_TILES: { label: string; to: string; icon: string; img?: string; brandBase?: string; brands: { label: string; value: string }[] }[] = [
  { label: 'Snow plows & ice', to: '/snow-plows', icon: '❄️', img: '/static/brand_images/WEST/WEST69500/00_bing_1d7776106e6d.jpg', brandBase: homeCat('Truck Equipment > Snow Plows'), brands: [{ label: 'Western', value: 'Western' }, { label: 'Meyer', value: 'Meyer Products' }, { label: 'SnowDogg', value: 'Buyers SnowDogg' }] },
  { label: 'Salt spreaders & hoppers', to: homeCat('Truck Equipment > Salt Spreaders and Hoppers'), icon: '🧂', img: '/static/brand_images/SNOW/SNOW1400601SS/00_bing_07e20e9b358a.jpg', brands: [{ label: 'SnowDogg', value: 'Buyers SnowDogg' }, { label: 'Buyers', value: 'Buyers Products' }] },
  { label: 'Van equipment', to: '/vans', icon: '🚐', img: '/static/category-images/home-van-equipment.jpg', brandBase: homeCatTop('Van Equipment'), brands: [{ label: 'Weather Guard', value: 'Weatherguard' }, { label: 'Kargo Master', value: 'Kargo Master' }] },
  { label: 'Cab partitions', to: homeCat('Van Equipment > Cab Partitions and Dividers'), icon: '🚧', img: '/static/category-images/cargo-management-cab-partitions-and-dividers.jpg', brands: [{ label: 'Weather Guard', value: 'Weatherguard' }, { label: 'Kargo Master', value: 'Kargo Master' }] },
  { label: 'Tonneau covers', to: homeCatTop('Truck Bed Covers'), icon: '🛻', img: '/static/category-images/home-truck-bed-covers.jpg', brands: [{ label: 'BAK', value: 'Bak Industries' }, { label: 'Truxedo', value: 'Truxedo' }, { label: 'UnderCover', value: 'Undercover Tonneau' }] },
  { label: 'Toolboxes', to: homeCatPath('Truck Accessories', 'Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories'), icon: '🧰', img: '/static/category-images/home-toolboxes.jpg', brands: [{ label: 'Weather Guard', value: 'Weatherguard' }, { label: 'UWS', value: 'UWS' }] },
  { label: 'Lighting', to: homeCat('Truck Accessories > Automotive Lighting'), icon: '💡', img: '/static/category-images/automotive-lighting.jpg', brands: [{ label: 'ARC', value: 'Arc Lighting' }, { label: 'Rigid', value: 'Rigid Industries' }, { label: 'Baja', value: 'Baja Designs' }] },
  { label: 'Running boards & steps', to: homeCat('Truck Accessories > Running Boards and Steps'), icon: '🪜', img: '/static/category-images/running-boards-and-steps.png', brands: [{ label: 'Go Rhino', value: 'Go Rhino' }, { label: 'Westin', value: 'Westin' }] },
  { label: 'Bumpers & grille guards', to: homeCat('Truck Accessories > Bumpers and Grille Guards'), icon: '🛡️', img: '/static/category-images/home-bumpers.jpg', brands: [{ label: 'Ranch Hand', value: 'Ranch Hand' }, { label: 'Go Rhino', value: 'Go Rhino' }, { label: 'Westin', value: 'Westin' }] },
  { label: 'Winches', to: homeCat('Truck Equipment > Winches and Accessories'), icon: '🪝', img: '/static/category-images/winches-and-accessories.jpg', brands: [{ label: 'Superwinch', value: 'Superwinch' }, { label: 'Warn', value: 'Warn' }] },
  { label: 'Towing & hitches', to: homeCat('Truck Equipment > Towing and Accessories'), icon: '🔗', img: '/static/category-images/towing-and-accessories.png', brands: [{ label: 'CURT', value: 'CURT Manufacturing' }, { label: 'Buyers', value: 'Buyers Products' }] },
  { label: 'Air intakes', to: homeCat('Truck Accessories > Air Intakes'), icon: '🌀', img: '/static/category-images/air-intakes.jpg', brands: [{ label: 'K&N', value: 'K&N Filters' }, { label: 'Rough Country', value: 'Rough Country' }] },
  { label: 'Suspension', to: homeCat('Truck Accessories > Suspension'), icon: '🔧', img: '/static/category-images/home-suspension.jpg', brands: [{ label: 'Rough Country', value: 'Rough Country' }, { label: 'Firestone', value: 'Firestone AirRide' }] },
  { label: 'Wheels & tires', to: homeCat('Truck Accessories > Wheels and Tires'), icon: '🛞', img: '/static/category-images/wheels-and-tires.jpg', brands: [{ label: 'Rough Country', value: 'Rough Country' }, { label: 'ICON', value: 'ICON Alloys' }, { label: 'Rugged Ridge', value: 'Rugged Ridge' }] },
  { label: 'Transfer tanks', to: homeCat('Truck Accessories > Transfer Tanks'), icon: '🛢️', img: '/static/category-images/truck-bed-and-tailgate-transfer-tanks-and-accessories.jpg', brands: [{ label: 'Dee Zee', value: 'Dee Zee' }, { label: 'UWS', value: 'UWS' }, { label: 'Lund', value: 'Lund' }] },
  { label: 'Floor mats & liners', to: homeCatPath('Truck Accessories', 'Truck Accessories > Interior > Floor Mats and Cargo Liners'), icon: '🟫', img: '/static/category-images/interior.jpg', brands: [{ label: 'WeatherTech', value: 'WeatherTech' }, { label: 'Husky', value: 'Husky Liners' }, { label: 'FIA', value: 'FIA' }] },
  { label: 'Fender flares', to: homeCatPath('Truck Accessories', 'Truck Accessories > Exterior > Fender Flares and Accessories'), icon: '🚙', img: '/static/category-images/exterior.jpeg', brands: [{ label: 'Bushwacker', value: 'Bushwacker' }, { label: 'AVS', value: 'Auto Ventshade' }] },
]
const HOME_CATEGORY_PILLS: { label: string; img: string; to: string }[] = [
  { label: 'Snow & Ice', img: '/static/brand_images/WEST/WEST69500/00_bing_1d7776106e6d.jpg', to: '/snow-plows' },
  { label: 'Van Equipment', img: '/static/category-images/home-van-equipment.jpg', to: '/vans' },
  { label: 'Tonneau', img: '/static/category-images/home-truck-bed-covers.jpg', to: '/catalog' },
  { label: 'Lighting', img: '/static/category-images/automotive-lighting.jpg', to: '/catalog' },
  { label: 'Racks & Ladders', img: '/static/product-images/74/742021d3cb011187_1280.jpg', to: '/catalog' },
  { label: 'Running Boards', img: '/static/category-images/running-boards-and-steps.png', to: '/catalog' },
  { label: 'Winches', img: '/static/category-images/winches-and-accessories.jpg', to: '/catalog' },
  { label: 'Toolboxes', img: '/static/category-images/home-toolboxes.jpg', to: '/catalog' },
  { label: 'Utility & Aerial', img: '/static/brand_images/KNP/KNP20095520/00_bing_2a1693debb24.png', to: '/catalog' },
]

// In Retail Showroom Mode the homepage promo tiles + "Shop by category" pills
// are filtered to these Truck-Accessories-only items (no plows/spreaders/van/
// winches/towing — those are equipment, not what a walk-in retail buyer shops).
const SHOWROOM_PROMO_LABELS = new Set([
  'Tonneau covers', 'Toolboxes', 'Lighting', 'Running boards & steps',
  'Bumpers & grille guards', 'Air intakes', 'Suspension', 'Wheels & tires',
  'Transfer tanks', 'Floor mats & liners', 'Fender flares',
])
const SHOWROOM_PILL_LABELS = new Set(['Tonneau', 'Lighting', 'Racks & Ladders', 'Running Boards', 'Toolboxes'])

// Horizontal row paginated by left/right arrow buttons (no visible scrollbar).
// Each click pages by the visible width — with the homepage tile sizing that's
// ~4 cards at a time, matching the Amazon-style category scroller.
function ScrollRow({ children, className = '' }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const page = (dir: number) => {
    const el = ref.current
    if (el) el.scrollBy({ left: dir * el.clientWidth, behavior: 'smooth' })
  }
  const arrow = 'absolute top-1/2 z-20 hidden h-9 w-9 -translate-y-1/2 place-items-center rounded-full border border-slate-200 bg-white text-lg leading-none text-slate-700 shadow-md hover:bg-slate-50 sm:grid'
  return (
    <div className="relative">
      <button type="button" onClick={() => page(-1)} aria-label="Scroll left" className={`${arrow} -left-3`}>‹</button>
      <div ref={ref} className={`flex overflow-x-auto scroll-smooth pb-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${className}`}>
        {children}
      </div>
      <button type="button" onClick={() => page(1)} aria-label="Scroll right" className={`${arrow} -right-3`}>›</button>
    </div>
  )
}

// --- Nelson Bold Red Garage homepage ---------------------------------------
const NELSON_SLIDES = [
  { ey: 'Snow & Ice · Ready before the storm', h1a: "Winter’s coming.", h1b: 'Get plow-ready.', copy: 'Western, SnowDogg & Meyer plows and spreaders — in stock, and mounted & wired in our Portland & Kent shops.', cta: 'Shop snow & ice', to: '/snow-plows', bto: false, card: { brand: 'Western · SnowDogg · Meyer', name: 'Straight-blade & V-plows', price: 'In stock & installed', imgs: ['/static/brand_images/WEST/WEST69500/00_bing_1d7776106e6d.jpg', '/static/product-images/92/92d1cd8fdb9fd85b_1280.jpg', '/static/product-images/dc/dc36845ac71cf80f_1280.jpg'] } },
  { ey: 'Tow Trucks · Towing & Recovery', h1a: 'Built to', h1b: 'bring it back.', copy: "Wreckers, rollbacks, and rotators from Jerr-Dan and Century — plus the Northwest’s deepest inventory of tow truck parts.", cta: 'Explore tow trucks', to: '/catalog', bto: true, card: { brand: 'Jerr-Dan', name: 'MPL-NGS Steel Rollback Carrier', price: 'Built to order' } },
  { ey: 'Aerial & Bucket Division', h1a: 'Reach', h1b: 'higher.', copy: 'Bucket trucks, aerial lifts, and digger derricks from Dur-A-Lift — sales, upfit, and service.', cta: 'Explore aerial & bucket', to: '/catalog', bto: true, card: { brand: 'Dur-A-Lift', name: 'DPM2-42 Insulated Aerial Bucket', price: 'Built to order' } },
  { ey: 'Trailers · Landoll Dealer', h1a: 'Haul the', h1b: 'heavy stuff.', copy: 'Landoll traveling-axle, detach, and sliding-axle trailers — plus a full line of Landoll parts, sold and serviced here.', cta: 'Explore trailers', to: '/catalog', bto: true, card: { brand: 'Landoll', name: '440 Series Traveling Axle Trailer', price: 'Built to order' } },
  { ey: 'Truck & Van Accessories', h1a: 'Cover your bed', h1b: 'in seconds.', copy: 'Hard roll-up and folding tonneau covers from BAK, Retrax, and Extang — fitment-matched to your truck.', cta: 'Shop tonneau covers', to: '/catalog?category_top=Truck+Bed+Covers', bto: false, card: { brand: 'BAK Industries', name: 'Revolver X4 Hard Roll-Up Cover', price: '$1,099.00', img: '/static/product-images/49/498d2a7bdf17730b_1280.jpg' } },
]

function NelsonHeroBanner() {
  const [i, setI] = useState(0)
  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const t = setInterval(() => setI((x) => (x + 1) % NELSON_SLIDES.length), 4800)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="relative overflow-hidden min-h-[420px] md:min-h-[440px] lg:min-h-[470px]" style={{ background: 'radial-gradient(120% 150% at 82% -10%, #c8232d 0, #a01a22 52%, #7c141b 100%)' }}>
      {NELSON_SLIDES.map((s, idx) => (
        <div key={idx} className={`absolute inset-0 flex flex-col items-center gap-6 px-6 py-8 md:flex-row md:items-center md:gap-6 md:px-10 lg:gap-8 lg:px-14 transition-opacity duration-700 ${idx === i ? 'opacity-100' : 'pointer-events-none opacity-0'}`}>
          <div className="w-full md:w-auto md:max-w-lg md:shrink-0">
            <div className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-amber-200">{s.ey}</div>
            <h1 className="font-cond text-4xl leading-[0.95] text-white md:text-6xl">{s.h1a}<br /><span className="text-amber-400">{s.h1b}</span></h1>
            <p className="mt-3 max-w-md text-[15px] text-red-50">{s.copy}</p>
            <Link to={s.to} className="mt-5 inline-block rounded-lg bg-amber-400 px-6 py-3 font-cond text-sm text-amber-950 hover:bg-amber-300">{s.cta} →</Link>
          </div>
          <div className="hidden w-full min-w-0 md:flex md:flex-1 md:justify-start">
            <div className="relative w-full max-w-2xl -rotate-1 rounded-2xl bg-[#fbf8f2] p-5 shadow-2xl lg:max-w-4xl">
              <span className={`absolute -top-3 left-4 z-10 rounded px-2 py-1 text-[10px] font-bold uppercase text-white ${s.bto ? 'bg-sky-700' : 'bg-emerald-600'}`}>{s.bto ? 'Sales · Upfit · Service' : '✓ In stock — pick up today'}</span>
              {/* White stage so white-background product photos blend in and the
                  product reads as floating (no photo-tile edge). A slide can carry
                  several images (`imgs`) — e.g. a lineup of plows — which stack and
                  float on the same white field. Single lifestyle photos / the
                  transparent badge keep a drop-shadow for a true silhouette float. */}
              {(s.card as { imgs?: string[] }).imgs ? (
                <div className="flex items-center justify-center gap-1 rounded-xl bg-white px-2 py-4 lg:gap-2">
                  {(s.card as { imgs: string[] }).imgs.map((src, k) => (
                    <div key={k} className="flex flex-1 items-center justify-center overflow-hidden">
                      <img src={src} alt="" className="max-h-36 w-full scale-[1.18] object-contain lg:max-h-52" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="relative grid h-52 place-items-center overflow-hidden rounded-xl bg-white lg:h-60">
                  <img
                    src={(s.card as { img?: string }).img || '/brand/nelson-badge.png'}
                    alt={s.card.name}
                    className={`max-h-[88%] max-w-[62%] object-contain ${(s.card as { whiteBg?: boolean }).whiteBg ? '' : 'drop-shadow-[0_18px_20px_rgba(15,23,42,0.26)]'}`}
                  />
                </div>
              )}
              <div className="mt-3 text-[10px] font-bold uppercase tracking-wide text-slate-500">{s.card.brand}</div>
              <div className="text-[15px] font-semibold leading-snug text-slate-900 lg:text-base">{s.card.name}</div>
              <div className="mt-1 font-cond text-xl text-red-700 lg:text-2xl">{s.card.price}</div>
            </div>
          </div>
        </div>
      ))}
      <div className="absolute bottom-4 left-6 z-10 flex gap-2 md:left-12">
        {NELSON_SLIDES.map((_, idx) => (
          <button key={idx} aria-label={`Slide ${idx + 1}`} onClick={() => setI(idx)} className={`h-1.5 w-6 rounded ${idx === i ? 'bg-white' : 'bg-white/40'}`} />
        ))}
      </div>
    </div>
  )
}

function NelsonHome() {
  const [prods, setProds] = useState<any[]>([])
  useEffect(() => {
    // Pickup-branch stock only (Portland/Kent) — the "In stock & ready today"
    // grid promises same-day counter pickup, so it must exclude Spokane-only
    // stock that /api/catalog/browse would otherwise count as in-stock.
    fetch('/api/catalog/featured-pickup?limit=12')
      .then((r) => r.json())
      .then((d) => setProds((d?.hits || []).slice(0, 12)))
      .catch(() => setProds([]))
  }, [])
  return (
    <div className="bg-[#16130f] text-[#f4efe6]">
      <Seo
        title="Nelson Truck Equipment — Snow Plows, Truck Bodies, Tow Trucks & Accessories"
        description="Commercial truck equipment, snow plows, service & dump bodies, tow trucks, aerial & bucket trucks, Landoll trailers, and accessories — in stock in Portland, OR and Kent, WA. Serving the Pacific Northwest since 1937. Pick it up today; we install everything we sell."
        path="/"
        jsonLd={[ORGANIZATION_JSONLD, WEBSITE_JSONLD, ...LOCALBUSINESS_JSONLD]}
      />
      <NelsonHeroBanner />

      {/* Value pillars */}
      <div className="grid gap-[2px] bg-[#2a2620] md:grid-cols-3">
        {[
          { k: 'No waiting', b: 'Pick it up ', i: 'today', p: 'On the shelf in Portland & Kent at a price that keeps you working — skip the wait, grab it now.', feat: false },
          { k: 'Full service', b: 'We install ', i: 'everything we sell', p: 'Plows, bodies, liftgates, accessories — mounted, wired, and dialed in at our Portland & Kent shops. Drive in, drive out.', feat: true },
          { k: 'Real people', b: 'Talk to a ', i: 'real expert', p: "Not sure it fits? Our counter team sorts the fitment and shows you in-stock alternates on the spot.", feat: false },
        ].map((v) => (
          <div key={v.k} className={`bg-[#141109] px-6 py-5 ${v.feat ? 'border-l-[3px] border-red-700 pl-[21px]' : ''}`}>
            <span className={`text-[11px] uppercase tracking-[0.14em] ${v.feat ? 'text-red-500' : 'text-amber-400'}`}>{v.k}</span>
            <div className="mt-2 font-cond text-lg text-white">{v.b}<span className="text-amber-400">{v.i}</span></div>
            <p className="mt-1 text-[13px] leading-relaxed text-[#9a917f]">{v.p}</p>
          </div>
        ))}
      </div>

      {/* Custom fabrication invite */}
      <div className="flex flex-wrap items-center justify-between gap-5 border-l-[4px] border-red-700 bg-[#1b1813] px-6 py-5">
        <div>
          <h3 className="font-cond text-2xl text-white">We build <span className="text-amber-400">custom</span>, too.</h3>
          <p className="mt-1 max-w-[70ch] text-sm text-[#9a917f]">Service bodies, racks, one-off fabrication, special upfits — if you can spec it, our shops can build it. We&rsquo;d love to hear about your project.</p>
        </div>
        <a href="mailto:sales@nelsontruck.com?subject=Custom%20project" className="rounded-lg bg-amber-400 px-6 py-3 font-cond text-sm uppercase text-amber-950 hover:bg-amber-300">Tell us about your project →</a>
      </div>

      {/* Steel / metal — advertise, counter-only */}
      <div className="flex flex-wrap items-center justify-between gap-5 border-l-[4px] border-[#8f9aa3] bg-[#141109] px-6 py-5">
        <div>
          <span className="text-[11px] uppercase tracking-[0.14em] text-[#aeb8c0]">At the counter · Portland & Kent</span>
          <h3 className="mt-1 font-cond text-2xl text-white">Yes — we sell <span className="text-[#c3ccd3]">steel.</span></h3>
          <p className="mt-1 max-w-[78ch] text-sm text-[#9a917f]">Bar, tube, angle, plate, and sheet in stock at both shops. Buy it by the pound at the counter, and we&rsquo;ll cut small jobs while you wait — come see us.</p>
        </div>
        <Link to="/catalog" className="rounded-lg bg-[#d7dde1] px-6 py-3 font-cond text-sm uppercase text-[#1a1d20] hover:bg-white">What we stock →</Link>
      </div>

      {/* Product grid */}
      <div className="mx-auto max-w-[1180px] px-6 py-6">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="font-cond text-2xl text-white">In stock & ready <span className="text-red-700">today</span></h2>
          <Link to="/catalog" className="text-xs font-semibold uppercase tracking-wide text-[#8b8171] hover:text-amber-400">View all →</Link>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
          {prods.map((p) => (
            <Link key={p.id} to={`/product/${encodeURIComponent(p.sku)}`} className="group flex flex-col gap-2 rounded-lg border border-[#2c271f] bg-[#1c1813] p-3 transition hover:border-red-700">
              <div className="aspect-[4/3] rounded-md" style={{ background: p.image_url ? `#0f0d0a url(${p.image_url}) center/contain no-repeat` : '#e8edf1 url(/brand/nelson-badge.png) center/40% no-repeat' }} />
              <div className="text-[10px] font-bold uppercase tracking-wide text-[#8b8171]">{p.brand || 'Nelson'}</div>
              <div className="min-h-[34px] text-[13px] font-semibold leading-snug text-[#efe9dc]">{p.name}</div>
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-400"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />In stock · today</div>
              <span className="mt-0.5 rounded-md bg-[#2a2620] py-2 text-center text-xs font-bold text-white transition group-hover:bg-red-700">Pick up today →</span>
            </Link>
          ))}
        </div>
      </div>

      {/* Stats */}
      <div className="flex flex-wrap border-t border-[#221e18] bg-[#0f0d0a]">
        {[['1937', 'Serving the PNW since'], ['60k+', 'Parts & accessories'], ['2', 'Branches · Portland + Kent'], ['Today', 'On the shelf — not in transit']].map(([b, s]) => (
          <div key={s} className="min-w-[150px] flex-1 border-r border-[#221e18] px-6 py-5">
            <div className="font-cond text-3xl leading-none text-amber-400">{b}</div>
            <div className="text-[11px] uppercase tracking-wide text-[#9a917f]">{s}</div>
          </div>
        ))}
      </div>

      {/* Brand marquee */}
      <div className="flex flex-wrap justify-center gap-6 bg-[#1b1813] p-5 font-cond text-lg text-[#7d7466]">
        {['Meyer', 'Western', 'Jerr-Dan', 'Landoll', 'Dur-A-Lift', 'WeatherTech', 'WeatherGuard', 'BAK', 'Curt', 'Liftmoore'].map((b) => <span key={b}>{b}</span>)}
      </div>
    </div>
  )
}

void Home  // legacy Nelson-style homepage, kept for reference; live route uses NelsonHome
function Home() {
  const { user, showroom } = useApp()
  const showroomActive = showroom && (user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer')
  const audience: 'retail' | 'wholesale' = user?.customer_tier && user.customer_tier !== 'retail' ? 'wholesale' : 'retail'
  const promoTiles = showroomActive ? HOME_PROMO_TILES.filter((t) => SHOWROOM_PROMO_LABELS.has(t.label)) : HOME_PROMO_TILES
  const categoryPills = showroomActive ? HOME_CATEGORY_PILLS.filter((c) => SHOWROOM_PILL_LABELS.has(c.label)) : HOME_CATEGORY_PILLS
  const [deals, setDeals] = useState<DealsHome | null>(null)
  const [rebates, setRebates] = useState<RebateRow[]>([])

  useEffect(() => {
    fetch(`/api/deals/home?audience=${audience}`, { credentials: 'include' })
      .then((r) => r.json()).then(setDeals).catch(() => setDeals(null))
    fetch(`/api/rebates?audience=${audience}`, { credentials: 'include' })
      .then((r) => r.json()).then((d) => setRebates(Array.isArray(d) ? d : [])).catch(() => setRebates([]))
  }, [audience])

  const products = deals?.products ?? []
  const highlights = deals?.highlights ?? []

  return (
    <div className="min-h-screen bg-slate-100">
      <Seo
        title="Nelson Truck Equipment — Snow Plows, Truck & Van Equipment"
        description="Commercial truck & van equipment, snow plows, spreaders, and accessories for the Pacific Northwest. Family-owned since 1937 — Portland & Kent."
        path="/"
        jsonLd={[ORGANIZATION_JSONLD, WEBSITE_JSONLD]}
      />
      <div className="mx-auto max-w-7xl space-y-5 px-4 py-5">
        {/* Banner on top + featured tiles that overlap its bottom edge and scroll
            left/right (variant-2 redesign). Banner+tiles are one unit so the
            negative margin isn't fought by the wrapper's space-y. */}
        <div>
          <RotatingBanner audience={audience} fallback={null} fadeBottom />
          <div className="relative z-10 -mt-6 md:-mt-12">
            <ScrollRow className="gap-4">
              {promoTiles.map((t) => (
                <div key={t.label} className="group flex w-48 flex-none flex-col rounded-xl border border-slate-200 bg-white p-2.5 shadow-lg transition hover:shadow-xl">
                  {/* Title floats above the image on white — megamenu font, sentence case, bold */}
                  <Link to={t.to} className="block px-1 pb-0.5 text-center text-sm font-bold text-slate-900 hover:text-blue-700">{t.label}</Link>
                  {/* Image, no gradient */}
                  <Link to={t.to} className="flex items-center justify-center" style={{ height: 140 }}>
                    {t.img
                      ? <img src={t.img} alt={t.label} loading="lazy" className="max-h-full max-w-full object-contain transition group-hover:scale-[1.04]" />
                      : <span className="text-5xl">{t.icon}</span>}
                  </Link>
                  {/* Brand lines float below the image as direct links */}
                  <div className="mt-1.5 flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 px-1 text-xs">
                    {t.brands.map((b, idx) => (
                      <Fragment key={b.value}>
                        {idx > 0 && <span className="text-slate-300">·</span>}
                        <Link to={appendBrand(t.brandBase ?? t.to, b.value)} className="font-medium text-slate-600 hover:text-blue-700 hover:underline">{b.label}</Link>
                      </Fragment>
                    ))}
                  </div>
                </div>
              ))}
            </ScrollRow>
          </div>
        </div>

        {/* Shop by category — scrollable pills */}
        <div>
          <h2 className="mb-2 text-sm font-black uppercase tracking-wide text-slate-500">Shop by category</h2>
          <ScrollRow className="gap-3">
            {categoryPills.map((c) => (
              <Link key={c.label} to={c.to} className="flex w-56 flex-none flex-col items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 text-center transition hover:border-slate-300 hover:shadow-sm">
                <span className="flex h-28 w-full items-center justify-center overflow-hidden rounded-lg bg-slate-50">
                  <img src={c.img} alt={c.label} loading="lazy" className="max-h-full max-w-full object-contain" />
                </span>
                <span className="text-sm font-semibold text-slate-700">{c.label}</span>
              </Link>
            ))}
          </ScrollRow>
        </div>

        {/* Curated deal shortcuts (admin "highlights") — scroll left/right */}
        {highlights.length > 0 && (
          <div className="flex gap-3 overflow-x-auto pb-2 [scrollbar-width:thin]">
            {highlights.map((h) => (
              <Link key={h.id} to={h.link_url || '/catalog'} className="group flex w-52 flex-none items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 transition hover:shadow-sm">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-100 text-lg">{h.icon || '🏷️'}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-slate-800 group-hover:text-blue-700">{h.label}</span>
                  {h.sublabel && <span className="block truncate text-xs text-slate-500">{h.sublabel}</span>}
                </span>
              </Link>
            ))}
          </div>
        )}

        {/* Today's top deals — curated products, scroll left/right */}
        {products.length > 0 && (
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <h2 className="text-sm font-black uppercase tracking-wide text-slate-500">
                🔥 {deals?.collection?.name || "Today's top deals"}
                {deals?.collection?.ends_at && (
                  <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 align-middle text-[11px] font-semibold text-white">
                    <span className="text-amber-400">⏱</span><HomeCountdown endsAt={deals.collection.ends_at} />
                  </span>
                )}
              </h2>
              <Link to="/catalog" className="text-sm font-bold text-blue-700 hover:underline">See all →</Link>
            </div>
            <ScrollRow className="gap-3">
              {products.map((p) => (
                <div key={p.id} className="w-44 flex-none"><DealProductTile p={p} /></div>
              ))}
            </ScrollRow>
          </div>
        )}

        {/* Trust strip */}
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[['🚚', 'Same-day shipping', 'Order by 2 PM PT'], ['🏠', 'Family-owned since 1937', 'Portland + Kent'], ['💲', 'Price match', 'Beat advertised prices'], ['📞', 'Real humans', '503-548-9300']].map(([i, a, b]) => (
            <div key={a} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-3 text-xs">
              <span className="text-xl">{i}</span><div><div className="font-semibold text-slate-900">{a}</div><div className="text-slate-500">{b}</div></div>
            </div>
          ))}
        </section>

        {/* Rebate Center — full-width band, moved below deals (variant-2 redesign).
            Hidden in Showroom Mode (wholesale rebate info isn't for a walk-in). */}
        {!showroomActive && rebates.length > 0 && (
          <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-blue-700 via-blue-800 to-indigo-900 text-white shadow-lg ring-1 ring-white/10">
            <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
              <div className="flex shrink-0 items-center gap-2">
                <span className="rounded-full bg-amber-400 px-2.5 py-1 text-[10px] font-extrabold uppercase text-blue-950">Rebate Center</span>
                <span className="text-lg font-black leading-tight">{rebates.length} active {audience === 'wholesale' ? 'wholesale ' : ''}rebate{rebates.length === 1 ? '' : 's'}</span>
              </div>
              <div className="flex flex-1 gap-3 overflow-x-auto pb-1 [scrollbar-width:thin]">
                {rebates.map((r) => (
                  <div key={r.id} className="min-w-[180px] flex-none rounded-xl bg-white/10 p-3 ring-1 ring-white/10">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-xs font-bold tracking-wide text-white">{r.brand}</span>
                      <span className="whitespace-nowrap text-base font-black text-amber-300">{r.amount_label}</span>
                    </div>
                    {r.terms && <div className="text-[11px] text-blue-100">{r.terms}</div>}
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 text-[10px] text-blue-200">
                      {r.threshold_label && <span className="inline-flex items-center gap-1"><span className="text-emerald-300">✓</span>{r.threshold_label}</span>}
                      {r.ends_at && <span>ends {new Date(r.ends_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* B2B account — for anonymous/retail viewers */}
        {audience === 'retail' && (
          <div className="flex flex-col gap-3 rounded-2xl bg-gradient-to-br from-blue-700 to-blue-900 p-4 text-white shadow sm:flex-row sm:items-center">
            <div className="flex-1">
              <div className="text-[10px] font-bold uppercase tracking-widest text-blue-200">B2B Account</div>
              <h3 className="mt-1 text-sm font-bold leading-tight">Wholesale pricing for jobbers, dealers, municipalities</h3>
            </div>
            <Link to="/signup" className="inline-block shrink-0 rounded bg-yellow-400 px-3 py-1.5 text-xs font-bold text-gray-900 hover:bg-yellow-300">Open an account →</Link>
          </div>
        )}

        {/* Brands */}
        <section className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">Brands we stock deep</div>
          <BrandStrip />
        </section>

        <RecentlyViewedStrip />
      </div>
    </div>
  )
}

function BrandStrip() {
  const [brands, setBrands] = useState<{ value: string; count: number; logo_url?: string }[]>([])
  useEffect(() => {
    // Use /api/catalog/brands (DB-backed) instead of /browse facets
    // so the widget renders even when Typesense is down.
    fetch('/api/catalog/brands').then((r) => r.json()).then((rows: any[]) => {
      const ranked = (rows || [])
        .filter((b) => (b.product_count || 0) > 0)
        .sort((a, b) => Number(!!b.is_featured) - Number(!!a.is_featured)
                       || (b.product_count || 0) - (a.product_count || 0))
        .slice(0, 12)
        .map((b) => ({ value: b.name, count: b.product_count || 0, logo_url: b.logo_url }))
      setBrands(ranked)
    }).catch(() => {})
  }, [])
  if (brands.length === 0) return <div className="text-xs text-gray-400">Loading…</div>
  return (
    <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
      {brands.map((b) => (
        <Link
          key={b.value}
          to={`/catalog?brand=${encodeURIComponent(b.value)}`}
          className="flex flex-col items-center justify-center border rounded p-2 text-center hover:border-red-700 hover:shadow-sm transition bg-white"
          title={`${b.value} · ${b.count.toLocaleString()} products`}
        >
          {b.logo_url ? (
            <img src={b.logo_url} alt={b.value} className="h-8 w-full object-contain mb-1" loading="lazy" />
          ) : (
            // Brands without a localized logo get a consistent h-8 placeholder
            // tile so all rows in the strip stay the same height — looks more
            // like a deliberate brand card than a "missing image" gap.
            <div className="h-8 w-full mb-1 flex items-center justify-center bg-gray-100 rounded">
              <span className="text-[9px] uppercase tracking-widest text-gray-500 font-bold">{b.value.slice(0, 14)}</span>
            </div>
          )}
          <span className="text-[11px] font-semibold text-gray-700 hover:text-red-700 truncate w-full">{b.value}</span>
        </Link>
      ))}
    </div>
  )
}

// =========================================================================
// Recently Viewed — pure helpers, localStorage-backed
// =========================================================================

const RECENTLY_VIEWED_KEY = 'titan_recently_viewed_v1'
const RECENTLY_VIEWED_MAX = 12

function loadRecentlyViewed(): RecentlyViewedItem[] {
  try {
    const raw = localStorage.getItem(RECENTLY_VIEWED_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
  } catch { return [] }
}

// Pydantic returns 422 detail as a list of {loc, msg, type}.  Older FastAPI
// returns 400 with a plain string.  Format whichever shape into a single
// user-facing line — avoids the "[object Object]" / raw JSON.stringify dump
// pattern that crept into early Checkout / Modal error handling.
function formatApiError(body: any, status: number): string {
  if (!body) return `HTTP ${status}`
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail) && body.detail.length > 0) {
    const first = body.detail[0]
    const field = first?.loc?.slice(-1)[0] || ''
    return field ? `${field}: ${first.msg}` : (first.msg || `HTTP ${status}`)
  }
  return `HTTP ${status}`
}

function pushRecentlyViewed(item: Omit<RecentlyViewedItem, 'visited_at'>) {
  try {
    const list = loadRecentlyViewed().filter((x) => x.sku !== item.sku)
    list.unshift({ ...item, visited_at: Date.now() })
    while (list.length > RECENTLY_VIEWED_MAX) list.pop()
    localStorage.setItem(RECENTLY_VIEWED_KEY, JSON.stringify(list))
    // Notify other open tabs / siblings
    window.dispatchEvent(new CustomEvent('titan:recently-viewed-updated'))
  } catch {}
}

function useRecentlyViewed(): RecentlyViewedItem[] {
  const [items, setItems] = useState<RecentlyViewedItem[]>(() => loadRecentlyViewed())
  useEffect(() => {
    function onUpdate() { setItems(loadRecentlyViewed()) }
    window.addEventListener('titan:recently-viewed-updated', onUpdate)
    window.addEventListener('storage', onUpdate)
    return () => {
      window.removeEventListener('titan:recently-viewed-updated', onUpdate)
      window.removeEventListener('storage', onUpdate)
    }
  }, [])
  return items
}

function RecentlyViewedStrip() {
  const items = useRecentlyViewed()
  if (items.length === 0) return null
  return (
    <section className="bg-white border-t">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-end justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900">Recently viewed</h2>
          <button
            onClick={() => { localStorage.removeItem(RECENTLY_VIEWED_KEY); window.dispatchEvent(new CustomEvent('titan:recently-viewed-updated')) }}
            className="text-xs text-gray-500 hover:text-red-700"
          >
            Clear
          </button>
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-3">
          {items.slice(0, 8).map((it) => (
            <Link
              key={it.sku}
              to={`/product/${it.sku}`}
              className="group flex flex-col bg-white rounded overflow-hidden shadow-[0_1px_4px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_10px_rgba(0,0,0,0.1)] transition-shadow"
            >
              <div className="aspect-square bg-white flex items-center justify-center overflow-hidden">
                {it.image_url ? (
                  <img src={it.image_url} alt="" loading="lazy" className="w-[80%] h-[80%] object-contain drop-shadow-md group-hover:scale-105 transition-transform duration-200" />
                ) : (
                  <div className="text-[10px] uppercase text-gray-300">No image</div>
                )}
              </div>
              <div className="p-1.5 border-t border-gray-100">
                <div className="font-mono text-[9px] text-gray-500 truncate">{formatPartNumber(it.sku, it.brand)}</div>
                <div className="text-[10px] text-gray-700 line-clamp-2">{it.name}</div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  )
}

// LikeProductsRail — PDP companion rail. Two modes:
//   YMM set:  "Other parts for your {Year Make Model}"
//   YMM null: "Like this part"
// Backend at /api/catalog/products/{sku}/alternates picks 8 candidates from
// the same primary category. Owner ask 2026-05-17 (R1).
type AlternateItem = {
  id: number
  sku: string
  name: string
  brand: string | null
  image_url: string | null
  in_stock: boolean
  stock_total: number
  retail_price: number | null
  cta_mode: string
}

// InStockSubstituteCallout — banner shown when the source product is
// OOS but a similar product IS in stock for the same vehicle (or same
// subcategory if universal). Owner ask 2026-05-17: the entire goal of
// landing a customer on an OOS surface is converting them onto an
// in-stock cousin we can ship today. Calls /alternates with
// in_stock_only=true and limit=1. Hidden silently when no substitute
// exists (e.g. brand has no in-stock variants in the subcategory).
//
// Variants:
//   'full'    — PDP-style horizontal banner with image (default)
//   'compact' — narrow text-only chip for grid cards + list image column.
//               Drops the image and shrinks the type so it fits in a
//               128–280px container without overwhelming the row.
function InStockSubstituteCallout({ sku, variant = 'full', vehicleId }: { sku: string; variant?: 'full' | 'compact'; vehicleId?: number }) {
  const { ymm } = useApp()
  const [item, setItem] = useState<AlternateItem | null>(null)
  const [loading, setLoading] = useState(true)
  // Prefer a vehicle parsed from the search query (vehicleId) over the YMM
  // picker session, so a typed "2023 f-250 …" search suggests a part that
  // fits the F-250 — not just any in-stock cousin. (fixes wrong-fitment
  // in-stock-alt, reported 2026-06-25)
  const effectiveBvId = vehicleId ?? ymm?.base_vehicle_id
  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams({ in_stock_only: 'true', limit: '1' })
    if (effectiveBvId) params.set('base_vehicle_id', String(effectiveBvId))
    fetch(`/api/catalog/products/${encodeURIComponent(sku)}/alternates?${params.toString()}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setItem((d?.items && d.items[0]) || null))
      .catch(() => setItem(null))
      .finally(() => setLoading(false))
  }, [sku, effectiveBvId])
  if (loading) return null
  if (!item) return null
  const ymmClause = ymm ? ` for your ${ymm.year} ${ymm.make_name} ${ymm.model_name}` : ''

  // Same click target / styling for both variants — stop propagation so
  // clicking the green banner inside a grid card doesn't also navigate
  // to the parent product's PDP.
  const onClick = (e: React.MouseEvent) => e.stopPropagation()

  // "BrandName: partnumber" identity line. formatPartNumber already
  // includes the brand prefix; don't prepend it again.
  const partLabel = formatPartNumber(item.sku, item.brand)

  // Compact (grid + list): two-zone amber+green card, sized down. Owner
  // ask 2026-05-17 — the colored card with a clear OOS truth on top
  // reads better at a glance than a single text line. Same framing as
  // the PDP full variant; just tighter padding + smaller type.
  if (variant === 'compact') {
    return (
      <Link
        to={`/product/${item.sku}`}
        onClick={onClick}
        className="block rounded overflow-hidden border border-amber-400 hover:border-amber-500 transition-colors"
        title={`Not in stock — ${item.name} is available instead`}
      >
        <div className="bg-amber-50 px-1.5 py-1 border-b border-amber-200">
          <div className="text-[9px] uppercase tracking-widest font-bold text-amber-800 leading-tight">⚠ Not in stock</div>
        </div>
        <div className="bg-green-50 px-1.5 py-1">
          <div className="text-[8px] uppercase tracking-widest font-bold text-green-700 leading-tight">In stock alt →</div>
          <div className="text-[9px] uppercase tracking-wider text-gray-500 truncate mt-0.5">{partLabel}</div>
          <div className="text-[10px] text-gray-700 line-clamp-1 leading-tight">{item.name}</div>
          <div className="flex items-baseline justify-between mt-0.5">
            {item.retail_price != null && (
              <span className="text-[11px] font-bold text-gray-900">${item.retail_price.toFixed(2)}</span>
            )}
            <span className="text-[9px] text-green-700 font-semibold">{item.stock_total} avail</span>
          </div>
        </div>
      </Link>
    )
  }

  return (
    <Link
      to={`/product/${item.sku}`}
      onClick={onClick}
      className="block rounded overflow-hidden border-2 border-amber-400 hover:border-amber-500 transition-colors"
    >
      <div className="bg-amber-50 px-3 py-2 border-b border-amber-200">
        <div className="text-[11px] uppercase tracking-widest font-bold text-amber-800">
          ⚠ This part is not in stock{ymmClause}
        </div>
      </div>
      <div className="bg-green-50 hover:bg-green-100 p-3">
        <div className="flex items-center gap-3">
          {item.image_url ? (
            <img src={item.image_url} alt="" style={{ mixBlendMode: 'multiply' }} className="w-16 h-16 object-contain flex-shrink-0" />
          ) : (
            <div className="w-16 h-16 bg-white border rounded flex-shrink-0 flex items-center justify-center text-[9px] uppercase text-gray-300">No image</div>
          )}
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase tracking-widest font-bold text-green-700">But this one is →</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500 truncate">{partLabel}</div>
            <div className="text-sm font-semibold text-gray-900 line-clamp-1">{item.name}</div>
            <div className="flex items-baseline gap-2 mt-0.5">
              {item.retail_price != null && (
                <span className="text-sm font-bold text-gray-900">${item.retail_price.toFixed(2)}</span>
              )}
              <span className="text-[11px] text-green-700 font-semibold">{item.stock_total} in stock</span>
            </div>
          </div>
        </div>
      </div>
    </Link>
  )
}


function LikeProductsRail({ sku, sourceOOS = false }: { sku: string; sourceOOS?: boolean }) {
  const { ymm } = useApp()
  const [items, setItems] = useState<AlternateItem[]>([])
  const [mode, setMode] = useState<string>('')
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    setLoading(true)
    const params = new URLSearchParams()
    if (ymm?.base_vehicle_id) params.set('base_vehicle_id', String(ymm.base_vehicle_id))
    // When the source product is OOS, prefer in-stock alternates so the
    // rail isn't a wall of "Special order" cousins. Owner ask 2026-05-17.
    if (sourceOOS) params.set('in_stock_only', 'true')
    const qs = params.toString() ? `?${params.toString()}` : ''
    fetch(`/api/catalog/products/${encodeURIComponent(sku)}/alternates${qs}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => {
        setItems(d?.items || [])
        setMode(d?.mode || '')
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [sku, ymm?.base_vehicle_id, sourceOOS])
  if (loading) return null
  if (items.length === 0) return null
  const heading = sourceOOS
    ? (ymm ? `Available now for your ${ymm.year} ${ymm.make_name} ${ymm.model_name}` : 'Available now')
    : mode === 'for_vehicle'
      ? (ymm ? `Other parts for your ${ymm.year} ${ymm.make_name} ${ymm.model_name}` : 'Other parts for your truck')
      : 'Like this part'
  return (
    <section className="bg-gray-50 border-t">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <h2 className="text-lg font-bold text-gray-900 mb-4">{heading}</h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-4 gap-3">
          {items.map((it) => (
            <Link
              key={it.id}
              to={`/product/${it.sku}`}
              className="group flex flex-col bg-white rounded overflow-hidden shadow-[0_1px_4px_rgba(0,0,0,0.05)] hover:shadow-[0_4px_10px_rgba(0,0,0,0.1)] transition-shadow"
            >
              <div className="aspect-square bg-white flex items-center justify-center overflow-hidden">
                {it.image_url ? (
                  <img src={it.image_url} alt="" loading="lazy" style={{ mixBlendMode: 'multiply' }} className="w-[82%] h-[82%] object-contain group-hover:scale-105 transition-transform duration-200" />
                ) : (
                  <div className="text-[10px] uppercase text-gray-300">No image</div>
                )}
              </div>
              <div className="p-2 border-t border-gray-100">
                <div className="text-[10px] uppercase tracking-wider text-gray-500">{it.brand}</div>
                <div className="font-mono text-[10px] text-gray-500 truncate">{formatPartNumber(it.sku, it.brand)}</div>
                <div className="text-xs text-gray-900 mt-0.5 line-clamp-2 leading-snug">{it.name}</div>
                <div className="mt-1.5 flex items-center justify-between text-[11px]">
                  {it.in_stock ? (
                    <span className="text-green-700 font-semibold">In stock</span>
                  ) : (
                    <span className="text-gray-500">Special order</span>
                  )}
                  {it.retail_price != null && (
                    <span className="text-gray-900 font-bold">${it.retail_price.toFixed(2)}</span>
                  )}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  )
}


// =========================================================================
// Hot Products + Featured Brands widgets
// =========================================================================

function YmmFitmentBadge() {
  const { ymm, setYmmOpen } = useApp()
  if (!ymm) {
    return (
      <div className="mt-3 text-xs">
        <span className="text-gray-500">Verify fitment for your truck — </span>
        <button
          onClick={() => setYmmOpen(true)}
          className="text-red-700 hover:underline font-semibold"
        >
          Set your vehicle
        </button>
      </div>
    )
  }
  return (
    <div className="mt-3 inline-flex items-center gap-2 px-3 py-1 bg-blue-50 border border-blue-200 rounded-full text-xs">
      <svg className="w-3 h-3 text-blue-700" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M5 17h14M5 17a2 2 0 100 4 2 2 0 000-4zm14 0a2 2 0 100 4 2 2 0 000-4zm-1-9l3 5h-3M3 7h11l4 6"/>
      </svg>
      <span className="text-blue-900">Verify for your <strong>{ymm.year} {ymm.make_name} {ymm.model_name}</strong></span>
    </div>
  )
}

function HotProductsWidget({ limit = 6 }: { limit?: number }) {
  const [items, setItems] = useState<HotProduct[]>([])
  useEffect(() => {
    fetch(`/api/catalog/hot-products?limit=${limit}`).then((r) => r.json()).then(setItems).catch(() => {})
  }, [limit])
  if (items.length === 0) return null
  return (
    <div className="border rounded p-4 bg-white">
      <div className="text-xs uppercase tracking-wider text-red-700 font-bold mb-3 flex items-center gap-1">
        🔥 Hot products
      </div>
      <div className="space-y-3">
        {items.map((p) => (
          <Link key={p.sku} to={`/product/${p.sku}`} className="flex items-center gap-3 group">
            <img src={p.image_url} alt="" loading="lazy" className="w-12 h-12 object-contain bg-gray-50 border rounded" />
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] text-gray-500 truncate">{formatPartNumber(p.sku, p.brand)}</div>
              <div className="text-xs text-gray-900 line-clamp-2 group-hover:text-red-700">{p.name}</div>
              {p.in_stock && <div className="text-[10px] text-green-700 font-semibold">{p.stock_total} in stock</div>}
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

function ImageGallery({ images, name }: { images: { url: string; alt: string | null }[]; name: string }) {
  const [active, setActive] = useState(0)
  if (!images || images.length === 0) {
    return <div className="aspect-square bg-gray-100 border rounded flex items-center justify-center text-gray-400">No image</div>
  }
  const main = images[active] || images[0]
  return (
    <div>
      <div className="aspect-square bg-white border rounded flex items-center justify-center overflow-hidden">
        <img src={main.url} alt={main.alt || name} className="w-full h-full object-contain" />
      </div>
      {images.length > 1 && (
        <div className="mt-3 flex gap-2 overflow-x-auto">
          {images.map((img, i) => (
            <button
              key={img.url}
              onClick={() => setActive(i)}
              className={`shrink-0 w-16 h-16 border-2 rounded overflow-hidden ${
                i === active ? 'border-red-700' : 'border-gray-200 hover:border-gray-400'
              }`}
            >
              <img src={img.url} alt="" className="w-full h-full object-contain bg-white" />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// PACE-style product list-view row — bigger image on left, brand + SKU +
// name + brief description on right, stock/CTA on far right.
/** Inline add-to-cart control for grid + list cards.
 *
 *  Owner ask 2026-05-17: customer should be able to order from the
 *  catalog grid or list view without clicking through to the PDP.
 *  OOS products in cta_mode='add_to_cart' are still orderable as
 *  "Special order" — the manufacturer's lead time will be surfaced
 *  here once we have per-brand lead-time data (queued).
 */
function InlineAddToOrder({ h, variant = 'list' }: { h: BrowseHit; variant?: 'list' | 'grid' }) {
  const { addToCart } = useApp()
  const [qty, setQty] = useState(1)
  const [adding, setAdding] = useState(false)
  const [added, setAdded] = useState(false)

  if (h.cta_mode === 'browse_only') return null
  if (h.cta_mode === 'quote_shipping') {
    return (
      <Link
        to={`/product/${h.sku}`}
        onClick={(e) => e.stopPropagation()}
        className={`block text-center font-semibold rounded ${
          variant === 'grid' ? 'px-2 py-1.5 text-xs' : 'px-3 py-2 text-sm'
        } bg-orange-600 hover:bg-orange-700 text-white`}
      >
        Get Quote
      </Link>
    )
  }

  async function onAdd(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    setAdding(true)
    try {
      await addToCart(h.sku, qty)
      setAdded(true)
      setTimeout(() => setAdded(false), 2000)
    } finally {
      setAdding(false)
    }
  }

  const isOOS = !h.in_stock
  // On phones each grid card is ~150px wide — qty + button side-by-side
  // squeezes the label into 3 lines ("Add / to / Cart"). Stack them on
  // mobile, side-by-side at sm:+ where there's room.
  return (
    <div className={`flex flex-col sm:flex-row items-stretch gap-1 ${variant === 'grid' ? 'text-xs' : 'text-sm'}`}>
      <input
        type="number"
        min={1}
        max={999}
        value={qty}
        onChange={(e) => {
          e.stopPropagation()
          setQty(Math.max(1, parseInt(e.target.value) || 1))
        }}
        onClick={(e) => e.stopPropagation()}
        className={`w-full sm:w-12 border border-gray-300 rounded px-1 text-center ${
          variant === 'grid' ? 'py-1 text-xs' : 'py-2 text-sm'
        }`}
      />
      <button
        type="button"
        onClick={onAdd}
        disabled={adding}
        title={isOOS ? 'Not in stock — we will source this from the manufacturer' : `${h.stock_total} in stock`}
        className={`flex-1 whitespace-nowrap font-semibold rounded transition disabled:opacity-50 ${
          variant === 'grid' ? 'px-2 py-1.5 sm:py-1' : 'px-3 py-2'
        } ${
          added
            ? 'bg-green-600 text-white'
            : 'bg-red-700 hover:bg-red-800 text-white'
        }`}
      >
        {adding ? 'Adding…' : added ? '✓ Added' : 'Add to Cart'}
      </button>
    </div>
  )
}


// NotifyBackInStock — small inline button + email field. Available to
// anyone (not gated to B2B like Lost Sale) because anonymous retail is
// the highest-volume audience for back-in-stock signals. Owner ask
// 2026-05-17 (L7). Posts to /api/signals/back-in-stock; backend dedups
// at (sku, email).
function NotifyBackInStock({ sku }: { sku: string }) {
  const { user } = useApp()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState<string>(user?.email || '')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    e.stopPropagation()
    const trimmed = email.trim()
    if (!trimmed) { setError('Email required'); return }
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch('/api/signals/back-in-stock', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku, email: trimmed }),
      })
      if (r.ok) {
        setSubmitted(true)
      } else {
        const data = await r.json().catch(() => ({}))
        setError(typeof data?.detail === 'string' ? data.detail : 'Could not save. Try again.')
      }
    } catch {
      setError('Network error. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return <div className="text-[11px] text-green-700 px-2 py-1.5 text-center">✓ We&apos;ll email you when it&apos;s back</div>
  }
  if (!open) {
    return (
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true) }}
        className="px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50 text-gray-700 text-xs"
      >
        🔔 Notify me when back in stock
      </button>
    )
  }
  return (
    <form onSubmit={submit} className="border border-blue-200 bg-blue-50 rounded p-2 text-[11px] space-y-1" onClick={(e) => e.stopPropagation()}>
      <div className="font-semibold text-blue-900 mb-1">Email me when this is back</div>
      <input
        type="email"
        autoFocus
        required
        value={email}
        placeholder="you@example.com"
        onChange={(e) => setEmail(e.target.value)}
        onClick={(e) => e.stopPropagation()}
        className="w-full border border-gray-300 rounded px-2 py-1 text-xs"
      />
      <div className="flex gap-1.5">
        <button
          type="submit"
          disabled={submitting}
          className="flex-1 bg-red-700 hover:bg-red-800 text-white font-semibold py-1 rounded disabled:opacity-50"
        >{submitting ? 'Saving…' : 'Subscribe'}</button>
        <button
          type="button"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); setError(null) }}
          className="px-2 py-1 text-gray-600 hover:bg-gray-100 rounded"
        >Cancel</button>
      </div>
      {error && <div className="text-red-700">{error}</div>}
    </form>
  )
}


function ProductListRow({ h, vehicleId }: { h: BrowseHit; vehicleId?: number }) {
  // Lost-Sale flow renders inline on the row when the product is OOS.
  // Owner ask 2026-05-17: only show this to B2B logins (jobber/dealer).
  // Retail and anonymous customers don't see it — they get the
  // "Add to Cart" special-order path instead, which is more useful at
  // their decision point. Submits to /api/signals/lost-sale.
  const { user, recentSkus } = useApp()
  const isB2B = user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer'
  const reordered = recentSkus.has(h.sku)
  const [showLostSale, setShowLostSale] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submittedReason, setSubmittedReason] = useState<string | null>(null)
  // Fitment expander — fetches full fitment groups from /products/{sku}/fitments
  // on first click; collapses on second click. Lets the customer see every
  // vehicle this product fits without leaving the catalog page.
  const [fitmentExpanded, setFitmentExpanded] = useState(false)
  const [fullFitment, setFullFitment] = useState<FitmentResponse | null>(null)
  const [fitmentLoading, setFitmentLoading] = useState(false)
  async function toggleFitment() {
    if (fitmentExpanded) { setFitmentExpanded(false); return }
    if (!fullFitment) {
      setFitmentLoading(true)
      try {
        const r = await fetch(`/api/catalog/products/${encodeURIComponent(h.sku)}/fitments`)
        if (r.ok) setFullFitment(await r.json())
      } finally {
        setFitmentLoading(false)
      }
    }
    setFitmentExpanded(true)
  }

  async function submitLostSale(reason: string) {
    setSubmitting(true)
    try {
      const r = await fetch('/api/signals/lost-sale', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sku: h.sku, reason }),
      })
      if (r.ok) {
        setSubmittedReason(reason)
        setShowLostSale(false)
      }
    } finally {
      setSubmitting(false)
    }
  }

  // Strip the legacy WSM prefix for the prominent part-number display
  // ("BHTJ-449491" → "449491"). Mirrors PACE's "Part #: 34389T" treatment
  // where the manufacturer's part number is the headline identifier.
  const displayPartNumber = (() => {
    if (!h.sku) return ''
    const idx = h.sku.indexOf('-')
    return idx > 0 && idx < 6 ? h.sku.slice(idx + 1) : h.sku
  })()

  const showPrice = h.retail_price != null
  const onSale = h.sale_price != null && h.retail_price != null && h.sale_price < h.retail_price

  return (
    <div className="group flex flex-col sm:flex-row gap-4 bg-white rounded-lg overflow-hidden shadow-[0_3px_10px_rgba(0,0,0,0.14)] hover:shadow-[0_8px_22px_rgba(0,0,0,0.22)] transition-shadow p-3">
      {/* On mobile: image + info sit side-by-side at the top, then the
          price/CTA rail stacks full-width below (so the description
          column has the whole screen-width minus the image to wrap into).
          On sm:+ the inner group is just a flex container that lays
          image and info beside each other, with the rail as the third
          column on the right (same look as desktop today). */}
      <div className="flex flex-row gap-4 flex-1 min-w-0">
      {/* IMAGE — clickable through to PDP. mix-blend-mode: multiply on the
          image blends the white product-photo background into the white
          row card so the silhouette floats without a visible square frame.
          drop-shadow is omitted because filter creates an isolated stacking
          context that traps the blend (same reason as the category-tile fix). */}
      {/* Image column — stacks the in-stock-substitute callout directly
          below the image when this row is OOS. Owner ask 2026-05-17. */}
      <div className="flex-shrink-0 flex flex-col gap-1.5 w-28 sm:w-32">
        <Link to={`/product/${h.sku}`} className="w-28 h-28 sm:w-32 sm:h-32 flex items-center justify-center overflow-hidden">
          {h.image_url ? (
            <img
              src={h.image_url}
              alt={h.name}
              loading="lazy"
              style={{ mixBlendMode: 'multiply' }}
              className="w-[90%] h-[90%] object-contain group-hover:scale-105 transition-transform duration-200"
            />
          ) : (
            <div className="text-center px-2">
              <div className="text-[10px] uppercase tracking-widest text-gray-600 font-bold leading-tight">{h.brand}</div>
              <div className="text-gray-300 text-[10px] uppercase mt-1">No image</div>
            </div>
          )}
        </Link>
        {!h.in_stock && <InStockSubstituteCallout sku={h.sku} variant="compact" vehicleId={vehicleId} />}
      </div>

      {/* INFO COLUMN — PACE-style hierarchy: Part # is the headline */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Part # as the prominent red header, like PACE's "Part #: 34389T" */}
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            to={`/product/${h.sku}`}
            className="text-lg font-bold text-red-700 hover:text-red-800 leading-tight"
          >
            Part #: {displayPartNumber}
          </Link>
          {reordered && (
            <span className="bg-green-100 text-green-800 border border-green-200 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider" title="You've ordered this before in the last 12 months">
              Reordered
            </span>
          )}
        </div>

        {/* Stock + locations + categories — single inline row */}
        <div className="flex items-center gap-3 text-xs mt-1 flex-wrap">
          {h.in_stock ? (
            <span className="text-green-700 font-bold">
              ✓ {h.stock_total >= 5 ? '5+' : h.stock_total} Available
            </span>
          ) : (
            // OOS in cta_mode='add_to_cart' is still orderable as a
            // special order. Brand-level lead-time (L9) tacks a parenthetical
            // "(typically X-Y business days)" so the customer knows what
            // they're committing to. Falls back to bare "Special order"
            // when the brand hasn't been configured.
            <span className="text-gray-600 font-semibold">
              Special order
              {(() => {
                const lt = formatLeadTime(h.special_order_lead_time_min_days, h.special_order_lead_time_max_days)
                return lt ? <span className="font-normal text-gray-500"> · {lt}</span> : null
              })()}
            </span>
          )}
          {h.in_stock && h.locations_count != null && h.locations_count > 0 && (
            <span className="text-gray-500">
              Locations ({h.locations_count})
            </span>
          )}
          {h.cta_mode === 'quote_shipping' && <span className="text-orange-600 font-semibold">Quote ship</span>}
          {h.cta_mode === 'browse_only' && <span className="text-gray-500 font-semibold">Browse only</span>}
        </div>

        {/* Brand · Series links — secondary identity row, mirrors PACE
            where Brand and Series are clickable refinements */}
        <div className="text-xs mt-2 text-gray-700">
          <span className="font-semibold text-gray-600">Brand: </span>
          {h.brand && (
            <Link
              to={`/catalog?brand=${encodeURIComponent(h.brand)}`}
              className="text-red-700 hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {h.brand}
            </Link>
          )}
          {h.series && (
            <>
              <span className="text-gray-400 mx-1">/</span>
              <Link
                to={`/catalog?brand=${encodeURIComponent(h.brand || '')}&q=${encodeURIComponent(h.series)}`}
                className="text-red-700 hover:underline"
                onClick={(e) => e.stopPropagation()}
              >
                {h.series}
              </Link>
            </>
          )}
        </div>

        {/* Product name + description — the long-form details */}
        <div className="text-xs mt-1.5 text-gray-700">
          <span className="font-semibold text-gray-600">Description: </span>
          <span>{h.name}</span>
          {h.description && (
            <span className="text-gray-600">; {h.description}</span>
          )}
        </div>
        {/* Application Summary — shows the first ~2 fitments inline, or
            "Universal" when the product has no vehicle fitments. If there
            are more groups than fit on two lines, an arrow expands the row
            to fetch and show the full vehicle list. Owner ask 2026-05-17. */}
        <div className="text-xs mt-1.5">
          <span className="font-semibold text-gray-600">Application Summary: </span>
          {h.fitment_universal ? (
            <span className="text-gray-700">Universal — fits all vehicles</span>
          ) : (h.fitment_summary && h.fitment_summary.length > 0) ? (
            <span className="text-gray-700">
              {h.fitment_summary.join(' · ')}
              {(h.fitment_group_count || 0) > h.fitment_summary.length && (
                <span className="text-gray-500">
                  {' '}· +{(h.fitment_group_count || 0) - h.fitment_summary.length} more
                </span>
              )}
              {(h.fitment_group_count || 0) > 0 && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); toggleFitment() }}
                  className="ml-2 text-red-700 hover:underline font-semibold"
                  title={fitmentExpanded ? 'Collapse' : 'Show all applications'}
                >
                  {fitmentLoading ? '…' : fitmentExpanded ? '▴ Hide' : '▾ Show all'}
                </button>
              )}
            </span>
          ) : (
            <span className="text-gray-500">No fitment data</span>
          )}
        </div>
        {/* Expanded full fitment list — appears below the row when toggled.
            Grouped by make so a wide-coverage product reads as "Ford: F-150,
            Ranger, Maverick; Chevy: Silverado, Colorado; …" */}
        {fitmentExpanded && fullFitment && (
          <div className="text-xs mt-2 p-2 border-l-2 border-red-200 bg-red-50 rounded-r space-y-1">
            {fullFitment.groups.map((g) => (
              <div key={g.make}>
                <span className="font-bold text-gray-900">{g.make}:</span>{' '}
                <span className="text-gray-700">
                  {g.models.map((m, i) => {
                    const yr = m.year_start && m.year_end
                      ? (m.year_start === m.year_end ? `${m.year_start}` : `${m.year_start}-${m.year_end}`)
                      : ''
                    return (
                      <span key={i}>
                        {i > 0 && <span className="text-gray-400">, </span>}
                        {yr} {m.model}
                      </span>
                    )
                  })}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
      </div>

      {/* RIGHT RAIL — price + actions. Lost-Sale UI only renders when OOS
          so the customer's "I needed this and you didn't have it" signal
          gets captured at the exact moment of frustration. On mobile this
          rail goes full-width below the image+info group; on sm:+ it
          becomes the third column on the right of the row. */}
      <div className="flex flex-col items-stretch gap-2 text-xs sm:flex-shrink-0 sm:min-w-[170px] text-sm sm:text-xs">
        {/* Pricing block. Logged-in B2B customers see their contract-
            resolved "Your Cost" on top with MAP/Retail as a strikethrough
            reference. Anonymous / retail customers fall through to the
            simple Retail line. Owner ask 2026-05-17 (L1). */}
        {h.tier_pricing && h.tier_pricing.primary_amount && (h.tier_pricing.tier === 'jobber' || h.tier_pricing.tier === 'dealer' || h.tier_pricing.tier === 'municipality') ? (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
              {h.tier_pricing.primary_label}
            </div>
            <div className="flex items-baseline justify-end gap-1.5">
              <span className="text-lg font-bold text-red-700">
                ${parseFloat(h.tier_pricing.primary_amount).toFixed(2)}
              </span>
              <span className="text-[10px] text-gray-500">USD</span>
            </div>
            {h.tier_pricing.secondary_amount && (
              <div className="text-[11px] text-gray-500 mt-0.5">
                {h.tier_pricing.secondary_label}:{' '}
                <span className="line-through">${parseFloat(h.tier_pricing.secondary_amount).toFixed(2)}</span>
              </div>
            )}
            {h.tier_pricing.contract_name && (
              <div className="text-[10px] text-gray-400 mt-0.5" title={h.tier_pricing.contract_name}>
                via contract
              </div>
            )}
          </div>
        ) : showPrice ? (
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
              Retail
            </div>
            <div className="flex items-baseline justify-end gap-1.5">
              {onSale && (
                <span className="text-xs text-gray-400 line-through">
                  ${h.retail_price?.toFixed(2)}
                </span>
              )}
              <span className="text-lg font-bold text-gray-900">
                ${(onSale ? h.sale_price : h.retail_price)?.toFixed(2)}
              </span>
              <span className="text-[10px] text-gray-500">USD</span>
            </div>
          </div>
        ) : null}
        <InlineAddToOrder h={h} variant="list" />
        <Link
          to={`/product/${h.sku}`}
          className="text-center px-3 py-1.5 border border-gray-300 text-gray-700 text-sm font-semibold rounded hover:bg-gray-50"
          onClick={(e) => e.stopPropagation()}
        >
          View details
        </Link>
        <CompareToggleButton sku={h.sku} variant="list" />
        {!h.in_stock && !submittedReason && !showLostSale && isB2B && (
          <button
            onClick={() => setShowLostSale(true)}
            className="px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50 text-gray-700"
            title="Tell us you needed this in stock"
          >
            Log lost sale
          </button>
        )}
        {!h.in_stock && <NotifyBackInStock sku={h.sku} />}
        {showLostSale && !submittedReason && isB2B && (
          <div className="border border-orange-200 bg-orange-50 rounded p-2 text-[11px] space-y-1">
            <div className="font-semibold text-orange-900 mb-1">Why did you skip it?</div>
            {[
              { v: 'out_of_stock', l: 'Out of stock' },
              { v: 'shipping_time', l: 'Shipping too slow' },
              { v: 'price_too_high', l: 'Price too high' },
              { v: 'found_elsewhere', l: 'Found elsewhere' },
              { v: 'wrong_fitment', l: 'Wrong fitment' },
              { v: 'other', l: 'Other' },
            ].map((opt) => (
              <button
                key={opt.v}
                disabled={submitting}
                onClick={() => submitLostSale(opt.v)}
                className="w-full text-left px-2 py-1 rounded hover:bg-orange-100 disabled:opacity-50"
              >
                {opt.l}
              </button>
            ))}
            <button
              onClick={() => setShowLostSale(false)}
              className="text-gray-500 hover:text-gray-700 text-[10px] mt-1"
            >
              cancel
            </button>
          </div>
        )}
        {submittedReason && (
          <div className="text-[11px] text-green-700 px-2 py-1.5 text-center">
            ✓ Thanks — logged
          </div>
        )}
      </div>
    </div>
  )
}

function ProductCard({ h, vehicleId }: { h: BrowseHit; vehicleId?: number }) {
  const { recentSkus, user } = useApp()
  const reordered = recentSkus.has(h.sku)
  // Shipping-mode labels are retail-only (B2B has a separate freight program).
  const isRetail = !user?.customer_tier || user.customer_tier === 'retail'
  const shipBadge = isRetail && (h.shipping_mode === 'truck_freight'
    ? { label: 'Truck Freight', cls: 'bg-amber-500' }
    : h.shipping_mode === 'will_call'
      ? { label: 'Will Call', cls: 'bg-blue-600' }
      : null)
  return (
    <Link
      to={`/product/${h.sku}`}
      className="group relative flex flex-col bg-white rounded-lg overflow-hidden shadow-[0_3px_10px_rgba(0,0,0,0.14)] hover:shadow-[0_8px_22px_rgba(0,0,0,0.22)] transition-shadow"
    >
      {shipBadge && (
        <span className={`absolute left-1.5 top-1.5 z-10 flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide text-white ${shipBadge.cls}`}>
          🚚 {shipBadge.label}
        </span>
      )}
      {/* Product image. mix-blend-mode: multiply blends the JPEG's white
          canvas into the white card so the silhouette reads cleanly with
          no per-image white square. Card-level shadow does the "lifted"
          look; drop-shadow on the img would create an isolated stacking
          context and trap the blend. Owner ask 2026-05-17. */}
      <div className="aspect-square flex items-center justify-center overflow-hidden">
        {h.image_url ? (
          <img
            src={thumbUrl(h.image_url) || h.image_url}
            srcSet={`${thumbUrl(h.image_url)} 400w, ${h.image_url} 1280w`}
            sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 22vw"
            alt={h.name}
            loading="lazy"
            style={{ mixBlendMode: 'multiply' }}
            className="w-[82%] h-[82%] object-contain group-hover:scale-105 transition-transform duration-200"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
          />
        ) : (
          <div className="px-4 text-center">
            <div className="text-[10px] uppercase tracking-widest text-gray-600 font-bold">{h.brand}</div>
            <div className="text-gray-300 text-[10px] uppercase tracking-wider mt-2">No image</div>
          </div>
        )}
      </div>
      <div className="p-3 flex-1 flex flex-col border-t border-gray-100">
        <div className="text-[10px] uppercase tracking-wider text-gray-500 mb-1 flex items-center gap-1.5">
          <span>{h.brand}</span>
          {reordered && (
            <span className="bg-green-100 text-green-800 border border-green-200 px-1 py-px rounded text-[9px] font-bold normal-case tracking-normal" title="You've ordered this before in the last 12 months">
              Reordered
            </span>
          )}
        </div>
        <div className="font-mono text-xs text-gray-500">{formatPartNumber(h.sku, h.brand)}</div>
        <div className="font-medium text-sm mt-1 line-clamp-2 text-gray-900 flex-1">{h.name}</div>
        <div className="mt-2 flex items-center justify-between text-xs">
          {h.in_stock ? (
            <span className="text-green-700 font-semibold">{h.stock_total} in stock</span>
          ) : (
            <span className="text-gray-500" title={formatLeadTime(h.special_order_lead_time_min_days, h.special_order_lead_time_max_days) || undefined}>
              Special order
            </span>
          )}
          {/* B2B sees Your Cost in red bold; retail sees Retail in black */}
          {h.tier_pricing && h.tier_pricing.primary_amount && (h.tier_pricing.tier === 'jobber' || h.tier_pricing.tier === 'dealer' || h.tier_pricing.tier === 'municipality') ? (
            <span className="text-right" title={h.tier_pricing.contract_name || h.tier_pricing.primary_label}>
              <span className="text-red-700 font-bold">${parseFloat(h.tier_pricing.primary_amount).toFixed(2)}</span>
              {h.tier_pricing.secondary_amount && (
                <span className="text-gray-400 line-through ml-1 text-[10px]">${parseFloat(h.tier_pricing.secondary_amount).toFixed(2)}</span>
              )}
            </span>
          ) : h.retail_price != null ? (
            <span className="text-gray-900 font-bold">${h.retail_price.toFixed(2)}</span>
          ) : null}
        </div>
        {/* OOS → show the in-stock substitute callout directly above the
            Add-to-Cart + Compare row so the green "get one today" off-ramp
            sits next to the buy action. Owner ask 2026-05-17. */}
        {!h.in_stock && (
          <div className="mt-2">
            <InStockSubstituteCallout sku={h.sku} variant="compact" vehicleId={vehicleId} />
          </div>
        )}
        {/* Inline Add-to-Order — owner ask 2026-05-17: customer should be
            able to order from grid view, not just click through to PDP.
            Component handles cta_mode variants (quote_shipping → Get Quote;
            browse_only → nothing) and OOS → "Special order".
            Stacks vertically on phone (qty + Add-to-Cart get full card width,
            Compare drops below) and goes side-by-side at sm:+ where the
            card is wider. */}
        {/* flex-wrap so that on a narrow 4-col grid card (~<1340px) where qty +
            Add-to-Cart + Compare can't share one row, Compare drops to its own
            line instead of overflowing the card's right edge. Do NOT add min-w-0
            to the Add-to-Cart group: it lets that item shrink below its content
            width, so the nowrap "Add to Cart" button overflows UNDER Compare
            instead of triggering the wrap. Keeping min-width:auto (min-content)
            is what makes flex-wrap push Compare to its own line. */}
        <div className="mt-2 flex flex-col sm:flex-row sm:flex-wrap sm:items-center gap-2">
          <div className="flex-1 w-full sm:w-auto"><InlineAddToOrder h={h} variant="grid" /></div>
          <div className="self-start sm:self-auto"><CompareToggleButton sku={h.sku} variant="card" /></div>
        </div>
      </div>
    </Link>
  )
}

/** FacetGroup — collapsible accordion-style filter group.
 *
 *  Restyled 2026-05-14 to match nelsontruck.com's left-side nav pattern:
 *  each filter dimension is a vertical accordion with a header that
 *  toggles open/closed.  Active value bolded; click to clear.
 */
function FacetGroup({
  title, items, activeValue, activeValues, multiSelect = false,
  onPick, onToggle, defaultOpen = true,
}: {
  title: string
  items: { value: string; count: number }[]
  activeValue?: string                 // single-select mode
  activeValues?: Set<string>           // multi-select mode
  multiSelect?: boolean
  onPick?: (v: string | null) => void  // single-select callback
  onToggle?: (v: string) => void       // multi-select callback (adds/removes)
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  if (!items || items.length === 0) return null
  return (
    <div className="border rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-gray-50 hover:bg-gray-100 border-b text-left"
      >
        <span className="font-bold text-xs uppercase tracking-widest text-gray-800">{title}</span>
        <span className="text-gray-400 text-sm">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="p-2 space-y-0.5 max-h-72 overflow-auto">
          {items.map((b) => {
            const isOn = multiSelect
              ? !!activeValues?.has(b.value)
              : activeValue === b.value
            return (
              <button
                key={b.value}
                onClick={() => {
                  if (multiSelect) onToggle?.(b.value)
                  else onPick?.(isOn ? null : b.value)
                }}
                className={`flex items-center w-full text-left text-xs px-2 py-1 rounded hover:bg-gray-100 ${
                  isOn ? 'bg-red-50 text-red-700 font-semibold' : 'text-gray-700'
                }`}
              >
                {multiSelect && (
                  <span
                    className={`inline-block w-3 h-3 mr-2 border rounded-sm flex-shrink-0 ${
                      isOn ? 'bg-red-700 border-red-700' : 'border-gray-300 bg-white'
                    }`}
                    aria-hidden="true"
                  />
                )}
                <span className="flex-1 truncate">{b.value}</span>
                <span className="text-gray-400 ml-1">({b.count.toLocaleString()})</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}


type AttrValue = { value: string; uom: string | null; count: number }
type AttrFacet = {
  key: string
  products_with_key: number
  distinct_values: number
  values: AttrValue[]
}
type CategoryAttributesResponse = {
  attributes: AttrFacet[]
  products_total: number
  products_with_attributes: number
}

const _attrCache = new Map<string, CategoryAttributesResponse>()

/** CategoryAttributeFacets — per-subcategory PIES attribute drill-down.
 *
 *  Owner ask 2026-05-17: "We need to have a further left navigation drill
 *  down when a customer chooses a subcategory… Each drill down will be
 *  different depending on the attributes of that specific subcategory."
 *  Fetches /api/catalog/category-attributes for the active category and
 *  renders one multi-select group per surfaced attribute key. Matches the
 *  FacetGroup look so the left rail stays visually coherent.
 *
 *  Filter semantics: same key + multiple values = OR (any-of); different
 *  keys = AND. Selected pairs are encoded as 'Key|Value' in the `attr`
 *  URL param (repeatable) which the backend's `_browse_via_pace` reads.
 */
function CategoryAttributeFacets({
  categoryTop,
  categoryPath,
  baseVehicleId,
  vehicleType,
  selected,
  onToggle,
}: {
  categoryTop: string
  categoryPath: string
  baseVehicleId: number | null
  vehicleType: string
  selected: Set<string>
  onToggle: (pair: string) => void
}) {
  const cacheKey = `${categoryTop}||${categoryPath}||${baseVehicleId ?? ''}||${vehicleType}`
  const [data, setData] = useState<CategoryAttributesResponse | null>(_attrCache.get(cacheKey) || null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!categoryTop && !categoryPath) {
      setData(null)
      return
    }
    const cached = _attrCache.get(cacheKey)
    if (cached) {
      setData(cached)
      return
    }
    setLoading(true)
    const url = new URL('/api/catalog/category-attributes', window.location.origin)
    if (categoryTop) url.searchParams.set('category_top', categoryTop)
    if (categoryPath) url.searchParams.set('category_path', categoryPath)
    if (baseVehicleId) url.searchParams.set('base_vehicle_id', String(baseVehicleId))
    if (vehicleType) url.searchParams.set('vehicle_type', vehicleType)
    fetch(url)
      .then((r) => r.json())
      .then((d: CategoryAttributesResponse) => {
        _attrCache.set(cacheKey, d)
        setData(d)
      })
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [cacheKey, categoryTop, categoryPath, baseVehicleId, vehicleType])

  if (!categoryTop && !categoryPath) return null
  if (loading && !data) {
    return (
      <div className="border rounded-lg bg-white px-3 py-3 text-xs text-gray-500">
        Loading filters…
      </div>
    )
  }
  if (!data || data.attributes.length === 0) {
    if (data && data.products_total > 0) {
      // Surface the coverage so the user knows why no filters appeared.
      const coverage = data.products_total > 0
        ? Math.round((data.products_with_attributes / data.products_total) * 100)
        : 0
      return (
        <div className="border rounded-lg bg-white px-3 py-3 text-[11px] text-gray-500">
          No drill-down filters yet for this subcategory.
          <div className="text-[10px] text-gray-400 mt-1">
            {data.products_with_attributes.toLocaleString()} of {data.products_total.toLocaleString()} products
            have PIES attribute data ({coverage}%).
          </div>
        </div>
      )
    }
    return null
  }

  const coverage = data.products_total > 0
    ? Math.round((data.products_with_attributes / data.products_total) * 100)
    : 0

  return (
    <div className="space-y-3">
      {data.attributes.map((attr) => (
        <AttributeFacetGroup
          key={attr.key}
          attr={attr}
          selected={selected}
          onToggle={onToggle}
        />
      ))}
      {/* Coverage footnote — tells the user how many products in this
          subcategory have PIES attribute data. Helps reason about why
          some products may not surface when filters are applied. */}
      {coverage < 100 && (
        <div className="text-[10px] text-gray-500 px-1">
          Filters cover {data.products_with_attributes.toLocaleString()} of
          {' '}{data.products_total.toLocaleString()} products in this subcategory ({coverage}%).
          Products without PIES attribute data are hidden when a filter is on.
        </div>
      )}
    </div>
  )
}

function AttributeFacetGroup({ attr, selected, onToggle }: {
  attr: AttrFacet
  selected: Set<string>
  onToggle: (pair: string) => void
}) {
  const [open, setOpen] = useState(true)
  return (
    <div className="border rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-gray-50 hover:bg-gray-100 border-b text-left"
      >
        <span className="font-bold text-xs uppercase tracking-widest text-gray-800">{attr.key}</span>
        <span className="text-gray-400 text-sm">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="p-2 space-y-0.5">
          {attr.values.map((v) => {
            const pair = `${attr.key}|${v.value}`
            const isOn = selected.has(pair)
            const label = v.uom ? `${v.value} ${v.uom}` : v.value
            return (
              <button
                key={pair}
                onClick={() => onToggle(pair)}
                className={`w-full flex items-center text-left text-xs px-2 py-1 rounded hover:bg-gray-100 ${
                  isOn ? 'bg-red-50 text-red-700 font-semibold' : 'text-gray-700'
                }`}
              >
                <span
                  className={`inline-block w-3 h-3 mr-2 border rounded-sm flex-shrink-0 ${
                    isOn ? 'bg-red-700 border-red-700' : 'border-gray-300 bg-white'
                  }`}
                  aria-hidden="true"
                />
                <span className="flex-1 truncate">{label}</span>
                <span className="text-gray-400 ml-1">({v.count.toLocaleString()})</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}


/** CategoryDrillNav — sidebar-style category tree navigator.
 *
 *  Owner ask 2026-05-14: "I want the new site to have a similar look at
 *  the side navigation drill down on titantruck."  Vertical
 *  collapsible tree with the current category highlighted.  Shows:
 *
 *   * Parent / ancestor breadcrumb (click to go up)
 *   * Sibling categories at the current level
 *   * Direct children of the current category (drill down)
 *
 *  Category-specific by construction — the tree always re-roots at the
 *  active node so the filters always reflect where the user is now.
 */
function CategoryDrillNav({
  tree,
  currentCategory,
  onPick,
}: {
  tree: CategoryNode[] | null
  currentCategory: CategoryNode | null
  onPick: (full_path: string | null) => void
}) {
  // When no category is selected, show the top-level categories as a
  // browse-by-department list — same widget reused on the "All products"
  // landing where the sidebar would otherwise be empty.
  const showTopLevel = !currentCategory && tree && tree.length > 0

  if (!showTopLevel && !currentCategory) return null

  // Walk to find just the parent of the current node — siblings are
  // intentionally NOT shown here (owner ask 2026-05-17: the mega menu
  // already handles lateral category nav, so the sidebar should focus on
  // drill-down attributes specific to the current subcategory instead).
  function findParent(): CategoryNode | null {
    if (!currentCategory || !tree) return null
    const target = currentCategory  // bind so the closure sees a non-null
    function walk(nodes: CategoryNode[], parent: CategoryNode | null): { found: boolean; parent: CategoryNode | null } {
      for (const n of nodes) {
        if (n.id === target.id) return { found: true, parent }
        const hit = walk(n.children, n)
        if (hit.found) return hit
      }
      return { found: false, parent: null }
    }
    return walk(tree, null).parent
  }
  const parent = findParent()

  // Title in the dark header — most context-relevant level
  const headerLabel = currentCategory
    ? (parent ? parent.name : "Shop by")
    : "Shop by Department"
  const headerSub = currentCategory
    ? currentCategory.name
    : "Pick a department to drill down"

  return (
    <div className="border rounded-lg bg-white overflow-hidden">
      <div className="px-4 py-3 bg-gradient-to-br from-gray-900 to-gray-800 text-white border-b">
        <div className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">{headerLabel}</div>
        <div className="text-sm font-bold mt-0.5 line-clamp-2">{headerSub}</div>
        {currentCategory && (
          <button
            onClick={() => onPick(null)}
            className="text-[11px] text-gray-400 hover:text-white mt-1.5"
          >
            ← All products
          </button>
        )}
      </div>

      <div className="p-2">
        {/* TOP-LEVEL MODE (no current category) — show all top-level nodes */}
        {showTopLevel && tree?.map((n) => (
          <button
            key={n.id}
            onClick={() => onPick(n.full_path)}
            className="w-full flex items-center justify-between px-3 py-2 text-left text-sm font-semibold text-gray-800 hover:bg-gray-50 rounded"
          >
            <span>{n.name}</span>
            <span className="text-gray-400 text-xs">{n.product_count.toLocaleString()}</span>
          </button>
        ))}

        {/* DRILL MODE — show parent + siblings + current + children */}
        {currentCategory && (
          <>
            {/* Parent breadcrumb chip */}
            {parent && (
              <button
                onClick={() => onPick(parent.full_path)}
                className="w-full flex items-center px-3 py-1.5 text-left text-[11px] uppercase tracking-wider text-gray-500 hover:text-red-700 rounded"
              >
                <span className="mr-1">↰</span>
                <span>Back to {parent.name}</span>
              </button>
            )}

            {/* Current category — bolded */}
            <div className="px-3 py-2 mt-1 text-sm font-bold text-red-700 bg-red-50 rounded border-l-4 border-red-700">
              {currentCategory.name}
              <span className="ml-1 text-[11px] text-red-500 font-normal">({currentCategory.product_count.toLocaleString()})</span>
            </div>

            {/* Direct children — drill DOWN */}
            {currentCategory.children.length > 0 && (
              <div className="ml-3 mt-1 space-y-0.5 border-l-2 border-gray-100 pl-3">
                {currentCategory.children.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => onPick(c.full_path)}
                    className="w-full flex items-center justify-between px-2 py-1.5 text-left text-[13px] text-gray-700 hover:text-red-700 hover:bg-gray-50 rounded"
                  >
                    <span>{c.name}</span>
                    <span className="text-gray-400 text-[10px]">{c.product_count.toLocaleString()}</span>
                  </button>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// Walk the category tree by full_path. After the 2026-05-10 re-parenting,
// MEGA_SECTIONS still references legacy paths like "Trailer Parts > Trailer
// Axles" even though the live path is "Trailer & RV > Trailer Parts >
// Trailer Axles". Tolerate that by ALSO matching when the requested path
// is a TAIL suffix of the live full_path (i.e. live ends with " > <fullPath>"
// or equals it). Avoids having to rewrite every MEGA_SECTIONS entry.
function findCategoryByPath(tree: CategoryNode[], fullPath: string): CategoryNode | null {
  for (const node of tree) {
    if (node.full_path === fullPath
        || node.full_path.endsWith(' > ' + fullPath)) return node
    const hit = findCategoryByPath(node.children, fullPath)
    if (hit) return hit
  }
  return null
}

// Cache so we don't refetch the (large) tree on every catalog navigation.
// (category-tree cache lives in loadCategoryTree() above — shared across all
// three consumers so the tree is fetched at most once per session.)

/** MobileFilterDrawer — slides in from the left on phones, covering ~85% of
 *  the screen with a dim backdrop. Locks <html> scroll while open so the
 *  page doesn't scroll behind the drawer. md:hidden so desktop continues
 *  to use the inline aside.  Owner ask 2026-05-18 (mobile catalog pass).
 */
function MobileFilterDrawer({ open, onClose, children, activeCount }: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  activeCount: number
}) {
  useEffect(() => {
    if (!open) return
    const prev = document.documentElement.style.overflow
    document.documentElement.style.overflow = 'hidden'
    return () => { document.documentElement.style.overflow = prev }
  }, [open])

  return (
    <>
      <div
        onClick={onClose}
        className={`md:hidden fixed inset-0 bg-black/40 z-40 transition-opacity ${
          open ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        aria-hidden="true"
      />
      <aside
        className={`md:hidden fixed inset-y-0 left-0 w-[85vw] max-w-sm bg-white z-50 shadow-xl transform transition-transform overflow-auto ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        aria-hidden={!open}
      >
        <div className="sticky top-0 bg-white border-b px-4 py-3 flex items-center justify-between z-10">
          <h2 className="font-bold text-sm uppercase tracking-wider text-gray-800">
            Filter
            {activeCount > 0 && (
              <span className="ml-2 text-[10px] text-red-700 font-bold">({activeCount} active)</span>
            )}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 text-2xl leading-none px-2 -mr-2"
            aria-label="Close filters"
            type="button"
          >×</button>
        </div>
        <div className="p-3 space-y-3">{children}</div>
      </aside>
    </>
  )
}

/** StickyMobileToolbar — pinned just below the page chrome on phones so
 *  Filter / view toggle / in-stock / result count are reachable from
 *  anywhere in a long results list. md:hidden — desktop uses the inline
 *  controls next to the H1.
 */
function StickyMobileToolbar({
  onOpenFilters, activeCount, viewMode, setViewMode, inStock, onToggleInStock, foundCount,
}: {
  onOpenFilters: () => void
  activeCount: number
  viewMode: 'grid' | 'list'
  setViewMode: (m: 'grid' | 'list') => void
  inStock: boolean
  onToggleInStock: (v: boolean) => void
  foundCount: number | undefined
}) {
  return (
    <div className="md:hidden sticky top-0 z-30 bg-white border-b border-gray-200 -mx-6 px-4 py-2 mb-3 flex items-center gap-2 text-sm">
      <button
        type="button"
        onClick={onOpenFilters}
        className="flex items-center gap-1 font-semibold text-gray-800 px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50"
      >
        ☰ Filter
        {activeCount > 0 && (
          <span className="ml-1 text-[10px] uppercase tracking-wider text-red-700 font-bold">{activeCount}</span>
        )}
      </button>
      <div className="inline-flex rounded border border-gray-300 overflow-hidden text-xs">
        <button
          type="button"
          onClick={() => setViewMode('grid')}
          className={`px-2.5 py-1.5 font-semibold ${viewMode === 'grid' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600'}`}
          title="Grid view"
        >▦</button>
        <button
          type="button"
          onClick={() => setViewMode('list')}
          className={`px-2.5 py-1.5 font-semibold ${viewMode === 'list' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600'} border-l border-gray-300`}
          title="List view"
        >☰</button>
      </div>
      <label className="flex items-center gap-1 text-xs whitespace-nowrap">
        <input type="checkbox" checked={inStock} onChange={(e) => onToggleInStock(e.target.checked)} />
        In stock
      </label>
      {foundCount !== undefined && (
        <span className="ml-auto text-xs text-gray-500 whitespace-nowrap">{foundCount.toLocaleString()} results</span>
      )}
    </div>
  )
}

/** Thin indeterminate bar shown while a catalog request is in flight.
 *  Sits above the results so a slow load (the Postgres/facet path can take
 *  several seconds on big categories) reads as "working", not "frozen". */
function TopProgressBar() {
  return (
    <div className="titan-progress-track h-0.5 bg-red-100 rounded-full mb-3" role="progressbar" aria-label="Loading products">
      <div className="titan-progress-bar rounded-full" />
    </div>
  )
}

/** Placeholder grid that mirrors the real product-card layout so the first
 *  load shows page structure immediately (no blank screen, no layout shift
 *  when data arrives). */
function CatalogSkeletonGrid({ count = 12, list = false }: { count?: number; list?: boolean }) {
  const cards = Array.from({ length: count })
  if (list) {
    return (
      <div className="flex flex-col gap-3" aria-hidden="true">
        {cards.map((_, i) => (
          <div key={i} className="border rounded p-3 flex gap-3 animate-pulse">
            <div className="w-[90px] h-[90px] rounded bg-gray-200 flex-shrink-0" />
            <div className="flex-1 space-y-2 py-1">
              <div className="h-4 w-3/4 rounded bg-gray-200" />
              <div className="h-3 w-1/2 rounded bg-gray-200" />
              <div className="h-3 w-1/4 rounded bg-gray-200" />
            </div>
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4" aria-hidden="true">
      {cards.map((_, i) => (
        <div key={i} className="border rounded-lg p-3 animate-pulse">
          <div className="aspect-square rounded bg-gray-200" />
          <div className="mt-3 h-4 w-3/4 rounded bg-gray-200" />
          <div className="mt-2 h-3 w-1/2 rounded bg-gray-200" />
          <div className="mt-3 h-4 w-1/3 rounded bg-gray-200" />
        </div>
      ))}
    </div>
  )
}

function CatalogBrowse() {
  const { ymm, user, showroom } = useApp()
  const showroomActive = showroom && (user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer')
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState<BrowseResponse | null>(null)
  const [loading, setLoading] = useState(false)
  // Escalating reassurance for genuinely slow loads. <1s: nothing extra.
  // 4s: "still loading". 10s: "large category" — so a 10-15s wait never
  // reads as a hung page. Reset whenever a load starts/ends.
  const [slowPhase, setSlowPhase] = useState<'none' | 'slow' | 'verySlow'>('none')
  const [tree, setTree] = useState<CategoryNode[] | null>(_categoryTree)
  // Filter sidebar — visible by default on desktop, collapsed by default
  // on mobile so users land on products instead of scrolling past 3 facet
  // groups + a HotProducts widget before seeing what they searched for.
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [viewMode, setViewModeState] = useState<'grid' | 'list'>(() => {
    const stored = (typeof window !== 'undefined' && window.localStorage.getItem('titan_view_mode')) || ''
    return stored === 'list' ? 'list' : 'grid'
  })
  const setViewMode = (m: 'grid' | 'list') => {
    setViewModeState(m)
    try { window.localStorage.setItem('titan_view_mode', m) } catch { /* ignore */ }
  }

  const q = params.get('q') || ''
  // Brand is multi-select — owner ask 2026-05-17: customer should be able
  // to compare brands side-by-side ("show me Husky AND WeatherTech mats").
  const brands = params.getAll('brand').filter(Boolean)
  const brandSet = new Set(brands)
  // Showroom Mode hard-clamps browse to the Truck Accessories subtree: force
  // category_top, and only honor a category_path that's already inside it (so a
  // direct URL to a non-accessory category can't escape the kiosk).
  const rawCategoryTop = params.get('category_top') || ''
  const rawCategoryPath = params.get('category_path') || ''
  const categoryTop = showroomActive ? SHOWROOM_CATEGORY : rawCategoryTop
  const categoryPath = showroomActive
    ? (rawCategoryPath.startsWith(SHOWROOM_CATEGORY) ? rawCategoryPath : '')
    : rawCategoryPath
  const inStock = params.get('in_stock') === '1' || params.get('in_stock') === 'true'
  const vehicleType = params.get('vehicle_type') || ''  // 'Van' restricts to van-fitting + universal
  const page = parseInt(params.get('page') || '1', 10)
  const sort = params.get('sort') || ''  // '' / 'name_asc' / 'name_desc' / 'stock_asc'. Default = stock-desc.
  // PIES attribute filters — each value is "Key|Value". Repeated entries
  // for the same key OR within that key; different keys AND across.
  const attrPairs = params.getAll('attr')
  const attrKey = attrPairs.join('§')  // stable dep key for useEffect
  // When user has a YMM saved AND it has a base_vehicle_id (came from new PACE-backed
  // resolve), restrict catalog browse to parts that fit that vehicle.
  const baseVehicleId = ymm?.base_vehicle_id ?? null

  // Load category tree once per session so we can render subcategory tiles
  useEffect(() => {
    if (_categoryTree) return
    loadCategoryTree().then(setTree).catch(() => {})
  }, [])

  const brandKey = brands.join('§')  // stable dep key for useEffect
  useEffect(() => {
    setLoading(true)
    const url = new URL('/api/catalog/browse', window.location.origin)
    if (q) url.searchParams.set('q', q)
    for (const b of brands) url.searchParams.append('brand', b)
    if (categoryTop) url.searchParams.set('category_top', categoryTop)
    if (categoryPath) url.searchParams.set('category_path', categoryPath)
    if (inStock) url.searchParams.set('in_stock', 'true')
    if (baseVehicleId) url.searchParams.set('base_vehicle_id', String(baseVehicleId))
    if (vehicleType) url.searchParams.set('vehicle_type', vehicleType)
    for (const a of attrPairs) url.searchParams.append('attrs', a)
    if (sort) url.searchParams.set('sort', sort)
    url.searchParams.set('page', String(page))
    url.searchParams.set('per_page', '24')
    fetch(url).then((r) => r.json()).then(setData).finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, brandKey, categoryTop, categoryPath, inStock, vehicleType, page, baseVehicleId, attrKey, sort])

  // Drive the slow-load reassurance timers off `loading`. Cleared on unmount
  // or when loading flips, so the message never lingers past the response.
  useEffect(() => {
    if (!loading) { setSlowPhase('none'); return }
    setSlowPhase('none')
    const t1 = setTimeout(() => setSlowPhase('slow'), 4000)
    const t2 = setTimeout(() => setSlowPhase('verySlow'), 10000)
    return () => { clearTimeout(t1); clearTimeout(t2) }
  }, [loading])

  // Scroll back to the top of the page when the user paginates OR navigates to
  // a new category/subcategory (e.g. via the megamenu).  Otherwise the grid
  // contents swap underneath the user and they're left staring at the middle
  // of the page with the category heading, sort, and filters hidden up above —
  // they shouldn't have to scroll up to see what they're now viewing.
  // Note: deliberately NOT keyed on filter/sort changes (brands, attrs, sort),
  // since those are driven from controls at the top and yanking the viewport up
  // mid-filtering would be jarring.  Pagination ask 2026-05-14; category 2026-06-06.
  useEffect(() => {
    if (page > 1 || data) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, categoryTop, categoryPath])

  // Resolve the current category node so we can render subcategory tiles +
  // a breadcrumb.  When only category_top is set, the "current" node is the
  // top node; when category_path is also set, we walk to that deeper node.
  const currentCategory: CategoryNode | null = (() => {
    if (!tree) return null
    const path = categoryPath || categoryTop
    if (!path) return null
    return findCategoryByPath(tree, path)
  })()
  const breadcrumb: { name: string; full_path: string }[] = (() => {
    if (!currentCategory) return []
    const parts = currentCategory.full_path.split('>').map(s => s.trim())
    return parts.map((_, i) => ({
      name: parts[i],
      full_path: parts.slice(0, i + 1).join('>'),
    }))
  })()

  function updateParam(key: string, value: string | null) {
    const next = new URLSearchParams(params)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    // Reset to page 1 whenever a filter changes (q/brand/category/vehicle_type/in_stock).
    // But NOT when the user is paginating — that would zero the click immediately.
    if (key !== 'page') next.delete('page')
    setParams(next)
  }

  // Toggle a brand in / out of the multi-select set. Adds on first click,
  // removes on second. Customer-side: lets the customer compare brands
  // side-by-side instead of forcing one at a time.
  function toggleBrand(name: string) {
    const next = new URLSearchParams(params)
    const current = next.getAll('brand')
    next.delete('brand')
    let found = false
    for (const b of current) {
      if (b === name) { found = true; continue }
      next.append('brand', b)
    }
    if (!found) next.append('brand', name)
    next.delete('page')
    setParams(next)
  }

  // Toggle one "Key|Value" attribute filter pair. Multi-select per key,
  // so a second click on the same pair removes it without disturbing
  // other selections on the same or different keys.
  function toggleAttr(pair: string) {
    const next = new URLSearchParams(params)
    const current = next.getAll('attr')
    next.delete('attr')
    let found = false
    for (const a of current) {
      if (a === pair) { found = true; continue }
      next.append('attr', a)
    }
    if (!found) next.append('attr', pair)
    next.delete('page')
    setParams(next)
  }
  const selectedAttrSet = new Set(attrPairs)

  // Active filter chips for clarity.  When category_path is set we render the
  // deepest segment (so "Truck Equipment > Snow Plows" shows "Snow Plows")
  // and clearing it drops back to the top category.
  const chips: { label: string; clear: () => void }[] = []
  if (q) chips.push({ label: `"${q}"`, clear: () => updateParam('q', null) })
  if (categoryPath) {
    const tail = categoryPath.split('>').slice(-1)[0].trim()
    chips.push({
      label: `Subcategory: ${tail}`,
      clear: () => updateParam('category_path', null),
    })
  }
  if (categoryTop) {
    chips.push({
      label: `Category: ${categoryTop}`,
      clear: () => {
        const next = new URLSearchParams(params)
        next.delete('category_top')
        next.delete('category_path')
        next.delete('page')
        setParams(next)
      },
    })
  }
  for (const b of brands) {
    chips.push({ label: `Brand: ${b}`, clear: () => toggleBrand(b) })
  }
  if (inStock) chips.push({ label: 'In stock only', clear: () => updateParam('in_stock', null) })
  if (vehicleType) chips.push({ label: `${vehicleType} fitment only`, clear: () => updateParam('vehicle_type', null) })
  for (const pair of attrPairs) {
    const [k, v] = pair.split('|')
    chips.push({ label: `${k}: ${v}`, clear: () => toggleAttr(pair) })
  }

  // Build chips against the *deepest* active filter for category
  function pickSubcategory(child: CategoryNode) {
    const next = new URLSearchParams(params)
    next.delete('q')
    // Always set category_top to the current top so the typesense filter still runs
    const topName = child.full_path.split('>')[0].trim()
    next.set('category_top', topName)
    if (child.depth > 0) next.set('category_path', child.full_path)
    else next.delete('category_path')
    next.delete('page')
    setParams(next)
  }

  // Shared filter sidebar content — rendered both in the inline desktop
  // <aside> and inside the mobile slide-in drawer so both surfaces stay
  // in lock-step as new filters are added.
  const isVanMode = vehicleType === 'Van'
  const isDewezeMode = (categoryPath || '').endsWith('Hydraulic Pump Kits')

  const filterContent = (
    <>
      {/* Type filtering — category/subcategory navigation (or the Van /
          Deweze finders that replace it for those flows). */}
      {isVanMode ? (
        <VanNavigator />
      ) : isDewezeMode ? (
        <DewezeKitFinder />
      ) : (
        <CategoryDrillNav
          tree={tree}
          currentCategory={currentCategory}
          onPick={(path) => {
            const next = new URLSearchParams(params)
            next.delete('q')
            next.delete('page')
            next.delete('attr')
            if (path === null) {
              next.delete('category_top')
              next.delete('category_path')
            } else {
              const topName = path.split('>')[0].trim()
              next.set('category_top', topName)
              if (path !== topName) next.set('category_path', path)
              else next.delete('category_path')
            }
            setParams(next)
          }}
        />
      )}
      {/* Brand sits directly below the type/category nav (owner ask
          2026-06-22) — above the granular PIES attribute drill-downs. */}
      <FacetGroup
        title="Brand"
        items={data?.facets?.brand_name || []}
        multiSelect
        activeValues={brandSet}
        onToggle={(v) => toggleBrand(v)}
      />
      {!isVanMode && !isDewezeMode && (categoryTop || categoryPath) && (
        <CategoryAttributeFacets
          categoryTop={categoryTop}
          categoryPath={categoryPath}
          baseVehicleId={baseVehicleId}
          vehicleType={vehicleType}
          selected={selectedAttrSet}
          onToggle={toggleAttr}
        />
      )}
      <FacetGroup
        title="Category"
        items={data?.facets?.category_top || []}
        activeValue={categoryTop}
        onPick={(v) => updateParam('category_top', v)}
      />
      <HotProductsWidget limit={4} />
    </>
  )

  return (
    <div className="px-4 sm:px-6 lg:px-8 pt-3 pb-6 max-w-[1600px] mx-auto">
      <MobileFilterDrawer
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        activeCount={chips.length}
      >
        {filterContent}
      </MobileFilterDrawer>
      <StickyMobileToolbar
        onOpenFilters={() => setFiltersOpen(true)}
        activeCount={chips.length}
        viewMode={viewMode}
        setViewMode={setViewMode}
        inStock={inStock}
        onToggleInStock={(v) => updateParam('in_stock', v ? '1' : null)}
        foundCount={data?.found}
      />
      {/* Title row — title big on the left, breadcrumb top-right with
          controls beneath. Owner ask 2026-05-17: dropped the standalone
          breadcrumb row + the "All products" link (redundant with Home)
          to remove vertical whitespace at the top of the page. */}
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3 mb-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-900">
            {currentCategory ? currentCategory.name : q ? `Search: "${q}"` : 'All products'}
          </h1>
          {data && (
            <div className="text-sm text-gray-500 mt-1">
              {data.found.toLocaleString()} products
              {' · '}
              {data.in_stock_count !== undefined ? (
                data.in_stock_count > 0 ? (
                  <span className="text-green-700 font-semibold">
                    {data.in_stock_count.toLocaleString()} in stock
                  </span>
                ) : (
                  <span className="text-gray-500">none in stock</span>
                )
              ) : null}
              {' · '}{data.search_time_ms}ms
            </div>
          )}
        </div>
        <div className="flex flex-col sm:items-end gap-2 sm:max-w-[60%]">
          {currentCategory && (
            <nav className="text-xs text-gray-500 sm:text-right">
              <Link to="/" className="hover:text-red-700">Home</Link>
              {breadcrumb.map((b, i) => (
                <span key={i}>
                  <span> / </span>
                  {i === breadcrumb.length - 1 ? (
                    <span className="text-gray-700">{b.name}</span>
                  ) : (
                    <button
                      onClick={() => {
                        const next = new URLSearchParams(params)
                        if (i === 0) {
                          next.set('category_top', b.full_path)
                          next.delete('category_path')
                        } else {
                          next.set('category_path', b.full_path)
                        }
                        next.delete('page')
                        setParams(next)
                      }}
                      className="hover:text-red-700"
                    >
                      {b.name}
                    </button>
                  )}
                </span>
              ))}
            </nav>
          )}
          <div className="flex items-center gap-4 flex-wrap">
            {/* Sort dropdown — Name + Price only. The "In stock only"
                checkbox to the right handles the stock filter so the
                sort doesn't need a stock dimension. Visible at all sizes
                (mobile included) since the sticky toolbar doesn't have
                room for it. */}
            <label className="flex items-center gap-1.5 text-xs">
              <span className="text-gray-500 uppercase tracking-wider font-semibold">Sort</span>
              <select
                value={sort}
                onChange={(e) => updateParam('sort', e.target.value || null)}
                className="border border-gray-300 rounded px-2 py-1 text-xs bg-white"
              >
                <option value="">Name (A → Z)</option>
                <option value="name_desc">Name (Z → A)</option>
                <option value="price_asc">Price (low → high)</option>
                <option value="price_desc">Price (high → low)</option>
              </select>
            </label>
            {/* View-mode toggle + in-stock checkbox — hidden on mobile
                because StickyMobileToolbar already provides them. Showing
                them here too would double up and waste mobile screen
                space. */}
            <div className="hidden sm:inline-flex rounded border border-gray-300 overflow-hidden text-xs">
              <button
                onClick={() => setViewMode('grid')}
                className={`px-3 py-1.5 font-semibold ${viewMode === 'grid' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
                title="Grid view"
              >
                ▦ Grid
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`px-3 py-1.5 font-semibold ${viewMode === 'list' ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'} border-l border-gray-300`}
                title="List view"
              >
                ☰ List
              </button>
            </div>
            <label className="hidden sm:flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={inStock}
                onChange={(e) => updateParam('in_stock', e.target.checked ? '1' : null)}
              />
              In stock only
            </label>
          </div>
        </div>
      </div>

      {/* Subcategory drill-down tiles — uniform product cards: image floats on
          a light frame up top, title sits below in a fixed 2-line slot so every
          card is the same height and the row reads as a tidy grid. Falls back to
          a clean letter tile when no resolvable image. */}
      {currentCategory && currentCategory.children.length > 0 && (
        <section className="mb-6">
          <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-3">
            Shop by subcategory
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
            {currentCategory.children.map((c) => (
              <button
                key={c.id}
                onClick={() => pickSubcategory(c)}
                className="group flex flex-col rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md"
              >
                {/* Image in a fixed-height frame — light neutral backing, and
                    mix-blend-mode: multiply melts the JPEG's white canvas into
                    the frame so the product reads as floating. */}
                <div className="flex h-32 w-full items-center justify-center overflow-hidden rounded-lg bg-slate-50">
                  {c.image_url ? (
                    <img
                      src={c.image_url}
                      alt={c.name}
                      loading="lazy"
                      style={{ mixBlendMode: 'multiply' }}
                      className="max-h-[85%] max-w-[85%] object-contain group-hover:scale-105 transition-transform duration-200"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = 'none'
                      }}
                    />
                  ) : (
                    <div className="text-4xl font-bold text-slate-300 uppercase">{c.name.charAt(0)}</div>
                  )}
                </div>
                {/* Title below the image in a fixed 2-line slot so titles +
                    images align across the row regardless of name length. */}
                <div className="mt-3 flex min-h-[3.5rem] items-start justify-center px-1 text-center text-xl font-semibold leading-snug text-slate-800 group-hover:text-red-700 line-clamp-2">
                  {c.name}
                </div>
                {c.children.length > 0 && (
                  <div className="text-center text-xs font-medium text-slate-400">{c.children.length} subcategories</div>
                )}
              </button>
            ))}
          </div>
        </section>
      )}

      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {chips.map((c, i) => (
            <button
              key={i}
              onClick={c.clear}
              className="px-3 py-1 bg-gray-100 hover:bg-gray-200 rounded-full text-xs text-gray-700"
            >
              {c.label} <span className="ml-1 text-gray-500">×</span>
            </button>
          ))}
          <Link to="/catalog" className="px-3 py-1 text-xs text-red-700 hover:underline">clear all</Link>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-[260px_1fr] gap-6">
        {/* Desktop sidebar — the same filterContent renders inside the
            MobileFilterDrawer at <md. Owner ask 2026-05-18: phones use a
            slide-in drawer instead of an inline expand that pushes the
            grid off-screen. */}
        <aside className="hidden md:block space-y-3 self-start">
          {filterContent}
        </aside>

        <div>
          {/* In-flight indicator. The bar always shows while loading; the
              reassurance line only escalates once a load runs long, so a
              fast load stays clean and a 10-15s load never looks hung. */}
          {loading && <TopProgressBar />}
          {loading && slowPhase !== 'none' && (
            <div className="text-sm text-gray-500 mb-3" role="status" aria-live="polite">
              {slowPhase === 'slow'
                ? 'Loading products…'
                : 'Still working — large category, almost there.'}
            </div>
          )}

          {/* First load (no data yet): show a skeleton grid so the page has
              structure immediately instead of a blank column. */}
          {loading && !data ? (
            <CatalogSkeletonGrid count={12} list={viewMode === 'list'} />
          ) : (
            <>
              {!loading && data && data.hits.length === 0 && (
                <div className="p-12 text-center text-gray-500 border-2 border-dashed rounded-lg">
                  No matches. <Link to="/catalog" className="text-red-700 underline">Clear filters</Link>?
                </div>
              )}

              {/* Pagination bar — rendered above AND below the grid.  Owner asked
                  for the page count at the top of the grid for ease-of-use
                  2026-05-14. */}
              {data && data.found > data.per_page && (
                <PaginationBar
                  page={page}
                  perPage={data.per_page}
                  found={data.found}
                  onPageChange={(p) => updateParam('page', String(p))}
                  className="mb-4"
                />
              )}

              {/* Stale-while-revalidate: keep the previous results visible but
                  dimmed + non-interactive while the next page/filter loads, so
                  the grid refines in place instead of flashing to a skeleton on
                  every facet click. */}
              <div className={loading ? 'opacity-50 pointer-events-none transition-opacity' : 'transition-opacity'}>
                {viewMode === 'list' ? (
                  <div className="flex flex-col gap-3">
                    {data?.hits.map((h) => <ProductListRow key={h.id} h={h} vehicleId={data?.resolved_vehicle?.base_vehicle_id} />)}
                  </div>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 gap-4">
                    {data?.hits.map((h) => <ProductCard key={h.id} h={h} vehicleId={data?.resolved_vehicle?.base_vehicle_id} />)}
                  </div>
                )}
              </div>

              {data && data.found > data.per_page && (
                <PaginationBar
                  page={page}
                  perPage={data.per_page}
                  found={data.found}
                  onPageChange={(p) => updateParam('page', String(p))}
                  className="mt-8"
                />
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** Pagination bar — rendered above and below the catalog grid.
 *
 *  Shows "Showing 25–48 of 1,247 · Page 2 of 52" plus prev/next buttons.
 *  Triggering `onPageChange` calls back with the new page number; the
 *  scroll-to-top behavior lives in the parent's effect on `page`.
 */
function PaginationBar({
  page, perPage, found, onPageChange, className = '',
}: {
  page: number
  perPage: number
  found: number
  onPageChange: (page: number) => void
  className?: string
}) {
  const totalPages = Math.max(1, Math.ceil(found / perPage))
  const startIdx = (page - 1) * perPage + 1
  const endIdx = Math.min(page * perPage, found)
  // On phones the pagination stacks: the page/arrow row sits on top
  // (the action users want to tap) and the "Showing N–M of T" count
  // sits below in smaller type. On sm:+ both halves go back to a
  // single horizontal row like before.
  return (
    <div className={`flex flex-col-reverse sm:flex-row items-center sm:justify-between gap-2 sm:gap-3 ${className}`}>
      <div className="text-xs sm:text-sm text-gray-600 text-center sm:text-left">
        Showing <span className="font-semibold text-gray-900">{startIdx.toLocaleString()}</span>
        –<span className="font-semibold text-gray-900">{endIdx.toLocaleString()}</span>
        {' '}of <span className="font-semibold text-gray-900">{found.toLocaleString()}</span>
      </div>
      <div className="flex items-center gap-2">
        <button
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="px-3 py-1.5 border rounded disabled:opacity-30 hover:bg-gray-50"
        >
          ← Prev
        </button>
        <div className="text-sm text-gray-600 px-2 whitespace-nowrap">
          Page <span className="font-semibold text-gray-900">{page}</span> of {totalPages.toLocaleString()}
        </div>
        <button
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="px-3 py-1.5 border rounded disabled:opacity-30 hover:bg-gray-50"
        >
          Next →
        </button>
      </div>
    </div>
  )
}


function PricingDisplay({ pricing, frontCounter, markupPct }: { pricing: PricingBlock; frontCounter: boolean; markupPct: number | null }) {
  const tier = pricing.tier

  if (tier === 'retail') {
    // Anonymous retail or RETAIL-tier customer: line-through suggested + bold retail + savings
    return (
      <div className="mt-6 p-4 bg-gray-50 rounded">
        {pricing.secondary_amount && (
          <div className="text-sm text-gray-500 line-through">
            {pricing.secondary_label}: ${pricing.secondary_amount}
          </div>
        )}
        <div className="text-3xl font-bold text-gray-900 mt-1">
          {pricing.primary_amount ? `$${pricing.primary_amount}` : 'Call for price'}
        </div>
        {pricing.savings_amount && (
          <div className="text-sm text-green-600 font-semibold mt-1">You save ${pricing.savings_amount}</div>
        )}
      </div>
    )
  }

  if (tier === 'municipality') {
    return (
      <div className="mt-6 p-4 bg-purple-50 border border-purple-200 rounded">
        <div className="text-xs uppercase tracking-wide text-purple-700 font-semibold">Contract Price</div>
        <div className="text-3xl font-bold text-gray-900 mt-1">
          {pricing.primary_amount ? `$${pricing.primary_amount}` : 'Call for quote'}
        </div>
        {pricing.contract_name && (
          <div className="text-xs text-gray-600 mt-2">Per contract: {pricing.contract_name}</div>
        )}
        {pricing.notes.length > 0 && (
          <ul className="text-xs text-gray-500 mt-1 list-disc list-inside">
            {pricing.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        )}
      </div>
    )
  }

  // jobber / dealer. Retail-facing pricing shows when a GLOBAL mode is on
  // (Showroom / Front Counter). The per-product retail view is now a full-screen
  // "Show retail price" presentation launched from ProductDetail.
  const isJD = tier === 'jobber' || tier === 'dealer'
  const isFrontCounter = frontCounter && isJD

  let block: ReactNode
  if (isFrontCounter) {
    const quote = frontCounterQuote(pricing.primary_amount, pricing.original_amount, pricing.secondary_amount, markupPct)
    block = (
      <div className="p-4 bg-orange-50 border border-orange-200 rounded">
        <div className="text-xs uppercase tracking-wide text-orange-700 font-semibold">Retail-Facing Price</div>
        <div className="text-3xl font-bold text-gray-900 mt-1">
          {quote ? `$${quote}` : 'Call for price'}
        </div>
        <div className="text-xs text-gray-500 mt-2">
          {markupPct
            ? <>Marked up {markupPct}% over wholesale (floored by MAP). <Link to="/account" className="text-red-700 underline">Change markup</Link></>
            : <>Showing MAP Retail. <Link to="/account" className="text-red-700 underline">Set a default markup</Link> to quote at cost + %.</>}
        </div>
      </div>
    )
  } else if (pricing.map_clamped) {
    // MAP-clamped: contract/tier price was below MAP and floored UP.
    block = (
      <div className="p-4 bg-blue-50 border border-blue-200 rounded">
        <div className="text-xs uppercase tracking-wide text-blue-700 font-semibold">{pricing.primary_label}</div>
        <div className="mt-1 flex items-baseline gap-3">
          {pricing.original_amount && (
            <span className="text-base text-gray-400 line-through">${pricing.original_amount}</span>
          )}
          <span className="text-3xl font-bold text-gray-900">
            {pricing.primary_amount ? `$${pricing.primary_amount}` : '—'}
          </span>
        </div>
        <div className="text-xs text-amber-700 mt-2">
          MAP-floor enforced{pricing.original_amount ? ` (true cost $${pricing.original_amount} blocked by MAP)` : ''}.
          {pricing.contract_name && <> Contract: {pricing.contract_name}.</>}
        </div>
      </div>
    )
  } else {
    // Normal jobber/dealer view: two-column "MAP Retail | Your Cost"
    block = (
      <div className="grid grid-cols-2 gap-3">
        <div className="p-3 bg-gray-50 rounded">
          <div className="text-xs uppercase tracking-wide text-gray-500">{pricing.secondary_label || 'MAP Retail'}</div>
          <div className="text-xl font-semibold text-gray-700 mt-1">
            {pricing.secondary_amount ? `$${pricing.secondary_amount}` : '—'}
          </div>
        </div>
        <div className="p-3 bg-blue-50 border border-blue-200 rounded">
          <div className="text-xs uppercase tracking-wide text-blue-700 font-semibold">{pricing.primary_label}</div>
          <div className="text-2xl font-bold text-gray-900 mt-1">
            {pricing.primary_amount ? `$${pricing.primary_amount}` : '—'}
          </div>
          {pricing.contract_name && (
            <div className="text-[10px] text-blue-600 mt-1">via {pricing.contract_name}</div>
          )}
        </div>
        {pricing.notes.length > 0 && (
          <div className="col-span-2 text-xs text-gray-500">
            {pricing.notes.join(' · ')}
          </div>
        )}
      </div>
    )
  }

  return <div className="mt-6">{block}</div>
}

// Full-screen, customer-facing presentation of a single product — image + name
// + fitment + retail price + stock, with ALL back-office chrome stripped. Opened
// by a counter rep ("Show customer"); requests browser fullscreen on the overlay
// so the address bar/nav are gone, and closes itself when fullscreen is exited.
function CustomerPresentation({ data, retail, ymm, sku, logoUrl, storeName, onClose }: { data: ProductDetail; retail: string | null; ymm: YMM | null; sku: string; logoUrl: string | null; storeName: string | null; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [idx, setIdx] = useState(0)
  const [paused, setPaused] = useState(false)
  const imgCount = data.images?.length || 0
  // "More in stock" — prefer items that fit the customer's truck (base_vehicle_id),
  // else other in-stock products from the same brand.
  const [related, setRelated] = useState<{ sku: string; name: string; brand: string | null; image_url: string | null; in_stock: boolean }[]>([])
  const baseVehicleId = ymm?.base_vehicle_id ?? null
  useEffect(() => {
    const params = new URLSearchParams({ in_stock: '1', per_page: '12' })
    if (baseVehicleId) params.set('base_vehicle_id', String(baseVehicleId))
    else if (data.brand?.name) params.append('brand', data.brand.name)
    else return
    fetch(`/api/catalog/browse?${params.toString()}`)
      .then((r) => r.json())
      .then((d) => setRelated(((d?.hits) || []).filter((h: { sku: string; image_url: string | null }) => h.sku !== data.sku && h.image_url).slice(0, 6)))
      .catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  // Auto-advance the gallery when idle so the counter screen looks alive; a
  // manual thumbnail tap pauses it.
  useEffect(() => {
    if (paused || imgCount <= 1) return
    const t = setInterval(() => setIdx((i) => (i + 1) % imgCount), 4000)
    return () => clearInterval(t)
  }, [paused, imgCount])
  useEffect(() => {
    const el = ref.current
    if (el) { const p = el.requestFullscreen?.(); if (p && typeof p.catch === 'function') p.catch(() => {}) }
    const onFs = () => { if (!document.fullscreenElement) onClose() }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('fullscreenchange', onFs)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('fullscreenchange', onFs)
      document.removeEventListener('keydown', onKey)
      try { if (document.fullscreenElement) { const p = document.exitFullscreen?.(); if (p && typeof p.catch === 'function') p.catch(() => {}) } } catch { /* ignore */ }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const images = data.images?.length ? data.images : []
  const img = images[idx]?.url || images[0]?.url
  // A few selling-point bullets: PIES feature rows first, else the description.
  // Features arrive under code 'FEA' (Buyers scrape, ~3.5k products) or 'FAB'
  // (the bulk PIES feed, ~263k products). Prefer FEA when present, else fall
  // back to FAB so products whose features only exist as FAB still render.
  const featureRows = (() => {
    const all = data.descriptions || []
    const fea = all.filter((d) => d.code === 'FEA' && d.text?.trim())
    return fea.length ? fea : all.filter((d) => d.code === 'FAB' && d.text?.trim())
  })()
  const features = featureRows
    .sort((a, b) => a.sequence - b.sequence)
    .map((d) => d.text.split('\n')[0].trim())
    .filter((t) => t.length > 0 && t.length < 120)
    .slice(0, 4)
  const inStock = (data.total_on_hand || 0) > 0
  const lead = data.brand?.special_order_lead_time_max_days

  // Key specs — dimensions + weight + a couple of top PIES attributes.
  const specs: { label: string; value: string }[] = []
  const dim = data.dimensions
  if (dim && (dim.length_in || dim.width_in || dim.height_in)) {
    specs.push({ label: 'Dimensions', value: [dim.length_in, dim.width_in, dim.height_in].filter(Boolean).map((n) => `${n}"`).join(' × ') })
  }
  if (data.weight_lb) specs.push({ label: 'Weight', value: `${data.weight_lb} lb` })
  for (const a of (data.attributes || [])) {
    if (specs.length >= 5) break
    if (a.value && !specs.some((s) => s.label === a.key)) specs.push({ label: a.key, value: `${a.value}${a.uom ? ` ${a.uom}` : ''}` })
  }

  // Illustrative financing line for bigger-ticket items (12-month split).
  const retailNum = retail ? parseFloat(retail) : null
  const monthly = retailNum && retailNum >= 150 ? Math.ceil(retailNum / 12) : null

  const productUrl = absoluteUrl(`/product/${sku}`)
  const description = (data.description || data.extended_description || '').trim()

  return (
    <div ref={ref} className="fixed inset-0 z-[70] flex flex-col overflow-auto bg-gradient-to-b from-slate-50 to-white">
      <button onClick={onClose} className="absolute right-5 top-5 z-10 rounded-full bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow ring-1 ring-gray-200 hover:bg-gray-50">✕ Close</button>
      {/* Jobber store branding band — logo + name + "sold & installed by" so the
          dealer's brand owns the screen they show their customer. */}
      {(logoUrl || storeName) && (
        <div className="flex flex-col items-center gap-1 border-b border-gray-100 bg-white/70 px-6 py-4">
          <div className="flex items-center gap-3">
            {logoUrl && <img src={logoUrl} alt={storeName || ''} className="h-9 w-auto max-w-[220px] object-contain" />}
            {storeName && <span className="text-xl font-extrabold tracking-tight text-gray-900">{storeName}</span>}
          </div>
          {storeName && <div className="text-sm font-semibold text-gray-500">Sold &amp; installed by {storeName}</div>}
        </div>
      )}
      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col items-center justify-center gap-8 p-6 md:flex-row md:gap-14 md:p-10">
        {/* Image + thumbnails */}
        <div className="flex w-full flex-col items-center md:w-1/2">
          <div className="flex w-full items-center justify-center rounded-2xl bg-white p-6 shadow-sm ring-1 ring-gray-100">
            {img
              ? <img src={img} alt={data.name} className="max-h-[58vh] max-w-full object-contain" />
              : <div className="grid h-72 w-full place-items-center text-7xl text-gray-300">📦</div>}
          </div>
          {images.length > 1 && (
            <div className="mt-3 flex flex-wrap justify-center gap-2">
              {images.slice(0, 6).map((im, i) => (
                <button key={i} onClick={() => { setIdx(i); setPaused(true) }} className={`h-14 w-14 overflow-hidden rounded-lg bg-white ring-1 ${i === idx ? 'ring-2 ring-orange-500' : 'ring-gray-200'}`}>
                  <img src={im.url} alt="" className="h-full w-full object-contain p-1" />
                </button>
              ))}
            </div>
          )}
        </div>
        {/* Details */}
        <div className="w-full md:w-1/2">
          <div className="text-lg font-semibold uppercase tracking-wide text-gray-400">{data.brand?.name}</div>
          <h1 className="mt-1 text-4xl font-extrabold leading-tight text-gray-900 md:text-5xl">{data.name}</h1>
          {ymm && (
            <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-emerald-50 px-4 py-1.5 text-sm font-bold text-emerald-700 ring-1 ring-emerald-200">
              ✓ Fits your {ymm.year} {ymm.make_name} {ymm.model_name}
            </div>
          )}
          {features.length > 0 && (
            <ul className="mt-5 space-y-1.5">
              {features.map((f, i) => (
                <li key={i} className="flex gap-2 text-[15px] text-gray-700"><span className="mt-0.5 text-orange-500">✓</span><span>{f}</span></li>
              ))}
            </ul>
          )}

          {/* Price + QR side by side */}
          <div className="mt-7 flex items-end justify-between gap-4">
            <div>
              <div className="text-xs font-bold uppercase tracking-widest text-gray-400">Your Price</div>
              <div className="mt-0.5 text-6xl font-black text-gray-900 md:text-7xl">{retail ? `$${retail}` : 'Ask us'}</div>
              {monthly && <div className="mt-1 text-sm font-semibold text-gray-500">or about <span className="text-gray-800">${monthly}/mo</span> with financing</div>}
            </div>
            <div className="shrink-0 text-center">
              <div className="rounded-lg bg-white p-2 ring-1 ring-gray-200"><QRCodeSVG value={productUrl} size={92} /></div>
              <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Scan for details</div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-2">
            {inStock
              ? <span className="inline-flex items-center gap-2 rounded-full bg-emerald-100 px-4 py-1.5 text-sm font-bold text-emerald-800">● In stock — ready to go</span>
              : <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-4 py-1.5 text-sm font-bold text-amber-800">Available to order{lead ? ` — about ${lead} days` : ''}</span>}
            <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-4 py-1.5 text-sm font-bold text-slate-700">🔧 Professional install available</span>
          </div>

          {specs.length > 0 && (
            <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-1.5 border-t border-gray-100 pt-4 text-sm">
              {specs.map((s) => (
                <div key={s.label} className="flex justify-between gap-2">
                  <dt className="text-gray-400">{s.label}</dt>
                  <dd className="text-right font-semibold text-gray-700">{s.value}</dd>
                </div>
              ))}
            </dl>
          )}

          {description && (
            <p className="mt-5 border-t border-gray-100 pt-4 text-[15px] leading-relaxed text-gray-600">
              {description.length > 700 ? `${description.slice(0, 700)}…` : description}
            </p>
          )}
        </div>
      </div>

      {/* "More in stock" — big product cards below */}
      {related.length > 0 && (
        <div className="border-t border-gray-100 bg-white/60 px-6 py-6">
          <div className="mx-auto max-w-6xl">
            <h2 className="mb-3 text-sm font-black uppercase tracking-wide text-gray-500">
              {baseVehicleId && ymm ? `More in stock for your ${ymm.year} ${ymm.make_name} ${ymm.model_name}` : `More from ${data.brand?.name}, in stock`}
            </h2>
            <div className="flex gap-4 overflow-x-auto pb-2 [scrollbar-width:thin]">
              {related.map((r) => (
                <div key={r.sku} className="flex w-44 flex-none flex-col rounded-xl border border-gray-200 bg-white p-3 text-center shadow-sm">
                  <div className="flex h-32 w-full items-center justify-center">
                    {r.image_url ? <img src={r.image_url} alt={r.name} className="max-h-full max-w-full object-contain" /> : <span className="text-4xl text-gray-300">📦</span>}
                  </div>
                  <div className="mt-2 line-clamp-2 text-sm font-semibold text-gray-800">{r.name}</div>
                  <span className="mx-auto mt-1.5 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700">● In stock</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ProductDetail() {
  const { sku } = useParams<{ sku: string }>()
  const { addToCart, frontCounter, showroom, user, ymm } = useApp()
  // B2B-only affordances (Lost Sale, etc). Retail / anonymous customers
  // get the Add-to-Cart path even when OOS (special order).
  const isB2B = user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer'
  // Retail-shipping display (badges, flat-rate, will-call) is retail-only —
  // B2B tiers (jobber/dealer/municipality) use a separate freight program.
  const isRetail = !user?.customer_tier || user.customer_tier === 'retail'
  const [data, setData] = useState<ProductDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [errorStatus, setErrorStatus] = useState<number | null>(null)
  const [qty, setQty] = useState(1)
  const [adding, setAdding] = useState(false)
  const [added, setAdded] = useState(false)
  const [lostSaleOpen, setLostSaleOpen] = useState(false)
  const [priceMatchOpen, setPriceMatchOpen] = useState(false)
  const [presentOpen, setPresentOpen] = useState(false)
  // Per-sale markup override (null = use the customer's profile/default markup).
  const [markupOverride, setMarkupOverride] = useState<number | null>(null)

  useEffect(() => {
    if (!sku) return
    // Reset scroll to the top of the page when a product opens.  Without this,
    // clicking a card near the bottom of the grid leaves the SPA scrolled to
    // the old grid position and the product view loads off-screen.
    window.scrollTo({ top: 0 })
    setData(null); setError(null); setErrorStatus(null); setAdded(false)
    // Prerender status signal (server.mjs reads it): default OK, overridden on error.
    ;(window as unknown as { prerenderStatus?: number }).prerenderStatus = 200
    fetch(`/api/catalog/products/${sku}`)
      .then(async (r) => {
        if (!r.ok) {
          setErrorStatus(r.status)
          ;(window as unknown as { prerenderStatus?: number }).prerenderStatus = r.status
          const body = await r.json().catch(() => ({}))
          throw new Error(body.detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then((d: ProductDetail) => {
        setData(d)
        // Track in Recently Viewed
        pushRecentlyViewed({
          sku: d.sku,
          name: d.name,
          brand: d.brand?.name || null,
          image_url: d.images[0]?.url || null,
        })
      })
      .catch((e) => setError(e.message))
  }, [sku])

  async function onAdd() {
    if (!sku) return
    setAdding(true)
    try {
      await addToCart(sku, qty)
      setAdded(true)
      setTimeout(() => setAdded(false), 2000)
    } finally {
      setAdding(false)
    }
  }

  if (error) {
    const gone = errorStatus === 410
    const notFound = errorStatus === 404
    return (
      <>
        <Seo
          title={gone ? 'No longer available | Nelson Truck Equipment' : 'Product not found | Nelson Truck Equipment'}
          description={gone ? 'This product is no longer available.' : 'This product could not be found.'}
          noindex
        />
        <div className="mx-auto max-w-xl px-6 py-16 text-center">
          <div className="mb-3 text-5xl">{gone ? '🚫' : '🔎'}</div>
          <h1 className="mb-2 text-2xl font-bold text-gray-900">
            {gone ? 'This product is no longer available'
              : notFound ? 'Product not found'
              : 'Something went wrong'}
          </h1>
          <p className="mb-6 text-gray-600">
            {gone ? 'This item has been discontinued or removed from our catalog.'
              : notFound ? "We couldn't find that product — it may have moved."
              : error}
          </p>
          <Link to="/catalog" className="inline-block rounded-lg bg-red-600 px-4 py-2 font-medium text-white hover:bg-red-700">
            Browse the catalog
          </Link>
        </div>
      </>
    )
  }
  if (!data) return <div className="p-8 text-gray-500">Loading…</div>

  // Markup: the customer's profile default (or 25% via /me), overridable per
  // sale via the spinner. The retail price + present view use the effective one.
  const profileMarkup = user?.front_counter_markup_pct ?? 25
  const effMarkup = markupOverride ?? profileMarkup
  const retailStr = data.pricing
    ? frontCounterQuote(data.pricing.primary_amount, data.pricing.original_amount, data.pricing.secondary_amount, effMarkup)
    : null

  // --- SEO: per-product title/meta/OG + Product & Breadcrumb JSON-LD ---
  const seoImage = data.images?.[0]?.url || null
  const seoInStock = (data.total_on_hand ?? 0) > 0
  const seoPrice = data.pricing?.primary_amount || null
  // Prepend the brand only when the product name doesn't already lead with it
  // (many WSM names already start with the brand, e.g. "Bestop Cleaner").
  const seoBrand = data.brand?.name || ''
  const seoNameLeadsWithBrand = seoBrand && data.name.toLowerCase().startsWith(seoBrand.toLowerCase())
  const seoTitle = clamp(`${seoBrand && !seoNameLeadsWithBrand ? seoBrand + ' ' : ''}${data.name} | Nelson Truck Equipment`, 65)
  const seoDesc = clamp(
    data.description || data.extended_description ||
      `${data.name} from ${data.brand?.name || 'Nelson Truck Equipment'}. Shop truck & van equipment at Nelson Truck Equipment.`,
    160,
  )
  const productJsonLd: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: data.name,
    sku: data.sku,
    brand: { '@type': 'Brand', name: data.brand?.name || 'Nelson Truck Equipment' },
    url: absoluteUrl(`/product/${data.sku}`),
  }
  if (data.description) productJsonLd.description = clamp(data.description, 500)
  if (seoImage) productJsonLd.image = absoluteUrl(seoImage)
  if (seoPrice) {
    productJsonLd.offers = {
      '@type': 'Offer',
      priceCurrency: 'USD',
      price: seoPrice,
      availability: seoInStock ? 'https://schema.org/InStock' : 'https://schema.org/BackOrder',
      url: absoluteUrl(`/product/${data.sku}`),
    }
  }
  const breadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: CANONICAL_BASE_URL },
      { '@type': 'ListItem', position: 2, name: 'Catalog', item: absoluteUrl('/catalog') },
      { '@type': 'ListItem', position: 3, name: data.name, item: absoluteUrl(`/product/${data.sku}`) },
    ],
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <Seo
        title={seoTitle}
        description={seoDesc}
        path={`/product/${data.sku}`}
        image={seoImage}
        type="product"
        noindex={data.is_hidden || !data.is_for_sale}
        jsonLd={[productJsonLd, breadcrumbJsonLd]}
      />
      <Link to="/catalog" className="text-sm text-red-700 hover:underline">← Catalog</Link>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-8">
        <ImageGallery images={data.images} name={data.name} />

        <div>
          <div className="text-sm text-gray-500">{data.brand.name}</div>
          <h1 className="text-2xl font-bold mt-1">{data.name}</h1>
          <div className="font-mono text-sm text-gray-600 mt-1">{formatPartNumber(data.sku, data.brand?.name)}</div>
          {/* YMM "fits your truck" advisory — Phase 1 placeholder until fitment data lands */}
          <YmmFitmentBadge />

          {data.pricing && <PricingDisplay pricing={data.pricing} frontCounter={frontCounter || showroom} markupPct={user?.front_counter_markup_pct ?? null} />}

          {/* Per-product retail view → full-screen, customer-facing presentation.
              Markup defaults to the customer's profile (25% if unset) and can be
              overridden per sale. Hidden in global retail modes. */}
          {isB2B && !frontCounter && !showroom && data.pricing && (
            <div className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-1.5 text-sm font-semibold text-gray-700">
                  Markup
                  <input
                    type="number" min={0} max={500} step={1} value={effMarkup}
                    onChange={(e) => setMarkupOverride(Math.max(0, Math.min(500, parseInt(e.target.value, 10) || 0)))}
                    className="w-20 rounded border border-gray-300 px-2 py-1.5 text-sm"
                  />
                  <span className="text-gray-500">%</span>
                </label>
                <div className="text-sm text-gray-600">Retail: <span className="text-base font-bold text-gray-900">{retailStr ? `$${retailStr}` : '—'}</span></div>
                <button
                  onClick={() => setPresentOpen(true)}
                  className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700"
                  title="Show this product full-screen to a customer at retail price"
                >
                  🛍️ Show retail price
                </button>
              </div>
              <div className="mt-1 text-[11px] text-gray-400">
                Default {profileMarkup}% from your profile — adjust per sale.
                {markupOverride !== null && <> · <button onClick={() => setMarkupOverride(null)} className="underline hover:text-gray-600">reset</button></>}
              </div>
            </div>
          )}
          {presentOpen && data.pricing && (
            <CustomerPresentation
              data={data}
              retail={retailStr}
              ymm={ymm}
              sku={sku!}
              logoUrl={user?.showroom_logo_url ?? null}
              storeName={user?.showroom_display_name || user?.customer_name || null}
              onClose={() => setPresentOpen(false)}
            />
          )}

          {/* R2 reseller-pair callout: confirmed reseller match where this
              product is the more-expensive sibling. */}
          {data.reseller_alternate && data.reseller_alternate.savings > 0 && (
            <Link
              to={`/product/${data.reseller_alternate.sku}`}
              className="mt-3 block bg-amber-50 border border-amber-200 rounded p-2 hover:bg-amber-100 transition-colors"
            >
              <div className="text-[10px] uppercase tracking-widest text-amber-900 font-bold">Also available</div>
              <div className="text-sm text-gray-900 mt-0.5">
                From <span className="font-semibold">{data.reseller_alternate.brand}</span> for <span className="font-bold text-red-700">${(data.reseller_alternate.retail_price).toFixed(2)}</span> — save <span className="font-bold text-green-700">${data.reseller_alternate.savings.toFixed(2)}</span>
              </div>
            </Link>
          )}

          <div className="mt-6">
            <div className="text-sm font-semibold mb-2">Stock by warehouse</div>
            <WarehouseStockTable sku={sku!} />
          </div>

          {/* Retail shipping labels — Truck Freight / Will Call / flat-rate.
              Retail-only: B2B tiers use a separate freight program. */}
          {isRetail && (() => {
            const mode = data.shipping_mode
            const flat = data.flat_ship_amount
            const branches = [...new Set((data.inventory || []).filter((w) => w.on_hand > 0).map((w) => w.warehouse_name))]
            if (mode === 'will_call') {
              return (
                <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2">
                  <span className="inline-block rounded bg-blue-600 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">Will Call — Pickup Only</span>
                  <p className="mt-1 text-sm text-blue-900">
                    Pickup only{branches.length ? ` at ${branches.join(' or ')}` : ' at the branch where it is stocked'} — not available for shipping.
                  </p>
                </div>
              )
            }
            const hasNote = mode === 'truck_freight' || flat != null
            if (!hasNote) return null
            return (
              <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
                {mode === 'truck_freight' && <span className="inline-block rounded bg-amber-500 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">Truck Freight</span>}
                {flat === 0 && <span className="inline-block rounded bg-emerald-600 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">Free Shipping</span>}
                {flat != null && flat > 0 && <span className="text-gray-700">Flat-rate shipping: <b>${flat.toFixed(2)}</b> per unit</span>}
                {mode === 'truck_freight' && flat == null && <span className="text-gray-500">Ships by freight — cost added to your invoice.</span>}
              </div>
            )
          })()}

          {data.cta_mode === 'add_to_cart' && (
            <div className="mt-6 space-y-3">
              {/* OOS gets a small banner above the button so the customer
                  understands "Add to Cart" means special-order, but the
                  primary CTA stays the same regardless of stock. */}
              {data.total_on_hand <= 0 && (
                <div className="p-3 border border-gray-300 bg-gray-50 rounded text-center">
                  <div className="text-gray-700 font-semibold">Special order</div>
                  <div className="text-xs text-gray-500 mt-1">
                    Not in stock — we'll source it from the manufacturer.
                    {(() => {
                      const lt = formatLeadTime(data.brand.special_order_lead_time_min_days, data.brand.special_order_lead_time_max_days)
                      return lt ? <> Lead time: <span className="font-semibold text-gray-700">{lt}</span>.</> : null
                    })()}
                  </div>
                </div>
              )}
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 text-sm">
                  Qty:
                  <input type="number" min={1} max={999} value={qty}
                         onChange={(e) => setQty(Math.max(1, parseInt(e.target.value) || 1))}
                         className="w-16 border rounded px-2 py-1" />
                </label>
                <button onClick={onAdd} disabled={adding}
                        className="flex-1 py-3 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50 transition">
                  {adding ? 'Adding…' : added ? '✓ Added to cart' : 'Add to Cart'}
                </button>
              </div>
              {/* Compare-list parity with grid + list rows. Owner ask 2026-05-17. */}
              <div className="flex justify-end">
                <CompareToggleButton sku={data.sku} variant="list" />
              </div>
              {/* Owner ask 2026-05-17: when this product is OOS, surface the
                  single best in-stock alternative for the same vehicle (or
                  same subcategory if universal). Sits below the Add-to-Cart
                  area so the primary CTA reads first; the green banner is
                  the secondary "or get one today" off-ramp. */}
              {data.total_on_hand <= 0 && <InStockSubstituteCallout sku={data.sku} />}
              {/* B2B-only Lost Sale capture on OOS products. Retail
                  customers never see this — they have the Add-to-Cart
                  special-order path instead. Owner ask 2026-05-17. */}
              {data.total_on_hand <= 0 && isB2B && (
                <button
                  onClick={() => setLostSaleOpen(true)}
                  className="w-full py-2 border border-gray-300 text-gray-700 hover:bg-gray-50 text-sm font-semibold rounded transition"
                >
                  Log lost sale
                </button>
              )}
              {data.total_on_hand <= 0 && (
                <div className="mt-1"><NotifyBackInStock sku={data.sku} /></div>
              )}
            </div>
          )}
          {data.cta_mode === 'quote_shipping' && (
            <button className="mt-6 w-full py-3 bg-orange-600 hover:bg-orange-700 text-white font-semibold rounded">
              Get Shipping Quote (form coming Week 2)
            </button>
          )}
          {data.cta_mode === 'browse_only' && (
            <button className="mt-6 w-full py-3 bg-gray-300 text-gray-700 font-semibold rounded cursor-not-allowed" disabled>
              Browse Only — Not For Sale Online
            </button>
          )}

          {/* Secondary CTAs: Lost Sale + Price Match */}
          <div className="mt-3 flex items-center gap-3 text-xs">
            <button onClick={() => setPriceMatchOpen(true)} className="text-red-700 hover:underline font-semibold">
              💲 Request price match
            </button>
            <span className="text-gray-300">|</span>
            <button onClick={() => setLostSaleOpen(true)} className="text-gray-600 hover:text-gray-900">
              Not what you're looking for?
            </button>
          </div>
        </div>
      </div>

      {/* PDP info tabs */}
      <ProductDetailTabs data={data} sku={sku!} />

      {/* Like-products rail — "Other parts for your truck" when YMM is set,
          "Like this part" when not. When the source is OOS, the rail headline
          pivots to "Available now" so the customer's first signal on the page
          is what we can ship today. Owner ask 2026-05-17 (R1). */}
      <LikeProductsRail sku={sku!} sourceOOS={(data?.total_on_hand ?? 0) <= 0} />

      {/* Recently viewed (filters out the current product) */}
      <RecentlyViewedStrip />

      {lostSaleOpen && <LostSaleModal sku={sku!} onClose={() => setLostSaleOpen(false)} />}
      {priceMatchOpen && <PriceMatchModal sku={sku!} onClose={() => setPriceMatchOpen(false)} />}

    </div>
  )
}

function ProductDetailTabs({ data, sku }: { data: ProductDetail; sku: string }) {
  const { ymm } = useApp()
  const hasKit = !!(data.kit && data.kit.components.length > 0)
  const [tab, setTab] = useState<'contents' | 'desc' | 'specs' | 'stock' | 'fitment'>(hasKit ? 'contents' : 'desc')
  const tabs = [
    ...(hasKit ? [{ id: 'contents' as const, label: `What's Included (${data.kit!.components.length})` }] : []),
    { id: 'desc' as const,    label: 'Description' },
    { id: 'specs' as const,   label: 'Specs' },
    { id: 'stock' as const,   label: 'Stock by warehouse' },
    { id: 'fitment' as const, label: ymm ? `Fitment (${ymm.year} ${ymm.make_name} ${ymm.model_name})` : 'Fitment' },
  ]
  const dims = data.dimensions
  // FEA (features) rows from the scraped/PIES descriptions, in source order.
  // Each row's text is either a single bullet sentence (Layout C/D hero
  // bullets) or "HEADING\n\nbody paragraph" (Layout B carousel) — splitFeature
  // handles both. Other description codes (DES/INL/WAR) are reserved for
  // future rendering; we surface FEA explicitly here because that's the
  // bulk of what the Buyers scrape produced (656 rows across the catalog).
  const features = (() => {
    const all = data.descriptions ?? []
    const fea = all.filter((d) => d.code === 'FEA' && d.text?.trim())
    const src = fea.length ? fea : all.filter((d) => d.code === 'FAB' && d.text?.trim())
    return src.sort((a, b) => a.sequence - b.sequence)
  })()
  const splitFeature = (text: string): { heading: string | null; body: string } => {
    const parts = text.split(/\n\n+/)
    if (parts.length >= 2) {
      return { heading: parts[0].trim(), body: parts.slice(1).join('\n\n').trim() }
    }
    return { heading: null, body: text.trim() }
  }
  const hasSpecs = (
    data.weight_lb !== null ||
    dims.length_in !== null ||
    dims.width_in !== null ||
    dims.height_in !== null ||
    data.freight_class ||
    data.prod_code ||
    (data.attributes ?? []).length > 0
  )
  const hasDescContent = (
    !!data.description || !!data.extended_description || features.length > 0
  )

  return (
    <div className="mt-12 border-t pt-6">
      <div className="flex gap-1 border-b mb-4">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition ${
              tab === t.id
                ? 'border-red-700 text-red-700'
                : 'border-transparent text-gray-600 hover:text-gray-900'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'desc' && (
        // Page widened to max-w-7xl; cap long-form copy at a readable measure
        // (~768px) so description paragraphs + feature bullets don't run the
        // full page width. Specs already cap themselves (max-w-md).
        <div className="prose max-w-3xl text-gray-700">
          {data.description && <p>{data.description}</p>}
          {data.extended_description && (
            <p className="mt-3 text-sm whitespace-pre-line">{data.extended_description}</p>
          )}
          {features.length > 0 && (
            <div className="mt-6">
              <h4 className="font-semibold text-gray-900 mb-3">Features</h4>
              <ul className="list-disc pl-5 space-y-2 text-sm">
                {features.map((f, i) => {
                  const { heading, body } = splitFeature(f.text)
                  return (
                    <li key={i}>
                      {heading && <span className="font-semibold">{heading}: </span>}
                      <span className="whitespace-pre-line">{body}</span>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
          {(data.resources ?? []).length > 0 && (
            <div className="mt-6">
              <h4 className="font-semibold text-gray-900 mb-3">Documents &amp; Downloads</h4>
              <ul className="space-y-2 text-sm not-prose">
                {(data.resources ?? []).map((r, i) => (
                  <li key={i}>
                    <a href={r.url} target="_blank" rel="noopener noreferrer"
                       className="inline-flex items-center gap-2 text-red-700 hover:underline">
                      <span aria-hidden>📄</span>
                      {r.title || 'Download'}
                      <span className="text-xs text-gray-400 uppercase">{r.kind.replace('_', ' ')}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!hasDescContent && (data.resources ?? []).length === 0 && (
            <p className="text-gray-500 italic">No description on file. Call sales for details.</p>
          )}
        </div>
      )}

      {tab === 'specs' && (
        <div className="text-sm text-gray-700">
          {hasSpecs ? (
            <>
              <dl className="grid grid-cols-2 gap-y-2 max-w-md">
                {data.prod_code && (<><dt className="text-gray-500">Brand prefix</dt><dd className="font-mono">{data.prod_code}</dd></>)}
                {data.weight_lb !== null && (<><dt className="text-gray-500">Weight</dt><dd>{data.weight_lb} lb</dd></>)}
                {dims.length_in !== null && (<><dt className="text-gray-500">Length</dt><dd>{dims.length_in}"</dd></>)}
                {dims.width_in !== null  && (<><dt className="text-gray-500">Width</dt><dd>{dims.width_in}"</dd></>)}
                {dims.height_in !== null && (<><dt className="text-gray-500">Height</dt><dd>{dims.height_in}"</dd></>)}
                {data.freight_class && (<><dt className="text-gray-500">Freight class</dt><dd>{data.freight_class}</dd></>)}
              </dl>
              {(data.attributes ?? []).length > 0 && (
                <>
                  <h4 className="mt-6 mb-2 font-semibold text-gray-900">Specifications</h4>
                  <dl className="grid grid-cols-2 gap-y-2 max-w-md">
                    {(data.attributes ?? []).map((a) => (
                      <Fragment key={a.key}>
                        <dt className="text-gray-500">{a.key}</dt>
                        <dd>
                          {a.value}
                          {a.uom ? <span className="text-gray-500"> {a.uom}</span> : null}
                        </dd>
                      </Fragment>
                    ))}
                  </dl>
                </>
              )}
            </>
          ) : (
            <p className="text-gray-500 italic">No specifications on file.</p>
          )}
        </div>
      )}

      {tab === 'contents' && hasKit && (
        <div className="text-sm text-gray-700">
          <p className="text-gray-600 mb-3">
            This package is built from the individual WeatherGuard parts below. Each
            part is also sold separately — click any linked part number to view it.
          </p>
          {(data.kit!.vehicle_model || data.kit!.wheelbase) && (
            <div className="mb-4 flex flex-wrap gap-2">
              {data.kit!.vehicle_model && (
                <span className="px-2 py-1 bg-gray-100 rounded text-xs font-semibold text-gray-700">
                  Fits: {data.kit!.vehicle_model}
                </span>
              )}
              {data.kit!.wheelbase && (
                <span className="px-2 py-1 bg-gray-100 rounded text-xs font-semibold text-gray-700">
                  Wheelbase: {data.kit!.wheelbase}
                </span>
              )}
              {data.kit!.trade && (
                <span className="px-2 py-1 bg-gray-100 rounded text-xs font-semibold text-gray-700">
                  {data.kit!.trade}
                </span>
              )}
            </div>
          )}
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-3 w-16">Qty</th>
                <th className="py-2 pr-3">Part #</th>
                <th className="py-2">Description</th>
              </tr>
            </thead>
            <tbody>
              {data.kit!.components.map((c, i) => (
                <tr key={i} className="border-b last:border-0 align-top">
                  <td className="py-2 pr-3 font-semibold">{c.quantity}</td>
                  <td className="py-2 pr-3 font-mono">
                    {c.sku ? (
                      <Link to={`/product/${c.sku}`} className="text-red-700 hover:underline">
                        {c.part_number}
                      </Link>
                    ) : (
                      <span className="text-gray-700">{c.part_number}</span>
                    )}
                  </td>
                  <td className="py-2 text-gray-700">{c.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'stock' && <WarehouseStockTable sku={sku} />}

      {tab === 'fitment' && <ProductFitmentTab sku={sku} ymm={ymm} />}
    </div>
  )
}

function CartPage() {
  const { cart, user, frontCounter, showroom, updateQty, removeLine } = useApp()
  const navigate = useNavigate()
  const tierBadge = user?.customer_tier
  const isFrontCounter = (frontCounter || showroom) && (tierBadge === 'jobber' || tierBadge === 'dealer')
  const markupPct = user?.front_counter_markup_pct ?? null

  // In Front Counter mode, recompute each line's display price as
  // max(MAP, cost * (1+markup)).  When markup is null/0 we just use MAP.
  function fcQuote(line: CartLine): number | null {
    const v = frontCounterQuote(line.unit_price, null, line.map_retail, markupPct)
    return v === null ? null : parseFloat(v)
  }
  const fcSubtotal = isFrontCounter
    ? cart?.lines.reduce((acc, l) => {
        const q = fcQuote(l)
        return q === null ? acc : acc + q * l.quantity
      }, 0) ?? 0
    : null

  const [receiptBusy, setReceiptBusy] = useState(false)
  async function printCustomerReceipt() {
    if (!cart || cart.lines.length === 0) return
    setReceiptBusy(true)
    try {
      const lines = cart.lines.map((l) => {
        const unit = fcQuote(l) ?? parseFloat(l.unit_price || '0')
        return { sku: l.sku, name: l.name, qty: l.quantity, unit, total: unit * l.quantity }
      })
      const total = fcSubtotal ?? lines.reduce((a, x) => a + x.total, 0)
      const r = await fetch('/api/showroom/receipts', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lines, subtotal: total, tax: 0, total }),
      })
      if (r.ok) { const d = await r.json(); navigate(`/showroom/receipt/${d.id}`) }
    } finally { setReceiptBusy(false) }
  }

  if (!cart || cart.lines.length === 0) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-4">Cart</h1>
        <div className="border-2 border-dashed border-gray-200 rounded-lg p-12 text-center bg-white">
          <div className="text-5xl mb-3">🛒</div>
          <div className="text-lg font-semibold text-gray-800 mb-1">Your cart is empty</div>
          <p className="text-sm text-gray-500 mb-6">Search for parts or browse by category to get started.</p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Link to="/catalog" className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Browse all products</Link>
            <Link to="/brands" className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm rounded">Shop by brand</Link>
            <Link to="/catalog?in_stock=1" className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm rounded">In stock now</Link>
          </div>
        </div>
        <RecentlyViewedStrip />
      </div>
    )
  }
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h1 className="text-3xl font-bold mb-4">Cart</h1>
      {isFrontCounter && (
        <div className="mb-3 p-3 bg-orange-50 border border-orange-200 rounded text-sm text-orange-800">
          🛍️ Front Counter view — totals reflect what you'd quote a walk-in
          {markupPct ? <> (cost + {markupPct}%, floored by MAP)</> : <> (MAP Retail)</>}.
          The order you place with Nelson still uses your wholesale prices — toggle off to confirm.
        </div>
      )}
      <div className="space-y-3">
        {cart.lines.map((l) => {
          const fc = isFrontCounter ? fcQuote(l) : null
          return (
            // Mobile: product info on top (full width), controls (qty / price /
            // remove) on a second row.  Desktop (sm+): single row with
            // product info flex-1 and controls fixed-width on the right.
            <div key={l.id} className="p-3 border rounded flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
              <Link to={`/product/${l.sku}`} className="flex-1 min-w-0">
                <div className="text-xs text-gray-500">{l.brand}</div>
                <div className="font-mono text-sm">{formatPartNumber(l.sku, l.brand)}</div>
                <div className="text-sm">{l.name}</div>
              </Link>
              <div className="flex items-center justify-between gap-3 sm:contents">
                <div>
                  <label className="text-[10px] uppercase tracking-wide text-gray-500 sm:hidden">Qty</label>
                  <input type="number" min={1} max={999} value={l.quantity}
                         onChange={(e) => updateQty(l.id, Math.max(1, parseInt(e.target.value) || 1))}
                         className="w-16 border rounded px-2 py-1 block" />
                </div>
                <div className="w-28 text-right">
                  {isFrontCounter && fc !== null ? (
                    <>
                      <div className="text-xs text-gray-400 line-through">${l.unit_price} ea</div>
                      <div className="text-sm text-orange-700">${fc.toFixed(2)} ea</div>
                      <div className="font-semibold">${(fc * l.quantity).toFixed(2)}</div>
                    </>
                  ) : (
                    <>
                      <div className="text-sm text-gray-500">${l.unit_price} ea</div>
                      <div className="font-semibold">${l.line_total}</div>
                    </>
                  )}
                </div>
                <button onClick={() => removeLine(l.id)}
                        aria-label="Remove from cart"
                        className="text-red-700 hover:text-red-900 text-sm whitespace-nowrap px-2 py-1 rounded hover:bg-red-50">
                  Remove
                </button>
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-6 p-4 bg-gray-50 rounded flex items-center justify-between">
        <div>
          <div className="text-lg">Subtotal ({cart.item_count} items)</div>
          {isFrontCounter && (
            <div className="text-xs text-gray-500 mt-1">Wholesale subtotal: ${cart.subtotal}</div>
          )}
        </div>
        <div className="text-2xl font-bold">
          ${isFrontCounter && fcSubtotal !== null ? fcSubtotal.toFixed(2) : cart.subtotal}
        </div>
      </div>
      <button onClick={() => navigate('/checkout')}
              className="mt-4 w-full py-3 bg-red-700 hover:bg-red-800 text-white font-semibold rounded">
        Checkout
      </button>
      {showroom && isFrontCounter && (
        <button onClick={printCustomerReceipt} disabled={receiptBusy}
                className="mt-3 w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white font-semibold rounded disabled:opacity-50">
          {receiptBusy ? 'Creating…' : '🧾 Print customer receipt'}
        </button>
      )}
    </div>
  )
}

interface ShowroomReceiptData {
  id: number; receipt_number: string; status: string; display_name: string | null; logo_url: string | null
  lines: { sku: string; name: string; qty: number; unit: number; total: number }[]
  retail_subtotal: number; retail_tax: number; retail_total: number; created_at: string
}

function ShowroomReceiptPage() {
  const { id } = useParams()
  const [r, setR] = useState<ShowroomReceiptData | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetch(`/api/showroom/receipts/${id}`, { credentials: 'include' })
      .then((res) => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json() })
      .then(setR).catch((e) => setErr(String(e.message || e)))
  }, [id])

  async function setStatus(status: 'paid' | 'unpaid') {
    const res = await fetch(`/api/showroom/receipts/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
    })
    if (res.ok) setR(await res.json())
  }

  if (err) return <div className="mx-auto max-w-md p-6 text-red-700">{err}</div>
  if (!r) return <div className="p-6 text-gray-400">Loading…</div>
  return (
    <div className="mx-auto max-w-md p-4">
      <div className="mb-3 flex items-center gap-3 print:hidden">
        <Link to="/cart" className="text-sm font-semibold text-red-700 hover:underline">← Cart</Link>
        <Link to="/showroom/receipts" className="text-sm text-gray-600 hover:underline">All receipts</Link>
        <button onClick={() => window.print()} className="ml-auto rounded bg-gray-800 px-3 py-1.5 text-sm font-semibold text-white hover:bg-gray-700">🖨 Print</button>
      </div>
      <div className="rounded-lg border border-gray-200 bg-white p-5">
        <div className="text-center">
          {r.logo_url
            ? <img src={r.logo_url} alt="" className="mx-auto h-12 w-auto max-w-[200px] object-contain" />
            : <div className="text-xl font-extrabold text-gray-900">{r.display_name || 'Receipt'}</div>}
          {r.logo_url && r.display_name && <div className="mt-1 text-sm font-semibold text-gray-700">{r.display_name}</div>}
        </div>
        <div className="mt-3 flex items-center justify-between text-xs text-gray-500">
          <span>Receipt {r.receipt_number}</span>
          <span>{new Date(r.created_at).toLocaleString()}</span>
        </div>
        <div className="my-2 flex justify-center">
          <span className={`rounded-full px-3 py-0.5 text-xs font-bold uppercase ${r.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{r.status}</span>
        </div>
        <table className="w-full text-sm">
          <thead><tr className="border-b text-left text-[11px] uppercase text-gray-400"><th className="py-1">Item</th><th className="py-1 text-center">Qty</th><th className="py-1 text-right">Price</th><th className="py-1 text-right">Total</th></tr></thead>
          <tbody>
            {r.lines.map((l, i) => (
              <tr key={i} className="border-b border-gray-100">
                <td className="py-1.5"><div className="font-medium text-gray-800">{l.name}</div><div className="text-[11px] text-gray-400">{l.sku}</div></td>
                <td className="text-center">{l.qty}</td>
                <td className="text-right">${l.unit.toFixed(2)}</td>
                <td className="text-right font-semibold">${l.total.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 space-y-1 text-sm">
          <div className="flex justify-between text-gray-600"><span>Subtotal</span><span>${r.retail_subtotal.toFixed(2)}</span></div>
          {r.retail_tax > 0 && <div className="flex justify-between text-gray-600"><span>Tax</span><span>${r.retail_tax.toFixed(2)}</span></div>}
          <div className="flex justify-between text-lg font-bold"><span>Total</span><span>${r.retail_total.toFixed(2)}</span></div>
        </div>
        <p className="mt-4 text-center text-[11px] text-gray-400">Thank you!</p>
      </div>
      <div className="mt-3 flex gap-2 print:hidden">
        {r.status === 'unpaid'
          ? <button onClick={() => setStatus('paid')} className="flex-1 rounded bg-emerald-600 py-2 text-sm font-bold text-white hover:bg-emerald-700">Mark PAID</button>
          : <button onClick={() => setStatus('unpaid')} className="flex-1 rounded border border-gray-300 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">Mark unpaid</button>}
      </div>
    </div>
  )
}

function ShowroomReceiptsPage() {
  const [rows, setRows] = useState<ShowroomReceiptData[]>([])
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    fetch('/api/showroom/receipts', { credentials: 'include' })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setRows).catch((e) => setErr(String(e.message || e)))
  }, [])
  return (
    <div className="mx-auto max-w-2xl p-4">
      <div className="mb-3 flex items-center gap-3">
        <Link to="/cart" className="text-sm font-semibold text-red-700 hover:underline">← Cart</Link>
        <h1 className="text-2xl font-bold">Customer Receipts</h1>
      </div>
      {err ? <div className="text-red-700">{err}</div> : rows.length === 0 ? <div className="rounded border border-dashed border-gray-300 p-8 text-center text-gray-500">No receipts yet.</div> : (
        <div className="divide-y rounded-lg border border-gray-200">
          {rows.map((r) => (
            <Link key={r.id} to={`/showroom/receipt/${r.id}`} className="flex items-center gap-3 p-3 hover:bg-gray-50">
              <span className="font-mono text-sm">{r.receipt_number}</span>
              <span className="text-sm text-gray-600">{new Date(r.created_at).toLocaleString()}</span>
              <span className="ml-auto font-semibold">${r.retail_total.toFixed(2)}</span>
              <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${r.status === 'paid' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{r.status}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

function LoginPage() {
  const navigate = useNavigate()
  const { refreshUser, refreshCart } = useApp()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true); setError(null)
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    setLoading(false)
    if (r.ok) {
      await refreshUser(); await refreshCart()
      navigate('/')
    } else {
      const body = await r.json().catch(() => ({}))
      setError(body.detail || `HTTP ${r.status}`)
    }
  }

  return (
    <div className="p-6 max-w-md mx-auto">
      <h1 className="text-3xl font-bold mb-4">Log in</h1>
      <form onSubmit={submit} className="space-y-3">
        <input type="email" required placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} className="w-full border rounded px-3 py-2" />
        <input type="password" required placeholder="Password" value={password}
               onChange={(e) => setPassword(e.target.value)} className="w-full border rounded px-3 py-2" />
        {error && <div className="text-red-700 text-sm">{error}</div>}
        <button type="submit" disabled={loading} className="w-full py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50">
          {loading ? 'Logging in…' : 'Log in'}
        </button>
      </form>
      <div className="mt-4 text-sm text-gray-600">
        No account? <Link to="/signup" className="text-red-700 hover:underline">Sign up</Link>
      </div>
    </div>
  )
}

function SignupPage() {
  const navigate = useNavigate()
  const { refreshUser, refreshCart } = useApp()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [customerNumber, setCustomerNumber] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true); setError(null)
    const r = await fetch('/api/auth/signup', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email,
        password,
        display_name: displayName || null,
        customer_number: customerNumber.trim() || null,
      }),
    })
    setLoading(false)
    if (r.ok) {
      await refreshUser(); await refreshCart()
      navigate('/')
    } else {
      const body = await r.json().catch(() => ({}))
      setError(body.detail || `HTTP ${r.status}`)
    }
  }

  return (
    <div className="p-6 max-w-md mx-auto">
      <h1 className="text-3xl font-bold mb-4">Sign up</h1>
      <form onSubmit={submit} className="space-y-3">
        <input type="text" placeholder="Display name (optional)" value={displayName}
               onChange={(e) => setDisplayName(e.target.value)} className="w-full border rounded px-3 py-2" />
        <input type="email" required placeholder="Email" value={email}
               onChange={(e) => setEmail(e.target.value)} className="w-full border rounded px-3 py-2" />
        <input type="password" required minLength={8} placeholder="Password (8+ chars)" value={password}
               onChange={(e) => setPassword(e.target.value)} className="w-full border rounded px-3 py-2" />
        <div>
          <input type="text" placeholder="Nelson customer number (optional, for B2B pricing)"
                 value={customerNumber}
                 onChange={(e) => setCustomerNumber(e.target.value)}
                 className="w-full border rounded px-3 py-2" />
          <div className="text-xs text-gray-500 mt-1">Already an account holder? Enter your Nelson customer number to unlock tier pricing. You can also link it later from your account page.</div>
        </div>
        {error && <div className="text-red-700 text-sm">{error}</div>}
        <button type="submit" disabled={loading} className="w-full py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50">
          {loading ? 'Creating…' : 'Create account'}
        </button>
      </form>
      <div className="mt-4 text-sm text-gray-600">
        Have an account? <Link to="/login" className="text-red-700 hover:underline">Log in</Link>
      </div>
    </div>
  )
}

function AccountPage() {
  const { user, refreshUser, setImpersonateOpen, setShowroom } = useApp()
  const navigate = useNavigate()
  const [customerNumber, setCustomerNumber] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [linked, setLinked] = useState(false)

  // Front Counter markup form
  const [markup, setMarkup] = useState<string>('')
  const [markupBusy, setMarkupBusy] = useState(false)
  const [markupError, setMarkupError] = useState<string | null>(null)
  const [markupSaved, setMarkupSaved] = useState(false)
  useEffect(() => { setMarkup(user?.front_counter_markup_pct?.toString() ?? '') }, [user])

  // Retail Showroom Mode settings
  const [srName, setSrName] = useState('')
  const [srBusy, setSrBusy] = useState(false)
  const [srMsg, setSrMsg] = useState<string | null>(null)
  const [srUploading, setSrUploading] = useState(false)
  useEffect(() => { setSrName(user?.showroom_display_name ?? '') }, [user])

  async function saveShowroom(enabled: boolean) {
    setSrBusy(true); setSrMsg(null)
    try {
      const r = await fetch('/api/auth/showroom-settings', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, display_name: srName.trim() || null }),
      })
      if (!r.ok) { setSrMsg(formatApiError(await r.json().catch(() => ({})), r.status)); return }
      await refreshUser()
      setSrMsg('✓ Saved.')
    } catch { setSrMsg('Network error') } finally { setSrBusy(false) }
  }

  async function uploadShowroomLogo(file: File) {
    setSrUploading(true); setSrMsg(null)
    try {
      const fd = new FormData(); fd.append('image', file)
      const r = await fetch('/api/auth/showroom-logo', { method: 'POST', credentials: 'include', body: fd })
      if (!r.ok) { setSrMsg(`Upload failed: ${formatApiError(await r.json().catch(() => ({})), r.status)}`); return }
      await refreshUser()
      setSrMsg('✓ Logo uploaded.')
    } catch { setSrMsg('Upload failed') } finally { setSrUploading(false) }
  }

  if (!user) return <div className="p-6 max-w-md mx-auto">Please <Link to="/login" className="text-red-700 hover:underline">log in</Link>.</div>

  async function link(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null); setLinked(false)
    const r = await fetch('/api/auth/link-customer', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ customer_number: customerNumber.trim() }),
    })
    setBusy(false)
    if (r.ok) {
      await refreshUser()
      setLinked(true)
      setCustomerNumber('')
    } else {
      const body = await r.json().catch(() => ({}))
      setError(body.detail || `HTTP ${r.status}`)
    }
  }

  async function saveMarkup(e: React.FormEvent) {
    e.preventDefault()
    setMarkupBusy(true); setMarkupError(null); setMarkupSaved(false)
    const v = Math.max(0, Math.min(500, parseInt(markup, 10) || 0))
    const r = await fetch('/api/auth/front-counter-markup', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markup_pct: v }),
    })
    setMarkupBusy(false)
    if (r.ok) {
      await refreshUser()
      setMarkupSaved(true)
    } else {
      const body = await r.json().catch(() => ({}))
      setMarkupError(formatApiError(body, r.status))
    }
  }

  const showFrontCounter = user.customer_tier === 'jobber' || user.customer_tier === 'dealer'

  type AdminTool = { icon: string; title: string; desc: string; to?: string; href?: string; onClick?: () => void; newTab?: boolean }
  const adminTools: AdminTool[] = [
    { icon: '🖼️', title: 'Banner Manager', desc: 'Homepage rotating banner — audience-scoped & schedulable slides', to: '/admin/banners' },
    { icon: '📝', title: 'Content pages', desc: 'Edit the FAQ and trust pages (About, Returns, Shipping, Privacy)', to: '/admin/content' },
    { icon: '📜', title: 'Audit Log', desc: 'Every admin action, per user — who changed what, and when', to: '/admin/audit-log' },
    { icon: '🩺', title: 'Site Health', desc: 'Nightly product & site health report (both sites) — download the Word doc', to: '/admin/site-health' },
    { icon: '💡', title: 'Build Ideas', desc: 'Backlog of future website features — admin-only, parked for later', to: '/admin/build-ideas' },
    { icon: '📐', title: 'Special Rules', desc: 'Non-obvious storefront rules — e.g. Dodge/RAM make merge', to: '/admin/special-rules' },
    { icon: '🗂️', title: 'Catalog visibility & shipping', desc: 'Turn manufacturer lines on/off (fully or partially); set shipping mode & flat rates — opens in a new window', href: '/admin/catalog-visibility?window=1', newTab: true },
    { icon: '📣', title: 'Message board', desc: 'Kit-conflict warnings + live site health (page errors, cart/checkout failures, JS errors)', to: '/admin/messages' },
    { icon: '📦', title: 'Kit packages', desc: 'Create & manage package kits (bill of materials, fitment, placement)', to: '/admin/kits' },
    { icon: '🏷️', title: 'Category image curation', desc: 'Pin a representative image for each catalog category', to: '/admin/category-images' },
    { icon: '🎛️', title: 'Attribute value curation', desc: 'Fold near-duplicate PIES values into one customer-facing filter bucket', to: '/admin/attribute-curator' },
    { icon: '🔀', title: 'Attribute key merge curation', desc: 'Merge synonym filter groups (e.g. Volume + Gallon Capacity) into one facet', to: '/admin/attribute-key-curator' },
    { icon: '🛒', title: 'Shop as Customer', desc: "Place orders, file RMAs, or build carts on a customer's behalf", onClick: () => setImpersonateOpen(true) },
    { icon: '✅', title: 'Customer link requests', desc: 'Approve or reject account-link requests from new users', href: '/admin-customer-link-requests.html' },
  ]
  const adminCardCls = 'group flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-3 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-red-300 hover:shadow-md'
  const adminCardInner = (t: AdminTool) => (
    <>
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-red-50 text-lg">{t.icon}</div>
      <div className="min-w-0">
        <div className="flex items-center gap-1 text-sm font-semibold text-gray-900 group-hover:text-red-700">
          {t.title}<span className="text-red-400 transition group-hover:translate-x-0.5">→</span>
        </div>
        <div className="mt-0.5 text-xs leading-snug text-gray-500">{t.desc}</div>
      </div>
    </>
  )

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-8">
      <h1 className="text-3xl font-bold">Account</h1>

      {user.role === 'admin' && (
        <section className="rounded-2xl border border-gray-200 bg-gradient-to-b from-gray-50 to-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            <h2 className="text-lg font-bold text-gray-900">Admin tools</h2>
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-red-700">Admin</span>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {adminTools.map((t) =>
              t.to ? <Link key={t.title} to={t.to} className={adminCardCls}>{adminCardInner(t)}</Link>
              : t.href ? <a key={t.title} href={t.href} {...(t.newTab ? { target: '_blank', rel: 'noopener noreferrer' } : {})} className={adminCardCls}>{adminCardInner(t)}</a>
              : <button key={t.title} onClick={t.onClick} className={adminCardCls}>{adminCardInner(t)}</button>
            )}
          </div>
        </section>
      )}

      <dl className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
        <dt className="text-gray-500">Email</dt><dd>{user.email}</dd>
        <dt className="text-gray-500">Display name</dt><dd>{user.display_name || <span className="text-gray-400">—</span>}</dd>
        <dt className="text-gray-500">Role</dt><dd className="uppercase tracking-wide">{user.role}</dd>
        <dt className="text-gray-500">Customer #</dt><dd>{user.customer_number || <span className="text-gray-400">not linked</span>}</dd>
        <dt className="text-gray-500">Customer name</dt><dd>{user.customer_name || <span className="text-gray-400">—</span>}</dd>
        <dt className="text-gray-500">Pricing tier</dt><dd className="uppercase tracking-wide">{user.customer_tier || <span className="text-gray-400">retail (anonymous-equivalent)</span>}</dd>
        {showFrontCounter && (
          <>
            <dt className="text-gray-500">Front Counter markup</dt>
            <dd>{user.front_counter_markup_pct ? `${user.front_counter_markup_pct}%` : <span className="text-gray-400">not set (defaults to MAP Retail)</span>}</dd>
          </>
        )}
      </dl>

      {!user.customer_id && (
        <div className="border rounded p-4 bg-blue-50 border-blue-200">
          <h2 className="font-semibold mb-2">Link a Nelson customer account</h2>
          <p className="text-sm text-gray-700 mb-3">If you already buy from Nelson, enter your customer number to unlock B2B contract pricing.</p>
          <form onSubmit={link} className="flex gap-2">
            <input type="text" placeholder="e.g. 25649"
                   value={customerNumber}
                   onChange={(e) => setCustomerNumber(e.target.value)}
                   className="flex-1 border rounded px-3 py-2" required />
            <button type="submit" disabled={busy} className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white rounded disabled:opacity-50">
              {busy ? 'Linking…' : 'Link'}
            </button>
          </form>
          {error && <div className="text-red-700 text-sm mt-2">{error}</div>}
          {linked && <div className="text-green-700 text-sm mt-2">✓ Linked successfully.</div>}
        </div>
      )}

      {showFrontCounter && (
        <div className="border rounded p-4 bg-orange-50 border-orange-200">
          <h2 className="font-semibold mb-1">Front Counter Mode markup</h2>
          <p className="text-sm text-gray-700 mb-3">When the Front Counter toggle is on, we apply this markup to your wholesale cost (floored by MAP) so the displayed price is what you'd quote a walk-in customer. Set to <strong>0</strong> to just show MAP Retail.</p>
          <form onSubmit={saveMarkup} className="flex items-center gap-2">
            <input type="number" min={0} max={500} value={markup}
                   onChange={(e) => setMarkup(e.target.value)}
                   className="w-24 border rounded px-3 py-2" />
            <span className="text-sm text-gray-600">%</span>
            <button type="submit" disabled={markupBusy} className="ml-2 px-4 py-2 bg-red-700 hover:bg-red-800 text-white rounded disabled:opacity-50">
              {markupBusy ? 'Saving…' : 'Save markup'}
            </button>
          </form>
          {markupError && <div className="text-red-700 text-sm mt-2">{markupError}</div>}
          {markupSaved && <div className="text-green-700 text-sm mt-2">✓ Saved.</div>}
        </div>
      )}

      {showFrontCounter && (
        <div className="border rounded p-4 bg-slate-50 border-slate-200">
          <h2 className="font-semibold mb-1">Retail Showroom Mode</h2>
          <p className="text-sm text-gray-700 mb-3">
            Turn this site into <strong>your own branded counter catalog</strong> for a walk-in customer: your logo,
            only Truck Accessories, and retail-facing pricing (using your markup above). Starting it locks this device
            into the customer view until a staff password is entered.
          </p>

          <label className="block text-xs font-semibold text-gray-600">Store name (shown on the kiosk &amp; receipts)</label>
          <input value={srName} onChange={(e) => setSrName(e.target.value)} placeholder={user.customer_name || 'Your store name'}
                 className="mb-3 w-full max-w-md border rounded px-3 py-2 text-sm" />

          <label className="block text-xs font-semibold text-gray-600">Your logo</label>
          <div className="mb-3 flex items-center gap-3">
            {user.showroom_logo_url
              ? <img src={user.showroom_logo_url} alt="logo" className="h-12 w-auto max-w-[180px] rounded border bg-white object-contain p-1" />
              : <span className="text-sm text-gray-400">No logo — a plain “{srName || user.customer_name || 'Online Catalog'}” wordmark is shown.</span>}
            <label className="cursor-pointer text-sm font-semibold text-blue-700 hover:underline">
              {srUploading ? 'Uploading…' : (user.showroom_logo_url ? 'Replace logo' : '↑ Upload logo')}
              <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && uploadShowroomLogo(e.target.files[0])} />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => saveShowroom(true)} disabled={srBusy}
                    className="px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white rounded text-sm font-semibold disabled:opacity-50">
              {srBusy ? 'Saving…' : 'Save settings'}
            </button>
            <button onClick={() => { enterFullscreen(); setShowroom(true); navigate('/') }}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-sm font-bold">
              ▶ Start Showroom Mode on this device
            </button>
            {srMsg && <span className={`text-sm ${srMsg.startsWith('✓') ? 'text-green-700' : 'text-red-700'}`}>{srMsg}</span>}
          </div>
          <p className="mt-2 text-[11px] text-gray-500">To leave Showroom Mode, use “🔒 Staff exit” in the top bar and enter your account password.</p>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Checkout / Orders
// ============================================================================

interface AddressForm {
  name: string
  company: string
  addr1: string
  addr2: string
  city: string
  state: string
  zip: string
}

const blankAddress: AddressForm = { name: '', company: '', addr1: '', addr2: '', city: '', state: '', zip: '' }

function CheckoutPage() {
  const navigate = useNavigate()
  const { user, cart, refreshCart, impersonation } = useApp()
  // When an admin is shopping as a customer, checkout resolves to that
  // customer server-side, so treat the session as linked even though the
  // admin's own user.customer_id is null.
  const effectiveCustomerLinked = !!user?.customer_id || !!impersonation?.impersonating

  const [shipping, setShipping] = useState<AddressForm>(blankAddress)
  const [billing, setBilling] = useState<AddressForm>(blankAddress)
  const [billingSame, setBillingSame] = useState(true)
  const [contactEmail, setContactEmail] = useState(user?.email || '')
  const [contactPhone, setContactPhone] = useState('')
  // Payment type is fixed to PO for now; no setter until a credit-card toggle
  // is added (the union type is kept so that change is a one-liner).
  const [paymentType] = useState<'purchase_order' | 'credit_card'>('purchase_order')
  const [poNumber, setPoNumber] = useState('')
  const [requiredDate, setRequiredDate] = useState('')
  const [comments, setComments] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { setContactEmail(user?.email || '') }, [user])

  if (!user) return (
    <div className="p-6 max-w-md mx-auto">
      <h1 className="text-2xl font-bold mb-3">Checkout</h1>
      <p className="text-gray-700">Please <Link to="/login" className="text-red-700 underline">log in</Link> or <Link to="/signup" className="text-red-700 underline">sign up</Link> to place an order.</p>
    </div>
  )

  if (!effectiveCustomerLinked) return (
    <div className="p-6 max-w-md mx-auto">
      <h1 className="text-2xl font-bold mb-3">Checkout</h1>
      <div className="p-4 bg-yellow-50 border border-yellow-200 rounded text-sm">
        Your account isn't linked to a Nelson customer record yet, so we can't push your order to fulfillment. <Link to="/account" className="text-red-700 underline">Link your customer number</Link> or contact <a href="mailto:sales@nelsontruck.com" className="text-red-700 underline">sales@nelsontruck.com</a>.
      </div>
    </div>
  )

  if (!cart || cart.lines.length === 0) return (
    <div className="p-6 max-w-md mx-auto">
      <h1 className="text-2xl font-bold mb-3">Checkout</h1>
      <p className="text-gray-700">Your cart is empty. <Link to="/catalog" className="text-red-700 underline">Browse the catalog →</Link></p>
    </div>
  )

  function setShipField<K extends keyof AddressForm>(k: K, v: string) {
    setShipping((s) => ({ ...s, [k]: v }))
  }
  function setBillField<K extends keyof AddressForm>(k: K, v: string) {
    setBilling((s) => ({ ...s, [k]: v }))
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    const payload: any = {
      shipping,
      billing: billingSame ? null : billing,
      contact_email: contactEmail,
      contact_phone: contactPhone,
      payment_type: paymentType,
      customer_po_number: poNumber.trim() || null,
      comments: comments.trim() || null,
      required_date: requiredDate || null,
    }
    const r = await fetch('/api/orders/checkout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setBusy(false)
    if (r.ok) {
      const order = await r.json() as OrderOut
      await refreshCart()
      navigate(`/orders/${order.web_order_number}?placed=1`)
    } else {
      const body = await r.json().catch(() => ({}))
      setError(formatApiError(body, r.status))
    }
  }

  function addrFields(prefix: string, addr: AddressForm, setField: (k: keyof AddressForm, v: string) => void, required: boolean) {
    return (
      <div className="grid grid-cols-2 gap-3">
        <input className="col-span-2 border rounded px-3 py-2" placeholder={`${prefix} name`} value={addr.name} onChange={(e) => setField('name', e.target.value)} required={required} />
        <input className="col-span-2 border rounded px-3 py-2" placeholder="Company (optional)" value={addr.company} onChange={(e) => setField('company', e.target.value)} />
        <input className="col-span-2 border rounded px-3 py-2" placeholder="Address line 1" value={addr.addr1} onChange={(e) => setField('addr1', e.target.value)} required={required} />
        <input className="col-span-2 border rounded px-3 py-2" placeholder="Address line 2 (optional)" value={addr.addr2} onChange={(e) => setField('addr2', e.target.value)} />
        <input className="border rounded px-3 py-2" placeholder="City" value={addr.city} onChange={(e) => setField('city', e.target.value)} required={required} />
        <div className="grid grid-cols-2 gap-3">
          <input className="border rounded px-3 py-2 uppercase" placeholder="ST" maxLength={2} value={addr.state} onChange={(e) => setField('state', e.target.value.toUpperCase())} required={required} />
          <input className="border rounded px-3 py-2" placeholder="Zip" value={addr.zip} onChange={(e) => setField('zip', e.target.value)} required={required} />
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Checkout</h1>
      <div className="grid grid-cols-1 md:grid-cols-[1fr_360px] gap-8">
        <form onSubmit={submit} className="space-y-6">
          <section>
            <h2 className="font-semibold text-lg mb-3">Ship to</h2>
            {addrFields('Recipient', shipping, setShipField, true)}
          </section>

          <section>
            <h2 className="font-semibold text-lg mb-3">Billing</h2>
            <label className="flex items-center gap-2 text-sm mb-3">
              <input type="checkbox" checked={billingSame} onChange={(e) => setBillingSame(e.target.checked)} />
              Same as shipping
            </label>
            {!billingSame && addrFields('Billing', billing, setBillField, true)}
          </section>

          <section>
            <h2 className="font-semibold text-lg mb-3">Contact</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <input type="email" required placeholder="Email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} className="border rounded px-3 py-2" />
              <input type="tel" required placeholder="Phone" value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} className="border rounded px-3 py-2" />
            </div>
          </section>

          <section>
            <h2 className="font-semibold text-lg mb-3">Payment</h2>
            <div className="text-sm bg-gray-50 border rounded p-3">
              <div className="font-medium text-gray-900">Purchase order — net terms</div>
              <p className="text-gray-600 mt-1">Billed to your Nelson account on your established terms. Enter your PO number below if you have one.</p>
            </div>
            <input className="mt-3 w-full border rounded px-3 py-2" placeholder="Your PO number (optional)" value={poNumber} onChange={(e) => setPoNumber(e.target.value)} />
          </section>

          <section>
            <h2 className="font-semibold text-lg mb-3">Notes</h2>
            <div className="space-y-3">
              <label className="block text-sm">
                Required by (optional)
                <input type="date" className="mt-1 block w-48 border rounded px-3 py-2" value={requiredDate} onChange={(e) => setRequiredDate(e.target.value)} />
              </label>
              <textarea className="w-full border rounded px-3 py-2 min-h-[80px]" placeholder="Special instructions, delivery notes, etc." value={comments} onChange={(e) => setComments(e.target.value)} />
            </div>
          </section>

          {error && <div className="p-3 border border-red-300 bg-red-50 text-red-800 text-sm rounded">{error}</div>}

          <button type="submit" disabled={busy} className="w-full py-3 bg-red-700 hover:bg-red-800 text-white font-semibold rounded disabled:opacity-50 transition">
            {busy ? 'Placing order…' : 'Place order'}
          </button>
        </form>

        <aside className="bg-gray-50 rounded p-4 h-fit sticky top-20 space-y-3">
          <h3 className="font-semibold mb-2">Order summary</h3>
          {cart.lines.map((l) => (
            <div key={l.id} className="text-sm flex items-start gap-2 border-b border-gray-200 pb-2 last:border-0">
              <div className="flex-1">
                <div className="font-mono text-xs text-gray-500">{formatPartNumber(l.sku, l.brand)}</div>
                <div className="text-gray-700 line-clamp-2">{l.name}</div>
                <div className="text-xs text-gray-500">qty {l.quantity} × ${l.unit_price}</div>
              </div>
              <div className="font-semibold">${l.line_total}</div>
            </div>
          ))}
          <div className="flex justify-between pt-2 border-t border-gray-300">
            <span>Subtotal</span>
            <span className="font-bold">${cart.subtotal}</span>
          </div>
          <p className="text-xs text-gray-500">Freight is added by Nelson as a flat fee and appears on your invoice. Sales tax is applied based on your ship-to address.</p>
        </aside>
      </div>
    </div>
  )
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    pending: 'bg-gray-200 text-gray-700',
    placed: 'bg-blue-100 text-blue-700',
    pushed_to_facs: 'bg-amber-100 text-amber-800',
    acknowledged: 'bg-green-100 text-green-700',
    shipped: 'bg-emerald-100 text-emerald-700',
    delivered: 'bg-emerald-200 text-emerald-900',
    cancelled: 'bg-red-100 text-red-700',
    quote: 'bg-purple-100 text-purple-700',
  }
  const cls = map[status] || 'bg-gray-100 text-gray-700'
  return <span className={`px-2 py-0.5 text-xs rounded uppercase tracking-wide ${cls}`}>{status.replace('_', ' ')}</span>
}

type ReorderResult = { lines_added: number; lines_skipped: number; skipped_reasons: string[] }

function OrdersPage() {
  const { user, refreshCart } = useApp()
  const navigate = useNavigate()
  const [orders, setOrders] = useState<OrderSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reorderingId, setReorderingId] = useState<number | null>(null)
  const [reorderResult, setReorderResult] = useState<ReorderResult | null>(null)
  const [reorderError, setReorderError] = useState<string | null>(null)

  useEffect(() => {
    if (!user) return
    fetch('/api/orders', { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setOrders)
      .catch((e) => setError(e.message))
  }, [user])

  async function reorder(o: OrderSummary) {
    setReorderingId(o.id)
    setReorderResult(null); setReorderError(null)
    const r = await fetch(`/api/orders/${o.web_order_number}/reorder`, {
      method: 'POST', credentials: 'include',
    })
    setReorderingId(null)
    if (r.ok) {
      const data: ReorderResult = await r.json()
      await refreshCart()
      setReorderResult(data)
    } else {
      const body = await r.json().catch(() => ({}))
      setReorderError(formatApiError(body, r.status))
    }
  }

  if (!user) return <div className="p-6 max-w-md mx-auto">Please <Link to="/login" className="text-red-700 underline">log in</Link>.</div>
  if (error) return <div className="p-6 text-red-700">Error: {error}</div>

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-3xl font-bold mb-6">Your orders</h1>

      {/* Inline reorder result — replaces the old blocking native alert().
          Shows added + skipped counts, lists skipped SKUs + reasons, and
          gives the user a clear "Go to cart" CTA so the navigation is no
          longer automatic / hidden. */}
      {reorderResult && (
        <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-green-900">
                ✓ Added {reorderResult.lines_added} line{reorderResult.lines_added === 1 ? '' : 's'} to your cart
                {reorderResult.lines_skipped > 0 && (
                  <span className="text-amber-700"> · {reorderResult.lines_skipped} skipped</span>
                )}
              </div>
              {reorderResult.skipped_reasons.length > 0 && (
                <ul className="mt-2 text-xs text-amber-800 list-disc list-inside space-y-0.5">
                  {reorderResult.skipped_reasons.slice(0, 6).map((s, i) => <li key={i}>{s}</li>)}
                  {reorderResult.skipped_reasons.length > 6 && (
                    <li className="text-amber-600">…and {reorderResult.skipped_reasons.length - 6} more</li>
                  )}
                </ul>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <button onClick={() => setReorderResult(null)} className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1">Dismiss</button>
              <button onClick={() => navigate('/cart')} className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Go to cart →</button>
            </div>
          </div>
        </div>
      )}
      {reorderError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">
          Reorder failed: {reorderError}
          <button onClick={() => setReorderError(null)} className="ml-3 text-xs text-red-600 hover:underline">Dismiss</button>
        </div>
      )}

      {!orders ? (
        <div className="text-gray-500">Loading…</div>
      ) : orders.length === 0 ? (
        <div className="border-2 border-dashed border-gray-200 rounded-lg p-12 text-center bg-white">
          <div className="text-5xl mb-3">📦</div>
          <div className="text-lg font-semibold text-gray-800 mb-1">No orders yet</div>
          <p className="text-sm text-gray-500 mb-6">Once you place an order it'll show here with reorder and FACS tracking.</p>
          <Link to="/catalog" className="inline-block px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Browse the catalog →</Link>
        </div>
      ) : (
        <>
          {/* Mobile: card list (each order as a stacked tile) */}
          <div className="space-y-3 md:hidden">
            {orders.map((o) => (
              <div key={o.id} className="border rounded p-3 bg-white">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <Link to={`/orders/${o.web_order_number}`} className="font-mono text-sm text-red-700 hover:underline">
                    {o.web_order_number}
                  </Link>
                  {statusBadge(o.status)}
                </div>
                <div className="text-xs text-gray-600 mb-2">{new Date(o.placed_at).toLocaleString()}</div>
                <div className="grid grid-cols-3 gap-2 text-xs text-gray-700 mb-3">
                  <div><span className="text-gray-500 block">Items</span><span className="font-semibold">{o.item_count}</span></div>
                  <div><span className="text-gray-500 block">Files</span><span className="font-semibold">{o.fulfillment_count}</span></div>
                  <div><span className="text-gray-500 block">Total</span><span className="font-semibold">${o.grand_total}</span></div>
                </div>
                <button
                  onClick={() => reorder(o)}
                  disabled={reorderingId === o.id}
                  className="w-full px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50"
                >
                  {reorderingId === o.id ? 'Adding…' : 'Reorder'}
                </button>
              </div>
            ))}
          </div>
          {/* Desktop: full 7-column table */}
          <div className="hidden md:block border rounded overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-100 text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th className="text-left px-3 py-2">Order #</th>
                  <th className="text-left px-3 py-2">Placed</th>
                  <th className="text-right px-3 py-2">Items</th>
                  <th className="text-right px-3 py-2">Files</th>
                  <th className="text-right px-3 py-2">Total</th>
                  <th className="text-left px-3 py-2">Status</th>
                  <th className="text-right px-3 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id} className="border-t hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono">
                      <Link to={`/orders/${o.web_order_number}`} className="text-red-700 hover:underline">{o.web_order_number}</Link>
                    </td>
                    <td className="px-3 py-2 text-gray-600">{new Date(o.placed_at).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">{o.item_count}</td>
                    <td className="px-3 py-2 text-right">{o.fulfillment_count}</td>
                    <td className="px-3 py-2 text-right font-semibold">${o.grand_total}</td>
                    <td className="px-3 py-2">{statusBadge(o.status)}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={() => reorder(o)}
                        disabled={reorderingId === o.id}
                        className="px-3 py-1 text-xs bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50"
                      >
                        {reorderingId === o.id ? 'Adding…' : 'Reorder'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

function fmtAddr(a: AddressOut): string {
  const parts: string[] = []
  if (a.name) parts.push(a.name)
  if (a.company) parts.push(a.company)
  if (a.addr1) parts.push(a.addr1)
  if (a.addr2) parts.push(a.addr2)
  const cityLine = [a.city, a.state, a.zip].filter(Boolean).join(', ')
  if (cityLine) parts.push(cityLine)
  return parts.join(' · ')
}

function OrderDetailPage() {
  const { webOrderNumber } = useParams<{ webOrderNumber: string }>()
  const [params] = useSearchParams()
  const placedNow = params.get('placed') === '1'
  const [order, setOrder] = useState<OrderOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!webOrderNumber) return
    fetch(`/api/orders/${webOrderNumber}`, { credentials: 'include' })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}))
          throw new Error(body.detail || `HTTP ${r.status}`)
        }
        return r.json()
      })
      .then(setOrder)
      .catch((e) => setError(e.message))
  }, [webOrderNumber])

  if (error) return <div className="p-6 text-red-700">Error: {error}</div>
  if (!order) return <div className="p-6 text-gray-500">Loading…</div>

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <Link to="/orders" className="text-sm text-red-700 hover:underline">← All orders</Link>
      {placedNow && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded text-green-900">
          ✓ Order placed. Confirmation: <strong>{order.web_order_number}</strong>. We've pushed the routing files to FACS for fulfillment.
        </div>
      )}
      <div className="mt-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <h1 className="text-2xl sm:text-3xl font-bold break-all">{order.web_order_number}</h1>
        <div className="flex items-center gap-3 flex-wrap">{statusBadge(order.status)}<span className="text-sm text-gray-500">placed {new Date(order.placed_at).toLocaleString()}</span></div>
      </div>

      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
        <div className="border rounded p-3">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Ship to</div>
          {fmtAddr(order.shipping)}
        </div>
        <div className="border rounded p-3">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Billing</div>
          {fmtAddr(order.billing)}
        </div>
        <div className="border rounded p-3">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Payment</div>
          {order.payment_type.replace('_', ' ')}{order.customer_po_number ? ` · PO ${order.customer_po_number}` : ''}
        </div>
        <div className="border rounded p-3">
          <div className="text-xs uppercase tracking-wide text-gray-500 mb-1">Contact</div>
          {order.contact_email}{order.contact_phone ? ` · ${order.contact_phone}` : ''}
        </div>
      </div>

      <h2 className="text-xl font-semibold mt-8 mb-3">Routing</h2>
      <div className="border rounded overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead className="bg-gray-100 text-xs uppercase tracking-wide text-gray-600">
            <tr>
              <th className="text-left px-3 py-2">Routing</th>
              <th className="text-left px-3 py-2">FACS file</th>
              <th className="text-left px-3 py-2">Push status</th>
              <th className="text-right px-3 py-2">Items</th>
              <th className="text-right px-3 py-2">Subtotal</th>
            </tr>
          </thead>
          <tbody>
            {order.fulfillments.map((f, i) => (
              <tr key={i} className="border-t">
                <td className="px-3 py-2 font-mono">{f.routing_type}</td>
                <td className="px-3 py-2 font-mono text-xs">{f.file_name}</td>
                <td className="px-3 py-2">{statusBadge(f.push_status)}</td>
                <td className="px-3 py-2 text-right">{f.line_count}</td>
                <td className="px-3 py-2 text-right">${f.item_subtotal}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="text-xl font-semibold mt-8 mb-3">Lines</h2>
      <div className="border rounded overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead className="bg-gray-100 text-xs uppercase tracking-wide text-gray-600">
            <tr>
              <th className="text-left px-3 py-2 w-10">#</th>
              <th className="text-left px-3 py-2">SKU</th>
              <th className="text-left px-3 py-2">Description</th>
              <th className="text-left px-3 py-2">Routing</th>
              <th className="text-right px-3 py-2">Ship</th>
              <th className="text-right px-3 py-2">B/O</th>
              <th className="text-right px-3 py-2">Unit</th>
              <th className="text-right px-3 py-2">Total</th>
            </tr>
          </thead>
          <tbody>
            {order.lines.map((l) => (
              <tr key={l.line_number} className="border-t">
                <td className="px-3 py-2">{l.line_number}</td>
                <td className="px-3 py-2 font-mono">{l.sku}</td>
                <td className="px-3 py-2">{l.description}</td>
                <td className="px-3 py-2 text-xs uppercase tracking-wide text-gray-500">{l.routing}</td>
                <td className="px-3 py-2 text-right">{l.quantity}</td>
                <td className="px-3 py-2 text-right">{l.backorder_quantity > 0 ? <span className="text-amber-700">{l.backorder_quantity}</span> : 0}</td>
                <td className="px-3 py-2 text-right">${l.unit_price}</td>
                <td className="px-3 py-2 text-right font-semibold">${l.line_total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 ml-auto max-w-sm bg-gray-50 rounded p-4 text-sm space-y-1">
        <div className="flex justify-between"><span>Items</span><span>${order.item_total}</span></div>
        <div className="flex justify-between text-gray-500"><span>Shipping</span><span>${order.shipping_total}</span></div>
        <div className="flex justify-between text-gray-500"><span>Handling</span><span>${order.handling_total}</span></div>
        <div className="flex justify-between text-gray-500"><span>Discount</span><span>${order.discount_total}</span></div>
        <div className="flex justify-between text-gray-500"><span>Tax</span><span>${order.tax_total}</span></div>
        <div className="flex justify-between text-base font-bold border-t pt-2 mt-2"><span>Total</span><span>${order.grand_total}</span></div>
      </div>
    </div>
  )
}

// ============================================================================
// Competitive landscape scoreboard — internal insights tool
// ============================================================================

interface InsightDimension { key: string; label: string; description: string }
interface InsightScore { value: number; note: string }
interface InsightCompetitor {
  id: string
  name: string
  url: string
  tier: string
  region: string
  summary: string
  last_audited: string
  scores: Record<string, InsightScore>
  average_score: number
}
interface InsightPayload {
  dimensions: InsightDimension[]
  competitors: InsightCompetitor[]
}

const TIER_LABELS: Record<string, string> = {
  us: 'Us (new build)',
  local: 'Local (Pacific NW)',
  national: 'National',
  snow_specialist: 'Snow Specialists',
  manufacturer: 'Manufacturer',
  reference: 'Reference / Mockup',
}

const TIER_COLORS: Record<string, string> = {
  us:               'bg-red-700 text-white',
  local:            'bg-orange-100 text-orange-800',
  national:         'bg-blue-100 text-blue-800',
  snow_specialist:  'bg-cyan-100 text-cyan-800',
  manufacturer:     'bg-purple-100 text-purple-800',
  reference:        'bg-gray-200 text-gray-800',
}

function scoreColor(value: number): string {
  if (value === 0)  return 'bg-gray-100 text-gray-400'
  if (value >= 9)   return 'bg-green-700 text-white'
  if (value >= 7)   return 'bg-green-100 text-green-800'
  if (value >= 5)   return 'bg-yellow-100 text-yellow-800'
  if (value >= 3)   return 'bg-orange-100 text-orange-800'
  return 'bg-red-100 text-red-800'
}

function CompetitiveLandscapePage() {
  const [data, setData] = useState<InsightPayload | null>(null)
  const [activeTier, setActiveTier] = useState<string>('all')
  const [selectedDimension, setSelectedDimension] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/insights/competitors').then((r) => r.json()).then(setData).catch(() => {})
  }, [])

  if (!data) {
    return <div className="p-12 text-center text-gray-500">Loading competitive landscape…</div>
  }

  const tiersInOrder = ['us', 'local', 'national', 'snow_specialist', 'manufacturer', 'reference']
  const tiers = Array.from(new Set(data.competitors.map((c) => c.tier))).sort(
    (a, b) => tiersInOrder.indexOf(a) - tiersInOrder.indexOf(b),
  )
  const filtered = activeTier === 'all'
    ? data.competitors
    : data.competitors.filter((c) => c.tier === activeTier)

  // Always include "us" first when filtering
  const us = data.competitors.find((c) => c.tier === 'us')
  const others = filtered.filter((c) => c.tier !== 'us')
  const ordered = us ? [us, ...others] : others

  // For the scoreboard, find the highest score per dimension across all
  // (filtered) competitors to mark "leader" badges.
  const dimensionLeaders: Record<string, string[]> = {}
  for (const dim of data.dimensions) {
    const max = Math.max(...ordered.map((c) => c.scores[dim.key]?.value || 0))
    if (max <= 0) continue
    dimensionLeaders[dim.key] = ordered
      .filter((c) => (c.scores[dim.key]?.value || 0) === max)
      .map((c) => c.id)
  }

  return (
    <div className="bg-gray-50 min-h-screen">
      {/* Header */}
      <div className="bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="text-xs uppercase tracking-widest text-blue-300 font-bold">Internal Insights</div>
          <h1 className="text-3xl font-extrabold mt-1">Competitive landscape</h1>
          <p className="text-sm text-gray-300 mt-1 max-w-3xl">
            Where Nelson leads, where we lag.  Curated 1–10 scores across {data.dimensions.length} dimensions
            for {data.competitors.length - 1} competitors plus our own new build.  Hand-curated for now;
            Phase 1.5 will run automated Lighthouse + crawl audits.
          </p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Tier filter chips */}
        <div className="mb-4 flex flex-wrap gap-2 items-center">
          <span className="text-xs uppercase tracking-wider text-gray-500 font-bold mr-2">Tier:</span>
          <button
            onClick={() => setActiveTier('all')}
            className={`px-3 py-1.5 text-xs font-semibold rounded transition ${activeTier === 'all' ? 'bg-blue-700 text-white' : 'bg-white border text-gray-700 hover:border-blue-700'}`}
          >
            All ({data.competitors.length})
          </button>
          {tiers.map((t) => (
            <button
              key={t}
              onClick={() => setActiveTier(t)}
              className={`px-3 py-1.5 text-xs font-semibold rounded transition ${activeTier === t ? 'bg-blue-700 text-white' : 'bg-white border text-gray-700 hover:border-blue-700'}`}
            >
              {TIER_LABELS[t] || t} ({data.competitors.filter((c) => c.tier === t).length})
            </button>
          ))}
        </div>

        {/* Score legend */}
        <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
          <span className="text-gray-500 mr-1">Score:</span>
          <span className="px-2 py-0.5 bg-red-100 text-red-800 rounded">1-2 broken</span>
          <span className="px-2 py-0.5 bg-orange-100 text-orange-800 rounded">3-4 thin</span>
          <span className="px-2 py-0.5 bg-yellow-100 text-yellow-800 rounded">5-6 functional</span>
          <span className="px-2 py-0.5 bg-green-100 text-green-800 rounded">7-8 strong</span>
          <span className="px-2 py-0.5 bg-green-700 text-white rounded">9-10 best-in-class</span>
        </div>

        {/* Matrix table */}
        <div className="bg-white border rounded-lg shadow-sm overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-100">
                <th className="text-left px-3 py-3 sticky left-0 bg-gray-100 w-56 z-10 border-r">Competitor</th>
                {data.dimensions.map((d) => (
                  <th
                    key={d.key}
                    onClick={() => setSelectedDimension(selectedDimension === d.key ? null : d.key)}
                    className={`text-center px-2 py-3 text-[10px] uppercase tracking-wider font-bold cursor-pointer hover:bg-gray-200 transition min-w-[64px] ${selectedDimension === d.key ? 'bg-blue-100' : ''}`}
                    title={d.description}
                  >
                    {d.label}
                  </th>
                ))}
                <th className="text-center px-3 py-3 text-[10px] uppercase tracking-wider font-bold border-l">Avg</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((c) => (
                <tr key={c.id} className={`border-t hover:bg-gray-50 ${c.tier === 'us' ? 'bg-red-50' : ''}`}>
                  <td className={`px-3 py-2 sticky left-0 z-10 border-r ${c.tier === 'us' ? 'bg-red-50' : 'bg-white hover:bg-gray-50'}`}>
                    <div className="flex items-center gap-2">
                      <span className={`px-1.5 py-0.5 text-[9px] uppercase tracking-wider rounded font-bold ${TIER_COLORS[c.tier] || ''}`}>
                        {TIER_LABELS[c.tier] || c.tier}
                      </span>
                    </div>
                    <div className="font-bold text-sm text-gray-900 mt-1">{c.name}</div>
                    <a href={c.url.startsWith('http') ? c.url : `#`} target="_blank" rel="noreferrer" className="text-[10px] text-blue-700 hover:underline truncate block max-w-[200px]">
                      {c.url}
                    </a>
                  </td>
                  {data.dimensions.map((d) => {
                    const s = c.scores[d.key]
                    const v = s?.value || 0
                    const isLeader = dimensionLeaders[d.key]?.includes(c.id) && v > 0
                    return (
                      <td key={d.key} className={`text-center px-2 py-2 ${selectedDimension === d.key ? 'bg-blue-50' : ''}`}>
                        <div
                          className={`inline-block w-9 h-7 rounded text-xs font-bold flex items-center justify-center mx-auto ${scoreColor(v)} ${isLeader ? 'ring-2 ring-yellow-400' : ''}`}
                          title={s?.note || ''}
                        >
                          {v > 0 ? v : '—'}
                        </div>
                      </td>
                    )
                  })}
                  <td className="text-center px-3 py-2 border-l font-bold text-gray-900">
                    {c.average_score.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Selected dimension detail */}
        {selectedDimension && (() => {
          const dim = data.dimensions.find((d) => d.key === selectedDimension)
          if (!dim) return null
          const sorted = [...ordered].sort((a, b) => (b.scores[dim.key]?.value || 0) - (a.scores[dim.key]?.value || 0))
          return (
            <section className="mt-6 bg-white border rounded-lg p-5">
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-bold">{dim.label}</h2>
                  <p className="text-sm text-gray-600 mt-1">{dim.description}</p>
                </div>
                <button onClick={() => setSelectedDimension(null)} className="text-xs text-red-700 hover:underline">Close</button>
              </div>
              <div className="mt-4 space-y-2">
                {sorted.map((c) => {
                  const s = c.scores[dim.key]
                  const v = s?.value || 0
                  return (
                    <div key={c.id} className="flex items-start gap-3 py-2 border-t">
                      <div className={`w-9 h-9 rounded text-sm font-bold flex items-center justify-center ${scoreColor(v)}`}>
                        {v > 0 ? v : '—'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`px-1.5 py-0.5 text-[9px] uppercase tracking-wider rounded font-bold ${TIER_COLORS[c.tier] || ''}`}>
                            {TIER_LABELS[c.tier] || c.tier}
                          </span>
                          <span className="font-semibold text-gray-900">{c.name}</span>
                        </div>
                        {s?.note && <div className="text-xs text-gray-600 mt-0.5">{s.note}</div>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>
          )
        })()}

        {/* Per-competitor notes (cards) */}
        <h2 className="text-xl font-bold mt-10 mb-4">Per-competitor positioning</h2>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {ordered.map((c) => (
            <div key={c.id} className="bg-white border rounded-lg p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <span className={`px-1.5 py-0.5 text-[9px] uppercase tracking-wider rounded font-bold ${TIER_COLORS[c.tier] || ''}`}>
                    {TIER_LABELS[c.tier] || c.tier}
                  </span>
                  <h3 className="font-bold text-gray-900 mt-1">{c.name}</h3>
                  <a href={c.url.startsWith('http') ? c.url : '#'} target="_blank" rel="noreferrer" className="text-xs text-blue-700 hover:underline truncate block">{c.url}</a>
                </div>
                <div className={`w-12 h-12 rounded text-base font-bold flex items-center justify-center ${scoreColor(Math.round(c.average_score))}`}>
                  {c.average_score.toFixed(1)}
                </div>
              </div>
              <p className="text-xs text-gray-600 mt-2 leading-relaxed">{c.summary}</p>
              <div className="text-[10px] text-gray-400 mt-2">Last audited: {c.last_audited}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Snow plow model catalog + comparison builder
// ============================================================================

interface PlowModel {
  id: string
  brand: string
  model: string
  family: string
  family_label: string
  blade_widths_in: string[]
  blade_height_in: number
  weight_lb: number
  cutting_edge: string
  moldboard: string
  mount: string
  hydraulics: string
  control: string[]
  truck_classes: string[]
  msrp_low: number
  msrp_high: number
  best_for: string
  highlights: string[]
  image_url: string | null              // legacy override
  notes: string | null
  snow_belt_rank: number
  // ---- Imagery (added Apr 27 2026) ----
  // moldboard_skus = list of Nelson stockids that compose this plow model.
  // hero_image_url = resolved URL of the first SKU's image (default card hero).
  // moldboard_image_urls = full SKU → URL map for the kit-builder / comparison.
  moldboard_skus?: string[]
  hero_image_url?: string | null
  moldboard_image_urls?: Record<string, string | null>
  // Manufacturer content scraped from westernplows.com / meyerproducts.com /
  // buyersproducts.com.  Auto-populated by build_manufacturer_content.py.
  manufacturer?: {
    manufacturer?: string
    product_name?: string
    tagline?: string
    source_url?: string
    pdf_spec_sheet?: string | null
    videos?: string[]
    description?: string
    key_features?: string[]
    manufacturer_specs?: Record<string, string>
    spec_variants?: Array<{
      model_number?: string | null
      fields?: Record<string, string>
    }>
    vehicle_class?: string
  }
}

interface PlowComparePayload {
  models: PlowModel[]
  all_match: Record<string, boolean>
}

const HYDRAULIC_LABEL: Record<string, string> = {
  truck_mounted_hydraulic: 'Truck-mounted hydraulic',
  self_contained_electric: 'Electric (self-contained)',
}
const CONTROL_LABEL: Record<string, string> = {
  handheld: 'Handheld',
  joystick: 'Joystick',
  cab_command: 'Cab Command',
  in_cab_touch: 'In-cab touch',
}

function formatPlowControl(controls: string[]): string {
  return controls.map((c) => CONTROL_LABEL[c] || c).join(' · ')
}

function PlowComparePage() {
  const [params, setParams] = useSearchParams()
  const [models, setModels] = useState<PlowModel[]>([])
  // Family filter is URL-driven: brand pages + "Shop by plow type" tiles
  // navigate here with `?family=v_plow` etc.  Falls back to "all" if absent.
  const [familyFilter, setFamilyFilter] = useState<string>(params.get('family') || '')
  const [brandFilter, setBrandFilter] = useState<string>(params.get('brand') || '')
  const [comparison, setComparison] = useState<PlowComparePayload | null>(null)
  const [pickLimitWarning, setPickLimitWarning] = useState(false)
  // Re-sync when URL params change (e.g. user clicks a brand card while
  // already on the compare page)
  useEffect(() => {
    setFamilyFilter(params.get('family') || '')
    setBrandFilter(params.get('brand') || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.get('family'), params.get('brand')])

  const ids = params.get('ids') || ''
  const selectedIds = ids.split(',').filter(Boolean)
  // ?truck=X carries the buyer's truck class through from the wizard so we can
  // label which picker cards directly fit and which would be a stretch.
  const truckClass = params.get('truck') || ''
  const truckLabel = TRUCK_CLASSES.find(t => t.id === truckClass)?.label || ''

  // Load model catalog once
  useEffect(() => {
    fetch('/api/catalog/snow-plow-models').then((r) => r.json()).then(setModels).catch(() => {})
  }, [])

  // Load comparison whenever selection changes
  useEffect(() => {
    if (selectedIds.length < 2) { setComparison(null); return }
    fetch(`/api/catalog/snow-plow-models/compare?ids=${selectedIds.join(',')}`)
      .then((r) => r.json()).then(setComparison).catch(() => setComparison(null))
  }, [ids])

  function toggleSelect(id: string) {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else if (next.size >= 4) {
      // Inline banner instead of blocking native alert.  Banner is rendered
      // alongside the picker so the user sees the limit AND can scan their
      // current selection without dismissing a modal.
      setPickLimitWarning(true)
      setTimeout(() => setPickLimitWarning(false), 4000)
      return
    } else {
      next.add(id)
    }
    const p = new URLSearchParams(params)
    if (next.size === 0) p.delete('ids')
    else p.set('ids', Array.from(next).join(','))
    setParams(p)
  }
  function clearSelection() {
    const p = new URLSearchParams(params)
    p.delete('ids')
    setParams(p)
  }

  const filteredModels = models.filter((m) => {
    if (familyFilter && m.family !== familyFilter) return false
    if (brandFilter && m.brand.toLowerCase() !== brandFilter.toLowerCase()) return false
    return true
  })

  function setFamily(family: string) {
    setFamilyFilter(family)
    const p = new URLSearchParams(params)
    if (family) p.set('family', family); else p.delete('family')
    setParams(p)
  }
  function clearBrand() {
    setBrandFilter('')
    const p = new URLSearchParams(params)
    p.delete('brand')
    setParams(p)
  }

  return (
    <div className="bg-gray-50 min-h-screen">
      {/* Header strip */}
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <Link to="/snow-plows" className="text-xs text-blue-300 hover:text-white">← Back to Snow Plows</Link>
          <h1 className="text-3xl font-extrabold mt-2">Snow Plow Comparison Builder</h1>
          <p className="text-sm text-blue-200 mt-1">Pick up to 4 plows from any brand. We&rsquo;ll line up the specs side by side and highlight the differences so you can decide fast.</p>
          {truckClass && truckLabel && (
            <div className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 bg-white/10 border border-white/20 rounded text-xs">
              <span className="text-blue-300 uppercase tracking-wider font-bold">Filtering for:</span>
              <span className="text-white font-semibold">{truckLabel}</span>
              <button
                onClick={() => { const p = new URLSearchParams(params); p.delete('truck'); setParams(p) }}
                className="text-blue-300 hover:text-white ml-1"
                title="Clear truck context"
              >
                ✕
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Family filter chips */}
        <div className="mb-4 flex flex-wrap gap-2 items-center">
          <span className="text-xs uppercase tracking-wider text-gray-500 font-bold mr-2">Filter:</span>
          {[
            { id: '',                label: 'All families' },
            { id: 'straight_blade',  label: 'Straight Blade' },
            { id: 'v_plow',          label: 'V-Plow' },
            { id: 'winged',          label: 'Winged' },
          ].map((f) => (
            <button
              key={f.id}
              onClick={() => setFamily(f.id)}
              className={`px-3 py-1.5 text-xs font-semibold rounded transition ${
                familyFilter === f.id ? 'bg-blue-700 text-white' : 'bg-white border text-gray-700 hover:border-blue-700'
              }`}
            >
              {f.label}
            </button>
          ))}
          {brandFilter && (
            <span className="ml-2 inline-flex items-center gap-1 px-2 py-1 bg-red-50 border border-red-200 rounded text-xs">
              <span className="text-gray-500">brand:</span>
              <span className="font-bold text-red-800">{brandFilter}</span>
              <button onClick={clearBrand} className="ml-1 text-red-600 hover:text-red-800" title="Clear brand filter">✕</button>
            </span>
          )}
          <span className="ml-auto text-xs text-gray-500">{filteredModels.length} models · {selectedIds.length} selected</span>
        </div>

        {pickLimitWarning && (
          <div className="mb-3 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-900 flex items-center gap-2">
            <span>⚠ Maximum 4 plows at a time — remove one to add another.</span>
          </div>
        )}

        {/* Picker grid */}
        <section className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-8">
          {filteredModels.map((m) => {
            const checked = selectedIds.includes(m.id)
            // Fit indicator: only meaningful when ?truck= is set
            const directFit = truckClass ? m.truck_classes.includes(truckClass) : null
            const cardClass = checked
              ? 'border-red-700 ring-2 ring-red-200'
              : directFit === false
                ? 'border-amber-300 bg-amber-50/40 hover:border-amber-500'
                : 'border-gray-200 hover:border-blue-700'
            return (
              <button
                key={m.id}
                onClick={() => toggleSelect(m.id)}
                className={`text-left bg-white border-2 rounded p-3 transition ${cardClass}`}
              >
                <div className="flex items-start justify-between">
                  <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">{m.brand}</div>
                  <div className={`w-4 h-4 rounded border flex items-center justify-center text-xs ${
                    checked ? 'bg-red-700 border-red-700 text-white' : 'border-gray-400'
                  }`}>{checked ? '✓' : ''}</div>
                </div>
                {/* Moldboard hero — same image source as the wizard cards */}
                {m.hero_image_url && (
                  <div className="my-2 h-20 bg-gray-50 rounded flex items-center justify-center overflow-hidden">
                    <img
                      src={m.hero_image_url}
                      alt={`${m.brand} ${m.model}`}
                      loading="lazy"
                      className="max-w-full max-h-full object-contain"
                    />
                  </div>
                )}
                <div className="text-sm font-bold text-gray-900 mt-0.5">{m.model}</div>
                <div className="text-[10px] text-blue-700 font-semibold mt-0.5">{m.family_label}</div>
                {/* Fit indicator — only render when the user came from the wizard with ?truck=X */}
                {directFit === true && (
                  <div className="mt-1 inline-block px-1.5 py-0.5 bg-green-100 text-green-800 text-[9px] uppercase tracking-wider rounded font-bold">
                    ✓ Fits {truckClass}
                  </div>
                )}
                {directFit === false && (
                  <div className="mt-1 inline-block px-1.5 py-0.5 bg-amber-100 text-amber-800 text-[9px] uppercase tracking-wider rounded font-bold">
                    ⚠ Needs heavier truck
                  </div>
                )}
                <div className="text-[10px] text-gray-500 mt-2">${m.msrp_low.toLocaleString()}–${m.msrp_high.toLocaleString()}</div>
                <div className="text-[10px] text-gray-500">{m.weight_lb} lb · fits {m.truck_classes.join('/')}</div>
              </button>
            )
          })}
        </section>

        {/* Comparison table */}
        {selectedIds.length === 0 && (
          <div className="bg-white border-2 border-dashed border-gray-200 rounded-lg p-10 text-center">
            <div className="text-4xl mb-2">⛏️</div>
            <div className="text-base font-semibold text-gray-800 mb-1">Pick at least 2 plows to compare</div>
            <p className="text-sm text-gray-500">Click any of the cards above. Selected plows show the red checkmark.</p>
          </div>
        )}

        {selectedIds.length === 1 && (
          <div className="bg-yellow-50 border border-yellow-200 rounded p-4 text-sm text-yellow-900">
            Pick at least one more plow to see them side by side.
          </div>
        )}

        {comparison && comparison.models.length >= 2 && (
          <PlowComparisonTable comparison={comparison} onRemove={toggleSelect} onClear={clearSelection} />
        )}
      </div>
    </div>
  )
}

function PlowComparisonTable({
  comparison, onRemove, onClear,
}: {
  comparison: PlowComparePayload
  onRemove: (id: string) => void
  onClear: () => void
}) {
  const { models, all_match } = comparison

  // Highlight class for cells in a row where all_match[key] is false
  function rowHighlight(key: string) {
    return all_match[key] === false ? 'bg-yellow-50' : ''
  }

  // Specific column-level helpers — best/lowest highlight per row
  function lowestIndex(values: number[]): number {
    let bestIdx = 0
    for (let i = 1; i < values.length; i++) if (values[i] < values[bestIdx]) bestIdx = i
    return bestIdx
  }

  const lowestWeightIdx = lowestIndex(models.map((m) => m.weight_lb))
  const lowestPriceIdx  = lowestIndex(models.map((m) => m.msrp_low))

  return (
    <div className="bg-white border rounded-lg shadow-sm overflow-hidden">
      <div className="flex items-center justify-between p-3 bg-gray-50 border-b">
        <div className="text-sm text-gray-700">
          Comparing <strong>{models.length}</strong> plow{models.length === 1 ? '' : 's'}.
          {' '}
          <span className="text-xs text-gray-500">Yellow rows show where the plows differ.</span>
        </div>
        <button onClick={onClear} className="text-xs text-red-700 hover:underline font-semibold">
          Clear selection
        </button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-blue-950 text-white">
              <th className="text-left px-3 py-3 sticky left-0 bg-blue-950 w-44 z-10">Spec</th>
              {models.map((m) => (
                <th key={m.id} className="text-left px-3 py-3 align-top min-w-[200px]">
                  <div className="text-[10px] uppercase tracking-wider text-blue-200 font-semibold">{m.brand}</div>
                  <div className="text-base font-bold">{m.model}</div>
                  <div className="text-[10px] text-blue-200 font-semibold mt-0.5">{m.family_label}</div>
                  <button onClick={() => onRemove(m.id)} className="mt-2 text-[10px] text-blue-300 hover:text-white underline">Remove</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-gray-800">
            {/* Hero image row — moldboard product photo from Nelson WSM. */}
            {models.some((m) => m.hero_image_url) && (
              <tr className="border-b">
                <td className="px-3 py-3 sticky left-0 bg-white text-xs uppercase tracking-wider text-gray-500 font-bold align-middle z-10">
                  Image
                </td>
                {models.map((m) => (
                  <td key={m.id} className="px-3 py-3 align-middle">
                    {m.hero_image_url ? (
                      <div className="h-32 bg-gray-50 rounded flex items-center justify-center overflow-hidden">
                        <img
                          src={m.hero_image_url}
                          alt={`${m.brand} ${m.model}`}
                          loading="lazy"
                          className="max-w-full max-h-full object-contain"
                        />
                      </div>
                    ) : (
                      <div className="h-32 bg-gray-100 rounded flex items-center justify-center text-xs text-gray-400">
                        No image yet
                      </div>
                    )}
                  </td>
                ))}
              </tr>
            )}
            <Row label="Best for" highlight={rowHighlight('best_for')} models={models}>
              {(m) => <span className="text-xs">{m.best_for}</span>}
            </Row>
            <Row label="Blade widths" highlight={rowHighlight('blade_widths_in')} models={models}>
              {(m) => <span>{m.blade_widths_in.join(' / ')}</span>}
            </Row>
            <Row label="Blade height" highlight={rowHighlight('blade_height_in')} models={models}>
              {(m) => <span>{m.blade_height_in}&Prime;</span>}
            </Row>
            <Row label="Weight" highlight={rowHighlight('weight_lb')} models={models} highlightIdx={lowestWeightIdx} highlightTag="lightest">
              {(m) => <span>{m.weight_lb} lb</span>}
            </Row>
            <Row label="Cutting edge" highlight={rowHighlight('cutting_edge')} models={models}>
              {(m) => <span className="text-xs">{m.cutting_edge}</span>}
            </Row>
            <Row label="Moldboard" highlight={rowHighlight('moldboard')} models={models}>
              {(m) => <span className="text-xs">{m.moldboard}</span>}
            </Row>
            <Row label="Mount" highlight={rowHighlight('mount')} models={models}>
              {(m) => <span className="text-xs">{m.mount}</span>}
            </Row>
            <Row label="Hydraulics" highlight={rowHighlight('hydraulics')} models={models}>
              {(m) => <span className="text-xs">{HYDRAULIC_LABEL[m.hydraulics] || m.hydraulics}</span>}
            </Row>
            <Row label="Controls" highlight={rowHighlight('control')} models={models}>
              {(m) => <span className="text-xs">{formatPlowControl(m.control)}</span>}
            </Row>
            <Row label="Fits truck" highlight={rowHighlight('truck_classes')} models={models}>
              {(m) => <span className="text-xs">{m.truck_classes.join(' / ')}</span>}
            </Row>
            <Row label="MSRP" models={models} highlightIdx={lowestPriceIdx} highlightTag="lowest">
              {(m) => <span className="font-semibold">${m.msrp_low.toLocaleString()}–${m.msrp_high.toLocaleString()}</span>}
            </Row>
            <Row label="Highlights" models={models}>
              {(m) => (
                <ul className="text-[11px] list-disc list-inside space-y-0.5">
                  {m.highlights.map((h, i) => <li key={i}>{h}</li>)}
                </ul>
              )}
            </Row>
            {/* Manufacturer description (Meyer plows have the richest copy) */}
            {models.some((m) => m.manufacturer?.description) && (
              <Row label="Manufacturer overview" models={models}>
                {(m) => m.manufacturer?.description ? (
                  <div className="text-[11px] leading-snug text-gray-700">
                    {m.manufacturer.description.length > 320
                      ? m.manufacturer.description.slice(0, 320) + "…"
                      : m.manufacturer.description}
                  </div>
                ) : <span className="text-[10px] text-gray-400 italic">—</span>}
              </Row>
            )}
            {models.some((m) => (m.manufacturer?.spec_variants?.length ?? 0) > 0) && (
              <Row label="Per-blade specs" models={models}>
                {(m) => {
                  const v = m.manufacturer?.spec_variants ?? []
                  if (!v.length) return <span className="text-[10px] text-gray-400 italic">—</span>
                  return (
                    <details className="text-[11px]">
                      <summary className="cursor-pointer text-blue-700 hover:underline">{v.length} blade variants</summary>
                      <div className="mt-1 space-y-1 max-h-40 overflow-y-auto">
                        {v.map((variant, idx) => (
                          <div key={idx} className="text-[10px] bg-gray-50 border border-gray-200 rounded p-1.5">
                            <div className="font-mono text-gray-600">#{variant.model_number}</div>
                            {variant.fields && Object.entries(variant.fields).slice(0, 4).map(([k, val]) => (
                              <div key={k} className="text-gray-700"><span className="text-gray-500">{k}:</span> {val}</div>
                            ))}
                          </div>
                        ))}
                      </div>
                    </details>
                  )
                }}
              </Row>
            )}
            {models.some((m) => m.manufacturer?.pdf_spec_sheet || m.manufacturer?.source_url) && (
              <Row label="Manufacturer links" models={models}>
                {(m) => (
                  <div className="space-y-1">
                    {m.manufacturer?.source_url && (
                      <a href={m.manufacturer.source_url} target="_blank" rel="noopener noreferrer"
                         className="text-[11px] text-blue-700 hover:underline block">
                        🔗 {m.manufacturer.manufacturer} product page
                      </a>
                    )}
                    {m.manufacturer?.pdf_spec_sheet && (
                      <a href={m.manufacturer.pdf_spec_sheet} target="_blank" rel="noopener noreferrer"
                         className="text-[11px] text-blue-700 hover:underline block">
                        📄 Spec sheet (PDF)
                      </a>
                    )}
                    {(!m.manufacturer?.source_url && !m.manufacturer?.pdf_spec_sheet) && (
                      <span className="text-[10px] text-gray-400 italic">—</span>
                    )}
                  </div>
                )}
              </Row>
            )}
            <tr>
              <td className="px-3 py-3 sticky left-0 bg-white border-t font-semibold text-xs text-gray-500 uppercase tracking-wider">Get a quote</td>
              {models.map((m) => (
                <td key={m.id} className="px-3 py-3 border-t">
                  <a
                    href={`mailto:sales@nelsontruck.com?subject=${encodeURIComponent(`Quote: ${m.brand} ${m.model}`)}&body=${encodeURIComponent(`Hi Nelson team — I'd like a quote on the ${m.brand} ${m.model} (${m.family_label}). My truck is …`)}`}
                    className="block w-full px-3 py-2 bg-red-700 hover:bg-red-800 text-white text-xs font-bold text-center rounded"
                  >
                    Quote {m.brand} {m.model} →
                  </a>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({
  label, models, highlight, children, highlightIdx, highlightTag,
}: {
  label: string
  models: PlowModel[]
  highlight?: string
  children: (m: PlowModel) => React.ReactNode
  highlightIdx?: number
  highlightTag?: string
}) {
  return (
    <tr className={`border-t ${highlight || ''}`}>
      <td className="px-3 py-2 sticky left-0 bg-white font-semibold text-xs text-gray-500 uppercase tracking-wider">{label}</td>
      {models.map((m, i) => (
        <td key={m.id} className="px-3 py-2 align-top">
          <div className="flex items-start gap-2">
            <div className="flex-1">{children(m)}</div>
            {highlightIdx === i && highlightTag && (
              <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-[9px] uppercase tracking-wider font-bold rounded whitespace-nowrap">{highlightTag}</span>
            )}
          </div>
        </td>
      ))}
    </tr>
  )
}

// ============================================================================
// Snow plow financing modal — links to each manufacturer's financing page
// ============================================================================
//
// Why a modal, not a dedicated page: based on Nelson's actual numbers
// (~5/65 plows financed via Sheffield), financing is a low-attach feature.
// We surface it but don't waste hero real estate on it.
//
// Sheffield Financial is the unifying partner across BOSS / Western / Fisher /
// SnowEx / Buyers — but each manufacturer's branded portal handles the
// application differently, so we link buyers directly to the right one.

interface FinancingPartner {
  brand: string                 // Display name
  url: string                   // Direct link to that brand's financing page
  partner: string               // "Sheffield Financial" / "Affirm" / etc.
  notes?: string                // One-line context
  audience: 'commercial' | 'residential' | 'both'
}

// Nelson sells almost exclusively contractor-grade plows.  Residential
// light-duty units are intentionally NOT pushed (we consider them under-built).
// Financing therefore = commercial financing, period.  Sheffield Financial is
// the unifying partner across every contractor-grade brand we carry.
// Brands Nelson actually carries.  Boss + SnowEx are NOT sold by Nelson and
// have been removed.  Fisher is included pending user confirmation.
const FINANCING_PARTNERS: FinancingPartner[] = [
  {
    brand: 'Western Snow Plows',
    url: 'https://westernplows.com/financing/',
    partner: 'Sheffield Financial',
    notes: 'Pro-Plus, MVP3, Wideout, HTS — Nelson\'s #1 brand, $1.5M last year',
    audience: 'commercial',
  },
  {
    brand: 'Buyers SnowDogg',
    url: 'https://www.buyersproducts.com/financing',
    partner: 'Sheffield Financial',
    notes: 'VX / VXF / EX / HD / XP series + SaltDogg spreaders',
    audience: 'commercial',
  },
  {
    brand: 'Meyer Products',
    url: 'https://meyerproducts.com',
    partner: 'Sheffield Financial',
    notes: 'Super V2, Lot Pro, XLS — Nelson stocks the commercial line',
    audience: 'commercial',
  },
]

function FinancingModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-12 overflow-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl">
        <div className="p-5 border-b flex items-start justify-between">
          <div>
            <h2 className="text-lg font-bold text-gray-900">Snow plow financing</h2>
            <p className="text-xs text-gray-500 mt-1">
              Most Nelson plow buyers pay outright or run on net-30 PO terms.  When
              financing makes sense, every contractor-grade brand we sell uses
              <strong> Sheffield Financial</strong> (a Truist Bank division specializing in
              outdoor power &amp; commercial equipment).  Apply directly with the
              brand you're buying:
            </p>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none flex-shrink-0">×</button>
        </div>
        <div className="p-5 space-y-2">
          {FINANCING_PARTNERS.map((p) => (
            <a
              key={p.brand}
              href={p.url}
              target="_blank" rel="noreferrer"
              className="block border rounded p-3 hover:border-red-700 hover:shadow-sm transition group"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-bold text-sm text-gray-900 group-hover:text-red-700">{p.brand}</span>
                    <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[9px] uppercase tracking-wider rounded font-bold">{p.partner}</span>
                  </div>
                  {p.notes && <div className="text-xs text-gray-500 mt-1">{p.notes}</div>}
                </div>
                <span className="text-xs text-red-700 group-hover:underline whitespace-nowrap flex-shrink-0">Apply →</span>
              </div>
            </a>
          ))}
          <div className="mt-4 p-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700">
            <strong>Already a Nelson account?</strong>  Skip the application — call sales
            at <a href="tel:8003461704" className="text-red-700 hover:underline">503-548-9300</a> and we'll put the plow
            on your existing PO / net-30 terms.  That's how 90%+ of our contractor
            customers actually buy.
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Snow Plows landing page — strategic vertical, modeled on Boss + titantruck
// ============================================================================

interface SnowLandingBrand {
  name: string
  slug: string | null
  total_products: number
  in_stock_skus: number
  rank: string
  tagline: string
  lineup?: string
  image: string | null
  color: string
}

interface SnowTopSeller {
  sku: string
  brand: string
  description: string
  units_last_12mo: number
  revenue_last_12mo: number
  category: string
  category_label: string
  note: string
  has_local_pdp: boolean
  image_url: string | null
}

interface SnowLandingPayload {
  brands: SnowLandingBrand[]
  plow_categories: { name: string; slug: string; full_path: string; product_count: number }[]
  featured_in_stock: SnowTopSeller[]
  total_in_stock_skus: number
}

// =========================================================================
// Plow Configurator — visualises the plow on the front of the user's truck.
//
// User insight Apr 27 2026: "the pictures will line up with moldboard part
// numbers — we will use these later to form kit part numbers or a different
// part of the website that can piece the whole complete snowplow together"
// + "as the user configures their plow the plow on the front of the truck
// they picked as there truck gets update with a different plow."
//
// v1 ships with hand-drawn SVG truck silhouettes (pickup + chassis cab) and
// the transparent-background plow PNGs extracted in extract_transparent_plows.
// Future phases:
//   - Replace SVGs with AI-rendered (Wan 2.2) or licensed photo trucks
//   - rembg-style ML segmentation for the 8 lifestyle-shot plows that white-mask
//     extraction couldn't clean
//   - Surface kit composition (mount + light adapter + harness) once those
//     SKU relationships are mapped
// =========================================================================

// Per-truck-class anchor data.  Bumper coords are in IMAGE pixel coords
// (intrinsic image dimensions, not screen pixels), and the wizard converts
// to CSS percentages at render time.  This way we can mix images of
// different intrinsic sizes (the SVG silhouettes are 800x500, the new Wan
// 2.2 renders are 1024x576).
interface TruckProfile {
  id: string
  label: string
  short: string             // "F-150" — used in compact UI
  image: string             // path under /static/
  imageWidth: number        // intrinsic image width — divisor for anchor coords
  imageHeight: number       // intrinsic image height
  bumperCx: number          // bumper center x in image-pixel coords
  bumperCy: number          // bumper center y in image-pixel coords
  bumperWidth: number       // visible bumper width in image-pixel coords
  realBumperInches: number  // approximate real-world track width — controls plow scale
}

// Snow E-2.5 Apr 27 2026: replaced Wan 2.2 5B Turbo renders with FLUX-Schnell
// HEAD-ON renders.  All 6 trucks now face camera dead-on with bumper centered
// horizontally — much cleaner anchoring (cx always = imageWidth / 2) and
// dramatically better photoreal quality than Wan Turbo's distilled 4-step.
//
// Generation specs (app/scripts/render_truck_lineup_flux.py):
//   - FLUX-Schnell fp8, 1024x576, 4 steps, cfg=1, simple scheduler, euler
//   - shared studio-backdrop prompt scaffolding for visual consistency
//   - ~6-21s per render after warmup, 51s total for the lineup
//
// Bumper anchors are now SYMMETRIC: cx=512 (image centerline), cy varies by
// truck class height, bumperWidth fills most of the visible bumper bar.
const TRUCK_PROFILES: Record<string, TruckProfile> = {
  "mid-size": { id: "mid-size", label: "Mid-size pickup",          short: "Tacoma / Colorado / Ranger / Maverick",
                image: "/static/trucks/renders/mid-size.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 395, bumperWidth: 610, realBumperInches: 70 },
  "1500":     { id: "1500",     label: "Half-ton (1500 / F-150)",  short: "F-150 / Silverado 1500 / Ram 1500",
                image: "/static/trucks/renders/1500.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 440, bumperWidth: 580, realBumperInches: 80 },
  "2500":     { id: "2500",     label: "3/4-ton (2500 / F-250)",   short: "F-250 / Silverado 2500 / Ram 2500",
                image: "/static/trucks/renders/2500.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 420, bumperWidth: 620, realBumperInches: 84 },
  "3500":     { id: "3500",     label: "1-ton (3500 / F-350)",     short: "F-350 / Silverado 3500 / Ram 3500",
                image: "/static/trucks/renders/3500.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 425, bumperWidth: 600, realBumperInches: 88 },
  "4500":     { id: "4500",     label: "Class 4 chassis cab",      short: "F-450 / Silverado 4500 / Ram 4500",
                image: "/static/trucks/renders/4500.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 410, bumperWidth: 660, realBumperInches: 96 },
  "5500":     { id: "5500",     label: "Class 5 chassis cab",      short: "F-550 / Silverado 5500 / Ram 5500",
                image: "/static/trucks/renders/5500.png",
                imageWidth: 1024, imageHeight: 576,
                bumperCx: 512, bumperCy: 410, bumperWidth: 540, realBumperInches: 100 },
}

function PlowConfigurator() {
  const [params, setParams] = useSearchParams()
  const [models, setModels] = useState<PlowModel[]>([])
  const [loading, setLoading] = useState(true)

  const truckClass = params.get("truck") || "1500"
  const plowId = params.get("plow") || ""
  const moldboardSku = params.get("moldboard") || ""

  const truck = TRUCK_PROFILES[truckClass] || TRUCK_PROFILES["1500"]

  useEffect(() => {
    fetch("/api/catalog/snow-plow-models")
      .then((r) => r.json())
      .then((d) => { setModels(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  // Derived: the currently-selected plow + moldboard SKU + image URL
  const plow: PlowModel | undefined = useMemo(
    () => models.find((m) => m.id === plowId) || (plowId === "" && models[0]) || undefined,
    [models, plowId],
  )

  // The currently rendered moldboard SKU image — falls back to plow's first SKU
  const activeSku = useMemo(() => {
    if (!plow) return ""
    if (moldboardSku && plow.moldboard_skus?.includes(moldboardSku)) return moldboardSku
    return plow.moldboard_skus?.[0] || ""
  }, [plow, moldboardSku])

  // Use transparent PNG when extraction succeeded; fall back to the JPG hero.
  // The extract script wrote hero_transparent.png alongside hero.jpg for studio
  // shots (~61 of 69 SKUs).  We always link to the transparent file path; if
  // it 404s the browser shows broken-image, which isn't ideal — so we probe
  // existence client-side and gracefully fall back.
  const transparentUrl = activeSku
    ? `/static/snow-plows/skus/${activeSku.replace(/:/g, "-")}/hero_transparent.png`
    : null
  const fallbackUrl = plow?.moldboard_image_urls?.[activeSku] || plow?.hero_image_url || null
  const [plowImageUrl, setPlowImageUrl] = useState<string | null>(null)
  useEffect(() => {
    if (!transparentUrl) { setPlowImageUrl(fallbackUrl); return }
    // Probe the transparent PNG; if missing, use the JPG.
    const img = new Image()
    img.onload = () => setPlowImageUrl(transparentUrl)
    img.onerror = () => setPlowImageUrl(fallbackUrl)
    img.src = transparentUrl
  }, [transparentUrl, fallbackUrl])

  function setParam(key: string, value: string) {
    const p = new URLSearchParams(params)
    if (value) p.set(key, value)
    else p.delete(key)
    // When the plow changes, reset moldboard so we don't carry a stale SKU
    if (key === "plow") p.delete("moldboard")
    setParams(p)
  }

  // Plow scale: bumperWidth (in viewBox units) maps to ~realBumperInches.  A
  // typical commercial plow is 96-114 inches wide (8'-9'6"), so it should be
  // wider than the truck bumper.  Pull the active blade width from the SKU
  // metadata if we can, otherwise default to 1.12x bumper width.
  const plowScalePct = 1.18  // plow image is ~118% of bumper width

  return (
    <div className="bg-gray-50 min-h-screen">
      {/* Header */}
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <Link to="/snow-plows" className="text-xs text-blue-300 hover:text-white">← Back to Snow Plows</Link>
          <h1 className="text-3xl font-extrabold mt-2">Plow Configurator</h1>
          <p className="text-sm text-blue-200 mt-1">
            See how the plow looks on the front of your truck.  Switch trucks or plows on the right —
            the preview updates live.
          </p>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8 grid lg:grid-cols-[1fr_360px] gap-6">
        {/* LEFT: live preview + parts breakdown */}
        <div className="space-y-5">
          {/* Composite preview */}
          <div className="bg-white rounded-lg shadow-sm border overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50 flex items-center justify-between">
              <div>
                <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">Preview</div>
                <div className="text-sm font-bold text-gray-900">
                  {truck.label}
                  {plow && <span className="text-gray-500 font-normal"> · {plow.brand} {plow.model}</span>}
                </div>
              </div>
              {plow && plow.hero_image_url && (
                <span className="text-[10px] text-gray-500 italic">Wan 2.2 5B Turbo render · backdrop tweak coming</span>
              )}
            </div>
            <div className="relative bg-gradient-to-b from-blue-50 via-white to-gray-100 overflow-hidden" style={{ aspectRatio: `${truck.imageWidth} / ${truck.imageHeight}` }}>
              {/* Truck — fills the canvas at the image's intrinsic aspect ratio */}
              <img
                src={truck.image}
                alt={truck.label}
                className="absolute inset-0 w-full h-full object-contain"
                style={{ filter: "drop-shadow(0 6px 8px rgba(0,0,0,0.15))" }}
              />
              {/* Plow overlay — positioned at bumper anchor in image-pixel coords,
                  converted to % so it scales with the displayed canvas */}
              {plowImageUrl && (
                <img
                  key={plowImageUrl}
                  src={plowImageUrl}
                  alt={plow ? `${plow.brand} ${plow.model}` : "plow"}
                  className="absolute"
                  style={{
                    left:      `${(truck.bumperCx / truck.imageWidth) * 100}%`,
                    top:       `${(truck.bumperCy / truck.imageHeight) * 100}%`,
                    width:     `${((truck.bumperWidth * plowScalePct) / truck.imageWidth) * 100}%`,
                    transform: "translate(-50%, -32%)",
                    filter:    "drop-shadow(0 4px 6px rgba(0,0,0,0.25))",
                    transition: "all 0.35s ease-out",
                  }}
                />
              )}
              {!plow && !loading && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="bg-white/90 backdrop-blur px-6 py-4 rounded shadow border text-center">
                    <div className="text-sm text-gray-700">Pick a plow from the right panel →</div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Parts breakdown — placeholder for the eventual kit-builder */}
          {plow && activeSku && (
            <div className="bg-white rounded-lg border shadow-sm">
              <div className="px-4 py-3 border-b bg-gray-50">
                <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">Build sheet</div>
                <div className="text-sm text-gray-700">A complete plow is moldboard + mount + light adapter + harness + control.  Today we have the moldboard.  The rest will join here as we wire the kit-builder.</div>
              </div>
              <div className="divide-y">
                <div className="px-4 py-3 flex items-center justify-between">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Moldboard</div>
                    <div className="text-sm font-bold text-gray-900">{activeSku}</div>
                    <div className="text-xs text-gray-600">{plow.brand} {plow.model} · {plow.family_label}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-500">MSRP range</div>
                    <div className="text-sm font-bold text-gray-900">${plow.msrp_low.toLocaleString()}–${plow.msrp_high.toLocaleString()}</div>
                  </div>
                </div>
                <div className="px-4 py-3 text-xs text-gray-500 italic">
                  Mount kit — auto-selected by your truck's YMM at quote time.
                </div>
                <div className="px-4 py-3 text-xs text-gray-500 italic">
                  Headlight adapter harness — auto-selected by your truck's headlight type.
                </div>
                <div className="px-4 py-3 text-xs text-gray-500 italic">
                  Vehicle-side wiring + in-cab control — selected with your sales rep.
                </div>
              </div>
              <div className="px-4 py-3 bg-gray-50 border-t flex flex-wrap gap-2">
                <a
                  href={`mailto:sales@nelsontruck.com?subject=${encodeURIComponent("Quote: " + plow.brand + " " + plow.model + " on " + truck.label)}&body=${encodeURIComponent("Truck class: " + truck.label + "\nPlow: " + plow.brand + " " + plow.model + "\nMoldboard SKU: " + activeSku + "\n\nPlease send a complete-kit quote with the right mount + harness for my truck.")}`}
                  className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded"
                >
                  Request a complete-kit quote →
                </a>
                <Link
                  to={`/snow-plows/compare?ids=${plow.id}&truck=${truckClass}`}
                  className="px-4 py-2 bg-white border hover:border-red-700 text-gray-700 text-sm font-bold rounded"
                >
                  Compare with other plows
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: pickers */}
        <div className="space-y-5">
          {/* Truck picker */}
          <div className="bg-white rounded-lg border shadow-sm">
            <div className="px-4 py-3 border-b bg-gray-50">
              <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">1. Your truck</div>
              <div className="text-sm font-bold text-gray-900">Pick your truck class</div>
            </div>
            <div className="p-3 space-y-1">
              {Object.values(TRUCK_PROFILES).map((t) => (
                <button
                  key={t.id}
                  onClick={() => setParam("truck", t.id)}
                  className={`w-full text-left px-3 py-2 rounded text-sm border transition ${
                    truckClass === t.id
                      ? "border-red-700 bg-red-50 text-red-900 font-semibold"
                      : "border-gray-200 hover:border-blue-700 text-gray-700"
                  }`}
                >
                  {t.label}
                  <div className="text-[10px] text-gray-500 mt-0.5">{t.short}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Plow picker */}
          <div className="bg-white rounded-lg border shadow-sm">
            <div className="px-4 py-3 border-b bg-gray-50">
              <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">2. Your plow</div>
              <div className="text-sm font-bold text-gray-900">Pick a plow</div>
              <div className="text-[11px] text-gray-500 mt-0.5">
                Don't know which?{" "}
                <Link to="/snow-plows#finder" className="text-red-700 hover:underline">
                  use Find My Plow →
                </Link>
              </div>
            </div>
            <div className="p-3 space-y-1 max-h-[420px] overflow-y-auto">
              {loading && <div className="text-xs text-gray-500">Loading...</div>}
              {!loading && models.map((m) => {
                const fits = m.truck_classes.includes(truckClass)
                return (
                  <button
                    key={m.id}
                    onClick={() => setParam("plow", m.id)}
                    className={`w-full text-left px-3 py-2 rounded text-sm border transition flex items-center gap-3 ${
                      plow?.id === m.id
                        ? "border-red-700 bg-red-50"
                        : fits
                          ? "border-gray-200 hover:border-blue-700"
                          : "border-amber-200 bg-amber-50/30 hover:border-amber-400"
                    }`}
                  >
                    {m.hero_image_url && (
                      <img src={m.hero_image_url} alt="" loading="lazy" className="w-12 h-9 object-contain bg-white rounded border flex-shrink-0"/>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">{m.brand}</div>
                      <div className="text-sm font-bold text-gray-900 truncate">{m.model}</div>
                      <div className="text-[10px] text-gray-500">{m.family_label} · {m.weight_lb} lb</div>
                    </div>
                    {fits ? (
                      <span className="text-[9px] uppercase tracking-wider text-green-700 font-bold flex-shrink-0">✓ fits</span>
                    ) : (
                      <span className="text-[9px] uppercase tracking-wider text-amber-700 font-bold flex-shrink-0">⚠ stretch</span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Moldboard width picker — only relevant if plow has multiple */}
          {plow && (plow.moldboard_skus?.length || 0) > 1 && (
            <div className="bg-white rounded-lg border shadow-sm">
              <div className="px-4 py-3 border-b bg-gray-50">
                <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">3. Moldboard width / material</div>
                <div className="text-sm font-bold text-gray-900">{plow.moldboard_skus!.length} options</div>
              </div>
              <div className="p-3 space-y-1">
                {plow.moldboard_skus!.map((sku) => (
                  <button
                    key={sku}
                    onClick={() => setParam("moldboard", sku)}
                    className={`w-full text-left px-3 py-2 rounded text-xs border transition font-mono ${
                      activeSku === sku
                        ? "border-red-700 bg-red-50 text-red-900 font-semibold"
                        : "border-gray-200 hover:border-blue-700 text-gray-700"
                    }`}
                  >
                    {sku}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* AI Render Panel — full-width row below the configurator grid */}
      {plow && activeSku && (
        <div className="max-w-7xl mx-auto px-6 pb-10">
          <AIRenderPanel plowSku={activeSku} truckClass={truckClass} />
        </div>
      )}
    </div>
  )
}

// =========================================================================
// AI Render Panel — "see this plow on YOUR truck" via FLUX Kontext.
// Customer fills out YMM (year, make, model, color), optionally uploads a
// photo of their truck, and we send to the backend which calls our llama's
// FLUX Kontext model.  Polls every 3 sec until rendered (typically 30-60s).
// YMM is logged for sales-team follow-up regardless of outcome.
// =========================================================================

interface AIRenderResponse {
  request_id: number
  status: "pending" | "rendering" | "complete" | "failed" | "rejected"
  rendered_image_url: string | null
  render_duration_ms: number | null
  error_message: string | null
}

function AIRenderPanel({ plowSku, truckClass }: { plowSku: string; truckClass: string }) {
  const [year, setYear] = useState("")
  const [make, setMake] = useState("")
  const [model, setModel] = useState("")
  const [color, setColor] = useState("")
  const [notes, setNotes] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [requestId, setRequestId] = useState<number | null>(null)
  const [status, setStatus] = useState<AIRenderResponse["status"] | null>(null)
  const [renderedUrl, setRenderedUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const isRendering = status === "pending" || status === "rendering"
  const canSubmit = !!plowSku && !submitting && !isRendering

  async function submit() {
    setError(null)
    setRenderedUrl(null)
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append("plow_sku", plowSku)
      if (file) fd.append("truck_image", file)
      else fd.append("truck_class", truckClass)
      if (year) fd.append("year", year)
      if (make) fd.append("make", make)
      if (model) fd.append("model", model)
      if (color) fd.append("color", color)
      if (notes) fd.append("customer_notes", notes)
      const r = await fetch("/api/configurator/render-on-truck", {
        method: "POST",
        body: fd,
      })
      if (!r.ok) {
        const txt = await r.text()
        throw new Error(`${r.status}: ${txt.substring(0, 200)}`)
      }
      const data = await r.json()
      setRequestId(data.request_id)
      setStatus(data.status)
    } catch (e: any) {
      setError(String(e?.message || e))
    } finally {
      setSubmitting(false)
    }
  }

  // Polling effect — every 3s while rendering
  useEffect(() => {
    if (!requestId || !isRendering) return
    const handle = setInterval(async () => {
      try {
        const r = await fetch(`/api/configurator/render/${requestId}`)
        if (!r.ok) return
        const data: AIRenderResponse = await r.json()
        setStatus(data.status)
        if (data.rendered_image_url) setRenderedUrl(data.rendered_image_url)
        if (data.error_message) setError(data.error_message)
      } catch (_) { /* ignore */ }
    }, 3000)
    return () => clearInterval(handle)
  }, [requestId, isRendering])

  return (
    <div className="bg-gradient-to-br from-blue-950 to-slate-900 rounded-lg shadow-lg overflow-hidden">
      <div className="px-5 py-4 border-b border-blue-800/50">
        <div className="text-[10px] uppercase tracking-[0.2em] text-yellow-400 font-bold">
          AI Render · powered by FLUX Kontext
        </div>
        <div className="text-2xl font-extrabold text-white mt-1">See it on YOUR actual truck</div>
        <div className="text-sm text-blue-200 mt-1">
          Upload a photo of your truck — our AI will mount this plow on it. Takes ~30–60 sec.
        </div>
      </div>

      <div className="p-5 grid md:grid-cols-2 gap-5">
        {/* LEFT: YMM form + upload */}
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Year</label>
              <input value={year} onChange={(e) => setYear(e.target.value)}
                placeholder="2022" inputMode="numeric"
                className="w-full mt-1 px-2 py-1.5 bg-slate-800 border border-slate-700 text-white text-sm rounded" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Make</label>
              <input value={make} onChange={(e) => setMake(e.target.value)}
                placeholder="Ford"
                className="w-full mt-1 px-2 py-1.5 bg-slate-800 border border-slate-700 text-white text-sm rounded" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Model</label>
              <input value={model} onChange={(e) => setModel(e.target.value)}
                placeholder="F-250 Super Duty"
                className="w-full mt-1 px-2 py-1.5 bg-slate-800 border border-slate-700 text-white text-sm rounded" />
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Color</label>
              <input value={color} onChange={(e) => setColor(e.target.value)}
                placeholder="Black"
                className="w-full mt-1 px-2 py-1.5 bg-slate-800 border border-slate-700 text-white text-sm rounded" />
            </div>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Truck photo (optional)</label>
            <input type="file" accept="image/*"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full mt-1 text-sm text-blue-100 file:mr-3 file:px-3 file:py-1.5 file:bg-yellow-400 file:text-black file:border-0 file:rounded file:font-bold file:cursor-pointer" />
            <div className="text-[10px] text-blue-300/80 mt-1">
              {file ? `Using: ${file.name}` : `No photo? We'll use the ${truckClass} preset render.`}
            </div>
          </div>

          <div>
            <label className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">Notes (optional)</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
              placeholder="What route are you plowing? Lot size? Any questions?"
              rows={2}
              className="w-full mt-1 px-2 py-1.5 bg-slate-800 border border-slate-700 text-white text-sm rounded resize-none" />
          </div>

          <button
            onClick={submit}
            disabled={!canSubmit}
            className={`w-full mt-1 px-4 py-3 text-sm font-extrabold uppercase tracking-widest rounded transition ${
              canSubmit
                ? "bg-yellow-400 hover:bg-yellow-300 text-black"
                : "bg-slate-700 text-slate-400 cursor-not-allowed"
            }`}
          >
            {submitting ? "Submitting..." : isRendering ? `Rendering… (${status})` : "Render with AI →"}
          </button>
          {error && (
            <div className="text-xs text-red-300 bg-red-900/40 border border-red-800 rounded px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* RIGHT: result preview */}
        <div className="rounded-lg bg-slate-950/50 border border-slate-700/50 flex items-center justify-center min-h-[280px] overflow-hidden">
          {renderedUrl ? (
            <img src={renderedUrl} alt="Your truck with the plow"
              className="w-full h-full object-contain" />
          ) : isRendering ? (
            <div className="text-center px-6 py-10">
              <div className="inline-block w-10 h-10 border-4 border-yellow-400 border-t-transparent rounded-full animate-spin"></div>
              <div className="text-sm text-blue-200 mt-4 font-mono">Status: {status}</div>
              <div className="text-[11px] text-blue-300/70 mt-2">FLUX Kontext is mounting the plow on your truck — usually 30–60 seconds.</div>
            </div>
          ) : (
            <div className="text-center px-6 py-10 text-blue-300/60">
              <div className="text-4xl mb-2">🛻</div>
              <div className="text-sm">Your render will appear here.</div>
              <div className="text-[11px] mt-2">Fill out the form (or just hit render with the preset truck) — takes about a minute.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// =========================================================================
// Find My Plow wizard — 3-step truck-class + route + budget recommender
// =========================================================================

interface RecommendMatch {
  plow: PlowModel
  score: number
  reasoning: string[]
  direct_fit: boolean
  fit_warning: string | null
}

interface RecommendResponse {
  truck_class: string
  route_type: string
  budget: string
  matches: RecommendMatch[]
  truck_class_warning: string | null
  suggested_step_up: string | null
}

const TRUCK_CLASSES: { id: string; label: string; sub: string }[] = [
  { id: "mid-size", label: "Mid-size pickup",          sub: "Tacoma · Colorado · Ranger · Maverick" },
  { id: "1500",     label: "Half-ton (1500 / F-150)",  sub: "1/2-ton GVWR" },
  { id: "2500",     label: "3/4-ton (2500 / F-250)",   sub: "Heavy-duty 3/4-ton" },
  { id: "3500",     label: "1-ton (3500 / F-350)",     sub: "1-ton single + dual rear wheel" },
  { id: "4500",     label: "Chassis cab 4500",          sub: "Class 4 commercial" },
  { id: "5500",     label: "Chassis cab 5500",          sub: "Class 5 / municipal" },
]

const ROUTE_TYPES: { id: string; label: string; sub: string }[] = [
  { id: "residential",      label: "Residential driveways",  sub: "Smaller jobs, fewer per night" },
  { id: "mixed_commercial", label: "Mixed commercial",       sub: "Driveways + small lots + walks" },
  { id: "lots",             label: "Open commercial lots",   sub: "Big parking lots, max snow per pass" },
  { id: "municipal",        label: "Municipal / heavy duty", sub: "Cul-de-sacs, EOD piles, hard pack" },
]

const BUDGETS: { id: string; label: string }[] = [
  { id: "under_5k", label: "Under $5,000" },
  { id: "5k_8k",    label: "$5K – $8K" },
  { id: "8k_12k",   label: "$8K – $12K" },
  { id: "over_12k", label: "$12K+" },
  { id: "any",      label: "No preference" },
]

// V-plow image used as the visual on the left half of the PlowFinderWizard
// hero band.  Currently the Western MVP3 (cleanest cutout we have); easy to
// swap for a configurator render or seasonal hero later.
const VPLOW_IMG = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
const PROPLUS_IMG = "/static/snow-plows/skus/WEST-PPMS86-EQP/hero_transparent.png"
const SD_VXFII_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"


// =========================================================================
// PAGE-LEVEL LANDING MOCKUPS — Apr 29 2026
// Six different visual languages for /snow-plows.  Each shows the hero +
// 1-2 representative sections so Ben can see the design SYSTEM, not just
// the hero treatment.  Live at /snow-plows/page-mockups.
// =========================================================================

/** M1 — BENTO BOX MODERN (image-rich variant).  Apple-watch-face inspired:
 *  dense grid of cards, but now with REAL plow + truck + part imagery on
 *  most cards.  Per Ben — the plow pics make the content come alive.
 *
 *  Three bento bands stack to show the full system:
 *    Band A  Hero — wizard + top-brand (Pro Plus image bg) + weather
 *    Band B  See-it-on-your-truck (truck silhouette + V-plow) + top
 *            seller part + pre-season teaser
 *    Band C  Brand grid — Western / Meyer / SnowDogg, each with a real
 *            plow photo as the visual; plus WinterWatch + compare CTA */
function PageMockupBento() {
  const TOP_SELLER_IMG = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"  // controller proxy
  const MEYER_LOTPRO_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SNOWDOGG_VXII_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  const TRUCK_1500_IMG = "/static/trucks/renders/1500.png"
  return (
    <section className="bg-slate-950 text-white px-6 py-10">
      <div className="max-w-7xl mx-auto">
        <div className="text-[10px] uppercase tracking-widest text-yellow-400 font-bold mb-3">Mockup 1 · Bento Box Modern (image-rich)</div>

        {/* BAND A — hero band: wizard + top brand + weather */}
        <div className="grid grid-cols-12 gap-3" style={{ gridAutoRows: '92px' }}>
          {/* Wizard — 7×4 */}
          <div className="col-span-12 md:col-span-7 row-span-4 bg-gradient-to-br from-white via-slate-50 to-slate-100 text-gray-900 rounded-2xl p-5 shadow-xl flex gap-4 items-center">
            <img src={VPLOW_IMG} alt="" className="w-1/2 max-w-[280px] flex-shrink-0" style={{ filter: 'drop-shadow(0 8px 16px rgba(0,0,0,0.18))' }}/>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">⚡ Find My Plow</div>
              <div className="text-2xl font-extrabold leading-tight mt-1">Tell us 3 things.</div>
              <p className="text-xs text-gray-600 mt-1">Truck. Route. Budget. We'll spec the right plow in 2 seconds.</p>
              <button className="mt-3 px-4 py-2 bg-red-700 text-white text-xs font-bold rounded">Start →</button>
            </div>
          </div>
          {/* Top brand · Pro Plus — image bg, 5×2 */}
          <div className="col-span-12 md:col-span-5 row-span-2 relative bg-gradient-to-br from-red-700 to-red-900 rounded-2xl shadow-lg overflow-hidden">
            <img src={PROPLUS_IMG} alt="" className="absolute right-0 top-0 h-full w-auto object-contain"
                 style={{ transform: 'translate(15%, 5%) rotate(-5deg)', filter: 'drop-shadow(-8px 8px 12px rgba(0,0,0,0.4))' }}/>
            <div className="relative p-4 flex flex-col h-full justify-between">
              <div className="text-[10px] uppercase tracking-widest text-red-200 font-bold">Top brand · Western</div>
              <div>
                <div className="text-3xl font-extrabold leading-none">PRO PLUS</div>
                <div className="text-[10px] text-red-200 mt-1">Heavy-duty straight blade · 3/4-ton +</div>
              </div>
            </div>
          </div>
          {/* Weather — 5×2 */}
          <div className="col-span-12 md:col-span-5 row-span-2 bg-gradient-to-br from-blue-600 to-blue-900 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
            <div className="text-[10px] uppercase tracking-widest text-blue-200 font-bold">Portland · 10-day</div>
            <div className="flex items-end gap-3">
              <div className="text-4xl">❄️</div>
              <div>
                <div className="text-2xl font-bold leading-none">3 snow days</div>
                <div className="text-[10px] text-blue-200 mt-1">in next 10 · Tue/Wed/Sat</div>
              </div>
            </div>
            <button className="self-start px-3 py-1 bg-white text-blue-900 text-[10px] font-bold rounded-full">Get alerts →</button>
          </div>
        </div>

        {/* BAND B — see-it-on-truck + top seller + pre-season */}
        <div className="grid grid-cols-12 gap-3 mt-3" style={{ gridAutoRows: '92px' }}>
          {/* Configurator — 6×3 — truck + plow imagery */}
          <div className="col-span-12 md:col-span-6 row-span-3 relative bg-gradient-to-br from-zinc-900 via-zinc-800 to-zinc-900 rounded-2xl overflow-hidden shadow-lg">
            {/* Truck silhouette in the back */}
            <img src={TRUCK_1500_IMG} alt="" className="absolute inset-0 w-full h-full object-cover opacity-30"/>
            <img src={VPLOW_IMG} alt="" className="absolute bottom-0 left-1/2 w-1/2 max-w-[260px]"
                 style={{ transform: 'translate(-50%, 8%)', filter: 'drop-shadow(0 12px 16px rgba(0,0,0,0.6))' }}/>
            <div className="relative p-4 z-10">
              <div className="text-[10px] uppercase tracking-widest text-yellow-400 font-bold">👀 Configurator · live</div>
              <div className="text-2xl font-extrabold leading-tight mt-1">See your plow<br/>on your truck.</div>
              <p className="text-[11px] text-zinc-300 mt-1 max-w-[230px]">Switch trucks or plows — render updates instantly.</p>
            </div>
          </div>
          {/* Top seller — 3×3 — uses an actual SKU image */}
          <div className="col-span-6 md:col-span-3 row-span-3 bg-white text-gray-900 rounded-2xl shadow-lg overflow-hidden flex flex-col">
            <div className="flex-1 bg-gradient-to-br from-slate-50 to-slate-100 p-3 flex items-center justify-center">
              <img src={TOP_SELLER_IMG} alt="" className="max-h-full max-w-full object-contain"/>
            </div>
            <div className="p-3 border-t border-gray-100">
              <div className="text-[9px] uppercase tracking-wider text-red-700 font-bold">Top seller · 12mo</div>
              <div className="text-sm font-extrabold leading-tight mt-0.5">Western MVP3 V-Plow</div>
              <div className="text-[10px] text-gray-500 mt-0.5">154 controllers sold · $69,817</div>
            </div>
          </div>
          {/* Pre-season — 3×3 */}
          <div className="col-span-6 md:col-span-3 row-span-3 bg-gradient-to-br from-amber-300 via-yellow-400 to-orange-500 text-gray-900 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
            <div>
              <div className="text-[10px] uppercase tracking-widest font-bold">⛄ Pre-season · save big</div>
              <div className="text-xl font-extrabold leading-tight mt-2">Order before Sept.</div>
              <div className="text-xs font-semibold mt-1">We cover the freight.</div>
            </div>
            <button className="self-start px-3 py-1.5 bg-gray-900 text-white text-[10px] font-bold rounded">Lock in pricing →</button>
          </div>
        </div>

        {/* BAND C — brand showcase: Western / Meyer / SnowDogg with images */}
        <div className="grid grid-cols-12 gap-3 mt-3" style={{ gridAutoRows: '92px' }}>
          {/* Western */}
          <div className="col-span-12 md:col-span-4 row-span-3 relative bg-gradient-to-br from-red-700 via-red-800 to-red-950 rounded-2xl shadow-lg overflow-hidden">
            <img src={PROPLUS_IMG} alt="" className="absolute -right-6 -bottom-4 w-2/3 opacity-90"
                 style={{ filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.5))', transform: 'rotate(-4deg)' }}/>
            <div className="relative p-4">
              <div className="text-[9px] uppercase tracking-widest text-red-200 font-bold">#1 in Pacific NW</div>
              <div className="text-3xl font-extrabold leading-none mt-1">Western</div>
              <div className="text-[11px] text-red-200 mt-1">6 plows · HTS → MVP3 → Wide-Out</div>
            </div>
          </div>
          {/* Meyer */}
          <div className="col-span-12 md:col-span-4 row-span-3 relative bg-gradient-to-br from-emerald-700 via-emerald-800 to-emerald-950 rounded-2xl shadow-lg overflow-hidden">
            <img src={MEYER_LOTPRO_IMG} alt="" className="absolute -right-6 -bottom-4 w-2/3 opacity-90"
                 style={{ filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.5))', transform: 'rotate(-4deg)' }}/>
            <div className="relative p-4">
              <div className="text-[9px] uppercase tracking-widest text-emerald-200 font-bold">Heaviest moldboards</div>
              <div className="text-3xl font-extrabold leading-none mt-1">Meyer</div>
              <div className="text-[11px] text-emerald-200 mt-1">5 plows · Drive Pro → Lot Pro → Super-V3</div>
            </div>
          </div>
          {/* SnowDogg */}
          <div className="col-span-12 md:col-span-4 row-span-3 relative bg-gradient-to-br from-slate-700 via-slate-800 to-slate-950 rounded-2xl shadow-lg overflow-hidden">
            <img src={SNOWDOGG_VXII_IMG} alt="" className="absolute -right-6 -bottom-4 w-2/3 opacity-90"
                 style={{ filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.5))', transform: 'rotate(-4deg)' }}/>
            <div className="relative p-4">
              <div className="text-[9px] uppercase tracking-widest text-slate-300 font-bold">Best-spec for the price</div>
              <div className="text-3xl font-extrabold leading-none mt-1">SnowDogg</div>
              <div className="text-[11px] text-slate-300 mt-1">5 plows · MDII → EXII → VXFII → XPII</div>
            </div>
          </div>
        </div>

        {/* BAND D — secondary actions: WinterWatch + Compare + In-stock counter */}
        <div className="grid grid-cols-12 gap-3 mt-3" style={{ gridAutoRows: '92px' }}>
          <div className="col-span-12 md:col-span-6 row-span-2 bg-gradient-to-br from-cyan-500 via-blue-600 to-indigo-700 rounded-2xl p-4 shadow-lg flex items-center gap-4">
            <div className="text-5xl">❄️</div>
            <div className="flex-1">
              <div className="text-[10px] uppercase tracking-widest text-cyan-100 font-bold">WinterWatch · free</div>
              <div className="text-xl font-extrabold leading-tight">Get email alerts when snow is in your 10-day forecast.</div>
            </div>
            <button className="px-4 py-2 bg-white text-blue-900 text-xs font-bold rounded shrink-0">Sign up →</button>
          </div>
          <div className="col-span-6 md:col-span-3 row-span-2 bg-gradient-to-br from-yellow-400 to-orange-500 text-gray-900 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
            <div className="text-[10px] uppercase tracking-widest font-bold">In stock</div>
            <div>
              <div className="text-3xl font-extrabold leading-none">2,114</div>
              <div className="text-[10px]">snow SKUs · ships today</div>
            </div>
          </div>
          <div className="col-span-6 md:col-span-3 row-span-2 bg-gradient-to-br from-slate-800 to-slate-700 rounded-2xl p-4 shadow-lg flex flex-col justify-between">
            <div className="text-[10px] uppercase tracking-widest text-slate-300 font-bold">⚖️ Compare</div>
            <div>
              <div className="text-base font-bold leading-tight">Spec 17 plows side-by-side.</div>
              <div className="text-[10px] text-slate-400 mt-1">Filter by truck class →</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** M2 — DARK TACTICAL (image-rich variant).  Black bg, neon-yellow +
 *  safety-red, uppercase typography, thick bars, monospace stats.  Reads
 *  like a tactical-gear site (5.11, Leatherman, Boss Plow ad campaigns).
 *
 *  Per Ben's "more images" feedback — expanded from a single hero into
 *  five tactical bands, each integrating real plow imagery in a way that
 *  reinforces the contractor/military identity:
 *    Band A  TACTICAL HERO — picker + V-plow with yellow glow
 *    Band B  HEADS-UP STRIP — "no home-plow garbage" callout
 *    Band C  LOADOUT (brands) — Western/Meyer/SnowDogg as gear cards
 *            with plow images, ratings, "DEPLOY" CTAs
 *    Band D  MISSION BRIEF (top seller) — featured plow with sales stats
 *            in tactical-readout format
 *    Band E  FITMENT CHECK (configurator) — truck silhouette + plow
 *            overlay with a "VEHICLE/PAYLOAD MATCH" header */
function PageMockupTactical() {
  const TOP_SELLER_IMG = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
  const MEYER_LOTPRO_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SNOWDOGG_VXII_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  const TRUCK_2500_IMG = "/static/trucks/renders/2500.png"
  return (
    <section className="bg-black text-white">
      <div className="text-[10px] uppercase tracking-widest text-yellow-400 font-bold px-6 pt-6 max-w-7xl mx-auto">Mockup 2 · Dark Tactical (image-rich)</div>

      {/* BAND A — TACTICAL HERO with V-plow visual */}
      <div className="relative max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_440px] gap-8 items-center">
        {/* Diagonal accent stripe behind */}
        <div className="absolute top-10 right-1/3 w-2 h-32 bg-yellow-400/30 rotate-12 pointer-events-none"/>
        <div className="absolute bottom-10 left-1/4 w-2 h-24 bg-red-700/30 -rotate-12 pointer-events-none"/>

        <div className="relative">
          <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-bold mb-2">CONTRACTOR-GRADE · PACIFIC NW</div>
          <h1 className="text-5xl md:text-7xl font-black leading-none uppercase tracking-tight">
            FIND YOUR<br/>
            <span className="text-yellow-400">PLOW.</span>
          </h1>
          {/* V-plow with yellow tactical glow */}
          <div className="mt-6 relative inline-block">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[480px]"
                 style={{ filter: 'drop-shadow(0 0 24px rgba(250,204,21,0.35)) drop-shadow(0 12px 16px rgba(0,0,0,0.6))' }}/>
          </div>
          <div className="mt-4 inline-flex items-center gap-3 px-4 py-2 bg-yellow-400 text-black text-xs font-black uppercase tracking-wider">
            <span>WESTERN · MEYER · SNOWDOGG</span>
            <span className="text-red-700">|</span>
            <span>2,114 IN STOCK</span>
          </div>
          <p className="mt-4 text-sm text-zinc-400 max-w-md">No home-plow garbage.  Half-ton through chassis-cab.  Ranked by your truck class + route + budget — in seconds.</p>
        </div>

        <div className="relative bg-zinc-900 border-l-4 border-yellow-400 p-5">
          <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-bold mb-3">⚡ FIND MY PLOW · 3-STEP</div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono mb-1">01 / TRUCK</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border border-zinc-700 hover:border-yellow-400 hover:text-yellow-400 transition font-mono">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono mb-1">02 / ROUTE</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border border-zinc-700 hover:border-yellow-400 hover:text-yellow-400 transition font-mono">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono mb-1">03 / BUDGET</div>
              <div className="grid grid-cols-3 gap-1">
                {['<5K','5-8K','8-12K','12K+','ANY','--'].map(c => (
                  <button key={c} className="px-1 py-2 text-[10px] font-bold uppercase border border-zinc-700 hover:border-yellow-400 hover:text-yellow-400 transition font-mono">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-3 px-3 py-3 bg-yellow-400 text-black text-sm font-black uppercase tracking-wider hover:bg-yellow-300">EXEC · find my plow ▸</button>
          </div>
        </div>
      </div>

      {/* BAND B — HEADS-UP strip */}
      <div className="bg-zinc-900 border-y-2 border-yellow-400">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-wrap items-center justify-between gap-4 text-xs uppercase tracking-wider">
          <span className="text-yellow-400 font-black">⚠ HEADS UP</span>
          <span className="text-zinc-300">WE DON'T SELL HOME-PLOW BLADES FOR CONTRACTOR ROUTES.</span>
          <span className="text-zinc-300">→ <span className="text-yellow-400 font-bold underline">WHY THAT MATTERS</span></span>
        </div>
      </div>

      {/* BAND C — LOADOUT: 3 brands as tactical gear cards with plow imagery */}
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-black mb-1">/ LOADOUT</div>
        <h2 className="text-3xl font-black uppercase tracking-tight mb-6">PICK YOUR ARSENAL.</h2>
        <div className="grid md:grid-cols-3 gap-3">
          {[
            { brand: 'WESTERN', tag: 'PRIMARY', sub: 'PRO PLUS · MVP3 · WIDE-OUT', units: '6 PLOWS', color: 'red', img: PROPLUS_IMG, accent: 'border-red-700' },
            { brand: 'MEYER',   tag: 'HEAVY-DUTY', sub: 'LOT PRO · DRIVE PRO · SUPER-V3', units: '5 PLOWS', color: 'emerald', img: MEYER_LOTPRO_IMG, accent: 'border-emerald-500' },
            { brand: 'SNOWDOGG', tag: 'VALUE TIER', sub: 'MDII · EXII · VXFII · XPII', units: '5 PLOWS', color: 'cyan', img: SNOWDOGG_VXII_IMG, accent: 'border-cyan-400' },
          ].map((b) => (
            <div key={b.brand} className={`relative bg-zinc-900 border ${b.accent} p-5 overflow-hidden hover:border-yellow-400 transition cursor-pointer group`}>
              <img src={b.img} alt="" className="absolute right-0 bottom-0 w-2/3 opacity-90 group-hover:opacity-100 transition"
                   style={{ filter: 'drop-shadow(-6px 6px 12px rgba(0,0,0,0.7)) drop-shadow(0 0 16px rgba(250,204,21,0.15))', transform: 'rotate(-3deg) translate(15%, 20%)' }}/>
              <div className="relative">
                <div className="text-[9px] uppercase tracking-[0.3em] text-zinc-500 font-mono">{b.tag}</div>
                <div className="text-3xl font-black uppercase tracking-tight mt-1">{b.brand}</div>
                <div className="text-[10px] text-zinc-400 mt-1 font-mono">{b.sub}</div>
                <div className="mt-12 flex items-center justify-between">
                  <span className="text-[10px] text-yellow-400 font-mono">{b.units}</span>
                  <span className="text-xs font-black uppercase tracking-wider text-yellow-400 group-hover:text-white transition">DEPLOY ▸</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* BAND D — MISSION BRIEF: top seller plow with tactical readout */}
      <div className="bg-zinc-900 border-y border-zinc-800">
        <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_2fr] gap-8 items-center">
          <div>
            <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-mono mb-1">/ MISSION BRIEF · TOP SELLER · 12MO</div>
            <h2 className="text-3xl font-black uppercase tracking-tight">WESTERN<br/>MVP3 V-PLOW.</h2>
            <p className="text-sm text-zinc-400 mt-3 max-w-md font-mono">Stainless V-plow.  Trip-edge protection.  Center-link strength.  The single most-deployed unit in the Pacific NW snow-belt arsenal.</p>
            {/* Tactical stat readouts */}
            <div className="mt-5 grid grid-cols-2 gap-2 max-w-md">
              {[['CONTROLLERS', '154', 'units · 12mo'],
                ['REVENUE', '$69,817', 'last 12mo'],
                ['IN STOCK', '✓', 'ships today'],
                ['PRE-SEASON', '8 wk', 'install lead']].map(([label, big, sub]) => (
                <div key={label as string} className="bg-black border border-zinc-700 px-3 py-2 font-mono">
                  <div className="text-[9px] uppercase tracking-widest text-zinc-500">{label}</div>
                  <div className="text-lg font-black text-yellow-400">{big}</div>
                  <div className="text-[9px] text-zinc-500">{sub}</div>
                </div>
              ))}
            </div>
            <button className="mt-5 px-5 py-2.5 bg-yellow-400 text-black text-xs font-black uppercase tracking-wider hover:bg-yellow-300">REQUEST QUOTE ▸</button>
          </div>
          <div className="relative">
            {/* Hex-grid bg overlay for tactical look */}
            <div className="absolute inset-0 opacity-20 pointer-events-none"
                 style={{ backgroundImage: 'linear-gradient(0deg, transparent 24%, rgba(250,204,21,0.18) 25%, rgba(250,204,21,0.18) 26%, transparent 27%, transparent 74%, rgba(250,204,21,0.18) 75%, rgba(250,204,21,0.18) 76%, transparent 77%), linear-gradient(90deg, transparent 24%, rgba(250,204,21,0.18) 25%, rgba(250,204,21,0.18) 26%, transparent 27%, transparent 74%, rgba(250,204,21,0.18) 75%, rgba(250,204,21,0.18) 76%, transparent 77%)', backgroundSize: '50px 50px' }}/>
            <img src={TOP_SELLER_IMG} alt="" className="relative w-full max-w-2xl mx-auto"
                 style={{ filter: 'drop-shadow(0 0 32px rgba(250,204,21,0.3)) drop-shadow(0 16px 24px rgba(0,0,0,0.6))' }}/>
          </div>
        </div>
      </div>

      {/* BAND E — FITMENT CHECK (configurator tease with truck) */}
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="grid md:grid-cols-2 gap-3">
          {/* Configurator card */}
          <div className="relative bg-gradient-to-br from-zinc-900 via-black to-zinc-900 border-2 border-yellow-400 p-6 overflow-hidden">
            <img src={TRUCK_2500_IMG} alt="" className="absolute inset-0 w-full h-full object-cover opacity-30"/>
            <img src={VPLOW_IMG} alt="" className="absolute bottom-0 left-1/2 w-1/2 max-w-[280px]"
                 style={{ transform: 'translate(-50%, 10%)', filter: 'drop-shadow(0 0 24px rgba(250,204,21,0.5)) drop-shadow(0 16px 20px rgba(0,0,0,0.8))' }}/>
            <div className="relative z-10">
              <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-mono mb-1">/ FITMENT CHECK</div>
              <h3 className="text-3xl font-black uppercase tracking-tight">VEHICLE / PAYLOAD<br/>MATCH.</h3>
              <p className="text-sm text-zinc-300 mt-2 max-w-[280px] font-mono">Pick truck.  Pick plow.  See it mounted.  Live render.</p>
              <button className="mt-4 px-4 py-2 bg-yellow-400 text-black text-xs font-black uppercase tracking-wider hover:bg-yellow-300">RUN CHECK ▸</button>
            </div>
          </div>
          {/* WinterWatch + ops strip */}
          <div className="grid grid-rows-[1fr_1fr] gap-3">
            <div className="bg-zinc-900 border-l-4 border-cyan-400 p-5 flex items-center gap-4">
              <div className="text-4xl">❄</div>
              <div className="flex-1">
                <div className="text-[10px] uppercase tracking-[0.3em] text-cyan-400 font-mono">/ WINTERWATCH · STANDBY</div>
                <div className="text-base font-black uppercase tracking-tight">SNOW INCOMING ALERTS · YOUR ZIP.</div>
                <div className="text-[10px] text-zinc-400 mt-1 font-mono">FREE · OPT-IN · 10-DAY FORECAST</div>
              </div>
              <button className="px-3 py-2 bg-cyan-400 text-black text-[10px] font-black uppercase tracking-wider">ENLIST ▸</button>
            </div>
            <div className="bg-zinc-900 border-l-4 border-red-700 p-5 flex items-center gap-4">
              <div className="text-4xl">⛽</div>
              <div className="flex-1">
                <div className="text-[10px] uppercase tracking-[0.3em] text-red-500 font-mono">/ PRE-SEASON · OPS WINDOW</div>
                <div className="text-base font-black uppercase tracking-tight">ORDER BEFORE SEPT · WE COVER THE FREIGHT.</div>
                <div className="text-[10px] text-zinc-400 mt-1 font-mono">WINDOW CLOSES BEFORE FIRST SNOW</div>
              </div>
              <button className="px-3 py-2 bg-red-700 text-white text-[10px] font-black uppercase tracking-wider">LOCK IN ▸</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** M3 — EDITORIAL MAGAZINE.  Cream/off-white, serif headlines, generous
 *  whitespace, large gallery imagery.  Treats the buying decision like
 *  a feature article rather than a transaction.  Premium, considered,
 *  understated.  Closer to NYT Cooking or The New Yorker than to a
 *  typical ecommerce hero. */
function PageMockupEditorial() {
  return (
    <section className="bg-stone-50 text-stone-900">
      <div className="text-[10px] uppercase tracking-widest text-stone-500 font-bold px-6 pt-6 max-w-7xl mx-auto">Mockup 3 · Editorial Magazine</div>
      <div className="max-w-6xl mx-auto px-6 py-12">
        <div className="text-[10px] uppercase tracking-[0.3em] text-stone-500 mb-4">CONTRACTOR PLOW BUYING GUIDE · WINTER 2026</div>
        <h1 className="font-serif text-5xl md:text-6xl leading-tight font-bold max-w-3xl">The right plow, picked by your truck.</h1>
        <p className="font-serif text-lg text-stone-700 mt-4 max-w-2xl italic leading-relaxed">
          Mount and light adapter are the only vehicle-specific parts on a snow plow build.  Everything else — the moldboard, the cutting edge, the hydraulics — is sized by truck <em>class</em>, not by VIN.  We've spent 40 years figuring out which plow goes on which truck.  Here's the short version.
        </p>
        <div className="mt-12 grid md:grid-cols-[1fr_360px] gap-12 items-start">
          <img src={PROPLUS_IMG} alt="" className="w-full" style={{ filter: 'drop-shadow(0 12px 30px rgba(0,0,0,0.10))' }}/>
          <div>
            <div className="text-[10px] uppercase tracking-[0.3em] text-stone-500 mb-2">FIND MY PLOW</div>
            <div className="font-serif text-2xl font-bold mb-1">Three questions.</div>
            <p className="text-sm text-stone-600 mb-5">Tell us about your truck, your route, and your budget.  We'll show you the three best matches from our 17-model contractor catalog.</p>
            <div className="space-y-3 border-l-2 border-stone-300 pl-4">
              <div><div className="text-[10px] uppercase tracking-wider text-stone-500">I.</div><div className="font-serif font-bold">My truck</div></div>
              <div><div className="text-[10px] uppercase tracking-wider text-stone-500">II.</div><div className="font-serif font-bold">My route</div></div>
              <div><div className="text-[10px] uppercase tracking-wider text-stone-500">III.</div><div className="font-serif font-bold">My budget</div></div>
            </div>
            <button className="mt-6 inline-flex items-center gap-2 text-sm font-serif italic text-stone-900 border-b border-stone-900 pb-0.5 hover:text-red-800 hover:border-red-800">
              Begin the questionnaire →
            </button>
          </div>
        </div>
      </div>
      {/* Pull-quote */}
      <div className="border-y border-stone-300 py-12 bg-white">
        <div className="max-w-3xl mx-auto px-6 text-center">
          <p className="font-serif text-3xl italic leading-relaxed text-stone-800">"We won't sell you a home-plow blade for a contractor route.  They're built for one or two seasons of driveway use.  Put one on a commercial route and it won't survive a single winter."</p>
          <div className="mt-6 text-[10px] uppercase tracking-[0.3em] text-stone-500">— Nelson Truck Equipment, since 1937</div>
        </div>
      </div>
    </section>
  )
}

/** M4 — STRIPE-STYLE MINIMAL.  Pure white, careful sans-serif, generous
 *  breathing room, a single bold sentence H1 + clear hierarchy.  Subtle
 *  gradients.  Looks like Stripe / Linear / Vercel.  For "this looks
 *  like a serious software company that ALSO happens to sell snow
 *  plows."  Modern SaaS aesthetic. */
function PageMockupMinimal() {
  return (
    <section className="bg-white text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-400 font-bold px-6 pt-6 max-w-7xl mx-auto">Mockup 4 · Stripe-style Minimal</div>
      <div className="max-w-5xl mx-auto px-6 py-20 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 bg-gray-100 rounded-full text-xs text-gray-600 mb-8">
          <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"/>
          <span>2,114 SKUs in stock today</span>
        </div>
        <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight leading-none">
          The right plow,<br/>
          <span className="bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">picked by your truck.</span>
        </h1>
        <p className="text-lg text-gray-600 mt-6 max-w-2xl mx-auto leading-relaxed">
          Tell us your truck class, route mix, and budget.  We'll spec one of 17 contractor-grade plows from Western, Meyer, and SnowDogg.  No VIN, no email up front.
        </p>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
          <button className="px-6 py-3 bg-gray-900 hover:bg-gray-800 text-white text-sm font-semibold rounded-lg shadow-sm">Find my plow →</button>
          <button className="px-6 py-3 bg-white hover:bg-gray-50 text-gray-700 text-sm font-semibold border border-gray-300 rounded-lg">See it on my truck</button>
        </div>
        <div className="mt-16">
          <img src={VPLOW_IMG} alt="" className="w-full max-w-2xl mx-auto" style={{ filter: 'drop-shadow(0 30px 60px rgba(0,0,0,0.12))' }}/>
        </div>
      </div>
      {/* Logos strip */}
      <div className="border-t border-gray-100 bg-gray-50/50">
        <div className="max-w-5xl mx-auto px-6 py-8 text-center">
          <div className="text-xs uppercase tracking-widest text-gray-500 mb-4">Factory-authorized for</div>
          <div className="flex flex-wrap items-center justify-center gap-8 text-xl font-bold text-gray-400">
            <span>WESTERN</span>
            <span>MEYER</span>
            <span>SNOWDOGG</span>
            <span>BUYERS</span>
          </div>
        </div>
      </div>
    </section>
  )
}

/** M5 — SCROLLYTELLING JOURNEY.  A guided 3-step narrative.  The hero
 *  introduces "3 questions, 3 picks" and then each scroll-section
 *  reveals the next step.  Inspired by Apple product pages.  Most
 *  ambitious technically (would need scroll-pinned animations) but
 *  highest-conversion if executed well. */
function PageMockupScrolly() {
  return (
    <section className="bg-gradient-to-b from-slate-100 via-white to-slate-100 text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">Mockup 5 · Scrollytelling Journey</div>
      <div className="max-w-7xl mx-auto px-6 py-16">
        <div className="text-center mb-16">
          <div className="text-[10px] uppercase tracking-widest text-blue-700 font-bold mb-2">Three questions.  Three picks.</div>
          <h1 className="text-5xl md:text-6xl font-extrabold leading-tight max-w-3xl mx-auto">Find your plow in under a minute.</h1>
          <p className="text-base text-gray-600 mt-4 max-w-xl mx-auto">Each question narrows our 17-model catalog by half.  By question three, you'll see the three plows that fit you best — and the reasoning behind each.</p>
        </div>
        {/* 3 progressive steps */}
        {[
          { num: '01', label: 'WHAT DO YOU DRIVE?', title: 'Truck class first.', body: 'Half-ton, three-quarter-ton, one-ton, chassis cab, mid-size pickup.  Front-axle weight rating is the constraint that picks your plow weight; everything else flows from this.', cta: 'Pick truck class', img: VPLOW_IMG, color: 'red' },
          { num: '02', label: 'WHAT DO YOU PLOW?', title: 'Driveways or open lots?', body: 'Residential, mixed commercial, big parking lots, or municipal heavy duty.  This picks the blade family — straight blade, V-plow, or winged.', cta: 'Pick route mix', img: PROPLUS_IMG, color: 'blue' },
          { num: '03', label: 'WHAT\'S YOUR BUDGET?', title: 'Then we narrow to 3.', body: 'Once we know your truck and route, budget picks between contractor-grade tiers.  We\'ll always show you the closest fit even if it stretches your range.', cta: 'See my matches', img: SD_VXFII_IMG, color: 'green' },
        ].map((step, i) => (
          <div key={step.num} className={`grid md:grid-cols-2 gap-12 items-center mb-24 ${i % 2 === 1 ? 'md:[&>div:first-child]:order-2' : ''}`}>
            <div>
              <img src={step.img} alt="" className="w-full max-w-[480px]" style={{ filter: 'drop-shadow(0 14px 28px rgba(0,0,0,0.15))' }}/>
            </div>
            <div>
              <div className={`inline-block text-[10px] uppercase tracking-[0.3em] font-bold mb-2 text-${step.color}-700`}>STEP {step.num} · {step.label}</div>
              <h2 className="text-4xl font-extrabold leading-tight mb-3">{step.title}</h2>
              <p className="text-base text-gray-600 leading-relaxed mb-5 max-w-md">{step.body}</p>
              <button className={`px-5 py-2.5 bg-${step.color}-700 hover:bg-${step.color}-800 text-white text-sm font-bold rounded`}>{step.cta} →</button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

/** M6 — PRO DASHBOARD.  Compact, info-dense, almost ERP-like.  Live
 *  data: in-stock counts, lead times, weather forecast strip, popular
 *  SKUs ranked by units-this-week.  Monospace accents.  For pros who
 *  hate marketing fluff.  Bloomberg Terminal meets Linear board view. */
function PageMockupDashboard() {
  return (
    <section className="bg-zinc-950 text-zinc-100 font-mono">
      <div className="text-[10px] uppercase tracking-widest text-cyan-400 font-bold px-6 pt-6 max-w-7xl mx-auto">Mockup 6 · Pro Dashboard</div>
      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Top status strip */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-6 text-xs">
          {[['STOCK', '2114', 'SKUs', 'text-green-400'],
            ['LEAD', '4-6 wk', 'pre-season', 'text-yellow-400'],
            ['SNOW', '3 days', 'next 10', 'text-cyan-400'],
            ['ALERT', '24', 'subscribers', 'text-zinc-400'],
            ['ORD', '1 left', 'free freight', 'text-red-400']].map(([label, big, sub, color]) => (
            <div key={label} className="bg-zinc-900 border border-zinc-800 px-3 py-2">
              <div className={`text-[9px] uppercase tracking-widest ${color} font-bold`}>{label}</div>
              <div className="text-lg font-bold">{big}</div>
              <div className="text-[10px] text-zinc-500">{sub}</div>
            </div>
          ))}
        </div>
        {/* Hero block */}
        <div className="grid md:grid-cols-[2fr_1fr] gap-3 mb-6">
          <div className="bg-zinc-900 border border-zinc-800 p-5">
            <div className="text-[10px] uppercase tracking-widest text-cyan-400 font-bold">/find_my_plow</div>
            <h1 className="text-3xl font-bold mt-1 leading-tight">contractor_grade.spec(truck, route, budget)</h1>
            <p className="text-xs text-zinc-400 mt-2">17 plows · 6 truck classes · 4 route types · 5 budget tiers · ranks 3 best matches with explainable scoring</p>
            <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
              <button className="px-3 py-2 bg-cyan-400 text-black font-bold uppercase">$ exec</button>
              <button className="px-3 py-2 border border-zinc-700 hover:border-cyan-400 uppercase">--help</button>
              <button className="px-3 py-2 border border-zinc-700 hover:border-cyan-400 uppercase">--list</button>
            </div>
          </div>
          {/* Top sellers table */}
          <div className="bg-zinc-900 border border-zinc-800 p-4">
            <div className="text-[10px] uppercase tracking-widest text-cyan-400 font-bold mb-2">top sellers · 7d</div>
            <table className="w-full text-xs">
              <tbody>
                {[['WEST35500', 'Controller', '12'],
                  ['WEST72530', 'Light Kit', '8'],
                  ['WEST31271-1', 'F-350 Mount', '4'],
                  ['WEST29070-1', '3-Port Module', '11']].map(([sku, desc, n]) => (
                  <tr key={sku} className="border-b border-zinc-800 last:border-0">
                    <td className="py-1.5 text-cyan-400">{sku}</td>
                    <td className="py-1.5 text-zinc-400 truncate">{desc}</td>
                    <td className="py-1.5 text-right text-green-400 font-bold">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {/* Forecast strip */}
        <div className="bg-zinc-900 border border-zinc-800 p-3 text-xs">
          <div className="text-[10px] uppercase tracking-widest text-cyan-400 font-bold mb-2">spokane.forecast · 10d</div>
          <div className="flex gap-1">
            {['M','T','W','T','F','S','S','M','T','W'].map((day, i) => {
              const snow = [false, true, true, false, false, false, true, false, false, false][i]
              return (
                <div key={i} className={`flex-1 text-center py-2 border ${snow ? 'border-cyan-400 bg-cyan-950 text-cyan-200' : 'border-zinc-800'}`}>
                  <div className="text-[9px] text-zinc-500">{day}</div>
                  <div className="text-base">{snow ? '❄' : '·'}</div>
                  <div className="text-[9px]">{[34,28,26,38,42,40,30,36,40,42][i]}°</div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

// =========================================================================
// LIGHT TACTICAL VARIANTS — Apr 29 2026
// Per Ben — likes the tactical layout / voice but wants the dark bg replaced
// with a white/light variant.  Keeps: uppercase headlines, monospace stats,
// slash-prefixed section headers, "DEPLOY ▸"-style CTAs, plow imagery
// integrated everywhere.  Changes: white/cream bg, black structure bars,
// single brand-color accent per variant so the personalities differ.
// Live at /snow-plows/page-mockups-light.
// =========================================================================

/** L1 · WORKSHOP WHITE — Pro-tool catalog feel (Snap-on, DeWalt, Mac Tools).
 *  Pure white bg, charcoal/black structure bars, yellow safety accent for
 *  CTAs, red for warnings.  Heavy use of plow imagery on clean white pops.
 *  Most "this is a serious tools store" of the four.  */
function PageMockupLightTacticalWorkshop() {
  const TOP_SELLER = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  return (
    <section className="bg-white text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L1 · Workshop White (Snap-on / DeWalt feel)</div>
      {/* HERO */}
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_440px] gap-8 items-center">
        <div>
          <div className="inline-block bg-gray-900 text-yellow-400 px-3 py-1 text-[10px] uppercase tracking-[0.3em] font-black mb-3">⚠ CONTRACTOR-GRADE · PACIFIC NW</div>
          <h1 className="text-5xl md:text-7xl font-black uppercase leading-none tracking-tight">
            FIND YOUR<br/>
            <span className="text-yellow-500" style={{ textShadow: '2px 2px 0 #18181b' }}>PLOW.</span>
          </h1>
          <div className="mt-6 relative inline-block">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[460px]"
                 style={{ filter: 'drop-shadow(0 14px 24px rgba(0,0,0,0.18))' }}/>
          </div>
          <div className="mt-4 inline-flex items-stretch text-xs font-black uppercase tracking-wider">
            <span className="bg-yellow-400 text-black px-3 py-2">2,114 IN STOCK</span>
            <span className="bg-gray-900 text-yellow-400 px-3 py-2">WEST · MEY · SDGG</span>
          </div>
        </div>
        <div className="bg-gray-50 border-2 border-gray-900 p-5">
          <div className="bg-gray-900 text-yellow-400 -mx-5 -mt-5 mb-4 px-5 py-2 text-[10px] uppercase tracking-[0.3em] font-black">⚡ FIND MY PLOW · 3-STEP</div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono mb-1">01 / TRUCK</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border-2 border-gray-300 hover:border-yellow-500 hover:bg-yellow-50 transition">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-mono mb-1">02 / ROUTE</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border-2 border-gray-300 hover:border-yellow-500 hover:bg-yellow-50 transition">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-2 px-3 py-3 bg-gray-900 text-yellow-400 text-sm font-black uppercase tracking-wider hover:bg-black">EXEC · find my plow ▸</button>
          </div>
        </div>
      </div>
      {/* HEADS-UP strip — black on white */}
      <div className="bg-gray-900 border-y-4 border-yellow-400">
        <div className="max-w-7xl mx-auto px-6 py-3 flex flex-wrap items-center justify-between gap-4 text-xs uppercase tracking-wider text-gray-100">
          <span className="text-yellow-400 font-black">⚠ HEADS UP</span>
          <span>WE DON'T SELL HOME-PLOW BLADES FOR CONTRACTOR ROUTES.</span>
          <span>→ <span className="text-yellow-400 font-bold underline">WHY THAT MATTERS</span></span>
        </div>
      </div>
      {/* LOADOUT */}
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="text-[10px] uppercase tracking-[0.3em] text-gray-900 font-black mb-1 font-mono">/ LOADOUT</div>
        <h2 className="text-3xl font-black uppercase tracking-tight mb-6">PICK YOUR ARSENAL.</h2>
        <div className="grid md:grid-cols-3 gap-3">
          {[
            { brand: 'WESTERN', tag: 'PRIMARY', sub: 'PRO PLUS · MVP3 · WIDE-OUT', img: PROPLUS_IMG, accent: 'border-red-700', text: 'text-red-700' },
            { brand: 'MEYER',   tag: 'HEAVY-DUTY', sub: 'LOT PRO · DRIVE PRO · SUPER-V3', img: MEYER_IMG, accent: 'border-emerald-700', text: 'text-emerald-700' },
            { brand: 'SNOWDOGG', tag: 'VALUE TIER', sub: 'MDII · EXII · VXFII · XPII', img: SD_IMG, accent: 'border-cyan-700', text: 'text-cyan-700' },
          ].map((b) => (
            <div key={b.brand} className={`relative bg-white border-2 ${b.accent} p-5 overflow-hidden hover:bg-gray-50 transition cursor-pointer group min-h-[200px]`}>
              <img src={b.img} alt="" className="absolute right-0 bottom-0 w-2/3 opacity-90 group-hover:opacity-100 transition"
                   style={{ filter: 'drop-shadow(-6px 6px 12px rgba(0,0,0,0.15))', transform: 'rotate(-3deg) translate(15%, 20%)' }}/>
              <div className="relative">
                <div className={`text-[9px] uppercase tracking-[0.3em] ${b.text} font-mono font-black`}>{b.tag}</div>
                <div className="text-3xl font-black uppercase tracking-tight mt-1">{b.brand}</div>
                <div className="text-[10px] text-gray-500 mt-1 font-mono">{b.sub}</div>
                <div className="mt-12 flex items-center gap-2">
                  <span className={`text-xs font-black uppercase tracking-wider ${b.text}`}>DEPLOY ▸</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      {/* MISSION BRIEF */}
      <div className="bg-gray-50 border-y-2 border-gray-900">
        <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_2fr] gap-8 items-center">
          <div>
            <div className="text-[10px] uppercase tracking-[0.3em] text-gray-700 font-mono font-black mb-1">/ MISSION BRIEF · TOP SELLER · 12MO</div>
            <h2 className="text-3xl font-black uppercase tracking-tight">WESTERN<br/>MVP3 V-PLOW.</h2>
            <p className="text-sm text-gray-600 mt-3 max-w-md font-mono">Stainless V-plow.  Trip-edge protection.  The single most-deployed unit in the Pacific NW snow-belt arsenal.</p>
            <div className="mt-5 grid grid-cols-2 gap-2 max-w-md">
              {[['CONTROLLERS', '154', 'units · 12mo'],
                ['REVENUE', '$69.8K', 'last 12mo'],
                ['IN STOCK', '✓', 'ships today'],
                ['LEAD', '8 wk', 'pre-season']].map(([label, big, sub]) => (
                <div key={label as string} className="bg-white border-2 border-gray-900 px-3 py-2 font-mono">
                  <div className="text-[9px] uppercase tracking-widest text-gray-500">{label}</div>
                  <div className="text-lg font-black text-gray-900">{big}</div>
                  <div className="text-[9px] text-gray-500">{sub}</div>
                </div>
              ))}
            </div>
            <button className="mt-5 px-5 py-2.5 bg-gray-900 text-yellow-400 text-xs font-black uppercase tracking-wider hover:bg-black">REQUEST QUOTE ▸</button>
          </div>
          <div>
            <img src={TOP_SELLER} alt="" className="w-full max-w-2xl mx-auto"
                 style={{ filter: 'drop-shadow(0 14px 28px rgba(0,0,0,0.15))' }}/>
          </div>
        </div>
      </div>
    </section>
  )
}


/** L2 · HI-VIS SAFETY — yellow + white dominant with black structure bars.
 *  Looks like a high-visibility safety vest or roadside signage.  Bold,
 *  highly readable, immediately reads as "construction / outdoor work."  */
function PageMockupLightTacticalHiVis() {
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  return (
    <section className="bg-yellow-50">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L2 · Hi-Vis Safety (signage feel)</div>
      {/* Hi-vis stripe banner */}
      <div className="bg-yellow-400 border-y-4 border-black">
        <div className="max-w-7xl mx-auto px-6 py-2 flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-widest font-black text-black">
          <span>⚠ CONTRACTOR-GRADE PLOWS</span>
          <span>2,114 IN STOCK · SHIPS TODAY</span>
          <span>WESTERN · MEYER · SNOWDOGG</span>
        </div>
      </div>
      {/* HERO */}
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_420px] gap-8 items-center">
        <div>
          <h1 className="text-6xl md:text-8xl font-black uppercase leading-[0.85] tracking-tighter text-black">
            FIND<br/>
            <span className="bg-black text-yellow-400 px-2 inline-block">YOUR PLOW</span>
          </h1>
          <p className="mt-6 text-base font-bold uppercase tracking-wide text-gray-800 max-w-md">No home-plow garbage. Half-ton through chassis-cab.</p>
          <div className="mt-6 relative inline-block">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[480px]"
                 style={{ filter: 'drop-shadow(0 0 32px rgba(0,0,0,0.15)) drop-shadow(0 14px 24px rgba(0,0,0,0.20))' }}/>
            {/* hi-vis diagonal stripe accent */}
            <div className="absolute -top-2 -right-2 w-16 h-16 bg-black -rotate-45 origin-top-right opacity-90"
                 style={{ clipPath: 'polygon(0 0, 100% 0, 100% 30%, 30% 100%, 0 100%)' }}/>
          </div>
        </div>
        <div className="bg-black text-yellow-400 border-4 border-black p-5 shadow-2xl">
          <div className="text-[10px] uppercase tracking-[0.3em] font-black mb-3">⚡ FIND MY PLOW</div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono mb-1">01 / TRUCK</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border border-zinc-700 hover:bg-yellow-400 hover:text-black hover:border-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 font-mono mb-1">02 / ROUTE</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border border-zinc-700 hover:bg-yellow-400 hover:text-black hover:border-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-2 px-3 py-3 bg-yellow-400 text-black text-sm font-black uppercase tracking-wider hover:bg-yellow-300">EXEC ▸</button>
          </div>
        </div>
      </div>
      {/* LOADOUT — yellow blocks with black borders */}
      <div className="bg-black py-10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-[10px] uppercase tracking-[0.3em] text-yellow-400 font-black mb-1 font-mono">/ LOADOUT</div>
          <h2 className="text-3xl font-black uppercase tracking-tight text-yellow-400 mb-6">PICK YOUR ARSENAL.</h2>
          <div className="grid md:grid-cols-3 gap-3">
            {[
              { brand: 'WESTERN', tag: 'PRIMARY', sub: 'PRO PLUS · MVP3 · WIDE-OUT', img: PROPLUS_IMG },
              { brand: 'MEYER',   tag: 'HEAVY-DUTY', sub: 'LOT PRO · DRIVE PRO · SUPER-V3', img: MEYER_IMG },
              { brand: 'SNOWDOGG', tag: 'VALUE TIER', sub: 'MDII · EXII · VXFII', img: SD_IMG },
            ].map((b) => (
              <div key={b.brand} className="relative bg-yellow-400 border-4 border-black p-5 overflow-hidden hover:bg-yellow-300 transition cursor-pointer group min-h-[220px]">
                <img src={b.img} alt="" className="absolute right-0 bottom-0 w-2/3"
                     style={{ filter: 'drop-shadow(-6px 6px 8px rgba(0,0,0,0.3))', transform: 'rotate(-3deg) translate(15%, 20%)' }}/>
                <div className="relative">
                  <div className="text-[9px] uppercase tracking-[0.3em] text-black font-mono font-black">{b.tag}</div>
                  <div className="text-3xl font-black uppercase tracking-tight text-black mt-1">{b.brand}</div>
                  <div className="text-[10px] text-gray-800 mt-1 font-mono">{b.sub}</div>
                  <div className="absolute bottom-0 left-0 mt-12">
                    <span className="text-xs font-black uppercase tracking-wider bg-black text-yellow-400 px-3 py-1.5">DEPLOY ▸</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}


/** L3 · ENGINEERING BLUEPRINT — cream/off-white with grid-paper background.
 *  Technical/CAD aesthetic.  Plows shown with dimensional callouts.
 *  Monospace headlines.  Looks like a build-sheet or engineering drawing.  */
function PageMockupLightTacticalBlueprint() {
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  // Subtle grid-paper bg
  const gridBg = {
    backgroundImage: 'linear-gradient(rgba(0,80,160,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(0,80,160,0.08) 1px, transparent 1px)',
    backgroundSize: '24px 24px',
  } as React.CSSProperties
  return (
    <section className="bg-stone-50 text-gray-900" style={gridBg}>
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L3 · Engineering Blueprint (build-sheet feel)</div>
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_420px] gap-8 items-center">
        <div>
          <div className="text-[10px] uppercase tracking-[0.3em] text-blue-900 font-mono font-black mb-2">SPEC SHEET · WINTER 2026 · REV 03</div>
          <h1 className="font-mono text-5xl md:text-6xl font-black uppercase leading-tight tracking-tight">
            FIND MY<br/>PLOW.<span className="text-blue-900">_</span>
          </h1>
          {/* Plow with dimensional callouts */}
          <div className="mt-6 relative">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[480px]"
                 style={{ filter: 'drop-shadow(0 8px 16px rgba(0,0,0,0.10))' }}/>
            {/* Dimensional callout lines */}
            <svg className="absolute top-0 left-0 w-full h-full pointer-events-none" viewBox="0 0 480 220">
              <line x1="20" y1="40" x2="20" y2="180" stroke="#1e3a8a" strokeWidth="0.8" strokeDasharray="4,2"/>
              <line x1="15" y1="40" x2="25" y2="40" stroke="#1e3a8a" strokeWidth="0.8"/>
              <line x1="15" y1="180" x2="25" y2="180" stroke="#1e3a8a" strokeWidth="0.8"/>
              <text x="2" y="115" fill="#1e3a8a" fontSize="9" fontFamily="monospace" fontWeight="bold">31"</text>
              <line x1="40" y1="200" x2="450" y2="200" stroke="#1e3a8a" strokeWidth="0.8" strokeDasharray="4,2"/>
              <line x1="40" y1="195" x2="40" y2="205" stroke="#1e3a8a" strokeWidth="0.8"/>
              <line x1="450" y1="195" x2="450" y2="205" stroke="#1e3a8a" strokeWidth="0.8"/>
              <text x="220" y="218" fill="#1e3a8a" fontSize="9" fontFamily="monospace" fontWeight="bold">8'-6"</text>
            </svg>
          </div>
          <p className="mt-4 text-xs font-mono text-gray-600 max-w-md uppercase tracking-wider">
            REF: WEST-MVP3MS86 · 891 lb · stainless V-plow · UltraMount 3
          </p>
        </div>
        <div className="bg-white border-2 border-blue-900 p-5">
          <div className="bg-blue-900 text-white -mx-5 -mt-5 mb-4 px-5 py-2 text-[10px] uppercase tracking-[0.3em] font-mono font-black">[ FIND_MY_PLOW.exe ]</div>
          <div className="space-y-3 font-mono">
            <div>
              <div className="text-[10px] uppercase text-gray-600 font-bold mb-1">{'> 01 INPUT TRUCK_CLASS'}</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border-2 border-gray-300 hover:border-blue-900 hover:bg-blue-50 transition">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-gray-600 font-bold mb-1">{'> 02 INPUT ROUTE_TYPE'}</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border-2 border-gray-300 hover:border-blue-900 hover:bg-blue-50 transition">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-2 px-3 py-3 bg-blue-900 text-white text-sm font-black uppercase tracking-wider hover:bg-blue-800">[ COMPILE → 3 MATCHES ]</button>
          </div>
        </div>
      </div>
      {/* LOADOUT — gear-card style with subtle blueprint borders */}
      <div className="max-w-7xl mx-auto px-6 py-8 border-t-2 border-blue-900/20">
        <div className="text-[10px] uppercase tracking-[0.3em] text-blue-900 font-mono font-black mb-1">/ AVAILABLE_BRANDS</div>
        <h2 className="font-mono text-3xl font-black uppercase tracking-tight mb-6">CATALOG.json</h2>
        <div className="grid md:grid-cols-3 gap-3">
          {[
            { brand: 'WESTERN', img: PROPLUS_IMG, count: 'n=6', sub: 'PRO PLUS · MVP3 · WIDE-OUT' },
            { brand: 'MEYER', img: MEYER_IMG, count: 'n=5', sub: 'LOT PRO · DRIVE PRO · SUPER-V3' },
            { brand: 'SNOWDOGG', img: SD_IMG, count: 'n=5', sub: 'MDII · EXII · VXFII · XPII' },
          ].map(b => (
            <div key={b.brand} className="bg-white border-2 border-blue-900 hover:border-blue-700 transition cursor-pointer group">
              <div className="border-b-2 border-blue-900 px-4 py-2 flex items-center justify-between font-mono">
                <span className="text-xs font-black uppercase">{b.brand}</span>
                <span className="text-[10px] text-blue-900">{b.count}</span>
              </div>
              <div className="p-4 h-40 flex items-center justify-center bg-stone-50">
                <img src={b.img} alt="" className="max-h-full max-w-full object-contain"/>
              </div>
              <div className="border-t-2 border-blue-900/30 px-4 py-2 font-mono text-[10px] flex items-center justify-between">
                <span className="text-gray-600">{b.sub}</span>
                <span className="text-blue-900 font-bold">VIEW ▸</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}


/** L4 · TACTICAL NEWSPRINT — warm paper white, black ink, single yellow
 *  accent.  Editorial-tabloid style with bold uppercase headlines + half-tone
 *  energy.  Reads like a Wirecutter review or NYT product feature with
 *  contractor swagger.  */
function PageMockupLightTacticalNewsprint() {
  return (
    <section className="bg-amber-50 text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L4 · Tactical Newsprint (Wirecutter / NYT review feel)</div>
      {/* Masthead */}
      <div className="border-y-4 border-double border-black bg-amber-100">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between text-xs uppercase tracking-widest font-bold">
          <span>VOL. 40 · ISS. 2026.W</span>
          <span className="font-serif italic font-bold">The Snow Plow Buyer's Brief</span>
          <span>SINCE 1986 · TITAN</span>
        </div>
      </div>
      <div className="max-w-7xl mx-auto px-6 py-10">
        {/* Headline */}
        <div className="text-center mb-8">
          <div className="inline-block bg-yellow-400 px-3 py-1 text-[10px] uppercase tracking-[0.3em] font-black mb-3">FEATURE · CONTRACTOR-GRADE</div>
          <h1 className="font-serif text-6xl md:text-8xl font-black leading-[0.9] tracking-tight max-w-5xl mx-auto">
            "FIND YOUR<br/>PLOW <span className="italic">in under a minute</span>."
          </h1>
          <p className="mt-4 font-serif text-base text-gray-700 italic max-w-2xl mx-auto">A 3-step questionnaire that picks one of 17 contractor-grade plows for your truck — from Western, Meyer, and SnowDogg.</p>
        </div>
        {/* Two-column article layout */}
        <div className="grid md:grid-cols-[1fr_2fr_1fr] gap-6 items-start">
          {/* Sidebar left - stats */}
          <aside className="border-y-2 border-black py-4">
            <div className="text-[10px] uppercase tracking-[0.3em] font-black mb-2">BY THE NUMBERS</div>
            <div className="space-y-3 font-mono">
              <div><div className="text-3xl font-black">17</div><div className="text-[10px] uppercase">PLOWS IN CATALOG</div></div>
              <div><div className="text-3xl font-black">2,114</div><div className="text-[10px] uppercase">IN STOCK NOW</div></div>
              <div><div className="text-3xl font-black">3</div><div className="text-[10px] uppercase">SNOW DAYS · NEXT 10</div></div>
              <div><div className="text-3xl font-black">40 yrs</div><div className="text-[10px] uppercase">PACIFIC NW SNOW BELT</div></div>
            </div>
          </aside>
          {/* Center article + plow image */}
          <div>
            <img src={VPLOW_IMG} alt="" className="w-full"
                 style={{ filter: 'grayscale(0.1) drop-shadow(0 12px 24px rgba(0,0,0,0.15))' }}/>
            <p className="font-serif text-base mt-4 leading-relaxed first-letter:font-black first-letter:text-6xl first-letter:float-left first-letter:mr-2 first-letter:leading-none">
              The right plow is picked by your truck — not by your wallet.  Mount and light adapter are the only vehicle-specific parts; everything else is sized by truck class and route mix.  Tell us three things and we'll show the three plows that actually fit, with the reasoning so you can see why each one made the list.
            </p>
            {/* Pull-quote */}
            <blockquote className="my-6 border-l-4 border-yellow-400 pl-4">
              <p className="font-serif italic text-2xl leading-tight">"We won't sell you a home-plow blade for a contractor route. Put one on a commercial route and it won't survive a single winter."</p>
            </blockquote>
          </div>
          {/* Sidebar right — picker */}
          <aside className="bg-white border-2 border-black p-4 sticky top-4">
            <div className="bg-black text-yellow-400 -mx-4 -mt-4 mb-3 px-4 py-2 text-[10px] uppercase tracking-[0.3em] font-black">⚡ START NOW</div>
            <div className="space-y-3 text-sm">
              <div>
                <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">YOUR TRUCK</label>
                <select className="w-full mt-1 px-2 py-1.5 border-2 border-gray-300 text-xs font-mono uppercase">
                  <option>— pick truck class —</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">YOUR ROUTE</label>
                <select className="w-full mt-1 px-2 py-1.5 border-2 border-gray-300 text-xs font-mono uppercase">
                  <option>— pick route type —</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">BUDGET</label>
                <select className="w-full mt-1 px-2 py-1.5 border-2 border-gray-300 text-xs font-mono uppercase">
                  <option>any price</option>
                </select>
              </div>
              <button className="w-full px-3 py-2.5 bg-black text-yellow-400 text-xs font-black uppercase tracking-wider hover:bg-gray-800">FIND MY PLOW ▸</button>
            </div>
          </aside>
        </div>
      </div>
    </section>
  )
}


// =========================================================================
// L1 WORKSHOP-WHITE FAMILY VARIANTS — Apr 29 2026
// Per Ben — likes L1 (Workshop White / Snap-on feel), wants more variants
// of THIS specific style.  Each variant keeps the L1 DNA: white bg,
// charcoal black structure bars, yellow safety + red warning accents,
// monospace stat readouts, uppercase headlines, slash-prefixed section
// headers.  What changes: accent intensity, layout density, type weight,
// signature motifs (barcodes, badges, dimensional callouts).
// Live at /snow-plows/page-mockups-l1.
// =========================================================================

/** L1.B · DEWALT YELLOW-FORWARD — same L1 palette but yellow becomes a
 *  PRIMARY surface, not just an accent.  Yellow header band, yellow CTA
 *  backgrounds, thick black uppercase on yellow.  Reads like a DeWalt
 *  power-tool box. */
function PageMockupL1_DeWalt() {
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  return (
    <section className="bg-white text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L1.B · DeWalt Yellow-Forward</div>
      {/* Yellow stripe banner like a power tool box */}
      <div className="bg-yellow-400 border-y-4 border-black">
        <div className="max-w-7xl mx-auto px-6 py-2 flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-widest font-black text-black">
          <span>⚠ HEAVY-DUTY · CONTRACTOR-GRADE</span>
          <span>· 2,114 IN STOCK ·</span>
          <span>WESTERN · MEYER · SNOWDOGG</span>
        </div>
      </div>
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_440px] gap-8 items-center">
        <div>
          <div className="inline-block bg-yellow-400 border-2 border-black px-3 py-1 text-[10px] uppercase tracking-[0.3em] font-black mb-3">⚡ FIND MY PLOW</div>
          <h1 className="text-6xl md:text-7xl font-black uppercase leading-[0.9] tracking-tight">
            Built<br/>
            <span className="bg-yellow-400 px-2 inline-block border-y-4 border-black">FOR THE JOB.</span>
          </h1>
          <div className="mt-6 relative inline-block">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[480px]"
                 style={{ filter: 'drop-shadow(0 14px 24px rgba(0,0,0,0.18))' }}/>
          </div>
          <p className="mt-4 text-base font-bold uppercase tracking-wide max-w-md">No home-plow garbage. Half-ton through chassis-cab.</p>
        </div>
        {/* Picker box styled like a power tool packaging panel */}
        <div className="bg-yellow-400 border-4 border-black p-1 shadow-2xl">
          <div className="bg-black text-yellow-400 px-4 py-2 text-[10px] uppercase tracking-[0.3em] font-black flex justify-between">
            <span>⚡ FIND MY PLOW</span><span>3-STEP</span>
          </div>
          <div className="bg-white p-5 space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-600 font-mono mb-1">01 / TRUCK</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border-2 border-black hover:bg-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-600 font-mono mb-1">02 / ROUTE</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase font-mono border-2 border-black hover:bg-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-2 px-3 py-3 bg-black text-yellow-400 text-sm font-black uppercase tracking-wider hover:bg-gray-900">FIND MY PLOW ▸</button>
          </div>
        </div>
      </div>
      {/* LOADOUT — yellow + black gear-card style */}
      <div className="bg-gray-100 border-y-4 border-black">
        <div className="max-w-7xl mx-auto px-6 py-10">
          <div className="text-[10px] uppercase tracking-[0.3em] font-black mb-1 font-mono">/ LOADOUT</div>
          <h2 className="text-3xl font-black uppercase tracking-tight mb-6">PICK YOUR ARSENAL.</h2>
          <div className="grid md:grid-cols-3 gap-3">
            {[
              { brand: 'WESTERN', tag: 'PRIMARY', sub: 'PRO PLUS · MVP3 · WIDE-OUT', img: PROPLUS_IMG },
              { brand: 'MEYER',   tag: 'HEAVY-DUTY', sub: 'LOT PRO · DRIVE PRO · SUPER-V3', img: MEYER_IMG },
              { brand: 'SNOWDOGG', tag: 'VALUE TIER', sub: 'MDII · EXII · VXFII · XPII', img: SD_IMG },
            ].map((b) => (
              <div key={b.brand} className="relative bg-white border-4 border-black p-5 overflow-hidden hover:shadow-2xl transition cursor-pointer group min-h-[220px]">
                <img src={b.img} alt="" className="absolute right-0 bottom-0 w-2/3"
                     style={{ filter: 'drop-shadow(-6px 6px 8px rgba(0,0,0,0.15))', transform: 'rotate(-3deg) translate(15%, 20%)' }}/>
                <div className="relative">
                  <div className="inline-block bg-yellow-400 border-2 border-black px-2 py-0.5 text-[9px] uppercase tracking-[0.3em] font-black">{b.tag}</div>
                  <div className="text-3xl font-black uppercase tracking-tight mt-2">{b.brand}</div>
                  <div className="text-[10px] text-gray-700 mt-1 font-mono">{b.sub}</div>
                  <div className="absolute bottom-0 left-0 mt-12">
                    <span className="bg-black text-yellow-400 px-3 py-1.5 text-xs font-black uppercase tracking-wider">DEPLOY ▸</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}


/** L1.C · INDUSTRIAL STENCIL — adds barcode + mil-spec stamp + "Made in
 *  USA" pills + crate-edge motifs.  Most "shipped from a warehouse"
 *  feel of the L1 family. */
function PageMockupL1_Stencil() {
  const TOP_SELLER = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  // Barcode SVG component
  const Barcode = ({ code = '7-841-2114' }: { code?: string }) => (
    <div className="inline-flex flex-col items-center">
      <svg width="120" height="32" viewBox="0 0 120 32">
        {[2,1,3,1,2,2,1,3,2,1,3,1,2,1,3,2,1,2,3,1,2,1,3,2,1,3,1,2,3,1,2,1,3,1,2,2].map((w, i, arr) => {
          const x = arr.slice(0, i).reduce((s, v) => s + v, 0)
          return i % 2 === 0 ? <rect key={i} x={x} y={0} width={w} height={32} fill="#000"/> : null
        })}
      </svg>
      <div className="text-[9px] font-mono">{code}</div>
    </div>
  )
  return (
    <section className="bg-white text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L1.C · Industrial Stencil (warehouse / crate feel)</div>
      {/* Crate edge top */}
      <div className="border-y-4 border-black bg-stone-100" style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent 0, transparent 10px, rgba(0,0,0,0.05) 10px, rgba(0,0,0,0.05) 20px)' }}>
        <div className="max-w-7xl mx-auto px-6 py-3 flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-widest font-black">
          <span>⚠ MIL-SPEC · CONTRACTOR-GRADE</span>
          <Barcode code="7-841-2114" />
          <span className="bg-yellow-400 border-2 border-black px-3 py-1">★ MADE IN USA</span>
        </div>
      </div>
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_440px] gap-8 items-start">
        <div>
          <div className="text-[10px] font-mono uppercase tracking-[0.3em] mb-2">⚙ ITEM · TT-PLOW-FINDER · v1.0</div>
          <h1 className="text-5xl md:text-7xl font-black uppercase leading-[0.9] tracking-tight" style={{ fontFamily: 'Impact, "Stencil Std", sans-serif', letterSpacing: '-0.02em' }}>
            FIND<br/>YOUR<br/>
            <span className="text-yellow-500" style={{ WebkitTextStroke: '2px black' }}>PLOW</span>
          </h1>
          <div className="mt-4 relative inline-block">
            <img src={VPLOW_IMG} alt="" className="w-full max-w-[440px]"
                 style={{ filter: 'drop-shadow(0 14px 24px rgba(0,0,0,0.18))' }}/>
            {/* Stamp overlay */}
            <div className="absolute top-2 right-2 border-4 border-red-700 text-red-700 px-2 py-1 -rotate-12 text-xs font-black uppercase font-mono opacity-80">
              ✓ APPROVED
            </div>
          </div>
          {/* Spec line */}
          <div className="mt-4 text-[10px] font-mono uppercase tracking-wider text-gray-700 grid grid-cols-3 gap-2 max-w-md">
            <div className="border-2 border-black bg-yellow-400 px-2 py-1 text-center"><strong>QTY:</strong> 2114</div>
            <div className="border-2 border-black px-2 py-1 text-center"><strong>SHIP:</strong> TODAY</div>
            <div className="border-2 border-black px-2 py-1 text-center"><strong>WARRANTY:</strong> Y</div>
          </div>
        </div>
        <div className="bg-stone-50 border-2 border-black p-5">
          <div className="bg-black text-yellow-400 -mx-5 -mt-5 mb-3 px-5 py-2 flex items-center justify-between text-[10px] uppercase tracking-[0.3em] font-black font-mono">
            <span>⚡ FIND_MY_PLOW</span><span>3-STEP</span>
          </div>
          <div className="space-y-3 font-mono">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-700 font-bold mb-1">// 01 TRUCK_CLASS</div>
              <div className="grid grid-cols-3 gap-1">
                {['MID','1500','2500','3500','4500','5500'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border-2 border-black hover:bg-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-700 font-bold mb-1">// 02 ROUTE_TYPE</div>
              <div className="grid grid-cols-2 gap-1">
                {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                  <button key={c} className="px-2 py-2 text-xs font-bold uppercase border-2 border-black hover:bg-yellow-400 transition">{c}</button>
                ))}
              </div>
            </div>
            <button className="w-full mt-2 px-3 py-3 bg-black text-yellow-400 text-sm font-black uppercase tracking-wider hover:bg-gray-900">[ EXEC → 3 MATCHES ]</button>
          </div>
        </div>
      </div>
      {/* MISSION BRIEF / spec sheet style */}
      <div className="bg-stone-50 border-y-4 border-black" style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent 0, transparent 10px, rgba(0,0,0,0.04) 10px, rgba(0,0,0,0.04) 20px)' }}>
        <div className="max-w-7xl mx-auto px-6 py-10">
          <div className="bg-white border-2 border-black">
            <div className="bg-black text-yellow-400 px-4 py-2 flex flex-wrap items-center justify-between gap-2 text-[10px] uppercase tracking-[0.3em] font-black font-mono">
              <span>/ SPEC SHEET · REV.03</span>
              <Barcode code="WEST-MVP3-86" />
              <span>P/N: WEST-MVP3MS86-EQP</span>
            </div>
            <div className="grid md:grid-cols-[1fr_2fr] gap-6 p-6 items-center">
              <div>
                <div className="inline-block bg-yellow-400 border-2 border-black px-3 py-1 text-[10px] uppercase tracking-[0.3em] font-black mb-2">★ TOP SELLER · 12MO</div>
                <h2 className="text-3xl font-black uppercase tracking-tight" style={{ fontFamily: 'Impact, sans-serif' }}>WESTERN<br/>MVP3 V-PLOW</h2>
                <div className="mt-4 grid grid-cols-2 gap-2 max-w-md">
                  {[['UNITS', '154', 'last 12mo'], ['REV', '$69.8K', 'last 12mo'], ['STOCK', '✓', 'ships now'], ['LEAD', '8 wk', 'pre-season']].map(([l, b, s]) => (
                    <div key={l as string} className="bg-stone-50 border-2 border-black px-3 py-2 font-mono">
                      <div className="text-[9px] uppercase tracking-widest text-gray-600">{l}</div>
                      <div className="text-lg font-black">{b}</div>
                      <div className="text-[9px] text-gray-500">{s}</div>
                    </div>
                  ))}
                </div>
              </div>
              <img src={TOP_SELLER} alt="" className="w-full max-w-2xl mx-auto" style={{ filter: 'drop-shadow(0 14px 28px rgba(0,0,0,0.15))' }}/>
            </div>
          </div>
        </div>
      </div>
      {/* LOADOUT crate boxes */}
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="text-[10px] uppercase tracking-[0.3em] font-black mb-1 font-mono">/ LOADOUT</div>
        <h2 className="text-3xl font-black uppercase tracking-tight mb-6" style={{ fontFamily: 'Impact, sans-serif' }}>BRANDS IN STOCK</h2>
        <div className="grid md:grid-cols-3 gap-3">
          {[
            { brand: 'WESTERN', code: 'WEST-001', img: PROPLUS_IMG, count: 'n=6' },
            { brand: 'MEYER', code: 'MYP-002', img: MEYER_IMG, count: 'n=5' },
            { brand: 'SNOWDOGG', code: 'SNOW-003', img: SD_IMG, count: 'n=5' },
          ].map(b => (
            <div key={b.brand} className="border-4 border-black bg-white" style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent 0, transparent 8px, rgba(0,0,0,0.03) 8px, rgba(0,0,0,0.03) 16px)' }}>
              <div className="bg-black text-yellow-400 px-3 py-1.5 flex items-center justify-between text-[10px] uppercase tracking-widest font-black font-mono">
                <span>{b.code}</span><span>{b.count}</span>
              </div>
              <div className="p-4 h-40 flex items-center justify-center bg-white">
                <img src={b.img} alt="" className="max-h-full max-w-full object-contain"/>
              </div>
              <div className="border-t-2 border-black px-3 py-2 flex items-center justify-between">
                <span className="text-2xl font-black uppercase tracking-tight" style={{ fontFamily: 'Impact, sans-serif' }}>{b.brand}</span>
                <span className="bg-yellow-400 border-2 border-black px-2 py-1 text-[10px] font-black uppercase">SHIP ▸</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}


/** L1.D · CATALOG CARDS — upscale tool catalog, white cards floating
 *  on a soft gray bg with subtle drop shadows.  Less aggressive black
 *  bars, more breathing room.  Like a Klein Tools or Snap-on premium
 *  catalog page. */
function PageMockupL1_Catalog() {
  const TOP_SELLER = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  return (
    <section className="bg-gray-100 text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L1.D · Catalog Cards (upscale tool catalog)</div>
      <div className="max-w-7xl mx-auto px-6 py-10">
        {/* Hero card */}
        <div className="bg-white shadow-xl rounded-sm border-l-8 border-yellow-400 grid md:grid-cols-[1fr_420px] gap-8 items-center p-8">
          <div>
            <div className="text-[10px] uppercase tracking-[0.3em] text-gray-500 font-bold mb-2">CONTRACTOR-GRADE · PACIFIC NW</div>
            <h1 className="text-5xl md:text-6xl font-black uppercase leading-[0.95] tracking-tight">FIND YOUR PLOW.</h1>
            <p className="mt-4 text-base text-gray-600 max-w-md">Tell us 3 things — truck class, route, budget.  We'll spec the right contractor-grade plow from our 17-model catalog in seconds.</p>
            <div className="mt-6">
              <img src={VPLOW_IMG} alt="" className="w-full max-w-[440px]" style={{ filter: 'drop-shadow(0 12px 24px rgba(0,0,0,0.10))' }}/>
            </div>
          </div>
          <div className="bg-gray-50 border-l-4 border-black p-5">
            <div className="text-[10px] uppercase tracking-[0.3em] text-gray-700 font-black mb-3">⚡ FIND MY PLOW</div>
            <div className="space-y-3">
              {/* Each step in its own bordered card so they don't visually
                  melt together — picked the lighter gray (gray-300) borders
                  so the cards read as grouped without screaming.  Shared
                  bg-white inside the gray-50 picker card pops the steps
                  forward visually. */}
              <div className="bg-white border border-gray-300 rounded-sm p-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500 font-bold mb-2">1. Your truck</div>
                <div className="grid grid-cols-2 gap-1.5">
                  {TRUCK_CLASSES.map(t => (
                    <button key={t.id} className="px-3 py-2 text-sm font-medium border border-gray-300 bg-white text-gray-800 hover:border-yellow-500 hover:bg-yellow-50 hover:shadow-sm transition text-left rounded-sm leading-tight">
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="bg-white border border-gray-300 rounded-sm p-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500 font-bold mb-2">2. What you plow</div>
                <div className="grid grid-cols-2 gap-1.5">
                  {ROUTE_TYPES.map(r => (
                    <button key={r.id} className="px-3 py-2 text-sm font-medium border border-gray-300 bg-white text-gray-800 hover:border-yellow-500 hover:bg-yellow-50 hover:shadow-sm transition text-left rounded-sm leading-tight">
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="bg-white border border-gray-300 rounded-sm p-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-gray-500 font-bold mb-2">3. Budget</div>
                <div className="grid grid-cols-2 gap-1.5">
                  {BUDGETS.map(b => (
                    <button key={b.id} className="px-3 py-2 text-sm font-medium border border-gray-300 bg-white text-gray-800 hover:border-yellow-500 hover:bg-yellow-50 hover:shadow-sm transition text-left rounded-sm leading-tight">
                      {b.label}
                    </button>
                  ))}
                </div>
              </div>
              <button className="w-full mt-2 px-3 py-3 bg-black text-yellow-400 text-sm font-bold uppercase tracking-wider hover:bg-gray-900 shadow-lg rounded-sm">Find My Plow →</button>
            </div>
          </div>
        </div>
        {/* Secondary band — 4 cards in a row */}
        <div className="grid md:grid-cols-4 gap-4 mt-6">
          {[
            { tag: 'TOP SELLER', title: 'WESTERN MVP3', sub: '154 sold · 12mo', img: TOP_SELLER, accent: 'border-red-600' },
            { tag: 'PRIMARY', title: 'WESTERN', sub: 'PRO PLUS · MVP3 · WIDE-OUT', img: PROPLUS_IMG, accent: 'border-red-600' },
            { tag: 'HEAVY-DUTY', title: 'MEYER', sub: 'LOT PRO · DRIVE PRO', img: MEYER_IMG, accent: 'border-emerald-600' },
            { tag: 'VALUE TIER', title: 'SNOWDOGG', sub: 'MDII · EXII · VXFII', img: SD_IMG, accent: 'border-cyan-600' },
          ].map(c => (
            <div key={c.title} className={`bg-white shadow-md rounded-sm border-l-4 ${c.accent} hover:shadow-xl transition cursor-pointer group`}>
              <div className="px-4 pt-4">
                <div className="text-[9px] uppercase tracking-[0.3em] text-gray-500 font-bold">{c.tag}</div>
                <div className="text-xl font-black uppercase tracking-tight mt-1">{c.title}</div>
                <div className="text-[10px] text-gray-500 font-mono mt-0.5">{c.sub}</div>
              </div>
              <div className="p-4 h-32 flex items-center justify-center">
                <img src={c.img} alt="" className="max-h-full max-w-full object-contain"/>
              </div>
              <div className="px-4 py-2 border-t border-gray-100 flex items-center justify-between text-xs">
                <span className="text-gray-500 font-mono">in stock</span>
                <span className="text-yellow-600 font-bold">DEPLOY ▸</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}


/** L1.E · HIGH-DENSITY WORKSHOP — info-rich grid pulling Mockup 1's bento
 *  density INTO the Workshop White language.  More cards per row, more
 *  data per card, less whitespace.  Like a contractor's wall-mounted
 *  dashboard. */
function PageMockupL1_Density() {
  const TOP_SELLER = "/static/snow-plows/skus/WEST-MVP3MS86-EQP/hero_transparent.png"
  const MEYER_IMG = "/static/snow-plows/skus/MYP-09402-EQP/hero_transparent.png"
  const SD_IMG = "/static/snow-plows/skus/SNOW-16020724-EQP/hero_transparent.png"
  const TRUCK_2500_IMG = "/static/trucks/renders/2500.png"
  return (
    <section className="bg-white text-gray-900">
      <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold px-6 pt-6 max-w-7xl mx-auto">L1.E · High-Density Workshop (info-rich grid)</div>
      {/* Header strip */}
      <div className="bg-black text-yellow-400">
        <div className="max-w-7xl mx-auto px-6 py-2 flex flex-wrap items-center justify-between gap-2 text-[10px] uppercase tracking-widest font-black font-mono">
          <span>SNOW-PLOWS · /catalog · contractor-grade</span>
          <span>QTY 2114 · STAGED · READY-SHIP</span>
          <span className="text-white">FRI · 1100 PT · OPS-NORMAL</span>
        </div>
      </div>
      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* Top row: hero wizard + stats sidebar */}
        <div className="grid md:grid-cols-[2fr_1fr] gap-3 mb-3">
          <div className="bg-gray-50 border-2 border-black p-5 grid md:grid-cols-[1fr_280px] gap-4 items-center">
            <div>
              <h1 className="text-4xl md:text-5xl font-black uppercase leading-[0.95] tracking-tight">FIND YOUR PLOW.</h1>
              <p className="text-sm text-gray-600 mt-2 font-mono uppercase tracking-wider">3-STEP · 17 PLOWS · CONTRACTOR-GRADE</p>
              <img src={VPLOW_IMG} alt="" className="w-full max-w-[280px] mt-3"
                   style={{ filter: 'drop-shadow(0 12px 20px rgba(0,0,0,0.15))' }}/>
            </div>
            <div className="bg-white border-2 border-black p-3 space-y-2">
              <div className="bg-black text-yellow-400 -mx-3 -mt-3 mb-2 px-3 py-1.5 text-[10px] uppercase tracking-[0.3em] font-black">⚡ FIND MY PLOW</div>
              <div>
                <div className="text-[9px] uppercase tracking-wider text-gray-500 font-mono mb-1">01 / TRUCK</div>
                <div className="grid grid-cols-3 gap-0.5">
                  {['MID','1500','2500','3500','4500','5500'].map(c => (
                    <button key={c} className="px-1.5 py-1.5 text-[10px] font-bold uppercase font-mono border border-black hover:bg-yellow-400 transition">{c}</button>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-[9px] uppercase tracking-wider text-gray-500 font-mono mb-1">02 / ROUTE</div>
                <div className="grid grid-cols-2 gap-0.5">
                  {['DRIVES','MIXED','LOTS','MUNI'].map(c => (
                    <button key={c} className="px-1.5 py-1.5 text-[10px] font-bold uppercase font-mono border border-black hover:bg-yellow-400 transition">{c}</button>
                  ))}
                </div>
              </div>
              <button className="w-full mt-1 px-3 py-2 bg-black text-yellow-400 text-xs font-black uppercase tracking-wider">EXEC ▸</button>
            </div>
          </div>
          {/* Stat tower */}
          <div className="grid grid-rows-4 gap-3">
            {[['IN STOCK', '2114', 'ships today', 'bg-yellow-400'],
              ['SNOW DAYS', '3', 'next 10 · spokane', 'bg-cyan-200'],
              ['ALERTS', '24', 'WinterWatch subs', 'bg-emerald-200'],
              ['PRE-SEASON', '1 wk', 'free freight ends', 'bg-red-200']].map(([l, b, s, bg]) => (
              <div key={l} className={`${bg} border-2 border-black p-3 font-mono`}>
                <div className="text-[10px] uppercase tracking-widest font-black">{l}</div>
                <div className="text-3xl font-black leading-none mt-1">{b}</div>
                <div className="text-[10px] mt-0.5 opacity-80">{s}</div>
              </div>
            ))}
          </div>
        </div>
        {/* Brand grid + configurator */}
        <div className="grid md:grid-cols-12 gap-3 mb-3">
          {[
            { brand: 'WESTERN', img: PROPLUS_IMG, span: 4, accent: 'border-l-red-700' },
            { brand: 'MEYER', img: MEYER_IMG, span: 4, accent: 'border-l-emerald-700' },
            { brand: 'SNOWDOGG', img: SD_IMG, span: 4, accent: 'border-l-cyan-700' },
          ].map(b => (
            <div key={b.brand} className={`md:col-span-${b.span} relative bg-gray-50 border-2 border-black border-l-8 ${b.accent} p-4 overflow-hidden hover:bg-white transition cursor-pointer min-h-[180px]`}>
              <img src={b.img} alt="" className="absolute right-0 bottom-0 w-2/3"
                   style={{ filter: 'drop-shadow(-4px 4px 8px rgba(0,0,0,0.15))', transform: 'rotate(-3deg) translate(15%, 25%)' }}/>
              <div className="relative">
                <div className="text-[9px] uppercase tracking-[0.3em] font-mono font-black">/ BRAND</div>
                <div className="text-2xl font-black uppercase tracking-tight mt-1">{b.brand}</div>
                <div className="absolute bottom-0 left-0 mt-12">
                  <span className="bg-black text-yellow-400 px-2 py-1 text-[10px] font-black uppercase">DEPLOY ▸</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        {/* Configurator + WinterWatch + Top seller row */}
        <div className="grid md:grid-cols-12 gap-3">
          {/* Configurator */}
          <div className="md:col-span-5 relative bg-gray-50 border-2 border-black p-4 overflow-hidden min-h-[200px]">
            <img src={TRUCK_2500_IMG} alt="" className="absolute inset-0 w-full h-full object-cover opacity-40"/>
            <img src={VPLOW_IMG} alt="" className="absolute bottom-0 left-1/2 w-1/2 max-w-[200px]"
                 style={{ transform: 'translate(-50%, 10%)', filter: 'drop-shadow(0 12px 16px rgba(0,0,0,0.4))' }}/>
            <div className="relative z-10">
              <div className="text-[9px] uppercase tracking-[0.3em] font-mono font-black">/ FITMENT CHECK</div>
              <div className="text-2xl font-black uppercase tracking-tight">VEHICLE / PAYLOAD MATCH.</div>
              <button className="mt-3 bg-black text-yellow-400 px-3 py-1.5 text-[10px] font-black uppercase tracking-wider">RUN CHECK ▸</button>
            </div>
          </div>
          {/* Top seller card */}
          <div className="md:col-span-4 bg-white border-2 border-black overflow-hidden min-h-[200px]">
            <div className="bg-black text-yellow-400 px-3 py-1 text-[10px] uppercase tracking-widest font-black font-mono flex justify-between">
              <span>★ TOP SELLER · 12MO</span>
              <span>WEST-MVP3</span>
            </div>
            <div className="p-3 flex items-center gap-3">
              <img src={TOP_SELLER} alt="" className="w-2/5 object-contain"/>
              <div>
                <div className="text-base font-black uppercase">WESTERN MVP3</div>
                <div className="text-[10px] text-gray-500 font-mono uppercase">154 sold · 12mo</div>
                <div className="text-[10px] text-gray-500 font-mono uppercase">$69,817 revenue</div>
                <button className="mt-2 bg-yellow-400 border border-black px-2 py-1 text-[9px] font-black uppercase">QUOTE ▸</button>
              </div>
            </div>
          </div>
          {/* WinterWatch + Pre-season stack */}
          <div className="md:col-span-3 grid grid-rows-2 gap-3">
            <div className="bg-cyan-100 border-2 border-black p-3">
              <div className="text-[9px] uppercase tracking-[0.3em] font-mono font-black">/ WINTERWATCH</div>
              <div className="text-sm font-black uppercase mt-1">SNOW IN YOUR ZIP?</div>
              <div className="text-[10px] mt-0.5 font-mono">FREE EMAIL ALERTS</div>
              <button className="mt-2 bg-cyan-700 text-white px-2 py-1 text-[10px] font-black uppercase tracking-wider">ENLIST ▸</button>
            </div>
            <div className="bg-yellow-100 border-2 border-black p-3">
              <div className="text-[9px] uppercase tracking-[0.3em] font-mono font-black">/ PRE-SEASON</div>
              <div className="text-sm font-black uppercase mt-1">FREE FREIGHT</div>
              <div className="text-[10px] mt-0.5 font-mono">CLOSES BEFORE 1ST SNOW</div>
              <button className="mt-2 bg-black text-yellow-400 px-2 py-1 text-[10px] font-black uppercase tracking-wider">LOCK IN ▸</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}


/** Preview page for the L1 Workshop-White family.  Shows L1 base +
 *  4 variants. */
function L1FamilyMockupsPreview() {
  return (
    <div className="bg-gray-100 min-h-screen pb-16">
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <Link to="/snow-plows/page-mockups-light" className="text-xs text-blue-300 hover:text-white">← back to all 4 light tactical variants</Link>
          <h1 className="text-2xl font-extrabold mt-2">L1 Workshop-White family — 5 variants</h1>
          <p className="text-sm text-blue-200 mt-1">All 5 share the L1 DNA: white background, charcoal black structure bars, yellow safety + red warning accents, monospace stats, uppercase headlines.  What changes between them: accent intensity, type weight, layout density, and signature motifs.</p>
        </div>
      </div>
      {[
        { id: 'L1.A', title: 'Workshop White (base) — Snap-on / DeWalt feel',
          tradeoffs: 'The original L1 — pure white bg, charcoal bars, yellow safety accents.  Closest 1:1 of the dark tactical with the bg flipped.  Most familiar to anyone who\'s shopped at a pro-tool store.',
          el: <PageMockupLightTacticalWorkshop /> },
        { id: 'L1.B', title: 'DeWalt Yellow-Forward — power-tool box feel',
          tradeoffs: 'Yellow becomes a PRIMARY surface, not just an accent.  Yellow header band, yellow CTA backgrounds, thick black uppercase on yellow.  Reads like a DeWalt power-tool box on a pegboard.  Boldest of the family.',
          el: <PageMockupL1_DeWalt /> },
        { id: 'L1.C', title: 'Industrial Stencil — warehouse / crate feel',
          tradeoffs: 'Adds barcode strips, "MADE IN USA" pills, "✓ APPROVED" stamps, mil-spec part numbers, crate-edge diagonal hatching.  Most "shipped from a warehouse" personality of the family.  Uses Impact for headlines (stencil-like).  For the contractor who appreciates hardware-store grit.',
          el: <PageMockupL1_Stencil /> },
        { id: 'L1.D', title: 'Catalog Cards — upscale tool catalog feel',
          tradeoffs: 'White cards floating on a soft gray bg with subtle drop shadows.  Less aggressive black bars, more breathing room, narrower color accents (left-border stripes per brand).  Like a Klein Tools or Snap-on premium catalog page.  Most "premium" / least "industrial."',
          el: <PageMockupL1_Catalog /> },
        { id: 'L1.E', title: 'High-Density Workshop — info-rich dashboard feel',
          tradeoffs: 'Pulls Mockup 1\'s bento density INTO the Workshop White language.  Header status strip, stat tower sidebar (in stock / snow days / alerts / pre-season countdown), brand grid, configurator + top seller + WinterWatch in a 12-col grid.  Like a contractor\'s wall-mounted dashboard.  For pros who want every signal visible above the fold.',
          el: <PageMockupL1_Density /> },
      ].map(m => (
        <section key={m.id} className="border-t-4 border-yellow-400">
          <div className="bg-white border-b">
            <div className="max-w-7xl mx-auto px-6 py-4">
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Variant {m.id}</div>
              <h2 className="text-base font-bold text-gray-900">{m.title}</h2>
              <p className="text-xs text-gray-600 mt-1 max-w-3xl">{m.tradeoffs}</p>
            </div>
          </div>
          {m.el}
        </section>
      ))}
    </div>
  )
}


/** Preview page for the 4 light-tactical variants.  Wired at
 *  /snow-plows/page-mockups-light. */
function LightTacticalMockupsPreview() {
  return (
    <div className="bg-gray-100 min-h-screen pb-16">
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <Link to="/snow-plows/page-mockups" className="text-xs text-blue-300 hover:text-white">← back to all 6 page directions</Link>
          <h1 className="text-2xl font-extrabold mt-2">Light Tactical — 4 variants</h1>
          <p className="text-sm text-blue-200 mt-1">Same tactical voice as Mockup 2 (uppercase, monospace stats, slash headers, "DEPLOY ▸" CTAs) but on a white/light background instead of dark.  Per Ben's pick — the contractor identity stays, the canvas brightens.</p>
        </div>
      </div>
      {[
        { id: 'L1', title: 'Workshop White — Snap-on / DeWalt feel', tradeoffs: 'Pure white background, charcoal black structure bars, yellow safety accents.  Looks like a serious pro-tool catalog.  Most readable of the four; closest match to the dark tactical mockup with just the bg flipped.', el: <PageMockupLightTacticalWorkshop /> },
        { id: 'L2', title: 'Hi-Vis Safety — construction signage feel', tradeoffs: 'Yellow + white dominant, black structure bars, oversized headlines with a black highlight on key words.  Looks like a hi-vis safety vest or roadside signage — bold, scannable, immediately reads as outdoor work.  Most distinctive personality of the four.', el: <PageMockupLightTacticalHiVis /> },
        { id: 'L3', title: 'Engineering Blueprint — build-sheet / CAD feel', tradeoffs: 'Cream background with subtle blueprint grid, monospace headlines, dimensional callout overlays on plow imagery (with actual SVG dimension lines), [ COMPILE ] -style CTAs.  Reads like a technical drawing.  For the spec-driven contractor who likes data.', el: <PageMockupLightTacticalBlueprint /> },
        { id: 'L4', title: 'Tactical Newsprint — Wirecutter / NYT feature feel', tradeoffs: 'Warm paper-white background, serif headlines with italic accents, sidebar layout with a sticky picker on the right and stats on the left.  Reads like a magazine review or NYT product feature.  Most "considered purchase" of the four; best when we want to feel premium without losing the contractor voice.', el: <PageMockupLightTacticalNewsprint /> },
      ].map(m => (
        <section key={m.id} className="border-t-4 border-yellow-400">
          <div className="bg-white border-b">
            <div className="max-w-7xl mx-auto px-6 py-4">
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Variant {m.id}</div>
              <h2 className="text-base font-bold text-gray-900">{m.title}</h2>
              <p className="text-xs text-gray-600 mt-1 max-w-3xl">{m.tradeoffs}</p>
            </div>
          </div>
          {m.el}
        </section>
      ))}
    </div>
  )
}


/** Preview page — stacks all 6 page-direction mockups with intro + tradeoffs.
 *  Wired at /snow-plows/page-mockups.  Doesn't conflict with the wizard
 *  preview at /snow-plows/wizard-preview. */
function PageMockupsPreview() {
  return (
    <div className="bg-gray-100 min-h-screen pb-16">
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <Link to="/snow-plows" className="text-xs text-blue-300 hover:text-white">← back to /snow-plows</Link>
          <h1 className="text-2xl font-extrabold mt-2">Snow Plows landing — 6 page-level directions</h1>
          <p className="text-sm text-blue-200 mt-1">Each mockup is one design language for the whole page.  These show the hero + a representative second section so you can see the SYSTEM, not just the hero.  Pick one, or mix-and-match — and I'll wire the winner into the live page.</p>
        </div>
      </div>
      {[
        { id: 1, title: 'Bento Box Modern', tradeoffs: 'Apple-watch-face vibes — every important section is a card, all visible above the fold in a single composition.  Premium "everything-at-a-glance" feel.  Modern (this look has been hot since 2024).  Risk: dense; first-time browsers may not know where to look first.', el: <PageMockupBento /> },
        { id: 2, title: 'Dark Tactical',     tradeoffs: 'Black background, neon-yellow + safety-red accents, thick uppercase typography.  Reads like a tactical/gear site (5.11 Tactical, Leatherman).  For the serious contractor identity.  Risk: aggressive — may turn off retail/light-commercial buyers.', el: <PageMockupTactical /> },
        { id: 3, title: 'Editorial Magazine', tradeoffs: 'Cream background, serif headlines, pull-quote layout, generous whitespace.  Treats the buying decision like a feature article.  Premium, considered, understated.  Risk: slow — feels like reading instead of shopping.  Best when paired with a sticky picker.', el: <PageMockupEditorial /> },
        { id: 4, title: 'Stripe-style Minimal', tradeoffs: 'Pure white, careful sans-serif, big bold sentence H1, gradient accents.  Looks like Stripe / Linear / Vercel.  Says "this is a serious software company that also sells snow plows."  Risk: too generic — doesn\'t feel snow-plow specific.', el: <PageMockupMinimal /> },
        { id: 5, title: 'Scrollytelling Journey', tradeoffs: 'Guided 3-step narrative.  Each scroll-section pins and reveals the next step (truck → route → budget → results).  Inspired by Apple product pages.  Most ambitious; needs scroll-pinned animations.  Highest-conversion if executed well, but heaviest implementation lift.', el: <PageMockupScrolly /> },
        { id: 6, title: 'Pro Dashboard',      tradeoffs: 'Compact, info-dense, almost ERP-like.  Live data widgets — in-stock, lead times, weather, top sellers — in a Bloomberg Terminal grid.  Monospace accents.  For pros who hate marketing fluff.  Risk: cold — turns off first-time / consumer buyers.', el: <PageMockupDashboard /> },
      ].map(m => (
        <section key={m.id} className="border-t-4 border-yellow-400">
          <div className="bg-white border-b">
            <div className="max-w-7xl mx-auto px-6 py-4">
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Direction {m.id}</div>
              <h2 className="text-base font-bold text-gray-900">{m.title}</h2>
              <p className="text-xs text-gray-600 mt-1 max-w-3xl">{m.tradeoffs}</p>
            </div>
          </div>
          {m.el}
        </section>
      ))}
    </div>
  )
}


// =========================================================================
// MOCKUP PREVIEW — kept at /snow-plows/wizard-preview for design reference
// after Ben picked E1 and we shipped it as the live hero (commit 24fe022).
// The 7 components below are STATIC mockups; the live recommender lives in
// PlowFinderWizard below.
// =========================================================================

// These four variants live on the preview route /snow-plows/wizard-preview
// for him to compare side-by-side; once he picks one, we wire it into the
// real SnowPlowsLanding flow (and delete the others).
//
// Each mockup is a STATIC visual — clicking the picker tiles doesn't fire
// the recommender, just toggles selection state to demonstrate the UX.  The
// recommender is wired in PlowFinderWizard below; we'll graft the chosen
// shell onto that engine after Ben picks.
// =========================================================================

/** Mockup A — slim inline picker BAKED INTO the yellow pre-season banner.
 *  Smallest visual footprint, treats Find-My-Plow as a peer of the pricing
 *  + phone CTAs.  Best for users who already know what's going on; weakest
 *  for first-time browsers because the picker only fires after all 3
 *  dropdowns are touched. */
function WizardMockupA() {
  const [t, setT] = useState(""); const [r, setR] = useState(""); const [b, setB] = useState("any")
  const ready = t && r && b
  return (
    <section className="bg-gradient-to-r from-yellow-400 via-yellow-300 to-yellow-400 text-gray-900 border-b-4 border-red-700">
      <div className="max-w-7xl mx-auto px-6 py-4 grid md:grid-cols-[auto_1fr_auto] gap-4 items-center">
        <div className="flex items-center gap-3">
          <span className="text-3xl">⚡</span>
          <div>
            <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Find My Plow — instant match</div>
            <div className="text-base md:text-lg font-extrabold leading-tight">Tell us 3 things, we'll spec your plow.</div>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <select value={t} onChange={e => setT(e.target.value)} className="px-3 py-2 rounded text-sm border-2 border-gray-900/20 bg-white">
            <option value="">Your truck...</option>
            {TRUCK_CLASSES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
          <select value={r} onChange={e => setR(e.target.value)} className="px-3 py-2 rounded text-sm border-2 border-gray-900/20 bg-white">
            <option value="">What you plow...</option>
            {ROUTE_TYPES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
          <select value={b} onChange={e => setB(e.target.value)} className="px-3 py-2 rounded text-sm border-2 border-gray-900/20 bg-white">
            {BUDGETS.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
        </div>
        <button disabled={!ready} className="px-4 py-2 bg-blue-950 hover:bg-blue-900 disabled:bg-gray-400 text-white text-sm font-extrabold rounded whitespace-nowrap">
          {ready ? 'Find my plow →' : 'Pick all 3'}
        </button>
      </div>
    </section>
  )
}

/** Mockup B — keep the yellow pre-season banner as-is, add a NEW dedicated
 *  dark-blue wizard band immediately below it.  Wizard uses the existing
 *  3-column tile picker (not dropdowns), big and tappable, screams "this is
 *  the primary tool."  Pushes the hero down ~250px but the tradeoff is the
 *  picker is the FIRST interactive thing you see. */
function WizardMockupB() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  return (
    <section className="bg-gradient-to-br from-blue-950 via-blue-900 to-slate-900 text-white border-b-4 border-yellow-400">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-end justify-between mb-4 flex-wrap gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">⚡ Find My Plow</div>
            <h2 className="text-xl font-extrabold">Tell us 3 things — we'll recommend the right plow in seconds.</h2>
          </div>
          <div className="text-[11px] text-blue-200">No VIN required.  17-model curated catalog.  Built on Nelson's actual snow-belt sales.</div>
        </div>
        <div className="grid md:grid-cols-3 gap-3">
          {[{label:'1. Your truck', items:TRUCK_CLASSES, sel:t, set:setT},
            {label:'2. What you plow', items:ROUTE_TYPES, sel:r, set:setR},
            {label:'3. Budget', items:BUDGETS as any, sel:b, set:setB}].map((col, i) => (
            <div key={i}>
              <div className="text-[10px] uppercase tracking-wider text-blue-300 font-bold mb-2">{col.label}</div>
              <div className="grid grid-cols-2 gap-1">
                {col.items.slice(0, 6).map((x: any) => (
                  <button key={x.id} onClick={() => col.set(x.id)}
                    className={`px-2 py-1.5 rounded text-[11px] border transition text-left ${
                      col.sel === x.id ? 'bg-yellow-400 text-gray-900 border-yellow-400 font-bold' : 'border-white/20 hover:border-white/60 text-blue-100'
                    }`}>{x.label}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

/** Mockup C — wizard REPLACES the current dark hero entirely.  Pre-season
 *  banner stays.  Hero band becomes the wizard with a big "Snow Plows"
 *  H1 + the 3 pickers in a single fluid layout.  Most committed look,
 *  zero scroll to find the tool, but you lose the "Contractor-grade /
 *  Pacific Northwest's snow plow HQ" copy that did brand-identity work. */
function WizardMockupC() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  const ready = t && r && b
  return (
    <section className="relative bg-gradient-to-br from-blue-950 via-gray-900 to-black text-white overflow-hidden">
      <div className="absolute inset-0 opacity-15" style={{ backgroundImage: 'radial-gradient(circle at 25% 30%, white, transparent 50%), radial-gradient(circle at 80% 70%, white, transparent 60%)' }} />
      <div className="relative max-w-7xl mx-auto px-6 py-12">
        <div className="text-xs uppercase tracking-widest text-blue-300 font-bold mb-2">Pacific Northwest's Snow Plow HQ ⚡ Western · Meyer · SnowDogg</div>
        <h1 className="text-3xl md:text-4xl font-extrabold leading-tight mb-2">Find my plow.</h1>
        <p className="text-sm text-blue-200 mb-6 max-w-2xl">Pick your truck, route, and budget — we'll show you the 3 best contractor-grade plows from our catalog, and let you see them on a render of your truck.</p>
        <div className="grid md:grid-cols-3 gap-4 mb-4">
          {[{label:'Your truck', items:TRUCK_CLASSES, sel:t, set:setT},
            {label:'What you plow', items:ROUTE_TYPES, sel:r, set:setR},
            {label:'Budget', items:BUDGETS as any, sel:b, set:setB}].map((col, i) => (
            <div key={i} className="bg-white/5 rounded-lg p-3 border border-white/10">
              <div className="text-[10px] uppercase tracking-wider text-blue-300 font-bold mb-2">{col.label}</div>
              <div className="space-y-1">
                {col.items.slice(0, 6).map((x: any) => (
                  <button key={x.id} onClick={() => col.set(x.id)}
                    className={`w-full px-2 py-1.5 rounded text-xs border transition text-left ${
                      col.sel === x.id ? 'bg-yellow-400 text-gray-900 border-yellow-400 font-bold' : 'border-white/20 hover:border-white/60 text-blue-100'
                    }`}>{x.label}</button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-3 items-center">
          <button disabled={!ready} className="px-6 py-3 bg-yellow-400 hover:bg-yellow-300 disabled:bg-gray-500 disabled:text-gray-300 text-gray-900 text-sm font-extrabold rounded">
            {ready ? 'Show my matches →' : 'Pick all 3 to continue'}
          </button>
          <a href="mailto:sales@nelsontruck.com?subject=Snow%20Plow%20Quote" className="text-sm text-blue-200 hover:text-white">Or email us a custom quote →</a>
        </div>
      </div>
    </section>
  )
}

/** Mockup D — split hero: brand copy on the LEFT, compact wizard form on
 *  the RIGHT, both visible above the fold.  Compromise between B and C —
 *  keeps the "Pacific NW snow plow HQ" identity copy while putting the
 *  picker on screen.  Best for desktop; on mobile the wizard sits below
 *  the copy. */
function WizardMockupD() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  return (
    <section className="relative bg-gradient-to-br from-blue-950 via-gray-900 to-black text-white overflow-hidden">
      <div className="absolute inset-0 opacity-15" style={{ backgroundImage: 'radial-gradient(circle at 30% 20%, white, transparent 50%)' }} />
      <div className="relative max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_400px] gap-8 items-start">
        <div>
          <div className="text-xs uppercase tracking-widest text-blue-300 font-bold mb-2">Pacific Northwest's Snow Plow HQ</div>
          <h1 className="text-4xl md:text-5xl font-extrabold leading-tight mb-3">Contractor-grade snow plows.</h1>
          <p className="text-base text-gray-300 mb-3 max-w-xl">Factory-authorized for Western, Meyer, and Buyers SnowDogg — the contractor-grade lineups our customers actually run all winter.</p>
          <p className="text-sm text-blue-200 mb-3 max-w-xl">
            <strong>Try the picker →</strong> 17 plows, ranked for your truck class + route mix + budget.  No VIN, no email up front.
          </p>
        </div>
        <div className="bg-white text-gray-900 rounded-lg p-4 shadow-2xl">
          <div className="text-[10px] uppercase tracking-widest text-blue-700 font-extrabold mb-2">⚡ Find My Plow</div>
          <div className="space-y-3">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">Your truck</div>
              <select value={t} onChange={e => setT(e.target.value)} className="w-full px-3 py-2 rounded text-sm border-2 border-gray-200 focus:border-blue-700 outline-none">
                <option value="">— pick truck class —</option>
                {TRUCK_CLASSES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">What you plow</div>
              <select value={r} onChange={e => setR(e.target.value)} className="w-full px-3 py-2 rounded text-sm border-2 border-gray-200 focus:border-blue-700 outline-none">
                <option value="">— pick route type —</option>
                {ROUTE_TYPES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">Budget</div>
              <select value={b} onChange={e => setB(e.target.value)} className="w-full px-3 py-2 rounded text-sm border-2 border-gray-200 focus:border-blue-700 outline-none">
                {BUDGETS.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <button disabled={!t || !r} className="w-full px-3 py-2.5 bg-red-700 hover:bg-red-800 disabled:bg-gray-300 text-white text-sm font-extrabold rounded">
              {t && r ? 'Show my 3 best matches →' : 'Pick truck + route'}
            </button>
            <p className="text-[10px] text-gray-500 text-center">Free.  No email required to see results.</p>
          </div>
        </div>
      </div>
    </section>
  )
}

// =========================================================================
// V-plow / white-bg / split-layout variants — Apr 29 2026 round 2
//
// Ben's feedback: "I like the idea of C, but with a white background and
// more like a layout in D.  I would go ahead and put a V-plow on the left
// side of the banner for now."
//
// All three variants:
//   - White / off-white background (light, approachable)
//   - Split: V-plow image on the LEFT, wizard form on the RIGHT
//   - Wizard IS the hero (no separate dark band above it)
// They differ in: how the plow sits in the frame, how the form is laid out,
// and the accent color story.
// =========================================================================


/** Variant E1 — Plow full-bleed on the left edge, oversized.  Wizard uses
 *  the tile-picker (matches the existing wizard's UX).  Nelson-red accent.
 *  Cleanest match to "make the wizard the hero."  */
function WizardMockupE1() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  const ready = t && r && b
  return (
    <section className="relative bg-gradient-to-br from-white via-slate-50 to-slate-100 border-b-4 border-red-700 overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1fr_460px] gap-8 items-center">
        {/* Left: oversized plow + tagline */}
        <div className="relative">
          <img src={VPLOW_IMG} alt="V-plow" className="w-full max-w-[640px] h-auto"
               style={{ filter: 'drop-shadow(0 12px 24px rgba(0,0,0,0.18))' }}/>
          <div className="mt-2 md:mt-4">
            <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Pacific Northwest's Snow Plow HQ</div>
            <h1 className="text-3xl md:text-4xl font-extrabold text-gray-900 leading-tight">Find my plow.</h1>
            <p className="text-sm text-gray-600 mt-2 max-w-md">Pick your truck, route, and budget. We'll show you the 3 best contractor-grade plows from our 17-model catalog — ranked for your truck's class.</p>
          </div>
        </div>
        {/* Right: tile-picker form */}
        <div className="bg-white rounded-xl shadow-xl border border-gray-200 p-5">
          <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold mb-3">⚡ Find My Plow</div>
          <div className="space-y-3">
            {[{label:'1. Your truck', items:TRUCK_CLASSES, sel:t, set:setT},
              {label:'2. What you plow', items:ROUTE_TYPES, sel:r, set:setR},
              {label:'3. Budget', items:BUDGETS as any, sel:b, set:setB}].map((col, i) => (
              <div key={i}>
                <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">{col.label}</div>
                <div className="grid grid-cols-2 gap-1">
                  {col.items.slice(0, 6).map((x: any) => (
                    <button key={x.id} onClick={() => col.set(x.id)}
                      className={`px-2 py-1.5 rounded text-[11px] border transition text-left ${
                        col.sel === x.id ? 'bg-red-700 text-white border-red-700 font-bold' : 'border-gray-200 hover:border-red-700 text-gray-700'
                      }`}>{x.label}</button>
                  ))}
                </div>
              </div>
            ))}
            <button disabled={!ready} className="w-full mt-2 px-4 py-2.5 bg-red-700 hover:bg-red-800 disabled:bg-gray-300 text-white text-sm font-extrabold rounded">
              {ready ? 'Show my matches →' : 'Pick all 3'}
            </button>
            <p className="text-[10px] text-gray-500 text-center">Free.  No email required to see results.</p>
          </div>
        </div>
      </div>
    </section>
  )
}

/** Variant E2 — Plow centered with a soft glow.  Wizard uses dropdowns
 *  (like Mockup A) — most compact form.  Subtle blue accent for the
 *  "answer / data" feeling. */
function WizardMockupE2() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  const ready = t && r && b
  return (
    <section className="relative bg-white border-b border-gray-200 overflow-hidden">
      {/* Soft radial glow behind the plow */}
      <div className="absolute left-0 top-0 w-1/2 h-full pointer-events-none"
           style={{ background: 'radial-gradient(circle at 30% 50%, rgba(30,64,175,0.08), transparent 60%)' }}/>
      <div className="relative max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-2 gap-8 items-center">
        {/* Left: plow centered */}
        <div className="text-center md:text-left">
          <img src={VPLOW_IMG} alt="V-plow" className="w-full max-w-[520px] h-auto mx-auto md:mx-0"
               style={{ filter: 'drop-shadow(0 8px 24px rgba(30,64,175,0.20))' }}/>
        </div>
        {/* Right: copy + compact dropdown wizard */}
        <div>
          <div className="text-[10px] uppercase tracking-widest text-blue-700 font-extrabold">Pacific NW Snow Plow HQ</div>
          <h1 className="text-3xl md:text-4xl font-extrabold text-gray-900 leading-tight mb-1">Find my plow.</h1>
          <p className="text-sm text-gray-600 mb-5">Tell us 3 things — we'll spec the right contractor-grade plow for your truck.</p>
          <div className="bg-slate-50 border border-slate-200 rounded-lg p-4 space-y-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Your truck</label>
              <select value={t} onChange={e => setT(e.target.value)} className="w-full mt-1 px-3 py-2 rounded text-sm border-2 border-gray-200 bg-white focus:border-blue-700 outline-none">
                <option value="">— pick truck class —</option>
                {TRUCK_CLASSES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">What you plow</label>
              <select value={r} onChange={e => setR(e.target.value)} className="w-full mt-1 px-3 py-2 rounded text-sm border-2 border-gray-200 bg-white focus:border-blue-700 outline-none">
                <option value="">— pick route type —</option>
                {ROUTE_TYPES.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Budget</label>
              <select value={b} onChange={e => setB(e.target.value)} className="w-full mt-1 px-3 py-2 rounded text-sm border-2 border-gray-200 bg-white focus:border-blue-700 outline-none">
                {BUDGETS.map(x => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
            </div>
            <button disabled={!ready} className="w-full px-4 py-2.5 bg-blue-700 hover:bg-blue-800 disabled:bg-gray-300 text-white text-sm font-extrabold rounded">
              {ready ? 'Show my matches →' : 'Pick all 3'}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

/** Variant E3 — Plow takes a 55% left column with a slight tilt for
 *  drama.  Wizard on the right uses tile-picker like E1 but more
 *  compactly stacked vertically.  Yellow + red accents (Nelson brand
 *  colors).  Most "shopping page" energy. */
function WizardMockupE3() {
  const [t, setT] = useState<string>(""); const [r, setR] = useState<string>(""); const [b, setB] = useState<string>("any")
  const ready = t && r && b
  return (
    <section className="relative bg-gradient-to-br from-amber-50 via-white to-white border-b-4 border-yellow-400 overflow-hidden">
      <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-[1.1fr_1fr] gap-6 items-center">
        {/* Left: plow with slight rotation for visual interest */}
        <div className="relative">
          <div className="absolute -inset-6 bg-gradient-to-br from-yellow-200/40 via-transparent to-transparent rounded-3xl pointer-events-none"/>
          <img src={VPLOW_IMG} alt="V-plow" className="relative w-full max-w-[600px] h-auto"
               style={{ filter: 'drop-shadow(0 14px 28px rgba(0,0,0,0.18))', transform: 'rotate(-2deg)' }}/>
          <div className="mt-3">
            <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Pacific NW Snow Plow HQ · Western · Meyer · SnowDogg</div>
            <h1 className="text-3xl md:text-4xl font-extrabold text-gray-900 leading-tight">Find my plow.</h1>
          </div>
        </div>
        {/* Right: wizard with tile-picker, narrower, more shopping-page energy */}
        <div className="bg-white rounded-lg shadow-2xl border border-yellow-200 p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">⚡ 3 questions, 3 picks</div>
            <span className="text-[9px] text-gray-500">17 plows in catalog</span>
          </div>
          <div className="space-y-3">
            {[{label:'Your truck', items:TRUCK_CLASSES, sel:t, set:setT},
              {label:'What you plow', items:ROUTE_TYPES, sel:r, set:setR},
              {label:'Budget', items:BUDGETS as any, sel:b, set:setB}].map((col, i) => (
              <div key={i}>
                <div className="text-[10px] uppercase tracking-wider text-gray-500 font-bold mb-1">{col.label}</div>
                <div className="flex flex-wrap gap-1">
                  {col.items.slice(0, 6).map((x: any) => (
                    <button key={x.id} onClick={() => col.set(x.id)}
                      className={`px-2.5 py-1 rounded-full text-[11px] border transition ${
                        col.sel === x.id ? 'bg-yellow-400 text-gray-900 border-yellow-400 font-bold' : 'border-gray-300 hover:border-yellow-500 text-gray-700'
                      }`}>{x.label}</button>
                  ))}
                </div>
              </div>
            ))}
            <button disabled={!ready} className="w-full mt-2 px-4 py-3 bg-red-700 hover:bg-red-800 disabled:bg-gray-300 text-white text-sm font-extrabold rounded">
              {ready ? '✨ Find my matches →' : 'Pick all 3 to find your plow'}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}


/** Preview page — renders all 4 mockups stacked with labels so Ben can
 *  scroll through and pick.  Wired at /snow-plows/wizard-preview. */
function WizardMockupsPreview() {
  return (
    <div className="bg-gray-100 min-h-screen pb-16">
      <div className="bg-blue-950 text-white">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <Link to="/snow-plows" className="text-xs text-blue-300 hover:text-white">← back to /snow-plows</Link>
          <h1 className="text-2xl font-extrabold mt-2">Find My Plow — placement mockups</h1>
          <p className="text-sm text-blue-200 mt-1">4 ways to surface the picker at the top of /snow-plows.  Scroll through, tell me which you want and I'll wire it into the real flow.  (Pickers are interactive but don't fire the recommender on this preview.)</p>
        </div>
      </div>

      {[
        { id: 'E1', title: 'Mockup E1 — V-plow + tile picker + Nelson red accent (round 2)',
          body: 'Round 2: white background per your feedback, split layout like D, V-plow image as the visual on the left.  Wizard uses the tile-picker UX (matches the existing wizard further down the page) with Nelson red as the accent.  Cleanest match to "wizard IS the hero, but on white instead of dark."',
          el: <WizardMockupE1 /> },
        { id: 'E2', title: 'Mockup E2 — V-plow with soft glow + dropdown form + blue accent (round 2)',
          body: 'Round 2: same brief, but the wizard uses dropdowns instead of tiles (most compact form), and blue accents for a "data / forecast" feel.  Plow is centered with a subtle blue glow.  Lightest visual weight.',
          el: <WizardMockupE2 /> },
        { id: 'E3', title: 'Mockup E3 — V-plow with tilt + pill-style tiles + Nelson yellow + red (round 2)',
          body: 'Round 2: same brief, but with more "shopping page" energy.  Plow has a slight rotation + yellow gradient halo behind it.  Wizard form uses pill-style tag pickers (compact + scannable).  Nelson brand colors throughout.',
          el: <WizardMockupE3 /> },
        { id: 'A', title: '— round 1 below this line — A: slim picker IN the yellow pre-season banner', body:
            'Compact dropdown row baked into the existing yellow strip.  Treats Find-My-Plow as a peer of the pricing + phone CTAs.  Smallest footprint.  Best for users who already know what they want; weakest for first-time browsers because dropdowns are less inviting than tile pickers.',
          el: <WizardMockupA /> },
        { id: 'B', title: 'Mockup B — yellow banner + dedicated dark wizard band below it',
          body: 'Pre-season banner unchanged; new dark blue full-width band below with the 3-column TILE picker (the existing UX).  Pushes the hero down ~250px but makes the wizard the FIRST interactive element on the page.  Most consistent with the existing wizard already further down the page.',
          el: <WizardMockupB /> },
        { id: 'C', title: 'Mockup C — wizard REPLACES the dark hero entirely',
          body: 'Most committed look.  The H1 IS "Find My Plow."  You lose the "Pacific NW snow plow HQ" brand-identity copy unless we keep it as a small line.  Zero scroll to the tool.  Aggressive but high-conversion.',
          el: <WizardMockupC /> },
        { id: 'D', title: 'Mockup D — split hero: brand copy LEFT, compact wizard card RIGHT',
          body: 'Compromise between B and C.  Brand identity stays on the left, white wizard card sits on the right (where the YMM "find a plow that fits" tease used to live).  Both visible above the fold on desktop; wizard stacks below copy on mobile.',
          el: <WizardMockupD /> },
      ].map(m => (
        <section key={m.id} className="border-t-4 border-yellow-400">
          <div className="bg-white border-b">
            <div className="max-w-7xl mx-auto px-6 py-4">
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">Mockup {m.id}</div>
              <h2 className="text-base font-bold text-gray-900">{m.title}</h2>
              <p className="text-xs text-gray-600 mt-1 max-w-3xl">{m.body}</p>
            </div>
          </div>
          {m.el}
        </section>
      ))}
    </div>
  )
}


function PlowFinderWizard() {
  const [truckClass, setTruckClass] = useState<string>("")
  const [routeType, setRouteType] = useState<string>("")
  const [budget, setBudget] = useState<string>("any")
  const [response, setResponse] = useState<RecommendResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const ready = truckClass && routeType && budget
  const matches = response?.matches ?? null

  async function recommend() {
    if (!ready) return
    setLoading(true)
    try {
      const url = `/api/catalog/snow-plow-models/recommend?truck_class=${encodeURIComponent(truckClass)}&route_type=${encodeURIComponent(routeType)}&budget=${encodeURIComponent(budget)}&limit=3`
      const r = await fetch(url)
      const d: RecommendResponse = await r.json()
      setResponse(d)
    } finally { setLoading(false) }
  }

  function reset() {
    setTruckClass(""); setRouteType(""); setBudget("any"); setResponse(null)
  }

  // Auto-recommend when all 3 are picked
  useEffect(() => {
    if (ready) recommend()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [truckClass, routeType, budget])

  // L1.D Catalog-Card chrome — picked by Ben Apr 29 2026 after a long
  // mockup process (E1 → 6 page directions → 4 light-tactical → 5 L1
  // family variants → L1.D + picker-font fix + bordered-step fix).
  // The recommender / state / effects above are unchanged; only the
  // visual chrome below got swapped.  Selected-tile state goes black-
  // with-yellow-text to match the primary CTA, hover lights yellow.
  const tileBase = "px-3 py-2 text-sm font-medium border bg-white text-gray-800 hover:border-yellow-500 hover:bg-yellow-50 hover:shadow-sm transition text-left rounded-sm leading-tight"
  const tileSelected = "border-black bg-black text-yellow-400 shadow-sm"
  const tileIdle = "border-gray-300"
  return (
    <section id="finder" className="bg-gray-100 text-gray-900">
      <div className="max-w-7xl mx-auto px-6 py-10">
        {/* HERO CARD — white card floating on gray catalog bg with a
            yellow safety-stripe left border.  Split into V-plow + brand
            identity (left) and the 3-step picker (right). */}
        <div className="bg-white shadow-xl rounded-sm border-l-8 border-yellow-400 grid md:grid-cols-[1fr_440px] gap-8 items-center p-6 md:p-8">
          <div>
            <div className="text-[10px] uppercase tracking-[0.3em] text-gray-500 font-bold mb-2">CONTRACTOR-GRADE · PACIFIC NW</div>
            <h1 className="text-4xl md:text-5xl font-black uppercase leading-[0.95] tracking-tight">FIND YOUR PLOW.</h1>
            <p className="mt-3 text-base text-gray-600 max-w-md">
              Tell us 3 things — truck class, route, budget.  We'll spec the right contractor-grade plow from our 17-model catalog in seconds.
            </p>
            <div className="mt-4">
              <img src={VPLOW_IMG} alt="Snow plow" className="w-full max-w-[440px]"
                   style={{ filter: 'drop-shadow(0 12px 24px rgba(0,0,0,0.10))' }}/>
            </div>
            {matches && (
              <button onClick={reset} className="mt-3 text-xs uppercase tracking-wider text-gray-700 hover:text-black font-bold border-b border-gray-300 hover:border-black pb-0.5">
                ← Reset and start over
              </button>
            )}
          </div>

          {/* PICKER — 3 bordered step cards inside a gray-50 picker frame */}
          <div className="bg-gray-50 border-l-4 border-black p-5 rounded-sm">
            <div className="text-[10px] uppercase tracking-[0.3em] text-gray-700 font-black mb-3">⚡ FIND MY PLOW</div>
            <div className="space-y-3">
              {/* Each step is a card with a solid black header bar across
                  the top — step number + label in white — and the tiles
                  in the white area below.  Matches the bg-black + light-text
                  pattern established by the CTA + selected-tile state. */}
              <div className="bg-white border border-gray-300 rounded-sm overflow-hidden">
                <div className="bg-gray-700 text-white text-xs uppercase tracking-[0.2em] font-bold px-3 py-2">1. Your truck</div>
                <div className="p-3">
                  <div className="grid grid-cols-2 gap-1.5">
                    {TRUCK_CLASSES.map((t) => (
                      <button key={t.id} onClick={() => setTruckClass(t.id)}
                        className={`${tileBase} ${truckClass === t.id ? tileSelected : tileIdle}`}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="bg-white border border-gray-300 rounded-sm overflow-hidden">
                <div className="bg-gray-700 text-white text-xs uppercase tracking-[0.2em] font-bold px-3 py-2">2. What you plow</div>
                <div className="p-3">
                  <div className="grid grid-cols-2 gap-1.5">
                    {ROUTE_TYPES.map((r) => (
                      <button key={r.id} onClick={() => setRouteType(r.id)}
                        className={`${tileBase} ${routeType === r.id ? tileSelected : tileIdle}`}>
                        {r.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="bg-white border border-gray-300 rounded-sm overflow-hidden">
                <div className="bg-gray-700 text-white text-xs uppercase tracking-[0.2em] font-bold px-3 py-2">3. Budget</div>
                <div className="p-3">
                  <div className="grid grid-cols-2 gap-1.5">
                    {BUDGETS.map((b) => (
                      <button key={b.id} onClick={() => setBudget(b.id)}
                        className={`${tileBase} ${budget === b.id ? tileSelected : tileIdle}`}>
                        {b.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <button disabled={!ready} className="w-full mt-2 px-3 py-3 bg-black text-yellow-400 text-sm font-bold uppercase tracking-wider hover:bg-gray-900 disabled:bg-gray-400 disabled:text-gray-200 shadow-lg rounded-sm">
                {ready ? 'Find My Plow →' : 'Pick all 3 to continue'}
              </button>
              <p className="text-[10px] text-gray-500 text-center">Free.  No email required to see results.</p>
            </div>
          </div>
        </div>
      </div>

      {/* BOTTOM BAND — recommendation results, full width below the hero card.
          Auto-fires the recommender once all 3 picks are made (see useEffect).
          Card-on-gray styling continues from the hero band. */}
      {ready && (
        <div className="bg-gray-100 border-t border-gray-200">
          <div className="max-w-7xl mx-auto px-6 py-8">
            {!ready && (
              <div className="bg-gray-50 border-2 border-dashed border-gray-200 rounded p-6 text-center text-sm text-gray-500">
                Pick all 3 to see your recommendations.
              </div>
            )}
            {ready && loading && (
              <div className="text-sm text-gray-500">Computing recommendations…</div>
            )}
            {ready && !loading && matches && matches.length === 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded p-4 text-sm text-amber-900">
                No exact matches in our 17-model catalog for that combo.{" "}
                <a href="mailto:sales@nelsontruck.com?subject=Snow%20Plow%20Recommendation" className="text-red-700 hover:underline font-semibold">
                  Request a custom spec from sales →
                </a>
              </div>
            )}
            {ready && !loading && matches && matches.length > 0 && (
              <div>
                {/* Truck-class warning — fires when the chosen route family
                    has no spec'd plows for the chosen truck class (e.g.
                    half-ton + winged blade). */}
                {response?.truck_class_warning && (
                  <div className="mb-4 bg-amber-50 border-l-4 border-amber-500 rounded-r p-4">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl flex-shrink-0">⚠️</span>
                      <div className="flex-1">
                        <div className="text-xs uppercase tracking-wider text-amber-700 font-bold mb-1">Heads up — truck/route mismatch</div>
                        <p className="text-sm text-amber-900 leading-snug">{response.truck_class_warning}</p>
                        {response.suggested_step_up && (
                          <p className="text-xs text-amber-800 mt-2 italic">{response.suggested_step_up}</p>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <div className="text-xs uppercase tracking-wider text-gray-500 font-bold mb-3">
                  ✨ Recommended for you ({matches.length} {matches.length === 1 ? "match" : "matches"})
                </div>
                <div className="space-y-3">
                  {matches.map((m, i) => {
                    const isDirect = m.direct_fit
                    return (
                      <div
                        key={m.plow.id}
                        className={`border-2 rounded-lg p-4 flex items-start gap-4 ${
                          isDirect
                            ? "border-green-200 bg-green-50"
                            : "border-amber-300 bg-amber-50"
                        }`}
                      >
                        <div className={`w-10 h-10 text-white text-base font-bold rounded-full flex items-center justify-center flex-shrink-0 ${
                          isDirect ? "bg-green-700" : "bg-amber-600"
                        }`}>
                          {i + 1}
                        </div>
                        {/* Hero image — moldboard SKU's product photo from Nelson WSM.
                            Null when scrape hasn't covered the model; hidden via
                            conditional so the layout collapses cleanly. */}
                        {m.plow.hero_image_url && (
                          <div className="w-32 h-24 flex-shrink-0 bg-white border border-gray-200 rounded overflow-hidden">
                            <img
                              src={m.plow.hero_image_url}
                              alt={`${m.plow.brand} ${m.plow.model}`}
                              loading="lazy"
                              className="w-full h-full object-contain"
                            />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">{m.plow.brand}</span>
                            <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[9px] uppercase tracking-wider rounded font-bold">{m.plow.family_label}</span>
                            {isDirect ? (
                              <span className="px-1.5 py-0.5 bg-green-700 text-white text-[9px] uppercase tracking-wider rounded font-bold">✓ Fits your truck</span>
                            ) : (
                              <span className="px-1.5 py-0.5 bg-amber-600 text-white text-[9px] uppercase tracking-wider rounded font-bold">⚠ Stretch — needs heavier truck</span>
                            )}
                          </div>
                          <h3 className="text-lg font-extrabold text-gray-900 mt-0.5">{m.plow.model}</h3>
                          <div className="text-sm text-gray-700 mt-1">{m.plow.best_for}</div>
                          {/* Manufacturer description (Meyer has the richest copy) */}
                          {m.plow.manufacturer?.description && (
                            <div className="mt-2 text-xs text-gray-600 leading-relaxed bg-white/60 border border-gray-200 rounded p-2">
                              <span className="text-[9px] uppercase tracking-wider text-gray-500 font-bold">From {m.plow.manufacturer.manufacturer}</span>
                              <p className="mt-1">{m.plow.manufacturer.description.length > 280 ? m.plow.manufacturer.description.slice(0, 280) + "…" : m.plow.manufacturer.description}</p>
                              {m.plow.manufacturer.source_url && (
                                <a href={m.plow.manufacturer.source_url} target="_blank" rel="noopener noreferrer"
                                   className="text-[10px] text-blue-700 hover:underline mt-1 inline-block">
                                  Read more on {new URL(m.plow.manufacturer.source_url).hostname.replace("www.","")} →
                                </a>
                              )}
                            </div>
                          )}
                          <div className="mt-2 text-xs text-gray-700 space-y-1">
                            {m.reasoning.map((r, j) => (
                              <div key={j} className="flex items-start gap-1">
                                <span className={isDirect ? "text-green-700" : "text-amber-700"}>{isDirect ? "✓" : "•"}</span>
                                <span>{r}</span>
                              </div>
                            ))}
                          </div>
                          {/* Per-plow fit warning text — only shown for stretch picks */}
                          {!isDirect && m.fit_warning && (
                            <div className="mt-2 text-[11px] text-amber-900 bg-amber-100 border border-amber-300 rounded px-2 py-1.5 leading-snug">
                              <strong>Why it's flagged:</strong> {m.fit_warning}
                            </div>
                          )}
                          <div className="mt-3 flex flex-wrap gap-2 items-center">
                            <span className="text-sm font-bold text-gray-900">${m.plow.msrp_low.toLocaleString()}–${m.plow.msrp_high.toLocaleString()}</span>
                            <span className="text-xs text-gray-500">·</span>
                            <span className="text-xs text-gray-600">{m.plow.weight_lb} lb</span>
                            <span className="text-xs text-gray-500">·</span>
                            <span className="text-xs text-gray-600">{m.plow.blade_widths_in.join(" / ")}</span>
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Link
                              to={`/snow-plows/configurator?truck=${truckClass}&plow=${m.plow.id}`}
                              className="px-3 py-1.5 bg-blue-700 hover:bg-blue-800 text-white text-xs font-bold rounded"
                            >
                              👀 See it on my truck →
                            </Link>
                            <a
                              href={`mailto:sales@nelsontruck.com?subject=${encodeURIComponent("Quote: " + m.plow.brand + " " + m.plow.model)}`}
                              className="px-3 py-1.5 bg-red-700 hover:bg-red-800 text-white text-xs font-bold rounded"
                            >
                              Request quote →
                            </a>
                            <Link
                              to={`/snow-plows/compare?ids=${matches.map((mm) => mm.plow.id).join(",")}&truck=${truckClass}`}
                              className="px-3 py-1.5 bg-white border hover:border-red-700 text-gray-700 text-xs font-bold rounded"
                            >
                              ⚖️ Compare all {matches.length}
                            </Link>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}

// =========================================================================
// Winter Weather Widget — NWS forecast for both Nelson locations.  Gated
// to Oct-Apr (the snow-plowing season) so it just doesn't render May-Sep.
// User vision Apr 27: "when winter hits, it would be a good idea to have
// the 10-day forecast on the website and analyze it to see what areas
// will get snow".  This is the first half (display); the analysis half
// (storm-incoming email outreach) is the next item in the queue.
// =========================================================================

interface ForecastPeriod {
  name: string
  is_daytime: boolean
  temperature: number
  temperature_unit: string
  short_forecast: string
  detailed_forecast: string
  pop: number | null
  wind_speed: string
  wind_direction: string
  icon_url: string
  snow_risk: 'snow' | 'wintry' | 'cold' | 'none'
  start_time: string
  end_time: string
}

interface WeatherLocation {
  key: string
  name: string
  headline: string
  updated_at: string
  periods: ForecastPeriod[]
}

function isPlowSeason(): boolean {
  const m = new Date().getMonth()  // 0-indexed: Jan=0
  // Oct(9) Nov(10) Dec(11) Jan(0) Feb(1) Mar(2) Apr(3)
  return m >= 9 || m <= 3
}

/** True for the spring/summer "lock in your fall plow" window — when Western,
 *  Meyer, and SnowDogg all run their pre-season programs (early-bird pricing
 *  + free freight).  Roughly April through September.  In-season (Oct-Mar)
 *  the banner copy shifts to "limited stock / call for in-stock plows" since
 *  the pre-season offers have all closed by then. */
function isPreSeasonWindow(): boolean {
  const m = new Date().getMonth()  // 0-indexed: Jan=0
  // Apr(3) May(4) Jun(5) Jul(6) Aug(7) Sep(8)
  return m >= 3 && m <= 8
}

const SNOW_RISK_STYLE: Record<string, string> = {
  snow:   'bg-blue-50 border-blue-300 text-blue-900',
  wintry: 'bg-purple-50 border-purple-300 text-purple-900',
  cold:   'bg-gray-100 border-gray-300 text-gray-700',
  none:   'bg-white border-gray-200 text-gray-700',
}
const SNOW_RISK_BADGE: Record<string, string> = {
  snow:   '❄️ Snow',
  wintry: '🌨️ Wintry',
  cold:   '🥶 Cold',
  none:   '',
}

function WinterWeatherWidget() {
  // Show in dev regardless of season for debugging — query string `?weather=1`
  // also forces it to render so it can be previewed off-season.
  const force = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('weather') === '1'
  const inSeason = isPlowSeason() || force

  const [data, setData] = useState<{ locations: WeatherLocation[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!inSeason) return
    fetch('/api/catalog/snow-weather')
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { setError(d.error || 'NWS forecast unavailable'); return }
        setData(d)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [inSeason])

  if (!inSeason) return null

  return (
    <section className="bg-gradient-to-b from-slate-50 to-white border-y">
      <div className="max-w-7xl mx-auto px-6 py-10">
        <div className="flex items-end justify-between mb-5 flex-wrap gap-3">
          <div>
            <div className="text-[10px] uppercase tracking-widest text-blue-700 font-bold">⛈ Active forecast</div>
            <h2 className="text-2xl font-extrabold text-gray-900">7-day weather at our locations</h2>
            <p className="text-sm text-gray-600 max-w-2xl mt-1">
              NWS-source forecast for our Portland + Kent shop.  Snow / wintry days are highlighted —
              if your route is in the area, this is when you'll want the plow on the truck.
            </p>
          </div>
          <span className="text-[10px] text-gray-500">Source: api.weather.gov · cached 1h</span>
        </div>

        {loading && <div className="text-sm text-gray-500">Loading forecast…</div>}
        {error && (
          <div className="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-900">
            Forecast temporarily unavailable: {error}
          </div>
        )}
        {data && (
          <div className="grid md:grid-cols-2 gap-5">
            {data.locations.map((loc) => {
              const snowDays = loc.periods.filter((p) => p.snow_risk === 'snow' || p.snow_risk === 'wintry').length
              return (
                <div key={loc.key} className="bg-white border rounded-lg shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b bg-blue-950 text-white">
                    <div className="text-[10px] uppercase tracking-widest text-blue-300 font-bold">{loc.headline}</div>
                    <div className="flex items-center justify-between">
                      <h3 className="text-base font-extrabold">{loc.name}</h3>
                      {snowDays > 0 && (
                        <span className="text-[10px] uppercase tracking-wider px-2 py-1 bg-blue-600/30 text-blue-100 rounded font-bold">
                          ❄ {snowDays} snow/wintry period{snowDays === 1 ? '' : 's'}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2 p-3">
                    {loc.periods.slice(0, 8).map((p, i) => (
                      <div
                        key={i}
                        className={`border-2 rounded p-2 ${SNOW_RISK_STYLE[p.snow_risk] || SNOW_RISK_STYLE.none}`}
                        title={p.detailed_forecast}
                      >
                        <div className="text-[10px] uppercase tracking-wide font-bold opacity-70 truncate">{p.name}</div>
                        <div className="text-xl font-extrabold mt-0.5">
                          {p.temperature}°{p.temperature_unit}
                        </div>
                        <div className="text-[10px] leading-tight mt-0.5 line-clamp-2">{p.short_forecast}</div>
                        {p.pop !== null && p.pop > 0 && (
                          <div className="text-[9px] opacity-70 mt-1">💧 {p.pop}%</div>
                        )}
                        {p.snow_risk !== 'none' && (
                          <div className="mt-1 text-[9px] uppercase tracking-wide font-bold">
                            {SNOW_RISK_BADGE[p.snow_risk]}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}

      </div>
    </section>
  )
}


// =========================================================================
// WinterWatch signup form — captures email + ZIP + opt-in flags, sends the
// confirmation email via /api/snow-alerts/signup.  Renders inside the
// WinterWeatherWidget section so it has the same Oct-Apr gating.
// =========================================================================
function WinterWatchSignup() {
  // Match the parent weather widget's seasonal gating — hide May-Sep so the
  // page doesn't carry a winter-themed signup form during summer when no one
  // would sign up.  `?weather=1` URL param force-renders for previewing.
  const force = typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('weather') === '1'
  const inSeason = isPlowSeason() || force

  const [email, setEmail] = useState('')
  const [zipCode, setZip] = useState('')
  const [alertOpt, setAlertOpt] = useState(true)
  const [promoOpt, setPromoOpt] = useState(false)
  const [state, setState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [serverMsg, setServerMsg] = useState<string>('')
  const [resultLabel, setResultLabel] = useState<string | null>(null)

  if (!inSeason) return null

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!email || !zipCode) return
    setState('submitting')
    setServerMsg('')
    try {
      const r = await fetch('/api/snow-alerts/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email.trim(),
          zip_code: zipCode.trim(),
          alert_opt_in: alertOpt,
          promo_opt_in: promoOpt,
        }),
      })
      const d = await r.json()
      if (!r.ok) {
        setState('error')
        setServerMsg(d.detail || `HTTP ${r.status}`)
        return
      }
      setResultLabel(d.location_label || null)
      setState('success')
    } catch (err) {
      setState('error')
      setServerMsg(String(err))
    }
  }

  return (
    <div className="mt-8 bg-blue-950 text-white rounded-lg shadow-lg overflow-hidden">
      <div className="grid md:grid-cols-[280px_1fr] gap-6 p-6 items-center">
        {/* Brand panel */}
        <div className="text-center md:text-left">
          <WinterWatchMark className="h-12 w-auto mx-auto md:mx-0 mb-2" />
          <h3 className="text-2xl font-extrabold">WinterWatch</h3>
          <p className="text-xs text-blue-200 mt-1">Free snow alerts for your ZIP — straight from the National Weather Service</p>
        </div>

        {/* Form */}
        {state === 'success' ? (
          <div className="bg-green-900/40 border border-green-500/40 rounded p-4">
            <div className="text-sm font-bold text-green-200">✓ Almost done — check your email</div>
            <p className="text-xs text-green-100/90 mt-1 leading-relaxed">
              We sent a confirmation link to <strong>{email}</strong>{resultLabel ? ` for ${resultLabel}` : ''}.
              Click the link to start receiving alerts whenever snow appears in the 10-day NWS forecast for your ZIP.
            </p>
            <button onClick={() => { setState('idle'); setEmail(''); setZip(''); setResultLabel(null) }}
                    className="mt-2 text-[11px] text-green-200 hover:text-white underline">
              Sign up another address →
            </button>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3">
            <div className="grid sm:grid-cols-[1fr_120px] gap-2">
              <input
                type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@yourcompany.com"
                className="px-3 py-2 rounded bg-white text-gray-900 text-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
              <input
                type="text" required pattern="\d{5}(-\d{4})?" value={zipCode} onChange={(e) => setZip(e.target.value)}
                placeholder="ZIP"
                className="px-3 py-2 rounded bg-white text-gray-900 text-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-400 font-mono"
              />
            </div>
            <div className="space-y-1.5 text-[11px]">
              <label className="flex items-start gap-2 cursor-pointer hover:text-white text-blue-100">
                <input type="checkbox" checked={alertOpt} onChange={(e) => setAlertOpt(e.target.checked)} className="mt-0.5"/>
                <span>Email me when snow appears in the 10-day forecast for my ZIP <em className="text-blue-300">(the main thing)</em></span>
              </label>
              <label className="flex items-start gap-2 cursor-pointer hover:text-white text-blue-100">
                <input type="checkbox" checked={promoOpt} onChange={(e) => setPromoOpt(e.target.checked)} className="mt-0.5"/>
                <span>Also send me occasional promotional emails about snow &amp; ice removal gear (pre-season pricing, parts deals, new arrivals)</span>
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button type="submit" disabled={state === 'submitting'}
                      className="px-4 py-2 bg-yellow-400 hover:bg-yellow-300 text-gray-900 text-sm font-extrabold rounded disabled:opacity-50 disabled:cursor-not-allowed">
                {state === 'submitting' ? 'Submitting…' : 'Sign me up →'}
              </button>
              <span className="text-[10px] text-blue-200">Free.  No spam.  Unsubscribe in one click.</span>
            </div>
            {state === 'error' && (
              <div className="text-xs text-red-300">⚠ {serverMsg}</div>
            )}
          </form>
        )}
      </div>
    </div>
  )
}


// =========================================================================
// WinterWatchMark — the mini-logo for WinterWatch.  Asset version of the
// metallic-blue medallion sourced from /static/winterwatch/logo.png.
// Auto-falls back to a transparent placeholder if the asset is missing.
// =========================================================================
function WinterWatchMark({ className = "" }: { className?: string }) {
  return (
    <img
      src="/static/winterwatch/logo.png"
      alt="WinterWatch"
      className={className}
      style={{ filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.25))' }}
    />
  )
}

// =========================================================================
// WinterWatch confirm + unsubscribe pages — landing pages for the email links
// =========================================================================
function WinterWatchConfirmPage() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [data, setData] = useState<{email?: string, zip_code?: string, location_label?: string|null, promo_opt_in?: boolean} | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!token) { setState('error'); setErr('Missing token'); return }
    fetch(`/api/snow-alerts/confirm?token=${encodeURIComponent(token)}`)
      .then(async (r) => {
        const d = await r.json()
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
        setData(d); setState('ok')
      })
      .catch((e) => { setState('error'); setErr(String(e)) })
  }, [token])

  return (
    <div className="bg-gray-50 min-h-[70vh]">
      <div className="max-w-md mx-auto px-6 py-16">
        <div className="bg-white rounded-lg shadow-sm border p-6 text-center">
          <WinterWatchMark className="h-14 w-auto mx-auto mb-3" />
          <div className="text-[10px] uppercase tracking-widest text-blue-700 font-bold">WinterWatch</div>
          {state === 'loading' && <p className="text-sm text-gray-500 mt-3">Confirming your subscription…</p>}
          {state === 'ok' && data && (
            <>
              <h1 className="text-2xl font-extrabold text-gray-900 mt-2">✓ You're confirmed</h1>
              <p className="text-sm text-gray-700 mt-3 leading-relaxed">
                We'll email <strong>{data.email}</strong> whenever snow appears in the 10-day NWS forecast for
                <strong> {data.location_label || `ZIP ${data.zip_code}`}</strong>.
              </p>
              {data.promo_opt_in && (
                <p className="text-xs text-gray-500 mt-2">
                  You'll also get occasional promotional emails about snow &amp; ice removal gear.
                </p>
              )}
              <Link to="/snow-plows" className="inline-block mt-5 px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded">
                Browse snow plows →
              </Link>
            </>
          )}
          {state === 'error' && (
            <>
              <h1 className="text-xl font-extrabold text-amber-700 mt-2">Something went wrong</h1>
              <p className="text-sm text-gray-700 mt-2">{err}</p>
              <p className="text-xs text-gray-500 mt-3">
                The link may have expired or been used already.  You can sign up again from the snow page.
              </p>
              <Link to="/snow-plows#winterwatch" className="inline-block mt-4 text-sm text-blue-700 hover:underline">
                ← Back to snow plows
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function WinterWatchUnsubscribePage() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading')
  const [email, setEmail] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!token) { setState('error'); setErr('Missing token'); return }
    fetch(`/api/snow-alerts/unsubscribe?token=${encodeURIComponent(token)}`)
      .then(async (r) => {
        const d = await r.json()
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`)
        setEmail(d.email || ''); setState('ok')
      })
      .catch((e) => { setState('error'); setErr(String(e)) })
  }, [token])

  return (
    <div className="bg-gray-50 min-h-[70vh]">
      <div className="max-w-md mx-auto px-6 py-16">
        <div className="bg-white rounded-lg shadow-sm border p-6 text-center">
          <WinterWatchMark className="h-14 w-auto mx-auto mb-3" />
          <div className="text-[10px] uppercase tracking-widest text-blue-700 font-bold">WinterWatch</div>
          {state === 'loading' && <p className="text-sm text-gray-500 mt-3">Unsubscribing…</p>}
          {state === 'ok' && (
            <>
              <h1 className="text-2xl font-extrabold text-gray-900 mt-2">You're unsubscribed</h1>
              <p className="text-sm text-gray-700 mt-3 leading-relaxed">
                We removed <strong>{email}</strong> from snow alerts and any promotional emails.
                You won't hear from us again unless you re-subscribe.
              </p>
              <p className="text-xs text-gray-500 mt-3">If this was a mistake, you can sign up again any time.</p>
              <Link to="/snow-plows#winterwatch" className="inline-block mt-4 text-sm text-blue-700 hover:underline">
                Re-subscribe →
              </Link>
            </>
          )}
          {state === 'error' && (
            <>
              <h1 className="text-xl font-extrabold text-amber-700 mt-2">Couldn't unsubscribe</h1>
              <p className="text-sm text-gray-700 mt-2">{err}</p>
              <p className="text-xs text-gray-500 mt-3">
                If you keep getting emails, just reply to one of them and we'll remove you manually.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}


function SnowTopSellerCard({ item, rank }: { item: SnowTopSeller; rank: number }) {
  const card = (
    <div className="group bg-white border rounded-lg overflow-hidden hover:border-red-700 hover:shadow-md transition flex flex-col h-full">
      <div className="flex items-stretch">
        {/* Rank + image area */}
        <div className="w-24 flex-shrink-0 bg-gray-50 flex items-center justify-center relative border-r">
          {item.image_url ? (
            <img src={item.image_url} alt={item.description} loading="lazy" className="w-full h-full object-contain p-2" />
          ) : (
            <div className="text-[10px] text-gray-400 uppercase tracking-wider text-center px-2">No image yet</div>
          )}
          <div className="absolute top-1 left-1 w-6 h-6 bg-red-700 text-white text-xs font-bold rounded-full flex items-center justify-center">
            {rank}
          </div>
        </div>
        {/* Body */}
        <div className="flex-1 p-3 flex flex-col min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">{item.brand}</span>
            <span className="px-1.5 py-0.5 bg-blue-100 text-blue-700 text-[9px] uppercase tracking-wider rounded font-bold">{item.category_label}</span>
          </div>
          <div className="font-mono text-xs text-gray-500">{item.sku}</div>
          <div className="text-sm font-medium text-gray-900 mt-0.5 leading-tight line-clamp-2">{item.description}</div>
          <div className="mt-2 flex items-center justify-between">
            <span className="text-xs text-green-700 font-bold">{item.units_last_12mo} sold last 12 mo</span>
            <span className="text-[10px] text-red-700 group-hover:underline font-semibold">
              {item.has_local_pdp ? 'View →' : 'Quote →'}
            </span>
          </div>
          {item.note && <div className="text-[11px] text-gray-500 italic mt-2">{item.note}</div>}
        </div>
      </div>
    </div>
  )
  return item.has_local_pdp ? (
    <Link to={`/product/${item.sku}`}>{card}</Link>
  ) : (
    <a href={`mailto:sales@nelsontruck.com?subject=${encodeURIComponent('Quote: ' + item.sku + ' (' + item.brand + ')')}`}>{card}</a>
  )
}

// =====================================================================
// Aerial Lifts & Bucket Trucks landing page — replicates the look of
// dur-a-lift.com/products/category/products/ for the Dur-A-Lift catalog
// we mirror.  Owner ask 2026-05-14: "please pull all data from this
// website for dur-a-lift and replicate their look as much as possible
// for the landing pages they are extremely well done."
//
// Page structure mirrors theirs:
//   1) Hero — H1 + intro paragraph + "Made in USA" badge
//   2) Breadcrumb bar (primary color background, white text)
//   3) Sub-category quick-link pills (Articulated / Telescopic Trucks /
//      Bucket Vans / Tracked Lifts) — clicking filters the grid below.
//   4) Product card grid — 3 columns desktop, 1 mobile.  Each card:
//        white panel, light-gray image well, primary-colored title
//        link, body paragraph, "Read More →" arrow CTA.
//   5) "Connect with a Nelson expert" CTA panel at the bottom
// =====================================================================

type AerialProduct = {
  id: number
  sku: string
  name: string
  description: string
  image_url: string | null
  applications?: { name: string }[]
}

const AERIAL_SUBCATS = [
  { slug: "articulated",        label: "Articulated", path: "Truck Equipment > Aerial Lifts and Bucket Trucks > Articulated Aerial Lifts" },
  { slug: "telescopic-trucks",  label: "Telescopic Bucket Trucks", path: "Truck Equipment > Aerial Lifts and Bucket Trucks > Telescopic Bucket Trucks" },
  { slug: "bucket-vans",        label: "Bucket Vans", path: "Truck Equipment > Aerial Lifts and Bucket Trucks > Telescopic Bucket Vans" },
  { slug: "tracked",            label: "Tracked Lifts", path: "Truck Equipment > Aerial Lifts and Bucket Trucks > Tracked Aerial Lifts" },
  { slug: "all",                label: "View All", path: "Truck Equipment > Aerial Lifts and Bucket Trucks" },
]

function AerialLiftsLanding() {
  const { subcatSlug } = useParams<{ subcatSlug?: string }>()
  const activeSub = AERIAL_SUBCATS.find((s) => s.slug === subcatSlug) ?? AERIAL_SUBCATS[AERIAL_SUBCATS.length - 1]
  const [products, setProducts] = useState<AerialProduct[]>([])
  const [intro, setIntro] = useState<string>("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const url = `/api/catalog/browse?category_path=${encodeURIComponent(activeSub.path)}&per_page=60`
    fetch(url)
      .then((r) => r.json())
      .then((d) => {
        // Filter to the marketing-page bucket-truck models (quote-only) and
        // skip the 8 small replacement-parts SKUs (decals, lanyards, filter,
        // boom strap, etc.) — those still surface in the regular catalog
        // grid for repair/replacement searches, but they shouldn't muddy the
        // marketing landing page.
        const items: AerialProduct[] = (d.hits || [])
          .filter((h: any) => (h.cta_mode || "") === "quote_shipping")
          .map((h: any) => ({
            id: h.id,
            sku: h.sku,
            name: h.name,
            description: h.description || "",
            image_url: h.image_url,
          }))
        setProducts(items)
      })
      .finally(() => setLoading(false))

    // Pull intro copy from the category detail
    fetch(`/api/catalog/category/${encodeURIComponent(activeSub.path.split(" > ").pop() || "")}`)
      .then((r) => r.ok ? r.json() : Promise.reject())
      .then((d) => setIntro(d.description || ""))
      .catch(() => setIntro(""))
  }, [activeSub.slug])

  return (
    <div className="bg-gray-50 min-h-screen">

      {/* HERO SECTION */}
      <section className="bg-white border-b">
        <div className="max-w-6xl mx-auto px-6 py-12 md:py-16">
          <div className="flex items-baseline gap-3 mb-2">
            <span className="text-[11px] uppercase tracking-widest font-bold text-red-700">
              Dur-A-Lift
            </span>
            <span className="text-[11px] uppercase tracking-widest text-gray-400">
              Made in USA since 1969
            </span>
          </div>
          <h1 className="text-4xl md:text-5xl font-black text-gray-900 leading-tight">
            Aerial Lifts &amp; Bucket Trucks
          </h1>
          {intro && (
            <p className="text-base md:text-lg text-gray-700 mt-5 leading-relaxed max-w-3xl">
              {intro.split("\n\n")[0]}
            </p>
          )}
          {intro && intro.split("\n\n").length > 1 && (
            <div className="text-sm md:text-base text-gray-600 mt-3 leading-relaxed max-w-3xl space-y-2">
              {intro.split("\n\n").slice(1).map((para, i) => (
                <p key={i}>{para}</p>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* BREADCRUMB BAR — primary color background like dur-a-lift.com */}
      <section className="bg-red-700">
        <div className="max-w-6xl mx-auto px-6 py-2.5 text-xs text-red-100">
          <Link to="/" className="hover:text-white">Home</Link>
          <span className="mx-2">›</span>
          <Link to="/catalog?category_top=Truck%20Equipment" className="hover:text-white">Truck Equipment</Link>
          <span className="mx-2">›</span>
          <Link to="/aerial-lifts" className="hover:text-white">Aerial Lifts &amp; Bucket Trucks</Link>
          {activeSub.slug !== "all" && (
            <>
              <span className="mx-2">›</span>
              <span className="text-white font-semibold">{activeSub.label}</span>
            </>
          )}
        </div>
      </section>

      {/* SUB-CATEGORY PILLS */}
      <section className="bg-white border-b">
        <div className="max-w-6xl mx-auto px-6 py-4 flex flex-wrap gap-2">
          {AERIAL_SUBCATS.map((s) => {
            const active = s.slug === activeSub.slug
            return (
              <Link
                key={s.slug}
                to={`/aerial-lifts${s.slug === "all" ? "" : "/" + s.slug}`}
                className={`px-4 py-2 text-sm font-semibold rounded-full border transition ${
                  active
                    ? "bg-red-700 text-white border-red-700"
                    : "bg-white text-gray-700 border-gray-300 hover:border-red-700 hover:text-red-700"
                }`}
              >
                {s.label}
              </Link>
            )
          })}
        </div>
      </section>

      {/* PRODUCT GRID */}
      <section className="max-w-6xl mx-auto px-6 py-10">
        {loading ? (
          <div className="text-gray-500 py-12 text-center">Loading…</div>
        ) : products.length === 0 ? (
          <div className="text-gray-500 py-12 text-center">No products found.</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {products.map((p) => (
              <Link
                key={p.id}
                to={`/product/${encodeURIComponent(p.sku)}`}
                className="group bg-white border-b-2 border-gray-200 hover:border-red-700 hover:shadow-md transition-all overflow-hidden flex flex-col"
              >
                <div className="bg-gray-50 aspect-[2/1] flex items-center justify-center overflow-hidden">
                  {p.image_url ? (
                    <img
                      src={p.image_url}
                      alt={p.name}
                      loading="lazy"
                      className="max-w-full max-h-full object-contain group-hover:scale-105 transition-transform duration-300"
                      onError={(e) => {
                        (e.currentTarget as HTMLImageElement).style.display = "none"
                      }}
                    />
                  ) : (
                    <div className="text-3xl font-bold text-gray-300">{p.name.charAt(0)}</div>
                  )}
                </div>
                <div className="p-5 flex-1 flex flex-col">
                  <h3 className="text-xl font-bold text-red-700 group-hover:text-red-800 mb-2 leading-tight">
                    {p.name}
                  </h3>
                  <p className="text-sm text-gray-700 leading-relaxed flex-1 line-clamp-4">
                    {p.description || "Request a quote to learn more about this Dur-A-Lift model."}
                  </p>
                  <div className="mt-4 inline-flex items-center text-sm font-bold text-red-700 group-hover:text-red-800">
                    Read More <span className="ml-1 transition-transform group-hover:translate-x-0.5">→</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* CTA PANEL */}
      <section className="bg-gradient-to-br from-gray-900 to-gray-800 text-white">
        <div className="max-w-6xl mx-auto px-6 py-12 md:py-16 text-center">
          <div className="text-[11px] uppercase tracking-widest text-gray-400 font-bold mb-2">
            Built for your job
          </div>
          <h2 className="text-3xl md:text-4xl font-black mb-4">
            Talk to Nelson about a Dur-A-Lift bucket truck
          </h2>
          <p className="text-base text-gray-300 max-w-2xl mx-auto mb-8 leading-relaxed">
            Tell us about your job spec — chassis, working height, basket configuration, insulation —
            and our team will spec the right Dur-A-Lift unit for you, with delivery and on-site
            commissioning options across the Pacific Northwest.
          </p>
          <Link
            to="/contact"
            className="inline-block px-8 py-3 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded uppercase tracking-wider"
          >
            Request a Quote →
          </Link>
        </div>
      </section>

      {/* MADE IN USA STRIP */}
      <section className="bg-white border-t">
        <div className="max-w-6xl mx-auto px-6 py-6 text-center">
          <div className="inline-flex items-center gap-3 text-sm text-gray-700">
            <span className="text-2xl">🇺🇸</span>
            <span><strong>Dur-A-Lift</strong> — Made in the USA since 1969.  Distributed by Nelson Truck Equipment in Portland OR and Kent WA.</span>
          </div>
        </div>
      </section>
    </div>
  )
}


function SnowPlowsLanding() {
  const [data, setData] = useState<SnowLandingPayload | null>(null)
  const [guideTab, setGuideTab] = useState<'choose' | 'sizing' | 'control' | 'fit'>('choose')
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [financingOpen, setFinancingOpen] = useState(false)

  useEffect(() => {
    fetch('/api/catalog/snow-plows-landing').then((r) => r.json()).then(setData).catch(() => {})
  }, [])

  // 7 plow types we'd like to surface — wire to our subcategories where they
  // exist and to a search query otherwise.  Phase 1.5 will add admin-curated
  // collections per type.
  // Plow type tiles — primary 3 link to the compare page filtered by plow
  // family.  Secondary 4 (UTV/Spreaders/Parts/Walk-Behind) don't have rich
  // catalog content yet so they fall through to a quote-request mailto
  // until we wire those product lines into the structured catalog.
  const PLOW_TYPES = [
    { label: 'Straight Blade Plows', icon: '▭',  desc: 'HTS / Pro-Plow / Lot Pro / EXII / MDII', href: '/snow-plows/compare?family=straight_blade' },
    { label: 'V-Plows',              icon: '▲',  desc: 'MVP3 / Super-V3 / VXFII / VMXII',         href: '/snow-plows/compare?family=v_plow' },
    { label: 'Winged Plows',         icon: '⊿',  desc: 'WIDE-OUT / Wingman / XPII',               href: '/snow-plows/compare?family=winged' },
    { label: 'UTV / Tractor Plows',  icon: '⛏',  desc: 'Sub-compact + utility',                   href: 'mailto:sales@nelsontruck.com?subject=UTV%20plow%20inquiry' },
    { label: 'Spreaders & De-icers', icon: '🧂', desc: 'In-bed + tailgate',                       href: 'mailto:sales@nelsontruck.com?subject=Spreader%20%2F%20De-icer%20inquiry' },
    { label: 'Parts & Accessories',  icon: '🔧', desc: 'Cutting edges, controls, lights',         href: 'mailto:sales@nelsontruck.com?subject=Plow%20parts%20%2F%20accessories' },
    { label: 'Walk-Behind / Sidewalk', icon: '🚶', desc: 'Snowrator + walk-behinds',              href: 'mailto:sales@nelsontruck.com?subject=Walk-behind%20snow%20unit%20inquiry' },
  ]

  const FAQS = [
    {
      q: 'Straight blade or V-plow — which should I buy?',
      a: 'Straight blades are simpler, lighter, and lower cost — best for residential driveways and small lots. V-plows let you scoop, windrow, and break through hard pack — best for commercial lots, cul-de-sacs, and heavy snow loads. If you plow more than 5 hours a week or push a lot of EOD piles, go V.',
    },
    {
      q: 'How big a plow does my truck need?',
      a: 'Match plow weight + width to your truck class. Half-tons (F-150 / 1500): 7\'6"–8\' light/mid weight. 3/4-tons (F-250 / 2500): 8\'–8\'6" mid/heavy. 1-tons (F-350 / 3500): 8\'6"–9\'6" heavy. Always check your truck\'s GVWR and front-axle capacity before committing.',
    },
    {
      q: 'Do you install? Can I have it shipped and install it myself?',
      a: 'We do both.  Install pickup is available at our Portland and Kent shop — usually a 1-day turnaround in pre-season, longer once it starts snowing.  Mount + light adapter are the only vehicle-specific parts; everything else is generic.  If you have a wrench and a Saturday, you can DIY.',
    },
    {
      q: 'Financing?',
      a: 'Most of our buyers (90%+) just put the plow on net-30 PO terms — no application needed.  When financing makes more sense, every brand we carry runs through Sheffield Financial.  Click "Financing options" below for direct application links per brand.',
    },
    {
      q: 'Hydraulic or electric — what\'s the difference?',
      a: 'Electric (e.g., SnowDogg MD/EX, Meyer Drive Pro): faster install, fewer points of failure, lower price. Hydraulic (Western Pro-Plus, Meyer Super V2): faster cycle times, holds up to commercial duty cycles. Most contractors run hydraulic; most homeowners run electric.',
    },
  ]

  // Season-aware banner — pre-season copy from Apr-Sep, in-season copy
  // (limited stock, call for in-stock plows) from Oct-Mar.  Both variants
  // share the same yellow band so the page identity stays consistent.
  const preSeason = isPreSeasonWindow()
  const bannerEyebrow = preSeason ? 'Pre-Season Ordering Now Open' : 'Plow Season — In-Stock Inventory'
  const bannerHeadline = preSeason
    ? 'Save on every plow + we cover the freight.'
    : 'Need a plow before the next storm?'
  const bannerCopy = preSeason
    ? 'Western · Meyer · Buyers SnowDogg all run pre-season programs every spring + summer.  Lock in your fall plow now — best pricing of the year + zero freight charges.  Pre-season windows close before the first snowflake.'
    : 'Pre-season programs have closed for the year, but we still stock the popular blade widths at both Portland and Kent.  Call for current in-stock plows + same-week install slots.'
  const bannerCtaLabel = preSeason ? 'Lock in pre-season pricing →' : 'Check in-stock plows →'
  const bannerCtaSubject = preSeason ? 'Pre-Season%20Snow%20Plow%20Order' : 'In-Stock%20Snow%20Plow%20Inquiry'

  return (
    <div className="bg-gray-50">
      {/* Seasonal order banner — primary conversion lever for /snow-plows.
          Pre-season (Apr-Sep): "lock in fall plow now".  In-season (Oct-Mar):
          "what's still in stock + call us".  See isPreSeasonWindow() */}
      <section className="bg-gradient-to-r from-yellow-400 via-yellow-300 to-yellow-400 text-gray-900 border-b-4 border-red-700">
        <div className="max-w-7xl mx-auto px-6 py-4 grid md:grid-cols-[auto_1fr_auto] gap-4 items-center">
          <div className="flex items-center gap-3">
            <span className="text-3xl">❄️</span>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-red-700 font-extrabold">{bannerEyebrow}</div>
              <div className="text-base md:text-lg font-extrabold leading-tight">{bannerHeadline}</div>
            </div>
          </div>
          <div className="text-xs md:text-sm text-gray-800">{bannerCopy}</div>
          <div className="flex flex-col sm:flex-row gap-2">
            <a href="#finder"
               className="px-4 py-2 bg-blue-950 hover:bg-blue-900 text-white text-sm font-bold rounded text-center whitespace-nowrap">
              ⚡ Find My Plow →
            </a>
            <a href={`mailto:sales@nelsontruck.com?subject=${bannerCtaSubject}`}
               className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded text-center whitespace-nowrap">
              {bannerCtaLabel}
            </a>
            <a href="tel:8003461704" className="px-4 py-2 bg-gray-900 hover:bg-black text-white text-sm font-bold rounded text-center whitespace-nowrap">
              📞 503-548-9300
            </a>
          </div>
        </div>
      </section>

      {/* HERO = the Find My Plow wizard.  Per Ben's pick of mockup E1 round-2:
          white background, V-plow image on the left, picker card on the right,
          recommendations render below as a full-width band.  No more dark
          marketing hero — the wizard IS the page identity now. */}
      <PlowFinderWizard />

      {/* Stock / phone / hours strip — used to live inside the dark hero;
          carved out as its own slim trust strip below the wizard so the
          numbers still appear "above the fold." */}
      {data && (
        <section className="bg-blue-950 text-white">
          <div className="max-w-7xl mx-auto px-6 py-3 flex flex-wrap items-center justify-center gap-x-6 gap-y-1 text-xs text-blue-200">
            <span>📦 <strong className="text-white">{data.total_in_stock_skus.toLocaleString()}</strong> snow SKUs in stock right now</span>
            <span>📞 <a href="tel:8003461704" className="text-white hover:underline">503-548-9300</a></span>
            <span>📅 M–F 7:30 AM – 5:30 PM PT</span>
            <span>⛽ <Link to="/snow-plows/configurator" className="text-white hover:underline">See it on my truck</Link></span>
          </div>
        </section>
      )}

      {/* Opinion strip — right below the trust strip so the contractor-
          grade positioning lands BEFORE the buyer dives into details.  This
          is the differentiator (we don't sell home-plow class blades for
          commercial routes) and works as part of the brand identity. */}
      <section className="bg-amber-50 border-b border-amber-200">
        <div className="max-w-7xl mx-auto px-6 py-5 flex flex-col md:flex-row md:items-center gap-3 text-sm">
          <div className="flex-shrink-0 text-2xl">⚠️</div>
          <div className="flex-1 text-amber-900">
            <strong>Heads up — we won't sell you a home-plow blade for a contractor route.</strong>{' '}
            Light-residential units like the <em>Meyer Home Plow</em> (and equivalents — judged by moldboard material + construction, not the badge on the box) are built for 1–2 seasons of driveway use.  Put one on a commercial route and it won't survive a single winter.{' '}
            <span className="block mt-1 text-xs">
              <strong>Note:</strong> mid-size truck contractor blades (Western Defender, Meyer Drive Pro, etc.) are <em>not</em> residential — they're right-sized contractor-grade for Tacoma / Colorado / Ranger / Maverick class trucks.  And ATV/UTV plows are their own category — lighter construction makes sense because the duty cycle is lower.
            </span>
          </div>
          <a href="mailto:sales@nelsontruck.com?subject=Snow%20Plow%20Spec%20Help" className="flex-shrink-0 px-3 py-1.5 bg-amber-700 hover:bg-amber-800 text-white text-xs font-bold rounded">Talk to a tech →</a>
        </div>
      </section>

      {/* Buyer-priority panel: cost / stock / which plow are the top 3 questions */}
      <section className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="text-xs uppercase tracking-widest text-gray-500 font-bold mb-3">The 3 questions every buyer asks first</div>
          <div className="grid md:grid-cols-3 gap-4">
            <div className="border-l-4 border-yellow-400 pl-4 py-2">
              <div className="text-xs uppercase tracking-wider text-gray-500 font-bold">1. Cost</div>
              <div className="text-base font-bold text-gray-900 mt-0.5">$3,800 – $14,200 typical</div>
              <p className="text-xs text-gray-600 mt-1">
                Half-ton straight blade ~$5K · 3/4-ton V-plow ~$8.5K · 1-ton winged ~$11K.
                <button onClick={() => setFinancingOpen(true)} className="ml-1 text-red-700 hover:underline">Financing →</button>
              </p>
            </div>
            <div className="border-l-4 border-green-500 pl-4 py-2">
              <div className="text-xs uppercase tracking-wider text-gray-500 font-bold">2. In stock or lead time</div>
              <div className="text-base font-bold text-gray-900 mt-0.5">Pre-season Aug–Oct</div>
              <p className="text-xs text-gray-600 mt-1">
                Order before Sept and you'll have it on your truck by Halloween.  Mid-season requires a stock check.
                <a href="tel:8003461704" className="ml-1 text-red-700 hover:underline">Call to confirm →</a>
              </p>
            </div>
            <div className="border-l-4 border-blue-500 pl-4 py-2">
              <div className="text-xs uppercase tracking-wider text-gray-500 font-bold">3. Which plow</div>
              <div className="text-base font-bold text-gray-900 mt-0.5">Match truck → route → blade</div>
              <p className="text-xs text-gray-600 mt-1">
                Skip the spec sheets — try the wizard below, or compare 2–4 side-by-side.
                <a href="#finder" className="ml-1 text-red-700 hover:underline">Find My Plow ↓</a>
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Winter weather widget — Oct-Apr only, NWS forecast for both Nelson
          locations.  Add `?weather=1` to URL to force-render off-season. */}
      <WinterWeatherWidget />

      {/* Brand showcase — large cards, color-only (no broken stock photos) */}
      <section id="brands" className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Shop by brand</h2>
            <p className="text-sm text-gray-500">Ranked by Nelson's actual last-12-months snow plow sales</p>
          </div>
        </div>
        <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
          {(data?.brands || []).map((b) => (
            <div key={b.name} className="rounded-lg overflow-hidden shadow-md bg-white border flex flex-col">
              {/* Branded color header — replaces the previous broken stock-photo */}
              <div className={`relative bg-gradient-to-br ${b.color} text-white p-5 flex flex-col justify-between min-h-[180px] overflow-hidden`}>
                {/* Snow texture overlay */}
                <div className="absolute inset-0 opacity-15 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 25% 25%, white 1px, transparent 2px), radial-gradient(circle at 75% 60%, white 1.5px, transparent 2.5px)', backgroundSize: '40px 40px, 60px 60px' }} />
                <div className="relative">
                  <div className="text-[10px] uppercase tracking-widest text-white/85 font-bold">{b.rank}</div>
                  <h3 className="text-xl font-extrabold mt-1 leading-tight">{b.name}</h3>
                </div>
                {b.lineup && (
                  <div className="relative text-[11px] text-white/80 font-semibold tracking-wide pt-3">
                    {b.lineup}
                  </div>
                )}
              </div>
              {/* White body for clean readability */}
              <div className="p-4 flex-1 flex flex-col">
                <p className="text-sm text-gray-700 leading-relaxed mb-3 flex-1">{b.tagline}</p>
                <div className="flex items-center justify-between text-xs mb-3">
                  <span className="text-gray-600">{b.total_products > 0 ? `${b.total_products.toLocaleString()} products` : 'Whole plows by quote'}</span>
                  {b.in_stock_skus > 0 && (
                    <span className="px-2 py-0.5 bg-green-100 text-green-800 rounded font-bold">{b.in_stock_skus} in stock</span>
                  )}
                </div>
                {/* Map the snow-plow brand display name to the catalog brand
                    string used in our snow_plow_catalog (Western / Meyer /
                    SnowDogg) so the compare page filter matches. */}
                {(() => {
                  const brandSlug = b.name.toLowerCase().includes('western') ? 'Western'
                    : b.name.toLowerCase().includes('meyer') ? 'Meyer'
                    : b.name.toLowerCase().includes('snow dogg') || b.name.toLowerCase().includes('snowdogg') ? 'SnowDogg'
                    : null
                  return brandSlug ? (
                    <Link
                      to={`/snow-plows/compare?brand=${brandSlug}`}
                      className="block text-center px-3 py-2 bg-red-700 hover:bg-red-800 text-white text-xs font-bold rounded"
                    >
                      Compare {brandSlug} plows →
                    </Link>
                  ) : (
                    <a
                      href={`mailto:sales@nelsontruck.com?subject=${encodeURIComponent(b.name + ' inquiry')}`}
                      className="block text-center px-3 py-2 bg-red-700 hover:bg-red-800 text-white text-xs font-bold rounded"
                    >
                      Request quote →
                    </a>
                  )
                })()}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Shop by plow type tile grid */}
      <section id="types" className="bg-white border-y">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="flex items-end justify-between mb-6">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Shop by plow type</h2>
              <p className="text-sm text-gray-500">Pick the configuration that fits your route and your truck</p>
            </div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {PLOW_TYPES.map((t) => {
              const isExternal = t.href.startsWith('mailto:') || t.href.startsWith('http')
              const cls = "border rounded-lg p-4 bg-gray-50 hover:bg-white hover:border-red-700 hover:shadow-md transition text-center block"
              const inner = (
                <>
                  <div className="text-3xl mb-2">{t.icon}</div>
                  <div className="text-sm font-bold text-gray-900 leading-tight">{t.label}</div>
                  <div className="text-[10px] text-gray-500 mt-1">{t.desc}</div>
                </>
              )
              return isExternal ? (
                <a key={t.label} href={t.href} className={cls}>{inner}</a>
              ) : (
                <Link key={t.label} to={t.href} className={cls}>{inner}</Link>
              )
            })}
          </div>
        </div>
      </section>

      {/* Top sellers — sales-velocity ranked, last 12 months from tte_rcv390 */}
      <section className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Top sellers — last 12 months</h2>
            <p className="text-sm text-gray-500">What contractors actually bought from Nelson, ranked by units sold</p>
          </div>
          <Link to="/catalog?category_top=Truck+Equipment&category_path=Truck+Equipment%3ESnow+Plows%2FSpreaders" className="text-sm text-red-700 hover:underline">All snow products →</Link>
        </div>
        {!data ? <div className="text-gray-500 text-sm">Loading…</div> : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {data.featured_in_stock.map((p, i) => (
              <SnowTopSellerCard key={p.sku} item={p} rank={i + 1} />
            ))}
          </div>
        )}
        <p className="text-xs text-gray-500 mt-4 italic">
          Based on Nelson's actual sales history — not vendor recommendations.  Updated {new Date().toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}.
        </p>
      </section>

      {/* WinterWatch signup — broken out of the weather widget into its own
          focused strip so the form is the only thing competing for attention.
          Same Oct-Apr seasonal gating (the component returns null off-season). */}
      <section id="winterwatch" className="max-w-5xl mx-auto px-6 py-8">
        <WinterWatchSignup />
      </section>

      {/* Buying guide tabs */}
      <section className="bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-6 py-12">
          <div className="text-xs uppercase tracking-widest text-blue-300 font-bold mb-2">Buying Guide</div>
          <h2 className="text-2xl font-bold mb-4">Buy the right plow the first time</h2>
          <div className="flex flex-wrap gap-1 border-b border-white/20 mb-4">
            {[
              { id: 'choose' as const, label: 'Straight vs V vs Winged' },
              { id: 'sizing' as const, label: 'Plow sizing' },
              { id: 'control' as const, label: 'Hydraulic vs Electric' },
              { id: 'fit'    as const, label: 'Truck fit + axle capacity' },
            ].map((t) => (
              <button
                key={t.id}
                onClick={() => setGuideTab(t.id)}
                className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px transition ${
                  guideTab === t.id ? 'border-yellow-400 text-yellow-400' : 'border-transparent text-gray-300 hover:text-white'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="bg-white/5 border border-white/10 rounded-lg p-6 text-sm leading-relaxed text-gray-200">
            {guideTab === 'choose' && (
              <div className="grid md:grid-cols-3 gap-6">
                <div>
                  <div className="text-base font-bold text-white mb-2">▭ Straight blade</div>
                  <p>Best for residential, light commercial, smaller lots. Lighter, simpler, cheaper. Push and angle, that's it.</p>
                  <div className="mt-2 text-xs text-blue-300">Western HTS / Pro-Plow 3 / Pro Plus · Meyer EZ Plus · SnowDogg MD/EX</div>
                </div>
                <div>
                  <div className="text-base font-bold text-white mb-2">▲ V-plow</div>
                  <p>Best for commercial lots, cul-de-sacs, hard-pack. Scoop / vee / windrow positions break through anything.</p>
                  <div className="mt-2 text-xs text-blue-300">Western MVP 3 · Meyer Super V2 · SnowDogg VX / VXF</div>
                </div>
                <div>
                  <div className="text-base font-bold text-white mb-2">⊿ Winged</div>
                  <p>Best for moving the most snow per pass. Wings extend reach and contain the load. Heaviest investment but pays back on big lots.</p>
                  <div className="mt-2 text-xs text-blue-300">Western Wide-Out · Meyer XLS · SnowDogg XP</div>
                </div>
              </div>
            )}
            {guideTab === 'sizing' && (
              <div>
                <p className="mb-3">Match plow size to your truck class and the snow you're moving:</p>
                <table className="w-full text-xs">
                  <thead className="text-gray-400">
                    <tr><th className="text-left pb-1">Truck</th><th className="text-left pb-1">Plow width</th><th className="text-left pb-1">Plow weight</th><th className="text-left pb-1">Best for</th></tr>
                  </thead>
                  <tbody>
                    <tr className="border-t border-white/10"><td className="py-1">Half-ton (F-150, 1500)</td><td>7'6" – 8'</td><td>Light/mid (550–700 lb)</td><td>Driveways + light commercial</td></tr>
                    <tr className="border-t border-white/10"><td className="py-1">3/4-ton (F-250, 2500)</td><td>8' – 8'6"</td><td>Mid/heavy (700–850 lb)</td><td>Commercial lots</td></tr>
                    <tr className="border-t border-white/10"><td className="py-1">1-ton (F-350, 3500)</td><td>8'6" – 9'6"</td><td>Heavy (850–1100 lb)</td><td>Heavy commercial + municipal</td></tr>
                    <tr className="border-t border-white/10"><td className="py-1">Chassis cab (4500/5500)</td><td>9' – 11'</td><td>HD (1100+ lb)</td><td>Municipal + airport + DOT</td></tr>
                  </tbody>
                </table>
                <p className="mt-3 text-xs text-blue-300">Always check GVWR and front-axle capacity before installing — plow + ballast can exceed limits on lifted or accessory-heavy trucks.</p>
              </div>
            )}
            {guideTab === 'control' && (
              <div className="grid md:grid-cols-2 gap-6">
                <div>
                  <div className="text-base font-bold text-white mb-2">⚡ Electric / electro-hydraulic</div>
                  <p>Self-contained pump on the plow. Quick install, fewer hoses, lower entry price. Cycle times moderate. Good for residential and light commercial duty.</p>
                  <div className="mt-2 text-xs text-blue-300">Western HTS / Defender · Meyer Drive Pro · SnowDogg MD</div>
                </div>
                <div>
                  <div className="text-base font-bold text-white mb-2">🔧 Truck-mounted hydraulic</div>
                  <p>Pump bolts to the truck, hoses run to the plow. Fast cycle, brutal duty cycle. Higher entry, lower lifetime cost when you plow a lot.</p>
                  <div className="mt-2 text-xs text-blue-300">Western Pro-Plus / MVP3 / Wide-Out · Meyer Super V2 / Lot Pro · SnowDogg EX / VX / VXF / XP</div>
                </div>
              </div>
            )}
            {guideTab === 'fit' && (
              <div>
                <p className="mb-3">Most plows ship as a kit with a vehicle-specific mount. We confirm fitment when you order — but here's what to check:</p>
                <ul className="list-disc list-inside space-y-1 text-sm">
                  <li><strong>Year / Make / Model / Cab / Bed / Engine</strong> all matter — same model can have different mounts within a single year.</li>
                  <li><strong>Front-axle capacity (FAWR)</strong> — plow + mount + ballast must stay under FAWR or you'll wear front suspension fast.</li>
                  <li><strong>Bumper / aero clearance</strong> — late-model trucks with active aero or sensors may need a custom mount or partial removal.</li>
                  <li><strong>Snow Prep package</strong> — Ford, GM, Ram all offer snow-prep options that include heavier alternator + cooling. Helps but not required.</li>
                </ul>
                <p className="mt-3 text-xs text-blue-300">Set your YMM in the header — once we have it, we'll filter compatible plows across all brands.</p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Service & install grid */}
      <section className="max-w-7xl mx-auto px-6 py-12">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Install &amp; service</h2>
            <p className="text-sm text-gray-500">Factory-trained techs at Portland + Kent</p>
          </div>
        </div>
        <div className="grid md:grid-cols-3 gap-4">
          <div className="border rounded-lg p-5 bg-white">
            <div className="text-3xl mb-2">🔩</div>
            <h3 className="text-base font-bold mb-1">Install pickup</h3>
            <p className="text-sm text-gray-700 mb-3">Drop your truck at any of our shops, we install the plow + wiring + mount, and you drive home ready to go. Pre-season turnaround usually 1–2 days.</p>
            <div className="text-xs text-gray-600 space-y-0.5">
              <div>📍 Portland — 253-395-3825</div>
              <div>📍 Kent — 503-548-9300</div>
            </div>
          </div>
          <div className="border rounded-lg p-5 bg-white">
            <div className="text-3xl mb-2">🛠️</div>
            <h3 className="text-base font-bold mb-1">Service &amp; warranty</h3>
            <p className="text-sm text-gray-700 mb-3">Factory-authorized service for Western, Meyer, and SnowDogg. We carry the parts inventory to fix most issues same-day during the season.</p>
            <a href="mailto:service@nelsontruck.com" className="text-xs text-red-700 hover:underline font-semibold">Schedule service →</a>
          </div>
          <div className="border rounded-lg p-5 bg-white">
            <div className="text-3xl mb-2">❄️</div>
            <h3 className="text-base font-bold mb-1">Pre-season check</h3>
            <p className="text-sm text-gray-700 mb-3">Bring your plow in late summer for a full inspection: hydraulic fluid, cylinder seals, cutting edge, pump performance, lighting, controller. Cheaper than a mid-storm breakdown.</p>
            <a href="mailto:service@nelsontruck.com?subject=Pre-season+plow+check" className="text-xs text-red-700 hover:underline font-semibold">Book a check →</a>
          </div>
        </div>
      </section>

      {/* Quote builder banner */}
      <section className="bg-gradient-to-br from-red-700 to-red-900 text-white">
        <div className="max-w-7xl mx-auto px-6 py-10 grid md:grid-cols-2 gap-6 items-center">
          <div>
            <div className="text-xs uppercase tracking-widest text-red-200 font-bold mb-1">Talk to a plow specialist</div>
            <h2 className="text-2xl md:text-3xl font-extrabold mb-2">Spec a plow with someone who's actually plowed snow.</h2>
            <p className="text-sm text-red-100">Our sales techs run plows themselves. Tell us your truck, your route, and your budget — we'll spec the right setup, line up install, and put it on your PO terms. Usually back to you within one business day.</p>
          </div>
          <div className="flex flex-wrap gap-3 md:justify-end">
            <a href="mailto:sales@nelsontruck.com?subject=Snow%20Plow%20Quote" className="px-5 py-3 bg-yellow-400 hover:bg-yellow-300 text-gray-900 text-sm font-bold rounded">Request a quote</a>
            <a href="tel:8003461704" className="px-5 py-3 bg-white/10 hover:bg-white/20 text-white text-sm font-bold rounded border border-white/30">📞 503-548-9300</a>
            <button onClick={() => setFinancingOpen(true)} className="px-5 py-3 bg-white/10 hover:bg-white/20 text-white text-sm font-bold rounded border border-white/30">💳 Financing options</button>
          </div>
        </div>
      </section>

      {/* FAQ accordion */}
      <section className="max-w-4xl mx-auto px-6 py-12">
        <h2 className="text-2xl font-bold text-gray-900 mb-6">Frequently asked questions</h2>
        <div className="space-y-2">
          {FAQS.map((f, i) => (
            <div key={i} className="border rounded bg-white">
              <button
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
                className="w-full text-left px-4 py-3 flex items-center justify-between font-semibold text-gray-900 hover:bg-gray-50"
              >
                <span>{f.q}</span>
                <span className="text-gray-500">{openFaq === i ? '−' : '+'}</span>
              </button>
              {openFaq === i && (
                <div className="px-4 pb-4 text-sm text-gray-700 leading-relaxed">
                  {f.a}
                  {f.q.toLowerCase().includes('financing') && (
                    <div className="mt-3">
                      <button onClick={() => setFinancingOpen(true)} className="text-sm text-red-700 hover:underline font-semibold">
                        💳 Open financing options →
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* Why Nelson */}
      <section className="bg-gray-900 text-white">
        <div className="max-w-7xl mx-auto px-6 py-12 grid md:grid-cols-4 gap-6 text-center">
          <div>
            <div className="text-4xl mb-2">🏔️</div>
            <div className="font-bold text-lg">50+ years in snow country</div>
            <p className="text-xs text-gray-400 mt-1">Family-owned since 1937. We outfit plow trucks for our region all winter, every winter.</p>
          </div>
          <div>
            <div className="text-4xl mb-2">📍</div>
            <div className="font-bold text-lg">2 install locations</div>
            <p className="text-xs text-gray-400 mt-1">Portland + Kent.  Both carry parts and have certified install techs on staff.</p>
          </div>
          <div>
            <div className="text-4xl mb-2">🔧</div>
            <div className="font-bold text-lg">Factory-authorized</div>
            <p className="text-xs text-gray-400 mt-1">Direct dealer for Western, Meyer, SnowDogg + Buyers SaltDogg. Warranty work done in-house.</p>
          </div>
          <div>
            <div className="text-4xl mb-2">📦</div>
            <div className="font-bold text-lg">Parts in stock</div>
            <p className="text-xs text-gray-400 mt-1">When you blow a cylinder mid-storm we usually have it on the shelf. Try our parts catalog first.</p>
          </div>
        </div>
      </section>

      {financingOpen && <FinancingModal onClose={() => setFinancingOpen(false)} />}
    </div>
  )
}

// ============================================================================
// Brands index, Category landing, PDP modals
// ============================================================================

function BrandsIndexPage() {
  const [data, setData] = useState<BrandsIndex | null>(null)
  useEffect(() => {
    fetch('/api/catalog/brands/index').then((r) => r.json()).then(setData)
  }, [])
  return (
    <div className="p-6 max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold mb-2">Shop by brand</h1>
      <p className="text-sm text-gray-500 mb-6">Every manufacturer Nelson stocks, A→Z. Click a brand to browse their full lineup.</p>
      {!data ? (
        <div className="text-gray-500">Loading…</div>
      ) : (
        <>
          {/* A-Z anchor strip */}
          <div className="sticky top-32 bg-white py-2 mb-4 border-y flex flex-wrap gap-1">
            {data.letters.map((L) => (
              <a key={L} href={`#letter-${L}`} className="w-7 h-7 flex items-center justify-center text-xs font-semibold text-red-700 hover:bg-red-50 rounded">
                {L}
              </a>
            ))}
          </div>
          {data.groups.map((g) => (
            <section key={g.letter} id={`letter-${g.letter}`} className="mb-8">
              <h2 className="text-2xl font-bold text-gray-900 border-b-2 border-red-700 inline-block mb-3 pr-3">{g.letter}</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
                {g.brands.map((b) => (
                  <Link
                    key={b.slug}
                    to={`/catalog?brand=${encodeURIComponent(b.name)}`}
                    className="border rounded p-3 hover:border-red-700 hover:shadow transition bg-white"
                  >
                    <div className="text-sm font-semibold text-gray-800 truncate">{b.name}</div>
                    <div className="text-[10px] text-gray-500 mt-1">
                      {b.product_count > 0 ? `${b.product_count.toLocaleString()} products` : 'Stocked'}
                      {b.is_featured && <span className="ml-1 px-1 py-0.5 bg-yellow-100 text-yellow-700 rounded text-[9px] uppercase tracking-wider">Featured</span>}
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </div>
  )
}

interface FitmentPageData {
  category: { name: string; slug: string; full_path: string }
  make: string
  model: string
  year_min: number | null
  year_max: number | null
  count: number
  products: { id: number; sku: string; name: string; brand: string | null; image_url: string | null; in_stock: boolean; stock_total: number }[]
}

// Programmatic {category} × {vehicle} fitment landing page (e.g. "Floor Mats for
// Ford F-250"). Only exists for combos with in-stock inventory (backend 404s
// otherwise). The single biggest organic + AI-answer lever for a fitment catalog.
function FitmentLandingPage() {
  const { category, make, model } = useParams<{ category: string; make: string; model: string }>()
  const [data, setData] = useState<FitmentPageData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!category || !make || !model) return
    setData(null); setError(null)
    fetch(`/api/fitment/page/${category}/${make}/${model}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? 'notfound' : `HTTP ${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch((e) => setError(String(e.message || e)))
  }, [category, make, model])

  if (error) return (
    <div className="p-8 max-w-2xl mx-auto text-center">
      <div className="text-4xl mb-3">🔍</div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">No matches in stock</h1>
      <p className="text-sm text-gray-600 mb-6">We don't currently have in-stock items for that vehicle and category. Browse the full catalog or shop your vehicle.</p>
      <div className="flex justify-center gap-2 flex-wrap">
        <Link to="/catalog" className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Browse all products</Link>
        <Link to="/" className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm rounded">Back to home</Link>
      </div>
    </div>
  )
  if (!data) return <div className="p-8 text-gray-500">Loading…</div>

  const vehicle = `${data.make} ${data.model}`
  const yr = data.year_min && data.year_max
    ? (data.year_min === data.year_max ? `${data.year_min}` : `${data.year_min}–${data.year_max}`)
    : ''
  const catName = data.category.name
  const path = `/fits/${category}/${make}/${model}`
  const title = clamp(`${catName} for ${vehicle} | Nelson Truck Equipment`, 65)
  const description = clamp(
    `${data.count} in-stock ${catName.toLowerCase()} that fit the ${yr ? yr + ' ' : ''}${vehicle}, ready to ship from Nelson Truck Equipment. Commercial-grade parts, expert fitment.`,
    160,
  )
  const itemListJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name: `${catName} for ${vehicle}`,
    numberOfItems: data.count,
    itemListElement: data.products.slice(0, 30).map((p, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      url: absoluteUrl(`/product/${p.sku}`),
      name: p.name,
    })),
  }
  const breadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: CANONICAL_BASE_URL },
      { '@type': 'ListItem', position: 2, name: catName, item: absoluteUrl(`/categories/${data.category.slug}`) },
      { '@type': 'ListItem', position: 3, name: `${catName} for ${vehicle}`, item: absoluteUrl(path) },
    ],
  }

  return (
    <div className="bg-white">
      <Seo title={title} description={description} path={path} jsonLd={[itemListJsonLd, breadcrumbJsonLd]} />

      <section className="bg-gray-900">
        <div className="max-w-7xl mx-auto px-6 py-10">
          <nav className="text-xs text-gray-300 mb-3">
            <Link to="/" className="hover:text-white">Home</Link>
            {' / '}
            <Link to={`/categories/${data.category.slug}`} className="hover:text-white">{catName}</Link>
            {' / '}
            <span className="text-white">{vehicle}</span>
          </nav>
          <h1 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight">{catName} for {vehicle}</h1>
          <p className="mt-3 max-w-2xl text-sm text-gray-300">
            {data.count} in-stock {catName.toLowerCase()} that fit the {yr ? `${yr} ` : ''}{vehicle}. Every item below is a verified fit for your {data.model} and ready to ship.
          </p>
        </div>
      </section>

      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
          {data.products.map((p) => (
            <Link key={p.sku} to={`/product/${p.sku}`} className="group block rounded-lg border border-gray-200 overflow-hidden hover:shadow-md transition">
              <div className="aspect-square bg-gray-50 flex items-center justify-center overflow-hidden">
                {p.image_url
                  ? <img src={thumbUrl(p.image_url) || p.image_url} srcSet={`${thumbUrl(p.image_url)} 400w, ${p.image_url} 1280w`} sizes="(max-width: 640px) 45vw, (max-width: 1024px) 30vw, 22vw" alt={p.name} loading="lazy" className="w-full h-full object-contain group-hover:scale-105 transition" onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden' }} />
                  : <span className="text-xs text-gray-400">No image</span>}
              </div>
              <div className="p-3">
                {p.brand && <div className="text-[11px] uppercase tracking-wide text-gray-500">{p.brand}</div>}
                <div className="text-sm font-medium text-gray-900 line-clamp-2">{p.name}</div>
                <div className="mt-1 text-[11px] font-semibold text-emerald-700">In stock</div>
              </div>
            </Link>
          ))}
        </div>

        {/* Answer-shaped copy — helps SEO + AI answer engines. */}
        <div className="mt-10 max-w-3xl border-t border-gray-100 pt-6 text-sm text-gray-600">
          <h2 className="text-base font-bold text-gray-900 mb-2">{catName} that fit the {vehicle}</h2>
          <p>
            Looking for {catName.toLowerCase()} for your {yr ? `${yr} ` : ''}{vehicle}? Nelson Truck Equipment stocks {data.count} verified-fit {data.count === 1 ? 'option' : 'options'} ready to ship. Family-owned and serving the Pacific Northwest since 1937 — call or browse to get the right part the first time.
          </p>
          <p className="mt-3">
            <Link to={`/categories/${data.category.slug}`} className="text-red-700 hover:underline">See all {catName}</Link>
          </p>
        </div>
      </div>
    </div>
  )
}

function CategoryLandingPage() {
  const { slug } = useParams<{ slug: string }>()
  const { ymm } = useApp()
  const [cat, setCat] = useState<CategoryDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (!slug) return
    setError(null); setCat(null)
    fetch(`/api/catalog/category/${slug}`)
      .then(async (r) => {
        if (r.status === 404) {
          const body = await r.json().catch(() => ({}))
          throw new Error(body.detail || 'Category not found')
        }
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setCat)
      .catch((e) => setError(String(e.message || e)))
  }, [slug])
  if (error) return (
    <div className="p-8 max-w-2xl mx-auto text-center">
      <div className="text-4xl mb-3">🔍</div>
      <h1 className="text-2xl font-bold text-gray-900 mb-2">Category not available</h1>
      <p className="text-sm text-gray-600 mb-6">{error}</p>
      <div className="flex justify-center gap-2 flex-wrap">
        <Link to="/catalog" className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Browse all products</Link>
        <Link to="/" className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm rounded">Back to home</Link>
      </div>
    </div>
  )
  if (!cat) return <div className="p-8 text-gray-500">Loading…</div>

  // nelsontruck.com-style category landing:
  //   Hero strip with category image + title overlay
  //   YMM-aware "browse all that fit" CTA
  //   "Shop By Category" subcategory grid with image tiles
  //   Footer CTA: browse all products in this top-level
  const heroImg = cat.image_url
  // --- SEO: category title/meta/OG + Breadcrumb JSON-LD ---
  const catTitle = clamp(`${cat.name} for Trucks & Vans | Nelson Truck Equipment`, 65)
  const catDesc = clamp(
    `Shop ${cat.name} for trucks and vans at Nelson Truck Equipment — commercial-grade parts, accessories, and equipment for the Pacific Northwest.`,
    160,
  )
  const catBreadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: CANONICAL_BASE_URL },
      ...cat.breadcrumb.map((b, i) => ({
        '@type': 'ListItem',
        position: i + 2,
        name: b.name,
        item: absoluteUrl(`/categories/${b.slug}`),
      })),
    ],
  }
  return (
    <div className="bg-white">
      <Seo
        title={catTitle}
        description={catDesc}
        path={`/categories/${cat.slug}`}
        image={heroImg || null}
        jsonLd={catBreadcrumbJsonLd}
      />
      {/* Hero — matches nelsontruck.com layout */}
      <section className="relative bg-gray-900">
        {heroImg && (
          <img
            src={heroImg}
            alt={cat.name}
            className="absolute inset-0 w-full h-full object-cover opacity-30"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
          />
        )}
        <div className="relative max-w-7xl mx-auto px-6 py-12">
          <nav className="text-xs text-gray-300 mb-3">
            <Link to="/" className="hover:text-white">Home</Link>
            {cat.breadcrumb.map((b, i) => (
              <span key={i}>
                {' '}/{' '}
                {i === cat.breadcrumb.length - 1 ? (
                  <span className="text-white">{b.name}</span>
                ) : (
                  <Link to={`/categories/${b.slug}`} className="hover:text-white">{b.name}</Link>
                )}
              </span>
            ))}
          </nav>
          <h1 className="text-4xl md:text-5xl font-extrabold text-white tracking-tight uppercase">{cat.name}</h1>
        </div>
      </section>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* YMM-aware CTA — replaces a separate inline picker (we already have one in the global header) */}
        <div className="mb-8 p-4 border-l-4 border-red-700 bg-red-50 flex flex-wrap items-center gap-4">
          {ymm ? (
            <>
              <div className="text-sm text-gray-700">
                <span className="text-xs uppercase tracking-wider text-gray-500 font-semibold mr-2">Shopping for:</span>
                <span className="font-bold">{ymm.year} {ymm.make_name} {ymm.model_name}</span>
              </div>
              <Link
                to={`/catalog?category_path=${encodeURIComponent(cat.full_path)}`}
                className="ml-auto px-5 py-2.5 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded shadow-sm uppercase tracking-wide"
              >
                Show {cat.name} that fit my truck →
              </Link>
            </>
          ) : (
            <>
              <div className="text-sm text-gray-700">
                <span className="font-semibold">Tip:</span> set your Year/Make/Model in the header to filter to only parts that fit your truck.
              </div>
              <Link
                to={`/catalog?category_path=${encodeURIComponent(cat.full_path)}`}
                className="ml-auto px-5 py-2.5 bg-red-700 hover:bg-red-800 text-white text-sm font-bold rounded shadow-sm uppercase tracking-wide"
              >
                Browse all {cat.name} →
              </Link>
            </>
          )}
        </div>

        {cat.children.length > 0 && (
          <section className="mb-12">
            <h2 className="text-xl font-bold text-gray-900 mb-1">Shop By Category</h2>
            <p className="text-sm text-gray-500 mb-6">Pick a subcategory below or browse all {cat.name.toLowerCase()}.</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-5">
              {cat.children.map((c) => (
                <Link
                  key={c.id}
                  to={`/categories/${c.slug}`}
                  className="group flex flex-col items-center text-center"
                >
                  {/* Label ABOVE the image (owner ask 2026-05-17). */}
                  <div className="mb-2 text-sm font-semibold text-gray-800 group-hover:text-red-700 leading-tight">
                    {c.name}
                  </div>
                  {/* Floating image — mix-blend-mode: multiply blends the
                      source JPEG's white canvas into the white page bg so
                      the silhouette floats. No drop-shadow filter — it
                      would trap the blend in a stacking context. */}
                  <div className="w-full aspect-square flex items-center justify-center overflow-hidden">
                    {c.image_url ? (
                      <img
                        src={c.image_url}
                        alt={c.name}
                        style={{ mixBlendMode: 'multiply' }}
                        className="w-[88%] h-[88%] object-contain group-hover:scale-105 transition-transform duration-200"
                        loading="lazy"
                        onError={(e) => {
                          const img = e.currentTarget as HTMLImageElement
                          img.style.display = 'none'
                          const fallback = img.nextElementSibling as HTMLElement | null
                          if (fallback) fallback.style.display = 'flex'
                        }}
                      />
                    ) : null}
                    <div
                      className={`w-full h-full ${c.image_url ? 'hidden' : 'flex'} items-center justify-center text-3xl font-bold text-gray-300 uppercase`}
                    >
                      {c.name.charAt(0)}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        )}

        {/* Footer browse CTA */}
        <section className="border-t pt-6 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-gray-900">Looking for something specific?</h3>
            <p className="text-sm text-gray-600">Search the full {cat.name.toLowerCase()} catalog by part number, brand, or keyword.</p>
          </div>
          <Link
            to={`/catalog?category_path=${encodeURIComponent(cat.full_path)}`}
            className="px-5 py-2.5 bg-gray-900 hover:bg-gray-700 text-white text-sm font-bold rounded uppercase tracking-wide"
          >
            Browse all {cat.name} →
          </Link>
        </section>
      </div>
    </div>
  )
}

type FitmentResp = {
  sku: string
  universal: boolean
  make_count: number
  model_count: number
  groups: { make: string; models: { model: string; year_start: number | null; year_end: number | null; fitment_count: number }[] }[]
}

function ProductFitmentTab({ sku, ymm }: { sku: string; ymm: YMM | null }) {
  const [data, setData] = useState<FitmentResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  useEffect(() => {
    setLoading(true)
    fetch(`/api/catalog/products/${encodeURIComponent(sku)}/fitments`)
      .then((r) => r.json()).then((d) => { setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [sku])

  if (loading) return <div className="text-sm text-gray-500">Loading fitment data…</div>
  if (!data) return <div className="text-sm text-gray-500">No fitment data available.</div>

  if (data.universal) {
    return (
      <div className="text-sm text-gray-700 space-y-3">
        <div className="p-4 bg-blue-50 border border-blue-200 rounded">
          <div className="font-semibold mb-1">Universal fit</div>
          <p className="text-gray-700">
            This product ships without vehicle-specific ACES fitment data, so the
            manufacturer considers it universal. Please verify dimensions against
            your vehicle, or call sales at <a href="tel:503-548-9300" className="text-red-700 underline">503-548-9300</a> for confirmation.
          </p>
        </div>
      </div>
    )
  }

  // Check if user's saved YMM matches any of this product's makes
  const ymmMatch = ymm
    ? data.groups.find((g) => g.make.toLowerCase() === ymm.make_name.toLowerCase())?.models
        .find((m) => m.model.toLowerCase() === ymm.model_name.toLowerCase()
                     && (m.year_start ?? 0) <= ymm.year
                     && (m.year_end ?? 9999) >= ymm.year)
    : null

  return (
    <div className="text-sm text-gray-700 space-y-4">
      {ymm && (
        <div className={`p-4 rounded border ${ymmMatch ? 'bg-green-50 border-green-300' : 'bg-amber-50 border-amber-300'}`}>
          <div className="text-xs uppercase tracking-wider font-semibold mb-1">
            {ymmMatch ? '✓ Fits your vehicle' : '⚠ May not fit your vehicle'}
          </div>
          <div className="font-semibold">{ymm.year} {ymm.make_name} {ymm.model_name}</div>
          {ymmMatch ? (
            <p className="mt-1 text-green-800 text-xs">
              This product is confirmed to fit your {ymm.year} {ymm.make_name} {ymm.model_name} via the manufacturer's ACES feed.
            </p>
          ) : (
            <p className="mt-1 text-amber-800 text-xs">
              Your vehicle isn't listed in this product's fitment data. It may still fit — double-check with sales at <a href="tel:503-548-9300" className="text-red-700 underline">503-548-9300</a>.
            </p>
          )}
        </div>
      )}

      <div>
        <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">
          Fits {data.model_count} model{data.model_count === 1 ? '' : 's'} across {data.make_count} make{data.make_count === 1 ? '' : 's'}
        </div>
        <div className="space-y-2">
          {data.groups.map((g) => {
            const isOpen = expanded.has(g.make)
            return (
              <div key={g.make} className="border rounded bg-white">
                <button
                  onClick={() => {
                    setExpanded((prev) => {
                      const next = new Set(prev)
                      if (next.has(g.make)) next.delete(g.make); else next.add(g.make)
                      return next
                    })
                  }}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-50"
                >
                  <span className="font-semibold text-gray-900">{g.make}</span>
                  <span className="text-xs text-gray-500">
                    {g.models.length} model{g.models.length === 1 ? '' : 's'} <span className="ml-2">{isOpen ? '▾' : '▸'}</span>
                  </span>
                </button>
                {isOpen && (
                  <div className="border-t bg-gray-50 px-3 py-2">
                    <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
                      {g.models.map((m, i) => (
                        <li key={i} className="flex justify-between">
                          <span className="text-gray-800">{m.model}</span>
                          <span className="text-gray-500 ml-2">
                            {m.year_start === m.year_end ? m.year_start : `${m.year_start}–${m.year_end}`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function WarehouseStockTable({ sku }: { sku: string }) {
  const [data, setData] = useState<WarehouseStock | null>(null)
  useEffect(() => {
    fetch(`/api/catalog/products/${sku}/warehouse-stock`).then((r) => r.json()).then(setData).catch(() => setData(null))
  }, [sku])
  if (!data) return null
  if (data.locations.length === 0) {
    return <div className="text-sm text-gray-500">Drop-shipped from manufacturer (no Nelson warehouse stock)</div>
  }
  return (
    <div className="border rounded overflow-hidden text-sm">
      <table className="w-full">
        <thead className="bg-gray-100 text-xs uppercase tracking-wider text-gray-600">
          <tr>
            <th className="text-left px-3 py-2">Warehouse</th>
            <th className="text-right px-3 py-2">In Stock</th>
            <th className="text-left px-3 py-2">Lead Time</th>
            {/* Cutoff is a nice-to-have; hide on phones so the three core
                columns get enough room to render legibly */}
            <th className="text-left px-3 py-2 hidden sm:table-cell">Next Day Cutoff</th>
          </tr>
        </thead>
        <tbody>
          {data.locations.map((l) => (
            <tr key={l.warehouse_code} className="border-t">
              <td className="px-3 py-2 font-mono text-xs">{l.warehouse_name}</td>
              <td className="px-3 py-2 text-right">
                {l.in_stock ? (
                  <span className="text-green-700 font-semibold">{l.on_hand}</span>
                ) : (
                  <span className="text-gray-400">—</span>
                )}
              </td>
              <td className="px-3 py-2">{l.lead_time}</td>
              <td className="px-3 py-2 text-xs text-gray-600 hidden sm:table-cell">{l.next_day_cutoff}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LostSaleModal({ sku, onClose }: { sku: string; onClose: () => void }) {
  const [reason, setReason] = useState('price_too_high')
  const [note, setNote] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)

  async function submit() {
    setBusy(true)
    const r = await fetch('/api/signals/lost-sale', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sku, reason, note: note.trim() || null }),
    })
    setBusy(false)
    if (r.ok) {
      setSubmitted(true)
      setTimeout(onClose, 1500)
    }
  }
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-8 sm:pt-20 overflow-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md">
        <div className="p-5 border-b flex items-center justify-between">
          <h2 className="text-lg font-bold">Why aren't you buying?</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        {submitted ? (
          <div className="p-5 text-center">
            <div className="text-3xl text-green-600">✓</div>
            <p className="text-sm text-gray-700 mt-2">Thanks for the feedback. The sales team has been notified.</p>
          </div>
        ) : (
          <div className="p-5 space-y-4">
            <p className="text-sm text-gray-600">Help us understand what's blocking the sale on <span className="font-mono font-semibold">{sku}</span>. The sales team uses this to win you back next time.</p>
            <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold">
              Reason
              <select value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1 block w-full border rounded px-3 py-2 normal-case font-normal text-sm text-gray-900">
                <option value="price_too_high">Price too high</option>
                <option value="out_of_stock">Out of stock</option>
                <option value="shipping_time">Shipping too slow</option>
                <option value="found_elsewhere">Found it elsewhere</option>
                <option value="wrong_fitment">Doesn't fit my vehicle</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold">
              Notes (optional)
              <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What would change your mind?"
                        className="mt-1 block w-full border rounded px-3 py-2 normal-case font-normal text-sm text-gray-900 min-h-[80px]" />
            </label>
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-700 hover:text-gray-900">Cancel</button>
              <button onClick={submit} disabled={busy} className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded text-sm disabled:opacity-50">
                {busy ? 'Submitting…' : 'Submit'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function PriceMatchModal({ sku, onClose }: { sku: string; onClose: () => void }) {
  const [competitor, setCompetitor] = useState('')
  const [url, setUrl] = useState('')
  const [price, setPrice] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setBusy(true); setError(null)
    const payload: any = {
      sku,
      competitor_name: competitor.trim(),
      competitor_price_usd: price.trim(),
    }
    if (url.trim()) {
      // Pydantic HttpUrl rejects scheme-less URLs ("their-store.com").  Most
      // users won't type the scheme — accept those and prepend https:// so
      // the validator passes.
      let u = url.trim()
      if (u && !/^https?:\/\//i.test(u)) u = `https://${u}`
      payload.competitor_url = u
    }
    if (notes.trim()) payload.notes = notes.trim()
    const r = await fetch('/api/signals/price-match', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setBusy(false)
    if (r.ok) {
      setSubmitted(true)
      setTimeout(onClose, 2000)
    } else {
      const body = await r.json().catch(() => ({}))
      setError(formatApiError(body, r.status))
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-4 pt-8 sm:pt-20 overflow-auto">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md">
        <div className="p-5 border-b flex items-center justify-between">
          <h2 className="text-lg font-bold">Request a price match</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        {submitted ? (
          <div className="p-5 text-center">
            <div className="text-3xl text-green-600">✓</div>
            <p className="text-sm text-gray-700 mt-2">Submitted. Our sales team will review and reply within 1 business day.</p>
          </div>
        ) : (
          <div className="p-5 space-y-3">
            <p className="text-sm text-gray-600">Saw a lower advertised price for <span className="font-mono font-semibold">{sku}</span>? Send us the details and we'll match if it qualifies.</p>
            <input value={competitor} onChange={(e) => setCompetitor(e.target.value)} placeholder="Competitor name"
                   className="w-full border rounded px-3 py-2 text-sm" />
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Link to their listing (optional)"
                   className="w-full border rounded px-3 py-2 text-sm" />
            <input value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Their price (e.g. $199.99)"
                   className="w-full border rounded px-3 py-2 text-sm" />
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Any other context (optional)"
                      className="w-full border rounded px-3 py-2 text-sm min-h-[60px]" />
            {error && <div className="text-red-700 text-sm">{error}</div>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-700 hover:text-gray-900">Cancel</button>
              <button onClick={submit} disabled={busy || !competitor.trim() || !price.trim()}
                      className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white font-semibold rounded text-sm disabled:opacity-50">
                {busy ? 'Submitting…' : 'Submit'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function NewsletterSignup() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!/^\S+@\S+\.\S+$/.test(email)) { setError('Enter a valid email'); return }
    setError(null)
    // Phase 1.5 will POST to /api/marketing/newsletter — for now, accept locally
    try { localStorage.setItem('titan_newsletter_email', email) } catch {}
    setSubmitted(true)
  }
  if (submitted) {
    return <p className="text-xs text-green-400">✓ Thanks — you're on the list. We'll send seasonal promos and rebate alerts.</p>
  }
  return (
    <form onSubmit={submit} className="flex gap-2">
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email address"
        className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-red-700"
      />
      <button type="submit" className="px-4 py-2 bg-red-700 hover:bg-red-800 text-white text-sm font-semibold rounded">Subscribe</button>
      {error && <span className="text-xs text-red-400 ml-2 self-center">{error}</span>}
    </form>
  )
}

function Footer() {
  const { user, showroom } = useApp()
  // Showroom kiosk: drop the footer (corporate links, phones, newsletter) so the
  // walk-in only sees the white-label catalog.
  if (showroom && (user?.customer_tier === 'jobber' || user?.customer_tier === 'dealer')) return null
  return (
    <footer className="bg-gray-900 text-gray-300">
      {/* Newsletter strip */}
      <div className="bg-gray-950 border-b border-gray-800">
        <div className="max-w-7xl mx-auto px-6 py-6 grid md:grid-cols-2 gap-6 items-center">
          <div>
            <div className="text-sm font-bold text-white mb-1">Get rebate alerts + new-product news</div>
            <p className="text-xs text-gray-400">Manufacturer rebates (CURT, Aries, Air Lift, ProSeries…) and seasonal promos. About one email a month. Unsubscribe anytime.</p>
          </div>
          <NewsletterSignup />
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-12 grid grid-cols-2 md:grid-cols-5 gap-8">
        <div className="col-span-2">
          <span className="mb-3 flex items-center gap-2.5">
            <img src="/brand/nelson-badge.png" alt="" className="h-12 w-auto" />
            <img src="/brand/nelson-wordmark.png" alt="Nelson Truck Equipment" className="h-6 w-auto [filter:brightness(0)_invert(1)]" />
          </span>
          <p className="text-sm text-gray-400 mb-3">The Pacific Northwest&rsquo;s commercial truck-equipment source since 1937 — snow &amp; ice, truck bodies, tow trucks, aerial &amp; bucket, Landoll trailers, and accessories. We install everything we sell, and we build custom. In stock in Portland, OR and Kent, WA — pick it up today.</p>
          <div className="text-xs space-y-1">
            <div><span className="text-gray-500">Portland, OR:</span> 503-548-9300</div>
            <div><span className="text-gray-500">Kent, WA:</span> 253-395-3825</div>
          </div>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider font-semibold text-white mb-3">Shop</div>
          <ul className="text-sm space-y-1.5">
            <li><Link to="/catalog" className="hover:text-white">All products</Link></li>
            <li><Link to="/brands" className="hover:text-white">Brands A-Z</Link></li>
            <li><Link to="/catalog?in_stock=1" className="hover:text-white">In stock now</Link></li>
            <li><Link to="/snow-plows" className="hover:text-white">Snow plows</Link></li>
            <li><Link to="/catalog?category_top=Towing%20and%20Accessories" className="hover:text-white">Towing &amp; hitches</Link></li>
            <li><Link to="/catalog?category_top=Interior" className="hover:text-white">Interior accessories</Link></li>
            <li><Link to="/catalog?category_top=Exterior" className="hover:text-white">Exterior accessories</Link></li>
            <li><Link to="/catalog?category_top=Truck%20Bed%20Covers" className="hover:text-white">Tonneau covers</Link></li>
          </ul>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider font-semibold text-white mb-3">Account</div>
          <ul className="text-sm space-y-1.5">
            <li><Link to="/account" className="hover:text-white">My account</Link></li>
            <li><Link to="/orders" className="hover:text-white">Order history</Link></li>
            <li><Link to="/cart" className="hover:text-white">Cart</Link></li>
            <li><Link to="/signup" className="hover:text-white">Open B2B account</Link></li>
            <li><Link to="/login" className="hover:text-white">Log in</Link></li>
          </ul>
        </div>
        <div>
          <div className="text-xs uppercase tracking-wider font-semibold text-white mb-3">Company</div>
          <ul className="text-sm space-y-1.5">
            <li><a href="mailto:sales@nelsontruck.com" className="hover:text-white">Contact sales</a></li>
            <li><Link to="/about" className="hover:text-white">About us</Link></li>
            <li><Link to="/faq" className="hover:text-white">FAQ</Link></li>
            <li><Link to="/returns" className="hover:text-white">Returns &amp; warranty</Link></li>
            <li><Link to="/shipping" className="hover:text-white">Shipping policy</Link></li>
            <li><Link to="/privacy" className="hover:text-white">Privacy &amp; terms</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-gray-800">
        <div className="max-w-7xl mx-auto px-6 py-4 text-xs text-gray-500 flex flex-wrap justify-between gap-2">
          <div>© {new Date().getFullYear()} Nelson Truck Equipment. All rights reserved.</div>
          <div className="text-gray-600">Built on FastAPI + React. Phase 1 Working Draft.</div>
        </div>
      </div>
    </footer>
  )
}

// ============================================================================
// Van Navigator — make -> family -> variant side-rail
// ============================================================================

type VanVariant = {
  model_id: number
  name: string
  year: number
  base_vehicle_id: number
  make_slug: string
  model_slug: string
}
type VanFamily = { name: string; variants: VanVariant[] }
type VanMake = { make: string; families: VanFamily[] }

let _vanTreeCache: VanMake[] | null = null


// =====================================================================
// DewEze Kit Finder — Make → Year → Engine drill-down for the Hydraulic
// Pump Kits category.  Surfaces the matching installation kit + its
// per-truck schematic + Installation Manual PDF.  Owner-asked
// 2026-05-14: "bring in their Year, Make, Model sorting for a side
// navigation drill down like what we do for van interiors and snow plows."
// =====================================================================

type DwzMake = { make: string; kit_count: number; min_year: number | null; max_year: number | null }
type DwzYearRange = { year_start: number | null; year_end: number | null; kit_count: number }
type DwzEngine = { engine_or_model: string; engine_size: string | null; engine_fuel: string | null; kit_count: number }
type DwzApplication = {
  make: string
  engine_or_model: string | null
  engine_size: string | null
  engine_fuel: string | null
  year_start: number | null
  year_end: number | null
  pump_type_short: string | null
  pump_type_name: string | null
  pump_port: string | null
  belt: string | null
  clutch_configuration: string | null
  obsolete: boolean
}
type DwzKit = {
  id: number
  sku: string
  name: string
  description: string | null
  manual_pdf_url: string | null
  image_url: string | null
  applications: DwzApplication[]
}


function DewezeKitFinder() {
  const navigate = useNavigate()
  const [makes, setMakes] = useState<DwzMake[]>([])
  const [years, setYears] = useState<DwzYearRange[]>([])
  const [engines, setEngines] = useState<DwzEngine[]>([])
  const [matches, setMatches] = useState<DwzKit[]>([])
  const [pickedMake, setPickedMake] = useState<string>('')
  const [pickedYear, setPickedYear] = useState<number | null>(null)
  const [pickedEngine, setPickedEngine] = useState<string>('')
  const [loadingMatches, setLoadingMatches] = useState(false)

  // Load makes once on mount
  useEffect(() => {
    fetch('/api/deweze/makes')
      .then((r) => r.json())
      .then((d: DwzMake[]) => setMakes(d || []))
      .catch(() => setMakes([]))
  }, [])

  // Load years when make changes
  useEffect(() => {
    if (!pickedMake) {
      setYears([])
      setPickedYear(null)
      return
    }
    fetch(`/api/deweze/years?make=${encodeURIComponent(pickedMake)}`)
      .then((r) => r.json())
      .then((d: DwzYearRange[]) => setYears(d || []))
      .catch(() => setYears([]))
  }, [pickedMake])

  // Load engines when make + year are set
  useEffect(() => {
    if (!pickedMake || !pickedYear) {
      setEngines([])
      setPickedEngine('')
      return
    }
    fetch(`/api/deweze/engines?make=${encodeURIComponent(pickedMake)}&year=${pickedYear}`)
      .then((r) => r.json())
      .then((d: DwzEngine[]) => setEngines(d || []))
      .catch(() => setEngines([]))
  }, [pickedMake, pickedYear])

  // Load matching kits whenever the selection changes (auto-search at every level)
  useEffect(() => {
    if (!pickedMake) {
      setMatches([])
      return
    }
    const params = new URLSearchParams()
    params.set('make', pickedMake)
    if (pickedYear) params.set('year', String(pickedYear))
    if (pickedEngine) params.set('engine', pickedEngine)
    setLoadingMatches(true)
    fetch(`/api/deweze/kits?${params.toString()}`)
      .then((r) => r.json())
      .then((d) => setMatches(d.products || []))
      .catch(() => setMatches([]))
      .finally(() => setLoadingMatches(false))
  }, [pickedMake, pickedYear, pickedEngine])

  // Flatten year ranges into a clean year picker.  Each range produces a
  // year list (year_start through year_end); we union them and dedupe.
  const availableYears = useMemo(() => {
    if (!years.length) return [] as number[]
    const s = new Set<number>()
    const thisYear = new Date().getFullYear() + 1
    for (const r of years) {
      const ys = r.year_start ?? 1990
      const ye = Math.min(r.year_end ?? thisYear, thisYear)
      for (let y = ye; y >= ys; y--) s.add(y)
    }
    return Array.from(s).sort((a, b) => b - a)
  }, [years])

  function reset() {
    setPickedMake('')
    setPickedYear(null)
    setPickedEngine('')
    setMatches([])
  }

  return (
    <div className="space-y-1 border rounded-lg bg-white overflow-hidden">
      {/* Header — mirrors the VanNavigator dark-gradient treatment for
          visual consistency.  Owner-asked 2026-05-14: "I want the deweze
          finder component to look like the vannavigator." */}
      <div className="px-4 py-3 bg-gradient-to-br from-gray-900 to-gray-800 text-white border-b">
        <div className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">⚙ Find by DewEze Kit</div>
        <div className="text-sm font-bold mt-0.5">Pick your make + year + engine</div>
        <div className="text-[11px] text-gray-400 mt-1">
          Each kit comes with a per-truck installation schematic and Installation Manual PDF.
        </div>
      </div>

      <div className="p-3">
        {/* Make */}
        <label className="block text-[10px] uppercase tracking-widest text-gray-500 font-bold mb-1">
          Make
        </label>
        <select
          className="w-full mb-3 px-2 py-1.5 text-sm border border-gray-300 rounded bg-white"
          value={pickedMake}
          onChange={(e) => { setPickedMake(e.target.value); setPickedYear(null); setPickedEngine('') }}
        >
          <option value="">Choose make…</option>
          {makes.map((m) => (
            <option key={m.make} value={m.make}>
              {m.make} ({m.kit_count} kits)
            </option>
          ))}
        </select>

        {/* Year */}
        {pickedMake && (
          <>
            <label className="block text-[10px] uppercase tracking-widest text-gray-500 font-bold mb-1">
              Year
            </label>
            <select
              className="w-full mb-3 px-2 py-1.5 text-sm border border-gray-300 rounded bg-white"
              value={pickedYear ?? ''}
              onChange={(e) => { setPickedYear(e.target.value ? parseInt(e.target.value, 10) : null); setPickedEngine('') }}
            >
              <option value="">Choose year…</option>
              {availableYears.map((y) => (
                <option key={y} value={y}>{y}</option>
              ))}
            </select>
          </>
        )}

        {/* Engine */}
        {pickedMake && pickedYear && engines.length > 0 && (
          <>
            <label className="block text-[10px] uppercase tracking-widest text-gray-500 font-bold mb-1">
              Engine
            </label>
            <select
              className="w-full mb-3 px-2 py-1.5 text-sm border border-gray-300 rounded bg-white"
              value={pickedEngine}
              onChange={(e) => setPickedEngine(e.target.value)}
            >
              <option value="">All engines ({engines.reduce((s, e) => s + e.kit_count, 0)} kits)</option>
              {engines.map((e) => (
                <option key={`${e.engine_or_model}-${e.engine_size}`} value={e.engine_or_model}>
                  {e.engine_or_model || '(unspecified)'}
                  {e.engine_size ? ` • ${e.engine_size}` : ''}
                  {e.engine_fuel ? ` ${e.engine_fuel}` : ''}
                  {' '}({e.kit_count})
                </option>
              ))}
            </select>
          </>
        )}

        {(pickedMake || pickedYear || pickedEngine) && (
          <button
            onClick={reset}
            className="text-[11px] text-gray-600 hover:text-gray-900 hover:underline font-semibold mb-3"
          >
            ← Start over
          </button>
        )}

        {/* Matching kits — mirrors the VanNavigator variant-list treatment
            (indented under the picked make, vertical guide line). */}
        {pickedMake && (
          <div className="ml-1 mt-2 space-y-2 border-l-2 border-gray-100 pl-3">
            <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold">
              {loadingMatches ? 'Loading…'
                : matches.length === 0 ? 'No kits found'
                : `${matches.length} kit${matches.length === 1 ? '' : 's'} found`}
            </div>
            <div className="space-y-1">
              {matches.slice(0, 12).map((k) => (
                <button
                  key={k.id}
                  onClick={() => navigate(`/catalog/products/${encodeURIComponent(k.sku)}`)}
                  className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 rounded"
                >
                  <div className="font-bold text-gray-900">{k.sku}</div>
                  <div className="text-[11px] text-gray-700 line-clamp-2 mt-0.5">{k.name}</div>
                  {k.applications[0] && (
                    <div className="text-[10px] text-gray-500 mt-0.5">
                      Pump: {k.applications[0].pump_type_short || '?'}
                      {k.applications[0].belt ? ` · ${k.applications[0].belt}` : ''}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


function VanNavigator({
  compact = false,
  onPickVariant,
}: {
  compact?: boolean
  onPickVariant?: (v: VanVariant, make: string, family: string) => void
}) {
  const { ymm, setYmm } = useApp()
  const navigate = useNavigate()
  const [tree, setTree] = useState<VanMake[]>(_vanTreeCache || [])
  const [openMakes, setOpenMakes] = useState<Set<string>>(new Set(_vanTreeCache ? [_vanTreeCache[0]?.make] : []))

  useEffect(() => {
    if (_vanTreeCache) return
    fetch('/api/ymm/van-tree')
      .then((r) => r.json())
      .then((t: VanMake[]) => {
        _vanTreeCache = t
        setTree(t)
        if (t.length > 0) setOpenMakes(new Set([t[0].make]))
      })
      .catch(() => {})
  }, [])

  function toggleMake(make: string) {
    setOpenMakes((prev) => {
      const next = new Set(prev)
      if (next.has(make)) next.delete(make); else next.add(make)
      return next
    })
  }

  function pick(v: VanVariant, make: string, family: string) {
    setYmm({
      year: v.year,
      make_slug: v.make_slug,
      make_name: make,
      model_slug: v.model_slug,
      model_name: v.name,
      base_vehicle_id: v.base_vehicle_id,
    })
    if (onPickVariant) onPickVariant(v, make, family)
    else navigate(`/catalog?vehicle_type=Van&category_top=Cargo%20Management`)
  }

  if (tree.length === 0) return <div className="text-sm text-gray-500 p-4">Loading van models…</div>

  return (
    <div className={`space-y-1 ${compact ? '' : 'border rounded-lg bg-white overflow-hidden'}`}>
      {!compact && (
        <div className="px-4 py-3 bg-gradient-to-br from-gray-900 to-gray-800 text-white border-b">
          <div className="text-[10px] uppercase tracking-widest text-gray-400 font-bold">🚐 Find by Van</div>
          <div className="text-sm font-bold mt-0.5">Pick your make + wheelbase</div>
          <div className="text-[11px] text-gray-400 mt-1">After you pick a variant, filter the remaining van products by roof height + cab type on the next page.</div>
        </div>
      )}
      <div className={`${compact ? '' : 'p-2'}`}>
        {tree.map((m) => (
          <div key={m.make} className="mb-1">
            <button
              onClick={() => toggleMake(m.make)}
              className="w-full flex items-center justify-between px-3 py-2 text-left text-sm font-bold text-gray-900 hover:bg-gray-50 rounded"
            >
              <span>{m.make}</span>
              <span className="text-gray-400 text-xs">{openMakes.has(m.make) ? '▾' : '▸'}</span>
            </button>
            {openMakes.has(m.make) && (
              <div className="ml-3 mt-1 mb-2 space-y-2 border-l-2 border-gray-100 pl-3">
                {m.families.map((fam) => (
                  <div key={fam.name}>
                    <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                      {m.make} {fam.name}
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {fam.variants.map((v) => {
                        const isCurrent = ymm?.base_vehicle_id === v.base_vehicle_id
                        return (
                          <button
                            key={v.base_vehicle_id}
                            onClick={() => pick(v, m.make, fam.name)}
                            className={`px-2 py-1 text-xs rounded border transition ${
                              isCurrent
                                ? 'border-red-700 bg-red-50 text-red-700 font-semibold'
                                : 'border-gray-200 hover:border-red-700 hover:bg-red-50'
                            }`}
                            title={`${v.year} ${m.make} ${v.name}`}
                          >
                            {v.name.replace(fam.name, '').replace(/^[\s-]+/, '') || v.name}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function vanCatLink(node: CategoryNode): string {
  // Van Equipment subcategories should only show van-fitting + universal
  // products, so append vehicle_type=Van (matches the mega-menu behavior).
  return `/catalog?category_path=${encodeURIComponent(node.full_path)}&vehicle_type=Van`
}

/** One top-level Van Equipment category: hero image + name + count, with its
 *  subcategories listed as quick-links underneath. Renders nothing clickable
 *  nested inside another anchor (the image/title is its own link, the
 *  subcategory chips are separate links). */
function VanCategoryCard({ node }: { node: CategoryNode }) {
  return (
    <div className="group flex flex-col border border-gray-200 rounded-xl bg-white overflow-hidden hover:border-red-700 hover:shadow-lg transition">
      <Link to={vanCatLink(node)} className="block">
        <div className="aspect-[4/3] bg-gray-50 flex items-center justify-center overflow-hidden">
          {node.image_url ? (
            <img
              src={node.image_url}
              alt={node.name}
              loading="lazy"
              className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
          ) : (
            <span className="text-6xl">🚐</span>
          )}
        </div>
        <div className="px-4 pt-3">
          <div className="text-base font-bold text-gray-900 group-hover:text-red-700">{node.name}</div>
          <div className="text-xs text-gray-500 mt-0.5">{(node.product_count || 0).toLocaleString()} products</div>
        </div>
      </Link>

      {node.children.length > 0 && (
        <ul className="px-4 py-3 mt-1 space-y-1 border-t border-gray-100">
          {node.children.map((ch) => (
            <li key={ch.id}>
              <Link
                to={vanCatLink(ch)}
                className="flex items-center justify-between text-sm text-gray-600 hover:text-red-700"
              >
                <span className="truncate">{ch.name}</span>
                <span className="ml-2 shrink-0 text-xs text-gray-400">{(ch.product_count || 0).toLocaleString()}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function VansLandingPage() {
  const [tree, setTree] = useState<CategoryNode[] | null>(_categoryTree)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    loadCategoryTree()
      .then((t) => { if (alive) setTree(t) })
      .catch(() => { if (alive) setError('Could not load van categories.') })
    return () => { alive = false }
  }, [])

  const vanRoot = tree ? findCategoryByName(tree, 'Van Equipment') : null
  const vanCats = vanRoot?.children ?? []

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      <nav className="text-sm text-gray-500 mb-4">
        <Link to="/" className="hover:text-red-700">Home</Link> / Vans
      </nav>
      <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-6">
        <aside className="space-y-4">
          <VanNavigator />
        </aside>
        <section>
          <h1 className="text-3xl font-bold text-gray-900">Van Equipment</h1>
          <p className="text-gray-600 mt-1">Outfit Transit, Sprinter, ProMaster, Metris &amp; more — liners, flooring, shelving, partitions and racks. Pick your make + wheelbase from the left rail to filter by fitment, or shop a category below.</p>

          <div className="mt-6">
            <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-3">Shop by category</div>

            {error && (
              <div className="p-4 bg-red-50 border border-red-200 rounded text-sm text-red-800">{error}</div>
            )}

            {!error && tree === null && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="border border-gray-200 rounded-xl bg-white overflow-hidden animate-pulse">
                    <div className="aspect-[4/3] bg-gray-100" />
                    <div className="p-4 space-y-2">
                      <div className="h-4 bg-gray-100 rounded w-2/3" />
                      <div className="h-3 bg-gray-100 rounded w-1/3" />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {tree !== null && vanCats.length > 0 && (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4">
                {vanCats.map((c) => (
                  <VanCategoryCard key={c.id} node={c} />
                ))}
              </div>
            )}

            {tree !== null && vanCats.length === 0 && !error && (
              <div className="p-4 bg-amber-50 border border-amber-200 rounded text-sm text-amber-900">
                No van categories are published yet. Use the navigator on the left to find parts by make + wheelbase.
              </div>
            )}
          </div>

          {/* Van racks now live under Van Equipment > Ladder and Cargo Racks,
              split into three subcategories.  Surface those here. */}
          <div className="mt-8">
            <div className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-3">Racks &amp; carriers</div>
            <div className="flex flex-wrap gap-2">
              {[
                { name: 'Van Cargo Racks', path: 'Van Equipment > Ladder and Cargo Racks > Van Cargo Racks' },
                { name: 'Drop Down Ladder Racks', path: 'Van Equipment > Ladder and Cargo Racks > Drop Down Ladder Racks' },
                { name: 'Van Rack Mounts', path: 'Van Equipment > Ladder and Cargo Racks > Van Rack Mounts' },
              ].map((c) => (
                <Link
                  key={c.path}
                  to={`/catalog?category_path=${encodeURIComponent(c.path)}&vehicle_type=Van`}
                  className="px-4 py-2 border border-gray-200 rounded-full bg-white text-sm font-medium text-gray-700 hover:border-red-700 hover:text-red-700 transition"
                >
                  {c.name}
                </Link>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}

function Health() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { fetch('/api/health').then(r => r.json()).then(setData) }, [])
  return (
    <div className="p-8 max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">API Health</h1>
      <pre className="bg-gray-100 p-4 rounded text-sm overflow-auto">{data ? JSON.stringify(data, null, 2) : 'Loading…'}</pre>
    </div>
  )
}

// ============================================================================
// Admin: PIES attribute value curation
// ============================================================================

type AdminAttrKey = {
  attribute_key: string
  raw_value_count: number
  canonical_value_count: number
  auto_foldable_value_count: number
  manual_alias_count: number
  products_with_key: number
  reviewed_at: string | null
}

type AdminAttrBucket = {
  canonical: string
  count: number
  raw_values: string[]
  uom?: string | null
}

type AdminAttrCluster = {
  canonical: string
  total_count: number
  members: AdminAttrBucket[]
}

type AdminAttrAlias = {
  raw_value: string
  canonical_value: string
}

type AdminAttrClustersResp = {
  attribute_key: string
  auto_merged: { canonical: string; count: number; raw_values: string[] }[]
  suggested_clusters: AdminAttrCluster[]
  long_tail: AdminAttrBucket[]
  manual_aliases: AdminAttrAlias[]
}

function AdminAttributeCuratorPage() {
  const [keys, setKeys] = useState<AdminAttrKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [onlyUnreviewed, setOnlyUnreviewed] = useState(true)
  const [minProducts, setMinProducts] = useState<number>(50)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [resp, setResp] = useState<AdminAttrClustersResp | null>(null)
  const [respLoading, setRespLoading] = useState(false)
  const [focusedClusterIdx, setFocusedClusterIdx] = useState<number>(0)
  // Per-cluster canonical override (curator edited the label before merging)
  const [canonicalOverrides, setCanonicalOverrides] = useState<Record<string, string>>({})
  // Members the curator has un-picked ("not like the parent"). Keyed
  // `${clusterIdx}:${memberIdx}`. Absence = picked, so every member starts
  // checked and the curator only has to uncheck the odd ones out.
  const [deselectedMembers, setDeselectedMembers] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const memberKey = (ci: number, mi: number) => `${ci}:${mi}`
  const isMemberPicked = (ci: number, mi: number) => !deselectedMembers.has(memberKey(ci, mi))
  function toggleMember(ci: number, mi: number) {
    setDeselectedMembers((prev) => {
      const next = new Set(prev)
      const k = memberKey(ci, mi)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })
  }
  // Raw values of just the picked members of a cluster — what a Merge folds.
  function pickedRaws(c: AdminAttrCluster, ci: number): string[] {
    return c.members.flatMap((m, mi) => (isMemberPicked(ci, mi) ? m.raw_values : []))
  }
  function pickedCount(c: AdminAttrCluster, ci: number): number {
    return c.members.reduce((n, _m, mi) => n + (isMemberPicked(ci, mi) ? 1 : 0), 0)
  }

  function loadKeys() {
    setLoading(true)
    const url = new URL('/api/catalog/admin/attribute-keys', window.location.origin)
    url.searchParams.set('min_products', String(minProducts))
    fetch(url)
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin role)')
        if (r.status === 403) throw new Error('Admin role required to access this page')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: AdminAttrKey[]) => { setKeys(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadKeys() }, [minProducts])

  // Load clusters when a key is selected
  useEffect(() => {
    if (selectedKey === null) { setResp(null); return }
    setRespLoading(true)
    setFocusedClusterIdx(0)
    setCanonicalOverrides({})
    setDeselectedMembers(new Set())
    fetch(`/api/catalog/admin/attribute-keys/${encodeURIComponent(selectedKey)}/clusters`)
      .then((r) => r.json())
      .then((d: AdminAttrClustersResp) => setResp(d))
      .finally(() => setRespLoading(false))
  }, [selectedKey])

  async function saveCluster(canonical: string, rawValues: string[]) {
    if (selectedKey === null || rawValues.length === 0) return
    setSaving(true); setSaveError(null)
    try {
      const r = await fetch('/api/catalog/admin/attribute-aliases', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          attribute_key: selectedKey,
          canonical,
          raw_values: rawValues,
        }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(formatApiError(body, r.status))
      }
      // Refresh clusters for the current key + the key list (manual alias count
      // and suggested-cluster count both change after a save).
      const refreshed = await fetch(`/api/catalog/admin/attribute-keys/${encodeURIComponent(selectedKey)}/clusters`).then((x) => x.json())
      setResp(refreshed)
      setDeselectedMembers(new Set())
      // Cluster the user just merged is gone; move focus to the next one
      setFocusedClusterIdx((i) => Math.min(i, Math.max(0, (refreshed.suggested_clusters?.length || 1) - 1)))
      loadKeys()
    } catch (e) {
      setSaveError(String((e as Error).message || e))
      setTimeout(() => setSaveError(null), 6000)
    } finally {
      setSaving(false)
    }
  }

  async function dismissCluster() {
    // "Keep separate" — flag each member as its own canonical (no-merge alias)
    // so the suggestion doesn't keep coming back next visit.
    if (!resp || selectedKey === null) return
    const c = resp.suggested_clusters[focusedClusterIdx]
    if (!c) return
    setSaving(true); setSaveError(null)
    try {
      // For each member, write its own canonical as a manual alias. That
      // tells future cluster-suggestion passes that the curator
      // intentionally kept them apart.
      for (const m of c.members) {
        for (const raw of m.raw_values) {
          const r = await fetch('/api/catalog/admin/attribute-aliases', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              attribute_key: selectedKey,
              canonical: m.canonical,
              raw_values: [raw],
            }),
          })
          if (!r.ok) {
            const body = await r.json().catch(() => ({}))
            throw new Error(formatApiError(body, r.status))
          }
        }
      }
      const refreshed = await fetch(`/api/catalog/admin/attribute-keys/${encodeURIComponent(selectedKey)}/clusters`).then((x) => x.json())
      setResp(refreshed)
      setDeselectedMembers(new Set())
      setFocusedClusterIdx((i) => Math.min(i, Math.max(0, (refreshed.suggested_clusters?.length || 1) - 1)))
      loadKeys()
    } catch (e) {
      setSaveError(String((e as Error).message || e))
      setTimeout(() => setSaveError(null), 6000)
    } finally {
      setSaving(false)
    }
  }

  async function markReviewed() {
    if (selectedKey === null) return
    const r = await fetch(`/api/catalog/admin/attribute-keys/${encodeURIComponent(selectedKey)}/mark-reviewed`, {
      method: 'POST',
    })
    if (r.ok) loadKeys()
  }

  async function unmarkReviewed() {
    if (selectedKey === null) return
    const r = await fetch(`/api/catalog/admin/attribute-keys/${encodeURIComponent(selectedKey)}/mark-reviewed`, {
      method: 'DELETE',
    })
    if (r.ok) loadKeys()
  }

  // Keyboard shortcuts: J/K nav, Y accept, N reject. Owner-asked to keep
  // the curation flow keyboard-driven so a session of 30+ clusters
  // doesn't require constant mousing.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!resp) return
      // ignore when typing into a text field
      const tgt = e.target as HTMLElement
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable)) return
      const clusters = resp.suggested_clusters
      if (!clusters || clusters.length === 0) return
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault()
        setFocusedClusterIdx((i) => Math.min(clusters.length - 1, i + 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault()
        setFocusedClusterIdx((i) => Math.max(0, i - 1))
      } else if (e.key === 'y' || e.key === 'Y') {
        e.preventDefault()
        const c = clusters[focusedClusterIdx]
        if (!c) return
        const canonical = canonicalOverrides[`${focusedClusterIdx}`] || c.canonical
        const raws = pickedRaws(c, focusedClusterIdx)
        if (raws.length > 0) saveCluster(canonical, raws)
      } else if (e.key === 'n' || e.key === 'N') {
        e.preventDefault()
        dismissCluster()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resp, focusedClusterIdx, canonicalOverrides, deselectedMembers])

  const visibleKeys = keys.filter((k) => {
    if (onlyUnreviewed && k.reviewed_at) return false
    if (filter && !k.attribute_key.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-12">
        <h1 className="text-2xl font-bold mb-2">Attribute Value Curation</h1>
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">
          {error}
          {/^Login/.test(error) && (
            <div className="mt-2 text-sm">
              <Link to="/login" className="text-red-700 underline">Sign in</Link> as an admin user.
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1500px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Attribute Value Curation</h1>
          <p className="text-sm text-gray-600">
            Fold near-duplicate PIES attribute values into one customer-facing bucket.
            Check the values that belong to the parent before merging.
            Keyboard: <kbd className="px-1 border rounded text-xs">J/K</kbd> navigate clusters,
            {' '}<kbd className="px-1 border rounded text-xs">Y</kbd> merge picked,
            {' '}<kbd className="px-1 border rounded text-xs">N</kbd> keep separate.
          </p>
        </div>
        <div className="text-xs text-gray-500">
          {keys.length} keys · {keys.filter((k) => k.reviewed_at).length} reviewed
        </div>
      </div>

      {saveError && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800 flex items-center justify-between">
          <span>Save failed: {saveError}</span>
          <button onClick={() => setSaveError(null)} className="text-xs text-red-600 hover:underline">Dismiss</button>
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* LEFT: attribute key queue */}
        <aside className="col-span-4 space-y-3">
          <div className="sticky top-2 bg-white pt-2 pb-3 z-10">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter keys…"
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <label className="flex items-center gap-2 text-sm text-gray-700 mt-2 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyUnreviewed}
                onChange={(e) => setOnlyUnreviewed(e.target.checked)}
              />
              Only show unreviewed
            </label>
            {/* Min-products threshold keeps the queue short. With 2K+ distinct
                PIES keys in the catalog, anything below ~25-product coverage
                is rarely worth curating. */}
            <label className="flex items-center justify-between gap-2 text-xs text-gray-600 mt-2">
              <span>Min products per key</span>
              <select
                value={minProducts}
                onChange={(e) => setMinProducts(parseInt(e.target.value, 10))}
                className="border rounded px-2 py-1 text-xs"
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={250}>250</option>
                <option value={500}>500</option>
              </select>
            </label>
          </div>
          {loading && <div className="text-gray-500 text-sm">Loading…</div>}
          <div className="space-y-1">
            {visibleKeys.map((k) => (
              <button
                key={k.attribute_key}
                onClick={() => setSelectedKey(k.attribute_key)}
                className={`w-full text-left px-3 py-2 rounded border transition ${
                  selectedKey === k.attribute_key
                    ? 'border-red-700 bg-red-50'
                    : 'border-gray-200 hover:border-gray-400 bg-white'
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-sm font-semibold text-gray-900 truncate">{k.attribute_key}</div>
                  {k.reviewed_at && (
                    <span className="text-[9px] uppercase tracking-wider text-green-700 font-bold">Reviewed</span>
                  )}
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">
                  {k.raw_value_count} raw → {k.canonical_value_count} canonical
                  {' · '}{k.products_with_key.toLocaleString()} products
                </div>
                <div className="text-[10px] mt-0.5">
                  {k.auto_foldable_value_count > 0 ? (
                    <span className="text-red-700 font-semibold">
                      {k.auto_foldable_value_count} value{k.auto_foldable_value_count === 1 ? '' : 's'} likely foldable
                    </span>
                  ) : (
                    <span className="text-gray-400">no obvious dupes</span>
                  )}
                  {k.manual_alias_count > 0 && (
                    <span className="text-gray-500"> · {k.manual_alias_count} manual</span>
                  )}
                </div>
              </button>
            ))}
            {!loading && visibleKeys.length === 0 && (
              <div className="text-sm text-gray-500 p-4 text-center border-2 border-dashed rounded">
                {filter ? 'No keys match your filter.' : 'All caught up — nothing left to review.'}
              </div>
            )}
          </div>
        </aside>

        {/* RIGHT: cluster review */}
        <section className="col-span-8">
          {selectedKey === null ? (
            <div className="border-2 border-dashed rounded-lg p-12 text-center text-gray-500">
              Pick an attribute key from the left to see its suggested merges.
            </div>
          ) : respLoading ? (
            <div className="text-gray-500">Loading clusters…</div>
          ) : resp ? (
            <>
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-gray-500">Curating</div>
                  <h2 className="text-xl font-bold text-gray-900">{resp.attribute_key}</h2>
                  <div className="text-sm text-gray-600">
                    {resp.suggested_clusters.length} suggested cluster{resp.suggested_clusters.length === 1 ? '' : 's'}
                    {' · '}{resp.long_tail.length} singletons
                    {' · '}{resp.manual_aliases.length} manual aliases
                  </div>
                </div>
                <div className="flex gap-2">
                  {keys.find((k) => k.attribute_key === selectedKey)?.reviewed_at ? (
                    <button
                      onClick={unmarkReviewed}
                      className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50"
                    >
                      Re-open
                    </button>
                  ) : (
                    <button
                      onClick={markReviewed}
                      className="px-3 py-1.5 text-sm border border-green-600 bg-green-50 text-green-800 rounded hover:bg-green-100"
                    >
                      Mark reviewed
                    </button>
                  )}
                </div>
              </div>

              {/* AUTO-MERGED — info only, lets curator spot a bad fold */}
              {resp.auto_merged.length > 0 && (
                <details className="mb-4 border rounded-lg bg-gray-50">
                  <summary className="cursor-pointer px-4 py-2 text-sm font-semibold text-gray-700">
                    Auto-merged ({resp.auto_merged.length}) — case/trim/plural collapses already applied
                  </summary>
                  <div className="p-3 space-y-1">
                    {resp.auto_merged.map((m, i) => (
                      <div key={i} className="text-xs text-gray-700 flex items-baseline justify-between gap-3">
                        <div>
                          <span className="font-semibold">{m.canonical}</span>
                          <span className="text-gray-400 ml-2">({m.count.toLocaleString()})</span>
                        </div>
                        <div className="text-gray-500 truncate max-w-[60%]" title={m.raw_values.join(' · ')}>
                          ← {m.raw_values.join(' · ')}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {/* SUGGESTED CLUSTERS — the main work surface */}
              <h3 className="text-sm uppercase tracking-wider text-gray-500 font-bold mt-4 mb-2">
                Suggested merges
              </h3>
              {resp.suggested_clusters.length === 0 ? (
                <div className="border-2 border-dashed rounded-lg p-6 text-center text-gray-500 text-sm">
                  No suggested merges — every remaining value looks distinct.
                </div>
              ) : (
                <div className="space-y-3">
                  {resp.suggested_clusters.map((c, i) => {
                    const overrideKey = `${i}`
                    const canonicalLabel = canonicalOverrides[overrideKey] ?? c.canonical
                    const focused = i === focusedClusterIdx
                    return (
                      <div
                        key={i}
                        className={`border rounded-lg p-4 transition ${
                          focused ? 'border-red-700 bg-red-50 shadow' : 'border-gray-200 bg-white'
                        }`}
                        onClick={() => setFocusedClusterIdx(i)}
                      >
                        <div className="flex items-baseline justify-between gap-3 mb-2">
                          <div className="flex-1 min-w-0">
                            <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">
                              Canonical label
                            </div>
                            <input
                              type="text"
                              value={canonicalLabel}
                              onChange={(e) =>
                                setCanonicalOverrides((prev) => ({ ...prev, [overrideKey]: e.target.value }))
                              }
                              className="w-full mt-1 px-2 py-1 text-base font-bold text-gray-900 border border-gray-300 rounded focus:border-red-700 focus:outline-none"
                            />
                          </div>
                          <div className="text-xs text-gray-500 whitespace-nowrap">
                            <div className="font-semibold text-gray-800">{c.total_count.toLocaleString()}</div>
                            <div>products</div>
                          </div>
                        </div>
                        <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-1 mt-3">
                          Pick the values that are like &ldquo;{canonicalLabel}&rdquo;
                        </div>
                        <div className="space-y-0.5 mb-3">
                          {c.members.map((m, mi) => {
                            const picked = isMemberPicked(i, mi)
                            return (
                              <label
                                key={mi}
                                onClick={(e) => e.stopPropagation()}
                                className={`text-sm flex items-baseline gap-2 px-1 py-0.5 rounded cursor-pointer ${
                                  picked ? 'text-gray-700 hover:bg-gray-50' : 'text-gray-400 line-through'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={picked}
                                  onChange={() => toggleMember(i, mi)}
                                  className="self-center"
                                />
                                <span className="flex-1">{m.canonical}</span>
                                <span className="text-gray-400 text-xs">({m.count.toLocaleString()})</span>
                              </label>
                            )
                          })}
                        </div>
                        <div className="flex gap-2">
                          <button
                            disabled={saving || pickedCount(c, i) === 0}
                            onClick={(e) => {
                              e.stopPropagation()
                              const raws = pickedRaws(c, i)
                              if (raws.length > 0) saveCluster(canonicalLabel, raws)
                            }}
                            className="flex-1 px-3 py-2 text-sm font-semibold bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                          >
                            ✓ Merge {pickedCount(c, i)} of {c.members.length} as &ldquo;{canonicalLabel}&rdquo; (Y)
                          </button>
                          <button
                            disabled={saving}
                            onClick={(e) => {
                              e.stopPropagation()
                              setFocusedClusterIdx(i)
                              dismissCluster()
                            }}
                            className="px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
                          >
                            ✗ Keep separate (N)
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* LONG TAIL — already-distinct values, info-only for v1 */}
              {resp.long_tail.length > 0 && (
                <details className="mt-6 border rounded-lg">
                  <summary className="cursor-pointer px-4 py-2 text-sm font-semibold text-gray-700 bg-gray-50">
                    Distinct values ({resp.long_tail.length})
                  </summary>
                  <div className="p-3 grid grid-cols-2 gap-x-4 gap-y-1">
                    {resp.long_tail.map((b, i) => (
                      <div key={i} className="text-xs text-gray-700 flex items-baseline justify-between gap-2">
                        <span className="truncate" title={b.canonical}>{b.canonical}</span>
                        <span className="text-gray-400 whitespace-nowrap">({b.count.toLocaleString()})</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}


// ============================================================================
// Admin: PIES attribute KEY merge curation (group synonym keys -> one facet)
// ============================================================================

type KeyMergeMember = { key: string; products: number }
type KeyMergeCluster = {
  label_guess: string
  members: KeyMergeMember[]
  categories: string[]
  category_count: number
  shared_values: string[]
  total_reach: number
}
type ExistingKeyGroup = { group_label: string; members: string[] }

function AdminAttributeKeyCuratorPage() {
  const [clusters, setClusters] = useState<KeyMergeCluster[] | null>(null)
  const [existing, setExisting] = useState<ExistingKeyGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Per-cluster editable label + unchecked members + dismissed (client-side).
  const [labels, setLabels] = useState<Record<number, string>>({})
  const [deselected, setDeselected] = useState<Set<string>>(new Set())
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())

  const memberKey = (ci: number, key: string) => `${ci}:${key}`
  const isPicked = (ci: number, key: string) => !deselected.has(memberKey(ci, key))
  function toggle(ci: number, key: string) {
    setDeselected((prev) => {
      const next = new Set(prev)
      const k = memberKey(ci, key)
      if (next.has(k)) next.delete(k); else next.add(k)
      return next
    })
  }
  const pickedKeys = (c: KeyMergeCluster, ci: number) =>
    c.members.filter((m) => isPicked(ci, m.key)).map((m) => m.key)

  function loadExisting() {
    return fetch('/api/catalog/admin/attribute-key-merges')
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin role)')
        if (r.status === 403) throw new Error('Admin role required to access this page')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: { groups: ExistingKeyGroup[] }) => setExisting(d.groups || []))
  }

  function loadSuggestions() {
    setLoading(true)
    return fetch('/api/catalog/admin/attribute-key-merge-suggestions')
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin role)')
        if (r.status === 403) throw new Error('Admin role required to access this page')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: { clusters: KeyMergeCluster[] }) => {
        setClusters(d.clusters || [])
        setLabels({}); setDeselected(new Set()); setDismissed(new Set())
        setError(null)
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    Promise.all([loadExisting(), loadSuggestions()]).catch((e) =>
      setError(String((e as Error).message || e)),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function mergeCluster(ci: number, label: string, members: string[]) {
    if (members.length < 2) return
    setSaving(true); setSaveError(null)
    try {
      const r = await fetch('/api/catalog/admin/attribute-key-merges', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_label: label.trim(), member_keys: members }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(formatApiError(body, r.status))
      }
      await loadExisting()
      // Drop the confirmed cluster from view (don't re-run the slow scan).
      setDismissed((prev) => new Set(prev).add(ci))
    } catch (e) {
      setSaveError(String((e as Error).message || e))
      setTimeout(() => setSaveError(null), 6000)
    } finally {
      setSaving(false)
    }
  }

  async function dissolve(label: string) {
    setSaving(true); setSaveError(null)
    try {
      const r = await fetch('/api/catalog/admin/attribute-key-merges', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_label: label }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(formatApiError(body, r.status))
      }
      await loadExisting()
    } catch (e) {
      setSaveError(String((e as Error).message || e))
      setTimeout(() => setSaveError(null), 6000)
    } finally {
      setSaving(false)
    }
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-12">
        <h1 className="text-2xl font-bold mb-2">Attribute Key Merge Curation</h1>
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">
          {error}
          {/^Login/.test(error) && (
            <div className="mt-2 text-sm">
              <Link to="/login" className="text-red-700 underline">Sign in</Link> as an admin user.
            </div>
          )}
        </div>
      </div>
    )
  }

  const visibleClusters = (clusters || []).map((c, i) => ({ c, i })).filter(({ i }) => !dismissed.has(i))

  return (
    <div className="max-w-[1100px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Attribute Key Merge Curation</h1>
          <p className="text-sm text-gray-600 max-w-3xl">
            Collapse separate filter groups that describe the <em>same</em> attribute
            (e.g. tank gallons under both &ldquo;Volume&rdquo; and &ldquo;Gallon Capacity&rdquo;).
            Format-only variants like &ldquo;X (in.)&rdquo; fold automatically — these are the
            genuine synonyms that need your call. <strong>Uncheck</strong> any key that
            doesn&rsquo;t belong before merging.
          </p>
        </div>
        <button
          onClick={() => loadSuggestions()}
          disabled={loading}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap"
        >
          {loading ? 'Scanning…' : 'Rescan'}
        </button>
      </div>

      {saveError && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800 flex items-center justify-between">
          <span>{saveError}</span>
          <button onClick={() => setSaveError(null)} className="text-xs text-red-600 hover:underline">Dismiss</button>
        </div>
      )}

      {/* EXISTING merges */}
      <div className="mb-6">
        <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-2">
          Active merges ({existing.length})
        </h2>
        {existing.length === 0 ? (
          <div className="text-sm text-gray-400 border-2 border-dashed rounded p-4">
            No key merges yet. Confirm suggestions below to create them.
          </div>
        ) : (
          <div className="space-y-2">
            {existing.map((g) => (
              <div key={g.group_label} className="flex items-center justify-between gap-3 border border-gray-200 rounded-lg px-4 py-2 bg-white">
                <div className="min-w-0">
                  <span className="font-semibold text-gray-900">{g.group_label}</span>
                  <span className="text-gray-500 text-sm ml-2">
                    ← {g.members.filter((m) => m !== g.group_label).join(' · ') || '(label only)'}
                  </span>
                </div>
                <button
                  onClick={() => dissolve(g.group_label)}
                  disabled={saving}
                  className="text-xs text-gray-500 hover:text-red-700 border border-gray-200 rounded px-2 py-1 hover:border-red-300 disabled:opacity-50 whitespace-nowrap"
                >
                  Dissolve
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SUGGESTED clusters */}
      <h2 className="text-sm font-bold uppercase tracking-wider text-gray-500 mb-2">
        Suggested merges {clusters ? `(${visibleClusters.length})` : ''}
      </h2>
      {loading && clusters === null ? (
        <div className="text-gray-500 text-sm p-6">Scanning the catalog for redundant facet keys…</div>
      ) : visibleClusters.length === 0 ? (
        <div className="text-sm text-gray-500 p-6 text-center border-2 border-dashed rounded">
          Nothing to suggest — all caught up.
        </div>
      ) : (
        <div className="space-y-3">
          {visibleClusters.map(({ c, i }) => {
            const label = labels[i] ?? c.label_guess
            const picked = pickedKeys(c, i)
            return (
              <div key={i} className="border border-gray-200 rounded-lg p-4 bg-white">
                <div className="flex items-baseline justify-between gap-3 mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[10px] uppercase tracking-widest text-gray-500 font-bold">
                      Group label
                    </div>
                    <input
                      type="text"
                      value={label}
                      onChange={(e) => setLabels((prev) => ({ ...prev, [i]: e.target.value }))}
                      className="w-full mt-1 px-2 py-1 text-base font-bold text-gray-900 border border-gray-300 rounded focus:border-red-700 focus:outline-none"
                    />
                  </div>
                  <div className="text-xs text-gray-500 whitespace-nowrap text-right">
                    <div className="font-semibold text-gray-800">{c.category_count}</div>
                    <div>categor{c.category_count === 1 ? 'y' : 'ies'}</div>
                  </div>
                </div>

                <div className="text-[11px] uppercase tracking-wider text-gray-500 font-semibold mb-1 mt-3">
                  Keys to merge — uncheck any that don&rsquo;t belong
                </div>
                <div className="space-y-0.5 mb-2">
                  {c.members.map((m) => {
                    const on = isPicked(i, m.key)
                    return (
                      <label
                        key={m.key}
                        className={`text-sm flex items-baseline gap-2 px-1 py-0.5 rounded cursor-pointer ${
                          on ? 'text-gray-800 hover:bg-gray-50' : 'text-gray-400 line-through'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={on}
                          onChange={() => toggle(i, m.key)}
                          className="self-center"
                        />
                        <span className="flex-1 font-mono text-[13px]">{m.key}</span>
                        <span className="text-gray-400 text-xs">{m.products.toLocaleString()} prod</span>
                      </label>
                    )
                  })}
                </div>

                {c.shared_values.length > 0 && (
                  <div className="mb-3">
                    <div className="text-[10px] uppercase tracking-wider text-gray-400 mb-1">
                      Shared values (evidence)
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {c.shared_values.slice(0, 8).map((v, vi) => (
                        <span key={vi} className="text-[11px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">{v}</span>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    disabled={saving || picked.length < 2 || !label.trim()}
                    onClick={() => mergeCluster(i, label, picked)}
                    className="flex-1 px-3 py-2 text-sm font-semibold bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
                  >
                    ✓ Merge {picked.length} key{picked.length === 1 ? '' : 's'} as &ldquo;{label.trim()}&rdquo;
                  </button>
                  <button
                    disabled={saving}
                    onClick={() => setDismissed((prev) => new Set(prev).add(i))}
                    className="px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
                    title="Hide this suggestion for now (not persisted)"
                  >
                    ✗ Skip
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}


// ============================================================================
// Admin: category image curation
// ============================================================================

type AdminCategory = {
  id: number
  name: string
  full_path: string
  depth: number
  curated_image_url: string | null
  candidate_count: number
  product_count: number
}

type AdminCandidate = {
  product_id: number
  sku: string
  product_name: string
  brand_name: string | null
  image_url: string
  on_hand?: number
  sold_12mo?: number
}

type AdminCandidateResp = {
  id: number
  name: string
  full_path: string
  curated_image_url: string | null
  candidates: AdminCandidate[]
}

// ============================================================================
// AdminCategoryCuratorPage — C1
// ============================================================================
// Mirrors the image-curator layout: left rail = active categories, right
// pane = products IN the selected category with checkboxes + a "Move to"
// bulk-action bar. Owner ask 2026-05-17 (C1).

type CuratorProductRow = {
  id: number; sku: string; name: string; brand: string | null
  image_url: string | null; is_for_sale: boolean
}

function AdminCategoryCuratorPage() {
  const [cats, setCats] = useState<AdminCategory[]>([])
  const [filter, setFilter] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [items, setItems] = useState<CuratorProductRow[]>([])
  const [catName, setCatName] = useState<string>('')
  const [catPath, setCatPath] = useState<string>('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [target, setTarget] = useState<number | ''>('')
  const [loading, setLoading] = useState(true)
  const [productsLoading, setProductsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastResult, setLastResult] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetch('/api/catalog/admin/categories', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin role)')
        if (r.status === 403) throw new Error('Admin role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: AdminCategory[]) => setCats(d))
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (selectedId === null) { setItems([]); setSelected(new Set()); return }
    setProductsLoading(true)
    fetch(`/api/catalog/admin/category-curator/${selectedId}/products?limit=300`, { credentials: 'include' })
      .then((r) => r.json())
      .then((d) => {
        setItems(d.items || [])
        setCatName(d.category_name || '')
        setCatPath(d.category_path || '')
        setSelected(new Set())
      })
      .finally(() => setProductsLoading(false))
  }, [selectedId])

  const visibleCats = cats.filter((c) => c.full_path.toLowerCase().includes(filter.toLowerCase()))
  const targetCats = cats.filter((c) => c.id !== selectedId)

  async function move() {
    if (selectedId === null || !target || selected.size === 0) return
    if (!confirm(`Move ${selected.size} product${selected.size === 1 ? '' : 's'} to "${cats.find((c) => c.id === target)?.full_path}"?`)) return
    setBusy(true); setError(null); setLastResult(null)
    try {
      const r = await fetch('/api/catalog/admin/category-curator/move', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_ids: Array.from(selected),
          from_category_id: selectedId,
          to_category_id: target,
        }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${r.status}`)
      }
      const data = await r.json()
      setLastResult(`Moved ${data.moved_count} product${data.moved_count === 1 ? '' : 's'} to ${cats.find((c) => c.id === target)?.full_path}`)
      // Drop moved items from the current list
      setItems((prev) => prev.filter((p) => !selected.has(p.id)))
      setSelected(new Set())
    } catch (e: any) {
      setError(String(e.message || e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <h1 className="text-2xl font-black uppercase tracking-tight mb-1" style={{ fontFamily: 'Impact, sans-serif' }}>Category curator</h1>
        <p className="text-sm text-gray-500 mb-4">Find misclassified products and bulk-move them to the right category. Every move is audit-logged.</p>
        {error && <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm mb-3">{error}</div>}
        {lastResult && <div className="bg-green-50 border border-green-200 text-green-800 rounded p-3 text-sm mb-3">{lastResult}</div>}
        <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-4">
          {/* Left: categories */}
          <aside className="bg-white border rounded p-3 h-fit sticky top-4 max-h-[80vh] overflow-y-auto">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter categories…"
              className="w-full border border-gray-300 rounded px-2 py-1 text-xs mb-2"
            />
            {loading ? <div className="text-gray-500 text-sm py-4">Loading…</div> : (
              <ul className="space-y-0.5">
                {visibleCats.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => setSelectedId(c.id)}
                      className={`block w-full text-left text-xs px-2 py-1 rounded hover:bg-gray-100 ${selectedId === c.id ? 'bg-red-50 text-red-700 font-semibold' : 'text-gray-700'}`}
                    >
                      {c.full_path}
                      <span className="text-gray-400 ml-1">({c.product_count.toLocaleString()})</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Right: product grid */}
          <main>
            {selectedId === null ? (
              <div className="text-gray-500 text-sm py-12 text-center bg-white border rounded">Pick a category on the left.</div>
            ) : productsLoading ? (
              <div className="text-gray-500 text-sm py-12 text-center bg-white border rounded">Loading products…</div>
            ) : (
              <>
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="font-bold text-gray-900">{catName}</h2>
                    <div className="text-xs text-gray-500">{catPath} · {items.length} products</div>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <button
                      onClick={() => setSelected(new Set(items.map((p) => p.id)))}
                      className="text-gray-600 hover:text-gray-900 underline"
                    >Select all</button>
                    <button
                      onClick={() => setSelected(new Set())}
                      className="text-gray-600 hover:text-gray-900 underline"
                    >Clear</button>
                  </div>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                  {items.map((p) => {
                    const checked = selected.has(p.id)
                    return (
                      <label key={p.id} className={`relative cursor-pointer bg-white border rounded overflow-hidden ${checked ? 'ring-2 ring-red-500' : ''}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            const next = new Set(selected)
                            if (e.target.checked) next.add(p.id); else next.delete(p.id)
                            setSelected(next)
                          }}
                          className="absolute top-2 left-2 w-4 h-4 z-10"
                        />
                        <div className="aspect-square bg-white flex items-center justify-center overflow-hidden">
                          {p.image_url ? (
                            <img src={p.image_url} alt="" loading="lazy" style={{ mixBlendMode: 'multiply' }} className="w-[82%] h-[82%] object-contain" />
                          ) : <span className="text-[9px] uppercase text-gray-300">No image</span>}
                        </div>
                        <div className="p-2 border-t">
                          <div className="text-[10px] uppercase tracking-wider text-gray-500">{p.brand}</div>
                          <div className="font-mono text-[10px] text-gray-500 truncate">{p.sku}</div>
                          <div className="text-xs text-gray-900 line-clamp-2 leading-snug">{p.name}</div>
                        </div>
                      </label>
                    )
                  })}
                </div>

                {/* Bulk-action bar */}
                {selected.size > 0 && (
                  <div className="fixed bottom-0 left-0 right-0 z-30 bg-white border-t shadow-[0_-4px_14px_rgba(0,0,0,0.12)]">
                    <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-3">
                      <div className="font-semibold text-gray-800">{selected.size} selected</div>
                      <select
                        value={target}
                        onChange={(e) => setTarget(e.target.value ? parseInt(e.target.value) : '')}
                        className="border border-gray-300 rounded px-2 py-1 text-sm flex-1 max-w-md"
                      >
                        <option value="">— Move to category —</option>
                        {targetCats.map((c) => (
                          <option key={c.id} value={c.id}>{c.full_path}</option>
                        ))}
                      </select>
                      <button
                        onClick={move}
                        disabled={busy || !target}
                        className="bg-red-700 hover:bg-red-800 text-white text-sm font-bold px-4 py-1.5 rounded disabled:bg-gray-300 disabled:cursor-not-allowed"
                      >{busy ? 'Moving…' : 'Move →'}</button>
                    </div>
                  </div>
                )}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  )
}


// ============================================================================
// AdminResellerFinderPage — S1 + S2
// ============================================================================
//
// Queue tab: walk pending reseller-pair candidates surfaced by the auto-scorer.
// For each pair, show both products side-by-side with attributes + price so
// the admin can hit [Same product ✓] / [Different ✗] / [Skip].
// Margin tab: confirmed pairs sorted by retail-price gap descending.

type ResellerProductCard = {
  id: number; sku: string; name: string; brand: string | null
  image_url: string | null
  retail_price: number | null
  cost: number | null
}
type ResellerMatchRow = {
  match_id: number
  score: number
  status: string
  source: string
  signals: Record<string, unknown>
  canonical: ResellerProductCard
  alias: ResellerProductCard
}
type MarginRow = {
  match_id: number
  expensive: { sku: string; brand: string | null; retail_price: number }
  cheap: { sku: string; brand: string | null; retail_price: number }
  gap_abs: number
  gap_pct: number
}

function AdminResellerFinderPage() {
  const [tab, setTab] = useState<'queue' | 'margins'>('queue')
  const [queueStatus, setQueueStatus] = useState<'pending' | 'confirmed' | 'rejected'>('pending')
  const [items, setItems] = useState<ResellerMatchRow[]>([])
  const [margins, setMargins] = useState<MarginRow[]>([])
  const [marginsGap, setMarginsGap] = useState<number>(25)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [totalPending, setTotalPending] = useState<number>(0)

  async function loadQueue(status: 'pending' | 'confirmed' | 'rejected') {
    setLoading(true); setError(null)
    try {
      const r = await fetch(`/api/catalog/admin/reseller-finder/queue?status=${status}&limit=50`, { credentials: 'include' })
      if (r.status === 401) throw new Error('Login required (admin role)')
      if (r.status === 403) throw new Error('Admin role required to access this page')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setItems(data.items || [])
      setTotalPending(data.total_pending || 0)
    } catch (e: any) {
      setError(String(e.message || e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }
  async function loadMargins() {
    setLoading(true); setError(null)
    try {
      const r = await fetch(`/api/catalog/admin/reseller-finder/margins?min_gap_pct=${marginsGap}&limit=200`, { credentials: 'include' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      setMargins(data.items || [])
    } catch (e: any) {
      setError(String(e.message || e))
      setMargins([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (tab === 'queue') loadQueue(queueStatus)
    else loadMargins()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, queueStatus, marginsGap])

  async function decide(matchId: number, action: 'confirm' | 'reject' | 'reopen') {
    setBusyId(matchId)
    try {
      const r = await fetch(`/api/catalog/admin/reseller-finder/${matchId}/decide?action=${action}`, {
        method: 'POST', credentials: 'include',
      })
      if (r.ok) {
        // Drop the row from the current list (it's no longer in the active status)
        setItems((prev) => prev.filter((m) => m.match_id !== matchId))
      }
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-2xl font-black uppercase tracking-tight" style={{ fontFamily: 'Impact, sans-serif' }}>Reseller finder</h1>
            <p className="text-sm text-gray-500 mt-0.5">Confirm Brand-A-resells-Brand-B private-label pairs. Auto-scorer surfaces candidates; you confirm or reject.</p>
          </div>
        </div>

        <div className="flex items-center gap-2 mb-4">
          <button onClick={() => setTab('queue')} className={`px-3 py-1.5 rounded text-sm font-semibold ${tab === 'queue' ? 'bg-red-700 text-white' : 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50'}`}>Queue {totalPending > 0 && <span className="ml-1 text-[10px] bg-white/30 px-1 rounded">{totalPending}</span>}</button>
          <button onClick={() => setTab('margins')} className={`px-3 py-1.5 rounded text-sm font-semibold ${tab === 'margins' ? 'bg-red-700 text-white' : 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50'}`}>Margin report</button>
          {tab === 'queue' && (
            <div className="ml-auto flex items-center gap-1">
              {(['pending', 'confirmed', 'rejected'] as const).map((s) => (
                <button key={s} onClick={() => setQueueStatus(s)} className={`px-2 py-1 rounded text-xs font-semibold uppercase tracking-wider ${queueStatus === s ? 'bg-gray-900 text-white' : 'bg-white text-gray-600 border border-gray-300 hover:bg-gray-100'}`}>{s}</button>
              ))}
            </div>
          )}
          {tab === 'margins' && (
            <div className="ml-auto flex items-center gap-2 text-xs">
              <label>Gap ≥</label>
              <input type="number" min={0} max={500} value={marginsGap} onChange={(e) => setMarginsGap(Math.max(0, parseInt(e.target.value) || 0))} className="w-16 border rounded px-2 py-1 text-xs" />
              <span>%</span>
            </div>
          )}
        </div>

        {error && <div className="bg-red-50 border border-red-200 text-red-800 rounded p-3 text-sm mb-3">{error}</div>}

        {tab === 'queue' && (
          <div className="space-y-3">
            {loading ? <div className="text-gray-500 py-12 text-center">Loading…</div>
              : items.length === 0 ? (
                <div className="text-gray-500 py-12 text-center bg-white border rounded">
                  No {queueStatus} pairs.
                  {queueStatus === 'pending' && <div className="text-xs text-gray-400 mt-2">Run the scorer: <code>cd /home/titan/titan-truck-website/app &amp;&amp; backend/.venv/bin/python -m scripts.find_reseller_pairs</code></div>}
                </div>
              ) : items.map((m) => (
                <div key={m.match_id} className="bg-white border rounded p-3">
                  <div className="flex items-start gap-3">
                    {/* Canonical */}
                    <div className="flex-1 border-r pr-3">
                      <ResellerProductBlock p={m.canonical} />
                    </div>
                    <div className="px-2 text-center min-w-[120px]">
                      <div className="text-[10px] uppercase tracking-widest text-gray-500 mb-1">Score</div>
                      <div className="text-2xl font-bold text-gray-900">{m.score.toFixed(2)}</div>
                      <div className="text-[10px] text-gray-500 mt-1">{m.source}</div>
                      <div className="mt-3 space-y-1">
                        <button onClick={() => decide(m.match_id, 'confirm')} disabled={busyId === m.match_id} className="block w-full px-2 py-1 bg-green-600 hover:bg-green-700 text-white text-xs font-semibold rounded disabled:opacity-50">Same product ✓</button>
                        <button onClick={() => decide(m.match_id, 'reject')} disabled={busyId === m.match_id} className="block w-full px-2 py-1 bg-gray-200 hover:bg-gray-300 text-gray-800 text-xs font-semibold rounded disabled:opacity-50">Different ✗</button>
                        {queueStatus !== 'pending' && (
                          <button onClick={() => decide(m.match_id, 'reopen')} disabled={busyId === m.match_id} className="block w-full px-2 py-1 bg-white hover:bg-gray-50 text-gray-700 text-xs rounded border border-gray-300 disabled:opacity-50">Reopen</button>
                        )}
                      </div>
                      <div className="mt-2 text-[9px] text-gray-400 text-left">
                        {Object.entries(m.signals).map(([k, v]) => (
                          <div key={k}><span className="text-gray-500">{k}:</span> {String(v)}</div>
                        ))}
                      </div>
                    </div>
                    {/* Alias */}
                    <div className="flex-1 border-l pl-3">
                      <ResellerProductBlock p={m.alias} />
                    </div>
                  </div>
                </div>
              ))}
          </div>
        )}

        {tab === 'margins' && (
          <div>
            {loading ? <div className="text-gray-500 py-12 text-center">Loading…</div>
              : margins.length === 0 ? (
                <div className="text-gray-500 py-12 text-center bg-white border rounded">
                  No confirmed pairs with retail gap ≥ {marginsGap}%.
                </div>
              ) : (
                <div className="bg-white border rounded overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="text-left p-2 text-[10px] uppercase tracking-wider text-gray-500">More expensive</th>
                        <th className="text-left p-2 text-[10px] uppercase tracking-wider text-gray-500">Cheaper sibling</th>
                        <th className="text-right p-2 text-[10px] uppercase tracking-wider text-gray-500">Gap $</th>
                        <th className="text-right p-2 text-[10px] uppercase tracking-wider text-gray-500">Gap %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {margins.map((row) => (
                        <tr key={row.match_id} className="border-t">
                          <td className="p-2">
                            <Link to={`/product/${row.expensive.sku}`} className="text-red-700 hover:underline font-mono text-xs">{row.expensive.sku}</Link>
                            <div className="text-[10px] uppercase tracking-wider text-gray-500">{row.expensive.brand}</div>
                            <div className="text-xs text-gray-700">${row.expensive.retail_price.toFixed(2)}</div>
                          </td>
                          <td className="p-2">
                            <Link to={`/product/${row.cheap.sku}`} className="text-red-700 hover:underline font-mono text-xs">{row.cheap.sku}</Link>
                            <div className="text-[10px] uppercase tracking-wider text-gray-500">{row.cheap.brand}</div>
                            <div className="text-xs text-gray-700">${row.cheap.retail_price.toFixed(2)}</div>
                          </td>
                          <td className="p-2 text-right font-mono text-sm">${row.gap_abs.toFixed(2)}</td>
                          <td className="p-2 text-right font-mono text-sm font-bold text-green-700">{row.gap_pct.toFixed(1)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        )}
      </div>
    </div>
  )
}

function ResellerProductBlock({ p }: { p: ResellerProductCard }) {
  return (
    <div className="flex gap-2">
      <div className="w-24 h-24 bg-white border border-gray-100 rounded flex items-center justify-center overflow-hidden flex-shrink-0">
        {p.image_url ? (
          <img src={p.image_url} alt="" style={{ mixBlendMode: 'multiply' }} className="w-[85%] h-[85%] object-contain" />
        ) : <span className="text-[9px] uppercase text-gray-300">No image</span>}
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] uppercase tracking-wider text-gray-500">{p.brand}</div>
        <Link to={`/product/${p.sku}`} className="font-mono text-xs text-red-700 hover:underline">{p.sku}</Link>
        <div className="text-xs text-gray-900 line-clamp-3 mt-0.5 leading-snug">{p.name}</div>
        <div className="text-xs text-gray-700 mt-1 font-semibold">{p.retail_price != null ? `$${p.retail_price.toFixed(2)}` : '—'}{p.cost != null ? <span className="text-gray-400 font-normal ml-2">cost ${p.cost.toFixed(2)}</span> : null}</div>
      </div>
    </div>
  )
}


function AdminCategoryImagesPage() {
  const [cats, setCats] = useState<AdminCategory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [onlyUnpinned, setOnlyUnpinned] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [cand, setCand] = useState<AdminCandidateResp | null>(null)
  const [candLoading, setCandLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Load category list once
  useEffect(() => {
    setLoading(true)
    fetch('/api/catalog/admin/categories')
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin role)')
        if (r.status === 403) throw new Error('Admin role required to access this page')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: AdminCategory[]) => { setCats(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }, [])

  // Load candidates when a category is selected
  useEffect(() => {
    if (selectedId === null) { setCand(null); return }
    setCandLoading(true)
    fetch(`/api/catalog/admin/categories/${selectedId}/candidates?limit=200`)
      .then((r) => r.json())
      .then((d: AdminCandidateResp) => setCand(d))
      .finally(() => setCandLoading(false))
  }, [selectedId])

  async function pinImage(image_url: string | null) {
    if (selectedId === null) return
    setSaving(true); setSaveError(null)
    const r = await fetch(`/api/catalog/admin/categories/${selectedId}/curated-image`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_url }),
    })
    setSaving(false)
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      setSaveError(formatApiError(body, r.status))
      // Auto-clear after 5s so the curation flow isn't blocked
      setTimeout(() => setSaveError(null), 5000)
      return
    }
    const updated = await r.json()
    // Reflect in left rail + right panel without refetching the whole list
    setCats((prev) => prev.map((c) => c.id === selectedId ? { ...c, curated_image_url: updated.curated_image_url } : c))
    setCand((prev) => prev ? { ...prev, curated_image_url: updated.curated_image_url } : prev)
  }

  const visibleCats = cats.filter((c) => {
    if (onlyUnpinned && c.curated_image_url) return false
    if (filter && !c.full_path.toLowerCase().includes(filter.toLowerCase())) return false
    return true
  })

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-12">
        <h1 className="text-2xl font-bold mb-2">Category Image Curation</h1>
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">
          {error}
          {/^Login/.test(error) && (
            <div className="mt-2 text-sm">
              <Link to="/login" className="text-red-700 underline">Sign in</Link> as an admin user.
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-[1500px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Category Image Curation</h1>
          <p className="text-sm text-gray-600">Pin a representative image for each category. Pinned wins over the algorithmic pick.</p>
        </div>
        <div className="text-xs text-gray-500">
          {cats.length} total · {cats.filter((c) => c.curated_image_url).length} pinned
        </div>
      </div>

      {saveError && (
        <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800 flex items-center justify-between">
          <span>Save failed: {saveError}</span>
          <button onClick={() => setSaveError(null)} className="text-xs text-red-600 hover:underline">Dismiss</button>
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* LEFT RAIL: category list */}
        <aside className="col-span-4 space-y-3">
          <div className="sticky top-2 bg-white pt-2 pb-3 z-10">
            <input
              type="text"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter categories…"
              className="w-full border rounded px-3 py-2 text-sm"
            />
            <label className="flex items-center gap-2 text-sm text-gray-700 mt-2 cursor-pointer">
              <input
                type="checkbox"
                checked={onlyUnpinned}
                onChange={(e) => setOnlyUnpinned(e.target.checked)}
              />
              Only show unpinned
            </label>
          </div>
          {loading && <div className="text-gray-500 text-sm">Loading…</div>}
          <div className="space-y-1 max-h-[78vh] overflow-auto pr-2">
            {visibleCats.map((c) => (
              <button
                key={c.id}
                onClick={() => setSelectedId(c.id)}
                className={`w-full text-left px-3 py-2 rounded border transition flex items-center gap-3 ${
                  selectedId === c.id
                    ? 'border-red-700 bg-red-50'
                    : 'border-gray-200 hover:border-gray-400 bg-white'
                }`}
              >
                <div className="w-12 h-12 flex-shrink-0 bg-gray-50 rounded flex items-center justify-center overflow-hidden">
                  {c.curated_image_url ? (
                    <img src={c.curated_image_url} className="w-full h-full object-contain p-1" />
                  ) : (
                    <div className="text-[10px] text-gray-400 text-center">no pick</div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-gray-900 truncate">{c.name}</div>
                  <div className="text-[11px] text-gray-500 truncate">{c.full_path}</div>
                  <div className="text-[10px] text-gray-400 mt-0.5">
                    {c.curated_image_url ? <span className="text-green-700 font-semibold">PINNED · </span> : null}
                    {c.candidate_count.toLocaleString()} candidate{c.candidate_count === 1 ? '' : 's'}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* RIGHT: candidate gallery */}
        <section className="col-span-8">
          {selectedId === null ? (
            <div className="border-2 border-dashed rounded-lg p-12 text-center text-gray-500">
              Pick a category from the left to see its candidate images.
            </div>
          ) : candLoading ? (
            <div className="text-gray-500">Loading candidates…</div>
          ) : cand ? (
            <>
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-wider text-gray-500">Curating</div>
                  <h2 className="text-xl font-bold text-gray-900">{cand.name}</h2>
                  <div className="text-sm text-gray-600">{cand.full_path}</div>
                </div>
                {cand.curated_image_url && (
                  <button
                    onClick={() => pinImage(null)}
                    disabled={saving}
                    className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
                  >
                    Clear pinned image
                  </button>
                )}
              </div>

              {cand.curated_image_url && (
                <div className="mb-6 p-4 border border-green-300 bg-green-50 rounded flex items-center gap-4">
                  <div className="w-24 h-24 bg-white rounded flex items-center justify-center overflow-hidden shadow">
                    <img src={cand.curated_image_url} className="w-full h-full object-contain p-2" />
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-wider text-green-800 font-semibold">Currently pinned</div>
                    <div className="text-sm text-gray-700 break-all">{cand.curated_image_url}</div>
                  </div>
                </div>
              )}

              {cand.candidates.length === 0 ? (
                <div className="border-2 border-dashed rounded-lg p-12 text-center text-gray-500">
                  No primary images on products in this category yet.
                </div>
              ) : (
                <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-3">
                  {cand.candidates.map((p) => {
                    const isPinned = p.image_url === cand.curated_image_url
                    return (
                      <button
                        key={`${p.product_id}-${p.image_url}`}
                        onClick={() => pinImage(p.image_url)}
                        disabled={saving}
                        className={`group flex flex-col bg-white rounded-lg overflow-hidden border-2 transition ${
                          isPinned
                            ? 'border-green-600 shadow-md'
                            : 'border-transparent shadow-[0_2px_8px_rgba(0,0,0,0.06)] hover:shadow-[0_6px_16px_rgba(0,0,0,0.12)] hover:border-red-700'
                        }`}
                      >
                        <div className="aspect-square bg-white flex items-center justify-center overflow-hidden">
                          <img
                            src={p.image_url}
                            alt={p.product_name}
                            loading="lazy"
                            className="w-[82%] h-[82%] object-contain drop-shadow-md group-hover:scale-105 transition-transform"
                          />
                        </div>
                        <div className="p-2 border-t border-gray-100 text-left">
                          {p.brand_name && <div className="text-[9px] uppercase tracking-wider text-gray-500 truncate">{p.brand_name}</div>}
                          <div className="font-mono text-[10px] text-gray-500 truncate">{p.sku}</div>
                          <div className="text-[11px] text-gray-800 line-clamp-2 leading-tight mt-0.5">{p.product_name}</div>
                          <div className="mt-1 flex items-center gap-2 text-[10px]">
                            {(p.on_hand || 0) > 0 && (
                              <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-800 font-semibold">
                                {p.on_hand} in stock
                              </span>
                            )}
                            {(p.sold_12mo || 0) > 0 && (
                              <span className="text-gray-500">{p.sold_12mo} sold 12mo</span>
                            )}
                          </div>
                          {isPinned && (
                            <div className="mt-1 text-[10px] font-bold text-green-700 uppercase tracking-wider">✓ Pinned</div>
                          )}
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </>
          ) : null}
        </section>
      </div>
    </div>
  )
}

// ============================================================================
// Compare — sticky bar + /compare side-by-side spec sheet
// ============================================================================
//
// State lives in AppCtx (localStorage-backed `titan_compare` array of SKUs,
// capped at 4). Owner ask 2026-05-17 (L6 in the storefront queue).

function CompareToggleButton({ sku, variant = 'card' }: { sku: string; variant?: 'card' | 'list' }) {
  const { isInCompare, toggleCompare, compareSkus } = useApp()
  const on = isInCompare(sku)
  const full = !on && compareSkus.length >= COMPARE_MAX
  const base = 'inline-flex items-center justify-center text-[10px] uppercase tracking-wider font-bold rounded border transition-colors'
  const styles = on
    ? 'bg-red-700 text-white border-red-700 hover:bg-red-800'
    : full
    ? 'bg-gray-50 text-gray-300 border-gray-200 cursor-not-allowed'
    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50 hover:border-gray-400'
  const size = variant === 'card' ? 'h-6 px-2' : 'h-7 px-2.5'
  return (
    <button
      type="button"
      disabled={full}
      onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (!full) toggleCompare(sku) }}
      title={on ? 'Remove from compare' : (full ? `Compare list is full (${COMPARE_MAX})` : 'Add to compare')}
      className={`${base} ${styles} ${size}`}
    >
      <span className="mr-1">{on ? '✓' : '+'}</span>
      Compare
    </button>
  )
}

function CompareBar() {
  const { compareSkus, toggleCompare, clearCompare } = useApp()
  const navigate = useNavigate()
  const loc = useLocation()
  if (compareSkus.length === 0) return null
  // Hide the bar on the compare page itself — redundant once the customer is
  // looking at the spec sheet.
  if (loc.pathname === '/compare') return null
  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-gray-300 shadow-[0_-4px_14px_rgba(0,0,0,0.12)]">
      <div className="max-w-7xl mx-auto px-4 py-2 flex items-center gap-3">
        <div className="text-[11px] uppercase tracking-widest font-bold text-gray-700 flex-shrink-0">
          Compare {compareSkus.length}/{COMPARE_MAX}
        </div>
        <div className="flex-1 flex flex-wrap items-center gap-1.5 min-w-0">
          {compareSkus.map((sku) => (
            <span key={sku} className="inline-flex items-center bg-gray-100 border border-gray-200 rounded-full pl-2.5 pr-1 py-0.5 text-xs">
              <span className="font-mono text-gray-700 truncate max-w-[140px]">{sku}</span>
              <button
                onClick={() => toggleCompare(sku)}
                className="ml-1 w-4 h-4 inline-flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-200 hover:text-gray-900"
                title="Remove"
              >×</button>
            </span>
          ))}
        </div>
        <button
          onClick={clearCompare}
          className="text-xs text-gray-600 hover:text-gray-900 underline flex-shrink-0"
        >Clear</button>
        <button
          onClick={() => navigate(`/compare?skus=${compareSkus.map(encodeURIComponent).join(',')}`)}
          disabled={compareSkus.length < 2}
          className="bg-red-700 hover:bg-red-800 text-white text-sm font-bold px-4 py-1.5 rounded disabled:bg-gray-300 disabled:cursor-not-allowed flex-shrink-0"
        >Compare →</button>
      </div>
    </div>
  )
}

type ComparePdp = {
  id: number
  sku: string
  name: string
  brand: { id: number; name: string; slug: string }
  description: string | null
  prod_code: string | null
  weight_lb: number | null
  dimensions: { length_in: number | null; width_in: number | null; height_in: number | null }
  freight_class: string | null
  cta_mode: string
  images: { url: string; alt: string | null; sort_order: number }[]
  inventory: { warehouse_code: string; warehouse_name: string; on_hand: number; available: number }[]
  total_on_hand: number
  pricing: TierPricingBlock | null
  viewer_tier: string | null
}

function ComparePage() {
  const { toggleCompare, clearCompare, addToCart } = useApp()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const skus = useMemo(() => {
    const raw = params.get('skus') || ''
    return raw.split(',').map((s) => s.trim()).filter(Boolean)
  }, [params])
  const [products, setProducts] = useState<Record<string, ComparePdp | { _error: true }>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (skus.length === 0) { setProducts({}); setLoading(false); return }
    setLoading(true)
    Promise.all(skus.map(async (sku) => {
      try {
        const r = await fetch(`/api/catalog/products/${encodeURIComponent(sku)}`, { credentials: 'include' })
        if (!r.ok) return [sku, { _error: true } as const] as const
        return [sku, await r.json() as ComparePdp] as const
      } catch { return [sku, { _error: true } as const] as const }
    })).then((entries) => {
      const map: Record<string, ComparePdp | { _error: true }> = {}
      for (const [sku, p] of entries) map[sku] = p
      setProducts(map)
      setLoading(false)
    })
  }, [skus.join(',')])

  if (skus.length === 0) {
    return (
      <div className="max-w-3xl mx-auto py-12 px-4 text-center">
        <h1 className="text-2xl font-bold mb-2">No products to compare</h1>
        <p className="text-gray-600 mb-4">Add products to your compare list from the catalog, then come back.</p>
        <Link to="/catalog" className="inline-block bg-red-700 hover:bg-red-800 text-white font-bold px-5 py-2 rounded">Browse catalog →</Link>
      </div>
    )
  }

  function fmt(v: number | null | undefined, suffix = '') {
    if (v == null) return <span className="text-gray-300">—</span>
    return <>{v}{suffix}</>
  }

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 pb-32">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-black uppercase tracking-tight" style={{ fontFamily: 'Impact, sans-serif' }}>Compare {skus.length} products</h1>
          <p className="text-sm text-gray-500 mt-0.5">Side-by-side specs, pricing, and availability.</p>
        </div>
        <button
          onClick={() => { clearCompare(); navigate('/catalog') }}
          className="text-sm text-gray-600 hover:text-gray-900 underline"
        >Clear &amp; return to catalog</button>
      </div>
      {loading ? (
        <div className="text-gray-500 py-12 text-center">Loading…</div>
      ) : (
        <div className="overflow-x-auto -mx-4 px-4">
          <table className="w-full border-collapse text-sm" style={{ minWidth: skus.length * 220 }}>
            <colgroup>
              <col style={{ width: 140 }} />
              {skus.map((s) => <col key={s} />)}
            </colgroup>
            <tbody>
              {/* Image row */}
              <tr>
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Image</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  const img = (p && !('_error' in p)) ? (p.images[0]?.url || null) : null
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      <div className="aspect-square bg-white border border-gray-100 rounded flex items-center justify-center overflow-hidden">
                        {img ? (
                          <img src={img} alt="" style={{ mixBlendMode: 'multiply' }} className="w-[82%] h-[82%] object-contain" />
                        ) : (
                          <span className="text-[10px] uppercase tracking-wider text-gray-400">No image</span>
                        )}
                      </div>
                      <button
                        onClick={() => toggleCompare(sku)}
                        className="mt-2 w-full text-[10px] uppercase tracking-wider text-gray-500 hover:text-red-700"
                      >Remove from compare</button>
                    </td>
                  )
                })}
              </tr>
              {/* Brand + name */}
              <tr>
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Part</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      <div className="text-[10px] uppercase tracking-wider text-gray-500">{p.brand.name}</div>
                      <div className="font-mono text-[11px] text-gray-500">{formatPartNumber(p.sku, p.brand.name)}</div>
                      <Link to={`/product/${p.sku}`} className="font-medium text-gray-900 hover:text-red-700 mt-1 block leading-snug">{p.name}</Link>
                    </td>
                  )
                })}
              </tr>
              {/* Price */}
              <tr className="bg-gray-50">
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Price</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  const pr = p.pricing
                  const isB2B = !!pr && (pr.tier === 'jobber' || pr.tier === 'dealer' || pr.tier === 'municipality')
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      {pr && pr.primary_amount ? (
                        <>
                          <div className={`text-lg font-bold ${isB2B ? 'text-red-700' : 'text-gray-900'}`}>${parseFloat(pr.primary_amount).toFixed(2)}</div>
                          <div className="text-[10px] uppercase tracking-wider text-gray-500">{pr.primary_label}</div>
                        </>
                      ) : <span className="text-gray-300">—</span>}
                    </td>
                  )
                })}
              </tr>
              {/* Stock */}
              <tr>
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">In stock</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  if (!p.total_on_hand) {
                    return <td key={sku} className="p-2 align-top border-l border-gray-100"><span className="text-gray-500">Special order</span></td>
                  }
                  const inStockLocs = p.inventory.filter((i) => i.on_hand > 0)
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      <div className="text-green-700 font-semibold">{p.total_on_hand} in stock</div>
                      <div className="text-[11px] text-gray-500 mt-0.5">
                        {inStockLocs.map((i) => `${i.warehouse_code}: ${i.on_hand}`).join(' · ')}
                      </div>
                    </td>
                  )
                })}
              </tr>
              {/* Weight */}
              <tr className="bg-gray-50">
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Weight</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  return <td key={sku} className="p-2 align-top border-l border-gray-100">{fmt(p.weight_lb, ' lb')}</td>
                })}
              </tr>
              {/* Dimensions */}
              <tr>
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Dimensions (L × W × H)</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  const d = p.dimensions
                  if (d.length_in == null && d.width_in == null && d.height_in == null) {
                    return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  }
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      {fmt(d.length_in, '"')} × {fmt(d.width_in, '"')} × {fmt(d.height_in, '"')}
                    </td>
                  )
                })}
              </tr>
              {/* Freight */}
              <tr className="bg-gray-50">
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Freight class</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  return <td key={sku} className="p-2 align-top border-l border-gray-100">{p.freight_class || <span className="text-gray-300">—</span>}</td>
                })}
              </tr>
              {/* Description (truncated) */}
              <tr>
                <th className="text-left text-[10px] uppercase tracking-widest text-gray-500 font-semibold align-top p-2">Description</th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 align-top border-l border-gray-100 text-gray-300">—</td>
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      <div className="text-[12px] text-gray-700 leading-snug line-clamp-6">{p.description || <span className="text-gray-300">—</span>}</div>
                    </td>
                  )
                })}
              </tr>
              {/* Actions */}
              <tr>
                <th className="p-2"></th>
                {skus.map((sku) => {
                  const p = products[sku]
                  if (!p || '_error' in p) return <td key={sku} className="p-2 border-l border-gray-100"></td>
                  const buyable = p.cta_mode === 'add_to_cart'
                  return (
                    <td key={sku} className="p-2 align-top border-l border-gray-100">
                      <div className="flex flex-col gap-1.5">
                        <Link
                          to={`/product/${p.sku}`}
                          className="text-center border border-gray-300 hover:bg-gray-50 text-gray-800 text-xs font-semibold px-3 py-1.5 rounded"
                        >View details</Link>
                        {buyable && (
                          <button
                            onClick={() => addToCart(p.sku, 1)}
                            className="bg-red-700 hover:bg-red-800 text-white text-xs font-bold px-3 py-1.5 rounded"
                          >Add to Cart</button>
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


// ============================================================================
// App
// ============================================================================

function GlobalQuickOrderHost() {
  const { quickOrderOpen, setQuickOrderOpen } = useApp()
  return quickOrderOpen ? <QuickOrderModal onClose={() => setQuickOrderOpen(false)} /> : null
}

// Admin-only mount for the Shop-as-Customer picker modal.
function ImpersonationHost() {
  const { user, impersonateOpen, setImpersonateOpen } = useApp()
  if (user?.role !== 'admin' || !impersonateOpen) return null
  return <ImpersonationModal onClose={() => setImpersonateOpen(false)} />
}

// Mounts the in-app issue recorder for EVERYONE — any visitor can file a report
// (attributed to their logged-in email, their Cloudflare-Access email, or
// "anonymous"). Only admins get the Reports queue tab (canViewList), so
// customers/testers can record + file but can't browse or resolve others'
// reports.
function ErrorReporterHost() {
  const { user } = useApp()
  const isAdmin = user?.role === 'admin'
  return <ErrorReporter canViewList={isAdmin} />
}

// Reset the window scroll to the top on every route (pathname) change.  Single
// touch-point so EVERY page lands at the top instead of inheriting the previous
// page's scroll offset (which left headings / filters hidden under the header).
// Keyed on pathname only — same-URL query changes (e.g. catalog filters & sort)
// are handled in-component and shouldn't yank the viewport.  POP navigations
// (browser back/forward) are skipped so native scroll restoration still works.
function ScrollToTop() {
  const { pathname } = useLocation()
  const navType = useNavigationType()
  const { cfIdentity } = useApp()
  useEffect(() => {
    if (navType !== 'POP') {
      window.scrollTo({ top: 0 })
    }
  }, [pathname, navType])
  // Page-view beacon for Cloudflare-Access testers — backend logs it per verified
  // identity (client-side route changes never otherwise reach the server). No-op
  // for non-tester/public traffic. Re-runs once cfIdentity resolves so the
  // landing page is captured too.
  useEffect(() => {
    if (!cfIdentity) return
    const search = typeof window !== 'undefined' ? window.location.search : ''
    fetch('/api/signals/pageview', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: pathname + search }),
      keepalive: true,
    }).catch(() => {})
  }, [pathname, cfIdentity])
  return null
}

// Persistent "you're on the live preview" notice. Shows ONLY for Cloudflare-Access
// testers (cfIdentity set) — never on local dev, Tailscale, or production
// nelsontruck.com. Fixed bottom-left so it clears the bottom-right Report launcher;
// dismissible for the browser session.
function PreviewBanner() {
  const { cfIdentity } = useApp()
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try { return sessionStorage.getItem('titan_preview_banner_dismissed') === '1' } catch { return false }
  })
  if (!cfIdentity || dismissed) return null
  return (
    <div className="fixed bottom-5 left-5 z-[99998] max-w-[20rem] pointer-events-none">
      <div className="pointer-events-auto flex items-start gap-2 rounded-xl bg-amber-400/95 text-amber-950 shadow-2xl ring-1 ring-amber-600/40 px-3 py-2 text-xs leading-snug">
        <span className="text-sm leading-none mt-0.5">🛠️</span>
        <span className="flex-1">
          <strong>Preview build</strong> — actively being updated, so you may see
          brief reloads. Spot anything off? Tap <strong>Report a Problem</strong>.
        </span>
        <button
          onClick={() => {
            try { sessionStorage.setItem('titan_preview_banner_dismissed', '1') } catch {}
            setDismissed(true)
          }}
          aria-label="Dismiss preview notice"
          className="ml-1 text-amber-900/70 hover:text-amber-950 font-bold leading-none"
        >×</button>
      </div>
    </div>
  )
}

// ============================================================================
// Banner CMS admin — manage the homepage rotating banner slides (Phase 1).
// Audience-scoped (retail | wholesale | both), schedulable, reorderable.
// ============================================================================
interface BannerSlideRow {
  id: number
  image_url: string
  alt: string
  link_url: string | null
  audience: 'retail' | 'wholesale' | 'both'
  placement: string
  sort_order: number
  is_active: boolean
  starts_at: string | null
  ends_at: string | null
  fill_color: string | null
  edge_fade: boolean
  link_status: 'ok' | 'broken' | 'unknown' | null
  link_checked_at: string | null
  link_error: string | null
  auto_hidden: boolean
}
type BannerDraft = Omit<BannerSlideRow, 'id'> & { id: number | null }

const BLANK_SLIDE: BannerDraft = {
  id: null, image_url: '', alt: '', link_url: '', audience: 'retail',
  placement: 'home_hero', sort_order: 1, is_active: true, starts_at: null, ends_at: null,
  fill_color: null, edge_fade: false,
  link_status: null, link_checked_at: null, link_error: null, auto_hidden: false,
}

// The hero frame is 3.7:1 (matches the production banner images, ~1200x325).
const BANNER_RECOMMENDED_W = 1200
const BANNER_RECOMMENDED_H = 325
const BANNER_ASPECT = BANNER_RECOMMENDED_W / BANNER_RECOMMENDED_H

// A slide link must be blank, an on-site path ('/…'), or a full http(s):// URL.
// Mirrors the backend validator so the admin gets the error before the request.
function validateBannerLink(raw: string | null): string | null {
  const v = (raw ?? '').trim()
  if (!v) return null
  if (v.startsWith('//')) return "Link must not start with '//'. Use a single '/' for on-site paths."
  if (v.startsWith('/')) return null
  if (/^https?:\/\/[^\s/]+/i.test(v)) return null
  return "Link must start with '/' (on-site path) or be a full http(s):// URL."
}

// ---------------------------------------------------------------------------
// Banner link builder — point a slide at a catalog view (category + brand +
// product filters), a landing page, a product, or a custom URL, without
// hand-writing query strings. Emits the same params CatalogBrowse reads
// (category_path / brand / q / in_stock / attr).
// ---------------------------------------------------------------------------
const BANNER_LANDING_PAGES: { path: string; label: string }[] = [
  { path: '/', label: 'Homepage' },
  { path: '/catalog', label: 'All products (catalog)' },
  { path: '/snow-plows', label: 'Snow Plows landing' },
  { path: '/vans', label: 'Van Packages landing' },
  { path: '/aerial-lifts', label: 'Aerial Lifts landing' },
  { path: '/brands', label: 'Brands A–Z directory' },
]

interface BannerCatNode { id: number; name: string; full_path: string; product_count?: number; children?: BannerCatNode[] }
interface BannerBrandOpt { name: string; slug: string; product_count?: number }
interface BannerCatAttr { key: string; values: { value: string; count?: number }[] }

type BannerLinkMode = 'catalog' | 'page' | 'product' | 'custom'
interface BannerLinkState {
  mode: BannerLinkMode
  categoryPath: string
  brands: string[]
  q: string
  inStock: boolean
  attrs: string[]
  pagePath: string
  sku: string
  custom: string
}

function buildCatalogLink(s: BannerLinkState): string {
  const p = new URLSearchParams()
  if (s.categoryPath) p.set('category_path', s.categoryPath)
  for (const b of s.brands) p.append('brand', b)
  if (s.q.trim()) p.set('q', s.q.trim())
  if (s.inStock) p.set('in_stock', '1')
  for (const a of s.attrs) p.append('attr', a)
  const qs = p.toString()
  return qs ? `/catalog?${qs}` : '/catalog'
}

function bannerLinkFromState(s: BannerLinkState): string {
  if (s.mode === 'catalog') return buildCatalogLink(s)
  if (s.mode === 'page') return s.pagePath || '/'
  if (s.mode === 'product') return s.sku.trim() ? `/product/${encodeURIComponent(s.sku.trim())}` : ''
  return s.custom.trim()
}

function parseBannerLink(value: string): BannerLinkState {
  const base: BannerLinkState = { mode: 'custom', categoryPath: '', brands: [], q: '', inStock: false, attrs: [], pagePath: '/', sku: '', custom: '' }
  const v = (value || '').trim()
  if (!v) return base
  if (v.startsWith('/catalog')) {
    const qIdx = v.indexOf('?')
    const sp = new URLSearchParams(qIdx >= 0 ? v.slice(qIdx + 1) : '')
    return {
      ...base, mode: 'catalog',
      categoryPath: sp.get('category_path') || sp.get('category_top') || '',
      brands: sp.getAll('brand').filter(Boolean),
      q: sp.get('q') || '',
      inStock: sp.get('in_stock') === '1' || sp.get('in_stock') === 'true',
      attrs: sp.getAll('attr').filter(Boolean),
    }
  }
  if (v.startsWith('/product/')) return { ...base, mode: 'product', sku: decodeURIComponent(v.slice('/product/'.length)) }
  if (BANNER_LANDING_PAGES.some((pg) => pg.path === v)) return { ...base, mode: 'page', pagePath: v }
  return { ...base, mode: 'custom', custom: v }
}

// Walk the category tree along the selected full_path to get the node chain.
function bannerCatChain(tree: BannerCatNode[], path: string): BannerCatNode[] {
  const names = path ? path.split(' > ') : []
  const chain: BannerCatNode[] = []
  let level: BannerCatNode[] = tree
  for (const nm of names) {
    const node = (level || []).find((n) => n.name === nm)
    if (!node) break
    chain.push(node)
    level = node.children || []
  }
  return chain
}

interface ProductHit { id: number; sku: string; name: string; brand: string | null; image_url: string | null; in_stock: boolean }

// Search-as-you-type SKU picker — same autocomplete endpoint as the storefront
// search bar, so a banner can only point at a real, validated product.
function ProductSkuPicker({ value, onChange }: { value: string; onChange: (sku: string) => void }) {
  const [input, setInput] = useState('')
  const [results, setResults] = useState<ProductHit[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [picked, setPicked] = useState<ProductHit | null>(null)

  useEffect(() => {
    const q = input.trim()
    if (q.length < 2) { setResults([]); setOpen(false); return }
    let alive = true
    setLoading(true)
    const t = setTimeout(() => {
      fetch(`/api/catalog/autocomplete?q=${encodeURIComponent(q)}&parts_limit=8`)
        .then((r) => r.json())
        .then((d) => { if (alive) { setResults(Array.isArray(d?.parts) ? d.parts : []); setOpen(true) } })
        .catch(() => { if (alive) setResults([]) })
        .finally(() => { if (alive) setLoading(false) })
    }, 250)
    return () => { alive = false; clearTimeout(t) }
  }, [input])

  function pick(p: ProductHit) { setPicked(p); onChange(p.sku); setInput(''); setResults([]); setOpen(false) }
  function clearPick() { setPicked(null); onChange(''); setInput('') }

  const currentSku = picked?.sku || value
  if (currentSku) {
    return (
      <div className="flex items-center gap-2 rounded border border-emerald-300 bg-emerald-50 px-2 py-1.5 text-sm">
        {picked?.image_url && <img src={picked.image_url} alt="" className="h-8 w-8 rounded bg-white object-contain" />}
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-emerald-800">✓ {picked?.name || `SKU ${currentSku}`}</div>
          <div className="truncate text-[11px] text-emerald-700">{currentSku}{picked?.brand ? ` · ${picked.brand}` : ''}</div>
        </div>
        <button type="button" onClick={clearPick} className="rounded px-2 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-100">Change</button>
      </div>
    )
  }
  return (
    <div className="relative">
      <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Search part #, name, or brand…" autoComplete="off"
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
      {open && (loading || input.trim().length >= 2) && (
        <div className="absolute z-10 mt-0.5 max-h-72 w-full overflow-auto rounded border border-gray-200 bg-white shadow-lg">
          {loading && <div className="px-2 py-1.5 text-xs text-gray-400">Searching…</div>}
          {!loading && results.length === 0 && <div className="px-2 py-1.5 text-xs text-gray-400">No matching products</div>}
          {results.map((p) => (
            <button key={p.id} type="button" onClick={() => pick(p)} className="flex w-full items-center gap-2 px-2 py-1.5 text-left hover:bg-gray-100">
              {p.image_url ? <img src={p.image_url} alt="" className="h-8 w-8 shrink-0 rounded bg-gray-50 object-contain" /> : <div className="h-8 w-8 shrink-0 rounded bg-gray-100" />}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold text-gray-800">{p.name}</div>
                <div className="truncate text-[11px] text-gray-500">{p.sku}{p.brand ? ` · ${p.brand}` : ''}</div>
              </div>
              {p.in_stock && <span className="shrink-0 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">in stock</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function BannerLinkBuilder({ value, onChange, error }: { value: string; onChange: (v: string) => void; error: string | null }) {
  const [st, setSt] = useState<BannerLinkState>(() => parseBannerLink(value))
  const [tree, setTree] = useState<BannerCatNode[]>([])
  const [brandList, setBrandList] = useState<BannerBrandOpt[]>([])
  const [brandQuery, setBrandQuery] = useState('')
  const [attrs, setAttrs] = useState<BannerCatAttr[] | null>(null)
  const [showFilters, setShowFilters] = useState(false)

  // Emit the computed link whenever builder state changes.
  useEffect(() => { onChange(bannerLinkFromState(st)) }, [st]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load category tree + full brand list once. Use /brands/index (the A–Z
  // directory = every active brand); /brands is capped to the top facet values.
  useEffect(() => {
    fetch('/api/catalog/categories/tree').then((r) => r.json()).then((d) => setTree(Array.isArray(d) ? d : [])).catch(() => {})
    fetch('/api/catalog/brands/index').then((r) => r.json())
      .then((d) => {
        const flat: BannerBrandOpt[] = Array.isArray(d?.groups)
          ? d.groups.flatMap((g: { brands: BannerBrandOpt[] }) => g.brands || [])
          : []
        flat.sort((a, b) => (b.product_count ?? 0) - (a.product_count ?? 0))
        setBrandList(flat)
      }).catch(() => {})
  }, [])

  // Pull product-filter facets for the chosen category (the "mixture of filters").
  useEffect(() => {
    if (st.mode !== 'catalog' || !st.categoryPath || !showFilters) { return }
    let alive = true
    setAttrs(null)
    fetch(`/api/catalog/category-attributes?category_path=${encodeURIComponent(st.categoryPath)}&max_keys=12`)
      .then((r) => r.json()).then((d) => { if (alive) setAttrs(Array.isArray(d?.attributes) ? d.attributes : []) })
      .catch(() => { if (alive) setAttrs([]) })
    return () => { alive = false }
  }, [st.mode, st.categoryPath, showFilters])

  const set = (patch: Partial<BannerLinkState>) => setSt((s) => ({ ...s, ...patch }))
  const chain = bannerCatChain(tree, st.categoryPath)
  // One <select> per chosen level, plus one more if the deepest node has kids.
  const selectLevels: { options: BannerCatNode[]; selected: string }[] = []
  let opts: BannerCatNode[] = tree
  for (let i = 0; ; i++) {
    if (!opts || opts.length === 0) break
    selectLevels.push({ options: opts, selected: chain[i]?.full_path || '' })
    const next = chain[i]?.children
    if (!next || next.length === 0) break
    opts = next
  }
  const brandMatches = brandQuery.trim()
    ? brandList.filter((b) => b.name.toLowerCase().includes(brandQuery.toLowerCase()) && !st.brands.includes(b.name)).slice(0, 8)
    : []
  const computed = bannerLinkFromState(st)

  const TABS: { id: BannerLinkMode; label: string }[] = [
    { id: 'catalog', label: 'Category & filters' },
    { id: 'page', label: 'Landing page' },
    { id: 'product', label: 'Product (SKU)' },
    { id: 'custom', label: 'Custom URL' },
  ]

  return (
    <div className="mb-3">
      <label className="block text-xs font-semibold text-gray-600">Click-through link (optional)</label>
      <div className="mt-1 mb-2 flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button key={t.id} type="button" onClick={() => set({ mode: t.id })}
            className={`rounded px-2.5 py-1 text-xs font-semibold ${st.mode === t.id ? 'bg-red-700 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {st.mode === 'catalog' && (
        <div className="rounded border border-gray-200 bg-gray-50 p-2.5">
          {/* Category cascade */}
          <label className="block text-[11px] font-semibold text-gray-600">Category → subcategory</label>
          <div className="mb-2 space-y-1">
            {selectLevels.map((lvl, i) => (
              <select key={i} value={lvl.selected}
                onChange={(e) => set({ categoryPath: e.target.value || (chain[i - 1]?.full_path || ''), attrs: [] })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                <option value={i === 0 ? '' : (chain[i - 1]?.full_path || '')}>{i === 0 ? '— Any category —' : '— All of the above —'}</option>
                {lvl.options.map((n) => (
                  <option key={n.id} value={n.full_path}>{n.name}{typeof n.product_count === 'number' ? ` (${n.product_count.toLocaleString()})` : ''}</option>
                ))}
              </select>
            ))}
          </div>

          {/* Brand multi-select */}
          <label className="block text-[11px] font-semibold text-gray-600">Brand(s)</label>
          {st.brands.length > 0 && (
            <div className="mb-1 flex flex-wrap gap-1">
              {st.brands.map((b) => (
                <span key={b} className="inline-flex items-center gap-1 rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-semibold text-blue-800">
                  {b}
                  <button type="button" onClick={() => set({ brands: st.brands.filter((x) => x !== b) })} className="text-blue-500 hover:text-blue-900">×</button>
                </span>
              ))}
            </div>
          )}
          <div className="relative mb-2">
            <input value={brandQuery} onChange={(e) => setBrandQuery(e.target.value)} placeholder="Type to add a brand…"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
            {brandMatches.length > 0 && (
              <div className="absolute z-10 mt-0.5 max-h-44 w-full overflow-auto rounded border border-gray-200 bg-white shadow-lg">
                {brandMatches.map((b) => (
                  <button key={b.slug} type="button"
                    onClick={() => { set({ brands: [...st.brands, b.name] }); setBrandQuery('') }}
                    className="flex w-full items-center justify-between px-2 py-1 text-left text-xs hover:bg-gray-100">
                    <span>{b.name}</span>
                    {typeof b.product_count === 'number' && <span className="text-gray-400">{b.product_count.toLocaleString()}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Search term + in-stock */}
          <div className="mb-2 grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[11px] font-semibold text-gray-600">Search term (optional)</label>
              <input value={st.q} onChange={(e) => set({ q: e.target.value })} placeholder="e.g. tonneau" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
            </div>
            <label className="mt-5 flex items-center gap-2 text-xs text-gray-700">
              <input type="checkbox" checked={st.inStock} onChange={(e) => set({ inStock: e.target.checked })} /> In-stock only
            </label>
          </div>

          {/* Product-attribute facets (the "mixture of filters") */}
          {st.categoryPath && (
            <div>
              <button type="button" onClick={() => setShowFilters((v) => !v)} className="text-[11px] font-semibold text-blue-700 hover:underline">
                {showFilters ? '− Hide product filters' : '+ Add product filters (material, length, color…)'}
              </button>
              {showFilters && (
                <div className="mt-1 rounded border border-gray-200 bg-white p-2">
                  {attrs === null ? <div className="text-[11px] text-gray-400">Loading filters…</div>
                    : attrs.length === 0 ? <div className="text-[11px] text-gray-400">No facetable filters for this category.</div>
                    : attrs.map((a) => (
                      <div key={a.key} className="mb-1.5">
                        <div className="text-[11px] font-bold text-gray-700">{a.key}</div>
                        <div className="flex flex-wrap gap-1">
                          {a.values.map((vl) => {
                            const tag = `${a.key}|${vl.value}`
                            const on = st.attrs.includes(tag)
                            return (
                              <button key={vl.value} type="button"
                                onClick={() => set({ attrs: on ? st.attrs.filter((x) => x !== tag) : [...st.attrs, tag] })}
                                className={`rounded px-1.5 py-0.5 text-[11px] ${on ? 'bg-emerald-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`}>
                                {vl.value}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {st.mode === 'page' && (
        <select value={st.pagePath} onChange={(e) => set({ pagePath: e.target.value })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
          {BANNER_LANDING_PAGES.map((pg) => <option key={pg.path} value={pg.path}>{pg.label} — {pg.path}</option>)}
        </select>
      )}

      {st.mode === 'product' && (
        <ProductSkuPicker value={st.sku} onChange={(sku) => set({ sku })} />
      )}

      {st.mode === 'custom' && (
        <input value={st.custom} onChange={(e) => set({ custom: e.target.value })} placeholder="/catalog?brand=YAKIMA  or  https://…"
          className={`w-full rounded border px-2 py-1.5 text-sm ${error ? 'border-red-400 bg-red-50' : 'border-gray-300'}`} />
      )}

      {/* Computed link preview */}
      <div className="mt-2 flex items-center gap-2">
        <span className="text-[11px] font-semibold text-gray-500">Link:</span>
        <code className="flex-1 truncate rounded bg-gray-900 px-2 py-1 text-[11px] text-emerald-300">{computed || '(none — non-clickable)'}</code>
        {computed && (computed.startsWith('http') ? <span className="text-[10px] text-gray-400">opens new tab</span> : <span className="text-[10px] text-gray-400">same tab</span>)}
      </div>
      {error && <p className="mt-1 text-[11px] font-semibold text-red-600">{error}</p>}
    </div>
  )
}

interface SpecialRule { id: string; category: string; title: string; summary: string; detail: string; scope: string; source: string; since: string | null; status: string }

function AdminSpecialRulesPage() {
  const [rules, setRules] = useState<SpecialRule[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/admin/special-rules', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin)')
        if (r.status === 403) throw new Error('Admin role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: SpecialRule[]) => { setRules(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }, [])

  // Group rules by category, preserving first-seen order.
  const groups: { category: string; items: SpecialRule[] }[] = []
  for (const r of rules) {
    let g = groups.find((x) => x.category === r.category)
    if (!g) { g = { category: r.category, items: [] }; groups.push(g) }
    g.items.push(r)
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <div className="mb-2 flex items-center gap-3">
        <Link to="/account" className="text-sm font-semibold text-red-700 hover:underline">← Account</Link>
        <h1 className="text-2xl font-bold">Special Rules</h1>
      </div>
      <p className="mb-5 text-sm text-gray-500">
        Non-obvious display / business rules the storefront applies. This list is generated from the live
        configuration, so it always reflects what the site is actually doing.
      </p>

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>
      ) : loading ? (
        <div className="text-gray-400">Loading…</div>
      ) : rules.length === 0 ? (
        <div className="rounded border border-dashed border-gray-300 p-8 text-center text-gray-500">No special rules configured.</div>
      ) : (
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.category}>
              <h2 className="mb-2 text-xs font-bold uppercase tracking-wide text-gray-400">{g.category}</h2>
              <div className="space-y-3">
                {g.items.map((r) => (
                  <div key={r.id} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-bold text-gray-900">{r.title}</h3>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold uppercase ${r.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-200 text-gray-600'}`}>{r.status}</span>
                    </div>
                    <p className="mt-1 text-sm text-gray-700">{r.summary}</p>
                    <p className="mt-2 text-xs leading-relaxed text-gray-500">{r.detail}</p>
                    <dl className="mt-3 grid grid-cols-[72px_1fr] gap-y-1 text-[11px]">
                      <dt className="font-semibold text-gray-400">Scope</dt><dd className="text-gray-600">{r.scope}</dd>
                      <dt className="font-semibold text-gray-400">Source</dt><dd><code className="text-gray-600">{r.source}</code></dd>
                      {r.since && (<><dt className="font-semibold text-gray-400">Since</dt><dd className="text-gray-600">{r.since}</dd></>)}
                    </dl>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

interface AuditRow { id: number; created_at: string; user_id: number | null; user_email: string | null; action: string; entity_type: string | null; entity_id: string | null; summary: string | null; ip_address: string | null }
interface AuditActor { user_id: number | null; user_email: string | null; count: number }

type HealthReport = {
  date: string; filename: string; xlsx_filename: string | null
  size_kb: number; xlsx_size_kb: number | null; generated_at: string | null
  high: number | null; med: number | null; low: number | null
  sellable: number | null; in_stock: number | null; index_drift: number | null
}

function AdminSiteHealthPage() {
  const [rows, setRows] = useState<HealthReport[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetch('/api/admin/health-reports', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin)')
        if (r.status === 403) throw new Error('Admin role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => { setRows(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }, [])

  const fmt = (iso: string | null) => { if (!iso) return '—'; try { return new Date(iso).toLocaleString() } catch { return iso } }
  const n = (v: number | null) => (v != null ? v.toLocaleString() : '—')

  return (
    <div className="mx-auto max-w-[1150px] px-4 py-6">
      <div className="mb-2 flex items-center gap-3">
        <Link to="/account" className="text-sm font-semibold text-red-700 hover:underline">← Account</Link>
        <h1 className="text-2xl font-bold">Site Health</h1>
      </div>
      <p className="mb-4 max-w-3xl text-sm text-gray-500">
        Nightly product &amp; site health report for this site. Each night produces a <strong>Word document</strong>
        {' '}(narrative + a recommended action for every issue) and a companion <strong>Excel workbook</strong> with
        every flagged SKU and its supporting data — Mfr Part #, AAIA code, Product code, brand, description, price and
        stock — one tab per issue, so any list can be reviewed and worked at the SKU level. Covers missing images,
        descriptions, pricing, categories, product/AAIA codes, parts-master gaps, search-index / inventory freshness,
        and live errors (HTTP, cart/checkout/payment, JS, bots). Generated automatically every night at 5:00 AM.
      </p>

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>
      ) : loading && rows.length === 0 ? (
        <div className="rounded border border-gray-200 bg-gray-50 p-6 text-center text-gray-400">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="rounded border border-gray-200 bg-gray-50 p-6 text-center text-gray-500">
          No reports yet — the first one is generated tonight at 5:00 AM (or run the generator manually).
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Report date</th>
                <th className="px-3 py-2 font-semibold">Generated</th>
                <th className="px-3 py-2 font-semibold">Urgent</th>
                <th className="px-3 py-2 font-semibold">Med</th>
                <th className="px-3 py-2 font-semibold">Low</th>
                <th className="px-3 py-2 font-semibold">Sellable</th>
                <th className="px-3 py-2 font-semibold">In stock</th>
                <th className="px-3 py-2 font-semibold">Downloads</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((r) => (
                <tr key={r.filename} className="align-top hover:bg-gray-50">
                  <td className="whitespace-nowrap px-3 py-2 font-semibold text-gray-800">{r.date}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-500">{fmt(r.generated_at)}</td>
                  <td className="px-3 py-2 font-bold text-red-700">{n(r.high)}</td>
                  <td className="px-3 py-2 text-gray-700">{n(r.med)}</td>
                  <td className="px-3 py-2 text-gray-500">{n(r.low)}</td>
                  <td className="px-3 py-2 text-gray-700">{n(r.sellable)}</td>
                  <td className="px-3 py-2 text-gray-700">
                    {n(r.in_stock)}
                    {r.index_drift ? <span className="ml-1 rounded bg-amber-100 px-1 text-[11px] font-bold text-amber-700">drift {r.index_drift > 0 ? '+' : ''}{r.index_drift}</span> : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <div className="flex items-center gap-2">
                      <a href={`/api/admin/health-reports/${r.filename}/download`}
                         className="inline-flex items-center gap-1 rounded-lg bg-red-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-800">
                        ⬇ Report <span className="font-normal opacity-80">.docx</span>
                      </a>
                      {r.xlsx_filename ? (
                        <a href={`/api/admin/health-reports/${r.xlsx_filename}/data`}
                           className="inline-flex items-center gap-1 rounded-lg bg-emerald-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-800">
                          ⬇ Data <span className="font-normal opacity-80">.xlsx</span>
                        </a>
                      ) : null}
                    </div>
                    <div className="mt-0.5 text-[11px] text-gray-400">
                      {r.size_kb} KB{r.xlsx_size_kb != null ? ` · ${r.xlsx_size_kb} KB` : ''}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function AdminAuditLogPage() {
  const [rows, setRows] = useState<AuditRow[]>([])
  const [actors, setActors] = useState<AuditActor[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [userId, setUserId] = useState('')
  const [action, setAction] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const PER = 100

  useEffect(() => {
    setLoading(true)
    const t = setTimeout(() => {
      const p = new URLSearchParams()
      if (userId) p.set('user_id', userId)
      if (action) p.set('action', action)
      if (q.trim()) p.set('q', q.trim())
      p.set('limit', String(PER)); p.set('offset', String(page * PER))
      fetch(`/api/admin/audit-log?${p.toString()}`, { credentials: 'include' })
        .then((r) => {
          if (r.status === 401) throw new Error('Login required (admin)')
          if (r.status === 403) throw new Error('Admin role required')
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.json()
        })
        .then((d) => { setRows(d.rows); setActors(d.actors); setTotal(d.total); setError(null) })
        .catch((e) => setError(String(e.message || e)))
        .finally(() => setLoading(false))
    }, 250)
    return () => clearTimeout(t)
  }, [userId, action, q, page])

  const ACTION_CLS: Record<string, string> = {
    POST: 'bg-emerald-100 text-emerald-700',
    PUT: 'bg-amber-100 text-amber-700',
    PATCH: 'bg-amber-100 text-amber-700',
    DELETE: 'bg-red-100 text-red-700',
  }
  const fmt = (iso: string) => { try { return new Date(iso).toLocaleString() } catch { return iso } }
  const resetPage = <T,>(setter: (v: T) => void) => (v: T) => { setter(v); setPage(0) }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <div className="mb-4 flex items-center gap-3">
        <Link to="/account" className="text-sm font-semibold text-red-700 hover:underline">← Account</Link>
        <h1 className="text-2xl font-bold">Audit Log</h1>
        <span className="text-sm text-gray-500">Every admin / editor action, newest first.</span>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={userId} onChange={(e) => resetPage(setUserId)(e.target.value)} className="rounded border border-gray-300 px-2 py-1.5 text-sm">
          <option value="">All users</option>
          {actors.map((a) => (
            <option key={`${a.user_id}-${a.user_email}`} value={a.user_id ?? ''}>
              {a.user_email || `user #${a.user_id ?? '—'}`} ({a.count})
            </option>
          ))}
        </select>
        <select value={action} onChange={(e) => resetPage(setAction)(e.target.value)} className="rounded border border-gray-300 px-2 py-1.5 text-sm">
          <option value="">All actions</option>
          {['POST', 'PUT', 'PATCH', 'DELETE'].map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <input value={q} onChange={(e) => resetPage(setQ)(e.target.value)} placeholder="Search path / email / entity…" className="min-w-[240px] flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm" />
      </div>

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-semibold">When</th>
                <th className="px-3 py-2 font-semibold">User</th>
                <th className="px-3 py-2 font-semibold">Action</th>
                <th className="px-3 py-2 font-semibold">Entity</th>
                <th className="px-3 py-2 font-semibold">Detail</th>
                <th className="px-3 py-2 font-semibold">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && rows.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-gray-400">No audit entries match.</td></tr>
              ) : rows.map((r) => (
                <tr key={r.id} className="align-top hover:bg-gray-50">
                  <td className="whitespace-nowrap px-3 py-2 text-gray-600">{fmt(r.created_at)}</td>
                  <td className="whitespace-nowrap px-3 py-2 font-medium text-gray-800">{r.user_email || (r.user_id != null ? `user #${r.user_id}` : '—')}</td>
                  <td className="px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-[11px] font-bold ${ACTION_CLS[r.action] || 'bg-gray-100 text-gray-600'}`}>{r.action}</span></td>
                  <td className="px-3 py-2 text-gray-700">{r.entity_type}{r.entity_id ? <span className="text-gray-400"> #{r.entity_id}</span> : null}</td>
                  <td className="px-3 py-2 text-gray-600"><code className="text-[11px]">{r.summary}</code></td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-400">{r.ip_address || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-3 flex items-center justify-between text-sm text-gray-600">
        <span>{total.toLocaleString()} total{total > 0 ? ` · showing ${page * PER + 1}–${Math.min((page + 1) * PER, total)}` : ''}</span>
        <div className="flex gap-2">
          <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="rounded border border-gray-300 px-3 py-1 font-semibold disabled:opacity-40">← Prev</button>
          <button disabled={(page + 1) * PER >= total} onClick={() => setPage((p) => p + 1)} className="rounded border border-gray-300 px-3 py-1 font-semibold disabled:opacity-40">Next →</button>
        </div>
      </div>
    </div>
  )
}

type BuildIdeaRow = {
  id: number; title: string; detail: string; category: string
  status: string; priority: string; source: string; source_report_id: number | null
  created_by: string; created_at: string | null; updated_at: string | null
}

// Admin-only backlog of future website features (owner ask 2026-06-25). Lives
// at /admin/build-ideas; parks "build this someday" items separate from the
// issue-report queue. Reports can be promoted here via the Issue Recorder.
// Small mic button: dictates speech into a field via the browser Web Speech API
// (Chrome/Edge). Renders nothing where unsupported (e.g. Firefox/Safari) so the
// typed inputs still work. Site is HTTPS so SpeechRecognition.start() is allowed.
function DictationButton({ onText, label }: { onText: (t: string) => void; label?: string }) {
  const [listening, setListening] = useState(false)
  const recRef = useRef<any>(null)
  const SR = typeof window !== 'undefined'
    ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
    : null
  if (!SR) return null
  const toggle = () => {
    if (listening) { recRef.current?.stop(); return }
    const rec = new SR()
    rec.lang = 'en-US'
    rec.interimResults = false
    rec.continuous = true
    rec.onresult = (e: any) => {
      let chunk = ''
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) chunk += e.results[i][0].transcript
      }
      if (chunk.trim()) onText(chunk.trim())
    }
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    recRef.current = rec
    setListening(true)
    try { rec.start() } catch { setListening(false) }
  }
  return (
    <button type="button" onClick={toggle} title={label || 'Dictate'}
      className={`shrink-0 rounded border px-2.5 py-1.5 text-sm ${listening
        ? 'animate-pulse border-red-400 bg-red-50 text-red-700'
        : 'border-gray-300 text-gray-600 hover:bg-gray-100'}`}>
      {listening ? '⏹ Stop' : '🎤'}
    </button>
  )
}

function AdminBuildIdeasPage() {
  const IDEA_STATUSES = ['idea', 'queued', 'in_progress', 'done', 'declined']
  const IDEA_PRIORITIES = ['high', 'normal', 'low']
  const STATUS_CLS: Record<string, string> = {
    idea: 'bg-sky-100 text-sky-700', queued: 'bg-indigo-100 text-indigo-700',
    in_progress: 'bg-amber-100 text-amber-700', done: 'bg-emerald-100 text-emerald-700',
    declined: 'bg-gray-200 text-gray-500',
  }
  const PRIO_CLS: Record<string, string> = {
    high: 'text-red-700 font-bold', normal: 'text-gray-600', low: 'text-gray-400',
  }
  const [rows, setRows] = useState<BuildIdeaRow[]>([])
  const [cats, setCats] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusF, setStatusF] = useState('')
  const [q, setQ] = useState('')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  // Cache of fetched source-report detail (video + transcript) keyed by report
  // id. undefined = not fetched, null = unavailable.
  const [reportCache, setReportCache] = useState<Record<number, { video_path: string | null; transcript: string } | null | undefined>>({})
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ title: '', detail: '', category: '', priority: 'normal', status: 'idea' })
  const [saving, setSaving] = useState(false)
  const [newCat, setNewCat] = useState(false)
  // Category dropdown options = a few seeded buckets merged with whatever
  // categories already exist on saved ideas. "+ Add new…" reveals a text input.
  const SEED_CATS = ['Catalog / Merchandising', 'Parts Lookup', 'Data / Catalog', 'Inventory / Damaged Goods', 'Search', 'Storefront / UX', 'Admin Tools']
  const catOptions = useMemo(
    () => Array.from(new Set([...SEED_CATS, ...cats])).sort((a, b) => a.localeCompare(b)),
    [cats],
  )
  const appendSpeech = (cur: string, add: string) => (cur.trim() ? `${cur.trimEnd()} ${add}` : add)

  const load = useCallback(() => {
    setLoading(true)
    const p = new URLSearchParams()
    if (statusF) p.set('status', statusF)
    if (q.trim()) p.set('q', q.trim())
    fetch(`/api/admin/build-ideas?${p.toString()}`, { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin)')
        if (r.status === 403) throw new Error('Admin role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => { setRows(d.ideas); setCats(d.categories || []); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }, [statusF, q])
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t) }, [load])

  const patch = async (id: number, body: Record<string, string>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...body } : r)))
    await fetch(`/api/admin/build-ideas/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).catch(() => load())
  }
  const remove = async (id: number) => {
    if (!window.confirm('Delete this idea permanently?')) return
    setRows((prev) => prev.filter((r) => r.id !== id))
    await fetch(`/api/admin/build-ideas/${id}`, { method: 'DELETE', credentials: 'include' }).catch(() => load())
  }
  const create = async () => {
    if (!draft.title.trim()) return
    setSaving(true)
    try {
      const r = await fetch('/api/admin/build-ideas', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setAdding(false); setNewCat(false); setDraft({ title: '', detail: '', category: '', priority: 'normal', status: 'idea' })
      load()
    } catch (e) { setError(String((e as Error).message || e)) } finally { setSaving(false) }
  }
  const toggle = (r: BuildIdeaRow) => {
    setExpanded((prev) => { const n = new Set(prev); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n })
    // Lazy-load the source report's recording + transcript on first expand.
    const rid = r.source_report_id
    if (rid != null && !(rid in reportCache)) {
      setReportCache((c) => ({ ...c, [rid]: undefined }))
      fetch(`/api/error-reports/${rid}`, { credentials: 'include' })
        .then((res) => (res.ok ? res.json() : null))
        .then((d) => {
          if (!d) { setReportCache((c) => ({ ...c, [rid]: null })); return }
          const segs = Array.isArray(d.speech_segments)
            ? d.speech_segments.map((s: { text?: string }) => s.text).filter(Boolean).join(' ')
            : ''
          setReportCache((c) => ({ ...c, [rid]: { video_path: d.video_path || null, transcript: segs || d.description || '' } }))
        })
        .catch(() => setReportCache((c) => ({ ...c, [rid]: null })))
    }
  }
  const fmt = (iso: string | null) => { if (!iso) return '—'; try { return new Date(iso).toLocaleDateString() } catch { return iso } }
  const openCount = rows.filter((r) => !['done', 'declined'].includes(r.status)).length

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-6">
      <div className="mb-4 flex items-center gap-3">
        <Link to="/account" className="text-sm font-semibold text-red-700 hover:underline">← Account</Link>
        <h1 className="text-2xl font-bold">💡 Build Ideas</h1>
        <span className="text-sm text-gray-500">Future website features, parked for later. Admin-only.</span>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)} className="rounded border border-gray-300 px-2 py-1.5 text-sm">
          <option value="">All statuses</option>
          {IDEA_STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
        </select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title / detail…" className="min-w-[240px] flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm" />
        <button onClick={() => { setAdding((v) => !v); setNewCat(false) }} className="rounded bg-red-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-red-700">{adding ? 'Cancel' : '+ New idea'}</button>
      </div>

      {adding && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-3">
          {/* Category picker first — pick a bucket, then type or speak the idea. */}
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <label className="text-sm font-semibold text-gray-600">Category</label>
            {newCat ? (
              <>
                <input autoFocus value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })} placeholder="New category name" className="min-w-[200px] rounded border border-gray-300 px-2 py-1.5 text-sm" />
                <button type="button" onClick={() => { setNewCat(false); setDraft({ ...draft, category: '' }) }} className="text-xs text-gray-500 hover:text-red-600">use list instead</button>
              </>
            ) : (
              <select value={draft.category} onChange={(e) => { if (e.target.value === '__new__') { setNewCat(true); setDraft({ ...draft, category: '' }) } else { setDraft({ ...draft, category: e.target.value }) } }} className="min-w-[200px] rounded border border-gray-300 px-2 py-1.5 text-sm">
                <option value="">— Uncategorized —</option>
                {catOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                <option value="__new__">＋ Add new category…</option>
              </select>
            )}
          </div>

          {/* Title — type or dictate. */}
          <div className="mb-2 flex items-start gap-2">
            <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="Title *" className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
            <DictationButton label="Speak the title" onText={(t) => setDraft((d) => ({ ...d, title: appendSpeech(d.title, t) }))} />
          </div>

          {/* Detail — type or speak your idea. */}
          <div className="mb-2 flex items-start gap-2">
            <textarea value={draft.detail} onChange={(e) => setDraft({ ...draft, detail: e.target.value })} placeholder="Detail / notes — type it, or tap 🎤 and speak your idea" rows={3} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
            <DictationButton label="Speak your idea" onText={(t) => setDraft((d) => ({ ...d, detail: appendSpeech(d.detail, t) }))} />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: e.target.value })} className="rounded border border-gray-300 px-2 py-1.5 text-sm">
              {IDEA_PRIORITIES.map((p) => <option key={p} value={p}>{p} priority</option>)}
            </select>
            <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })} className="rounded border border-gray-300 px-2 py-1.5 text-sm">
              {IDEA_STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
            </select>
            <button onClick={create} disabled={saving || !draft.title.trim()} className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-40">{saving ? 'Saving…' : 'Save idea'}</button>
            <span className="text-xs text-gray-400">🎤 Tip: tap the mic to dictate instead of typing (Chrome/Edge).</span>
          </div>
        </div>
      )}

      {error ? (
        <div className="rounded border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Idea</th>
                <th className="px-3 py-2 font-semibold">Category</th>
                <th className="px-3 py-2 font-semibold">Priority</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Source</th>
                <th className="px-3 py-2 font-semibold">Added</th>
                <th className="px-3 py-2 font-semibold"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && rows.length === 0 ? (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-400">Loading…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-400">No ideas yet. Add one above, or promote an issue report from the Issue Recorder.</td></tr>
              ) : rows.map((r) => (
                <tr key={r.id} className="align-top hover:bg-gray-50">
                  <td className="px-3 py-2">
                    <button onClick={() => toggle(r)} className="text-left font-medium text-gray-900 hover:text-red-700">
                      <span className="mr-1 text-gray-400">{expanded.has(r.id) ? '▾' : '▸'}</span>{r.title}
                    </button>
                    {expanded.has(r.id) && (
                      <div className="mt-1 space-y-2">
                        {r.detail && (
                          <div className="whitespace-pre-wrap text-xs leading-snug text-gray-600">{r.detail}</div>
                        )}
                        {r.source_report_id != null && (() => {
                          const rep = reportCache[r.source_report_id]
                          if (rep === undefined) return <div className="text-xs text-gray-400">Loading original report…</div>
                          if (rep === null) return <div className="text-xs text-gray-400">Original report #{r.source_report_id} is no longer available.</div>
                          const dupTranscript = rep.transcript.trim() === (r.detail || '').trim()
                          return (
                            <div className="rounded-md border border-gray-200 bg-gray-50 p-2">
                              <div className="mb-1 text-[11px] font-bold uppercase tracking-wide text-gray-500">📋 Original report #{r.source_report_id}</div>
                              {rep.video_path ? (
                                <video src={rep.video_path} controls preload="metadata" className="w-full max-w-md rounded border border-gray-300 bg-black" />
                              ) : (
                                <div className="text-xs text-gray-400">No screen recording on this report.</div>
                              )}
                              {rep.transcript && !dupTranscript && (
                                <div className="mt-2">
                                  <div className="mb-0.5 text-[11px] font-bold uppercase tracking-wide text-gray-500">🎙 Transcript</div>
                                  <div className="whitespace-pre-wrap text-xs leading-snug text-gray-600">{rep.transcript}</div>
                                </div>
                              )}
                            </div>
                          )
                        })()}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-600">{r.category || '—'}</td>
                  <td className="px-3 py-2">
                    <select value={r.priority} onChange={(e) => patch(r.id, { priority: e.target.value })} className={`rounded border border-gray-200 bg-transparent px-1 py-0.5 text-xs ${PRIO_CLS[r.priority] || ''}`}>
                      {IDEA_PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">
                    <select value={r.status} onChange={(e) => patch(r.id, { status: e.target.value })} className={`rounded px-1.5 py-0.5 text-xs font-semibold ${STATUS_CLS[r.status] || 'bg-gray-100 text-gray-600'}`}>
                      {IDEA_STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
                    </select>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-500">
                    {r.source === 'issue_report' ? <span title="Promoted from an issue report">📋 report #{r.source_report_id}</span> : 'manual'}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-400" title={r.created_by}>{fmt(r.created_at)}</td>
                  <td className="px-3 py-2 text-right"><button onClick={() => remove(r.id)} className="text-xs text-gray-400 hover:text-red-600" title="Delete">✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 text-sm text-gray-500">{rows.length} idea{rows.length === 1 ? '' : 's'} · {openCount} open</div>
    </div>
  )
}

function AdminBannerManagerPage() {
  const [slides, setSlides] = useState<BannerSlideRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<BannerDraft | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState<string | null>(null)
  // Natural pixel size of the draft image, probed in-browser so we can warn the
  // admin when the art is smaller than the 1200x325 frame.
  const [imgDims, setImgDims] = useState<{ w: number; h: number } | null>(null)

  useEffect(() => {
    const url = draft?.image_url?.trim()
    if (!url) { setImgDims(null); return }
    let alive = true
    const probe = new Image()
    probe.onload = () => { if (alive) setImgDims({ w: probe.naturalWidth, h: probe.naturalHeight }) }
    probe.onerror = () => { if (alive) setImgDims(null) }
    probe.src = url
    return () => { alive = false }
  }, [draft?.image_url])

  const linkError = draft ? validateBannerLink(draft.link_url) : null
  const tooSmall = imgDims !== null && (imgDims.w < BANNER_RECOMMENDED_W || imgDims.h < BANNER_RECOMMENDED_H)
  const aspectOff = imgDims !== null && Math.abs(imgDims.w / imgDims.h - BANNER_ASPECT) > 0.6

  function load() {
    setLoading(true)
    fetch('/api/admin/banners', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin or editor)')
        if (r.status === 403) throw new Error('Admin or editor role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: BannerSlideRow[]) => { setSlides(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  async function recheckLinks() {
    setChecking(true); setCheckResult(null)
    try {
      const r = await fetch('/api/admin/banners/check-links', { method: 'POST', credentials: 'include' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      setCheckResult(`Checked ${d.total}: ${d.broken} broken, ${d.unknown} unknown, ${d.auto_hidden} auto-hidden, ${d.restored} restored.`)
      load()
    } catch (e) { setCheckResult(`Check failed: ${String((e as Error).message || e)}`) }
    finally { setChecking(false) }
  }

  async function uploadImage(file: File) {
    setUploading(true); setSaveError(null)
    try {
      const fd = new FormData()
      fd.append('image', file)
      const r = await fetch('/api/admin/banners/upload', { method: 'POST', credentials: 'include', body: fd })
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`)
      const { url } = await r.json()
      setDraft((d) => (d ? { ...d, image_url: url } : d))
    } catch (e) { setSaveError(`Upload failed: ${String((e as Error).message || e)}`) }
    finally { setUploading(false) }
  }

  async function save() {
    if (!draft) return
    if (!draft.image_url.trim()) { setSaveError('Image URL is required'); return }
    const linkProblem = validateBannerLink(draft.link_url)
    if (linkProblem) { setSaveError(linkProblem); return }
    setSaving(true); setSaveError(null)
    const body = {
      image_url: draft.image_url.trim(),
      alt: draft.alt,
      link_url: draft.link_url?.trim() || null,
      audience: draft.audience,
      placement: draft.placement || 'home_hero',
      sort_order: Number(draft.sort_order) || 0,
      is_active: draft.is_active,
      starts_at: draft.starts_at || null,
      ends_at: draft.ends_at || null,
      fill_color: draft.fill_color?.trim() || null,
      edge_fade: draft.edge_fade,
    }
    const isNew = draft.id === null
    const r = await fetch(isNew ? '/api/admin/banners' : `/api/admin/banners/${draft.id}`, {
      method: isNew ? 'POST' : 'PUT',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    setSaving(false)
    if (!r.ok) { setSaveError((await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`); return }
    setDraft(null)
    load()
  }

  async function remove(id: number) {
    if (!confirm('Delete this slide?')) return
    const r = await fetch(`/api/admin/banners/${id}`, { method: 'DELETE', credentials: 'include' })
    if (r.ok) load()
  }

  const AUD_BADGE: Record<string, string> = {
    retail: 'bg-emerald-100 text-emerald-700',
    wholesale: 'bg-blue-100 text-blue-700',
    both: 'bg-purple-100 text-purple-700',
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto p-12">
        <h1 className="text-2xl font-bold mb-2">Banner Manager</h1>
        <div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">{error}</div>
      </div>
    )
  }

  return (
    <div className="max-w-[1500px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Banner Manager</h1>
          <p className="text-sm text-gray-500">Homepage rotating banner — audience-scoped &amp; schedulable.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={recheckLinks} disabled={checking} title="Validate every slide's link and auto-hide broken ones (runs nightly too)"
            className="rounded border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50">
            {checking ? 'Checking…' : '↻ Re-check links'}
          </button>
          <button onClick={() => setDraft({ ...BLANK_SLIDE, sort_order: slides.length ? Math.max(...slides.map((s) => s.sort_order)) + 1 : 1 })} className="rounded bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">+ New slide</button>
        </div>
      </div>
      {checkResult && <div className="mb-3 rounded bg-blue-50 px-3 py-2 text-xs text-blue-800 ring-1 ring-blue-200">{checkResult}</div>}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        {/* list */}
        <div>
          {loading ? <div className="text-gray-500">Loading…</div> : slides.length === 0 ? (
            <div className="rounded border border-dashed border-gray-300 p-8 text-center text-gray-500">No slides yet — add one.</div>
          ) : (
            <div className="space-y-2">
              {slides.map((s) => (
                <div key={s.id} className={`flex items-center gap-3 rounded-lg border bg-white p-2 ${draft?.id === s.id ? 'border-red-400 ring-1 ring-red-200' : 'border-gray-200'}`}>
                  <img src={s.image_url} alt={s.alt} className="h-12 w-44 shrink-0 rounded object-cover bg-gray-100" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-gray-800">{s.alt || <span className="text-gray-400">(no label)</span>}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                      <span className={`rounded px-1.5 py-0.5 font-bold uppercase ${AUD_BADGE[s.audience]}`}>{s.audience}</span>
                      <span className="text-gray-400">#{s.sort_order}</span>
                      {!s.is_active && <span className="rounded bg-gray-200 px-1.5 py-0.5 font-semibold text-gray-600">hidden</span>}
                      {(s.starts_at || s.ends_at) && <span className="text-gray-400">scheduled</span>}
                      {s.link_status === 'broken' && (
                        <span title={s.link_error || 'Broken link'} className="rounded bg-red-100 px-1.5 py-0.5 font-bold text-red-700">
                          ⚠ broken link{s.auto_hidden ? ' · auto-hidden' : ''}
                        </span>
                      )}
                      {s.link_status === 'unknown' && s.link_error && (
                        <span title={s.link_error} className="rounded bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-700">link unverified</span>
                      )}
                    </div>
                    {s.link_status === 'broken' && s.link_error && (
                      <div className="mt-0.5 truncate text-[11px] text-red-600" title={s.link_error}>{s.link_error}</div>
                    )}
                  </div>
                  <button onClick={() => setDraft({ ...s, link_url: s.link_url ?? '', starts_at: s.starts_at, ends_at: s.ends_at })} className="rounded px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50">Edit</button>
                  <button onClick={() => remove(s.id)} className="rounded px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-50">Delete</button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* editor */}
        <aside>
          {draft === null ? (
            <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">Select a slide to edit, or add a new one.</div>
          ) : (
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h2 className="mb-3 text-sm font-bold text-gray-900">{draft.id === null ? 'New slide' : `Edit slide #${draft.id}`}</h2>
              {/* Live preview of the 3.7:1 hero frame — mirrors how the storefront
                  renders this slide (solid-color fill + centered image + edge
                  fade, or the default blurred backdrop). */}
              {draft.image_url && (
                <div
                  className="relative mb-1 w-full overflow-hidden rounded bg-gray-100"
                  style={{ aspectRatio: '3.7 / 1' }}
                >
                  {draft.fill_color ? (
                    <div className="absolute inset-0 flex items-center justify-center" style={{ backgroundColor: draft.fill_color }}>
                      <img
                        src={draft.image_url}
                        alt="preview"
                        className="max-h-full max-w-full object-contain"
                        style={draft.edge_fade ? {
                          WebkitMaskImage: 'linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0, #000 11%, #000 89%, transparent 100%)',
                          WebkitMaskComposite: 'source-in',
                          maskImage: 'linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0, #000 11%, #000 89%, transparent 100%)',
                          maskComposite: 'intersect',
                        } : undefined}
                      />
                    </div>
                  ) : (
                    <>
                      <img src={draft.image_url} aria-hidden className="absolute inset-0 h-full w-full scale-110 object-cover blur-2xl" />
                      <img src={draft.image_url} alt="preview" className="absolute inset-0 h-full w-full object-contain" />
                    </>
                  )}
                </div>
              )}
              {/* Size guidance + live too-small / aspect warning. */}
              <p className="mb-2 text-[11px] leading-snug text-gray-500">
                Recommended: <b>{BANNER_RECOMMENDED_W}×{BANNER_RECOMMENDED_H} px</b> (3.7:1). Larger same-ratio art is fine — it scales down crisply.
                {imgDims && <> This image is <b className={tooSmall || aspectOff ? 'text-amber-700' : 'text-emerald-700'}>{imgDims.w}×{imgDims.h}</b>.</>}
              </p>
              {(tooSmall || aspectOff) && (
                <div className="mb-2 rounded bg-amber-50 px-3 py-2 text-[11px] leading-snug text-amber-800 ring-1 ring-amber-200">
                  {tooSmall && <>This image is smaller than the {BANNER_RECOMMENDED_W}×{BANNER_RECOMMENDED_H} frame and will look soft if stretched. </>}
                  {aspectOff && <>Its shape doesn’t match the wide 3.7:1 banner. </>}
                  Turn on <b>Solid color fill</b> below to center it at full quality and fill the rest with a color (add <b>Feather edges</b> so it blends in).
                  {draft.fill_color === null && (
                    <button
                      type="button"
                      onClick={() => setDraft({ ...draft, fill_color: '#0b1f3a', edge_fade: true })}
                      className="ml-1 font-bold text-amber-900 underline"
                    >Do it for me</button>
                  )}
                </div>
              )}
              <label className="block text-xs font-semibold text-gray-600">Image URL</label>
              <input value={draft.image_url} onChange={(e) => setDraft({ ...draft, image_url: e.target.value })} placeholder="/static/uploads/banners/… or https://…" className="mb-1 w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
              <label className="mb-3 block cursor-pointer text-xs font-semibold text-blue-700 hover:underline">
                {uploading ? 'Uploading…' : '↑ Upload an image instead'}
                <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && uploadImage(e.target.files[0])} />
              </label>

              <label className="block text-xs font-semibold text-gray-600">Label / alt text</label>
              <input value={draft.alt} onChange={(e) => setDraft({ ...draft, alt: e.target.value })} className="mb-3 w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />

              <BannerLinkBuilder
                key={draft.id ?? 'new'}
                value={draft.link_url ?? ''}
                onChange={(v) => setDraft((d) => (d ? { ...d, link_url: v } : d))}
                error={linkError}
              />

              {/* Fill for art that doesn't fill the 3.7:1 frame. */}
              <label className="block text-xs font-semibold text-gray-600">Background fill (for small / off-ratio art)</label>
              <select
                value={draft.fill_color ? 'color' : 'blur'}
                onChange={(e) => setDraft({ ...draft, fill_color: e.target.value === 'color' ? (draft.fill_color || '#0b1f3a') : null })}
                className="mb-2 w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
              >
                <option value="blur">Blurred image (default) — fills the frame with a blurred copy</option>
                <option value="color">Solid color — center the image &amp; fill with a color</option>
              </select>
              {draft.fill_color !== null && (
                <div className="mb-3 rounded border border-gray-200 bg-gray-50 p-2">
                  <div className="flex items-center gap-2">
                    <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(draft.fill_color) ? draft.fill_color : '#0b1f3a'}
                      onChange={(e) => setDraft({ ...draft, fill_color: e.target.value })}
                      className="h-8 w-10 cursor-pointer rounded border border-gray-300" />
                    <input value={draft.fill_color} onChange={(e) => setDraft({ ...draft, fill_color: e.target.value })}
                      placeholder="#0b1f3a" className="w-28 rounded border border-gray-300 px-2 py-1.5 text-sm" />
                    <span className="text-[11px] text-gray-500">Surrounding color</span>
                  </div>
                  <label className="mt-2 flex items-center gap-2 text-xs text-gray-700">
                    <input type="checkbox" checked={draft.edge_fade} onChange={(e) => setDraft({ ...draft, edge_fade: e.target.checked })} />
                    Feather edges — fade the image into the color so it melts into the layout
                  </label>
                </div>
              )}

              <div className="mb-3 grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Audience</label>
                  <select value={draft.audience} onChange={(e) => setDraft({ ...draft, audience: e.target.value as BannerDraft['audience'] })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="retail">Retail</option>
                    <option value="wholesale">Wholesale (B2B)</option>
                    <option value="both">Both</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Sort order</label>
                  <input type="number" value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
                </div>
              </div>

              <div className="mb-3 grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-gray-600">Start (optional)</label>
                  <input type="datetime-local" value={draft.starts_at ? draft.starts_at.slice(0, 16) : ''} onChange={(e) => setDraft({ ...draft, starts_at: e.target.value || null })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-600">End (optional)</label>
                  <input type="datetime-local" value={draft.ends_at ? draft.ends_at.slice(0, 16) : ''} onChange={(e) => setDraft({ ...draft, ends_at: e.target.value || null })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" />
                </div>
              </div>

              <label className="mb-4 flex items-center gap-2 text-sm text-gray-700">
                <input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })} /> Active (visible)
              </label>

              {saveError && <div className="mb-2 rounded bg-red-50 px-3 py-2 text-xs text-red-700">{saveError}</div>}
              <div className="flex gap-2">
                <button onClick={save} disabled={saving || linkError !== null} className="flex-1 rounded bg-red-700 py-2 text-sm font-bold text-white hover:bg-red-800 disabled:bg-gray-400">{saving ? 'Saving…' : 'Save'}</button>
                <button onClick={() => { setDraft(null); setSaveError(null) }} className="rounded border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">Cancel</button>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

// ============================================================================
// Rebate manager admin — manage audience-scoped rebate programs (Rebate Center)
// ============================================================================
interface RebateAdminRow {
  id: number; name: string; brand: string | null; amount_label: string
  rebate_type: string; terms: string | null; threshold_label: string | null
  fine_print: string | null; link_url: string | null
  audience: 'retail' | 'wholesale' | 'both'; claim_method: 'instant' | 'mail_in'
  is_active: boolean; starts_at: string | null; ends_at: string | null; sort_order: number
}
type RebateDraft = Omit<RebateAdminRow, 'id'> & { id: number | null }
const BLANK_REBATE: RebateDraft = {
  id: null, name: '', brand: '', amount_label: '', rebate_type: 'fixed', terms: '',
  threshold_label: '', fine_print: '', link_url: '', audience: 'retail', claim_method: 'mail_in',
  is_active: true, starts_at: null, ends_at: null, sort_order: 1000,
}

function AdminRebateManagerPage() {
  const [rows, setRows] = useState<RebateAdminRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<RebateDraft | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function load() {
    setLoading(true)
    fetch('/api/admin/rebates', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401) throw new Error('Login required (admin or editor)')
        if (r.status === 403) throw new Error('Admin or editor role required')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d: RebateAdminRow[]) => { setRows(d); setError(null) })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  async function save() {
    if (!draft) return
    if (!draft.name.trim() || !draft.amount_label.trim()) { setSaveError('Name and amount are required'); return }
    setSaving(true); setSaveError(null)
    const body = {
      name: draft.name, brand: draft.brand || null, amount_label: draft.amount_label,
      rebate_type: draft.rebate_type, terms: draft.terms || null, threshold_label: draft.threshold_label || null,
      fine_print: draft.fine_print || null, link_url: draft.link_url || null,
      audience: draft.audience, claim_method: draft.claim_method, is_active: draft.is_active,
      starts_at: draft.starts_at || null, ends_at: draft.ends_at || null, sort_order: Number(draft.sort_order) || 0,
    }
    const isNew = draft.id === null
    const r = await fetch(isNew ? '/api/admin/rebates' : `/api/admin/rebates/${draft.id}`, {
      method: isNew ? 'POST' : 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    setSaving(false)
    if (!r.ok) { setSaveError((await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`); return }
    setDraft(null); load()
  }
  async function remove(id: number) {
    if (!confirm('Delete this rebate?')) return
    const r = await fetch(`/api/admin/rebates/${id}`, { method: 'DELETE', credentials: 'include' })
    if (r.ok) load()
  }
  const AUD: Record<string, string> = { retail: 'bg-emerald-100 text-emerald-700', wholesale: 'bg-blue-100 text-blue-700', both: 'bg-purple-100 text-purple-700' }

  if (error) return <div className="max-w-4xl mx-auto p-12"><h1 className="text-2xl font-bold mb-2">Rebate Manager</h1><div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">{error}</div></div>

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div><h1 className="text-2xl font-bold">Rebate Manager</h1><p className="text-sm text-gray-500">Audience-scoped rebate programs shown in the Rebate Center.</p></div>
        <button onClick={() => setDraft({ ...BLANK_REBATE })} className="rounded bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">+ New rebate</button>
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div>
          {loading ? <div className="text-gray-500">Loading…</div> : rows.length === 0 ? (
            <div className="rounded border border-dashed border-gray-300 p-8 text-center text-gray-500">No rebates yet.</div>
          ) : (
            <div className="space-y-2">
              {rows.map((r) => (
                <div key={r.id} className={`flex items-center gap-3 rounded-lg border bg-white p-3 ${draft?.id === r.id ? 'border-red-400 ring-1 ring-red-200' : 'border-gray-200'}`}>
                  <div className="w-20 shrink-0 text-base font-black text-blue-700">{r.amount_label}</div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-gray-800">{r.brand ? `${r.brand} — ` : ''}{r.name}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px]">
                      <span className={`rounded px-1.5 py-0.5 font-bold uppercase ${AUD[r.audience]}`}>{r.audience}</span>
                      <span className="rounded bg-gray-100 px-1.5 py-0.5 font-semibold text-gray-600">{r.claim_method === 'instant' ? 'instant' : 'mail-in'}</span>
                      {r.threshold_label && <span className="text-gray-500">✓ {r.threshold_label}</span>}
                      {!r.is_active && <span className="rounded bg-gray-200 px-1.5 py-0.5 text-gray-600">hidden</span>}
                    </div>
                  </div>
                  <button onClick={() => setDraft({ ...r, brand: r.brand ?? '', terms: r.terms ?? '', threshold_label: r.threshold_label ?? '', fine_print: r.fine_print ?? '', link_url: r.link_url ?? '' })} className="rounded px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50">Edit</button>
                  <button onClick={() => remove(r.id)} className="rounded px-2 py-1 text-xs font-semibold text-red-600 hover:bg-red-50">Delete</button>
                </div>
              ))}
            </div>
          )}
        </div>
        <aside>
          {draft === null ? <div className="rounded-lg border border-dashed border-gray-300 p-8 text-center text-sm text-gray-500">Select a rebate to edit, or add one.</div> : (
            <div className="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
              <h2 className="text-sm font-bold text-gray-900">{draft.id === null ? 'New rebate' : `Edit rebate #${draft.id}`}</h2>
              {([['Program name', 'name'], ['Brand (display)', 'brand'], ['Amount label (e.g. $500, 10% back)', 'amount_label'], ['Terms (e.g. PRO-PLUS plow systems)', 'terms'], ['Qualifying threshold (e.g. $750+ order)', 'threshold_label'], ['Link / claim URL', 'link_url']] as const).map(([label, key]) => (
                <div key={key}><label className="block text-xs font-semibold text-gray-600">{label}</label>
                  <input value={(draft as any)[key] ?? ''} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" /></div>
              ))}
              <div className="grid grid-cols-2 gap-3">
                <div><label className="block text-xs font-semibold text-gray-600">Audience</label>
                  <select value={draft.audience} onChange={(e) => setDraft({ ...draft, audience: e.target.value as RebateDraft['audience'] })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="retail">Retail</option><option value="wholesale">Wholesale (B2B)</option><option value="both">Both</option></select></div>
                <div><label className="block text-xs font-semibold text-gray-600">Claim method</label>
                  <select value={draft.claim_method} onChange={(e) => setDraft({ ...draft, claim_method: e.target.value as RebateDraft['claim_method'] })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="mail_in">Mail-in / portal</option><option value="instant">Instant (in-cart)</option></select></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="block text-xs font-semibold text-gray-600">Type</label>
                  <select value={draft.rebate_type} onChange={(e) => setDraft({ ...draft, rebate_type: e.target.value })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm">
                    <option value="fixed">Fixed $</option><option value="percent">Percent</option><option value="per_unit">Per unit</option></select></div>
                <div><label className="block text-xs font-semibold text-gray-600">Sort</label>
                  <input type="number" value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" /></div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="block text-xs font-semibold text-gray-600">Start</label><input type="datetime-local" value={draft.starts_at ? draft.starts_at.slice(0, 16) : ''} onChange={(e) => setDraft({ ...draft, starts_at: e.target.value || null })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" /></div>
                <div><label className="block text-xs font-semibold text-gray-600">End</label><input type="datetime-local" value={draft.ends_at ? draft.ends_at.slice(0, 16) : ''} onChange={(e) => setDraft({ ...draft, ends_at: e.target.value || null })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" /></div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={draft.is_active} onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })} /> Active (visible)</label>
              {saveError && <div className="rounded bg-red-50 px-3 py-2 text-xs text-red-700">{saveError}</div>}
              <div className="flex gap-2"><button onClick={save} disabled={saving} className="flex-1 rounded bg-red-700 py-2 text-sm font-bold text-white hover:bg-red-800 disabled:bg-gray-400">{saving ? 'Saving…' : 'Save'}</button>
                <button onClick={() => { setDraft(null); setSaveError(null) }} className="rounded border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50">Cancel</button></div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

// ============================================================================
// Deals manager admin — the active "Today's Deals" collection: countdown,
// sidebar highlights, and featured product cards (sku + badge).
// ============================================================================
interface DealItemAdmin {
  id: number; kind: 'product' | 'highlight'; audience: string; sort_order: number; is_active: boolean
  sku: string | null; badge_label: string | null; badge_tone: string | null
  label: string | null; sublabel: string | null; icon: string | null; link_url: string | null
}
interface DealCollectionAdmin {
  id: number; name: string; placement: string; audience: 'retail' | 'wholesale' | 'both'
  is_active: boolean; starts_at: string | null; ends_at: string | null; sort_order: number; items: DealItemAdmin[]
}
const BADGE_TONES = ['rebate', 'clearance', 'free_shipping', 'pro_price', 'limited', 'sale']

function AdminDealsManagerPage() {
  const [colls, setColls] = useState<DealCollectionAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selId, setSelId] = useState<number | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  // add-item forms
  const [hi, setHi] = useState({ label: '', sublabel: '', icon: '', link_url: '' })
  const [pi, setPi] = useState({ sku: '', badge_label: '', badge_tone: 'rebate' })

  function load() {
    setLoading(true)
    fetch('/api/admin/deals', { credentials: 'include' })
      .then((r) => { if (r.status === 401) throw new Error('Login required (admin or editor)'); if (r.status === 403) throw new Error('Admin or editor role required'); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d: DealCollectionAdmin[]) => { setColls(d); setError(null); if (selId === null && d.length) setSelId(d[0].id) })
      .catch((e) => setError(String(e.message || e))).finally(() => setLoading(false))
  }
  useEffect(load, [])
  const sel = colls.find((c) => c.id === selId) || null

  async function api(url: string, method: string, body?: unknown) {
    const r = await fetch(url, { method, credentials: 'include', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
    if (!r.ok) { setMsg((await r.json().catch(() => ({})))?.detail || `HTTP ${r.status}`); return null }
    return r.json().catch(() => ({}))
  }
  async function newCollection() {
    const c = await api('/api/admin/deals', 'POST', { name: "Today's Deals", placement: 'home', audience: 'retail' })
    if (c) { load(); setSelId(c.id) }
  }
  async function saveMeta() {
    if (!sel) return
    const ok = await api(`/api/admin/deals/${sel.id}`, 'PUT', { name: sel.name, audience: sel.audience, is_active: sel.is_active, ends_at: sel.ends_at || null, sort_order: sel.sort_order })
    if (ok) { setMsg('Saved'); load() }
  }
  async function delCollection() { if (sel && confirm('Delete this collection and its items?')) { await api(`/api/admin/deals/${sel.id}`, 'DELETE'); setSelId(null); load() } }
  async function addHighlight() { if (!sel || !hi.label) return; await api(`/api/admin/deals/${sel.id}/items`, 'POST', { kind: 'highlight', audience: sel.audience, ...hi }); setHi({ label: '', sublabel: '', icon: '', link_url: '' }); load() }
  async function addProduct() { if (!sel || !pi.sku) return; await api(`/api/admin/deals/${sel.id}/items`, 'POST', { kind: 'product', audience: sel.audience, ...pi }); setPi({ sku: '', badge_label: '', badge_tone: 'rebate' }); load() }
  async function delItem(id: number) { await api(`/api/admin/deal-items/${id}`, 'DELETE'); load() }
  const patch = (p: Partial<DealCollectionAdmin>) => sel && setColls((cs) => cs.map((c) => c.id === sel.id ? { ...c, ...p } : c))

  if (error) return <div className="max-w-4xl mx-auto p-12"><h1 className="text-2xl font-bold mb-2">Deals Manager</h1><div className="p-4 bg-red-50 border border-red-200 rounded text-red-800">{error}</div></div>

  return (
    <div className="max-w-[1400px] mx-auto px-4 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div><h1 className="text-2xl font-bold">Deals Manager</h1><p className="text-sm text-gray-500">Today's Deals collection — countdown, sidebar highlights, featured products.</p></div>
        <button onClick={newCollection} className="rounded bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">+ New collection</button>
      </div>
      {msg && <div className="mb-3 rounded bg-blue-50 px-3 py-2 text-xs text-blue-800">{msg}</div>}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="space-y-2">
          {loading ? <div className="text-gray-500">Loading…</div> : colls.length === 0 ? <div className="rounded border border-dashed p-6 text-center text-sm text-gray-500">No collections.</div> : colls.map((c) => (
            <button key={c.id} onClick={() => setSelId(c.id)} className={`block w-full rounded-lg border p-3 text-left ${selId === c.id ? 'border-red-400 bg-red-50' : 'border-gray-200 bg-white'}`}>
              <div className="text-sm font-semibold text-gray-800">{c.name}</div>
              <div className="mt-0.5 text-[11px] text-gray-500">{c.audience} · {c.items.length} items {c.is_active ? '' : '· hidden'}</div>
            </button>
          ))}
        </aside>
        {sel && (
          <div className="space-y-5">
            {/* meta */}
            <section className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <div><label className="block text-xs font-semibold text-gray-600">Name</label><input value={sel.name} onChange={(e) => patch({ name: e.target.value })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" /></div>
                <div><label className="block text-xs font-semibold text-gray-600">Audience</label><select value={sel.audience} onChange={(e) => patch({ audience: e.target.value as DealCollectionAdmin['audience'] })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"><option value="retail">Retail</option><option value="wholesale">Wholesale (B2B)</option><option value="both">Both</option></select></div>
                <div><label className="block text-xs font-semibold text-gray-600">Countdown ends</label><input type="datetime-local" value={sel.ends_at ? sel.ends_at.slice(0, 16) : ''} onChange={(e) => patch({ ends_at: e.target.value || null })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" /></div>
                <div><label className="block text-xs font-semibold text-gray-600">Sort</label><input type="number" value={sel.sort_order} onChange={(e) => patch({ sort_order: Number(e.target.value) })} className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" /></div>
              </div>
              <label className="mt-3 flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={sel.is_active} onChange={(e) => patch({ is_active: e.target.checked })} /> Active</label>
              <div className="mt-3 flex gap-2"><button onClick={saveMeta} className="rounded bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">Save collection</button><button onClick={delCollection} className="rounded border border-gray-300 px-4 py-2 text-sm font-semibold text-red-600 hover:bg-red-50">Delete</button></div>
            </section>
            {/* highlights */}
            <section className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-2 text-sm font-bold text-gray-900">Sidebar highlights</h3>
              <div className="space-y-1">
                {sel.items.filter((i) => i.kind === 'highlight').map((i) => (
                  <div key={i.id} className="flex items-center gap-2 rounded bg-gray-50 px-2 py-1 text-sm"><span>{i.icon}</span><span className="font-medium">{i.label}</span><span className="text-gray-400">{i.sublabel}</span><button onClick={() => delItem(i.id)} className="ml-auto text-xs text-red-600">✕</button></div>
                ))}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-5">
                <input placeholder="Icon (emoji)" value={hi.icon} onChange={(e) => setHi({ ...hi, icon: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <input placeholder="Label" value={hi.label} onChange={(e) => setHi({ ...hi, label: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <input placeholder="Sublabel" value={hi.sublabel} onChange={(e) => setHi({ ...hi, sublabel: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <input placeholder="Link URL" value={hi.link_url} onChange={(e) => setHi({ ...hi, link_url: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <button onClick={addHighlight} className="rounded bg-gray-900 px-3 py-1 text-sm font-bold text-white">Add</button>
              </div>
            </section>
            {/* products */}
            <section className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-2 text-sm font-bold text-gray-900">Featured products</h3>
              <div className="space-y-1">
                {sel.items.filter((i) => i.kind === 'product').map((i) => (
                  <div key={i.id} className="flex items-center gap-2 rounded bg-gray-50 px-2 py-1 text-sm"><span className="font-mono text-xs">{i.sku}</span>{i.badge_label && <span className="rounded bg-blue-100 px-1.5 text-[10px] font-bold text-blue-700">{i.badge_label}</span>}<button onClick={() => delItem(i.id)} className="ml-auto text-xs text-red-600">✕</button></div>
                ))}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <input placeholder="SKU (e.g. BHTJ-110001)" value={pi.sku} onChange={(e) => setPi({ ...pi, sku: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <input placeholder="Badge label" value={pi.badge_label} onChange={(e) => setPi({ ...pi, badge_label: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm" />
                <select value={pi.badge_tone} onChange={(e) => setPi({ ...pi, badge_tone: e.target.value })} className="rounded border border-gray-300 px-2 py-1 text-sm">{BADGE_TONES.map((t) => <option key={t} value={t}>{t}</option>)}</select>
                <button onClick={addProduct} className="rounded bg-gray-900 px-3 py-1 text-sm font-bold text-white">Add</button>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

export default function App() {
  // Homepage spatial mockups render their own header/footer chrome, so we
  // suppress the global Header/Footer on /mockup* to avoid a double-header.
  const { pathname, search } = useLocation()
  const isMockup = pathname.startsWith('/mockup')
  // "?window=1" opens a route as a bare, full-window admin workspace (no
  // storefront header/footer) — used by the admin "open in new window" tools.
  const bare = new URLSearchParams(search).has('window')
  return (
    <AppProvider>
      <ScrollToTop />
      {!isMockup && !bare && <Header />}
      <main>
        <Suspense fallback={<div className="p-8 text-gray-500">Loading…</div>}>
        <Routes>
          <Route path="/" element={<NelsonHome />} />
          <Route path="/catalog" element={<CatalogBrowse />} />
          <Route path="/brands" element={<BrandsIndexPage />} />
          <Route path="/categories/:slug" element={<CategoryLandingPage />} />
          <Route path="/fits/:category/:make/:model" element={<FitmentLandingPage />} />
          <Route path="/faq" element={<FaqPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/returns" element={<ReturnsPage />} />
          <Route path="/shipping" element={<ShippingPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />
          <Route path="/admin/content" element={<AdminContentPage />} />
          <Route path="/snow-plows" element={<SnowPlowsLanding />} />
          <Route path="/snow-plows/compare" element={<PlowComparePage />} />
          <Route path="/snow-plows/configurator" element={<PlowConfigurator />} />
          <Route path="/snow-plows/wizard-preview" element={<WizardMockupsPreview />} />
          <Route path="/snow-plows/page-mockups" element={<PageMockupsPreview />} />
          <Route path="/snow-plows/page-mockups-light" element={<LightTacticalMockupsPreview />} />
          <Route path="/snow-plows/page-mockups-l1" element={<L1FamilyMockupsPreview />} />
          <Route path="/aerial-lifts" element={<AerialLiftsLanding />} />
          <Route path="/aerial-lifts/:subcatSlug" element={<AerialLiftsLanding />} />
          <Route path="/snow-alerts/confirm" element={<WinterWatchConfirmPage />} />
          <Route path="/snow-alerts/unsubscribe" element={<WinterWatchUnsubscribePage />} />
          <Route path="/insights/competitive" element={<CompetitiveLandscapePage />} />
          <Route path="/product/:sku" element={<ProductDetail />} />
          <Route path="/cart" element={<CartPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/checkout" element={<CheckoutPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/orders/:webOrderNumber" element={<OrderDetailPage />} />
          <Route path="/admin/category-images" element={<AdminCategoryImagesPage />} />
          <Route path="/admin/attribute-curator" element={<AdminAttributeCuratorPage />} />
          <Route path="/admin/attribute-key-curator" element={<AdminAttributeKeyCuratorPage />} />
          <Route path="/admin/reseller-finder" element={<AdminResellerFinderPage />} />
          <Route path="/admin/category-curator" element={<AdminCategoryCuratorPage />} />
          <Route path="/admin/banners" element={<AdminBannerManagerPage />} />
          <Route path="/admin/audit-log" element={<AdminAuditLogPage />} />
          <Route path="/admin/site-health" element={<AdminSiteHealthPage />} />
          <Route path="/admin/build-ideas" element={<AdminBuildIdeasPage />} />
          <Route path="/showroom/receipts" element={<ShowroomReceiptsPage />} />
          <Route path="/showroom/receipt/:id" element={<ShowroomReceiptPage />} />
          <Route path="/admin/special-rules" element={<AdminSpecialRulesPage />} />
          <Route path="/admin/rebates" element={<AdminRebateManagerPage />} />
          <Route path="/admin/deals" element={<AdminDealsManagerPage />} />
          <Route path="/admin/catalog-visibility" element={<AdminCatalogVisibilityPage />} />
          <Route path="/admin/messages" element={<AdminMessagesPage />} />
          <Route path="/admin/kits" element={<AdminKitsListPage />} />
          <Route path="/admin/kits/new" element={<AdminKitWizardPage />} />
          <Route path="/admin/kits/:id" element={<AdminKitWizardPage />} />
          <Route path="/vans" element={<VansLandingPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/health" element={<Health />} />
        </Routes>
        </Suspense>
      </main>
      {!isMockup && !bare && <Footer />}
      <GlobalQuickOrderHost />
      <ImpersonationHost />
      <CompareBar />
      <ErrorReporterHost />
      <PreviewBanner />
    </AppProvider>
  )
}
