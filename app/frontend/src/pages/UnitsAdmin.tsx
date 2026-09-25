import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Seo } from '../components/Seo'

// Admin > Trucks for Sale (Ben, 2026-09-25). Organised like CommercialTruck-
// Trader's dealer backend -- Inventory, Leads, Reports -- plus the Build & Price
// price guide. The editor follows the "Post a Truck" mockup Ben approved on
// 2026-07-22: one long page, a sticky section nav and a Listing Health meter.

const money = (n: number | null | undefined) => (n == null ? '—' : '$' + Math.round(n).toLocaleString('en-US'))
const J = { 'Content-Type': 'application/json' }
async function api<T = any>(url: string, opts: RequestInit = {}): Promise<{ ok: boolean; status: number; data: T }> {
  const r = await fetch(url, { credentials: 'include', ...opts })
  const data = await r.json().catch(() => ({}))
  return { ok: r.ok, status: r.status, data }
}
const errText = (d: any, s: number) => (typeof d?.detail === 'string' ? d.detail : s === 401 || s === 403 ? 'Admins only — please log in.' : `Something went wrong (${s}).`)

const STATUS_TONE: Record<string, string> = {
  draft: 'bg-gray-200 text-gray-800', active: 'bg-green-600 text-white', pending: 'bg-amber-500 text-black',
  sold: 'bg-sky-700 text-white', archived: 'bg-gray-400 text-white',
}
const LEAD_TONE: Record<string, string> = {
  new: 'bg-red-600 text-white', contacted: 'bg-amber-400 text-black', quoted: 'bg-sky-600 text-white',
  won: 'bg-green-600 text-white', lost: 'bg-gray-400 text-white', spam: 'bg-gray-200 text-gray-600',
}
const KIND_LABEL: Record<string, string> = {
  price_range: 'Price range', build_quote: 'Build & Price', quote: 'Quote', call: 'Call me', question: 'Question', offer: 'Offer',
}

// ---------------------------------------------------------------------------
// Shell with the three tabs
// ---------------------------------------------------------------------------

function Shell({ children, openLeads }: { children: ReactNode; openLeads?: number }) {
  const { pathname } = useLocation()
  const tabs = [
    { to: '/admin/units', label: 'Inventory', on: pathname === '/admin/units' },
    { to: '/admin/units/leads', label: 'Leads', on: pathname.startsWith('/admin/units/leads'), badge: openLeads },
    { to: '/admin/units/reports', label: 'Reports', on: pathname.startsWith('/admin/units/reports') },
    { to: '/admin/units/price-guide', label: 'Price guide', on: pathname.startsWith('/admin/units/price-guide') },
  ]
  return (
    <div className="min-h-screen bg-gray-100">
      <div className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-4 pt-4 sm:px-6">
          <div className="mr-4">
            <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-red-700">Admin</div>
            <h1 className="font-cond text-2xl text-gray-900">Trucks for Sale</h1>
          </div>
          <nav className="flex gap-1">
            {tabs.map((t) => (
              <Link key={t.to} to={t.to} className={`relative border-b-[3px] px-4 pb-3 pt-2 text-sm font-bold ${t.on ? 'border-red-700 text-red-700' : 'border-transparent text-gray-600 hover:text-gray-900'}`}>
                {t.label}{t.badge ? <span className="ml-1.5 rounded-full bg-red-600 px-1.5 py-0.5 text-[10px] text-white">{t.badge}</span> : null}
              </Link>
            ))}
          </nav>
          <div className="ml-auto pb-2 text-sm"><Link to="/trucks-for-sale" className="text-gray-600 hover:text-red-700" target="_blank">View on site ↗</Link></div>
        </div>
      </div>
      <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">{children}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inventory
// ---------------------------------------------------------------------------

interface ErpRow {
  id: number; part_number: string; prod_code: string | null; warehouse: number | null; location: string | null
  onhand: number; available: number | null; committed: boolean; gl_cost: number | null; days: number | null; serial: string | null; description: string | null
  extra_desc: string | null; p1: number | null; p2: number | null; p3: number | null; kind: string
  linked_to: { id: number; status: string; title: string }[]; synced_at: string | null
}

function HealthBar({ h }: { h: any }) {
  const tone = h.can_publish ? (h.label === 'Excellent' ? 'bg-green-600' : 'bg-green-500') : 'bg-amber-500'
  return (
    <div>
      <div className="flex items-center justify-between text-xs"><span className="text-gray-500">Listing health</span><span className="font-bold text-gray-800">{h.label}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-gray-200"><div className={`h-full ${tone}`} style={{ width: `${h.score}%` }} /></div>
    </div>
  )
}

function UnlistedPanel({ onCreate }: { onCreate: (pn: string, serial: string | null) => void }) {
  const [d, setD] = useState<{ items: ErpRow[]; unlisted_count: number; unlisted_cost: number; committed_count: number; committed_cost: number; synced_at: string | null } | null>(null)
  const [open, setOpen] = useState(true)
  const [kind, setKind] = useState('')
  const [showListed, setShowListed] = useState(false)
  useEffect(() => { api('/api/admin/units/erp/unlisted').then((r) => r.ok && setD(r.data)) }, [])
  if (!d) return null
  const kinds = [...new Set(d.items.map((i) => i.kind))]
  const rows = d.items.filter((i) => (showListed || (!i.linked_to.length && !i.committed)) && (!kind || i.kind === kind))
  return (
    <section className="mb-6 rounded-xl border border-amber-300 bg-amber-50">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
        <span className="text-xl">📦</span>
        <div className="flex-1">
          <div className="font-bold text-gray-900">In stock, not listed yet: {d.unlisted_count} units · {money(d.unlisted_cost)} at cost</div>
          <div className="text-xs text-gray-600">Straight from the ERP on-hand, refreshed every 15 minutes{d.synced_at ? ` (last ${new Date(d.synced_at).toLocaleTimeString()})` : ''}. Units over $10,000 at cost.{d.committed_count ? ` Not counted: ${d.committed_count} on customers’ orders (${money(d.committed_cost)}).` : ''}</div>
        </div>
        <span className="text-gray-500">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="border-t border-amber-200 px-4 pb-4">
          <div className="flex flex-wrap items-center gap-2 py-3 text-sm">
            <button type="button" onClick={() => setKind('')} className={`rounded-full px-3 py-1 ${!kind ? 'bg-gray-900 text-white' : 'bg-white'}`}>All</button>
            {kinds.map((k) => <button key={k} type="button" onClick={() => setKind(k)} className={`rounded-full px-3 py-1 ${kind === k ? 'bg-gray-900 text-white' : 'bg-white'}`}>{k}</button>)}
            <label className="ml-auto flex items-center gap-1.5 text-gray-600"><input type="checkbox" checked={showListed} onChange={(e) => setShowListed(e.target.checked)} /> show listed and sold ones too</label>
          </div>
          <div className="max-h-[420px] overflow-auto rounded-lg border border-amber-200 bg-white">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
                <tr><th className="px-3 py-2">Kind</th><th className="px-3 py-2">Part #</th><th className="px-3 py-2">Description</th><th className="px-3 py-2">Where</th><th className="px-3 py-2 text-right">Days</th><th className="px-3 py-2 text-right">Cost</th><th className="px-3 py-2 text-right">ERP P1</th><th className="px-3 py-2" /></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-gray-100">
                    <td className="px-3 py-2 text-xs text-gray-600">{r.kind}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.part_number}{r.serial ? <div className="text-gray-400">sn {r.serial}</div> : null}</td>
                    <td className="px-3 py-2">{r.description}<div className="text-xs text-gray-500">{r.extra_desc}</div></td>
                    <td className="px-3 py-2 text-xs capitalize">{r.location || `wh ${r.warehouse}`}</td>
                    <td className={`px-3 py-2 text-right ${(r.days || 0) > 365 ? 'font-bold text-red-700' : (r.days || 0) > 180 ? 'text-amber-700' : ''}`}>{r.days ?? '—'}</td>
                    <td className="px-3 py-2 text-right">{money(r.gl_cost)}</td>
                    <td className="px-3 py-2 text-right text-gray-500">{r.p1 ? money(r.p1) : '—'}</td>
                    <td className="px-3 py-2 text-right">
                      {r.committed ? <span className="rounded bg-gray-200 px-2 py-0.5 text-[11px] font-bold text-gray-700" title="On a customer's order in the ERP">SOLD</span>
                        : r.linked_to.length ? <Link to={`/admin/units/${r.linked_to[0].id}`} className="text-xs text-gray-500 underline">{r.linked_to[0].status}</Link>
                        : <button type="button" onClick={() => onCreate(r.part_number, r.serial)} className="rounded bg-red-700 px-2.5 py-1 text-xs font-bold text-white hover:bg-red-800">List it</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

export function AdminUnitsInventoryPage() {
  const nav = useNavigate()
  const [d, setD] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [adding, setAdding] = useState(false)
  const load = useCallback(async () => {
    const qs = new URLSearchParams(); if (status) qs.set('status', status); if (q) qs.set('q', q)
    const r = await api(`/api/admin/units?${qs}`)
    if (!r.ok) { setErr(errText(r.data, r.status)); return }
    setD(r.data)
  }, [status, q])
  useEffect(() => { load() }, [load])

  async function create(body: Record<string, unknown>) {
    const r = await api('/api/admin/units', { method: 'POST', headers: J, body: JSON.stringify(body) })
    if (r.ok) nav(`/admin/units/${r.data.id}`)
    else alertBox(errText(r.data, r.status))
  }
  async function setSt(id: number, st: string) {
    const r = await api(`/api/admin/units/${id}/status`, { method: 'POST', headers: J, body: JSON.stringify({ status: st }) })
    if (!r.ok) alertBox(errText(r.data, r.status)); load()
  }

  return (
    <Shell openLeads={d?.open_leads}>
      <Seo title="Trucks for Sale — Admin" path="/admin/units" noindex />
      {err && <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</div>}
      <UnlistedPanel onCreate={(pn, serial) => create({ part_number: pn, serial })} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search make, model, VIN, stock #, consignor…" className="w-72 rounded-md border border-gray-300 px-3 py-2 text-sm" />
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="rounded-md border border-gray-300 px-2 py-2 text-sm">
          <option value="">All but archived</option>
          {['draft', 'active', 'pending', 'sold', 'archived'].map((s) => <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)} ({d?.status_counts?.[s] || 0})</option>)}
          <option value="all">Everything</option>
        </select>
        <div className="relative ml-auto">
          <button type="button" onClick={() => setAdding(!adding)} className="rounded-md bg-red-700 px-4 py-2 text-sm font-bold text-white hover:bg-red-800">+ Add unit</button>
          {adding && (
            <div className="absolute right-0 z-20 mt-1 w-72 rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
              {[
                { t: 'Unit in stock', s: 'Pick it from the list above, or start blank and link the part', b: { ownership: 'nelson' } },
                { t: 'Future build', s: 'A chassis + body we will build — available date and retail price', b: { availability: 'future_build' } },
                { t: 'Consignment', s: 'Selling it for a customer — no ERP part needed', b: { ownership: 'consignment', unit_type: 'equipment', category: 'equipment' } },
              ].map((o) => (
                <button key={o.t} type="button" onClick={() => { setAdding(false); create(o.b) }} className="block w-full rounded-md px-3 py-2 text-left hover:bg-gray-50">
                  <div className="font-semibold text-gray-900">{o.t}</div><div className="text-xs text-gray-500">{o.s}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {!d ? <div className="py-10 text-gray-500">Loading…</div> : d.items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-white py-14 text-center text-gray-600">No listings yet. Use <b>List it</b> on a unit above, or <b>+ Add unit</b>.</div>
      ) : (
        <div className="space-y-3">
          {d.items.map((u: any) => (
            <div key={u.id} className="grid overflow-hidden rounded-xl border border-gray-200 bg-white md:grid-cols-[260px_minmax(0,1fr)_240px_150px]">
              <Link to={`/admin/units/${u.id}`} className="relative block aspect-[4/3] bg-gray-100 md:aspect-auto md:h-full">
                {u.photo ? <img src={u.photo} alt="" className="h-full w-full object-cover" /> : <div className="grid h-full min-h-[150px] place-items-center text-sm text-gray-400">No photos yet</div>}
                <div className="absolute inset-x-0 bottom-0 flex gap-3 bg-black/65 px-3 py-1.5 text-xs font-semibold text-white">
                  <span className={u.counts.photos < 10 ? 'text-amber-300' : ''}>📷 {u.counts.photos}</span><span>▶ {u.counts.videos}</span><span>📄 {u.counts.documents}</span>
                </div>
              </Link>
              <div className="min-w-0 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/admin/units/${u.id}`} className="font-cond text-xl text-sky-800 hover:underline">{u.title}</Link>
                  {u.ownership === 'consignment' && <span className="rounded bg-purple-100 px-2 py-0.5 text-[11px] font-bold uppercase text-purple-800">Consignment</span>}
                  {u.availability === 'future_build' && <span className="rounded bg-sky-100 px-2 py-0.5 text-[11px] font-bold uppercase text-sky-800">Future build</span>}
                  {u.featured && <span className="rounded bg-amber-100 px-2 py-0.5 text-[11px] font-bold uppercase text-amber-800">★ Homepage</span>}
                </div>
                <div className="text-sm text-gray-700">{u.subtitle}</div>
                <div className="mt-0.5 text-xs text-gray-500">Created {new Date(u.created_at).toLocaleDateString()} · {u.category} · {u.condition}{u.location ? ` · ${u.location}` : ''}{u.stock_number ? ` · stock ${u.stock_number}` : ''}</div>
                <div className="mt-3 max-w-sm"><HealthBar h={u.health} /></div>
                {!u.health.can_publish && <div className="mt-1 text-xs text-amber-700">Needs: {u.health.items.filter((i: any) => i.blocking && !i.ok).map((i: any) => i.label).join(' · ')}</div>}
                {u.erp_state === 'committed' && <div className="mt-1 text-xs font-semibold text-sky-800">The ERP has this unit on a customer’s order — the site shows it as Sale pending. Mark it sold when it goes.</div>}
                {u.erp_state === 'gone' && <div className="mt-1 text-xs font-semibold text-red-700">No longer on hand in the ERP — it’s off the site. Mark it sold.</div>}
              </div>
              <div className="border-t border-gray-100 p-4 text-sm md:border-l md:border-t-0">
                <div className="text-xs text-gray-500">Price</div>
                <div className="font-semibold text-gray-900">
                  {u.effective_price_mode === 'show' ? money(u.sale_price || u.price) : u.effective_price_mode === 'range' ? (u.effective_range ? `${money(u.effective_range.low)}–${money(u.effective_range.high)} (range chat)` : 'Range chat — no price yet') : 'Call for price'}
                </div>
                {u.price_restricted && <div className="text-[11px] text-gray-500">Jerr-Dan: no advertised price</div>}
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-gray-600">
                  <span>Views (30d)</span><b className="text-gray-900">{u.views_30}</b>
                  <span>Leads</span><b className="text-gray-900">{u.leads}{u.new_leads ? <span className="ml-1 rounded bg-red-600 px-1 text-white">{u.new_leads} new</span> : null}</b>
                  {u.cost != null && <><span>Cost</span><b className="text-gray-900">{money(u.cost)}</b></>}
                  {u.margin_pct != null && <><span>Margin</span><b className={u.margin_pct < 8 ? 'text-red-700' : 'text-gray-900'}>{u.margin_pct}%</b></>}
                  {u.days_in_stock != null && <><span>Days in stock</span><b className={u.days_in_stock > 180 ? 'text-red-700' : 'text-gray-900'}>{u.days_in_stock}</b></>}
                </div>
              </div>
              <div className="flex flex-row flex-wrap items-center gap-2 border-t border-gray-100 p-4 md:flex-col md:items-stretch md:border-l md:border-t-0">
                <span className={`rounded px-2 py-1 text-center text-xs font-bold uppercase ${STATUS_TONE[u.status]}`}>{u.status}</span>
                <Link to={`/admin/units/${u.id}`} className="rounded-md border border-gray-300 px-3 py-1.5 text-center text-sm font-semibold hover:bg-gray-50">Edit</Link>
                {u.status === 'draft' && <button type="button" disabled={!u.health.can_publish} onClick={() => setSt(u.id, 'active')} className="rounded-md bg-green-600 px-3 py-1.5 text-sm font-bold text-white disabled:opacity-40">Publish</button>}
                {u.status === 'active' && <button type="button" onClick={() => setSt(u.id, 'pending')} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm">Sale pending</button>}
                {(u.status === 'active' || u.status === 'pending') && <button type="button" onClick={() => setSt(u.id, 'sold')} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm">Mark sold</button>}
                {u.status !== 'draft' && <a href={u.public_url} target="_blank" rel="noopener" className="text-center text-xs text-sky-700 underline">View ↗</a>}
              </div>
            </div>
          ))}
        </div>
      )}
    </Shell>
  )
}

function alertBox(msg: string) { window.alert(msg) }

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------

const SECTIONS = [
  ['identity', 'Identity & model'], ['parts', 'ERP parts'], ['pricing', 'Pricing'], ['chassis', 'Chassis specs'],
  ['upfit', 'Body / equipment'], ['features', 'Features'], ['description', 'Description'], ['media', 'Photos & media'], ['publish', 'Publish'],
] as const

const inp = 'w-full rounded-md border border-gray-300 bg-gray-50 px-2.5 py-2 text-sm focus:border-sky-600 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100'
function F({ label, children, hint, req, span }: { label: string; children: ReactNode; hint?: string; req?: boolean; span?: number }) {
  return (
    <label className={`block ${span === 2 ? 'sm:col-span-2' : span === 3 ? 'sm:col-span-3' : span === 4 ? 'sm:col-span-4' : ''}`}>
      <span className="text-[11.5px] font-semibold text-gray-600">{label}{req && <span className="text-red-700"> *</span>}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-0.5 block text-[11px] text-gray-500">{hint}</span>}
    </label>
  )
}
function Card({ id, title, eyebrow, right, children }: { id: string; title: string; eyebrow?: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section id={`s-${id}`} className="scroll-mt-20 rounded-xl border border-gray-200 bg-white shadow-sm">
      <header className="flex items-center gap-3 border-b border-gray-100 px-5 py-3.5">
        <div className="flex-1">{eyebrow && <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-gray-500">{eyebrow}</div>}<h2 className="text-base font-bold text-gray-900">{title}</h2></div>
        {right}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

type Media = { id: number; kind: string; url: string; thumb_url: string | null; poster_url: string | null; width: number | null; height: number | null; bytes: number | null; original_name: string | null; caption: string | null; doc_type: string | null }
type Upload = { key: string; name: string; pct: number; err?: string; warn?: string }

const CHUNK = 8 * 1024 * 1024

async function uploadFile(listingId: number, file: File, onPct: (p: number) => void): Promise<{ media?: Media; warning?: string; error?: string }> {
  const total = Math.max(1, Math.ceil(file.size / CHUNK))
  const uid = Array.from(crypto.getRandomValues(new Uint8Array(12))).map((b) => b.toString(16).padStart(2, '0')).join('')
  let last: any = null
  for (let i = 0; i < total; i++) {
    const fd = new FormData()
    fd.append('upload_id', uid); fd.append('index', String(i)); fd.append('total', String(total)); fd.append('filename', file.name)
    fd.append('chunk', file.slice(i * CHUNK, (i + 1) * CHUNK), 'blob')
    let r: Response | null = null
    for (let attempt = 0; attempt < 3; attempt++) {
      try { r = await fetch(`/api/admin/units/${listingId}/media/chunk`, { method: 'POST', body: fd, credentials: 'include' }); if (r.ok || r.status < 500) break } catch { /* retry */ }
      await new Promise((res) => setTimeout(res, 800 * (attempt + 1)))
    }
    if (!r) return { error: 'Network error' }
    last = await r.json().catch(() => ({}))
    if (!r.ok) return { error: last?.detail || `Upload failed (${r.status})` }
    onPct(Math.round(((i + 1) / total) * 100))
  }
  return { media: last?.media, warning: last?.warning }
}

// A video's poster frame is grabbed here, in the admin's own browser: the server
// has no ffmpeg. If this browser can't decode the file, many visitors' won't
// either -- that is worth a warning.
function grabPoster(file: File): Promise<Blob | null> {
  return new Promise((resolve) => {
    const v = document.createElement('video')
    const url = URL.createObjectURL(file)
    let done = false
    const finish = (b: Blob | null) => { if (!done) { done = true; URL.revokeObjectURL(url); resolve(b) } }
    v.muted = true; v.preload = 'auto'; v.src = url
    v.onloadeddata = () => { v.currentTime = Math.min(1.5, (v.duration || 3) / 3) }
    v.onseeked = () => {
      const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight
      if (!c.width) return finish(null)
      c.getContext('2d')?.drawImage(v, 0, 0); c.toBlob((b) => finish(b), 'image/jpeg', 0.85)
    }
    v.onerror = () => finish(null)
    setTimeout(() => finish(null), 15000)
  })
}

export function AdminUnitEditorPage() {
  const { id } = useParams()
  const lid = Number(id)
  const nav = useNavigate()
  const [meta, setMeta] = useState<any>(null)
  const [u, setU] = useState<any>(null)
  const [f, setF] = useState<Record<string, any>>({})
  const [parts, setParts] = useState<{ part_number: string; serial: string | null; role: string }[]>([])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'err' | 'info'; text: string } | null>(null)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [erpQ, setErpQ] = useState('')
  const [erpRes, setErpRes] = useState<ErpRow[]>([])
  const [vinBusy, setVinBusy] = useState(false)
  const [active, setActive] = useState('identity')
  const dragId = useRef<number | null>(null)

  const hydrate = useCallback((d: any) => {
    setU(d)
    setF({ ...d, specs: d.specs || [], features: d.features || [], video_urls: d.video_urls || [], qualify_specs: d.qualify_specs || [] })
    setParts((d.parts || []).map((p: any) => ({ part_number: p.part_number, serial: p.serial, role: p.role })))
    setDirty(false)
  }, [])
  useEffect(() => {
    api('/api/admin/units/meta').then((r) => r.ok && setMeta(r.data))
    api(`/api/admin/units/${lid}`).then((r) => (r.ok ? hydrate(r.data) : setMsg({ tone: 'err', text: errText(r.data, r.status) })))
  }, [lid, hydrate])
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  useEffect(() => {
    const obs = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && setActive(e.target.id.slice(2))), { rootMargin: '-30% 0px -60% 0px' })
    document.querySelectorAll('section[id^="s-"]').forEach((s) => obs.observe(s))
    return () => obs.disconnect()
  }, [u?.id, f.unit_type])

  const set = (k: string, v: any) => { setF((x) => ({ ...x, [k]: v })); setDirty(true) }
  const isEquip = f.unit_type === 'equipment'
  const consigned = f.ownership === 'consignment'
  const hints: string[] = meta?.spec_hints?.[f.category] || []

  async function save(extra?: Record<string, any>): Promise<any> {
    setSaving(true); setMsg(null)
    const fields: Record<string, any> = { ...f, ...(extra || {}) }
    for (const k of ['id', 'slug', 'status', 'media', 'counts', 'parts', 'health', 'title', 'subtitle', 'created_at', 'updated_at', 'published_at', 'sold_at', 'created_by', 'updated_by', 'price_restricted', 'effective_price_mode', 'effective_range', 'cost', 'margin_pct', 'erp_list_p1', 'days_in_stock', 'views_30', 'leads', 'default_qualify_specs', 'public_url', 'notice']) delete fields[k]
    const r = await api(`/api/admin/units/${lid}`, { method: 'PUT', headers: J, body: JSON.stringify({ fields, parts }) })
    setSaving(false)
    if (!r.ok) { setMsg({ tone: 'err', text: errText(r.data, r.status) }); return null }
    hydrate(r.data)
    setMsg(r.data.notice ? { tone: 'info', text: r.data.notice } : { tone: 'ok', text: 'Saved.' })
    return r.data
  }
  async function setStatus(st: string) {
    if (dirty && !(await save())) return
    const r = await api(`/api/admin/units/${lid}/status`, { method: 'POST', headers: J, body: JSON.stringify({ status: st }) })
    if (!r.ok) { setMsg({ tone: 'err', text: errText(r.data, r.status) }); return }
    hydrate(r.data); setMsg({ tone: 'ok', text: st === 'active' ? 'Published — it’s live on the site.' : `Marked ${st}.` })
  }
  async function remove() {
    if (!window.confirm(u.status === 'draft' && !u.published_at ? 'Delete this draft and its photos?' : 'Archive this listing? It comes off the site.')) return
    const r = await api(`/api/admin/units/${lid}`, { method: 'DELETE' })
    if (r.ok) nav('/admin/units')
  }
  async function decodeVin() {
    if (!f.vin) return
    setVinBusy(true)
    const r = await api(`/api/admin/units/vin/${encodeURIComponent(f.vin)}`)
    setVinBusy(false)
    if (!r.ok || !r.data.ok) { setMsg({ tone: 'err', text: r.data?.error || 'VIN decode failed' }); return }
    const got = r.data.fields; let n = 0
    setF((x) => { const y = { ...x }; for (const [k, v] of Object.entries(got)) { if (k in y && (y[k] == null || y[k] === '')) { y[k] = v; n++ } } return y })
    setDirty(true); setMsg({ tone: 'info', text: `VIN decoded (NHTSA) — filled ${n} empty field(s)${r.data.fields.gvwr_class ? `; ${r.data.fields.gvwr_class}` : ''}. Check them.` })
  }
  async function parseSheet() {
    if (!f.spec_sheet) return
    const r = await api('/api/admin/units/parse-specs', { method: 'POST', headers: J, body: JSON.stringify({ text: f.spec_sheet }) })
    if (!r.ok) return
    let n = 0
    setF((x) => { const y = { ...x }; for (const [k, v] of Object.entries(r.data.fields)) { if (k in y && (y[k] == null || y[k] === '')) { y[k] = v; n++ } } return y })
    setDirty(true); setMsg({ tone: 'info', text: n ? `Filled ${n} empty field(s) from the spec sheet — check them.` : 'Nothing new found in the spec sheet (fields already filled are never overwritten).' })
  }
  useEffect(() => {
    if (erpQ.trim().length < 3) { setErpRes([]); return }
    const t = setTimeout(() => api(`/api/admin/units/erp/search?q=${encodeURIComponent(erpQ.trim())}`).then((r) => r.ok && setErpRes(r.data.items)), 250)
    return () => clearTimeout(t)
  }, [erpQ])

  async function onFiles(files: FileList | File[]) {
    const list = Array.from(files)
    if (!list.length) return
    if (dirty) await save()
    for (const file of list) {
      const key = file.name + file.size + Math.random()
      setUploads((x) => [...x, { key, name: file.name, pct: 0 }])
      const isVideo = /\.(mp4|mov|m4v|webm)$/i.test(file.name)
      const poster = isVideo ? await grabPoster(file) : null
      const res = await uploadFile(lid, file, (p) => setUploads((x) => x.map((y) => (y.key === key ? { ...y, pct: p } : y))))
      let warn = res.warning
      if (isVideo && res.media) {
        if (poster) {
          const fd = new FormData(); fd.append('image', poster, 'poster.jpg')
          await fetch(`/api/admin/units/${lid}/media/${res.media.id}/poster`, { method: 'POST', body: fd, credentials: 'include' })
        } else warn = `${file.name}: this browser couldn’t play it, so some visitors won’t either (often an iPhone HEVC video). Uploading it to YouTube and pasting the link below plays everywhere.`
      }
      setUploads((x) => x.map((y) => (y.key === key ? { ...y, pct: 100, err: res.error, warn } : y)))
    }
    const r = await api(`/api/admin/units/${lid}`)
    if (r.ok) { setU(r.data); setF((x) => ({ ...x })) }
  }
  async function delMedia(m: Media) {
    if (!window.confirm(`Remove ${m.kind}?`)) return
    await api(`/api/admin/units/${lid}/media/${m.id}`, { method: 'DELETE' })
    const r = await api(`/api/admin/units/${lid}`); if (r.ok) setU(r.data)
  }
  async function reorder(kind: string, fromId: number, toId: number) {
    const list: Media[] = u.media.filter((m: Media) => m.kind === kind)
    const from = list.findIndex((m) => m.id === fromId), to = list.findIndex((m) => m.id === toId)
    if (from < 0 || to < 0 || from === to) return
    const moved = [...list]; const [x] = moved.splice(from, 1); moved.splice(to, 0, x)
    const others = u.media.filter((m: Media) => m.kind !== kind)
    const all = [...moved, ...others]
    setU({ ...u, media: all })
    await api(`/api/admin/units/${lid}/media/order`, { method: 'PATCH', headers: J, body: JSON.stringify({ ids: all.map((m: Media) => m.id) }) })
  }
  async function patchMedia(m: Media, body: Record<string, string>) {
    await api(`/api/admin/units/${lid}/media/${m.id}`, { method: 'PATCH', headers: J, body: JSON.stringify(body) })
  }

  if (!u || !meta) return <Shell><div className="py-10 text-gray-500">{msg?.text || 'Loading…'}</div></Shell>
  const photos: Media[] = u.media.filter((m: Media) => m.kind === 'photo')
  const videos: Media[] = u.media.filter((m: Media) => m.kind === 'video')
  const docs: Media[] = u.media.filter((m: Media) => m.kind === 'document')
  const h = u.health
  const restricted = u.price_restricted || /jerr.?dan/i.test(f.upfit_make || '') || /jerr.?dan/i.test(f.make || '')
  const mode = restricted && f.price_mode === 'show' ? 'range' : f.price_mode
  const qspecs = (f.qualify_specs && f.qualify_specs.length ? f.qualify_specs : u.default_qualify_specs) as { label: string; value: string }[]
  const asking = Number(f.sale_price || f.price || 0)
  const liveMargin = asking && u.cost ? Math.round(1000 * (asking - u.cost) / asking) / 10 : null

  const kvEditor = (key: 'specs' | 'qualify_specs', rows: { label: string; value: string }[], suggest: string[] = []) => (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex gap-2">
          <input className={`${inp} w-1/3`} value={r.label} placeholder="Label" list={`dl-${key}`}
            onChange={(e) => set(key, rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
          <input className={inp} value={r.value} placeholder="Value"
            onChange={(e) => set(key, rows.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
          <button type="button" onClick={() => set(key, rows.filter((_, j) => j !== i))} className="px-2 text-gray-400 hover:text-red-700" aria-label="Remove">✕</button>
        </div>
      ))}
      <datalist id={`dl-${key}`}>{suggest.map((s) => <option key={s} value={s} />)}</datalist>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => set(key, [...rows, { label: '', value: '' }])} className="rounded-md border border-gray-300 px-3 py-1.5 text-sm">+ Add row</button>
        {suggest.filter((s) => !rows.some((r) => r.label === s)).slice(0, 6).map((s) => (
          <button key={s} type="button" onClick={() => set(key, [...rows, { label: s, value: '' }])} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-700 hover:bg-gray-200">+ {s}</button>
        ))}
      </div>
    </div>
  )

  return (
    <Shell>
      <Seo title={`${u.title} — Edit listing`} path={`/admin/units/${lid}`} noindex />
      <div className="sticky top-0 z-30 -mx-4 mb-5 flex flex-wrap items-center gap-3 border-b border-gray-200 bg-gray-100/95 px-4 py-2.5 backdrop-blur sm:-mx-6 sm:px-6">
        <Link to="/admin/units" className="text-sm text-gray-600 hover:text-gray-900">‹ Inventory</Link>
        <div className="min-w-0 flex-1 truncate font-semibold text-gray-900">{u.title} <span className="font-normal text-gray-500">{u.subtitle}</span></div>
        <span className={`rounded px-2 py-1 text-xs font-bold uppercase ${STATUS_TONE[u.status]}`}>{u.status}</span>
        {dirty && <span className="text-xs font-semibold text-amber-700">Unsaved changes</span>}
        {u.status !== 'draft' && <a href={u.public_url} target="_blank" rel="noopener" className="text-sm text-sky-700 underline">View ↗</a>}
        <button type="button" onClick={() => save()} disabled={saving} className="rounded-md border border-gray-400 bg-white px-4 py-1.5 text-sm font-bold">{saving ? 'Saving…' : 'Save'}</button>
        {u.status === 'draft' && <button type="button" onClick={() => setStatus('active')} disabled={!h.can_publish} title={h.can_publish ? '' : 'Finish the items in Listing Health first'} className="rounded-md bg-red-700 px-4 py-1.5 text-sm font-bold text-white disabled:opacity-40">Publish to site</button>}
      </div>
      {msg && <div className={`mb-4 rounded-lg px-4 py-3 text-sm ${msg.tone === 'err' ? 'bg-red-50 text-red-800' : msg.tone === 'info' ? 'bg-sky-50 text-sky-900' : 'bg-green-50 text-green-800'}`}>{msg.text}</div>}

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-4 lg:sticky lg:top-16 lg:self-start">
          <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="flex items-center gap-3">
              <div className="relative grid h-14 w-14 place-items-center rounded-full" style={{ background: `conic-gradient(${h.can_publish ? '#16a34a' : '#d97706'} ${h.score}%, #e5e7eb 0)` }}>
                <div className="grid h-11 w-11 place-items-center rounded-full bg-white text-sm font-bold">{h.done}/{h.total}</div>
              </div>
              <div><div className="text-sm font-bold text-gray-900">Listing Health</div><div className={`text-xs font-bold ${h.can_publish ? 'text-green-700' : 'text-amber-700'}`}>{h.label}</div></div>
            </div>
            <ul className="mt-3 space-y-2">
              {h.items.map((i: any) => (
                <li key={i.key} className={`flex items-start gap-2 text-[12.5px] ${i.ok ? 'text-gray-800' : 'text-gray-500'}`} title={i.detail}>
                  <span className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] font-bold text-white ${i.ok ? 'bg-green-600' : i.blocking ? 'bg-red-600' : 'bg-amber-500'}`}>{i.ok ? '✓' : '!'}</span>
                  <span>{i.label}{!i.ok && i.blocking && <span className="text-red-700"> — required</span>}</span>
                </li>
              ))}
            </ul>
            {dirty && <div className="mt-2 text-[11px] text-amber-700">Save to refresh the checklist.</div>}
          </div>
          <nav className="rounded-xl border border-gray-200 bg-white p-2 shadow-sm">
            {SECTIONS.filter(([k]) => !(k === 'chassis' && isEquip)).map(([k, label]) => (
              <a key={k} href={`#s-${k}`} className={`flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-semibold ${active === k ? 'bg-red-50 text-red-700' : 'text-gray-600 hover:bg-gray-50'}`}>
                <span className={`h-2 w-2 rounded-sm ${active === k ? 'bg-red-700' : 'bg-gray-300'}`} />{label}
              </a>
            ))}
          </nav>
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="px-3 pt-2.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gray-500">Storefront preview</div>
            <div className="m-3 mb-0 aspect-[4/3] overflow-hidden rounded-lg bg-gray-100">{photos[0] && <img src={photos[0].thumb_url || photos[0].url} alt="" className="h-full w-full object-cover" />}</div>
            <div className="p-3">
              <div className="font-cond text-lg leading-tight text-gray-900">{[f.year, f.make, f.model, f.trim].filter(Boolean).join(' ') || 'Untitled unit'}</div>
              <div className="text-xs text-gray-600">{[f.upfit_make, f.upfit_model].filter(Boolean).join(' ')}{f.location ? ` · ${meta.locations.find((l: any) => l.value === f.location)?.label}` : ''}</div>
              <div className="mt-1 text-sm font-bold text-red-700">{mode === 'show' && asking ? money(asking) : mode === 'range' ? 'Get your price in 2 minutes' : 'Call for price'}</div>
            </div>
          </div>
        </aside>

        <main className="min-w-0 space-y-5">
          <Card id="identity" eyebrow="Section 1" title="Identity & model">
            <div className="grid gap-4 sm:grid-cols-4">
              <F label="Whose unit"><select className={inp} value={f.ownership} onChange={(e) => set('ownership', e.target.value)}><option value="nelson">Nelson's own</option><option value="consignment">Consignment (selling for a customer)</option></select></F>
              <F label="Type"><select className={inp} value={f.unit_type} onChange={(e) => set('unit_type', e.target.value)}><option value="truck">Truck</option><option value="trailer">Trailer</option><option value="equipment">Equipment (no chassis)</option></select></F>
              <F label="Category" req><select className={inp} value={f.category} onChange={(e) => set('category', e.target.value)}>{meta.categories.map((c: any) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></F>
              <F label="Condition"><select className={inp} value={f.condition} onChange={(e) => set('condition', e.target.value)}>{meta.conditions.map((c: string) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}</select></F>
              <F label="Availability"><select className={inp} value={f.availability} onChange={(e) => set('availability', e.target.value)}><option value="in_stock">In stock now</option><option value="future_build">Future build</option></select></F>
              {f.availability === 'future_build' && <>
                <F label="Available date" req><input type="date" className={inp} value={f.available_date || ''} onChange={(e) => set('available_date', e.target.value)} /></F>
                <F label="…or a note" span={2} hint='Shown on the card, e.g. "Ready mid-November"'><input className={inp} value={f.available_note || ''} onChange={(e) => set('available_note', e.target.value)} /></F>
              </>}
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-4">
              <F label="Year" req={!isEquip}><input inputMode="numeric" className={inp} value={f.year ?? ''} onChange={(e) => set('year', e.target.value)} /></F>
              <F label="Make" req><input className={inp} value={f.make || ''} onChange={(e) => set('make', e.target.value)} placeholder={isEquip ? 'e.g. Palfinger' : 'e.g. Ford'} /></F>
              <F label="Model" req><input className={inp} value={f.model || ''} onChange={(e) => set('model', e.target.value)} placeholder={isEquip ? 'e.g. PK 12000 knuckle boom' : 'e.g. F-550'} /></F>
              <F label="Trim"><input className={inp} value={f.trim || ''} onChange={(e) => set('trim', e.target.value)} /></F>
              {!isEquip && <F label="VIN" span={2}>
                <div className="flex gap-2"><input className={`${inp} font-mono uppercase`} maxLength={17} value={f.vin || ''} onChange={(e) => set('vin', e.target.value.toUpperCase())} />
                  <button type="button" onClick={decodeVin} disabled={vinBusy || (f.vin || '').length !== 17} className="shrink-0 rounded-md border border-gray-300 bg-white px-3 text-sm font-semibold disabled:opacity-40">{vinBusy ? '…' : 'Decode'}</button></div>
              </F>}
              <F label="Stock #"><input className={inp} value={f.stock_number || ''} onChange={(e) => set('stock_number', e.target.value)} /></F>
              <F label="Location" req><select className={inp} value={f.location || ''} onChange={(e) => set('location', e.target.value)}><option value="">—</option>{meta.locations.map((l: any) => <option key={l.value} value={l.value}>{l.label}</option>)}</select></F>
              {!isEquip && <F label="Mileage"><input inputMode="numeric" className={inp} value={f.mileage ?? ''} onChange={(e) => set('mileage', e.target.value)} /></F>}
              <F label="Engine / machine hours"><input inputMode="numeric" className={inp} value={f.engine_hours ?? ''} onChange={(e) => set('engine_hours', e.target.value)} /></F>
              <F label="Headline (tagline)" span={2} hint="One line under the title"><input className={inp} maxLength={160} value={f.headline || ''} onChange={(e) => set('headline', e.target.value)} /></F>
            </div>
            {consigned && (
              <div className="mt-5 rounded-lg border border-purple-200 bg-purple-50 p-4">
                <div className="mb-3 text-xs font-bold uppercase tracking-wide text-purple-800">Consignor — internal only, never shown on the site</div>
                <div className="grid gap-4 sm:grid-cols-3">
                  <F label="Consignor"><input className={inp} value={f.consignor_name || ''} onChange={(e) => set('consignor_name', e.target.value)} /></F>
                  <F label="Contact"><input className={inp} value={f.consignor_contact || ''} onChange={(e) => set('consignor_contact', e.target.value)} placeholder="Phone / email" /></F>
                  <F label="ERP customer #"><input className={inp} value={f.consignor_customer_number || ''} onChange={(e) => set('consignor_customer_number', e.target.value)} /></F>
                  <F label="Notes (floor price, commission, where it is…)" span={3}><textarea rows={2} className={inp} value={f.consignor_notes || ''} onChange={(e) => set('consignor_notes', e.target.value)} /></F>
                </div>
              </div>
            )}
          </Card>

          <Card id="parts" eyebrow="Section 2" title="ERP parts" right={<span className="text-xs text-gray-500">{consigned ? 'Not needed for consignment' : f.availability === 'future_build' ? 'The chassis and/or body it will be built from' : 'At least one must be on hand to publish'}</span>}>
            {u.parts.length > 0 && (
              <table className="mb-4 w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-gray-500"><tr><th className="py-1">Part #</th><th>Serial</th><th>Role</th><th>On hand</th><th className="text-right">Days</th><th className="text-right">Cost</th><th className="text-right">P1 / P2 / P3</th><th /></tr></thead>
                <tbody>
                  {parts.map((p, i) => { const s = u.parts.find((x: any) => x.part_number === p.part_number && (x.serial || null) === (p.serial || null)); return (
                    <tr key={p.part_number + (p.serial || '')} className="border-t border-gray-100">
                      <td className="py-2 font-mono text-xs">{p.part_number}<div className="font-sans text-gray-500">{s?.description}</div></td>
                      <td className="font-mono text-xs">{p.serial || '—'}</td>
                      <td><select className="rounded border border-gray-300 px-1 py-0.5 text-xs" value={p.role} onChange={(e) => { setParts(parts.map((x, j) => (j === i ? { ...x, role: e.target.value } : x))); setDirty(true) }}>{meta.part_roles.map((r: string) => <option key={r}>{r}</option>)}</select></td>
                      <td>{s ? (s.committed ? <span className="font-semibold text-sky-800">On a customer’s order</span> : s.on_hand ? <span className="font-semibold text-green-700">Yes · {s.warehouse === 1 ? 'Portland' : s.warehouse === 2 ? 'Kent' : `wh ${s.warehouse}`}</span> : <span className="text-red-700">Not on hand</span>) : <span className="text-gray-400">save to check</span>}</td>
                      <td className="text-right">{s?.days ?? '—'}</td>
                      <td className="text-right">{money(s?.gl_cost)}</td>
                      <td className="text-right text-xs text-gray-500">{[s?.p1, s?.p2, s?.p3].map((v: number | null) => (v ? money(v) : '—')).join(' / ')}</td>
                      <td className="text-right"><button type="button" onClick={() => { setParts(parts.filter((_, j) => j !== i)); setDirty(true) }} className="text-gray-400 hover:text-red-700">✕</button></td>
                    </tr>
                  ) })}
                </tbody>
              </table>
            )}
            {u.parts.length === 0 && parts.length > 0 && <div className="mb-3 text-sm text-gray-500">{parts.length} part(s) added — save to check stock.</div>}
            <F label="Add a part — search the on-hand by part #, serial, VIN or description">
              <input className={inp} value={erpQ} onChange={(e) => setErpQ(e.target.value)} placeholder="e.g. CHASSIS-TG183750, MPL40, 0230013566, Landoll" />
            </F>
            {erpRes.length > 0 && (
              <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-gray-200">
                {erpRes.map((r) => (
                  <button key={r.id} type="button" onClick={() => { if (!parts.some((p) => p.part_number === r.part_number && p.serial === r.serial)) { setParts([...parts, { part_number: r.part_number, serial: r.serial, role: r.prod_code === 'CHASSIS' ? 'chassis' : ['JERR', 'DRL'].includes(r.prod_code || '') ? 'body' : r.prod_code === 'LAND' ? 'trailer' : 'unit' }]); setDirty(true) } setErpQ(''); setErpRes([]) }}
                    className="flex w-full items-center gap-3 border-b border-gray-100 px-3 py-2 text-left text-sm hover:bg-sky-50">
                    <span className="font-mono text-xs">{r.part_number}</span><span className="flex-1 truncate">{r.description} <span className="text-gray-500">{r.extra_desc}</span></span>
                    <span className="text-xs text-gray-500">{r.serial ? `sn ${r.serial} · ` : ''}{r.location || `wh ${r.warehouse}`} · {money(r.gl_cost)}</span>
                    {r.committed && <span className="rounded bg-gray-200 px-1.5 text-[10px] font-bold text-gray-700">SOLD</span>}
                    {r.linked_to.length > 0 && <span className="rounded bg-amber-100 px-1.5 text-[10px] font-bold text-amber-800">on #{r.linked_to[0].id}</span>}
                  </button>
                ))}
              </div>
            )}
          </Card>

          <Card id="pricing" eyebrow="Section 3" title="Pricing">
            {restricted && <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"><b>Jerr-Dan:</b> {meta.restricted_note}</div>}
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                { v: 'show', t: 'Show the price', s: 'The number is on the listing', dis: restricted },
                { v: 'range', t: 'Price-range chat', s: 'Customer confirms the specs, leaves contact details, gets a range (also emailed)' },
                { v: 'call', t: 'Call for price', s: 'No number anywhere online' },
              ].map((o) => (
                <button key={o.v} type="button" disabled={o.dis} onClick={() => set('price_mode', o.v)}
                  className={`rounded-lg border-2 p-3 text-left disabled:cursor-not-allowed disabled:opacity-40 ${mode === o.v ? 'border-red-700 bg-red-50' : 'border-gray-200 hover:border-gray-300'}`}>
                  <div className="font-semibold text-gray-900">{o.t}</div><div className="text-xs text-gray-600">{o.s}</div>
                </button>
              ))}
            </div>
            <div className="mt-4 grid gap-4 sm:grid-cols-4">
              <F label={f.availability === 'future_build' ? 'Retail price' : 'Asking price'} req={mode === 'show' || f.availability === 'future_build'} hint={mode === 'show' ? 'Shown on the site' : 'Not shown; drives the range'}><input inputMode="decimal" className={inp} value={f.price ?? ''} onChange={(e) => set('price', e.target.value)} placeholder="$" /></F>
              {mode === 'show' && <F label="Sale price" hint="Optional — shows the asking price struck through"><input inputMode="decimal" className={inp} value={f.sale_price ?? ''} onChange={(e) => set('sale_price', e.target.value)} placeholder="$" /></F>}
              {mode === 'range' && <>
                <F label="Range low" hint="Blank = 3% under asking"><input inputMode="decimal" className={inp} value={f.range_low ?? ''} onChange={(e) => set('range_low', e.target.value)} placeholder={u.effective_range ? String(u.effective_range.low) : '$'} /></F>
                <F label="Range high" hint="Blank = 3% over asking"><input inputMode="decimal" className={inp} value={f.range_high ?? ''} onChange={(e) => set('range_high', e.target.value)} placeholder={u.effective_range ? String(u.effective_range.high) : '$'} /></F>
                <F label="Deliver the range"><select className={inp} value={f.range_delivery} onChange={(e) => set('range_delivery', e.target.value)}><option value="screen_email">In the chat + by email</option><option value="email_only">By email only</option></select></F>
              </>}
            </div>
            {(u.cost != null || u.erp_list_p1) && (
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1 rounded-lg bg-gray-50 px-4 py-2.5 text-sm">
                <span className="text-gray-500">Internal only:</span>
                {u.cost != null && <span>Cost <b>{money(u.cost)}</b></span>}
                {u.erp_list_p1 ? <span>ERP P1 <b>{money(u.erp_list_p1)}</b></span> : null}
                {liveMargin != null && <span>Margin at {money(asking)}: <b className={liveMargin < 8 ? 'text-red-700' : 'text-green-700'}>{liveMargin}%</b></span>}
                {u.days_in_stock != null && <span>In stock <b>{u.days_in_stock}</b> days</span>}
              </div>
            )}
            {mode === 'range' && (
              <div className="mt-5">
                <div className="mb-1 text-sm font-semibold text-gray-900">What the customer confirms before getting a range</div>
                <p className="mb-2 text-xs text-gray-500">One question per row: "This unit's [label]: [value]. Is that what you need?" A "no" on any row means no range — a salesperson prices their exact spec. {(!f.qualify_specs || !f.qualify_specs.length) && 'Showing the defaults built from this listing.'}</p>
                {kvEditor('qualify_specs', qspecs, ['Chassis', 'Drivetrain', 'Cab', 'Body / equipment', ...hints])}
              </div>
            )}
          </Card>

          {!isEquip && (
            <Card id="chassis" eyebrow="Section 4" title={f.unit_type === 'trailer' ? 'Trailer specs' : 'Chassis specs'}>
              <div className="grid gap-4 sm:grid-cols-4">
                {f.unit_type !== 'trailer' && <>
                  <F label="Cab"><input className={inp} list="cabs" value={f.cab_type || ''} onChange={(e) => set('cab_type', e.target.value)} /><datalist id="cabs"><option value="Regular cab" /><option value="Extended cab" /><option value="Crew cab" /><option value="Day cab" /></datalist></F>
                  <F label="Drive"><input className={inp} list="drives" value={f.drive || ''} onChange={(e) => set('drive', e.target.value)} /><datalist id="drives">{['4x2', '4x4', '6x4', '6x6'].map((d) => <option key={d} value={d} />)}</datalist></F>
                  <F label="Fuel"><input className={inp} list="fuels" value={f.fuel || ''} onChange={(e) => set('fuel', e.target.value)} /><datalist id="fuels">{['Diesel', 'Gas', 'CNG', 'Electric'].map((d) => <option key={d} value={d} />)}</datalist></F>
                  <F label="Engine"><input className={inp} value={f.engine || ''} onChange={(e) => set('engine', e.target.value)} /></F>
                  <F label="Horsepower"><input inputMode="numeric" className={inp} value={f.horsepower ?? ''} onChange={(e) => set('horsepower', e.target.value)} /></F>
                  <F label="Transmission" span={2}><input className={inp} value={f.transmission || ''} onChange={(e) => set('transmission', e.target.value)} /></F>
                </>}
                <F label="GVWR (lbs)"><input inputMode="numeric" className={inp} value={f.gvwr_lbs ?? ''} onChange={(e) => set('gvwr_lbs', e.target.value)} /></F>
                {f.unit_type !== 'trailer' && <>
                  <F label="Wheelbase (in)"><input inputMode="decimal" className={inp} value={f.wheelbase_in ?? ''} onChange={(e) => set('wheelbase_in', e.target.value)} /></F>
                  <F label="Cab to axle (in)"><input inputMode="decimal" className={inp} value={f.cab_to_axle_in ?? ''} onChange={(e) => set('cab_to_axle_in', e.target.value)} /></F>
                  <F label="Front axle (lbs)"><input inputMode="numeric" className={inp} value={f.front_axle_lbs ?? ''} onChange={(e) => set('front_axle_lbs', e.target.value)} /></F>
                  <F label="Rear axle (lbs)"><input inputMode="numeric" className={inp} value={f.rear_axle_lbs ?? ''} onChange={(e) => set('rear_axle_lbs', e.target.value)} /></F>
                </>}
                <F label="Suspension"><input className={inp} value={f.suspension || ''} onChange={(e) => set('suspension', e.target.value)} /></F>
                <F label="Brakes"><input className={inp} value={f.brakes || ''} onChange={(e) => set('brakes', e.target.value)} /></F>
                <F label="Tires"><input className={inp} value={f.tires || ''} onChange={(e) => set('tires', e.target.value)} /></F>
                {f.unit_type !== 'trailer' && <F label="Fuel capacity"><input className={inp} value={f.fuel_capacity || ''} onChange={(e) => set('fuel_capacity', e.target.value)} /></F>}
                <F label="Color"><input className={inp} value={f.color || ''} onChange={(e) => set('color', e.target.value)} /></F>
                {f.unit_type !== 'trailer' && <F label="CDL required?"><select className={inp} value={f.cdl_required == null ? '' : f.cdl_required ? 'y' : 'n'} onChange={(e) => set('cdl_required', e.target.value === '' ? null : e.target.value === 'y')}><option value="">—</option><option value="n">No (under 26,001 lb)</option><option value="y">Yes</option></select></F>}
              </div>
              <div className="mt-5">
                <F label="Full chassis spec sheet — paste it straight from the window sticker, order acknowledgement or build sheet" hint="Shown on the listing as-is under “Full chassis spec sheet”.">
                  <textarea rows={6} className={`${inp} font-mono text-[12.5px]`} value={f.spec_sheet || ''} onChange={(e) => set('spec_sheet', e.target.value)} />
                </F>
                <button type="button" onClick={parseSheet} disabled={!f.spec_sheet} className="mt-2 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-semibold disabled:opacity-40">Fill empty fields from the spec sheet</button>
              </div>
            </Card>
          )}

          <Card id="upfit" eyebrow={`Section ${isEquip ? 4 : 5}`} title={isEquip ? 'Equipment specs' : 'Body / upfit'}>
            {!isEquip && f.unit_type !== 'trailer' && (
              <div className="mb-4 grid gap-4 sm:grid-cols-3">
                <F label="Body / upfit make"><input className={inp} list="upmakes" value={f.upfit_make || ''} onChange={(e) => set('upfit_make', e.target.value)} /><datalist id="upmakes">{['Jerr-Dan', 'Dur-A-Lift', 'Knapheide', 'Landoll', 'Palfinger', 'Auto Crane', 'Rugby', 'Godwin'].map((m) => <option key={m} value={m} />)}</datalist></F>
                <F label="Body / upfit model" span={2}><input className={inp} value={f.upfit_model || ''} onChange={(e) => set('upfit_model', e.target.value)} placeholder="e.g. MPL40 self-loading wrecker, 22 ft steel carrier" /></F>
                <F label="Body description" span={3}><textarea rows={3} className={inp} value={f.upfit_description || ''} onChange={(e) => set('upfit_description', e.target.value)} /></F>
              </div>
            )}
            <div className="mb-1 text-sm font-semibold text-gray-900">Specs</div>
            {kvEditor('specs', f.specs || [], hints)}
          </Card>

          <Card id="features" eyebrow="Section" title="Features & options" right={<span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">{(f.features || []).length} selected</span>}>
            <div className="columns-2 gap-6 md:columns-3">
              {meta.features.map((ft: string) => {
                const on = (f.features || []).includes(ft)
                return <label key={ft} className={`flex break-inside-avoid items-center gap-2 py-1 text-sm ${on ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>
                  <input type="checkbox" checked={on} onChange={() => set('features', on ? f.features.filter((x: string) => x !== ft) : [...(f.features || []), ft])} className="h-4 w-4 accent-red-700" />{ft}</label>
              })}
            </div>
          </Card>

          <Card id="description" eyebrow="Section" title="Description" right={<span className={`text-xs ${(f.description || '').length >= 250 ? 'text-green-700' : 'text-gray-500'}`}>{(f.description || '').length} / 250+ characters</span>}>
            <textarea rows={8} className={inp} value={f.description || ''} onChange={(e) => set('description', e.target.value)}
              placeholder="What the customer reads. What it is, what it does well, what's been done to it, who it suits. Plain words — no ALL CAPS." />
          </Card>

          <Card id="media" eyebrow="Section" title="Photos & media" right={<span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${photos.length >= meta.min_photos ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'}`}>{photos.length} photos · {meta.min_photos}+ required</span>}>
            <label onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files) }}
              className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 px-4 py-8 text-center hover:border-red-400 hover:bg-red-50/40">
              <span className="text-3xl">📷</span>
              <span className="mt-1 font-semibold text-gray-900">Drop photos, videos or PDFs here, or click to choose</span>
              <span className="text-xs text-gray-500">JPG, PNG, HEIC (iPhone), WebP · MP4, MOV, WebM up to 750 MB · PDF spec sheets. Full-size originals from the camera look best.</span>
              <input type="file" multiple accept="image/*,video/*,.heic,.heif,.pdf" className="hidden" onChange={(e) => { if (e.target.files) onFiles(e.target.files); e.target.value = '' }} />
            </label>
            {uploads.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {uploads.map((x) => (
                  <li key={x.key} className="text-sm">
                    <div className="flex items-center gap-2"><span className="w-56 truncate">{x.name}</span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200"><div className={`h-full ${x.err ? 'bg-red-600' : 'bg-green-600'}`} style={{ width: `${x.pct}%` }} /></div>
                      <span className="w-10 text-right text-xs">{x.err ? '✕' : `${x.pct}%`}</span></div>
                    {(x.err || x.warn) && <div className={`ml-1 text-xs ${x.err ? 'text-red-700' : 'text-amber-700'}`}>{x.err || x.warn}</div>}
                  </li>
                ))}
                <li><button type="button" onClick={() => setUploads([])} className="text-xs text-gray-500 underline">clear</button></li>
              </ul>
            )}
            {photos.length > 0 && <>
              <div className="mt-4 mb-1 text-xs text-gray-500">Drag to reorder. The first photo is the one on the card and the homepage.</div>
              <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-4 lg:grid-cols-6">
                {photos.map((m, i) => (
                  <div key={m.id} draggable onDragStart={() => { dragId.current = m.id }} onDragOver={(e) => e.preventDefault()} onDrop={() => { if (dragId.current != null) reorder('photo', dragId.current, m.id); dragId.current = null }}
                    className="group relative aspect-[4/3] cursor-move overflow-hidden rounded-lg border border-gray-200 bg-gray-100">
                    <img src={m.thumb_url || m.url} alt="" className="h-full w-full object-cover" />
                    {i === 0 && <span className="absolute left-1.5 top-1.5 rounded bg-red-700 px-1.5 py-0.5 text-[9.5px] font-bold text-white">PRIMARY</span>}
                    {m.width && m.width < 1200 && <span className="absolute bottom-1.5 left-1.5 rounded bg-amber-500 px-1 text-[9.5px] font-bold text-black" title="Low resolution">LOW-RES</span>}
                    <button type="button" onClick={() => delMedia(m)} className="absolute right-1.5 top-1.5 hidden h-6 w-6 rounded-full bg-black/70 text-xs text-white group-hover:block" aria-label="Delete photo">✕</button>
                  </div>
                ))}
              </div>
            </>}
            {videos.length > 0 && (
              <div className="mt-5">
                <div className="mb-2 text-sm font-semibold text-gray-900">Videos</div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {videos.map((m) => (
                    <div key={m.id} className="rounded-lg border border-gray-200 p-2">
                      <video src={m.url} poster={m.poster_url || undefined} controls preload="metadata" className="aspect-video w-full rounded bg-black" />
                      <div className="mt-1 flex items-center gap-2 text-xs text-gray-600"><span className="flex-1 truncate">{m.original_name} · {m.bytes ? Math.round(m.bytes / 1048576) + ' MB' : ''}</span><button type="button" onClick={() => delMedia(m)} className="text-red-700">Remove</button></div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-5">
              <F label="YouTube / Vimeo links" hint="One per line. Plays everywhere and costs no server space — the best home for long walk-arounds.">
                <textarea rows={2} className={inp} value={(f.video_urls || []).join('\n')} onChange={(e) => set('video_urls', e.target.value.split('\n').map((s) => s.trim()).filter(Boolean))} />
              </F>
            </div>
            {docs.length > 0 && (
              <div className="mt-5 space-y-2">
                <div className="text-sm font-semibold text-gray-900">Documents</div>
                {docs.map((m) => (
                  <div key={m.id} className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm">
                    <span>📄</span>
                    <input className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm" defaultValue={m.caption || ''} onBlur={(e) => patchMedia(m, { caption: e.target.value })} />
                    <select defaultValue={m.doc_type || 'other'} onChange={(e) => patchMedia(m, { doc_type: e.target.value })} className="rounded border border-gray-300 px-1 py-1 text-xs">{meta.doc_types.map((t: string) => <option key={t} value={t}>{t.replace('_', ' ')}</option>)}</select>
                    <a href={m.url} target="_blank" rel="noopener" className="text-xs text-sky-700 underline">open</a>
                    <button type="button" onClick={() => delMedia(m)} className="text-xs text-red-700">remove</button>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card id="publish" eyebrow="Section" title="Publish">
            <div className="flex flex-wrap gap-2">
              {[['draft', 'Draft'], ['active', 'Active — live on site'], ['pending', 'Sale pending'], ['sold', 'Sold']].map(([v, t]) => (
                <button key={v} type="button" onClick={() => v !== u.status && setStatus(v)} disabled={(v === 'active' || v === 'pending') && !h.can_publish && u.status === 'draft'}
                  className={`rounded-lg border-2 px-4 py-2 text-sm font-semibold disabled:opacity-40 ${u.status === v ? 'border-red-700 bg-red-50 text-red-800' : 'border-gray-200 hover:border-gray-300'}`}>{t}</button>
              ))}
            </div>
            {!h.can_publish && <p className="mt-2 text-sm text-amber-700">To publish: {h.items.filter((i: any) => i.blocking && !i.ok).map((i: any) => i.label).join(' · ')}</p>}
            <label className="mt-4 flex items-center justify-between gap-4 rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
              <span><b className="text-gray-900">Feature on the homepage</b><span className="block text-xs text-gray-600">Featured units lead the band at the top of the homepage. Lower rank shows first.</span></span>
              <span className="flex items-center gap-3"><input type="number" className="w-16 rounded border border-gray-300 px-2 py-1 text-sm" value={f.featured_rank ?? 0} onChange={(e) => set('featured_rank', e.target.value)} title="Rank" />
                <input type="checkbox" className="h-5 w-5 accent-red-700" checked={!!f.featured} onChange={(e) => set('featured', e.target.checked)} /></span>
            </label>
            <div className="mt-5 flex flex-wrap justify-between gap-3">
              <button type="button" onClick={remove} className="text-sm font-semibold text-red-700 hover:underline">{u.status === 'draft' && !u.published_at ? 'Delete draft' : 'Archive listing'}</button>
              <div className="flex gap-2">
                <button type="button" onClick={() => save()} disabled={saving} className="rounded-md border border-gray-400 bg-white px-5 py-2 font-bold">{saving ? 'Saving…' : 'Save'}</button>
                {u.status === 'draft' && <button type="button" onClick={() => setStatus('active')} disabled={!h.can_publish} className="rounded-md bg-red-700 px-5 py-2 font-bold text-white disabled:opacity-40">Publish to nelsontruck.com</button>}
              </div>
            </div>
          </Card>
        </main>
      </div>
    </Shell>
  )
}

// ---------------------------------------------------------------------------
// Leads
// ---------------------------------------------------------------------------

export function AdminUnitLeadsPage() {
  const [d, setD] = useState<any>(null)
  const [status, setStatus] = useState('open')
  const [openRow, setOpenRow] = useState<number | null>(null)
  const load = useCallback(() => api(`/api/admin/unit-leads?status=${status}`).then((r) => r.ok && setD(r.data)), [status])
  useEffect(() => { load() }, [load])
  async function patch(id: number, body: Record<string, unknown>) {
    await api(`/api/admin/unit-leads/${id}`, { method: 'PATCH', headers: J, body: JSON.stringify(body) }); load()
  }
  const counts = d?.status_counts || {}
  return (
    <Shell openLeads={counts.new}>
      <Seo title="Unit leads — Admin" path="/admin/units/leads" noindex />
      <div className="mb-4 flex flex-wrap gap-2 text-sm">
        {[['open', 'Open'], ['new', 'New'], ['contacted', 'Contacted'], ['quoted', 'Quoted'], ['won', 'Won'], ['lost', 'Lost'], ['', 'All']].map(([v, t]) => (
          <button key={t} type="button" onClick={() => setStatus(v)} className={`rounded-full px-3 py-1.5 font-semibold ${status === v ? 'bg-gray-900 text-white' : 'bg-white text-gray-700'}`}>{t}{v && v !== 'open' && counts[v] ? ` (${counts[v]})` : ''}</button>
        ))}
      </div>
      {!d ? <div className="text-gray-500">Loading…</div> : d.items.length === 0 ? <div className="rounded-xl border border-dashed border-gray-300 bg-white py-12 text-center text-gray-600">No leads here.</div> : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Unit</th><th className="px-3 py-2">Customer</th><th className="px-3 py-2">Range given</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {d.items.map((x: any) => (
                <Fragment key={x.id}>
                  <tr className="cursor-pointer border-t border-gray-100 hover:bg-gray-50" onClick={() => setOpenRow(openRow === x.id ? null : x.id)}>
                    <td className="px-3 py-2.5 text-xs text-gray-600">{new Date(x.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</td>
                    <td className="px-3 py-2.5"><span className="rounded bg-gray-100 px-2 py-0.5 text-xs font-semibold">{KIND_LABEL[x.kind] || x.kind}</span>{x.specs_confirmed === false && <div className="mt-0.5 text-[11px] font-semibold text-amber-700">wants a different spec</div>}
                      {(x.answers?.additional_items || []).length > 0 && <div className="mt-0.5 text-[11px] font-semibold text-red-700">+ also quote {x.answers.additional_items.length} item{x.answers.additional_items.length > 1 ? 's' : ''}</div>}</td>
                    <td className="px-3 py-2.5">{x.listing_id ? <Link to={`/admin/units/${x.listing_id}`} onClick={(e) => e.stopPropagation()} className="text-sky-700 hover:underline">{x.listing_title}</Link> : <span className="text-gray-700">{x.listing_title}</span>}</td>
                    <td className="px-3 py-2.5"><div className="font-semibold text-gray-900">{x.name}{x.company ? <span className="font-normal text-gray-500"> · {x.company}</span> : ''}</div>
                      <div className="text-xs">{x.email && <a href={`mailto:${x.email}`} onClick={(e) => e.stopPropagation()} className="text-sky-700">{x.email}</a>}{x.phone && <> · <a href={`tel:${x.phone}`} onClick={(e) => e.stopPropagation()} className="text-sky-700">{x.phone}</a></>}</div></td>
                    <td className="px-3 py-2.5">{x.range_low != null ? <>{money(x.range_low)}–{money(x.range_high)}</> : x.offer_amount ? <>Offer {money(x.offer_amount)}</> : '—'}</td>
                    <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <select value={x.status} onChange={(e) => patch(x.id, { status: e.target.value })} className={`rounded px-2 py-1 text-xs font-bold ${LEAD_TONE[x.status]}`}>
                        {['new', 'contacted', 'quoted', 'won', 'lost', 'spam'].map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                  </tr>
                  {openRow === x.id && (
                    <tr className="bg-gray-50"><td colSpan={6} className="px-4 py-3">
                      <div className="grid gap-4 md:grid-cols-2">
                        <div>
                          <div className="mb-1 text-xs font-bold uppercase text-gray-500">Answers</div>
                          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-sm">
                            {Object.entries(x.answers || {}).map(([k, v]) => <Fragment key={k}><dt className="text-gray-500">{k}</dt><dd className="text-gray-900">{typeof v === 'object' ? Object.entries(v as any).map(([a, b]) => `${a}: ${b}`).join(' · ') : String(v)}</dd></Fragment>)}
                          </dl>
                          {x.message && <p className="mt-2 whitespace-pre-line text-sm text-gray-800">“{x.message}”</p>}
                          {x.zip && <div className="mt-1 text-xs text-gray-500">ZIP {x.zip}</div>}
                        </div>
                        <div>
                          <div className="mb-1 text-xs font-bold uppercase text-gray-500">Notes</div>
                          <textarea rows={3} defaultValue={x.notes || ''} onBlur={(e) => e.target.value !== (x.notes || '') && patch(x.id, { notes: e.target.value })} className="w-full rounded border border-gray-300 px-2 py-1 text-sm" placeholder="Called, left voicemail…" />
                          <div className="mt-1 text-xs text-gray-500">{x.handled_by ? `Last updated by ${x.handled_by}` : ''}{x.range_emailed ? ' · range emailed to customer' : ''}</div>
                        </div>
                      </div>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  )
}

// ---------------------------------------------------------------------------
// Reports
// ---------------------------------------------------------------------------

function Tile({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: string; tone?: string }) {
  return <div className="rounded-xl border border-gray-200 bg-white p-4"><div className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</div><div className={`mt-1 text-2xl font-bold ${tone || 'text-gray-900'}`}>{value}</div>{sub && <div className="text-xs text-gray-500">{sub}</div>}</div>
}

export function AdminUnitReportsPage() {
  const [days, setDays] = useState(30)
  const [d, setD] = useState<any>(null)
  useEffect(() => { setD(null); api(`/api/admin/units/reports?days=${days}`).then((r) => r.ok && setD(r.data)) }, [days])
  const series = useMemo(() => {
    if (!d) return []
    const out: { day: string; views: number; leads: number }[] = []
    const end = new Date(); for (let i = days - 1; i >= 0; i--) { const dt = new Date(end); dt.setDate(end.getDate() - i); const k = dt.toISOString().slice(0, 10); out.push({ day: k, views: d.daily.views[k] || 0, leads: d.daily.leads[k] || 0 }) }
    return out
  }, [d, days])
  const maxV = Math.max(1, ...series.map((s) => s.views))
  const t = d?.totals
  return (
    <Shell>
      <Seo title="Unit reports — Admin" path="/admin/units/reports" noindex />
      <div className="mb-4 flex items-center gap-2 text-sm">
        <span className="text-gray-600">Period</span>
        {[7, 30, 90].map((n) => <button key={n} type="button" onClick={() => setDays(n)} className={`rounded-full px-3 py-1 font-semibold ${days === n ? 'bg-gray-900 text-white' : 'bg-white'}`}>{n} days</button>)}
      </div>
      {!d ? <div className="text-gray-500">Loading…</div> : <>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Tile label="Live on the site" value={t.live} sub={`${t.drafts} drafts · ${t.sold} sold`} />
          <Tile label="Asking, live units" value={money(t.live_asking)} sub={`${money(t.live_cost)} at cost${t.consigned_asking ? ` · ${money(t.consigned_asking)} consigned` : ''}`} />
          <Tile label="In stock, not listed" value={money(t.unlisted_cost)} sub={`${t.unlisted_count} units at cost`} tone={t.unlisted_cost > 0 ? 'text-amber-700' : undefined} />
          <Tile label={`Leads, ${days} days`} value={t.leads} sub={`${t.views} views · ${t.ranges_given} ranges given · ${t.build_quotes} builds`} />
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between text-sm"><b className="text-gray-900">Views and leads per day</b><span className="text-xs text-gray-500"><span className="mr-1 inline-block h-2 w-3 bg-sky-600" />views <span className="ml-2 mr-1 inline-block h-2 w-3 bg-red-600" />leads</span></div>
            <div className="flex h-40 items-end gap-[2px]">
              {series.map((s) => (
                <div key={s.day} className="group relative flex h-full flex-1 flex-col justify-end" title={`${s.day}: ${s.views} views, ${s.leads} leads`}>
                  <div className="w-full rounded-t-sm bg-sky-600/80" style={{ height: `${(s.views / maxV) * 100}%` }} />
                  {s.leads > 0 && <div className="absolute bottom-0 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-red-600 ring-2 ring-white" />}
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-[11px] text-gray-500"><span>{series[0]?.day}</span><span>{series[series.length - 1]?.day}</span></div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <b className="text-sm text-gray-900">Unlisted units by age (cost)</b>
            <div className="mt-3 space-y-2">
              {Object.entries(d.aging_cost as Record<string, number>).map(([k, v]) => {
                const max = Math.max(1, ...Object.values(d.aging_cost as Record<string, number>))
                return <div key={k} className="text-sm"><div className="flex justify-between"><span className="text-gray-600">{k} days</span><b>{money(v)}</b></div><div className="mt-0.5 h-2 rounded-full bg-gray-100"><div className={`h-full rounded-full ${k === '365+' ? 'bg-red-600' : k === '181-365' ? 'bg-amber-500' : 'bg-sky-600'}`} style={{ width: `${(v / max) * 100}%` }} /></div></div>
              })}
            </div>
            <div className="mt-3 text-xs text-gray-500">Listing the oldest first frees the most money.</div>
          </div>
        </div>
        <div className="mt-5 overflow-x-auto rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr><th className="px-3 py-2">Listing</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Views</th><th className="px-3 py-2 text-right">Leads</th><th className="px-3 py-2 text-right">Ranges</th><th className="px-3 py-2 text-right">Days listed</th><th className="px-3 py-2 text-right">Days in stock</th><th className="px-3 py-2 text-right">Cost</th><th className="px-3 py-2 text-right">Asking</th><th className="px-3 py-2 text-right">Margin</th></tr>
            </thead>
            <tbody>
              {d.listings.map((r: any) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="px-3 py-2"><Link to={`/admin/units/${r.id}`} className="text-sky-700 hover:underline">{r.title}</Link>{r.ownership === 'consignment' && <span className="ml-1 text-[10px] font-bold text-purple-700">CONSIGN</span>}</td>
                  <td className="px-3 py-2"><span className={`rounded px-1.5 py-0.5 text-[11px] font-bold uppercase ${STATUS_TONE[r.status]}`}>{r.status}</span></td>
                  <td className="px-3 py-2 text-right">{r.views}</td><td className="px-3 py-2 text-right">{r.leads}</td><td className="px-3 py-2 text-right">{r.ranges_given}</td>
                  <td className="px-3 py-2 text-right">{r.days_listed ?? '—'}</td>
                  <td className={`px-3 py-2 text-right ${(r.days_in_stock || 0) > 180 ? 'font-bold text-red-700' : ''}`}>{r.days_in_stock ?? '—'}</td>
                  <td className="px-3 py-2 text-right">{money(r.cost)}</td><td className="px-3 py-2 text-right">{money(r.asking)}</td>
                  <td className={`px-3 py-2 text-right ${r.margin_pct != null && r.margin_pct < 8 ? 'font-bold text-red-700' : ''}`}>{r.margin_pct != null ? `${r.margin_pct}%` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </>}
    </Shell>
  )
}

// ---------------------------------------------------------------------------
// Price guide (Build & Price)
// ---------------------------------------------------------------------------

export function AdminUnitPriceGuidePage() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [cat, setCat] = useState('wrecker')
  const [msg, setMsg] = useState<string | null>(null)
  const load = useCallback(() => api('/api/admin/unit-price-guide').then((r) => r.ok && setRows(r.data.items)), [])
  useEffect(() => { load() }, [load])
  const cats = [...new Set((rows || []).map((r) => r.category)), 'crane', 'service', 'dump'].filter((v, i, a) => a.indexOf(v) === i)
  const mine = (rows || []).filter((r) => r.category === cat)
  const groups = [...new Set(mine.map((r) => r.group_name))]
  async function saveRow(r: any) {
    const res = await api(r.id ? `/api/admin/unit-price-guide/${r.id}` : '/api/admin/unit-price-guide', { method: r.id ? 'PUT' : 'POST', headers: J, body: JSON.stringify(r) })
    setMsg(res.ok ? 'Saved.' : errText(res.data, res.status)); load()
  }
  async function del(r: any) { if (window.confirm(`Delete “${r.label}”?`)) { await api(`/api/admin/unit-price-guide/${r.id}`, { method: 'DELETE' }); load() } }
  function addRow(group: string, multi: boolean, order: number) {
    setRows([...(rows || []), { id: 0, category: cat, group_name: group || 'New step', group_order: order, multi, required: !multi, label: 'New choice', detail: '', price_low: 0, price_high: 0, sort_order: 999, active: true, basis: '' }])
  }
  return (
    <Shell>
      <Seo title="Price guide — Admin" path="/admin/units/price-guide" noindex />
      <p className="mb-4 max-w-3xl text-sm text-gray-600">What <Link to="/trucks-for-sale/build" className="text-sky-700 underline" target="_blank">Build & Price</Link> adds up. A customer’s range is the sum of their choices, widened 3% and rounded out to $5,000 — they never see a single choice’s number. The starting values come from Nelson’s own invoices 2023–26; each row’s <i>basis</i> says which.</p>
      <div className="mb-4 flex flex-wrap gap-2">{cats.map((c) => <button key={c} type="button" onClick={() => setCat(c)} className={`rounded-full px-3 py-1.5 text-sm font-semibold capitalize ${cat === c ? 'bg-gray-900 text-white' : 'bg-white'}`}>{c}</button>)}</div>
      {msg && <div className="mb-3 text-sm text-gray-700">{msg}</div>}
      {!rows ? <div className="text-gray-500">Loading…</div> : (
        <div className="space-y-5">
          {groups.map((g) => { const gr = mine.filter((r) => r.group_name === g); const multi = !!gr[0]?.multi; return (
            <div key={g} className="rounded-xl border border-gray-200 bg-white">
              <div className="flex items-center gap-3 border-b border-gray-100 px-4 py-2.5"><b className="text-gray-900">{g}</b><span className="text-xs text-gray-500">{multi ? 'pick any (options)' : 'pick one'} · step {gr[0]?.group_order}</span>
                <button type="button" onClick={() => addRow(g, multi, gr[0]?.group_order || 0)} className="ml-auto text-sm text-sky-700">+ Add choice</button></div>
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-gray-500"><tr><th className="px-3 py-1.5">Choice</th><th className="px-3 py-1.5">Detail shown</th><th className="px-3 py-1.5 text-right">Low</th><th className="px-3 py-1.5 text-right">High</th><th className="px-3 py-1.5">Basis (internal)</th><th className="px-3 py-1.5">On</th><th /></tr></thead>
                <tbody>{gr.map((r) => <GuideRow key={r.id || r.label + r.sort_order} r={r} onSave={saveRow} onDel={del} />)}</tbody>
              </table>
            </div>
          ) })}
          <button type="button" onClick={() => addRow('New step', false, (Math.max(0, ...mine.map((r) => r.group_order)) + 10))} className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-semibold">+ Add a step to {cat}</button>
        </div>
      )}
    </Shell>
  )
}

function GuideRow({ r, onSave, onDel }: { r: any; onSave: (r: any) => void; onDel: (r: any) => void }) {
  const [x, setX] = useState(r)
  const dirty = JSON.stringify(x) !== JSON.stringify(r)
  const c = 'w-full rounded border border-gray-200 px-2 py-1 text-sm'
  return (
    <tr className="border-t border-gray-100 align-top">
      <td className="px-3 py-1.5"><input className={c} value={x.label} onChange={(e) => setX({ ...x, label: e.target.value })} />{!r.id && <input className={`${c} mt-1`} value={x.group_name} onChange={(e) => setX({ ...x, group_name: e.target.value })} placeholder="Step name" />}</td>
      <td className="px-3 py-1.5"><input className={c} value={x.detail || ''} onChange={(e) => setX({ ...x, detail: e.target.value })} /></td>
      <td className="w-28 px-3 py-1.5"><input inputMode="numeric" className={`${c} text-right`} value={x.price_low} onChange={(e) => setX({ ...x, price_low: Number(e.target.value.replace(/[^\d.]/g, '')) })} /></td>
      <td className="w-28 px-3 py-1.5"><input inputMode="numeric" className={`${c} text-right`} value={x.price_high} onChange={(e) => setX({ ...x, price_high: Number(e.target.value.replace(/[^\d.]/g, '')) })} /></td>
      <td className="px-3 py-1.5"><textarea rows={1} className={`${c} text-xs text-gray-600`} value={x.basis || ''} onChange={(e) => setX({ ...x, basis: e.target.value })} /></td>
      <td className="px-3 py-1.5"><input type="checkbox" checked={x.active} onChange={(e) => setX({ ...x, active: e.target.checked })} /></td>
      <td className="whitespace-nowrap px-3 py-1.5 text-right">{dirty && <button type="button" onClick={() => onSave(x)} className="mr-2 rounded bg-red-700 px-2 py-1 text-xs font-bold text-white">Save</button>}{r.id ? <button type="button" onClick={() => onDel(r)} className="text-xs text-gray-400 hover:text-red-700">✕</button> : null}</td>
    </tr>
  )
}
