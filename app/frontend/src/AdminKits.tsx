import { useEffect, useState, type CSSProperties } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

// ── Types ───────────────────────────────────────────────────────────────────
type Component = {
  part_number: string
  product_id: number | null
  product_sku?: string | null
  product_name?: string | null
  quantity: number
  description?: string | null
}
type Resource = { title?: string | null; url: string; kind: string }
type Image = { url: string; is_primary: boolean }
type PriceTier = 'retail' | 'wholesale' | 'dealer' | 'municipality'
type Prices = Record<PriceTier, string>  // strings for inputs; '' = leave unset
type KitForm = {
  id?: number
  sku: string
  name: string
  trade: string
  description: string
  is_active: boolean
  product_id: number | null
  category_id: number | null
  vehicle_make: string
  vehicle_model: string
  wheelbase: string
  roof_height: string
  hand: string
  components: Component[]
  resources: Resource[]
  images: Image[]
  prices: Prices
  avail_retail: boolean
  avail_wholesale: boolean
  avail_dealer: boolean
  avail_municipality: boolean
  available_from: string  // 'YYYY-MM-DD' or '' (open-ended)
  available_until: string
  // read-only, populated when editing
  derived_on_hand?: number
  limiting_part?: string | null
  unlinked_components?: number
  stock_by_warehouse?: { warehouse_id: number; on_hand: number; available: number }[]
}
const PRICE_TIERS: { key: PriceTier; label: string; channelKey: AvailKey }[] = [
  { key: 'retail', label: 'Retail', channelKey: 'avail_retail' },
  { key: 'municipality', label: 'Municipality', channelKey: 'avail_municipality' },
  { key: 'dealer', label: 'Dealer', channelKey: 'avail_dealer' },
  { key: 'wholesale', label: 'Wholesale', channelKey: 'avail_wholesale' },
]
type AvailKey = 'avail_retail' | 'avail_wholesale' | 'avail_dealer' | 'avail_municipality'
type KitSummary = {
  id: number; sku: string; name: string; trade: string | null
  vehicle_make: string | null; vehicle_model: string | null
  wheelbase: string | null; component_count: number; is_active: boolean
  showing: boolean; hidden_reasons: string[]
}
type Cat = { id: number; name: string; full_path: string; depth: number; children?: Cat[] }

const RESOURCE_KINDS = ['installation', 'manual', 'datasheet', 'spec_sheet', 'parts_list', 'brochure', 'video', 'diagram', 'other']

const j = (u: string, init?: RequestInit) =>
  fetch(u, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init })

function emptyKit(): KitForm {
  return {
    sku: '', name: '', trade: '', description: '', is_active: true,
    product_id: null, category_id: null, vehicle_make: '', vehicle_model: '',
    wheelbase: '', roof_height: '', hand: '', components: [], resources: [], images: [],
    prices: { retail: '', wholesale: '', dealer: '', municipality: '' },
    avail_retail: true, avail_wholesale: true, avail_dealer: true, avail_municipality: true,
    available_from: '', available_until: '',
  }
}
const priceStr = (v: number | null | undefined) => (v === null || v === undefined ? '' : String(v))

// ── Kits list ────────────────────────────────────────────────────────────────
export function AdminKitsListPage() {
  const [kits, setKits] = useState<KitSummary[]>([])
  const [q, setQ] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'showing' | 'hidden'>('all')

  const load = (query = '') => {
    setLoading(true)
    j(`/api/admin/kits?q=${encodeURIComponent(query)}`)
      .then((r) => { if (r.status === 401 || r.status === 403) throw new Error('Admin access required.'); return r.json() })
      .then((d: KitSummary[]) => { setKits(d); setErr(null) })
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const hiddenCount = kits.filter((k) => !k.showing).length
  const shown = kits.filter((k) => filter === 'all' || (filter === 'hidden' ? !k.showing : k.showing))

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Kit packages</h1>
        <Link to="/admin/kits/new" className="bg-red-700 text-white text-sm px-4 py-2 rounded hover:bg-red-800">+ Create a kit package</Link>
      </div>
      {!loading && hiddenCount > 0 && (
        <button onClick={() => setFilter(filter === 'hidden' ? 'all' : 'hidden')}
          className={`mb-4 w-full text-left rounded p-3 text-sm border ${filter === 'hidden' ? 'bg-amber-100 border-amber-300' : 'bg-amber-50 border-amber-200'} text-amber-900 hover:bg-amber-100`}>
          ⚠ <span className="font-semibold">{hiddenCount} of {kits.length} kit{kits.length === 1 ? '' : 's'} {hiddenCount === 1 ? 'is' : 'are'} not showing on the website.</span>{' '}
          {filter === 'hidden' ? 'Showing only hidden — click to show all.' : 'Click to see just those.'}
        </button>
      )}
      <div className="mb-4 flex items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load(q)}
          placeholder="Search by SKU, name, or trade…" className="border rounded px-3 py-2 flex-1 max-w-md text-sm" />
        <select value={filter} onChange={(e) => setFilter(e.target.value as any)} className="border rounded px-2 py-2 text-sm">
          <option value="all">All kits</option>
          <option value="showing">Showing only</option>
          <option value="hidden">Hidden only</option>
        </select>
      </div>
      {err && <div className="bg-amber-50 border border-amber-200 text-amber-900 text-sm rounded p-3 mb-4">{err}</div>}
      {loading ? <div className="text-gray-500 text-sm">Loading…</div> : (
        <table className="w-full text-sm border-t">
          <thead><tr className="text-left text-gray-500 border-b">
            <th className="py-2">SKU</th><th>Name</th><th>Status</th><th>Vehicle</th><th className="text-center">Parts</th><th></th>
          </tr></thead>
          <tbody>
            {shown.map((k) => (
              <tr key={k.id} className="border-b hover:bg-gray-50 align-top">
                <td className="py-2 font-mono text-xs">{k.sku}</td>
                <td>{k.name}</td>
                <td>
                  {k.showing
                    ? <span className="inline-block text-xs font-semibold text-green-700 bg-green-50 border border-green-200 rounded px-1.5 py-0.5">● Showing</span>
                    : <div>
                        <span className="inline-block text-xs font-semibold text-amber-800 bg-amber-50 border border-amber-300 rounded px-1.5 py-0.5">✕ Hidden</span>
                        <div className="text-xs text-gray-500 mt-1">{k.hidden_reasons.join(' · ')}</div>
                      </div>}
                </td>
                <td className="text-gray-600">{[k.vehicle_make, k.vehicle_model, k.wheelbase].filter(Boolean).join(' ') || '—'}</td>
                <td className="text-center">{k.component_count}</td>
                <td className="text-right"><Link to={`/admin/kits/${k.id}`} className="text-red-700 hover:underline">Edit →</Link></td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={6} className="py-6 text-center text-gray-400">{kits.length ? 'No kits match this filter.' : 'No kits yet. Create one to get started.'}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Category placement picker (Category → Subcategory) ───────────────────────
function CategoryPicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const [flat, setFlat] = useState<{ id: number; full_path: string }[]>([])
  useEffect(() => {
    j('/api/catalog/categories/tree').then((r) => r.json()).then((d) => {
      const root: Cat[] = Array.isArray(d) ? d : (d.categories || d.children || [])
      const out: { id: number; full_path: string }[] = []
      const walk = (ns: Cat[]) => ns.forEach((n) => { out.push({ id: n.id, full_path: n.full_path }); if (n.children) walk(n.children) })
      walk(root)
      out.sort((a, b) => a.full_path.localeCompare(b.full_path))
      setFlat(out)
    }).catch(() => {})
  }, [])
  return (
    <select value={value ?? ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      className="border rounded px-3 py-2 text-sm w-full">
      <option value="">— choose website category / subcategory —</option>
      {flat.map((c) => <option key={c.id} value={c.id}>{c.full_path}</option>)}
    </select>
  )
}

const fieldCls = 'border rounded px-3 py-2 text-sm w-full'
const labelCls = 'block text-xs font-medium text-gray-600 mb-1'

// ── Wizard ───────────────────────────────────────────────────────────────────
const STEPS = ['Details & placement', 'Components', 'Vehicle fitment', 'Pricing & availability', 'Resources & images', 'Review'] as const

export function AdminKitWizardPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [step, setStep] = useState(0)
  const [form, setForm] = useState<KitForm>(emptyKit())
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const editing = !!id

  useEffect(() => {
    if (!id) return
    j(`/api/admin/kits/${id}`).then((r) => { if (!r.ok) throw new Error('Could not load kit'); return r.json() })
      .then((k) => setForm({
        id: k.id, sku: k.sku, name: k.name, trade: k.trade || '', description: k.description || '',
        is_active: k.is_active, product_id: k.product_id, category_id: k.category_id,
        vehicle_make: k.vehicle_make || '', vehicle_model: k.vehicle_model || '',
        wheelbase: k.wheelbase || '', roof_height: k.roof_height || '', hand: k.hand || '',
        components: k.components || [], resources: k.resources || [], images: k.images || [],
        prices: {
          retail: priceStr(k.prices?.retail), wholesale: priceStr(k.prices?.wholesale),
          dealer: priceStr(k.prices?.dealer), municipality: priceStr(k.prices?.municipality),
        },
        avail_retail: k.avail_retail ?? true, avail_wholesale: k.avail_wholesale ?? true,
        avail_dealer: k.avail_dealer ?? true, avail_municipality: k.avail_municipality ?? true,
        available_from: k.available_from || '', available_until: k.available_until || '',
        derived_on_hand: k.derived_on_hand, limiting_part: k.limiting_part,
        unlinked_components: k.unlinked_components, stock_by_warehouse: k.stock_by_warehouse,
      }))
      .catch((e) => setErr(e.message))
  }, [id])

  const set = <K extends keyof KitForm>(k: K, v: KitForm[K]) => setForm((f) => ({ ...f, [k]: v }))

  const save = async () => {
    setSaving(true); setErr(null)
    try {
      const numOrNull = (s: string) => { const t = (s ?? '').trim(); return t === '' ? null : Number(t) }
      const payload = {
        ...form,
        prices: {
          retail: numOrNull(form.prices.retail), wholesale: numOrNull(form.prices.wholesale),
          dealer: numOrNull(form.prices.dealer), municipality: numOrNull(form.prices.municipality),
        },
        available_from: form.available_from || null,
        available_until: form.available_until || null,
      }
      const r = await j(editing ? `/api/admin/kits/${id}` : '/api/admin/kits',
        { method: editing ? 'PUT' : 'POST', body: JSON.stringify(payload) })
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || `Save failed (${r.status})`) }
      nav('/admin/kits')
    } catch (e: any) { setErr(e.message) } finally { setSaving(false) }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-xl font-semibold">{editing ? 'Edit kit package' : 'Create a kit package'}</h1>
        <Link to="/admin/kits" className="text-sm text-gray-500 hover:underline">← All kits</Link>
      </div>
      {/* stepper */}
      <div className="flex flex-wrap items-center gap-2 mb-5 text-sm">
        {STEPS.map((s, i) => (
          <button key={s} onClick={() => setStep(i)}
            className={`px-3 py-1 rounded ${i === step ? 'bg-red-700 text-white' : i < step ? 'bg-gray-100 text-gray-700' : 'text-gray-400'}`}>
            {i + 1} · {s}
          </button>
        ))}
      </div>
      {err && <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded p-3 mb-4">{err}</div>}

      <div className="border rounded-lg p-5 bg-white">
        {step === 0 && <StepDetails form={form} set={set} />}
        {step === 1 && <StepComponents form={form} set={set} />}
        {step === 2 && <StepFitment form={form} set={set} />}
        {step === 3 && <StepPricing form={form} set={set} editing={editing} />}
        {step === 4 && <StepResources form={form} set={set} />}
        {step === 5 && <StepReview form={form} />}
      </div>

      <div className="flex justify-between mt-5">
        <button disabled={step === 0} onClick={() => setStep((s) => s - 1)}
          className="border rounded px-4 py-2 text-sm disabled:opacity-40">Back</button>
        {step < STEPS.length - 1
          ? <button onClick={() => setStep((s) => s + 1)} className="border rounded px-4 py-2 text-sm">Next →</button>
          : <button onClick={save} disabled={saving || !form.sku || !form.name}
              className="bg-red-700 text-white rounded px-5 py-2 text-sm disabled:opacity-50">
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create kit'}</button>}
      </div>
    </div>
  )
}

type StepProps = { form: KitForm; set: <K extends keyof KitForm>(k: K, v: KitForm[K]) => void }

function StepDetails({ form, set }: StepProps) {
  const resolveProduct = (sku: string) => {
    if (!sku.trim()) return
    j(`/api/admin/kits/resolve-part/${encodeURIComponent(sku.trim())}`).then((r) => r.json())
      .then((d) => { if (d.found) { set('product_id', d.product_id); if (!form.name) set('name', d.name) } })
      .catch(() => {})
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div><label className={labelCls}>Package SKU</label>
          <input className={fieldCls} value={form.sku} placeholder="HWZD-600-8214L"
            onChange={(e) => set('sku', e.target.value)} onBlur={(e) => resolveProduct(e.target.value)} />
          <p className="text-xs text-gray-400 mt-1">{form.product_id ? `✓ linked to product #${form.product_id}` : 'links to the sellable package product'}</p>
        </div>
        <div><label className={labelCls}>Trade</label>
          <input className={fieldCls} value={form.trade} placeholder="Electrical Contractor" onChange={(e) => set('trade', e.target.value)} /></div>
      </div>
      <div><label className={labelCls}>Name</label>
        <input className={fieldCls} value={form.name} placeholder="Electrical Contractor Van Package, Mid-Roof, Ford Transit 148" onChange={(e) => set('name', e.target.value)} /></div>
      <div><label className={labelCls}>Description</label>
        <textarea className={fieldCls} rows={3} value={form.description} onChange={(e) => set('description', e.target.value)} /></div>
      <div><label className={labelCls}>Website placement — Category → Subcategory</label>
        <CategoryPicker value={form.category_id} onChange={(v) => set('category_id', v)} /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Active (visible on the site)</label>
    </div>
  )
}

type PickCard = { id: number; sku: string; name: string; brand: string | null; in_stock: boolean; stock_total: number; image_url: string | null; category_top: string | null }
type Facet = { value: string; count: number }
type AttrValue = { value: string; uom?: string | null; count: number }
type AttrFacet = { key: string; values: AttrValue[] }
const clamp2: CSSProperties = { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }

// Full "Add parts" picker — reuses the storefront catalog search (/browse) for
// rich cards (image/brand/stock) + brand/category/in-stock filters + an
// optional "fits this vehicle" YMM filter (resolve -> base_vehicle_id).
function PartsPickerModal({ kitMake, kitModel, existingIds, onAdd, onClose }: {
  kitMake: string; kitModel: string; existingIds: Set<number>;
  onAdd: (cards: PickCard[]) => void; onClose: () => void;
}) {
  const PER = 24
  const [q, setQ] = useState(''); const [brand, setBrand] = useState('')
  const [inStock, setInStock] = useState(false); const [page, setPage] = useState(1)
  const [hits, setHits] = useState<PickCard[]>([]); const [found, setFound] = useState(0)
  const [brandFacets, setBrandFacets] = useState<Facet[]>([])
  // PIES attribute facets for the selected category (SERIES, POSITION, …) +
  // the chosen "Key|Value" pairs (same key = OR, different keys = AND).
  const [attrFacets, setAttrFacets] = useState<AttrFacet[]>([])
  const [selAttrs, setSelAttrs] = useState<Set<string>>(new Set())
  // Dynamic N-level category drill-down from the full tree (not facets, so every
  // level is always available). One dropdown per level — a new one appears
  // whenever the selected node has children — so you can drill as deep as the
  // tree goes (e.g. Truck Accessories › Suspension › Leveling Kits). Filter
  // /browse by category_path = the deepest selected node (matches it + descendants).
  const [tree, setTree] = useState<Cat[]>([])
  const [catChain, setCatChain] = useState<string[]>([])  // selected full_path per level
  const catLevels: Cat[][] = []
  {
    let opts = tree
    for (let i = 0; opts && opts.length; i++) {
      catLevels.push(opts)
      const sel = catChain[i]
      if (!sel) break
      const node = opts.find((n) => n.full_path === sel)
      opts = (node && node.children) ? node.children : []
      if (!opts.length) break
    }
  }
  const catPath = catChain.filter(Boolean).slice(-1)[0] || ''
  const [loading, setLoading] = useState(false); const [sel, setSel] = useState<Map<number, PickCard>>(new Map())
  // fitment
  const [fitOn, setFitOn] = useState(false)
  const [years, setYears] = useState<number[]>([]); const [year, setYear] = useState<number | ''>('')
  const [makeList, setMakeList] = useState<{ slug: string; name: string }[]>([]); const [makeSlug, setMakeSlug] = useState('')
  const [modelList, setModelList] = useState<{ slug: string; name: string }[]>([]); const [modelSlug, setModelSlug] = useState('')
  const [bvId, setBvId] = useState<number | null>(null); const [fitLabel, setFitLabel] = useState('')

  useEffect(() => { j('/api/catalog/categories/tree').then((r) => r.json()).then((d) => setTree(Array.isArray(d) ? d : (d.categories || d.children || []))).catch(() => {}) }, [])
  useEffect(() => { j('/api/ymm/years').then((r) => r.json()).then((ys: number[]) => {
    setYears(ys || [])
    // Default to the latest non-future model year — the top of the list is
    // often a sparse future year (e.g. 2027) with little fitment data.
    if (ys?.length) { const cy = new Date().getFullYear(); setYear(ys.find((y) => y <= cy) ?? ys[0]) }
  }).catch(() => {}) }, [])
  useEffect(() => {
    if (!year) return
    j(`/api/ymm/makes?year=${year}`).then((r) => r.json()).then((ms) => {
      setMakeList(ms || [])
      if (!makeSlug && kitMake) { const m = (ms || []).find((x: any) => x.name.toLowerCase() === kitMake.toLowerCase()); if (m) setMakeSlug(m.slug) }
    }).catch(() => {})
  }, [year]) // eslint-disable-line
  useEffect(() => {
    if (!year || !makeSlug) { setModelList([]); return }
    j(`/api/ymm/makes/${makeSlug}/models?year=${year}`).then((r) => r.json()).then((ms) => {
      setModelList(ms || [])
      if (!modelSlug && kitModel) { const km = kitModel.toLowerCase(); const m = (ms || []).find((x: any) => km.includes(x.name.toLowerCase())); if (m) setModelSlug(m.slug) }
    }).catch(() => {})
  }, [year, makeSlug]) // eslint-disable-line
  useEffect(() => {
    if (!(fitOn && year && makeSlug && modelSlug)) { setBvId(null); setFitLabel(''); return }
    j(`/api/ymm/resolve?year=${year}&make_slug=${makeSlug}&model_slug=${modelSlug}`).then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (d && d.base_vehicle_id) { setBvId(d.base_vehicle_id); setFitLabel(d.label || '') } else setBvId(null)
    }).catch(() => setBvId(null))
  }, [fitOn, year, makeSlug, modelSlug])

  // PIES attribute facets for the selected category (cleared when the category changes).
  useEffect(() => { setSelAttrs(new Set()) }, [catPath])
  useEffect(() => {
    if (!catPath) { setAttrFacets([]); return }
    let stale = false
    const p = new URLSearchParams(); p.set('category_path', catPath)
    if (fitOn && bvId) p.set('base_vehicle_id', String(bvId))
    j(`/api/catalog/category-attributes?${p.toString()}`).then((r) => r.json())
      .then((d) => { if (!stale) setAttrFacets(d.attributes || []) }).catch(() => { if (!stale) setAttrFacets([]) })
    return () => { stale = true }  // ignore a slower earlier fetch (drill-down race)
  }, [catPath, fitOn ? bvId : null]) // eslint-disable-line
  const attrsKey = [...selAttrs].sort().join(',')

  useEffect(() => { setPage(1) }, [q, brand, catPath, inStock, fitOn, bvId, attrsKey])
  const key = [q, brand, catPath, inStock, page, fitOn ? bvId : null, attrsKey].join('|')
  useEffect(() => {
    setLoading(true)
    let stale = false
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (brand) p.set('brand', brand)
    if (catPath) p.set('category_path', catPath)
    if (inStock) p.set('in_stock', 'true')
    if (fitOn && bvId) p.set('base_vehicle_id', String(bvId))
    for (const pair of selAttrs) p.append('attrs', pair)
    p.set('page', String(page)); p.set('per_page', String(PER))
    j(`/api/catalog/browse?${p.toString()}`).then((r) => r.json()).then((d) => {
      if (stale) return
      setHits(d.hits || []); setFound(d.found || 0)
      setBrandFacets(d.facets?.brand_name || [])
    }).catch(() => { if (!stale) { setHits([]); setFound(0) } }).finally(() => { if (!stale) setLoading(false) })
    return () => { stale = true }
  }, [key]) // eslint-disable-line

  const toggle = (c: PickCard) => setSel((prev) => { const n = new Map(prev); if (n.has(c.id)) n.delete(c.id); else n.set(c.id, c); return n })
  const pages = Math.max(1, Math.ceil(found / PER))
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-lg w-full max-w-5xl h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b">
          <h3 className="font-semibold">Add parts from the catalog</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-2xl leading-none">×</button>
        </div>
        <div className="px-5 py-3 border-b space-y-2">
          <div className="flex gap-2">
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search part #, name, or brand…" className="border rounded px-3 py-2 text-sm flex-1" />
            <label className="flex items-center gap-1 text-sm whitespace-nowrap"><input type="checkbox" checked={inStock} onChange={(e) => setInStock(e.target.checked)} /> In stock</label>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <select value={brand} onChange={(e) => setBrand(e.target.value)} className="border rounded px-2 py-1 text-sm max-w-[180px]">
              <option value="">All brands</option>{brandFacets.slice(0, 50).map((f) => <option key={f.value} value={f.value}>{f.value} ({f.count})</option>)}
            </select>
            {catLevels.map((opts, i) => {
              const parentName = i === 0 ? null : catLevels[i - 1].find((n) => n.full_path === catChain[i - 1])?.name
              return (
                <select key={i} value={catChain[i] || ''} className="border rounded px-2 py-1 text-sm max-w-[160px]"
                  onChange={(e) => { const v = e.target.value; setCatChain((prev) => (v ? [...prev.slice(0, i), v] : prev.slice(0, i))) }}>
                  <option value="">{i === 0 ? 'All categories' : `All ${parentName || 'subcategories'}`}</option>
                  {opts.map((o) => <option key={o.id} value={o.full_path}>{o.name}</option>)}
                </select>
              )
            })}
            <label className="flex items-center gap-1 text-sm ml-auto"><input type="checkbox" checked={fitOn} onChange={(e) => setFitOn(e.target.checked)} /> Fits a vehicle</label>
            {fitOn && (
              <div className="flex gap-1 items-center">
                <select value={year} onChange={(e) => setYear(Number(e.target.value) || '')} className="border rounded px-1 py-1 text-xs"><option value="">Year</option>{years.map((y) => <option key={y} value={y}>{y}</option>)}</select>
                <select value={makeSlug} onChange={(e) => { setMakeSlug(e.target.value); setModelSlug('') }} className="border rounded px-1 py-1 text-xs"><option value="">Make</option>{makeList.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}</select>
                <select value={modelSlug} onChange={(e) => setModelSlug(e.target.value)} className="border rounded px-1 py-1 text-xs"><option value="">Model</option>{modelList.map((m) => <option key={m.slug} value={m.slug}>{m.name}</option>)}</select>
              </div>
            )}
          </div>
          {fitOn && (bvId ? <div className="text-xs text-green-700">Showing parts that fit {fitLabel}</div> : <div className="text-xs text-amber-600">Pick year + make + model to filter by fitment.</div>)}
        </div>
        <div className="flex-1 flex overflow-hidden">
          {catPath && attrFacets.length > 0 && (
            <div className="w-44 shrink-0 border-r overflow-auto p-2 space-y-2 bg-gray-50">
              <div className="flex items-center justify-between px-1">
                <span className="text-[10px] uppercase tracking-wide text-gray-400">Refine</span>
                {selAttrs.size > 0 && <button onClick={() => setSelAttrs(new Set())} className="text-[10px] text-red-700 hover:underline">clear ({selAttrs.size})</button>}
              </div>
              {attrFacets.map((a) => (
                <div key={a.key} className="bg-white border rounded">
                  <div className="px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-gray-700 border-b bg-gray-50">{a.key}</div>
                  <div className="p-1 max-h-44 overflow-auto">
                    {a.values.map((v) => {
                      const pair = `${a.key}|${v.value}`; const on = selAttrs.has(pair)
                      return (
                        <button key={pair} onClick={() => setSelAttrs((prev) => { const n = new Set(prev); if (n.has(pair)) n.delete(pair); else n.add(pair); return n })}
                          className={`w-full flex items-center text-left text-[11px] px-1.5 py-0.5 rounded ${on ? 'bg-red-50 text-red-700 font-semibold' : 'hover:bg-gray-100 text-gray-700'}`}>
                          <span className={`inline-block w-2.5 h-2.5 mr-1.5 border rounded-sm shrink-0 ${on ? 'bg-red-700 border-red-700' : 'border-gray-300 bg-white'}`} />
                          <span className="flex-1 truncate">{v.uom ? `${v.value} ${v.uom}` : v.value}</span>
                          <span className="text-gray-400 ml-1">{v.count.toLocaleString()}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="flex-1 overflow-auto px-5 py-3">
          {loading ? <div className="text-gray-400 text-sm py-8 text-center">Loading…</div> : (
            <>
              <div className="text-xs text-gray-500 mb-2">{found.toLocaleString()} result{found === 1 ? '' : 's'}</div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {hits.map((c) => {
                  const picked = sel.has(c.id); const already = existingIds.has(c.id)
                  return (
                    <button key={c.id} onClick={() => toggle(c)} disabled={already}
                      className={`text-left border rounded p-2 flex gap-2 ${picked ? 'border-red-500 bg-red-50' : 'hover:border-gray-300'} ${already ? 'opacity-40 cursor-not-allowed' : ''}`}>
                      <div className="w-14 h-14 shrink-0 bg-gray-50 rounded overflow-hidden flex items-center justify-center">
                        {c.image_url ? <img src={c.image_url} alt="" className="object-contain w-full h-full" /> : <span className="text-[9px] text-gray-300">No image</span>}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[11px] text-red-700 truncate">{c.sku}</div>
                        <div className="text-xs text-gray-800" style={clamp2}>{c.name}</div>
                        <div className="text-[10px] text-gray-400 truncate">{c.brand}</div>
                        <div className="text-[10px]">{c.in_stock ? <span className="text-green-600">In stock ({c.stock_total})</span> : <span className="text-gray-400">Out of stock</span>}</div>
                      </div>
                      {already ? <span className="text-[9px] text-gray-400 self-center">added</span> : picked ? <span className="text-red-600 self-center">✓</span> : null}
                    </button>
                  )
                })}
              </div>
              {!hits.length && <div className="text-gray-400 text-sm py-8 text-center">No matching parts.</div>}
            </>
          )}
          </div>
        </div>
        <div className="flex items-center justify-between px-5 py-3 border-t">
          <div className="flex items-center gap-2 text-sm">
            <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="border rounded px-2 py-1 disabled:opacity-40">← Prev</button>
            <span className="text-gray-500">Page {page} / {pages}</span>
            <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="border rounded px-2 py-1 disabled:opacity-40">Next →</button>
          </div>
          <button onClick={() => { onAdd([...sel.values()]); onClose() }} disabled={!sel.size}
            className="bg-red-700 text-white rounded px-5 py-2 text-sm disabled:opacity-50">Add {sel.size || ''} part{sel.size === 1 ? '' : 's'}</button>
        </div>
      </div>
    </div>
  )
}

function StepComponents({ form, set }: StepProps) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<any[]>([])
  const [paste, setPaste] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return }
    const t = setTimeout(() => j(`/api/admin/kits/component-search?q=${encodeURIComponent(q)}`).then((r) => r.json()).then(setHits).catch(() => {}), 200)
    return () => clearTimeout(t)
  }, [q])
  const add = (c: Component) => set('components', [...form.components, c])
  const addHit = (h: any) => { add({ part_number: h.sku, product_id: h.id, product_sku: h.sku, product_name: h.name, quantity: 1 }); setQ(''); setHits([]) }
  const setQty = (i: number, n: number) => set('components', form.components.map((c, ix) => ix === i ? { ...c, quantity: Math.max(1, n) } : c))
  const remove = (i: number) => set('components', form.components.filter((_, ix) => ix !== i))
  const runPaste = async () => {
    const rows = paste.split('\n').map((l) => l.trim()).filter(Boolean)
    const out: Component[] = []
    for (const row of rows) {
      const m = row.split(/[\s,;\t]+/)
      const part = m[0]; const qty = parseInt(m[1] || '1', 10) || 1
      const d = await j(`/api/admin/kits/resolve-part/${encodeURIComponent(part)}`).then((r) => r.json()).catch(() => ({}))
      out.push({ part_number: part, product_id: d.product_id || null, product_sku: d.sku, product_name: d.name, quantity: qty })
    }
    set('components', [...form.components, ...out]); setPaste('')
  }
  const addCards = (cards: PickCard[]) => {
    const have = new Set(form.components.map((c) => c.product_id).filter(Boolean))
    const toAdd = cards.filter((c) => !have.has(c.id)).map((c) => ({
      part_number: c.sku, product_id: c.id, product_sku: c.sku, product_name: c.name, quantity: 1,
    }))
    if (toAdd.length) set('components', [...form.components, ...toAdd])
  }
  return (
    <div className="space-y-4">
      {pickerOpen && (
        <PartsPickerModal
          kitMake={form.vehicle_make} kitModel={form.vehicle_model}
          existingIds={new Set(form.components.map((c) => c.product_id).filter(Boolean) as number[])}
          onAdd={addCards} onClose={() => setPickerOpen(false)}
        />
      )}
      <button onClick={() => setPickerOpen(true)}
        className="w-full bg-red-700 hover:bg-red-800 text-white rounded px-4 py-2.5 text-sm font-semibold">
        🔍 Browse &amp; add parts from the catalog
      </button>
      <div className="relative">
        <label className={labelCls}>…or quick-add by SKU / name</label>
        <input className={fieldCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="search products…" />
        {hits.length > 0 && (
          <div className="absolute z-10 bg-white border rounded mt-1 w-full max-h-56 overflow-auto shadow">
            {hits.map((h) => (
              <button key={h.id} onClick={() => addHit(h)} className="block w-full text-left px-3 py-2 text-sm hover:bg-gray-50">
                <span className="font-mono text-xs text-red-700">{h.sku}</span> · {h.name} <span className="text-gray-400">({h.brand})</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer text-gray-600">Paste part numbers (one per line: <code>part qty</code>)</summary>
        <textarea className={`${fieldCls} mt-2 font-mono text-xs`} rows={4} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder={'9375-3-03 1\n9605-3-01 2'} />
        <button onClick={runPaste} className="border rounded px-3 py-1 text-xs mt-2">Resolve &amp; add</button>
      </details>
      <table className="w-full text-sm border-t">
        <thead><tr className="text-left text-gray-500 border-b"><th className="py-1">Part #</th><th className="w-16">Qty</th><th>Description / product</th><th></th></tr></thead>
        <tbody>
          {form.components.map((c, i) => (
            <tr key={i} className="border-b">
              <td className="py-1 font-mono text-xs">{c.part_number}{c.product_id ? <span className="ml-1 text-green-600" title="linked">●</span> : <span className="ml-1 text-gray-300" title="no product match">○</span>}</td>
              <td><input type="number" min={1} value={c.quantity} onChange={(e) => setQty(i, parseInt(e.target.value, 10))} className="border rounded px-2 py-1 w-14 text-sm" /></td>
              <td className="text-gray-600 text-xs">{c.product_name || c.description || '—'}</td>
              <td className="text-right"><button onClick={() => remove(i)} className="text-gray-400 hover:text-red-700">✕</button></td>
            </tr>
          ))}
          {!form.components.length && <tr><td colSpan={4} className="py-4 text-center text-gray-400">No components yet.</td></tr>}
        </tbody>
      </table>
      <p className="text-xs text-gray-400">● linked to a product (sub-part link will work) · ○ part not in catalog yet</p>
    </div>
  )
}

type FitComp = { product_id: number; sku: string | null; name: string | null; universal: boolean; makes: string[]; models: string[]; vehicle_count: number }
type FitResult = {
  components: FitComp[]
  common: { makes: string[]; models: string[]; vehicle_count: number; year_start: number | null; year_end: number | null; suggest_make: string | null; suggest_model: string | null }
  conflict: boolean; warnings: string[]; fitment_bearing: number; universal: number
}

function StepFitment({ form, set }: StepProps) {
  const [makes, setMakes] = useState<string[]>([])
  const [fit, setFit] = useState<FitResult | null>(null)
  const [fitLoading, setFitLoading] = useState(false)
  useEffect(() => { j('/api/ymm/makes').then((r) => r.json()).then((d) => {
    const arr = Array.isArray(d) ? d : (d.makes || [])
    setMakes(arr.map((m: any) => (typeof m === 'string' ? m : m.name)).filter(Boolean))
  }).catch(() => {}) }, [])

  const linkedPids = form.components.filter((c) => c.product_id).map((c) => c.product_id as number)
  const pidKey = linkedPids.slice().sort((a, b) => a - b).join(',')
  useEffect(() => {
    if (!linkedPids.length) { setFit(null); return }
    setFitLoading(true)
    const qs = linkedPids.map((p) => `product_ids=${p}`).join('&')
    j(`/api/admin/kits/fitment-check?${qs}`).then((r) => (r.ok ? r.json() : null))
      .then((d: FitResult | null) => setFit(d)).catch(() => setFit(null)).finally(() => setFitLoading(false))
  }, [pidKey])  // eslint-disable-line react-hooks/exhaustive-deps

  const applyCommon = () => {
    if (!fit) return
    if (fit.common.suggest_make) set('vehicle_make', fit.common.suggest_make)
    if (fit.common.suggest_model) set('vehicle_model', fit.common.suggest_model)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">Which vehicle(s) this kit fits — shown as the fitment guide on the package page.</p>

      {fitLoading && <div className="text-xs text-gray-400">Checking component fitments…</div>}
      {fit && fit.conflict && (
        <div className="bg-red-50 border border-red-300 text-red-800 text-sm rounded p-3">
          <div className="font-semibold mb-1">⚠ Fitment conflict</div>
          {fit.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
      {fit && !fit.conflict && fit.warnings.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded p-3">
          {fit.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
      {fit && fit.fitment_bearing > 0 && !fit.conflict && (
        <div className="bg-gray-50 border rounded p-3 text-sm">
          <div className="flex items-center justify-between">
            <div className="font-medium text-gray-700">Components share this fitment</div>
            {(fit.common.suggest_make || fit.common.suggest_model) && (
              <button onClick={applyCommon} className="text-xs text-red-700 hover:underline">Use for make / model →</button>
            )}
          </div>
          {fit.common.makes.length > 0 ? (
            <div className="mt-1 text-gray-700">
              <span className="font-semibold">{fit.common.makes.join(', ')}</span>
              {fit.common.models.length > 0 && <> — {fit.common.models.join(' · ')}</>}
              {fit.common.year_start && <span className="text-gray-500"> ({fit.common.year_start}–{fit.common.year_end})</span>}
            </div>
          ) : <div className="text-gray-500">No single shared vehicle across the fitment-bearing parts — verify these belong together.</div>}
          {fit.universal > 0 && <div className="text-xs text-gray-400 mt-1">{fit.universal} universal part(s) fit any vehicle.</div>}
        </div>
      )}
      {fit && fit.components.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-gray-600">Per-component fitment ({fit.components.length})</summary>
          <table className="w-full mt-2 text-xs">
            <tbody>
              {fit.components.map((c, i) => (
                <tr key={i} className="border-b align-top">
                  <td className="py-1 font-mono pr-3 whitespace-nowrap">{c.sku}</td>
                  <td className="text-gray-600">{c.universal ? <span className="text-gray-400">universal (fits any)</span> : c.makes.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div className="grid grid-cols-2 gap-4">
        <div><label className={labelCls}>Make</label>
          <input className={fieldCls} list="kit-makes" value={form.vehicle_make} onChange={(e) => set('vehicle_make', e.target.value)} placeholder="Ford" />
          <datalist id="kit-makes">{makes.map((m) => <option key={m} value={m} />)}</datalist></div>
        <div><label className={labelCls}>Model</label>
          <input className={fieldCls} value={form.vehicle_model} onChange={(e) => set('vehicle_model', e.target.value)} placeholder="Transit" /></div>
        <div><label className={labelCls}>Wheelbase</label>
          <input className={fieldCls} value={form.wheelbase} onChange={(e) => set('wheelbase', e.target.value)} placeholder="148" /></div>
        <div><label className={labelCls}>Roof height</label>
          <input className={fieldCls} value={form.roof_height} onChange={(e) => set('roof_height', e.target.value)} placeholder="Mid-Roof" /></div>
        <div><label className={labelCls}>Hand</label>
          <select className={fieldCls} value={form.hand} onChange={(e) => set('hand', e.target.value)}>
            <option value="">—</option><option value="L">Left (driver side)</option><option value="R">Right (curb side)</option><option value="LR">Both</option>
          </select></div>
      </div>
    </div>
  )
}

function StepPricing({ form, set, editing }: StepProps & { editing: boolean }) {
  const [sugg, setSugg] = useState<Record<PriceTier, number> | null>(null)
  const [missing, setMissing] = useState<{ count: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const fetchSuggest = () => {
    if (!form.id) return
    setLoading(true)
    j(`/api/admin/kits/${form.id}/suggest-pricing`).then((r) => r.json()).then((d) => {
      setSugg(d.suggested); setMissing({ count: d.missing_count })
    }).catch(() => {}).finally(() => setLoading(false))
  }
  const setPrice = (t: PriceTier, v: string) => set('prices', { ...form.prices, [t]: v })
  const applyAll = () => { if (sugg) set('prices', { retail: String(sugg.retail), wholesale: String(sugg.wholesale), dealer: String(sugg.dealer), municipality: String(sugg.municipality) }) }
  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-500">Set the kit price per customer channel and choose which channels may see/buy it. A visitor whose channel is unchecked won't see this kit anywhere on the site.</p>
      {editing ? (
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={fetchSuggest} disabled={loading} className="border rounded px-3 py-1.5 text-sm">{loading ? 'Calculating…' : 'Suggest from parts'}</button>
          {sugg && <button onClick={applyAll} className="text-sm text-red-700 hover:underline">Use all suggested →</button>}
          {missing && missing.count > 0 && <span className="text-xs text-amber-700">{missing.count} part(s) have no price on file — suggestion is partial.</span>}
        </div>
      ) : <p className="text-xs text-gray-400">Save the kit first, then reopen to auto-suggest pricing from the component list.</p>}
      <table className="w-full text-sm">
        <thead><tr className="text-left text-gray-500 border-b text-xs"><th className="py-1">Channel</th><th>Price</th><th>Suggested (parts at retail/tier)</th><th className="text-center">Available?</th></tr></thead>
        <tbody>
          {PRICE_TIERS.map(({ key, label, channelKey }) => (
            <tr key={key} className="border-b">
              <td className="py-2 font-medium">{label}</td>
              <td><div className="flex items-center gap-1"><span className="text-gray-400">$</span>
                <input type="number" step="0.01" min="0" className="border rounded px-2 py-1 w-32 text-sm" value={form.prices[key]} onChange={(e) => setPrice(key, e.target.value)} /></div></td>
              <td className="text-gray-500 text-xs">{sugg ? <>${sugg[key].toFixed(2)} <button onClick={() => setPrice(key, String(sugg[key]))} className="ml-1 text-red-700 hover:underline">use</button></> : '—'}</td>
              <td className="text-center"><input type="checkbox" checked={form[channelKey]} onChange={(e) => set(channelKey, e.target.checked)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="border-t pt-4">
        <div className="text-sm font-medium text-gray-700 mb-1">Availability window <span className="font-normal text-gray-400">(optional)</span></div>
        <p className="text-xs text-gray-400 mb-2">Leave blank for always-on. Outside the window the package is hidden everywhere (search + product page). Dates are inclusive.</p>
        <div className="grid grid-cols-2 gap-4 max-w-md">
          <div><label className={labelCls}>Available from</label>
            <input type="date" className={fieldCls} value={form.available_from} onChange={(e) => set('available_from', e.target.value)} /></div>
          <div><label className={labelCls}>Available until (end date)</label>
            <input type="date" className={fieldCls} value={form.available_until} onChange={(e) => set('available_until', e.target.value)} /></div>
        </div>
        {form.available_until && (() => {
          const today = new Date().toISOString().slice(0, 10)
          if (form.available_until < today) return <div className="text-xs text-red-600 mt-1">⚠ This end date is in the past — the package is currently hidden.</div>
          if (form.available_from && form.available_from > form.available_until) return <div className="text-xs text-red-600 mt-1">⚠ "From" date is after the "until" date.</div>
          return null
        })()}
      </div>

      {editing && (
        <div className="bg-gray-50 border rounded p-3 text-sm">
          <div className="font-medium text-gray-700 mb-1">Derived stock (from components)</div>
          <div>In stock: <span className="font-semibold">{form.derived_on_hand ?? '—'}</span>
            {form.limiting_part && form.derived_on_hand !== undefined && <span className="text-gray-500"> · limited by part {form.limiting_part}</span>}</div>
          {!!form.unlinked_components && <div className="text-amber-700 text-xs mt-1">{form.unlinked_components} component(s) aren't linked to a catalog product — they can't be stock-checked and are skipped.</div>}
          <div className="text-xs text-gray-400 mt-1">Recomputed on save. Per-warehouse: a kit is buildable at a branch only if every part is stocked there; if any required part is out everywhere, the kit shows 0.</div>
        </div>
      )}
    </div>
  )
}

function StepResources({ form, set }: StepProps) {
  const addRes = () => set('resources', [...form.resources, { title: '', url: '', kind: 'installation' }])
  const addImg = () => set('images', [...form.images, { url: '', is_primary: form.images.length === 0 }])
  const upRes = (i: number, k: keyof Resource, v: string) => set('resources', form.resources.map((r, ix) => ix === i ? { ...r, [k]: v } : r))
  const upImg = (i: number, url: string) => set('images', form.images.map((im, ix) => ix === i ? { ...im, url } : im))
  const primary = (i: number) => set('images', form.images.map((im, ix) => ({ ...im, is_primary: ix === i })))
  return (
    <div className="space-y-6">
      <div>
        <div className="flex items-center justify-between mb-2"><label className={labelCls}>Resources (install PDFs, manuals)</label>
          <button onClick={addRes} className="text-xs border rounded px-2 py-1">+ Add</button></div>
        {form.resources.map((r, i) => (
          <div key={i} className="flex gap-2 mb-2">
            <input className={`${fieldCls} flex-1`} placeholder="Title" value={r.title || ''} onChange={(e) => upRes(i, 'title', e.target.value)} />
            <input className={`${fieldCls} flex-[2]`} placeholder="https://…pdf" value={r.url} onChange={(e) => upRes(i, 'url', e.target.value)} />
            <select className={`${fieldCls} w-36`} value={r.kind} onChange={(e) => upRes(i, 'kind', e.target.value)}>{RESOURCE_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select>
            <button onClick={() => set('resources', form.resources.filter((_, ix) => ix !== i))} className="text-gray-400 hover:text-red-700 px-1">✕</button>
          </div>
        ))}
        {!form.resources.length && <p className="text-xs text-gray-400">No resources.</p>}
      </div>
      <div>
        <div className="flex items-center justify-between mb-2"><label className={labelCls}>Images (first = primary)</label>
          <button onClick={addImg} className="text-xs border rounded px-2 py-1">+ Add</button></div>
        {form.images.map((im, i) => (
          <div key={i} className="flex gap-2 items-center mb-2">
            <input className={`${fieldCls} flex-1`} placeholder="/static/product-images/… or https://…" value={im.url} onChange={(e) => upImg(i, e.target.value)} />
            <label className="text-xs flex items-center gap-1 whitespace-nowrap"><input type="radio" checked={im.is_primary} onChange={() => primary(i)} /> primary</label>
            <button onClick={() => set('images', form.images.filter((_, ix) => ix !== i))} className="text-gray-400 hover:text-red-700 px-1">✕</button>
          </div>
        ))}
        {!form.images.length && <p className="text-xs text-gray-400">No images.</p>}
        <p className="text-xs text-gray-400 mt-1">Saving replaces the package product's resources &amp; images with what's listed here. Leave empty to keep none.</p>
      </div>
    </div>
  )
}

function StepReview({ form }: { form: KitForm }) {
  const Row = ({ l, v }: { l: string; v: any }) => (
    <div className="flex gap-3 py-1 text-sm border-b last:border-0"><span className="text-gray-500 w-40 shrink-0">{l}</span><span>{v || '—'}</span></div>
  )
  return (
    <div>
      <Row l="SKU" v={form.sku} />
      <Row l="Name" v={form.name} />
      <Row l="Trade" v={form.trade} />
      <Row l="Placement" v={form.category_id ? `category #${form.category_id}` : 'not set'} />
      <Row l="Fitment" v={[form.vehicle_make, form.vehicle_model, form.wheelbase, form.roof_height, form.hand].filter(Boolean).join(' ')} />
      <Row l="Components" v={`${form.components.length} parts (${form.components.filter((c) => c.product_id).length} linked)`} />
      <Row l="Pricing" v={PRICE_TIERS.map(({ key, label }) => form.prices[key] ? `${label} $${form.prices[key]}` : null).filter(Boolean).join(' · ') || 'not set'} />
      <Row l="Available to" v={PRICE_TIERS.filter(({ channelKey }) => form[channelKey]).map(({ label }) => label).join(', ') || 'no channels (hidden)'} />
      <Row l="Availability window" v={(form.available_from || form.available_until) ? `${form.available_from || 'always'} → ${form.available_until || 'always'}` : 'always on'} />
      <Row l="Resources" v={`${form.resources.length}`} />
      <Row l="Images" v={`${form.images.length}`} />
      <Row l="Active" v={form.is_active ? 'yes' : 'no'} />
    </div>
  )
}
