import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'

/**
 * Admin Catalog tree — Windows-explorer show/hide + shipping-mode + flat-rate.
 *
 * A CUSTOMER-TYPE (audience) selector sits above the manufacturer dropdown:
 * All customers | Retail | Jobber | Dealer | Municipality. Visibility is
 * per-channel — the selector picks which `hidden_<channel>` field the per-node
 * (and bulk) Visibility control reads/writes; "All customers" fans out to all
 * four at once. Shipping-mode + flat-rate stay global (retail-only) and show
 * regardless of audience.
 *
 * Pick a manufacturer line, then the tree opens: brand → category →
 * subcategory → part numbers. Toggle the overridable fields at any grouping
 * level or per SKU. Inside a subcategory, a "bulk select" tool narrows the
 * parts by a CURATED filter (or search) and applies a field to all matching
 * parts at once — stamping explicit PER-SKU overrides. Backend:
 * /api/admin/catalog/*.
 */

const j = (u: string, init?: RequestInit) =>
  fetch(u, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init })

type FieldMeta = {
  key: string; label: string; type: 'enum' | 'money'
  values?: { value: string; label: string }[]; null_label?: string; help?: string
  channel?: string; channel_label?: string; group?: string
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
type ApplyState = { running: boolean; phase: string; done: number; total: number; changed: number; elapsed_ms: number; error: string | null }

const CLEAR = '__clear__'
const box: CSSProperties = { fontVariantNumeric: 'tabular-nums' }
const ICON: Record<NodeType, string> = { brand: '🏭', category: '📁', bucket: '🗂️', part: '🔩' }

// ── Customer types — the multi-select parent layer above the manufacturer line.
// Pick any combination (one, several, or all); the Visibility control edits the
// selected channels together. ──────────────────────────────────────────────
const CHANNELS = ['retail', 'wholesale', 'dealer', 'municipality'] as const
type Channel = (typeof CHANNELS)[number]
const CHANNEL_LABEL: Record<Channel, string> = {
  retail: 'Retail', wholesale: 'Jobber (Wholesale)', dealer: 'Dealer', municipality: 'Municipality',
}
const VIS_VALUES = [
  { value: 'false', label: 'Visible' },
  { value: 'true', label: 'Hidden' },
  { value: 'in_stock_only', label: 'Hidden except in-stock' },
]
const hiddenField = (c: string) => `hidden_${c}`
const VIS = '__visibility__'  // synthetic bulk-field key standing for the selected channels

// ── Per-node field controls ─────────────────────────────────────────────────
function FieldControls({ fields, node, channels, onApplied }: {
  fields: FieldMeta[]; node: TreeNode; channels: Channel[]; onApplied: (field: string, ov: OverrideRow | null) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const scope = node.scope || {}
  const overrides = node.overrides || {}

  const applyOne = async (field: string, value: string | null) => {
    if (value === null) {
      const ov = overrides[field]
      if (ov) await j(`/api/admin/catalog/override/${ov.id}`, { method: 'DELETE' })
      onApplied(field, null)
    } else {
      const r = await j('/api/admin/catalog/override', { method: 'POST', body: JSON.stringify({ field, value, ...scope }) }).then((x) => x.json())
      onApplied(field, r.override ?? null)
    }
  }
  const apply = async (field: string, value: string | null) => {
    setBusy(field)
    try { await applyOne(field, value) } finally { setBusy(null) }
  }
  const applyMany = async (chs: Channel[], value: string | null) => {
    setBusy('__vis__')
    try { for (const c of chs) await applyOne(hiddenField(c), value) } finally { setBusy(null) }
  }

  // Render a normal enum/money control bound to one field's override.
  const renderField = (f: FieldMeta) => {
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
  }

  // Visibility control across the selected customer types.
  const renderVisibility = () => {
    if (channels.length === 0) return null
    // One selected → bind directly to that channel's field.
    if (channels.length === 1) {
      const f = fields.find((x) => x.channel === channels[0])
      return f ? renderField(f) : null
    }
    // Several selected → combined state + fan-out across the selected channels.
    const chOvs = channels.map((c) => overrides[hiddenField(c)]).filter(Boolean) as OverrideRow[]
    const noneSet = chOvs.length === 0
    const allSet = chOvs.length === channels.length
    const vals = new Set(chOvs.map((o) => o.value))
    const combined = noneSet ? '' : (allSet && vals.size === 1 ? [...vals][0] : '__mixed__')
    const anyPending = chOvs.some((o) => o.pending)
    const ring = noneSet ? 'bg-white'
      : anyPending ? 'ring-1 ring-amber-400 bg-amber-50'
      : (allSet && vals.size === 1) ? 'ring-1 ring-emerald-400 bg-emerald-50'
      : 'ring-1 ring-gray-300 bg-gray-50'
    return (
      <label className="flex items-center gap-1 text-[11px] text-gray-500">
        <span className="hidden lg:inline">Visibility</span>
        <select disabled={busy === '__vis__'} value={combined}
          onChange={(e) => { const v = e.target.value; if (v === '__mixed__') return; applyMany(channels, v === '' ? null : v) }}
          className={`rounded border border-gray-300 px-1 py-0.5 text-[11px] text-gray-800 ${ring}`}
          title={combined === '__mixed__' ? 'Mixed across the selected customer types — pick one to set all' : 'Applies to the selected customer types'}>
          <option value="">Inherit</option>
          {VIS_VALUES.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
          {combined === '__mixed__' && <option value="__mixed__">Mixed…</option>}
        </select>
      </label>
    )
  }

  const otherFields = fields.filter((f) => !f.channel)
  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {renderVisibility()}
      {otherFields.map(renderField)}
    </div>
  )
}

// ── A single part row (leaf) ────────────────────────────────────────────────
function PartRow({ node, depth, fields, channels, onMutated }: { node: TreeNode; depth: number; fields: FieldMeta[]; channels: Channel[]; onMutated: () => void }) {
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
      <FieldControls fields={fields} node={self} channels={channels} onApplied={onApplied} />
    </div>
  )
}

// ── Parts panel: bulk-select toolbar + paginated parts for a scope ──────────
function PartsPanel({ scope, depth, fields, channels, onMutated }: { scope: Scope; depth: number; fields: FieldMeta[]; channels: Channel[]; onMutated: () => void }) {
  const [filters, setFilters] = useState<FilterOpt[]>([])
  const [sel, setSel] = useState('')            // "key|||value" or ''
  const [q, setQ] = useState('')
  const [parts, setParts] = useState<TreeNode[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  // Bulk field: the synthetic "Visibility" (audience-scoped) plus the global
  // (non-channel) fields. Default to Visibility.
  const globalFields = useMemo(() => fields.filter((f) => !f.channel), [fields])
  const [bulkField, setBulkField] = useState<string>(VIS)
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

  // The fields a bulk "Visibility" apply targets (the selected customer types),
  // else the picked global field.
  const isVisibilityBulk = bulkField === VIS
  const bulkTargetFields = isVisibilityBulk ? channels.map(hiddenField) : [bulkField]
  const globalMeta = globalFields.find((f) => f.key === bulkField)

  const doBulk = async () => {
    if (isVisibilityBulk && channels.length === 0) return
    const base: Record<string, unknown> = { ...scopeToBody(scope), attr_key: attrKey, attr_value: attrValue, q: q.trim() || undefined }
    const label = bulkValue === CLEAR ? 'clear overrides on'
      : isVisibilityBulk ? `set Visibility (${channels.length} customer type${channels.length === 1 ? '' : 's'}) on`
      : `set ${globalMeta?.label} on`
    if (total > 50 && !window.confirm(`Bulk ${label} ${total} parts?`)) return
    setApplying(true); setMsg(null)
    try {
      let applied = 0
      for (const field of bulkTargetFields) {
        let payload: Record<string, unknown> = { ...base, field }
        if (bulkValue === CLEAR) payload = { ...payload, clear: true }
        else if (field === 'flat_ship_amount') payload = { ...payload, value: bulkValue === '__flat__' ? bulkFlat : bulkValue }
        else payload = { ...payload, value: bulkValue }
        const r = await j('/api/admin/catalog/bulk-apply', { method: 'POST', body: JSON.stringify(payload) })
        const d = await r.json()
        if (!r.ok) { setMsg(d.detail || 'Bulk apply failed.'); return }
        applied = d.applied  // same match-set per field
      }
      setMsg(`${bulkValue === CLEAR ? 'Cleared' : 'Applied to'} ${applied} part${applied === 1 ? '' : 's'}.`)
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
          <option value={VIS}>Visibility</option>
          {globalFields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        {isVisibilityBulk || globalMeta?.type === 'enum' ? (
          <select value={bulkValue} onChange={(e) => setBulkValue(e.target.value)} className="rounded border border-gray-300 px-1 py-0.5">
            <option value={CLEAR}>Inherit (clear)</option>
            {(isVisibilityBulk ? VIS_VALUES : globalMeta!.values!).map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
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
        <button onClick={doBulk} disabled={applying || total === 0 || (isVisibilityBulk && channels.length === 0)} className="rounded bg-gray-800 px-2 py-0.5 font-medium text-white hover:bg-gray-900 disabled:opacity-50">
          {applying ? 'Applying…' : `Apply to ${total.toLocaleString()}`}
        </button>
        {msg && <span className="text-emerald-700">{msg}</span>}
      </div>
      {/* Parts */}
      {loading && parts.length === 0 && <div className="py-1 text-xs text-gray-400">Loading parts…</div>}
      {parts.map((p) => <PartRow key={`part-${p.product_id}`} node={p} depth={depth} fields={fields} channels={channels} onMutated={onMutated} />)}
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
function GroupRow({ node, depth, fields, channels, onMutated, initialOpen = false }: {
  node: TreeNode; depth: number; fields: FieldMeta[]; channels: Channel[]; onMutated: () => void; initialOpen?: boolean
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
        <FieldControls fields={fields} node={self} channels={channels} onApplied={onApplied} />
      </div>
      {open && (
        <div>
          {loading && <div className="py-2 text-xs text-gray-400" style={{ paddingLeft: `${(depth + 1) * 16 + 6}px` }}>Loading…</div>}
          {(kids || []).map((k, i) => (
            <GroupRow key={`${k.type}-${k.category_id ?? k.brand_id ?? k.label}-${i}`} node={k} depth={depth + 1} fields={fields} channels={channels} onMutated={onMutated} />
          ))}
          {/* Parts live under categories + the Uncategorized bucket (not the
              brand root — those would just duplicate the category listings). */}
          {(node.type === 'category' || node.type === 'bucket') && (
            <PartsPanel scope={node.scope || {}} depth={depth + 1} fields={fields} channels={channels} onMutated={onMutated} />
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
  const [sel, setSel] = useState<Channel[]>([...CHANNELS])   // selected customer types (multi)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(0)
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<string | null>(null)
  const [applyState, setApplyState] = useState<ApplyState | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
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
  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])
  useEffect(() => stopPoll, [stopPoll])   // clear the poller on unmount

  const pollApplyStatus = useCallback(async () => {
    const s = await j('/api/admin/catalog/apply-status').then((x) => x.json()).catch(() => null)
    if (!s) return
    setApplyState(s)
    if (!s.running) {
      stopPoll(); setApplying(false); loadPending()
      setApplyMsg(s.phase === 'error'
        ? `Apply failed: ${s.error || 'unknown error'}`
        : `Applied ✓ — ${(s.changed || 0).toLocaleString()} item${s.changed === 1 ? '' : 's'} updated in ${((s.elapsed_ms || 0) / 1000).toFixed(1)}s.`)
    }
  }, [loadPending, stopPoll])

  const applyNow = async () => {
    setApplying(true); setApplyMsg(null)
    setApplyState({ running: true, phase: 'starting', done: 0, total: 0, changed: 0, elapsed_ms: 0, error: null })
    await j('/api/admin/catalog/apply-now', { method: 'POST' }).catch(() => {})
    stopPoll()
    pollRef.current = setInterval(pollApplyStatus, 700)
    pollApplyStatus()
  }
  const channels = CHANNELS.filter((c) => sel.includes(c))
  const toggleCh = (c: Channel) => setSel((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]))
  const selSummary = channels.length === 0 ? '— none selected —'
    : channels.length === CHANNELS.length ? 'all customers'
    : channels.map((c) => CHANNEL_LABEL[c]).join(', ')

  return (
    <div className="mx-auto w-full max-w-[1600px] px-6 py-5">
      <div className="mb-1 flex items-center justify-between gap-2 text-sm text-gray-500">
        <div className="flex items-center gap-2"><Link to="/account" className="hover:underline">Admin</Link><span>/</span><span>Catalog visibility</span></div>
        {!windowMode && <button onClick={() => window.open('/admin/catalog-visibility?window=1', '_blank', 'noopener')} className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:border-gray-400 hover:text-gray-800">⧉ Open in new window</button>}
      </div>
      <h1 className="mb-1 text-2xl font-bold text-gray-900">Catalog visibility & shipping</h1>
      <p className="mb-4 max-w-3xl text-sm text-gray-600">
        First pick <b>which customer types</b> (any combination — one, several, or all), then a
        manufacturer line — and turn it on or off for those audiences, completely or partially, down
        to category, subcategory, or part. Inside a subcategory you can narrow by a filter and apply
        to all matching parts at once. Shipping & flat-rate are global (retail). Changes save
        instantly and go live at tonight's re-index, or click <b>Apply now</b>.
      </p>

      {/* Customer-type selector — multi-select parent layer above the manufacturer dropdown. */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="text-sm font-medium text-gray-700">Customer types</label>
        <div className="inline-flex flex-wrap gap-1.5">
          <button onClick={() => setSel([...CHANNELS])}
            className={`rounded-full border px-3 py-1 text-sm transition ${channels.length === CHANNELS.length ? 'border-red-600 bg-red-600 text-white' : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'}`}>
            All
          </button>
          {CHANNELS.map((c) => {
            const on = sel.includes(c)
            return (
              <button key={c} onClick={() => toggleCh(c)}
                className={`rounded-full border px-3 py-1 text-sm transition ${on ? 'border-red-600 bg-red-600 text-white' : 'border-gray-300 bg-white text-gray-600 hover:bg-gray-50'}`}>
                {on ? '✓ ' : ''}{CHANNEL_LABEL[c]}
              </button>
            )
          })}
        </div>
        <span className="text-xs text-gray-400">Visibility edits apply to <b>{selSummary}</b>.</span>
      </div>
      {channels.length === 0 && (
        <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">Select at least one customer type to edit visibility. (Shipping & flat-rate still apply.)</div>
      )}

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
      {applying && applyState && (
        <div className="mb-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-800">
          <div className="mb-1 flex items-center justify-between">
            <span>
              {applyState.phase === 'reindexing'
                ? `Updating search — ${applyState.done.toLocaleString()} / ${applyState.total.toLocaleString()} items`
                : applyState.phase === 'resolving' ? 'Applying visibility to products…'
                : 'Starting…'}
            </span>
            <span style={box}>{(applyState.elapsed_ms / 1000).toFixed(1)}s</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-blue-100">
            <div className="h-full rounded-full bg-blue-500 transition-all duration-300"
              style={{ width: applyState.total > 0 ? `${Math.round(100 * applyState.done / applyState.total)}%` : (applyState.phase === 'reindexing' ? '100%' : '20%') }} />
          </div>
        </div>
      )}
      {!applying && applyMsg && <div className="mb-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{applyMsg}</div>}

      <div className="mb-3 flex flex-wrap gap-4 text-[11px] text-gray-500">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-400 align-middle"></span>override set here</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400 align-middle"></span>pending until re-index</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-gray-300 align-middle"></span>mixed across customer types</span>
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
          <PartsPanel scope={{ kits: true }} depth={0} fields={fields} channels={channels} onMutated={loadPending} />
        </div>
      ) : !selected ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 py-10 text-center text-sm text-gray-500">Choose a manufacturer line above to open its tree.</div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white">
          <GroupRow key={`brand-${selected.brand_id}`} node={selected} depth={0} fields={fields} channels={channels} onMutated={loadPending} initialOpen />
        </div>
      )}
    </div>
  )
}

export default AdminCatalogVisibilityPage
