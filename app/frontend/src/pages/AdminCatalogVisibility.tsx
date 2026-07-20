import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'

/**
 * Admin Catalog tree — Windows-explorer show/hide + shipping-mode + flat-rate.
 *
 * Pick a manufacturer line, then the tree opens: brand → category →
 * subcategory → part numbers. Toggle three overridable fields (visibility,
 * shipping mode, flat shipping) at any grouping level or per SKU. Inside a
 * subcategory, a "bulk select" tool narrows the parts by a CURATED filter (or
 * search) and applies a field to all matching parts at once — stamping explicit
 * PER-SKU overrides (no confusing overlapping filter rules). Backend:
 * /api/admin/catalog/*.
 */

const j = (u: string, init?: RequestInit) =>
  fetch(u, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init })

type FieldMeta = {
  key: string; label: string; type: 'enum' | 'money'
  values?: { value: string; label: string }[]; null_label?: string; help?: string
}
type OverrideRow = { id: number; field: string; value: string; pending: boolean }
type Scope = { brand_id?: number; category_id?: number; product_id?: number; uncategorized?: boolean; kits?: boolean }
type NodeType = 'brand' | 'category' | 'bucket' | 'part'
type TreeNode = {
  type: NodeType; label: string; count?: number
  brand_id?: number; category_id?: number; product_id?: number
  sku?: string; scope?: Scope; scope_key?: string
  overrides?: Record<string, OverrideRow>
  effective?: Record<string, unknown>
}
type FilterOpt = { key: string; value: string; count: number }

const CLEAR = '__clear__'
const box: CSSProperties = { fontVariantNumeric: 'tabular-nums' }
const ICON: Record<NodeType, string> = { brand: '🏭', category: '📁', bucket: '🗂️', part: '🔩' }

// ── Per-node field controls ─────────────────────────────────────────────────
function FieldControls({ fields, node, onApplied }: {
  fields: FieldMeta[]; node: TreeNode; onApplied: (field: string, ov: OverrideRow | null) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const scope = node.scope || {}
  const overrides = node.overrides || {}
  const apply = async (field: string, value: string | null) => {
    setBusy(field)
    try {
      if (value === null) {
        const ov = overrides[field]
        if (ov) await j(`/api/admin/catalog/override/${ov.id}`, { method: 'DELETE' })
        onApplied(field, null)
      } else {
        const r = await j('/api/admin/catalog/override', { method: 'POST', body: JSON.stringify({ field, value, ...scope }) }).then((x) => x.json())
        onApplied(field, r.override ?? null)
      }
    } finally { setBusy(null) }
  }
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {fields.map((f) => {
        const ov = overrides[f.key]
        const set = !!ov
        const ring = set ? (ov?.pending ? 'ring-1 ring-amber-400 bg-amber-50' : 'ring-1 ring-emerald-400 bg-emerald-50') : 'bg-white'
        if (f.type === 'enum') {
          return (
            <label key={f.key} className="flex items-center gap-1 text-[11px] text-gray-500">
              <span className="hidden lg:inline">{f.label}</span>
              <select disabled={busy === f.key} value={ov?.value ?? ''} onChange={(e) => apply(f.key, e.target.value === '' ? null : e.target.value)}
                className={`rounded border border-gray-300 px-1 py-0.5 text-[11px] text-gray-800 ${ring}`}
                title={ov?.pending ? 'Pending until re-index' : (set ? 'Override set here' : 'Inherited')}>
                <option value="">Inherit</option>
                {f.values!.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
              </select>
            </label>
          )
        }
        return (
          <label key={f.key} className="flex items-center gap-1 text-[11px] text-gray-500">
            <span className="hidden lg:inline">{f.label}</span>
            <input disabled={busy === f.key} defaultValue={ov?.value ?? ''} placeholder={f.null_label || 'inherit'}
              onBlur={(e) => { const v = e.target.value.trim(); const cur = ov?.value ?? ''; if (v === cur) return; apply(f.key, v === '' ? null : v) }}
              className={`w-24 rounded border border-gray-300 px-1 py-0.5 text-[11px] text-gray-800 ${ring}`} title={f.help || ''} />
          </label>
        )
      })}
    </div>
  )
}

// ── A single part row (leaf) ────────────────────────────────────────────────
function PartRow({ node, depth, fields, onMutated }: { node: TreeNode; depth: number; fields: FieldMeta[]; onMutated: () => void }) {
  const [self, setSelf] = useState(node)
  useEffect(() => { setSelf(node) }, [node])
  const onApplied = (field: string, ov: OverrideRow | null) => {
    setSelf((s) => { const m = { ...(s.overrides || {}) }; if (ov) m[field] = ov; else delete m[field]; return { ...s, overrides: m } })
    onMutated()
  }
  return (
    <div className="flex items-center justify-between gap-3 border-b border-gray-100 py-1.5 hover:bg-gray-50" style={{ paddingLeft: `${depth * 16 + 22}px` }}>
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span>🔩</span>
        <span className="truncate text-sm text-gray-800">{node.label}{node.sku && <span className="ml-2 text-[11px] text-gray-400">{node.sku}</span>}</span>
      </div>
      <FieldControls fields={fields} node={self} onApplied={onApplied} />
    </div>
  )
}

// ── Parts panel: bulk-select toolbar + paginated parts for a scope ──────────
function PartsPanel({ scope, depth, fields, onMutated }: { scope: Scope; depth: number; fields: FieldMeta[]; onMutated: () => void }) {
  const [filters, setFilters] = useState<FilterOpt[]>([])
  const [sel, setSel] = useState('')            // "key|||value" or ''
  const [q, setQ] = useState('')
  const [parts, setParts] = useState<TreeNode[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const [bulkField, setBulkField] = useState<string>(fields[0]?.key || 'hidden')
  const [bulkValue, setBulkValue] = useState<string>(CLEAR)
  const [bulkFlat, setBulkFlat] = useState('')
  const [applying, setApplying] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const attrKey = sel ? sel.split('|||')[0] : undefined
  const attrValue = sel ? sel.split('|||')[1] : undefined
  const inSubcat = scope.category_id != null

  const params = useCallback((extra: Record<string, string> = {}) => {
    const p = new URLSearchParams()
    if (scope.brand_id != null) p.set('brand_id', String(scope.brand_id))
    if (scope.category_id != null) p.set('category_id', String(scope.category_id))
    if (scope.uncategorized) p.set('uncategorized', 'true')
    if (scope.kits) p.set('kits', 'true')
    if (attrKey) { p.set('attr_key', attrKey); p.set('attr_value', attrValue || '') }
    if (q.trim()) p.set('q', q.trim())
    for (const [k, v] of Object.entries(extra)) p.set(k, v)
    return p
  }, [scope, attrKey, attrValue, q])

  const loadParts = useCallback(async (pg: number, reset: boolean) => {
    setLoading(true)
    try {
      const p = params({ page: String(pg), page_size: '50' })
      const r = await j(`/api/admin/catalog/parts?${p}`).then((x) => x.json())
      setTotal(r.total || 0); setPage(pg)
      setParts((prev) => (reset ? r.parts : [...prev, ...r.parts]))
    } finally { setLoading(false) }
  }, [params])

  useEffect(() => { loadParts(1, true) }, [loadParts])
  useEffect(() => {
    // Curated filters only inside a subcategory (that's where they're unambiguous).
    if (!inSubcat) { setFilters([]); return }
    const p = new URLSearchParams({ brand_id: String(scope.brand_id), category_id: String(scope.category_id) })
    j(`/api/admin/catalog/filters?${p}`).then((x) => x.json())
      .then((d) => setFilters((d.groups || []).flatMap((g: { key: string; values: { attr_value: string; count: number }[] }) =>
        g.values.map((v) => ({ key: g.key, value: v.attr_value, count: v.count })))))
      .catch(() => setFilters([]))
  }, [inSubcat, scope.brand_id, scope.category_id])

  const bulkFieldMeta = fields.find((f) => f.key === bulkField)
  const doBulk = async () => {
    let payload: Record<string, unknown> = { field: bulkField, ...scopeToBody(scope), attr_key: attrKey, attr_value: attrValue, q: q.trim() || undefined }
    if (bulkValue === CLEAR) payload = { ...payload, clear: true }
    else if (bulkField === 'flat_ship_amount') payload = { ...payload, value: bulkValue === '__flat__' ? bulkFlat : bulkValue }
    else payload = { ...payload, value: bulkValue }
    const label = bulkValue === CLEAR ? 'clear overrides on' : `set ${bulkFieldMeta?.label} on`
    if (total > 50 && !window.confirm(`Bulk ${label} ${total} parts?`)) return
    setApplying(true); setMsg(null)
    try {
      const r = await j('/api/admin/catalog/bulk-apply', { method: 'POST', body: JSON.stringify(payload) })
      const d = await r.json()
      if (!r.ok) { setMsg(d.detail || 'Bulk apply failed.'); return }
      setMsg(`${d.cleared ? 'Cleared' : 'Applied to'} ${d.applied} part${d.applied === 1 ? '' : 's'}.`)
      await loadParts(1, true)
      onMutated()
    } finally { setApplying(false) }
  }

  return (
    <div style={{ paddingLeft: `${depth * 16 + 22}px` }} className="py-1">
      {/* Bulk toolbar */}
      <div className="mb-1 flex flex-wrap items-center gap-2 rounded-lg bg-gray-50 px-2 py-1.5 text-xs">
        {inSubcat && (
          <select value={sel} onChange={(e) => setSel(e.target.value)} className="rounded border border-gray-300 px-1 py-0.5" title="Narrow by a curated filter">
            <option value="">All parts{filters.length ? '' : ' (no filters)'}</option>
            {filters.map((f) => <option key={`${f.key}|||${f.value}`} value={`${f.key}|||${f.value}`}>{f.key}: {f.value} ({f.count})</option>)}
          </select>
        )}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="search sku/name" className="w-36 rounded border border-gray-300 px-1 py-0.5" />
        <span className="text-gray-400">·</span>
        <span className="text-gray-500">Bulk set</span>
        <select value={bulkField} onChange={(e) => { setBulkField(e.target.value); setBulkValue(CLEAR) }} className="rounded border border-gray-300 px-1 py-0.5">
          {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        {bulkFieldMeta?.type === 'enum' ? (
          <select value={bulkValue} onChange={(e) => setBulkValue(e.target.value)} className="rounded border border-gray-300 px-1 py-0.5">
            <option value={CLEAR}>Inherit (clear)</option>
            {bulkFieldMeta.values!.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
          </select>
        ) : (
          <>
            <select value={bulkValue} onChange={(e) => setBulkValue(e.target.value)} className="rounded border border-gray-300 px-1 py-0.5">
              <option value={CLEAR}>Inherit (clear)</option>
              <option value="">Weight-based</option>
              <option value="0">Free ($0)</option>
              <option value="__flat__">Flat $…</option>
            </select>
            {bulkValue === '__flat__' && <input value={bulkFlat} onChange={(e) => setBulkFlat(e.target.value)} placeholder="19.00" className="w-16 rounded border border-gray-300 px-1 py-0.5" />}
          </>
        )}
        <button onClick={doBulk} disabled={applying || total === 0} className="rounded bg-gray-800 px-2 py-0.5 font-medium text-white hover:bg-gray-900 disabled:opacity-50">
          {applying ? 'Applying…' : `Apply to ${total.toLocaleString()}`}
        </button>
        {msg && <span className="text-emerald-700">{msg}</span>}
      </div>
      {/* Parts */}
      {loading && parts.length === 0 && <div className="py-1 text-xs text-gray-400">Loading parts…</div>}
      {parts.map((p) => <PartRow key={`part-${p.product_id}`} node={p} depth={depth} fields={fields} onMutated={onMutated} />)}
      {total > parts.length && (
        <button className="py-1.5 text-xs text-red-600 hover:underline" onClick={() => loadParts(page + 1, false)}>
          Load more ({parts.length.toLocaleString()} of {total.toLocaleString()})
        </button>
      )}
    </div>
  )
}

function scopeToBody(s: Scope): Record<string, unknown> {
  return { brand_id: s.brand_id, category_id: s.category_id, uncategorized: s.uncategorized || false, kits: s.kits || false }
}

// ── A grouping node (brand / category / bucket) ─────────────────────────────
function GroupRow({ node, depth, fields, onMutated, initialOpen = false }: {
  node: TreeNode; depth: number; fields: FieldMeta[]; onMutated: () => void; initialOpen?: boolean
}) {
  const [open, setOpen] = useState(initialOpen)
  const [kids, setKids] = useState<TreeNode[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [self, setSelf] = useState(node)

  const loadChildren = useCallback(async () => {
    setLoading(true)
    try {
      if (node.type === 'brand' || node.type === 'category') {
        const p = new URLSearchParams(); p.set('brand_id', String(node.brand_id))
        if (node.category_id != null) p.set('category_id', String(node.category_id))
        const r = await j(`/api/admin/catalog/children?${p}`).then((x) => x.json())
        setKids(r.nodes || [])
      } else { setKids([]) }
    } finally { setLoading(false) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node])

  useEffect(() => { if (initialOpen && kids === null) loadChildren() }, [initialOpen, kids, loadChildren])

  const toggle = async () => { const next = !open; setOpen(next); if (next && kids === null) await loadChildren() }
  const onApplied = (field: string, ov: OverrideRow | null) => {
    setSelf((s) => { const m = { ...(s.overrides || {}) }; if (ov) m[field] = ov; else delete m[field]; return { ...s, overrides: m } })
    onMutated()
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 py-1.5 hover:bg-gray-50" style={{ paddingLeft: `${depth * 16 + 6}px` }}>
        <button className="flex min-w-0 flex-1 items-center gap-2 text-left" onClick={toggle}>
          <span className="w-3 shrink-0 text-gray-400">{open ? '▾' : '▸'}</span>
          <span className="shrink-0">{ICON[node.type]}</span>
          <span className="truncate text-sm font-medium text-gray-800">{node.label}</span>
          {node.count != null && <span className="shrink-0 rounded-full bg-gray-100 px-1.5 text-[11px] text-gray-500" style={box}>{node.count.toLocaleString()}</span>}
        </button>
        <FieldControls fields={fields} node={self} onApplied={onApplied} />
      </div>
      {open && (
        <div>
          {loading && <div className="py-2 text-xs text-gray-400" style={{ paddingLeft: `${(depth + 1) * 16 + 6}px` }}>Loading…</div>}
          {(kids || []).map((k, i) => (
            <GroupRow key={`${k.type}-${k.category_id ?? k.brand_id ?? k.label}-${i}`} node={k} depth={depth + 1} fields={fields} onMutated={onMutated} />
          ))}
          {/* Parts live under categories + the Uncategorized bucket (not the
              brand root — those would just duplicate the category listings). */}
          {(node.type === 'category' || node.type === 'bucket') && (
            <PartsPanel scope={node.scope || {}} depth={depth + 1} fields={fields} onMutated={onMutated} />
          )}
        </div>
      )}
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────
export function AdminCatalogVisibilityPage() {
  const [fields, setFields] = useState<FieldMeta[]>([])
  const [brands, setBrands] = useState<TreeNode[]>([])
  const [kitCount, setKitCount] = useState(0)
  const [selectedId, setSelectedId] = useState<number | 'kits' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(0)
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<string | null>(null)
  const windowMode = typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('window')

  const loadPending = useCallback(async () => {
    const r = await j('/api/admin/catalog/pending').then((x) => x.json()).catch(() => null)
    if (r) setPending(r.pending || 0)
  }, [])

  useEffect(() => {
    j('/api/admin/catalog/fields').then((x) => x.json()).then((d) => setFields(d.fields || [])).catch(() => {})
    ;(async () => {
      setLoading(true); setErr(null)
      try {
        const r = await j('/api/admin/catalog/roots')
        if (r.status === 401 || r.status === 403) throw new Error('Admin access required.')
        const data = await r.json(); setBrands(data.nodes || []); setKitCount(data.kit_count || 0)
      } catch (e) { setErr(e instanceof Error ? e.message : 'Failed to load manufacturer lines.') }
      finally { setLoading(false) }
    })()
    loadPending()
  }, [loadPending])

  const selected = useMemo(() => (typeof selectedId === 'number' ? brands.find((b) => b.brand_id === selectedId) : null) || null, [brands, selectedId])
  const applyNow = async () => {
    setApplying(true); setApplyMsg(null)
    try {
      const r = await j('/api/admin/catalog/apply-now', { method: 'POST' }).then((x) => x.json())
      setApplyMsg(r.status === 'started' ? 'Applying — search will refresh shortly.' : `Apply: ${r.status}`)
      setTimeout(loadPending, 1500)
    } finally { setApplying(false) }
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] px-6 py-5">
      <div className="mb-1 flex items-center justify-between gap-2 text-sm text-gray-500">
        <div className="flex items-center gap-2"><Link to="/account" className="hover:underline">Admin</Link><span>/</span><span>Catalog visibility</span></div>
        {!windowMode && <button onClick={() => window.open('/admin/catalog-visibility?window=1', '_blank', 'noopener')} className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:border-gray-400 hover:text-gray-800">⧉ Open in new window</button>}
      </div>
      <h1 className="mb-1 text-2xl font-bold text-gray-900">Catalog visibility & shipping</h1>
      <p className="mb-4 max-w-3xl text-sm text-gray-600">
        Pick a manufacturer line, then turn it on or off — completely or partially — down to category,
        subcategory, or part. Inside a subcategory you can narrow by a filter and apply to all matching
        parts at once. Changes save instantly and go live at tonight's re-index, or click <b>Apply now</b>.
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <label className="text-sm text-gray-600">Manufacturer line</label>
        <select value={selectedId ?? ''} onChange={(e) => setSelectedId(e.target.value === '' ? null : e.target.value === 'kits' ? 'kits' : Number(e.target.value))} className="min-w-[16rem] rounded-lg border border-gray-300 px-3 py-1.5 text-sm">
          <option value="">— choose a line —</option>
          {kitCount > 0 && <option value="kits">📦 Kit Packages ({kitCount.toLocaleString()})</option>}
          {brands.map((b) => <option key={b.brand_id} value={b.brand_id}>{b.label} ({b.count?.toLocaleString()})</option>)}
        </select>
        <div className="ml-auto flex items-center gap-3">
          {pending > 0 && <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800">{pending} change{pending === 1 ? '' : 's'} pending</span>}
          <button onClick={applyNow} disabled={applying} className="rounded-lg bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">{applying ? 'Applying…' : 'Apply now'}</button>
        </div>
      </div>
      {applyMsg && <div className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{applyMsg}</div>}

      <div className="mb-3 flex flex-wrap gap-4 text-[11px] text-gray-500">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400 align-middle"></span>override set here</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400 align-middle"></span>pending until re-index</span>
        <span>Blank field = inherits from the level above.</span>
      </div>

      {err && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      {loading ? (
        <div className="py-8 text-center text-sm text-gray-400">Loading manufacturer lines…</div>
      ) : selectedId === 'kits' ? (
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center gap-2 border-b border-gray-100 px-2 py-2 text-sm font-medium text-gray-800">
            <span>📦</span> Kit Packages
            <span className="rounded-full bg-gray-100 px-1.5 text-[11px] text-gray-500" style={box}>{kitCount.toLocaleString()}</span>
          </div>
          <PartsPanel scope={{ kits: true }} depth={0} fields={fields} onMutated={loadPending} />
        </div>
      ) : !selected ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 py-10 text-center text-sm text-gray-500">Choose a manufacturer line above to open its tree.</div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white">
          <GroupRow key={`brand-${selected.brand_id}`} node={selected} depth={0} fields={fields} onMutated={loadPending} initialOpen />
        </div>
      )}
    </div>
  )
}

export default AdminCatalogVisibilityPage
