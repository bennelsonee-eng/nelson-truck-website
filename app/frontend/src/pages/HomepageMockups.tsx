// ============================================================================
// Homepage spatial-layout MOCKUPS  —  /mockup
// ----------------------------------------------------------------------------
// Four self-contained homepage concepts for Ben to compare side-by-side, each
// exploring a different SPATIAL arrangement (Amazon-storefront inspired):
//
//   1. Marketplace Grid     — top mega-menu, hero carousel, quad tiles, rails
//   2. Garage / Fitment     — YMM selector IS the hero
//   3. Department Store      — persistent left-rail nav + dense category mosaic
//   4. Configurator Spotlight— complete-plow builder front and center
//
// Every mockup embeds the REAL titantruck.com rotating promo banner at the top
// (slide images scraped live from the production site, see BANNER_SLIDES).
//
// These are STATIC visual mockups — selectors toggle local state to show the
// UX but don't hit the API.  Once Ben picks a direction we wire the winner
// into the live Home component.  Routes are registered in App.tsx; the global
// Header/Footer are suppressed on /mockup* so each concept shows its own chrome.
// ============================================================================

import { useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'

// ---------------------------------------------------------------------------
// The actual titantruck.com rotating banner — slide images + click-through
// links pulled live from production (www.titantruck.com homepage carousel).
// ---------------------------------------------------------------------------
const BANNER_SLIDES: { src: string; alt: string; href: string | null }[] = [
  { src: 'https://www.titantruck.com/images/F4181000.png', alt: 'Now open Saturdays', href: null },
  { src: 'https://www.titantruck.com/images/F4180648.webp', alt: 'Superwinch Tigershark', href: 'https://www.titantruck.com/b-134-superwinch.html' },
  { src: 'https://www.titantruck.com/images/F4180637.png', alt: 'Yakima — Titan picks, typically in stock', href: 'https://www.titantruck.com/p-246-titans-picks-typically-in-stock-yakima.html' },
  { src: 'https://www.titantruck.com/images/F4180649.webp', alt: 'Yakima', href: 'https://www.titantruck.com/yakima' },
  { src: 'https://www.titantruck.com/images/F3417030.png', alt: 'Financing with Affirm', href: null },
  { src: 'https://www.titantruck.com/images/F4184508.png', alt: 'Customer Appreciation Event', href: 'https://www.facebook.com/titantruck/' },
  { src: 'https://www.titantruck.com/images/F4180642.webp', alt: 'ARC Lighting — SAE', href: 'https://www.titantruck.com/b-200-arc-lighting.html' },
  { src: 'https://www.titantruck.com/images/F4180998.png', alt: 'BAK Industries', href: null },
  { src: 'https://www.titantruck.com/images/F4180643.webp', alt: 'Go Rhino E-Board', href: 'https://www.titantruck.com/i-288602-go-rhino-e-board-e1-electric-running-board-kit-20404887pc.html' },
]

/**
 * Faithful recreation of the live titantruck.com hero carousel: auto-advances
 * every 5s, pause-on-hover, prev/next arrows, clickable dots, and slides link
 * out to their real destinations.  Aspect ratio matches the production images
 * (1200×325 ≈ 3.7:1).  `tight` shrinks it for the sidebar/department layout.
 */
type Slide = { src: string; alt: string; href: string | null; fillColor?: string | null; edgeFade?: boolean }

// Feather all four edges so an undersized banner melts into its fill color out
// to the edge of the banner space (intersect two axis gradients into a vignette).
const EDGE_FADE_MASK: CSSProperties = {
  WebkitMaskImage:
    'linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0, #000 11%, #000 89%, transparent 100%)',
  WebkitMaskComposite: 'source-in',
  maskImage:
    'linear-gradient(to right, transparent 0, #000 7%, #000 93%, transparent 100%), linear-gradient(to bottom, transparent 0, #000 11%, #000 89%, transparent 100%)',
  maskComposite: 'intersect',
}

export function RotatingBanner({
  tight = false,
  audience = 'retail',
  fallback = null,
  fadeBottom = false,
}: { tight?: boolean; audience?: 'retail' | 'wholesale' | 'dealer' | 'municipality'; fallback?: ReactNode; fadeBottom?: boolean }) {
  // When the homepage tiles overlap the banner, fade its bottom 45px to 0%
  // opacity so it blends into the page instead of ending on a hard edge.
  const fadeMask = fadeBottom
    ? { WebkitMaskImage: 'linear-gradient(to bottom, #000 calc(100% - 45px), transparent)', maskImage: 'linear-gradient(to bottom, #000 calc(100% - 45px), transparent)' }
    : undefined
  // Data-driven via the Banner CMS (GET /api/banners). Falls back to the
  // hardcoded retail slides whenever an audience has no slides of its own (or
  // the API is unavailable) so the banner is never blank — e.g. a wholesale
  // shopper, or an admin shopping-as a B2B customer, still sees the carousel
  // instead of an empty gap.
  const initial = BANNER_SLIDES
  const [slides, setSlides] = useState<Slide[]>(initial)
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    let alive = true
    setI(0)
    setSlides(BANNER_SLIDES)
    fetch(`/api/banners?audience=${audience}`)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { image_url: string; alt: string; link_url: string | null; fill_color?: string | null; edge_fade?: boolean }[]) => {
        if (!alive || !Array.isArray(data)) return
        if (data.length) setSlides(data.map(d => ({ src: d.image_url, alt: d.alt, href: d.link_url, fillColor: d.fill_color, edgeFade: d.edge_fade })))
        // else: no slides configured for this audience → keep the default BANNER_SLIDES
      })
      .catch(() => { /* API down → keep the default slides already set */ })
    return () => { alive = false }
  }, [audience])

  const n = slides.length
  useEffect(() => {
    if (paused || n <= 1) return
    const t = setInterval(() => setI(p => (p + 1) % n), 5000)
    return () => clearInterval(t)
  }, [paused, n])

  if (n === 0) return <>{fallback}</>
  const cur = i % n
  const go = (d: number) => setI(p => (p + d + n) % n)

  return (
    <div
      className="relative w-full overflow-hidden rounded-xl bg-gray-200 shadow-sm ring-1 ring-black/5"
      style={fadeMask}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <div className="relative w-full" style={{ aspectRatio: tight ? '4.4 / 1' : '3.7 / 1' }}>
        {slides.map((s, idx) => {
          // Two fill strategies for art that doesn't match the 3.7:1 frame:
          //  • fillColor set → solid color backdrop with the image centered at
          //    its natural size (never upscaled), optionally feathered at the
          //    edges so a small banner melts into the color to the frame edge.
          //  • fillColor null → default: blurred backdrop + object-contain so no
          //    content is ever cropped, whatever the source aspect ratio.
          const media = s.fillColor
            ? (
              <div className="absolute inset-0 flex items-center justify-center" style={{ backgroundColor: s.fillColor }}>
                <img
                  src={s.src}
                  alt={s.alt}
                  loading="lazy"
                  className="max-h-full max-w-full object-contain"
                  style={s.edgeFade ? EDGE_FADE_MASK : undefined}
                />
              </div>
            )
            : (
              <>
                <img src={s.src} aria-hidden="true" className="absolute inset-0 h-full w-full scale-110 object-cover blur-2xl" />
                <img src={s.src} alt={s.alt} loading="lazy" className="absolute inset-0 h-full w-full object-contain" />
              </>
            )
          const internal = !!s.href && s.href.startsWith('/')
          return (
            <div
              key={`${s.src}-${idx}`}
              className={`absolute inset-0 transition-opacity duration-700 ${idx === cur ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
            >
              {s.href
                ? (internal
                    ? <Link to={s.href} title={s.alt} className="block h-full w-full">{media}</Link>
                    : <a href={s.href} target="_blank" rel="noreferrer" title={s.alt} className="block h-full w-full">{media}</a>)
                : media}
            </div>
          )
        })}
      </div>

      {/* arrows */}
      <button onClick={() => go(-1)} aria-label="Previous slide"
        className="absolute left-2 top-1/2 -translate-y-1/2 grid h-9 w-9 place-items-center rounded-full bg-black/35 text-white hover:bg-black/60">‹</button>
      <button onClick={() => go(1)} aria-label="Next slide"
        className="absolute right-2 top-1/2 -translate-y-1/2 grid h-9 w-9 place-items-center rounded-full bg-black/35 text-white hover:bg-black/60">›</button>

      {/* dots */}
      <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex gap-1.5">
        {slides.map((_, idx) => (
          <button key={idx} onClick={() => setI(idx)} aria-label={`Go to slide ${idx + 1}`}
            className={`h-2 rounded-full transition-all ${idx === cur ? 'w-5 bg-white' : 'w-2 bg-white/50 hover:bg-white/80'}`} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared mock data — real Titan categories / brands (scraped from production)
// ---------------------------------------------------------------------------
export const CATEGORIES = [
  { name: 'Snow & Ice Control', icon: '❄️', tone: 'from-sky-700 to-blue-900' },
  { name: 'Towing & Hitches', icon: '🪝', tone: 'from-amber-700 to-orange-900' },
  { name: 'Automotive Lighting', icon: '💡', tone: 'from-yellow-600 to-amber-800' },
  { name: 'Tool Boxes', icon: '🧰', tone: 'from-slate-600 to-slate-900' },
  { name: 'Running Boards & Steps', icon: '🪜', tone: 'from-zinc-600 to-zinc-900' },
  { name: 'Winches', icon: '⚙️', tone: 'from-red-700 to-rose-900' },
  { name: 'Truck Bed Accessories', icon: '🛻', tone: 'from-emerald-700 to-green-900' },
  { name: 'Bumpers', icon: '🛡️', tone: 'from-neutral-600 to-neutral-900' },
  { name: 'Lift Gates', icon: '🛗', tone: 'from-cyan-700 to-teal-900' },
  { name: 'Cranes', icon: '🏗️', tone: 'from-orange-700 to-red-900' },
  { name: 'Van Equipment', icon: '🚐', tone: 'from-indigo-700 to-violet-900' },
  { name: 'Cargo Management', icon: '📦', tone: 'from-stone-600 to-stone-900' },
]

export const BRANDS = ['WESTERN', 'BOSS', 'SnowEx', 'BUYERS', 'SUPERWINCH', 'YAKIMA', 'GO RHINO', 'ARC', 'BAK', 'CURT', 'WeatherTech', 'FISHER']

export const PRODUCTS = [
  { name: 'PRO-PLOW® Series 2 Straight Blade', brand: 'WESTERN', price: '6,499', cat: '❄️' },
  { name: 'Tigershark 9500 SR Winch', brand: 'SUPERWINCH', price: '729', cat: '⚙️' },
  { name: 'E-Board E1 Electric Running Board', brand: 'GO RHINO', price: '1,899', cat: '🪜' },
  { name: 'Revolver X4s Hard Roll-Up Cover', brand: 'BAK', price: '1,099', cat: '🛻' },
  { name: 'SaltDogg® 1.5 yd Hopper Spreader', brand: 'BUYERS', price: '4,250', cat: '❄️' },
  { name: 'SAE Series 32" Light Bar', brand: 'ARC', price: '389', cat: '💡' },
  { name: 'Crossover Aluminum Tool Box', brand: 'BUYERS', price: '419', cat: '🧰' },
  { name: 'Class V Receiver Hitch', brand: 'CURT', price: '329', cat: '🪝' },
]

// ---------------------------------------------------------------------------
// Reusable visual atoms
// ---------------------------------------------------------------------------
export function ProductCard({ p, badge }: { p: typeof PRODUCTS[number]; badge?: string }) {
  return (
    <div className="group flex w-44 shrink-0 flex-col rounded-lg border border-gray-200 bg-white p-3 transition hover:shadow-md">
      <div className="relative mb-2 grid aspect-square place-items-center rounded bg-gradient-to-br from-gray-100 to-gray-200 text-4xl">
        {p.cat}
        {badge && <span className="absolute left-1 top-1 rounded bg-emerald-600 px-1.5 py-0.5 text-[9px] font-bold uppercase text-white">{badge}</span>}
      </div>
      <div className="text-[10px] font-bold uppercase tracking-wide text-red-700">{p.brand}</div>
      <div className="line-clamp-2 text-xs font-medium text-gray-800">{p.name}</div>
      <div className="mt-1 text-sm font-extrabold text-gray-900">Retail ${p.price}</div>
      <button className="mt-2 rounded bg-yellow-400 py-1.5 text-[11px] font-bold text-gray-900 hover:bg-yellow-300">Add to Cart</button>
    </div>
  )
}

export function CategoryTile({ c, big = false }: { c: typeof CATEGORIES[number]; big?: boolean }) {
  return (
    <a className={`group relative flex flex-col justify-end overflow-hidden rounded-lg bg-gradient-to-br ${c.tone} ${big ? 'h-40' : 'h-28'} p-3 text-white shadow-sm transition hover:shadow-lg`}>
      <span className={`absolute right-2 top-2 ${big ? 'text-4xl' : 'text-2xl'} opacity-80`}>{c.icon}</span>
      <span className={`font-bold leading-tight ${big ? 'text-base' : 'text-xs'}`}>{c.name}</span>
      <span className="mt-0.5 text-[10px] text-white/70 group-hover:text-white">Shop now →</span>
    </a>
  )
}

function YmmSelector({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const lg = size === 'lg'
  const sel = `rounded border-2 border-gray-300 bg-white text-gray-800 ${lg ? 'px-4 py-3 text-base' : 'px-3 py-2 text-sm'}`
  return (
    <div className={`flex flex-wrap items-center gap-2 ${lg ? '' : ''}`}>
      <select className={sel} defaultValue=""><option value="">Year</option><option>2024</option><option>2023</option><option>2022</option></select>
      <select className={sel} defaultValue=""><option value="">Make</option><option>Ford</option><option>RAM</option><option>Chevrolet</option></select>
      <select className={sel} defaultValue=""><option value="">Model</option><option>F-250</option><option>F-350</option><option>2500</option></select>
      <button className={`rounded bg-red-700 font-bold text-white hover:bg-red-800 ${lg ? 'px-6 py-3 text-base' : 'px-4 py-2 text-sm'}`}>Find Parts →</button>
    </div>
  )
}

export function BrandStrip() {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      {BRANDS.map(b => (
        <span key={b} className="text-sm font-extrabold tracking-tight text-gray-400 transition hover:text-gray-700">{b}</span>
      ))}
    </div>
  )
}

function Rail({ title, badge }: { title: string; badge?: string }) {
  return (
    <section>
      <div className="mb-2 flex items-baseline gap-3">
        <h3 className="text-lg font-bold text-gray-900">{title}</h3>
        <a className="text-xs font-semibold text-red-700 hover:underline">See all →</a>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {PRODUCTS.map((p, idx) => <ProductCard key={p.name} p={p} badge={badge && idx % 3 === 0 ? badge : undefined} />)}
      </div>
    </section>
  )
}

// Shared logo lockup
// Real Titan Truck Equipment logo (yellow/red on transparent — reads on both
// light and dark headers).  Served from the app's own /public/brand asset, the
// same file the production Header uses.  `light` is accepted for call-site
// compatibility but no longer needed since the mark is multi-color.
export function Logo({ to = '/mockup' }: { light?: boolean; to?: string }) {
  return (
    <Link to={to} className="flex shrink-0 items-center leading-none">
      <img src="/brand/titan-logo.png" alt="Titan Truck Equipment" className="h-10 w-auto md:h-12" />
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Sticky switcher so Ben can flip between the four concepts while comparing
// ---------------------------------------------------------------------------
const TABS = [
  { to: '/mockup/marketplace', label: '1 · Marketplace' },
  { to: '/mockup/garage', label: '2 · Garage' },
  { to: '/mockup/department', label: '3 · Department' },
  { to: '/mockup/configurator', label: '4 · Configurator' },
]
function MockupSwitcher({ active }: { active: string }) {
  return (
    <div className="sticky top-0 z-50 border-b border-gray-700 bg-gray-900 text-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-1 px-4 py-1.5 text-xs">
        <Link to="/mockup" className="mr-2 font-bold text-gray-300 hover:text-white">◀ All concepts</Link>
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

// ===========================================================================
// Shared header bits
// ===========================================================================
export function UtilityBar() {
  return (
    <div className="bg-gray-900 text-gray-300">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-1.5 text-xs">
        <span>📞 Spokane <a className="font-semibold text-white">509-534-5010</a> · Toll-Free <a className="font-semibold text-white">800-346-1704</a></span>
        <div className="flex items-center gap-4">
          <a className="hover:text-white">Dealer Locator</a>
          <a className="hover:text-white">Returns</a>
          <a className="hover:text-white">Login / Signup</a>
        </div>
      </div>
    </div>
  )
}

function MegaMenuBar() {
  const items = ['Truck Accessories', 'Truck Equipment', 'Van Equipment', 'Snow & Ice', 'Lighting', 'Towing', 'Tool Boxes', 'Brands']
  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center gap-1 px-4 text-sm">
        <button className="flex items-center gap-1.5 bg-red-700 px-3 py-2.5 font-bold text-white">☰ All</button>
        {items.map(i => (
          <a key={i} className="whitespace-nowrap px-3 py-2.5 font-medium text-gray-700 hover:bg-gray-100 hover:text-red-700">{i}</a>
        ))}
      </div>
    </div>
  )
}

export function SearchBar({ flex = false }: { flex?: boolean }) {
  return (
    <div className={`flex items-stretch ${flex ? 'order-last w-full basis-full sm:order-none sm:flex-1 sm:basis-0' : 'w-full max-w-xl'}`}>
      <input placeholder="Search parts, SKUs, or vehicles…" className="w-full rounded-l border-2 border-r-0 border-gray-300 px-3 py-2 text-sm outline-none focus:border-red-600" />
      <button className="rounded-r bg-yellow-400 px-4 font-bold text-gray-900 hover:bg-yellow-300">🔍</button>
    </div>
  )
}

export function CartButton() {
  return (
    <button className="relative flex items-center gap-2 rounded bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">
      🛒 Cart
      <span className="grid h-5 w-5 place-items-center rounded-full bg-white text-xs text-red-700">0</span>
    </button>
  )
}

export function Trust() {
  const items = [
    ['🚚', 'Same-day shipping', 'on in-stock orders by 2pm'],
    ['🏠', 'Family-owned since 1955', 'Spokane & Boise'],
    ['💲', 'Price-match promise', 'we’ll beat written quotes'],
    ['🧑‍🔧', 'Real humans', 'talk to a rig specialist'],
  ]
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map(([i, a, b]) => (
        <div key={a} className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white p-3">
          <span className="text-2xl">{i}</span>
          <div><div className="text-xs font-bold text-gray-900">{a}</div><div className="text-[11px] text-gray-500">{b}</div></div>
        </div>
      ))}
    </div>
  )
}

// ===========================================================================
// MOCKUP 1 — MARKETPLACE GRID  (closest to the Amazon storefront)
// ===========================================================================
export function MockupMarketplace() {
  return (
    <div className="min-h-screen bg-gray-50">
      <MockupSwitcher active="/mockup/marketplace" />
      <UtilityBar />
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo />
          <SearchBar flex />
          <CartButton />
        </div>
      </div>
      <MegaMenuBar />

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {/* REAL rotating banner */}
        <RotatingBanner />

        {/* quad category tiles — Amazon's 4-up card row */}
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[CATEGORIES[0], CATEGORIES[1], CATEGORIES[2]].map(c => (
            <div key={c.name} className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-2 text-sm font-bold text-gray-900">{c.name}</h3>
              <div className="grid grid-cols-2 gap-2">
                {[0, 1, 2, 3].map(j => <div key={j} className={`grid aspect-square place-items-center rounded bg-gradient-to-br ${c.tone} text-2xl text-white/90`}>{c.icon}</div>)}
              </div>
              <a className="mt-2 inline-block text-xs font-semibold text-red-700">Shop all →</a>
            </div>
          ))}
          {/* the 4th tile = YMM finder, like Amazon's sign-in card */}
          <div className="flex flex-col justify-center rounded-lg border-2 border-red-200 bg-red-50 p-4">
            <h3 className="text-sm font-bold text-gray-900">Find parts for your truck</h3>
            <p className="mb-3 text-xs text-gray-600">Guaranteed-fit results.</p>
            <div className="flex flex-col gap-2">
              <select className="rounded border-2 border-gray-300 bg-white px-2 py-1.5 text-sm"><option>Year</option></select>
              <select className="rounded border-2 border-gray-300 bg-white px-2 py-1.5 text-sm"><option>Make</option></select>
              <select className="rounded border-2 border-gray-300 bg-white px-2 py-1.5 text-sm"><option>Model</option></select>
              <button className="rounded bg-red-700 py-1.5 text-sm font-bold text-white">Go →</button>
            </div>
          </div>
        </div>

        <Trust />
        <Rail title="Best sellers" />
        <Rail title="Back in stock" badge="In stock" />

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-gray-500">Brands we stock deep</div>
          <BrandStrip />
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// MOCKUP 2 — GARAGE / FITMENT-FIRST  (YMM selector is the hero)
// ===========================================================================
export function MockupGarage() {
  const [job, setJob] = useState<string | null>(null)
  return (
    <div className="min-h-screen bg-gray-50">
      <MockupSwitcher active="/mockup/garage" />
      <UtilityBar />
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo />
          <SearchBar flex />
          <button className="flex items-center gap-2 rounded border-2 border-gray-300 px-3 py-2 text-sm font-bold text-gray-700 hover:border-red-600">🚚 My Garage</button>
          <CartButton />
        </div>
      </div>
      <MegaMenuBar />

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <RotatingBanner />

        {/* GIANT YMM hero */}
        <div className="overflow-hidden rounded-2xl bg-gradient-to-r from-gray-900 via-red-900 to-gray-900 p-8 text-white shadow">
          <div className="text-xs font-bold uppercase tracking-widest text-red-300">Start here</div>
          <h1 className="mt-1 text-3xl font-black md:text-4xl">What do you drive?</h1>
          <p className="mt-1 text-sm text-gray-300">Set your vehicle once — every part, plow, and accessory is filtered to guaranteed fit.</p>
          <div className="mt-5 rounded-xl bg-white/95 p-4">
            <YmmSelector size="lg" />
          </div>
          <div className="mt-3 text-sm text-gray-300">
            ✓ Saved: <span className="rounded bg-white/15 px-2 py-0.5 font-semibold text-white">2019 RAM 2500</span>{' '}
            <span className="rounded bg-white/15 px-2 py-0.5 font-semibold text-white">2021 Ford F-350</span>
          </div>
        </div>

        {/* shop by job */}
        <div>
          <h2 className="mb-3 text-lg font-bold text-gray-900">Shop by job for your truck</h2>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[['❄️', 'Plow'], ['🪝', 'Tow'], ['💡', 'Light'], ['🧰', 'Haul']].map(([icon, label]) => (
              <button key={label} onClick={() => setJob(label)}
                className={`flex flex-col items-center gap-2 rounded-xl border-2 bg-white p-6 transition ${job === label ? 'border-red-600 ring-2 ring-red-200' : 'border-gray-200 hover:border-red-300'}`}>
                <span className="text-4xl">{icon}</span>
                <span className="font-bold text-gray-800">{label}</span>
              </button>
            ))}
          </div>
        </div>

        <Rail title={job ? `Guaranteed-fit ${job} picks for your RAM 2500` : 'Guaranteed-fit picks for your RAM 2500'} badge="Fits" />

        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-gray-500">Brands we stock deep</div>
          <BrandStrip />
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// MOCKUP 3 — DEPARTMENT STORE  (persistent left rail + dense mosaic)
// ===========================================================================
export function MockupDepartment() {
  const depts = ['Snow & Ice Control', 'Towing & Hitches', 'Lighting', 'Tool Boxes', 'Running Boards', 'Winches', 'Bumpers', 'Lift Gates', 'Cranes', 'Van Equipment', 'Bed Accessories', 'Shop by Brand']
  return (
    <div className="min-h-screen bg-gray-50">
      <MockupSwitcher active="/mockup/department" />
      <UtilityBar />
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Logo />
          <SearchBar flex />
          <CartButton />
        </div>
      </div>

      <div className="mx-auto max-w-7xl gap-5 px-4 py-5 lg:grid lg:grid-cols-[240px_minmax(0,1fr)]">
        {/* persistent left rail */}
        <aside className="mb-4 lg:mb-0">
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <div className="bg-red-700 px-4 py-2 text-xs font-bold uppercase tracking-widest text-white">Departments</div>
            <nav className="flex flex-col">
              {depts.map(d => (
                <a key={d} className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5 text-sm font-medium text-gray-700 last:border-0 hover:bg-gray-50 hover:text-red-700">
                  {d} <span className="text-gray-400">›</span>
                </a>
              ))}
            </nav>
          </div>
          <div className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 p-3">
            <div className="text-sm font-bold text-gray-900">🚚 Your Vehicle</div>
            <p className="mb-2 mt-1 text-[11px] text-gray-600">Set it to filter every dept.</p>
            <button className="w-full rounded bg-red-700 py-1.5 text-xs font-bold text-white">Set Year / Make / Model</button>
          </div>
        </aside>

        {/* content */}
        <div className="space-y-5">
          <RotatingBanner tight />

          {/* dense category mosaic */}
          <div>
            <h2 className="mb-3 text-lg font-bold text-gray-900">Shop every department</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {CATEGORIES.map((c, idx) => <CategoryTile key={c.name} c={c} big={idx < 2} />)}
            </div>
          </div>

          <Rail title="Top sellers this week" />
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// MOCKUP 4 — CONFIGURATOR SPOTLIGHT  (complete-plow builder front & center)
// ===========================================================================
export function MockupConfigurator() {
  return (
    <div className="min-h-screen bg-white">
      <MockupSwitcher active="/mockup/configurator" />
      {/* slim top bar */}
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
          <Logo />
          <nav className="hidden items-center gap-5 text-sm font-medium text-gray-700 md:flex">
            <a className="hover:text-red-700">Plows</a><a className="hover:text-red-700">Hitches</a>
            <a className="hover:text-red-700">Lighting</a><a className="hover:text-red-700">Tool Boxes</a><a className="hover:text-red-700">Brands</a>
          </nav>
          <div className="ml-auto flex items-center gap-3"><SearchBar /><CartButton /></div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl space-y-8 px-4 py-6">
        <RotatingBanner />

        {/* full-bleed builder hero */}
        <div className="overflow-hidden rounded-2xl bg-gradient-to-br from-blue-950 via-blue-900 to-gray-900 p-8 text-white shadow-lg md:p-10">
          <div className="text-xs font-bold uppercase tracking-widest text-sky-300">Titan exclusive</div>
          <h1 className="mt-1 max-w-2xl text-3xl font-black leading-tight md:text-4xl">Build your complete plow — one click, every part guaranteed to fit.</h1>
          <p className="mt-2 max-w-xl text-sm text-blue-200">Mount, blade, harness, controls, and headlamps — speced for your exact truck and bundled into a single SKU.</p>
          <div className="mt-6 grid gap-3 rounded-xl bg-white/95 p-4 text-gray-800 sm:grid-cols-4">
            <select className="rounded border-2 border-gray-300 px-3 py-3 text-sm"><option>Your vehicle…</option><option>2021 Ford F-350</option></select>
            <select className="rounded border-2 border-gray-300 px-3 py-3 text-sm"><option>Plow model…</option><option>WESTERN PRO-PLOW 2</option></select>
            <select className="rounded border-2 border-gray-300 px-3 py-3 text-sm"><option>Headlamps…</option><option>Standard halogen</option></select>
            <button className="rounded bg-red-700 px-4 py-3 text-sm font-extrabold text-white hover:bg-red-800">Build my plow →</button>
          </div>
        </div>

        {/* wide category bands */}
        <div>
          <h2 className="mb-3 text-lg font-bold text-gray-900">Shop by category</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[CATEGORIES[0], CATEGORIES[1], CATEGORIES[2], CATEGORIES[6]].map(c => <CategoryTile key={c.name} c={c} big />)}
          </div>
        </div>

        {/* deals 4-up */}
        <div>
          <div className="mb-3 flex items-baseline gap-3">
            <h2 className="text-lg font-bold text-gray-900">This week’s deals</h2>
            <a className="text-xs font-semibold text-red-700">See all →</a>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {PRODUCTS.slice(0, 4).map(p => (
              <div key={p.name} className="flex flex-col rounded-lg border border-gray-200 p-3">
                <div className="mb-2 grid aspect-square place-items-center rounded bg-gradient-to-br from-gray-100 to-gray-200 text-5xl">{p.cat}</div>
                <div className="text-[10px] font-bold uppercase text-red-700">{p.brand}</div>
                <div className="line-clamp-2 text-sm font-medium text-gray-800">{p.name}</div>
                <div className="mt-1 text-base font-extrabold">Retail ${p.price}</div>
              </div>
            ))}
          </div>
        </div>

        {/* brand logo strip */}
        <div className="rounded-xl bg-gray-50 p-6 text-center">
          <div className="mb-3 text-xs font-bold uppercase tracking-widest text-gray-500">Trusted brands</div>
          <div className="flex flex-wrap justify-center"><BrandStrip /></div>
        </div>
      </div>
    </div>
  )
}

// ===========================================================================
// INDEX / CHOOSER  —  /mockup
// ===========================================================================
const CONCEPTS = [
  { to: '/mockup/marketplace', n: 1, title: 'Marketplace Grid', tone: 'from-red-600 to-rose-800', blurb: 'Closest to the Amazon storefront: top mega-menu, hero carousel, quad category tiles (4th = vehicle finder), then horizontal best-seller & back-in-stock rails.', best: 'Promo/merchandising breadth' },
  { to: '/mockup/garage', n: 2, title: 'Garage / Fitment-First', tone: 'from-gray-800 to-red-900', blurb: 'The YMM vehicle selector IS the hero. Everything below filters to “fits your truck.” Saved vehicles + shop-by-job blocks + guaranteed-fit rails.', best: 'Fitment-first part buyers' },
  { to: '/mockup/department', n: 3, title: 'Department Store', tone: 'from-slate-700 to-slate-900', blurb: 'Persistent left-rail department nav (no dropdown hunting) beside a dense category mosaic and top-seller rail. Scales to a huge catalog.', best: 'Deep, many-category browsing' },
  { to: '/mockup/configurator', n: 4, title: 'Configurator Spotlight', tone: 'from-blue-900 to-gray-900', blurb: 'Slim nav, then a full-bleed complete-plow builder hero (vehicle × plow × headlamps → one SKU), wide category bands, deals 4-up, brand strip.', best: 'Selling complete-kit solutions' },
]

export function HomepageMockupsIndex() {
  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-gray-900 text-white">
        <div className="mx-auto max-w-6xl px-6 py-10">
          <div className="text-xs font-bold uppercase tracking-widest text-red-400">Titan Truck — homepage concepts</div>
          <h1 className="mt-2 text-3xl font-black md:text-4xl">4 spatial layouts for the new homepage</h1>
          <p className="mt-2 max-w-2xl text-sm text-gray-300">
            Each is a clickable, self-contained mockup with its own header treatment. All four embed the{' '}
            <span className="font-semibold text-white">real titantruck.com rotating banner</span> (live slide images) at the top.
            Open one, then use the dark switcher bar to flip between them. Static visuals — selectors toggle but don’t hit the API.
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-6 py-8">
        {/* live banner preview at the top of the chooser too */}
        <div className="mb-8">
          <div className="mb-2 text-xs font-bold uppercase tracking-widest text-gray-500">The rotating banner (shared across all 4)</div>
          <RotatingBanner />
        </div>

        <div className="grid gap-5 md:grid-cols-2">
          {CONCEPTS.map(c => (
            <Link key={c.to} to={c.to} className="group flex flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg">
              <div className={`relative h-40 bg-gradient-to-br ${c.tone} p-5 text-white`}>
                <div className="text-5xl font-black opacity-20">{c.n}</div>
                <div className="absolute bottom-4 left-5 text-xl font-bold">{c.title}</div>
              </div>
              <div className="flex flex-1 flex-col p-5">
                <p className="text-sm text-gray-600">{c.blurb}</p>
                <div className="mt-3 flex items-center justify-between">
                  <span className="rounded-full bg-gray-100 px-3 py-1 text-xs font-semibold text-gray-700">Best for: {c.best}</span>
                  <span className="text-sm font-bold text-red-700 group-hover:underline">Open mockup →</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
