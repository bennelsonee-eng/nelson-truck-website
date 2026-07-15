// ============================================================================
// Marketplace storefront VARIANTS  —  /mockup/market
// ----------------------------------------------------------------------------
// Ben picked the "Marketplace Grid" homepage concept.  This file explores four
// different *types* of marketplace storefront within that direction, so he can
// pick the flavor:
//
//   A. Classic Everything-Store  — Amazon-dense: hero + side promos, many rails
//   B. Big-Box Pro               — Home-Depot/Grainger industrial, department-led
//   C. Modern Boutique           — premium, curated collections, lots of whitespace
//   D. Deal Warehouse            — value-forward, dense product grid + deals rail
//
// All four keep the REAL titantruck.com rotating banner at the top (shared
// RotatingBanner from HomepageMockups).  Pricing follows the house rule: a
// single "Retail $X" line, no MSRP strike-through — the Deal variant uses
// authentic manufacturer-rebate / clearance badges instead of fake was/now.
// (see memory: feedback_map_retail_only)
//
// Static mockups — selectors toggle local state but don't hit the API.
// ============================================================================

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  RotatingBanner, ProductCard, BrandStrip, Trust, UtilityBar,
  Logo, SearchBar, CartButton, CATEGORIES, PRODUCTS,
} from './HomepageMockups'

// ---------------------------------------------------------------------------
// Switcher across the four marketplace flavors
// ---------------------------------------------------------------------------
const TABS = [
  { to: '/mockup/market/classic', label: 'A · Classic' },
  { to: '/mockup/market/bigbox', label: 'B · Big-Box Pro' },
  { to: '/mockup/market/boutique', label: 'C · Boutique' },
  { to: '/mockup/market/deals', label: 'D · Deal Warehouse' },
]
function Switcher({ active }: { active: string }) {
  return (
    <div className="sticky top-0 z-50 border-b border-gray-700 bg-gray-900 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-1 px-4 py-1.5 text-xs">
        <Link to="/mockup/market" className="mr-2 font-bold text-gray-300 hover:text-white">◀ Marketplace types</Link>
        {TABS.map(t => (
          <Link key={t.to} to={t.to}
            className={`rounded px-2.5 py-1 font-semibold ${active === t.to ? 'bg-red-700 text-white' : 'text-gray-300 hover:bg-gray-800'}`}>
            {t.label}
          </Link>
        ))}
        <span className="ml-auto text-[10px] uppercase tracking-widest text-gray-500">static mockup · not wired</span>
      </div>
    </div>
  )
}

const NAV = ['Truck Accessories', 'Truck Equipment', 'Van Equipment', 'Snow & Ice', 'Lighting', 'Towing', 'Tool Boxes', 'Brands']

// A small promo card used in the Classic hero side-stack
function PromoCard({ title, sub, tone, cta }: { title: string; sub: string; tone: string; cta: string }) {
  return (
    <a className={`flex flex-1 flex-col justify-between rounded-lg bg-gradient-to-br ${tone} p-4 text-white shadow-sm transition hover:shadow-md`}>
      <div>
        <div className="text-sm font-extrabold leading-tight">{title}</div>
        <div className="mt-0.5 text-xs text-white/80">{sub}</div>
      </div>
      <span className="mt-3 text-xs font-bold underline-offset-2 hover:underline">{cta} →</span>
    </a>
  )
}

// ===========================================================================
// A — CLASSIC EVERYTHING-STORE  (Amazon-dense)
// ===========================================================================
export function MarketClassic() {
  return (
    <div className="min-h-screen bg-gray-50">
      <Switcher active="/mockup/market/classic" />
      <UtilityBar />
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo to="/mockup/market" />
          <SearchBar flex />
          <CartButton />
        </div>
      </div>
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-1 px-4 text-sm">
          <button className="flex items-center gap-1.5 bg-red-700 px-3 py-2.5 font-bold text-white">☰ All</button>
          {NAV.map(i => <a key={i} className="whitespace-nowrap px-3 py-2.5 font-medium text-gray-700 hover:bg-gray-100 hover:text-red-700">{i}</a>)}
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {/* hero carousel (2/3) + promo side-stack (1/3) */}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
          <RotatingBanner />
          <div className="flex flex-col gap-4">
            <PromoCard title="Financing with Affirm" sub="As low as 0% APR on qualifying orders" tone="from-indigo-700 to-blue-900" cta="See options" />
            <PromoCard title="Become a Dealer" sub="Wholesale pricing for shops & fleets" tone="from-red-700 to-rose-900" cta="Apply now" />
          </div>
        </div>

        {/* deals strip */}
        <div className="flex items-center gap-4 overflow-hidden rounded-lg bg-gray-900 px-5 py-3 text-white">
          <span className="rounded bg-yellow-400 px-2 py-1 text-xs font-extrabold text-gray-900">DEALS</span>
          <span className="text-sm font-medium">Pre-season snow &amp; ice savings — spreaders, plows &amp; parts in stock now</span>
          <a className="ml-auto whitespace-nowrap text-sm font-bold text-yellow-300 hover:underline">Shop deals →</a>
        </div>

        <Rail title="Best sellers" />
        <Trust />
        <Rail title="Snow &amp; Ice — ready to ship" />
        <Rail title="Back in stock" badge="In stock" />

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-gray-500">Brands we stock deep</div>
          <BrandStrip />
        </div>
      </div>
    </div>
  )
}

function Rail({ title, badge }: { title: string; badge?: string }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-3">
        <h3 className="text-lg font-bold text-gray-900" dangerouslySetInnerHTML={{ __html: title }} />
        <a className="text-xs font-semibold text-red-700 hover:underline">See all →</a>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {PRODUCTS.map((p, idx) => <ProductCard key={p.name} p={p} badge={badge && idx % 3 === 0 ? badge : undefined} />)}
      </div>
    </section>
  )
}

// ===========================================================================
// B — BIG-BOX PRO  (industrial / contractor, department-led)
// ===========================================================================
export function MarketBigBox() {
  return (
    <div className="min-h-screen bg-zinc-100">
      <Switcher active="/mockup/market/bigbox" />
      {/* pro top bar */}
      <div className="bg-black text-zinc-300">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-1.5 text-xs">
          <span className="font-semibold text-orange-400">PRO DESK · Volume pricing &amp; will-call pickup in Spokane</span>
          <div className="flex gap-4"><a className="hover:text-white">Quick Order by SKU</a><a className="hover:text-white">Order History</a><a className="hover:text-white">Login</a></div>
        </div>
      </div>
      {/* header */}
      <div className="border-b-4 border-orange-500 bg-zinc-900">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo to="/mockup/market" light />
          <div className="order-last w-full basis-full sm:order-none sm:flex-1 sm:basis-0">
            <div className="flex items-stretch">
              <input placeholder="Search 60,000+ parts by name or SKU…" className="w-full border-2 border-orange-500 px-3 py-2.5 text-sm outline-none" />
              <button className="bg-orange-500 px-5 font-extrabold text-black hover:bg-orange-400">SEARCH</button>
            </div>
          </div>
          <button className="flex items-center gap-2 bg-orange-500 px-4 py-2.5 text-sm font-extrabold text-black hover:bg-orange-400">🛒 CART (0)</button>
        </div>
      </div>
      {/* uppercase nav */}
      <div className="bg-zinc-800">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-1 px-4 text-xs font-bold uppercase tracking-wide text-zinc-200">
          {NAV.map(i => <a key={i} className="px-3 py-2.5 hover:bg-zinc-700 hover:text-orange-400">{i}</a>)}
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <RotatingBanner />

        {/* DOMINANT department grid — square, bordered, industrial */}
        <div>
          <h2 className="mb-3 border-l-4 border-orange-500 pl-3 text-xl font-black uppercase tracking-tight text-zinc-900">Shop by Department</h2>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded border-2 border-zinc-300 bg-zinc-300 sm:grid-cols-3 lg:grid-cols-4">
            {CATEGORIES.map(c => (
              <a key={c.name} className="group flex flex-col items-center justify-center gap-2 bg-white p-6 text-center transition hover:bg-orange-50">
                <span className="text-4xl">{c.icon}</span>
                <span className="text-sm font-bold uppercase leading-tight text-zinc-800 group-hover:text-orange-700">{c.name}</span>
                <span className="text-[10px] font-semibold text-zinc-400">In stock now</span>
              </a>
            ))}
          </div>
        </div>

        {/* pro deals / volume band */}
        <div className="grid gap-4 md:grid-cols-3">
          {[['🏷️', 'Volume pricing', 'Buy 5+, save automatically at checkout'], ['💳', 'Net-30 terms', 'For approved commercial accounts'], ['🚚', 'Jobsite delivery', 'Spokane & Boise metro freight']].map(([i, a, b]) => (
            <div key={a} className="flex items-center gap-3 rounded border-2 border-zinc-200 bg-white p-4">
              <span className="text-3xl">{i}</span>
              <div><div className="text-sm font-extrabold uppercase text-zinc-900">{a}</div><div className="text-xs text-zinc-500">{b}</div></div>
            </div>
          ))}
        </div>

        {/* project bundle callout */}
        <div className="flex flex-col items-start gap-4 rounded border-2 border-orange-500 bg-orange-50 p-5 md:flex-row md:items-center">
          <span className="text-4xl">❄️</span>
          <div className="flex-1">
            <div className="text-lg font-black uppercase text-zinc-900">Complete plow setups — one SKU</div>
            <div className="text-sm text-zinc-600">Mount, blade, harness, controls &amp; lights speced for your exact truck.</div>
          </div>
          <button className="bg-zinc-900 px-5 py-2.5 text-sm font-extrabold uppercase text-white hover:bg-black">Build a setup →</button>
        </div>

        <RailBox title="Top sellers" />
      </div>
    </div>
  )
}

function RailBox({ title }: { title: string }) {
  return (
    <section>
      <h3 className="mb-2 border-l-4 border-orange-500 pl-3 text-lg font-black uppercase text-zinc-900">{title}</h3>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {PRODUCTS.map(p => <ProductCard key={p.name} p={p} />)}
      </div>
    </section>
  )
}

// ===========================================================================
// C — MODERN BOUTIQUE  (premium, curated, whitespace-forward)
// ===========================================================================
const COLLECTIONS = [
  { title: 'Built for Winter', sub: 'Plows, spreaders & ice control', tone: 'from-sky-600 to-blue-800', icon: '❄️' },
  { title: 'Overland Ready', sub: 'Racks, lighting & recovery', tone: 'from-amber-600 to-orange-800', icon: '🏕️' },
  { title: 'Work-Ready Vans', sub: 'Shelving, bulkheads & bins', tone: 'from-emerald-600 to-green-800', icon: '🚐' },
]
export function MarketBoutique() {
  return (
    <div className="min-h-screen bg-white">
      <Switcher active="/mockup/market/boutique" />
      {/* airy header */}
      <div className="border-b border-gray-100">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-3 px-6 py-5">
          <Logo to="/mockup/market" />
          <nav className="hidden flex-1 items-center justify-center gap-7 text-sm font-medium text-gray-600 md:flex">
            {['Accessories', 'Equipment', 'Van', 'Snow & Ice', 'Brands'].map(i => <a key={i} className="hover:text-gray-900">{i}</a>)}
          </nav>
          <div className="flex items-center gap-3">
            <div className="flex items-stretch rounded-full border border-gray-300 px-1">
              <input placeholder="Search…" className="w-40 rounded-full bg-transparent px-3 py-1.5 text-sm outline-none" />
              <button className="px-2 text-gray-500">🔍</button>
            </div>
            <button className="text-xl">🛒</button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl space-y-12 px-6 py-8">
        <RotatingBanner />

        {/* curated collections — 3 big cards */}
        <section>
          <div className="mb-5 text-center">
            <div className="text-xs font-bold uppercase tracking-[0.2em] text-red-600">Curated for the season</div>
            <h2 className="mt-1 text-2xl font-bold tracking-tight text-gray-900">Shop our collections</h2>
          </div>
          <div className="grid gap-5 md:grid-cols-3">
            {COLLECTIONS.map(c => (
              <a key={c.title} className={`group relative flex h-56 flex-col justify-end overflow-hidden rounded-2xl bg-gradient-to-br ${c.tone} p-6 text-white shadow-sm transition hover:shadow-xl`}>
                <span className="absolute right-5 top-5 text-5xl opacity-30">{c.icon}</span>
                <div className="text-xl font-bold">{c.title}</div>
                <div className="text-sm text-white/80">{c.sub}</div>
                <span className="mt-3 inline-flex w-fit rounded-full bg-white/15 px-4 py-1.5 text-xs font-semibold backdrop-blur transition group-hover:bg-white/25">Explore →</span>
              </a>
            ))}
          </div>
        </section>

        {/* editorial category grid */}
        <section>
          <h2 className="mb-5 text-2xl font-bold tracking-tight text-gray-900">Browse by category</h2>
          <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
            {CATEGORIES.slice(0, 8).map(c => (
              <a key={c.name} className="group text-center">
                <div className={`mb-2 grid aspect-square place-items-center rounded-2xl bg-gradient-to-br ${c.tone} text-5xl text-white/90 shadow-sm transition group-hover:shadow-lg`}>{c.icon}</div>
                <div className="text-sm font-semibold text-gray-800 group-hover:text-red-700">{c.name}</div>
              </a>
            ))}
          </div>
        </section>

        {/* featured — bigger cards, generous gaps */}
        <section>
          <div className="mb-5 flex items-end justify-between">
            <h2 className="text-2xl font-bold tracking-tight text-gray-900">Featured this week</h2>
            <a className="text-sm font-semibold text-red-700 hover:underline">View all →</a>
          </div>
          <div className="grid grid-cols-2 gap-5 md:grid-cols-4">
            {PRODUCTS.slice(0, 4).map(p => (
              <div key={p.name} className="group flex flex-col">
                <div className="mb-3 grid aspect-square place-items-center rounded-2xl bg-gray-50 text-6xl ring-1 ring-gray-100 transition group-hover:ring-gray-200">{p.cat}</div>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{p.brand}</div>
                <div className="text-sm font-medium text-gray-800">{p.name}</div>
                <div className="mt-1 text-base font-bold text-gray-900">Retail ${p.price}</div>
              </div>
            ))}
          </div>
        </section>

        {/* newsletter */}
        <section className="rounded-2xl bg-gray-50 p-10 text-center">
          <h3 className="text-xl font-bold text-gray-900">Get the latest promos, products &amp; events</h3>
          <p className="mt-1 text-sm text-gray-500">Join the Titan list — no spam, just good gear.</p>
          <div className="mx-auto mt-4 flex max-w-md items-stretch">
            <input placeholder="you@example.com" className="w-full rounded-l-full border border-gray-300 px-5 py-2.5 text-sm outline-none" />
            <button className="rounded-r-full bg-gray-900 px-6 text-sm font-semibold text-white hover:bg-black">Sign up</button>
          </div>
        </section>
      </div>
    </div>
  )
}

// ===========================================================================
// D — DEAL WAREHOUSE  (value-forward, dense grid + deals rail)
// ===========================================================================
const DEAL_BADGES = ['$300 mfr rebate', 'Clearance', 'Free shipping', 'Pro price', 'Limited stock', null, '$150 rebate', 'Free shipping']

// Live HH:MM:SS countdown — resets on reload (mockup only).
function Countdown() {
  const [s, setS] = useState(4 * 3600 + 35 * 60 + 59)
  useEffect(() => { const t = setInterval(() => setS(p => (p > 0 ? p - 1 : 0)), 1000); return () => clearInterval(t) }, [])
  const p = (n: number) => String(n).padStart(2, '0')
  return <span className="tabular-nums">{p(Math.floor(s / 3600))}:{p(Math.floor((s % 3600) / 60))}:{p(s % 60)}</span>
}

// Today's deal categories (color-coded). Real version comes from a curated/
// seasonal "deal collection" — see wiring plan.
const DEAL_CATS = [
  { label: 'Snow Plows', save: 'Up to $500 rebate', icon: '❄️', tone: 'bg-sky-100 text-sky-700' },
  { label: 'Tool Boxes', save: 'Clearance pricing', icon: '🧰', tone: 'bg-amber-100 text-amber-700' },
  { label: 'Winches', save: 'Free shipping', icon: '⚙️', tone: 'bg-rose-100 text-rose-700' },
  { label: 'Lighting', save: 'Buy 2, save 15%', icon: '💡', tone: 'bg-yellow-100 text-yellow-700' },
  { label: 'Spreaders', save: 'Pre-season pricing', icon: '🧂', tone: 'bg-emerald-100 text-emerald-700' },
]

// Active rebates — shape mirrors what the rebate engine will return: brand,
// amount, the qualifying threshold, and an expiry date.  Rebates are
// AUDIENCE-SCOPED and admin-controlled: a retail shopper and a B2B wholesale
// account see different programs (retail = consumer mail-in/instant; wholesale
// = volume / stock-order programs at much higher thresholds).  In production
// the set is chosen automatically by the viewer's account type; the toggle in
// the Rebate Center here just lets you preview both.
const RETAIL_REBATES = [
  { brand: 'WESTERN', amount: '$500', terms: 'PRO-PLUS plow systems', threshold: 'Complete plow purchase', expires: 'Jun 30' },
  { brand: 'BUYERS', amount: '$150', terms: 'SaltDogg® spreaders', threshold: 'Min. 1.5 yd model', expires: 'Jul 15' },
  { brand: 'SnowEx', amount: '10% back', terms: 'parts & accessories', threshold: '$750+ order', expires: 'Aug 1' },
]
const WHOLESALE_REBATES = [
  { brand: 'WESTERN', amount: '$75 / unit', terms: 'PRO-PLUS plow systems', threshold: 'Buy 5+ units', expires: 'Jun 30' },
  { brand: 'BUYERS', amount: '$2,000', terms: 'SaltDogg® spreader stock order', threshold: '$15,000+ qualifying order', expires: 'Jul 15' },
  { brand: 'SnowEx', amount: '15% back', terms: 'parts & accessories', threshold: '$5,000+ order', expires: 'Aug 1' },
  { brand: 'FISHER', amount: '$120 / unit', terms: 'early-buy stock program', threshold: 'Min. 10 units', expires: 'Aug 31' },
]

// Wholesale ad banner — shown to B2B accounts instead of the retail carousel.
// Like rebates, banner slides are audience-scoped & admin-controlled
// (retail | wholesale | both).  These are CSS placeholders since we don't have
// wholesale artwork yet; in prod they'd be uploaded images in the banner CMS.
const WHOLESALE_BANNERS = [
  { kicker: 'Dealer stock-order season', title: 'EARLY-BUY PRICING IS LIVE', sub: 'Volume rebates + extended dating on pre-season plow & spreader orders', tone: 'from-blue-800 via-blue-900 to-slate-900', cta: 'Shop stock orders' },
  { kicker: 'Approved commercial accounts', title: 'NET-30 TERMS', sub: 'Buy now, invoice later — apply for a wholesale account', tone: 'from-slate-800 via-blue-900 to-indigo-900', cta: 'Apply for terms' },
  { kicker: 'Spokane • Boise', title: 'WILL-CALL & JOBSITE DELIVERY', sub: 'Reserve online, pick up at the counter, or we deliver to the job', tone: 'from-indigo-900 via-blue-900 to-slate-900', cta: 'See pickup options' },
]
function WholesaleBanner() {
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const n = WHOLESALE_BANNERS.length
  useEffect(() => { if (paused) return; const t = setInterval(() => setI(p => (p + 1) % n), 5000); return () => clearInterval(t) }, [paused, n])
  const go = (d: number) => setI(p => (p + d + n) % n)
  return (
    <div className="relative w-full overflow-hidden rounded-xl shadow-sm ring-1 ring-black/5"
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <div className="relative w-full" style={{ aspectRatio: '3.7 / 1' }}>
        {WHOLESALE_BANNERS.map((s, idx) => (
          <div key={idx} className={`absolute inset-0 flex flex-col justify-center bg-gradient-to-br ${s.tone} px-6 text-white transition-opacity duration-700 sm:px-12 ${idx === i ? 'opacity-100' : 'pointer-events-none opacity-0'}`}>
            <span className="absolute right-4 top-3 rounded-full bg-white/10 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-blue-100 ring-1 ring-white/20">Wholesale</span>
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-amber-300 sm:text-xs">{s.kicker}</div>
            <div className="mt-1 text-xl font-black leading-none sm:text-3xl md:text-4xl">{s.title}</div>
            <div className="mt-1.5 max-w-xl text-[11px] text-blue-100 sm:text-sm">{s.sub}</div>
            <button className="mt-3 w-fit rounded bg-amber-400 px-3 py-1.5 text-[11px] font-extrabold text-blue-950 hover:bg-amber-300 sm:text-xs">{s.cta} →</button>
          </div>
        ))}
      </div>
      <button onClick={() => go(-1)} aria-label="Previous slide" className="absolute left-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full bg-black/35 text-white hover:bg-black/60">‹</button>
      <button onClick={() => go(1)} aria-label="Next slide" className="absolute right-2 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full bg-black/35 text-white hover:bg-black/60">›</button>
      <div className="absolute bottom-2 left-1/2 flex -translate-x-1/2 gap-1.5">
        {WHOLESALE_BANNERS.map((_, idx) => (
          <button key={idx} onClick={() => setI(idx)} aria-label={`Go to slide ${idx + 1}`}
            className={`h-2 rounded-full transition-all ${idx === i ? 'w-5 bg-white' : 'w-2 bg-white/50 hover:bg-white/80'}`} />
        ))}
      </div>
    </div>
  )
}

export function MarketDeals() {
  const [audience, setAudience] = useState<'retail' | 'wholesale'>('retail')
  const rebates = audience === 'retail' ? RETAIL_REBATES : WHOLESALE_REBATES
  return (
    <div className="min-h-screen bg-slate-100">
      <Switcher active="/mockup/market/deals" />
      <div className="bg-blue-900 text-blue-100">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-1.5 text-xs">
          {/* Demo control — in prod the audience is set by login/account type
              (or by the b2b. subdomain), not a visible switch. Drives both the
              ad banner and the Rebate Center. */}
          <div className="flex items-center gap-1.5">
            <span className="text-blue-300">Preview as:</span>
            <span className="inline-flex overflow-hidden rounded-full text-[11px] font-bold ring-1 ring-white/25">
              <button onClick={() => setAudience('retail')} className={`px-2.5 py-0.5 transition ${audience === 'retail' ? 'bg-white text-blue-900' : 'text-blue-100 hover:bg-white/10'}`}>Retail</button>
              <button onClick={() => setAudience('wholesale')} className={`px-2.5 py-0.5 transition ${audience === 'wholesale' ? 'bg-white text-blue-900' : 'text-blue-100 hover:bg-white/10'}`}>Wholesale</button>
            </span>
          </div>
          <div className="flex shrink-0 gap-4"><a className="hover:text-white">Rebate center</a><a className="hover:text-white">Login</a></div>
        </div>
      </div>
      <div className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo to="/mockup/market" />
          <div className="order-last w-full basis-full sm:order-none sm:flex-1 sm:basis-0">
            <div className="flex items-stretch">
              <input placeholder="Find a deal — search parts, SKUs, brands…" className="w-full rounded-l border-2 border-blue-600 px-3 py-2 text-sm outline-none" />
              <button className="rounded-r bg-blue-600 px-5 font-bold text-white hover:bg-blue-700">Search</button>
            </div>
          </div>
          <button className="flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-bold text-white hover:bg-blue-700">🛒 Cart (0)</button>
        </div>
        <div className="mx-auto flex max-w-7xl items-center gap-1 overflow-x-auto whitespace-nowrap px-4 text-sm [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <a className="shrink-0 bg-yellow-400 px-3 py-2 font-extrabold text-gray-900">🔥 Today's Deals</a>
          {NAV.slice(0, 6).map(i => <a key={i} className="shrink-0 px-3 py-2 font-medium text-gray-700 hover:text-blue-700">{i}</a>)}
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-5 px-4 py-5">
        {/* Audience-scoped ad banner from the Banner CMS (GET /api/banners).
            Retail falls back to the seeded slides; wholesale falls back to the
            CSS banner until wholesale artwork is uploaded in /admin/banners. */}
        <RotatingBanner audience={audience} fallback={<WholesaleBanner />} />

        <div className="flex flex-col gap-5 md:grid md:grid-cols-[220px_minmax(0,1fr)] lg:grid-cols-[240px_minmax(0,1fr)]">
          {/* today's deals sidebar — modernized.  Order-2 on phones so products
              come first; moves to the left column from iPad width up. */}
          <aside className="order-2 space-y-4 md:order-1">
            {/* Today's Deals */}
            <section className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm">
              <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-red-50 text-sm">🔥</span>
                  <h3 className="text-sm font-bold text-slate-900">Today&apos;s Deals</h3>
                </div>
                <span className="flex items-center gap-1 rounded-full bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white">
                  <span className="text-amber-400">⏱</span><Countdown />
                </span>
              </div>
              <ul className="p-2">
                {DEAL_CATS.map(d => (
                  <li key={d.label}>
                    <a className="group flex items-center gap-3 rounded-xl px-2.5 py-2 transition hover:bg-slate-50">
                      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg text-lg ${d.tone}`}>{d.icon}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-slate-800 group-hover:text-blue-700">{d.label}</span>
                        <span className="block text-xs text-slate-500">{d.save}</span>
                      </span>
                      <span className="text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-blue-600">→</span>
                    </a>
                  </li>
                ))}
              </ul>
              <a className="block border-t border-slate-100 px-4 py-2.5 text-center text-xs font-bold text-blue-700 transition hover:bg-slate-50">See all deals →</a>
            </section>

            {/* Rebate Center — modernized, previews the rebate data model.
                Audience (retail vs B2B wholesale) is admin-controlled per
                rebate; in prod the set is auto-selected by account type. */}
            <section className="overflow-hidden rounded-2xl bg-gradient-to-br from-blue-700 via-blue-800 to-indigo-900 text-white shadow-lg ring-1 ring-white/10">
              <div className="flex items-start justify-between px-4 pt-4">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-blue-200">Rebate Center</div>
                  <div className="text-lg font-black leading-tight">{rebates.length} active rebates</div>
                </div>
                <span className="rounded-full bg-amber-400 px-2.5 py-1 text-[10px] font-extrabold uppercase text-blue-950">New</span>
              </div>
              {/* audience toggle — retail vs B2B wholesale */}
              <div className="mx-3 mt-3 flex gap-1 rounded-lg bg-white/10 p-1 text-[11px] font-bold">
                <button onClick={() => setAudience('retail')}
                  className={`flex-1 rounded-md px-2 py-1.5 transition ${audience === 'retail' ? 'bg-white text-blue-900' : 'text-blue-100 hover:text-white'}`}>Retail</button>
                <button onClick={() => setAudience('wholesale')}
                  className={`flex-1 rounded-md px-2 py-1.5 transition ${audience === 'wholesale' ? 'bg-white text-blue-900' : 'text-blue-100 hover:text-white'}`}>Wholesale (B2B)</button>
              </div>
              <div className="mt-3 space-y-2 px-3 pb-3">
                {rebates.map(r => (
                  <div key={r.brand} className="rounded-xl bg-white/10 p-3 ring-1 ring-white/10 backdrop-blur transition hover:bg-white/15">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-xs font-bold tracking-wide text-white">{r.brand}</span>
                      <span className="whitespace-nowrap text-base font-black text-amber-300">{r.amount}</span>
                    </div>
                    <div className="text-[11px] text-blue-100">{r.terms}</div>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-2 text-[10px] text-blue-200">
                      <span className="inline-flex items-center gap-1"><span className="text-emerald-300">✓</span>{r.threshold}</span>
                      <span>ends {r.expires}</span>
                    </div>
                  </div>
                ))}
              </div>
              <a className="block bg-white/10 px-4 py-2.5 text-center text-xs font-bold text-white transition hover:bg-white/20">Browse all {audience === 'wholesale' ? 'wholesale ' : ''}rebates →</a>
            </section>
          </aside>

          {/* dense, price-forward product grid (no rails) */}
          <div className="order-1 md:order-2">
            <div className="mb-3 flex items-baseline justify-between">
              <h2 className="text-xl font-black text-slate-900">🔥 Today&apos;s top deals</h2>
              <a className="text-sm font-bold text-blue-700 hover:underline">See all deals →</a>
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-4">
              {[...PRODUCTS, ...PRODUCTS].map((p, idx) => {
                const badge = DEAL_BADGES[idx % DEAL_BADGES.length]
                return (
                  <div key={idx} className="group flex flex-col rounded-lg border border-slate-200 bg-white p-3 transition hover:shadow-md">
                    <div className="relative mb-2 grid aspect-square place-items-center rounded bg-gradient-to-br from-slate-100 to-slate-200 text-4xl">
                      {p.cat}
                      {badge && <span className="absolute left-1 top-1 rounded bg-red-600 px-1.5 py-0.5 text-[9px] font-extrabold uppercase text-white">{badge}</span>}
                    </div>
                    <div className="text-[10px] font-bold uppercase text-blue-700">{p.brand}</div>
                    <div className="line-clamp-2 text-xs font-medium text-slate-800">{p.name}</div>
                    <div className="mt-1 text-sm font-black text-slate-900">Retail ${p.price}</div>
                    <div className="text-[10px] font-semibold text-emerald-700">✓ In stock · ships today</div>
                    <button className="mt-2 rounded bg-yellow-400 py-1.5 text-[11px] font-extrabold text-gray-900 hover:bg-yellow-300">Add to Cart</button>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">Shop deals by brand</div>
          <BrandStrip />
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// INDEX / CHOOSER  —  /mockup/market
// ===========================================================================
const VARIANTS = [
  { to: '/mockup/market/classic', tag: 'A', title: 'Classic Everything-Store', tone: 'from-red-600 to-rose-800', blurb: 'Amazon-dense. Hero carousel beside a promo side-stack, a deals strip, then stacked horizontal rails (best sellers, snow & ice, back in stock). Maximum merchandising surface.', best: 'Breadth & browsing' },
  { to: '/mockup/market/bigbox', tag: 'B', title: 'Big-Box Pro', tone: 'from-orange-500 to-zinc-900', blurb: 'Home-Depot / Grainger industrial. Department tile grid dominates, uppercase nav, safety-orange accents, volume-pricing + Net-30 + jobsite-delivery bands, complete-setup bundle. Contractor-first.', best: 'Pros, fleets & shops' },
  { to: '/mockup/market/boutique', tag: 'C', title: 'Modern Boutique', tone: 'from-slate-700 to-slate-900', blurb: 'Premium & curated. Big rounded hero, three “collection” cards (Built for Winter / Overland Ready / Work-Ready Vans), airy category grid, larger product cards, newsletter. Lots of whitespace.', best: 'Brand & retail buyers' },
  { to: '/mockup/market/deals', tag: 'D', title: 'Deal Warehouse', tone: 'from-blue-700 to-blue-950', blurb: 'Value-forward. “Today’s Deals” sidebar with countdown + a dense, price-forward product grid above the fold (rebate / clearance / free-ship badges). High info density, savings-led.', best: 'Deal-seekers & volume' },
]
export function MarketplaceVariantsIndex() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-gray-900 text-white">
        <div className="mx-auto max-w-6xl px-6 py-10">
          <Link to="/mockup" className="text-xs font-bold text-gray-400 hover:text-white">◀ All homepage concepts</Link>
          <div className="mt-3 text-xs font-bold uppercase tracking-widest text-red-400">Marketplace Grid — pick a flavor</div>
          <h1 className="mt-2 text-3xl font-black md:text-4xl">4 types of marketplace storefront</h1>
          <p className="mt-2 max-w-2xl text-sm text-gray-300">You picked the Marketplace direction — here are four distinct takes on it. All four embed the
            <span className="font-semibold text-white"> real titantruck.com rotating banner</span> at the top and follow the “Retail $X” pricing rule. Open one, then use the switcher bar to compare.</p>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-8">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-gray-500">The rotating banner (shared across all 4)</div>
          <RotatingBanner />
        </div>
        <div className="grid gap-5 md:grid-cols-2">
          {VARIANTS.map(v => (
            <Link key={v.to} to={v.to} className="group flex flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg">
              <div className={`relative h-36 bg-gradient-to-br ${v.tone} p-5 text-white`}>
                <div className="text-6xl font-black opacity-25">{v.tag}</div>
                <div className="absolute bottom-4 left-5 text-xl font-bold">{v.title}</div>
              </div>
              <div className="flex flex-1 flex-col p-5">
                <p className="text-sm text-gray-600">{v.blurb}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-700">Best for: {v.best}</span>
                  <span className="text-sm font-bold text-red-700 group-hover:underline">Open →</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
