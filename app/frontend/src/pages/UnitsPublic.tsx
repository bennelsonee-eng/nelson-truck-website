import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Seo, absoluteUrl, CANONICAL_BASE_URL } from '../components/Seo'
import { BRANCHES } from '../components/Inquiry'

// Trucks & equipment for sale (Ben, 2026-09-25): whole units -- wreckers,
// carriers, bucket trucks, Landoll trailers, cab-chassis, consigned equipment --
// "front and center, in your face". The homepage band, the /trucks-for-sale
// grid, each unit's page, the price-range chat and Build & Price all live here.
//
// Jerr-Dan units never show a price (their dealer agreement); the API decides
// that, and this file only renders what /api/units hands it.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PriceBlock { mode: 'show' | 'call' | 'range'; restricted: boolean; range_available: boolean; price?: number; sale_price?: number }
export interface UnitCard {
  slug: string; title: string; subtitle: string; headline: string | null
  category: string; category_label: string; unit_type: string; condition: string; status: string
  availability: 'in_stock' | 'future_build'; available_date: string | null; available_note: string | null
  location: string | null; location_label: string | null
  year: number | null; make: string | null; model: string | null
  mileage: number | null; drive: string | null; fuel: string | null; gvwr_lbs: number | null
  photo: string | null; thumb: string | null; photo_count: number; video_count: number
  price: PriceBlock; featured: boolean
  sold: boolean; tags: string[]
}
interface KV { label: string; value: string }
interface UnitDetail extends UnitCard {
  description: string | null; upfit_make: string | null; upfit_model: string | null; upfit_description: string | null
  specs: KV[]; chassis_specs: KV[]; features: string[]; spec_sheet: string | null
  photos: { url: string; thumb: string; width: number | null; height: number | null; caption: string | null }[]
  videos: { url: string; poster: string | null; caption: string | null }[]
  video_links: string[]
  documents: { url: string; name: string; doc_type: string | null }[]
  qualify_specs: KV[]; vin: string | null; stock_number: string | null
  published_at: string | null; updated_at: string | null; sold: boolean
}
interface FollowUp { when: string; text: string }

const money = (n: number) => '$' + Math.round(n).toLocaleString('en-US')

// Equipment a customer can ask to have quoted on top of the unit or build
// (Ben, 2026-09-25: "we can always add truck equipment components to it after
// the fact"). Sent as additional_items and flagged ALSO QUOTE in the alert.
export const ADD_ONS = ['Toolboxes', 'LED light bar & strobes', 'Work lights', 'Backup camera', 'Wireless remote',
  'Hitch / pintle hook', 'Headache rack', 'Mud flaps & fenders', 'Two-way radio', 'Snow plow / spreader']

function AddOnPicker({ value, onChange, dark }: { value: string[]; onChange: (v: string[]) => void; dark?: boolean }) {
  const [other, setOther] = useState('')
  const toggle = (x: string) => onChange(value.includes(x) ? value.filter((y) => y !== x) : [...value, x])
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {ADD_ONS.map((x) => {
          const on = value.includes(x)
          return <button key={x} type="button" onClick={() => toggle(x)}
            className={`rounded-full border px-3 py-1.5 text-sm font-semibold transition ${on ? 'border-red-700 bg-red-700 text-white' : dark ? 'border-gray-300 bg-white text-gray-800' : 'border-gray-300 bg-white text-gray-800 hover:border-red-400'}`}>
            {on ? '✓ ' : '+ '}{x}</button>
        })}
        {value.filter((x) => !ADD_ONS.includes(x)).map((x) => (
          <button key={x} type="button" onClick={() => toggle(x)} className="rounded-full border border-red-700 bg-red-700 px-3 py-1.5 text-sm font-semibold text-white">✓ {x}</button>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        <input value={other} onChange={(e) => setOther(e.target.value)} placeholder="Something else? e.g. crane, compressor, ladder rack"
          onKeyDown={(e) => { if (e.key === 'Enter' && other.trim()) { e.preventDefault(); onChange([...value, other.trim()]); setOther('') } }}
          className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" />
        <button type="button" disabled={!other.trim()} onClick={() => { onChange([...value, other.trim()]); setOther('') }}
          className="shrink-0 rounded-md border border-gray-300 bg-white px-3 text-sm font-semibold disabled:opacity-40">Add</button>
      </div>
    </div>
  )
}
const PHONE = { Portland: BRANCHES[0], Kent: BRANCHES[1] }

function availabilityChip(u: Pick<UnitCard, 'availability' | 'available_date' | 'available_note' | 'status'> & { sold?: boolean }): { text: string; tone: string } {
  if (u.sold || u.status === 'sold') return { text: 'Sold', tone: 'bg-gray-900 text-white' }
  if (u.status === 'pending') return { text: 'Sale pending', tone: 'bg-amber-500 text-black' }
  if (u.availability === 'future_build') {
    if (u.available_note) return { text: u.available_note, tone: 'bg-sky-600 text-white' }
    if (u.available_date) {
      const d = new Date(u.available_date + 'T12:00:00')
      return { text: `Available ${d.toLocaleString('en-US', { month: 'short', year: 'numeric' })}`, tone: 'bg-sky-600 text-white' }
    }
    return { text: 'Future build', tone: 'bg-sky-600 text-white' }
  }
  return { text: 'In stock', tone: 'bg-green-600 text-white' }
}

function specLine(u: UnitCard): string {
  const bits: string[] = []
  if (u.condition === 'used' && u.mileage) bits.push(`${u.mileage.toLocaleString()} mi`)
  if (u.drive) bits.push(u.drive)
  if (u.fuel) bits.push(u.fuel)
  if (u.gvwr_lbs) bits.push(`${u.gvwr_lbs.toLocaleString()} lb GVWR`)
  return bits.join(' · ')
}

// Admin-chosen badges ("Hot item", "New build"...). Colour by name; anything
// typed in the admin gets the neutral one.
const TAG_TONE: Record<string, string> = {
  'hot item': 'bg-red-600 text-white', "won't last": 'bg-red-600 text-white',
  'new build': 'bg-sky-600 text-white', 'fleet special': 'bg-sky-600 text-white',
  'just arrived': 'bg-green-600 text-white', 'ready to work': 'bg-green-600 text-white',
  'price reduced': 'bg-amber-400 text-black', 'make an offer': 'bg-amber-400 text-black',
}
export function TagBadges({ tags, className = '' }: { tags: string[]; className?: string }) {
  if (!tags?.length) return null
  return (
    <div className={`flex flex-wrap gap-1 ${className}`}>
      {tags.map((t) => <span key={t} className={`rounded px-1.5 py-0.5 text-[10.5px] font-extrabold uppercase tracking-wide shadow-sm ${TAG_TONE[t.toLowerCase()] || 'bg-white/90 text-gray-900'}`}>{t}</span>)}
    </div>
  )
}

export function PriceTag({ price, dark, size = 'md' }: { price: PriceBlock; dark?: boolean; size?: 'md' | 'lg' }) {
  const big = size === 'lg' ? 'text-3xl' : 'text-xl'
  if (price.mode === 'show' && price.price) {
    if (price.sale_price) return (
      <div className="flex items-baseline gap-2">
        <span className={`${big} font-extrabold ${dark ? 'text-amber-400' : 'text-red-700'}`}>{money(price.sale_price)}</span>
        <span className={`text-sm line-through ${dark ? 'text-[#9a917f]' : 'text-gray-400'}`}>{money(price.price)}</span>
      </div>
    )
    return <span className={`${big} font-extrabold ${dark ? 'text-white' : 'text-gray-900'}`}>{money(price.price)}</span>
  }
  if (price.mode === 'range' && price.range_available) {
    return <span className={`text-sm font-bold uppercase tracking-wide ${dark ? 'text-amber-400' : 'text-red-700'}`}>Get your price →</span>
  }
  return <span className={`text-sm font-bold uppercase tracking-wide ${dark ? 'text-amber-400' : 'text-red-700'}`}>Call for price</span>
}

export function UnitCardView({ u, dark, big }: { u: UnitCard; dark?: boolean; big?: boolean }) {
  const chip = availabilityChip(u)
  return (
    <Link to={`/trucks-for-sale/${u.slug}`}
      className={`group flex h-full flex-col overflow-hidden rounded-xl border transition hover:-translate-y-0.5 hover:shadow-xl ${
        dark ? 'border-[#2a2620] bg-[#1b1813] hover:border-red-700' : 'border-gray-200 bg-white hover:border-red-300'}`}>
      <div className={`relative ${big ? 'aspect-[16/10]' : 'aspect-[4/3]'} overflow-hidden ${dark ? 'bg-[#0f0d0a]' : 'bg-gray-100'}`}>
        {u.photo
          ? <img src={u.thumb || u.photo} alt={u.title} loading="lazy" className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
          : <div className="grid h-full place-items-center text-sm text-gray-500">Photos coming</div>}
        {u.sold && <div className="absolute inset-0 bg-black/35" />}
        <div className="absolute left-2 top-2 flex flex-col items-start gap-1">
          <span className={`rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${chip.tone}`}>{chip.text}</span>
          <TagBadges tags={u.tags} />
        </div>
        {u.condition !== 'new' && <span className="absolute right-2 top-2 rounded bg-black/70 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">{u.condition}</span>}
        <span className="absolute bottom-2 right-2 rounded bg-black/65 px-2 py-0.5 text-[11px] font-semibold text-white">
          📷 {u.photo_count}{u.video_count ? ` · ▶ ${u.video_count}` : ''}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1 p-4">
        <div className={`text-[11px] font-bold uppercase tracking-[0.12em] ${dark ? 'text-amber-400' : 'text-red-700'}`}>{u.category_label}</div>
        <h3 className={`font-cond text-xl leading-tight ${dark ? 'text-white' : 'text-gray-900'}`}>{u.title}</h3>
        {u.subtitle && <div className={`text-sm ${dark ? 'text-[#d8cfbf]' : 'text-gray-700'}`}>{u.subtitle}</div>}
        {specLine(u) && <div className={`text-xs ${dark ? 'text-[#9a917f]' : 'text-gray-500'}`}>{specLine(u)}</div>}
        <div className="mt-auto flex items-end justify-between gap-2 pt-3">
          {u.sold ? <span className={`text-sm font-bold uppercase tracking-wide ${dark ? 'text-[#9a917f]' : 'text-gray-500'}`}>Sold by Nelson</span> : <PriceTag price={u.price} dark={dark} />}
          {u.location_label && <span className={`shrink-0 text-xs ${dark ? 'text-[#9a917f]' : 'text-gray-500'}`}>{u.location_label}</span>}
        </div>
      </div>
    </Link>
  )
}

// ---------------------------------------------------------------------------
// Homepage band + category strips
// ---------------------------------------------------------------------------

export function UnitShowcase({ variant = 'home', category, title }: { variant?: 'home' | 'strip'; category?: string; title?: string }) {
  const [items, setItems] = useState<UnitCard[] | null>(null)
  const [total, setTotal] = useState(0)
  const [soldCount, setSoldCount] = useState(0)
  const rail = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const qs = new URLSearchParams({ limit: '12' })
    if (category) qs.set('category', category)
    fetch(`/api/units/showcase?${qs}`).then((r) => (r.ok ? r.json() : null))
      .then((d) => { setItems(d?.items || []); setTotal(d?.total || 0); setSoldCount(d?.sold_count || 0) })
      .catch(() => setItems([]))
  }, [category])
  const scroll = (dir: number) => rail.current?.scrollBy({ left: dir * (rail.current.clientWidth * 0.85), behavior: 'smooth' })

  if (!items || items.length === 0) return null
  const dark = variant === 'home'
  const allLink = category ? `/trucks-for-sale?category=${category}` : '/trucks-for-sale'
  return (
    <section className={dark ? 'border-b-4 border-red-700 bg-[#0f0d0a] text-[#f4efe6]' : 'bg-gray-50 border-y border-gray-200'}
      aria-label="Trucks and equipment for sale">
      <div className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className={`text-[11px] font-bold uppercase tracking-[0.16em] ${dark ? 'text-red-500' : 'text-red-700'}`}>
              {dark ? `${total} ready to work · Portland & Kent` : 'For sale now'}
            </div>
            <h2 className={`font-cond text-3xl leading-tight md:text-4xl ${dark ? 'text-white' : 'text-gray-900'}`}>
              {title || (dark ? <>Trucks & equipment <span className="text-amber-400">for sale</span></> : 'Units for sale')}
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {dark && (
              <Link to="/trucks-for-sale/build" className="hidden rounded-md border border-amber-400/60 px-4 py-2 text-sm font-bold text-amber-300 hover:bg-amber-400 hover:text-black sm:inline-block">
                Build & price your own
              </Link>
            )}
            <Link to={allLink} className="rounded-md bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">
              See all {category ? '' : total} →
            </Link>
            <button type="button" onClick={() => scroll(-1)} aria-label="Scroll left"
              className={`hidden h-9 w-9 rounded-full border text-lg md:block ${dark ? 'border-[#3a342b] text-white hover:bg-[#2a2620]' : 'border-gray-300 hover:bg-white'}`}>‹</button>
            <button type="button" onClick={() => scroll(1)} aria-label="Scroll right"
              className={`hidden h-9 w-9 rounded-full border text-lg md:block ${dark ? 'border-[#3a342b] text-white hover:bg-[#2a2620]' : 'border-gray-300 hover:bg-white'}`}>›</button>
          </div>
        </div>
        <div ref={rail} className="-mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-2 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {items.map((u) => (
            <div key={u.slug} className={`${dark ? 'w-[82%] sm:w-[46%] lg:w-[31%] xl:w-[24%]' : 'w-[78%] sm:w-[44%] lg:w-[30%] xl:w-[23%]'} shrink-0 snap-start`}>
              <UnitCardView u={u} dark={dark} big={dark} />
            </div>
          ))}
          {dark && (
            <Link to="/trucks-for-sale/build" className="flex w-[70%] shrink-0 snap-start flex-col justify-center rounded-xl border-2 border-dashed border-[#3a342b] p-6 hover:border-amber-400 sm:w-[40%] lg:w-[24%]">
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-amber-400">Don't see it?</div>
              <div className="mt-1 font-cond text-2xl text-white">Build & price the truck you need</div>
              <p className="mt-2 text-sm text-[#9a917f]">Pick the body, chassis and options — get a price range in two minutes, and a salesperson follows up.</p>
              <span className="mt-4 text-sm font-bold text-amber-300">Start building →</span>
            </Link>
          )}
          {dark && soldCount > 0 && (
            <Link to="/trucks-for-sale#sold" className="flex w-[60%] shrink-0 snap-start flex-col justify-center rounded-xl border border-[#2a2620] bg-[#1b1813] p-6 hover:border-amber-400 sm:w-[34%] lg:w-[20%]">
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[#9a917f]">Recently sold</div>
              <div className="mt-1 font-cond text-2xl text-white">{soldCount} truck{soldCount === 1 ? '' : 's'} sold</div>
              <span className="mt-3 text-sm font-bold text-amber-300">See what we’ve sold →</span>
            </Link>
          )}
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// /trucks-for-sale
// ---------------------------------------------------------------------------

interface Facet { value: string; label?: string; count: number }

export function TrucksForSalePage() {
  const [sp, setSp] = useSearchParams()
  const [data, setData] = useState<{ items: UnitCard[]; sold?: UnitCard[]; facets: { category: Facet[]; make: Facet[]; location: Facet[]; availability: Record<string, number> } } | null>(null)
  const category = sp.get('category') || ''
  const availability = sp.get('availability') || ''
  const location = sp.get('location') || ''
  const make = sp.get('make') || ''
  const sort = sp.get('sort') || 'featured'
  useEffect(() => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries({ category, availability, location, make, sort })) if (v) qs.set(k, v)
    fetch(`/api/units?${qs}`).then((r) => r.json()).then(setData).catch(() => setData({ items: [], facets: { category: [], make: [], location: [], availability: {} } }))
  }, [category, availability, location, make, sort])
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); setSp(n, { replace: true }) }
  const catLabel = data?.facets.category.find((c) => c.value === category)?.label

  return (
    <div className="bg-white">
      <Seo
        title={`${catLabel || 'Trucks & Equipment'} for Sale — Portland OR & Kent WA | Nelson Truck Equipment`}
        description="Wreckers, rollback carriers, bucket trucks, Landoll trailers, cab-chassis and used equipment for sale at Nelson Truck Equipment in Portland, OR and Kent, WA. In stock now or built to order."
        path={category ? `/trucks-for-sale?category=${category}` : '/trucks-for-sale'}
        ready={data !== null}
      />
      <div className="border-b-4 border-red-700 bg-[#16130f] text-[#f4efe6]">
        <div className="mx-auto max-w-[1600px] px-4 py-8 sm:px-6 lg:px-8">
          <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-red-500">Nelson Truck Equipment · Since 1937</div>
          <h1 className="font-cond text-4xl text-white md:text-5xl">{catLabel || 'Trucks & equipment'} <span className="text-amber-400">for sale</span></h1>
          <p className="mt-2 max-w-3xl text-[15px] text-[#b8ae9b]">Built, inspected and ready to work — on the lot in Portland and Kent, or built to your spec. Every unit is backed by our own shops.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link to="/trucks-for-sale/build" className="rounded-md bg-amber-400 px-4 py-2 text-sm font-bold text-black hover:bg-amber-300">Build & price your own →</Link>
            <a href={`tel:${PHONE.Portland.tel}`} className="rounded-md border border-[#3a342b] px-4 py-2 text-sm font-semibold text-white hover:border-amber-400">Portland {PHONE.Portland.phone}</a>
            <a href={`tel:${PHONE.Kent.tel}`} className="rounded-md border border-[#3a342b] px-4 py-2 text-sm font-semibold text-white hover:border-amber-400">Kent {PHONE.Kent.phone}</a>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => set('category', '')}
            className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${!category ? 'border-red-700 bg-red-700 text-white' : 'border-gray-300 text-gray-800 hover:border-red-400'}`}>All</button>
          {data?.facets.category.map((c) => (
            <button key={c.value} type="button" onClick={() => set('category', c.value)}
              className={`rounded-full border px-3 py-1.5 text-sm font-semibold ${category === c.value ? 'border-red-700 bg-red-700 text-white' : 'border-gray-300 text-gray-800 hover:border-red-400'}`}>
              {c.label} <span className="opacity-70">({c.count})</span>
            </button>
          ))}
          <span className="mx-2 hidden h-6 w-px bg-gray-300 md:block" />
          <select value={availability} onChange={(e) => set('availability', e.target.value)} className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">In stock & future builds</option>
            <option value="in_stock">In stock now</option>
            <option value="future_build">Future builds</option>
          </select>
          <select value={location} onChange={(e) => set('location', e.target.value)} className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All locations</option>
            {data?.facets.location.map((l) => <option key={l.value} value={l.value}>{l.label} ({l.count})</option>)}
          </select>
          <select value={make} onChange={(e) => set('make', e.target.value)} className="rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="">All makes</option>
            {data?.facets.make.map((m) => <option key={m.value} value={m.value}>{m.value} ({m.count})</option>)}
          </select>
          <select value={sort} onChange={(e) => set('sort', e.target.value)} className="ml-auto rounded-md border border-gray-300 px-2 py-1.5 text-sm">
            <option value="featured">Featured</option>
            <option value="newest">Newest listed</option>
            <option value="year">Newest model year</option>
          </select>
        </div>

        {data === null ? <div className="py-16 text-center text-gray-500">Loading…</div> : data.items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 px-6 py-14 text-center">
            <div className="font-cond text-2xl text-gray-900">Nothing listed here right now</div>
            <p className="mt-2 text-gray-600">Units come and go fast. Tell us what you're after and we'll find or build it.</p>
            <Link to="/trucks-for-sale/build" className="mt-4 inline-block rounded-md bg-red-700 px-5 py-2.5 font-bold text-white hover:bg-red-800">Build & price your truck</Link>
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data.items.map((u) => <UnitCardView key={u.slug} u={u} />)}
            <Link to="/trucks-for-sale/build" className="flex flex-col justify-center rounded-xl border-2 border-dashed border-gray-300 p-6 hover:border-red-400">
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-red-700">Don't see it?</div>
              <div className="mt-1 font-cond text-2xl text-gray-900">Build & price the truck you need</div>
              <p className="mt-2 text-sm text-gray-600">Choose the body, chassis and options, get a price range in two minutes, and a salesperson follows up.</p>
              <span className="mt-4 text-sm font-bold text-red-700">Start building →</span>
            </Link>
          </div>
        )}

        {data && (data.sold || []).length > 0 && (
          <section id="sold" className="mt-12 scroll-mt-24 border-t border-gray-200 pt-8">
            <div className="text-[11px] font-bold uppercase tracking-[0.16em] text-gray-500">Recently sold</div>
            <h2 className="font-cond text-3xl text-gray-900">What we’ve sold</h2>
            <p className="mt-1 max-w-2xl text-sm text-gray-600">These found their new owners. Want one like it? We build them to order — <Link to="/trucks-for-sale/build" className="font-semibold text-red-700 hover:underline">build & price yours</Link>.</p>
            <div className="mt-5 grid gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {(data.sold || []).map((u) => <UnitCardView key={u.slug} u={u} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Unit page
// ---------------------------------------------------------------------------

function videoEmbed(url: string): string | null {
  const yt = url.match(/(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/)|youtu\.be\/)([\w-]{6,})/)
  if (yt) return `https://www.youtube-nocookie.com/embed/${yt[1]}`
  const vm = url.match(/vimeo\.com\/(?:video\/)?(\d+)/)
  if (vm) return `https://player.vimeo.com/video/${vm[1]}`
  return null
}

function Gallery({ u }: { u: UnitDetail }) {
  const [i, setI] = useState(0)
  const [open, setOpen] = useState(false)
  const photos = u.photos
  const go = useCallback((d: number) => setI((x) => (x + d + photos.length) % photos.length), [photos.length])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); if (e.key === 'ArrowRight') go(1); if (e.key === 'ArrowLeft') go(-1) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, go])
  if (!photos.length) return <div className="grid aspect-[16/10] place-items-center rounded-xl bg-gray-100 text-gray-500">Photos coming soon</div>
  const p = photos[i]
  return (
    <div>
      <div className="relative overflow-hidden rounded-xl bg-gray-900">
        <button type="button" onClick={() => setOpen(true)} className="block w-full" aria-label="Open full-size photo">
          <img src={p.url} alt={`${u.title} — photo ${i + 1} of ${photos.length}`} className="aspect-[16/10] w-full object-contain" />
        </button>
        {photos.length > 1 && <>
          <button type="button" onClick={() => go(-1)} aria-label="Previous photo" className="absolute left-2 top-1/2 h-11 w-11 -translate-y-1/2 rounded-full bg-black/55 text-2xl text-white hover:bg-black/75">‹</button>
          <button type="button" onClick={() => go(1)} aria-label="Next photo" className="absolute right-2 top-1/2 h-11 w-11 -translate-y-1/2 rounded-full bg-black/55 text-2xl text-white hover:bg-black/75">›</button>
        </>}
        <span className="absolute bottom-2 right-2 rounded bg-black/65 px-2 py-0.5 text-xs font-semibold text-white">{i + 1} / {photos.length}</span>
      </div>
      <div className="mt-2 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]">
        {photos.map((ph, j) => (
          <button key={ph.url} type="button" onClick={() => setI(j)} aria-label={`Photo ${j + 1}`}
            className={`h-16 w-24 shrink-0 overflow-hidden rounded-md border-2 ${j === i ? 'border-red-700' : 'border-transparent opacity-80 hover:opacity-100'}`}>
            <img src={ph.thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
          </button>
        ))}
      </div>
      {open && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/95" role="dialog" aria-modal="true" onClick={() => setOpen(false)}>
          <img src={p.url} alt="" className="max-h-[92vh] max-w-[96vw] object-contain" onClick={(e) => e.stopPropagation()} />
          <button type="button" onClick={(e) => { e.stopPropagation(); go(-1) }} aria-label="Previous photo" className="absolute left-3 top-1/2 h-12 w-12 -translate-y-1/2 rounded-full bg-white/15 text-3xl text-white">‹</button>
          <button type="button" onClick={(e) => { e.stopPropagation(); go(1) }} aria-label="Next photo" className="absolute right-3 top-1/2 h-12 w-12 -translate-y-1/2 rounded-full bg-white/15 text-3xl text-white">›</button>
          <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="absolute right-4 top-4 h-10 w-10 rounded-full bg-white/15 text-xl text-white">✕</button>
          <span className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-white/80">{i + 1} / {photos.length}</span>
        </div>
      )}
    </div>
  )
}

function SpecTable({ rows }: { rows: KV[] }) {
  if (!rows.length) return null
  return (
    <dl className="grid overflow-hidden rounded-lg border border-gray-200 sm:grid-cols-2">
      {rows.map((r, i) => (
        <div key={r.label + i} className="flex justify-between gap-4 border-b border-gray-100 px-4 py-2.5 text-sm odd:bg-gray-50 sm:[&:nth-child(4n+3)]:bg-gray-50 sm:[&:nth-child(4n+2)]:bg-white sm:[&:nth-child(4n+4)]:bg-white">
          <dt className="text-gray-500">{r.label}</dt><dd className="text-right font-semibold text-gray-900">{r.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export function UnitDetailPage() {
  const { slug = '' } = useParams()
  const [u, setU] = useState<UnitDetail | null | 'missing'>(null)
  const [chat, setChat] = useState(false)
  const [contact, setContact] = useState<null | 'quote' | 'call' | 'offer' | 'question'>(null)
  useEffect(() => {
    setU(null)
    fetch(`/api/units/${encodeURIComponent(slug)}`).then((r) => (r.ok ? r.json() : 'missing')).then(setU).catch(() => setU('missing'))
    fetch(`/api/units/${encodeURIComponent(slug)}/view`, { method: 'POST' }).catch(() => {})
  }, [slug])

  if (u === null) return <div className="mx-auto max-w-6xl px-4 py-16 text-gray-500">Loading…<Seo title="Loading — Nelson Truck Equipment" ready={false} /></div>
  if (u === 'missing') return (
    <div className="mx-auto max-w-3xl px-4 py-20 text-center">
      <Seo title="Unit no longer listed — Nelson Truck Equipment" noindex />
      <h1 className="font-cond text-3xl text-gray-900">That unit has sold or is no longer listed</h1>
      <p className="mt-2 text-gray-600">We turn units over fast. Here's what's for sale right now.</p>
      <Link to="/trucks-for-sale" className="mt-5 inline-block rounded-md bg-red-700 px-5 py-2.5 font-bold text-white">See trucks for sale</Link>
    </div>
  )

  const chip = availabilityChip(u)
  const specs = [...u.specs]
  const desc = u.description || u.upfit_description || ''
  const offerOk = u.condition !== 'new'
  const priceShown = u.price.mode === 'show' && !!u.price.price
  const jsonLd: Record<string, unknown> = {
    '@context': 'https://schema.org',
    '@type': u.unit_type === 'equipment' ? 'Product' : 'Vehicle',
    name: u.title,
    description: desc.slice(0, 500) || `${u.title} — ${u.subtitle}`,
    url: `${CANONICAL_BASE_URL}/trucks-for-sale/${u.slug}`,
    image: u.photos.slice(0, 6).map((p) => absoluteUrl(p.url)),
    brand: u.make ? { '@type': 'Brand', name: u.make } : undefined,
    ...(u.unit_type !== 'equipment' ? {
      vehicleModelDate: u.year ? String(u.year) : undefined, model: u.model || undefined,
      vehicleIdentificationNumber: u.vin || undefined,
      itemCondition: u.condition === 'new' ? 'https://schema.org/NewCondition' : 'https://schema.org/UsedCondition',
      mileageFromOdometer: u.mileage ? { '@type': 'QuantitativeValue', value: u.mileage, unitCode: 'SMI' } : undefined,
    } : {}),
    // An Offer only when the price may be advertised -- never for Jerr-Dan.
    ...(priceShown ? { offers: { '@type': 'Offer', price: u.price.sale_price || u.price.price, priceCurrency: 'USD',
      availability: u.status === 'pending' ? 'https://schema.org/LimitedAvailability' : u.availability === 'future_build' ? 'https://schema.org/PreOrder' : 'https://schema.org/InStock',
      seller: { '@type': 'Organization', name: 'Nelson Truck Equipment' } } } : {}),
  }

  return (
    <div className="bg-white">
      <Seo
        title={`${u.title}${u.subtitle ? ' — ' + u.subtitle : ''} for Sale | Nelson Truck Equipment`}
        description={`${u.title} ${u.subtitle || ''} for sale${u.location_label ? ' in ' + u.location_label : ''}. ${desc}`.slice(0, 300)}
        path={`/trucks-for-sale/${u.slug}`}
        image={u.photos[0]?.url || null}
        type="product"
        noindex={false}
        jsonLd={jsonLd}
      />
      <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6 lg:px-8">
        <nav className="mb-3 text-sm text-gray-500">
          <Link to="/trucks-for-sale" className="hover:text-red-700">Trucks for sale</Link>
          <span className="mx-1.5">›</span>
          <Link to={`/trucks-for-sale?category=${u.category}`} className="hover:text-red-700">{u.category_label}</Link>
        </nav>
        {u.sold && <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">This unit has sold. <Link to="/trucks-for-sale" className="font-bold underline">See what's for sale now</Link> or <Link to="/trucks-for-sale/build" className="font-bold underline">build & price one like it</Link>.</div>}

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0">
            <Gallery u={u} />
            {(u.videos.length > 0 || u.video_links.length > 0) && (
              <section className="mt-8">
                <h2 className="mb-3 font-cond text-2xl text-gray-900">Video</h2>
                <div className="grid gap-4 md:grid-cols-2">
                  {u.videos.map((v) => (
                    <video key={v.url} controls preload="metadata" poster={v.poster || u.photos[0]?.url} className="aspect-video w-full rounded-lg bg-black">
                      <source src={v.url} />
                    </video>
                  ))}
                  {u.video_links.map((l) => { const e = videoEmbed(l); return e ? (
                    <iframe key={l} src={e} title={`${u.title} video`} loading="lazy" className="aspect-video w-full rounded-lg" allow="accelerometer; encrypted-media; picture-in-picture; fullscreen" />
                  ) : null })}
                </div>
              </section>
            )}
            {desc && (
              <section className="mt-8">
                <h2 className="mb-2 font-cond text-2xl text-gray-900">About this {u.unit_type === 'equipment' ? 'unit' : 'truck'}</h2>
                <div className="whitespace-pre-line text-[15px] leading-relaxed text-gray-800">{u.description || u.upfit_description}</div>
              </section>
            )}
            {(u.upfit_make || u.upfit_model || specs.length > 0) && (
              <section className="mt-8">
                <h2 className="mb-3 font-cond text-2xl text-gray-900">{u.upfit_make || u.upfit_model ? `${[u.upfit_make, u.upfit_model].filter(Boolean).join(' ')}` : 'Equipment specs'}</h2>
                {u.description && u.upfit_description && <p className="mb-3 whitespace-pre-line text-[15px] leading-relaxed text-gray-800">{u.upfit_description}</p>}
                <SpecTable rows={specs} />
              </section>
            )}
            {u.chassis_specs.length > 0 && (
              <section className="mt-8">
                <h2 className="mb-3 font-cond text-2xl text-gray-900">{u.unit_type === 'equipment' ? 'Details' : 'Chassis'}</h2>
                <SpecTable rows={u.chassis_specs} />
              </section>
            )}
            {u.features.length > 0 && (
              <section className="mt-8">
                <h2 className="mb-3 font-cond text-2xl text-gray-900">Features</h2>
                <div className="flex flex-wrap gap-2">
                  {u.features.map((f) => <span key={f} className="rounded-full border border-gray-300 bg-gray-50 px-3 py-1 text-sm text-gray-800">✓ {f}</span>)}
                </div>
              </section>
            )}
            {u.spec_sheet && (
              <details className="mt-8 rounded-lg border border-gray-200">
                <summary className="cursor-pointer px-4 py-3 font-semibold text-gray-900">Full chassis spec sheet</summary>
                <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap border-t border-gray-200 bg-gray-50 px-4 py-3 text-[13px] leading-relaxed text-gray-800">{u.spec_sheet}</pre>
              </details>
            )}
            {u.documents.length > 0 && (
              <section className="mt-8">
                <h2 className="mb-3 font-cond text-2xl text-gray-900">Documents</h2>
                <ul className="space-y-2">
                  {u.documents.map((d) => <li key={d.url}><a href={d.url} target="_blank" rel="noopener" className="font-semibold text-red-700 hover:underline">📄 {d.name}</a></li>)}
                </ul>
              </section>
            )}
          </div>

          <aside className="lg:sticky lg:top-4 lg:self-start">
            <div className="rounded-xl border border-gray-200 p-5 shadow-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${chip.tone}`}>{chip.text}</span>
                {u.condition !== 'new' && <span className="rounded bg-gray-800 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">{u.condition}</span>}
                <span className="text-[11px] font-bold uppercase tracking-[0.12em] text-red-700">{u.category_label}</span>
              </div>
              <TagBadges tags={u.tags} className="mt-2" />
              <h1 className="mt-2 font-cond text-3xl leading-tight text-gray-900">{u.title}</h1>
              {u.subtitle && <div className="text-lg text-gray-700">{u.subtitle}</div>}
              {u.headline && <p className="mt-1 text-sm text-gray-600">{u.headline}</p>}
              <div className="mt-2 text-sm text-gray-500">{[u.location_label, u.stock_number ? `Stock # ${u.stock_number}` : ''].filter(Boolean).join(' · ')}</div>

              <div className="mt-4 border-t border-gray-100 pt-4">
                {u.sold ? (
                  <>
                    <div className="text-lg font-bold text-gray-900">Sold</div>
                    <p className="mt-0.5 text-sm text-gray-600">This one found its new owner. We build these to order — tell us what you need.</p>
                    <Link to="/trucks-for-sale/build" className="mt-3 block w-full rounded-lg bg-red-700 px-4 py-3 text-center text-base font-bold text-white hover:bg-red-800">Build & price one like it</Link>
                    <button type="button" onClick={() => setContact('question')} className="mt-2 w-full text-sm font-semibold text-red-700 hover:underline">Ask about one like it</button>
                  </>
                ) : priceShown ? (
                  <>
                    <PriceTag price={u.price} size="lg" />
                    <p className="mt-1 text-xs text-gray-500">Plus tax, title and license. Trade-ins welcome.</p>
                  </>
                ) : u.price.mode === 'range' && u.price.range_available && !u.sold ? (
                  <>
                    <div className="text-sm font-semibold text-gray-900">Want a price right now?</div>
                    <p className="mt-0.5 text-sm text-gray-600">{u.price.restricted
                      ? 'Jerr-Dan units can’t carry an advertised price, but we can give you a range right now.'
                      : 'Confirm a few specs and we’ll give you a price range right now.'} Takes about two minutes.</p>
                    <button type="button" onClick={() => setChat(true)} className="mt-3 w-full rounded-lg bg-red-700 px-4 py-3 text-base font-bold text-white hover:bg-red-800">Get my price range</button>
                  </>
                ) : (
                  <div className="text-lg font-bold text-gray-900">Call for price</div>
                )}
              </div>

              {!u.sold && <div className="mt-4 grid gap-2">
                <button type="button" onClick={() => setContact('quote')} className="rounded-lg border-2 border-gray-900 px-4 py-2.5 font-bold text-gray-900 hover:bg-gray-900 hover:text-white">Request a quote</button>
                <div className="grid grid-cols-2 gap-2">
                  <a href={`tel:${PHONE.Portland.tel}`} className="rounded-lg border border-gray-300 px-3 py-2 text-center text-sm hover:border-red-400"><div className="font-semibold text-gray-900">Portland</div><div className="text-gray-600">{PHONE.Portland.phone}</div></a>
                  <a href={`tel:${PHONE.Kent.tel}`} className="rounded-lg border border-gray-300 px-3 py-2 text-center text-sm hover:border-red-400"><div className="font-semibold text-gray-900">Kent</div><div className="text-gray-600">{PHONE.Kent.phone}</div></a>
                </div>
                <div className="flex justify-center gap-4 text-sm">
                  <button type="button" onClick={() => setContact('call')} className="font-semibold text-red-700 hover:underline">Have us call you</button>
                  {offerOk && <button type="button" onClick={() => setContact('offer')} className="font-semibold text-red-700 hover:underline">Make an offer</button>}
                  <button type="button" onClick={() => setContact('question')} className="font-semibold text-red-700 hover:underline">Ask a question</button>
                </div>
              </div>}
            </div>
            <div className="mt-4 rounded-xl bg-gray-50 p-4 text-sm text-gray-700">
              <div className="font-semibold text-gray-900">Why buy from Nelson</div>
              <ul className="mt-2 space-y-1">
                <li>• Family-owned since 1937 — Portland & Kent</li>
                <li>• We install and service everything we sell</li>
                <li>• Trade-ins and financing welcome</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>

      {u.price.mode === 'range' && <PriceRangeChat open={chat} onClose={() => setChat(false)} unit={u} />}
      {contact && <ContactModal kind={contact} unit={u} onClose={() => setContact(null)} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Contact form (quote / call-back / offer / question)
// ---------------------------------------------------------------------------

function Field({ label, children, req }: { label: string; children: ReactNode; req?: boolean }) {
  return <label className="block text-sm"><span className="font-semibold text-gray-800">{label}{req && <span className="text-red-700"> *</span>}</span><div className="mt-1">{children}</div></label>
}
const inputCls = 'w-full rounded-md border border-gray-300 px-3 py-2 text-[15px] focus:border-red-600 focus:outline-none focus:ring-2 focus:ring-red-200'

function ContactModal({ kind, unit, onClose }: { kind: 'quote' | 'call' | 'offer' | 'question'; unit: UnitDetail; onClose: () => void }) {
  const [f, setF] = useState({ name: '', company: '', email: '', phone: '', zip: '', message: '', offer_amount: '', website: '' })
  const [addOns, setAddOns] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [done, setDone] = useState<FollowUp | null>(null)
  const title = { quote: 'Request a quote', call: 'Have us call you', offer: 'Make an offer', question: 'Ask a question' }[kind]
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    const r = await fetch(`/api/units/${unit.slug}/inquiry`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...f, kind, additional_items: addOns, offer_amount: f.offer_amount ? Number(f.offer_amount.replace(/[^\d.]/g, '')) : null, page_url: window.location.href }) })
    const d = await r.json().catch(() => ({}))
    setBusy(false)
    if (!r.ok) { setErr(d.detail || 'Something went wrong — please call us.'); return }
    setDone(d.follow_up)
  }
  return (
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-black/50 sm:items-center" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-6 sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div><h2 className="font-cond text-2xl text-gray-900">{title}</h2><div className="text-sm text-gray-600">{unit.title} {unit.subtitle}</div></div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-2xl text-gray-400 hover:text-gray-700">✕</button>
        </div>
        {done ? (
          <div className="mt-6 rounded-lg bg-green-50 p-4 text-green-900">{done.text}</div>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-3">
            <input type="text" name="website" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} className="hidden" tabIndex={-1} autoComplete="off" />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Name" req><input required className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoComplete="name" /></Field>
              <Field label="Company"><input className={inputCls} value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} autoComplete="organization" /></Field>
              <Field label="Email"><input type="email" className={inputCls} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} autoComplete="email" /></Field>
              <Field label="Phone" req={kind === 'call'}><input type="tel" required={kind === 'call'} className={inputCls} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} autoComplete="tel" /></Field>
            </div>
            {kind === 'quote' && <Field label="Add equipment to the quote (optional)"><AddOnPicker value={addOns} onChange={setAddOns} /></Field>}
            {kind === 'offer' && <Field label="Your offer" req><input required inputMode="numeric" placeholder="$" className={inputCls} value={f.offer_amount} onChange={(e) => setF({ ...f, offer_amount: e.target.value })} /></Field>}
            <Field label={kind === 'question' ? 'Your question' : 'Anything we should know?'} req={kind === 'question'}>
              <textarea required={kind === 'question'} rows={3} className={inputCls} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })}
                placeholder={kind === 'quote' ? 'Trade-in, financing, delivery, options…' : ''} />
            </Field>
            {err && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{err}</div>}
            <button disabled={busy} className="w-full rounded-lg bg-red-700 px-4 py-3 font-bold text-white hover:bg-red-800 disabled:opacity-60">{busy ? 'Sending…' : 'Send'}</button>
            <p className="text-center text-xs text-gray-500">Or call Portland {PHONE.Portland.phone} · Kent {PHONE.Kent.phone}</p>
          </form>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Price-range chat (the qualifier)
// ---------------------------------------------------------------------------

type Msg = { who: 'bot' | 'me'; text: ReactNode }

const TIMELINE = ['Right away', 'Within 30 days', '1–3 months', 'Just pricing it out']
const USE: Record<string, string[]> = {
  wrecker: ['Light-duty cars', 'Pickups & SUVs', 'Mixed fleet', 'Roadside & recovery'],
  carrier: ['Cars & light trucks', 'Equipment hauling', 'Dealer transport', 'Mixed'],
  aerial: ['Tree care', 'Utility work', 'Signs & lighting', 'Other'],
  trailer: ['Construction equipment', 'Ag equipment', 'Heavy haul', 'Other'],
}

export function PriceRangeChat({ open, onClose, unit }: { open: boolean; onClose: () => void; unit: UnitDetail }) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [step, setStep] = useState(0)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [confirmed, setConfirmed] = useState<boolean[]>([])
  const [addOns, setAddOns] = useState<string[]>([])
  const [c, setC] = useState({ name: '', company: '', email: '', phone: '', zip: '', website: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<null | { range: { low: number; high: number } | null; emailed: boolean; specs_confirmed: boolean; follow_up: FollowUp }>(null)
  const end = useRef<HTMLDivElement>(null)
  const specs = unit.qualify_specs
  const uses = USE[unit.category] || ['Business use', 'Fleet', 'Owner-operator', 'Other']

  // Steps: 0 timeline, 1 use, 2..(2+n-1) specs, 2+n trade-in, 3+n add-ons, 4+n contact, 5+n done
  const nSpec = specs.length
  const bot = (text: ReactNode) => setMsgs((m) => [...m, { who: 'bot', text }])
  const me = (text: string) => setMsgs((m) => [...m, { who: 'me', text }])

  useEffect(() => {
    if (!open) return
    setMsgs([
      { who: 'bot', text: <>Hi! I can get you a price range on the <b>{unit.title} {unit.subtitle}</b> right now.</> },
      { who: 'bot', text: 'First I’ll check a few specs with you, so the price is for exactly the truck you want. When do you need it?' },
    ])
    setStep(0); setAnswers({}); setConfirmed([]); setAddOns([]); setResult(null); setErr(null)
  }, [open, unit.title, unit.subtitle])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, step, result])

  function answer(key: string, value: string, next: () => void) {
    me(value); setAnswers((a) => ({ ...a, [key]: value })); setTimeout(next, 250)
  }
  function askSpec(i: number) {
    if (i < nSpec) { bot(<>This unit’s <b>{specs[i].label.toLowerCase()}</b>: <b>{specs[i].value}</b>. Is that what you need?</>); setStep(2 + i) }
    else { bot('Do you have a trade-in?'); setStep(2 + nSpec) }
  }
  function onSpec(i: number, yes: boolean) {
    me(yes ? 'Yes, that works' : 'No, I need something different')
    setConfirmed((cs) => { const n = [...cs]; n[i] = yes; return n })
    if (!yes) setTimeout(() => bot('No problem — a salesperson will price the exact spec you need.'), 200)
    setTimeout(() => askSpec(i + 1), yes ? 250 : 700)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    const r = await fetch(`/api/units/${unit.slug}/price-range`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...c, confirmed, answers: { ...answers, ...(addOns.length ? { additional_items: addOns } : {}) }, page_url: window.location.href }) })
    const d = await r.json().catch(() => ({}))
    setBusy(false)
    if (!r.ok) { setErr(d.detail || 'Something went wrong — please call us.'); return }
    setResult(d); setStep(5 + nSpec)
  }

  if (!open) return null
  const chip = 'rounded-full border border-red-300 bg-white px-3 py-1.5 text-sm font-semibold text-red-800 hover:bg-red-700 hover:text-white'
  return (
    <div className="fixed inset-0 z-[95] flex items-end justify-center bg-black/55 sm:items-center" role="dialog" aria-modal="true" aria-label="Get a price range" onClick={onClose}>
      <div className="flex h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl bg-white sm:h-[80vh] sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-gray-200 bg-[#16130f] px-4 py-3 text-white">
          <div className="grid h-9 w-9 place-items-center rounded-full bg-red-700 font-bold">N</div>
          <div className="flex-1"><div className="font-semibold">Nelson price check</div><div className="text-xs text-[#b8ae9b]">{unit.title}</div></div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-xl text-white/70 hover:text-white">✕</button>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto bg-gray-50 p-4">
          {msgs.map((m, i) => (
            <div key={i} className={`flex ${m.who === 'me' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-[15px] ${m.who === 'me' ? 'rounded-br-sm bg-red-700 text-white' : 'rounded-bl-sm border border-gray-200 bg-white text-gray-900'}`}>{m.text}</div>
            </div>
          ))}

          {step === 0 && <div className="flex flex-wrap gap-2">{TIMELINE.map((t) => <button key={t} type="button" className={chip}
            onClick={() => answer('timeline', t, () => { bot('What will the truck mainly do?'); setStep(1) })}>{t}</button>)}</div>}
          {step === 1 && <div className="flex flex-wrap gap-2">{uses.map((t) => <button key={t} type="button" className={chip}
            onClick={() => answer('use', t, () => askSpec(0))}>{t}</button>)}</div>}
          {step >= 2 && step < 2 + nSpec && (
            <div className="flex flex-wrap gap-2">
              <button type="button" className={chip} onClick={() => onSpec(step - 2, true)}>Yes, that works</button>
              <button type="button" className={chip} onClick={() => onSpec(step - 2, false)}>No, I need something different</button>
            </div>
          )}
          {step === 2 + nSpec && <div className="flex flex-wrap gap-2">{['Yes', 'No', 'Maybe'].map((t) => <button key={t} type="button" className={chip}
            onClick={() => answer('trade_in', t, () => { bot('Want anything else quoted with it? Toolboxes, lights, a hitch… we install it all.'); setStep(3 + nSpec) })}>{t}</button>)}</div>}
          {step === 3 + nSpec && (
            <div className="space-y-2 rounded-2xl border border-gray-200 bg-white p-3">
              <AddOnPicker value={addOns} onChange={setAddOns} />
              <button type="button" className="w-full rounded-lg bg-gray-900 px-4 py-2 text-sm font-bold text-white"
                onClick={() => { me(addOns.length ? `Also quote: ${addOns.join(', ')}` : 'No, just the truck'); setTimeout(() => { bot('Last thing — where should we send your price range?'); setStep(4 + nSpec) }, 250) }}>
                {addOns.length ? `Add ${addOns.length} to my quote` : 'No, just the truck'}</button>
            </div>
          )}
          {step === 4 + nSpec && (
            <form onSubmit={submit} className="space-y-2 rounded-2xl border border-gray-200 bg-white p-3">
              <input type="text" name="website" value={c.website} onChange={(e) => setC({ ...c, website: e.target.value })} className="hidden" tabIndex={-1} autoComplete="off" />
              <input required placeholder="Your name *" className={inputCls} value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} autoComplete="name" />
              <input placeholder="Company" className={inputCls} value={c.company} onChange={(e) => setC({ ...c, company: e.target.value })} autoComplete="organization" />
              <input required type="email" placeholder="Email * (we send the range here)" className={inputCls} value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} autoComplete="email" />
              <div className="grid grid-cols-2 gap-2">
                <input type="tel" placeholder="Phone" className={inputCls} value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} autoComplete="tel" />
                <input placeholder="ZIP" className={inputCls} value={c.zip} onChange={(e) => setC({ ...c, zip: e.target.value })} autoComplete="postal-code" />
              </div>
              {err && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{err}</div>}
              <button disabled={busy} className="w-full rounded-lg bg-red-700 px-4 py-2.5 font-bold text-white hover:bg-red-800 disabled:opacity-60">{busy ? 'Checking…' : 'Show my price range'}</button>
              <p className="text-center text-[11px] text-gray-500">We use your details only to follow up on this truck.</p>
            </form>
          )}
          {result && (
            <div className="space-y-3">
              {addOns.length > 0 && <div className="rounded-2xl border border-gray-200 bg-white p-3 text-sm text-gray-700">Your salesperson will add pricing for: <b>{addOns.join(', ')}</b>.</div>}
              {result.range ? (
                <div className="rounded-2xl border-2 border-red-700 bg-white p-4 text-center">
                  <div className="text-xs font-bold uppercase tracking-[0.14em] text-red-700">Your price range</div>
                  <div className="mt-1 font-cond text-4xl text-gray-900">{money(result.range.low)} – {money(result.range.high)}</div>
                  <div className="mt-1 text-sm text-gray-600">For this unit as listed. Final price depends on options, trade-in and delivery.</div>
                  {result.emailed && <div className="mt-2 text-sm text-green-700">✓ We’ve emailed it to {c.email}</div>}
                </div>
              ) : result.specs_confirmed && result.emailed ? (
                <div className="rounded-2xl border border-gray-200 bg-white p-4 text-[15px]">✓ Your price range is on its way to <b>{c.email}</b>.</div>
              ) : (
                <div className="rounded-2xl border border-gray-200 bg-white p-4 text-[15px]">Since you need a different spec than this unit, a salesperson will price exactly what you need — no guesswork.</div>
              )}
              <div className="rounded-2xl rounded-bl-sm border border-gray-200 bg-white px-3.5 py-2 text-[15px] text-gray-900">{result.follow_up.text}</div>
              <button type="button" onClick={onClose} className="w-full rounded-lg border border-gray-300 px-4 py-2 font-semibold text-gray-800">Back to the truck</button>
            </div>
          )}
          <div ref={end} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Build & Price
// ---------------------------------------------------------------------------

interface BuilderStep { name: string; order: number; multi: boolean; required: boolean; choices: { id: number; label: string; detail: string | null }[] }
interface BuilderCat { category: string; label: string; steps: BuilderStep[]; spec_hints: string[] }

const CAT_BLURB: Record<string, string> = {
  wrecker: 'Self-loading wreckers — Jerr-Dan MPL40 and MPL60 on the chassis you choose.',
  carrier: 'Rollback car carriers — aluminum or steel decks, 19 to 22 feet.',
  aerial: 'Dur-A-Lift bucket trucks for tree care, utility and sign work.',
  trailer: 'Landoll traveling-axle and detachable equipment trailers.',
}
const CAB = ['Regular cab', 'Extended cab', 'Crew cab', 'No preference']
const FUEL = ['Diesel', 'Gas', 'No preference']
const MAKES = ['Ford', 'Ram', 'Freightliner', 'International', 'Isuzu', 'Chevrolet', 'No preference']

export function BuildAndPricePage() {
  const nav = useNavigate()
  const [cfg, setCfg] = useState<BuilderCat[] | null>(null)
  const [cat, setCat] = useState<string>('')
  const [picks, setPicks] = useState<Record<string, number[]>>({})
  const [specs, setSpecs] = useState<Record<string, string>>({})
  const [answers, setAnswers] = useState<Record<string, string>>({ timeline: '' })
  const [addOns, setAddOns] = useState<string[]>([])
  const [c, setC] = useState({ name: '', company: '', email: '', phone: '', zip: '', message: '', website: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<null | { range: { low: number; high: number } | null; emailed: boolean; follow_up: FollowUp }>(null)
  const top = useRef<HTMLDivElement>(null)
  useEffect(() => { fetch('/api/units/builder').then((r) => r.json()).then((d) => setCfg(d.categories || [])).catch(() => setCfg([])) }, [])
  const cur = useMemo(() => cfg?.find((x) => x.category === cat), [cfg, cat])
  const missing = (cur?.steps || []).filter((s) => s.required && !s.multi && !(picks[s.name] || []).length).map((s) => s.name)

  function toggle(s: BuilderStep, id: number) {
    setPicks((p) => {
      const cur = p[s.name] || []
      if (!s.multi) return { ...p, [s.name]: [id] }
      return { ...p, [s.name]: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id] }
    })
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(null)
    const r = await fetch('/api/units/builder/quote', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...c, category: cat, choice_ids: Object.values(picks).flat(), specs, answers: { ...answers, ...(addOns.length ? { additional_items: addOns } : {}) }, page_url: window.location.href }) })
    const d = await r.json().catch(() => ({}))
    setBusy(false)
    if (!r.ok) { setErr(d.detail || 'Something went wrong — please call us.'); return }
    setResult(d); top.current?.scrollIntoView({ behavior: 'smooth' })
  }
  const labelFor = (s: BuilderStep) => (picks[s.name] || []).map((id) => s.choices.find((x) => x.id === id)?.label).filter(Boolean).join(', ')

  return (
    <div className="bg-white" ref={top}>
      <Seo title="Build & Price Your Truck — Wreckers, Carriers, Bucket Trucks | Nelson Truck Equipment"
        description="Spec the wrecker, rollback carrier, bucket truck or Landoll trailer you need and get a price range in two minutes, based on what Nelson has built and sold. A salesperson follows up."
        path="/trucks-for-sale/build" ready={cfg !== null} />
      <div className="border-b-4 border-red-700 bg-[#16130f] text-[#f4efe6]">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
          <Link to="/trucks-for-sale" className="text-sm text-[#b8ae9b] hover:text-white">‹ Trucks for sale</Link>
          <h1 className="mt-1 font-cond text-4xl text-white md:text-5xl">Build & price <span className="text-amber-400">your truck</span></h1>
          <p className="mt-2 max-w-2xl text-[15px] text-[#b8ae9b]">Pick the body, chassis and options. We’ll give you a price range right away — based on what we’ve actually built and sold — and a salesperson follows up to nail down the details.</p>
        </div>
      </div>

      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        {result ? (
          <div className="mx-auto max-w-2xl text-center">
            {result.range ? <>
              <div className="text-xs font-bold uppercase tracking-[0.14em] text-red-700">Your ballpark{addOns.length ? ' for the truck' : ''}</div>
              <div className="mt-1 font-cond text-5xl text-gray-900">{money(result.range.low)} – {money(result.range.high)}</div>
              <p className="mx-auto mt-2 max-w-xl text-gray-600">For the {cur?.label.toLowerCase()} you configured, based on similar trucks we’ve built and today’s chassis and equipment pricing. Your exact price depends on the chassis we can source, options and timing.</p>
              {result.emailed && <p className="mt-2 text-sm text-green-700">✓ We’ve emailed this to {c.email}</p>}
              {addOns.length > 0 && <p className="mt-2 text-sm text-gray-700">Your salesperson will add pricing for: <b>{addOns.join(', ')}</b>.</p>}
            </> : <div className="font-cond text-3xl text-gray-900">We’ve got your build</div>}
            <div className="mx-auto mt-6 max-w-xl rounded-xl border border-gray-200 bg-gray-50 p-5 text-left text-[15px] text-gray-800">{result.follow_up.text}</div>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Link to="/trucks-for-sale" className="rounded-md bg-red-700 px-5 py-2.5 font-bold text-white hover:bg-red-800">See trucks in stock</Link>
              <button type="button" onClick={() => { setResult(null); setCat(''); setPicks({}) }} className="rounded-md border border-gray-300 px-5 py-2.5 font-semibold">Build another</button>
            </div>
          </div>
        ) : cfg === null ? <div className="py-16 text-center text-gray-500">Loading…</div> : (
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_280px]">
            <div className="min-w-0 space-y-8">
              <section>
                <h2 className="font-cond text-2xl text-gray-900">1. What are you building?</h2>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  {cfg.map((x) => (
                    <button key={x.category} type="button" onClick={() => { setCat(x.category); setPicks({}); setSpecs({}) }}
                      className={`rounded-xl border-2 p-4 text-left transition ${cat === x.category ? 'border-red-700 bg-red-50' : 'border-gray-200 hover:border-red-300'}`}>
                      <div className="font-cond text-xl text-gray-900">{x.label}</div>
                      <div className="mt-1 text-sm text-gray-600">{CAT_BLURB[x.category] || ''}</div>
                    </button>
                  ))}
                  <button type="button" onClick={() => nav('/contact?topic=quote')} className="rounded-xl border-2 border-dashed border-gray-300 p-4 text-left hover:border-red-300">
                    <div className="font-cond text-xl text-gray-900">Something else</div>
                    <div className="mt-1 text-sm text-gray-600">Crane truck, service or dump truck, a custom build — tell us about it.</div>
                  </button>
                </div>
              </section>

              {cur && cur.steps.map((s, si) => (
                <section key={s.name}>
                  <h2 className="font-cond text-2xl text-gray-900">{si + 2}. {s.name}{s.multi && <span className="ml-2 text-sm font-sans text-gray-500">(pick any)</span>}</h2>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    {s.choices.map((ch) => {
                      const on = (picks[s.name] || []).includes(ch.id)
                      return (
                        <button key={ch.id} type="button" onClick={() => toggle(s, ch.id)}
                          className={`flex items-start gap-3 rounded-xl border-2 p-4 text-left transition ${on ? 'border-red-700 bg-red-50' : 'border-gray-200 hover:border-red-300'}`}>
                          <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center ${s.multi ? 'rounded' : 'rounded-full'} border-2 ${on ? 'border-red-700 bg-red-700 text-white' : 'border-gray-400'} text-xs`}>{on ? '✓' : ''}</span>
                          <span><span className="block font-semibold text-gray-900">{ch.label}</span>{ch.detail && <span className="mt-0.5 block text-sm text-gray-600">{ch.detail}</span>}</span>
                        </button>
                      )
                    })}
                  </div>
                </section>
              ))}

              {cur && (
                <section>
                  <h2 className="font-cond text-2xl text-gray-900">{cur.steps.length + 2}. Your specs <span className="text-sm font-sans text-gray-500">(optional — helps us quote apples to apples)</span></h2>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    {cat !== 'trailer' && <>
                      <Field label="Chassis make"><select className={inputCls} value={specs['Chassis make'] || ''} onChange={(e) => setSpecs({ ...specs, 'Chassis make': e.target.value })}><option value="">—</option>{MAKES.map((m) => <option key={m}>{m}</option>)}</select></Field>
                      <Field label="Cab"><select className={inputCls} value={specs['Cab'] || ''} onChange={(e) => setSpecs({ ...specs, Cab: e.target.value })}><option value="">—</option>{CAB.map((m) => <option key={m}>{m}</option>)}</select></Field>
                      <Field label="Fuel"><select className={inputCls} value={specs['Fuel'] || ''} onChange={(e) => setSpecs({ ...specs, Fuel: e.target.value })}><option value="">—</option>{FUEL.map((m) => <option key={m}>{m}</option>)}</select></Field>
                      <Field label="CDL"><select className={inputCls} value={specs['CDL'] || ''} onChange={(e) => setSpecs({ ...specs, CDL: e.target.value })}><option value="">—</option><option>Must be non-CDL</option><option>CDL is fine</option></select></Field>
                    </>}
                    {cur.spec_hints.slice(0, 4).map((h) => (
                      <Field key={h} label={h}><input className={inputCls} value={specs[h] || ''} onChange={(e) => setSpecs({ ...specs, [h]: e.target.value })} /></Field>
                    ))}
                    <Field label="When do you need it?">
                      <select className={inputCls} value={answers.timeline} onChange={(e) => setAnswers({ ...answers, timeline: e.target.value })}><option value="">—</option>{TIMELINE.map((t) => <option key={t}>{t}</option>)}</select>
                    </Field>
                    <Field label="Trade-in?"><select className={inputCls} value={answers.trade_in || ''} onChange={(e) => setAnswers({ ...answers, trade_in: e.target.value })}><option value="">—</option><option>Yes</option><option>No</option></select></Field>
                  </div>
                </section>
              )}

              {cur && (
                <section>
                  <h2 className="font-cond text-2xl text-gray-900">{cur.steps.length + 3}. Add equipment <span className="text-sm font-sans text-gray-500">(optional — your salesperson prices these with the build)</span></h2>
                  <div className="mt-3"><AddOnPicker value={addOns} onChange={setAddOns} /></div>
                </section>
              )}

              {cur && (
                <section>
                  <h2 className="font-cond text-2xl text-gray-900">{cur.steps.length + 4}. Where should we send your price?</h2>
                  <form onSubmit={submit} className="mt-3 space-y-3">
                    <input type="text" name="website" value={c.website} onChange={(e) => setC({ ...c, website: e.target.value })} className="hidden" tabIndex={-1} autoComplete="off" />
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="Name" req><input required className={inputCls} value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} autoComplete="name" /></Field>
                      <Field label="Company"><input className={inputCls} value={c.company} onChange={(e) => setC({ ...c, company: e.target.value })} autoComplete="organization" /></Field>
                      <Field label="Email" req><input required type="email" className={inputCls} value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} autoComplete="email" /></Field>
                      <Field label="Phone"><input type="tel" className={inputCls} value={c.phone} onChange={(e) => setC({ ...c, phone: e.target.value })} autoComplete="tel" /></Field>
                    </div>
                    <Field label="Anything else?"><textarea rows={3} className={inputCls} value={c.message} onChange={(e) => setC({ ...c, message: e.target.value })} placeholder="Special equipment, delivery, financing…" /></Field>
                    {missing.length > 0 && <div className="text-sm text-amber-700">Still to choose: {missing.join(', ')}</div>}
                    {err && <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{err}</div>}
                    <button disabled={busy || missing.length > 0} className="w-full rounded-lg bg-red-700 px-4 py-3 text-base font-bold text-white hover:bg-red-800 disabled:opacity-50 sm:w-auto sm:px-8">{busy ? 'Pricing…' : 'Get my price range'}</button>
                  </form>
                </section>
              )}
            </div>

            <aside className="lg:sticky lg:top-4 lg:self-start">
              <div className="rounded-xl border border-gray-200 p-4">
                <div className="text-xs font-bold uppercase tracking-[0.14em] text-red-700">Your build</div>
                {!cur ? <p className="mt-2 text-sm text-gray-500">Pick what you’re building to start.</p> : (
                  <dl className="mt-2 space-y-2 text-sm">
                    <div><dt className="text-gray-500">Type</dt><dd className="font-semibold text-gray-900">{cur.label}</dd></div>
                    {cur.steps.map((s) => <div key={s.name}><dt className="text-gray-500">{s.name}</dt><dd className="font-semibold text-gray-900">{labelFor(s) || <span className="font-normal text-gray-400">{s.multi ? 'None' : '—'}</span>}</dd></div>)}
                    {addOns.length > 0 && <div><dt className="text-gray-500">Also quote</dt><dd className="font-semibold text-gray-900">{addOns.join(', ')}</dd></div>}
                  </dl>
                )}
              </div>
              <p className="mt-3 text-xs text-gray-500">Prefer to talk? Portland {PHONE.Portland.phone} · Kent {PHONE.Kent.phone}</p>
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}
