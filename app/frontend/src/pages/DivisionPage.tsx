import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Seo } from '../components/Seo'
import { BRANCHES, InquiryForm } from '../components/Inquiry'

// Division landing pages (launch audit 2026-09-22). The Tow Trucks, Trailers and
// Metal & Hardware menus sent every link to the generic /catalog, which shows
// hitch parts and floor mats -- nothing about the division. These are built-to-
// order / counter-sale lines, so each page says what we sell, shows whatever we
// do stock online, and puts a quote form on the page.

interface DivisionConfig {
  slug: string
  path: string
  title: string          // <title>
  description: string    // meta description
  eyebrow: string
  h1: string
  intro: string
  heroImage?: string
  sections: { id: string; heading: string; body: string; bullets?: string[] }[]
  catalog?: { heading: string; categoryTop: string; categoryPath: string; linkLabel: string }
  formHeading: string
  formKind: 'quote' | 'contact'
}

const DIVISIONS: Record<string, DivisionConfig> = {
  'tow-trucks': {
    slug: 'tow-trucks',
    path: '/tow-trucks',
    title: 'Tow Trucks, Wreckers & Rollbacks — Jerr-Dan | Nelson Truck Equipment',
    description: 'Jerr-Dan wreckers and rollback carriers, tow truck parts and recovery equipment — sold, upfit and serviced at Nelson Truck Equipment in Portland, OR and Kent, WA.',
    eyebrow: 'Tow Trucks · Towing & Recovery',
    h1: 'Tow trucks, built to order',
    intro: 'Jerr-Dan wreckers and rollback carriers, spec’d for your chassis and your calls — plus the parts and recovery gear that keep a tow operator running. Sold, mounted and serviced at our Portland and Kent shops.',
    heroImage: '/banner/tow-rollback.jpg',
    sections: [
      { id: 'wreckers', heading: 'Wreckers & rollbacks', body: 'Light-, medium- and heavy-duty Jerr-Dan wreckers and steel or aluminum rollback carriers, built to order on your chassis or one we source. Tell us the chassis, deck length and what you haul, and we’ll quote the build.' },
      { id: 'parts', heading: 'Tow truck parts', body: 'We stock Jerr-Dan and tow truck parts at our counters. Call with the part number or your unit’s serial number and we’ll check stock at both branches.' },
      { id: 'recovery', heading: 'Recovery equipment', body: 'Wheel-lift dollies, chains, straps and truck-mounted storage for recovery work — the in-stock items are listed below and can be picked up today.' },
    ],
    catalog: { heading: 'Recovery equipment in stock', categoryTop: 'Truck Equipment', categoryPath: 'Truck Equipment > Towing & Recovery', linkLabel: 'All towing & recovery products' },
    formHeading: 'Request a tow truck quote',
    formKind: 'quote',
  },
  trailers: {
    slug: 'trailers',
    path: '/trailers',
    title: 'Landoll Trailers & Landoll Parts | Nelson Truck Equipment',
    description: 'Nelson Truck Equipment is a Landoll dealer: traveling-axle, detach gooseneck and sliding-axle trailers, trailer parts and Landoll parts — Portland, OR and Kent, WA.',
    eyebrow: 'Trailers · Landoll Dealer',
    h1: 'Landoll trailers & parts',
    intro: 'We’re a Landoll dealer. Traveling-axle, detach gooseneck and sliding-axle trailers, sold and serviced here — and Landoll parts at the counter.',
    heroImage: '/banner/landoll-trailer.jpg',
    sections: [
      { id: 'traveling-axle', heading: 'Traveling-axle trailers', body: 'Landoll traveling-axle trailers for equipment dealers, rental fleets and contractors. Tell us what you haul and we’ll match the model.' },
      { id: 'detach', heading: 'Detach gooseneck trailers', body: 'Detachable-gooseneck trailers for front-loading heavy equipment. Ask us about deck lengths and capacities.' },
      { id: 'sliding-axle', heading: 'Sliding-axle trailers', body: 'Landoll sliding-axle trailers — ask us which model fits your equipment and your routes.' },
      { id: 'parts', heading: 'Trailer & Landoll parts', body: 'Call either counter with your trailer’s model and serial number and we’ll check stock or order the part.' },
    ],
    formHeading: 'Ask about a trailer or a part',
    formKind: 'quote',
  },
  steel: {
    slug: 'steel',
    path: '/steel',
    title: 'Steel & Aluminum Stock, Cut at the Counter — Portland & Kent | Nelson Truck Equipment',
    description: 'Yes, we sell steel. Bar, tube, angle, plate and sheet in stock at our Portland, OR and Kent, WA shops — buy it by the pound at the counter and we’ll cut small jobs while you wait.',
    eyebrow: 'Metal & Hardware · At the counter',
    h1: 'Yes — we sell steel',
    intro: 'Bar, tube, angle, plate and sheet in stock at both shops. Buy it by the pound at the counter, and we’ll cut small jobs while you wait. Metal is sold in person only — come see us or call ahead to check what’s on the rack.',
    sections: [
      { id: 'steel-stock', heading: 'Steel & aluminum stock', body: 'Common sizes of steel and aluminum kept on the rack at both branches, priced by the pound.' },
      { id: 'shapes', heading: 'Bar · tube · angle · plate & sheet', body: 'Flat bar, square and rectangular tube, angle, plate and sheet. Call ahead with your sizes and we’ll check the rack.' },
      { id: 'fasteners', heading: 'Nuts, bolts & fasteners', body: 'The hardware to finish the job, at the same counter.' },
      { id: 'cutting', heading: 'Cut-to-size service', body: 'We cut small jobs while you wait. Cut material is sold at the counter only — we don’t ship cut metal.' },
    ],
    formHeading: 'Check stock or ask about a cut',
    formKind: 'contact',
  },
}

interface Hit { sku: string; name: string; brand: string | null; image_url: string | null; in_stock: boolean; stock_total: number; retail_price: number | null }

function CategoryStrip({ top, path }: { top: string; path: string }) {
  const [hits, setHits] = useState<Hit[]>([])
  useEffect(() => {
    let alive = true
    fetch(`/api/catalog/browse?category_top=${encodeURIComponent(top)}&category_path=${encodeURIComponent(path)}&per_page=12&in_stock=1`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive) setHits(d?.hits || []) })
      .catch(() => {})
    return () => { alive = false }
  }, [top, path])
  if (hits.length === 0) return null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {hits.map((h) => (
        <Link key={h.sku} to={`/product/${encodeURIComponent(h.sku)}`} className="flex flex-col overflow-hidden rounded border border-gray-200 bg-white hover:shadow">
          <div className="flex aspect-square items-center justify-center bg-white">
            {h.image_url
              ? <img src={h.image_url} alt="" loading="lazy" className="h-[85%] w-[85%] object-contain" />
              : <span className="text-[10px] uppercase text-gray-300">No image</span>}
          </div>
          <div className="flex flex-1 flex-col border-t border-gray-100 p-2">
            <div className="text-[10px] uppercase text-gray-500">{h.brand}</div>
            <div className="line-clamp-2 text-xs text-gray-900">{h.name}</div>
            <div className="mt-auto flex items-center justify-between pt-1 text-[11px]">
              {h.in_stock ? <span className="font-semibold text-green-700">{h.stock_total} in stock</span> : <span className="text-gray-500">Special order</span>}
              {h.retail_price ? <span className="font-bold text-gray-900">${h.retail_price.toFixed(2)}</span> : null}
            </div>
          </div>
        </Link>
      ))}
    </div>
  )
}

export default function DivisionPage({ slug }: { slug: 'tow-trucks' | 'trailers' | 'steel' }) {
  const d = DIVISIONS[slug]
  const { hash } = useLocation()
  // Menu links point at sections (#parts, #quote ...); React Router doesn't
  // scroll to a hash on its own.
  useEffect(() => {
    if (!hash) { window.scrollTo(0, 0); return }
    const t = window.setTimeout(() => document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    return () => window.clearTimeout(t)
  }, [slug, hash])
  return (
    <div>
      <Seo title={d.title} description={d.description} path={d.path} image={d.heroImage} />
      <section className="bg-gradient-to-br from-red-900 via-red-800 to-red-700 text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-8 px-6 py-12 md:grid-cols-2">
          <div>
            <div className="text-xs font-bold uppercase tracking-[0.2em] text-amber-300">{d.eyebrow}</div>
            <h1 className="mt-3 font-cond text-5xl uppercase leading-none">{d.h1}</h1>
            <p className="mt-4 max-w-xl text-red-50">{d.intro}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <a href="#quote" className="rounded bg-amber-400 px-5 py-2.5 font-cond text-sm uppercase text-amber-950 hover:bg-amber-300">{d.formHeading} →</a>
              <a href={`tel:${BRANCHES[0].tel}`} className="rounded border border-white/40 px-5 py-2.5 text-sm hover:bg-white/10">Portland {BRANCHES[0].phone}</a>
              <a href={`tel:${BRANCHES[1].tel}`} className="rounded border border-white/40 px-5 py-2.5 text-sm hover:bg-white/10">Kent {BRANCHES[1].phone}</a>
            </div>
          </div>
          {d.heroImage && (
            <div className="hidden overflow-hidden rounded-xl bg-white p-3 shadow-2xl md:block">
              <img src={d.heroImage} alt="" className="h-72 w-full object-contain" onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = 'none' }} />
            </div>
          )}
        </div>
      </section>

      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="grid gap-6 md:grid-cols-2">
          {d.sections.map((s) => (
            <section key={s.id} id={s.id} className="scroll-mt-28 rounded-lg border border-gray-200 bg-white p-5">
              <h2 className="text-lg font-bold text-gray-900">{s.heading}</h2>
              <p className="mt-2 text-sm text-gray-700">{s.body}</p>
            </section>
          ))}
        </div>

        {d.catalog && (
          <section className="mt-10">
            <div className="mb-3 flex items-end justify-between gap-3">
              <h2 className="text-xl font-bold text-gray-900">{d.catalog.heading}</h2>
              <Link to={`/catalog?category_top=${encodeURIComponent(d.catalog.categoryTop)}&category_path=${encodeURIComponent(d.catalog.categoryPath)}`}
                    className="text-sm font-semibold text-red-700 hover:underline">{d.catalog.linkLabel} →</Link>
            </div>
            <CategoryStrip top={d.catalog.categoryTop} path={d.catalog.categoryPath} />
          </section>
        )}

        <section id="quote" className="mt-10 grid scroll-mt-28 gap-8 rounded-lg border border-gray-200 bg-gray-50 p-6 lg:grid-cols-3">
          <div>
            <h2 className="text-xl font-bold text-gray-900">{d.formHeading}</h2>
            <p className="mt-2 text-sm text-gray-600">A real person at the counter will get back to you within one business day.</p>
            <div className="mt-4 space-y-3 text-sm">
              {BRANCHES.map((b) => (
                <div key={b.key}>
                  <div className="font-semibold text-gray-900">{b.name}</div>
                  <div className="text-gray-600">{b.street}, {b.cityLine}</div>
                  <a className="text-red-700 hover:underline" href={`tel:${b.tel}`}>{b.phone}</a> <span className="text-gray-500">· {b.hours}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="lg:col-span-2">
            <InquiryForm prefill={{ kind: d.formKind, message: '' }} />
          </div>
        </section>
      </div>
    </div>
  )
}
