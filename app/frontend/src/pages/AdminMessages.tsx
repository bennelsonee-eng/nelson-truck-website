import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

/**
 * Admin message board — everything an admin needs to know about, in one place.
 *   • Alerts: persistent admin_message rows (kit-conflict warnings from the
 *     catalog-visibility resolver, etc.), with ack / resolve.
 *   • Site health: a LIVE rollup from request_log — recent 5xx, cart/checkout/
 *     payment failures, client JS errors, bot errors.
 * Backend: /api/admin/messages/*.
 */

const j = (u: string, init?: RequestInit) =>
  fetch(u, { credentials: 'include', headers: { 'Content-Type': 'application/json' }, ...init })

type Message = {
  id: number; kind: string; severity: string; title: string; body: string
  context: Record<string, unknown> | null; status: string; occurrences: number
  first_seen: string | null; last_seen: string | null; resolved_by: string | null
}
type Health = {
  hours: number; telemetry_active: boolean; severity: string
  counts: { errors_4xx_5xx: number; errors_5xx: number; js_errors: number; cart_failures: number }
  by_status: { cls: string; c: number }[]
  top_error_paths: { path: string; status: number; c: number }[]
  cart_checkout_errors: { path: string; status: number; c: number }[]
  js_errors_top: { detail: string; c: number }[]
  bot_errors: { bot: string; c: number; errs: number }[]
}

const SEV_CLS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  info: 'bg-blue-100 text-blue-800 border-blue-200',
  ok: 'bg-emerald-100 text-emerald-800 border-emerald-200',
}
const KIND_LABEL: Record<string, string> = {
  kit_conflict: 'Kit conflict', site_error: 'Site error', cart_failure: 'Cart failure',
  js_error: 'JS error', page_down: 'Page down', info: 'Info',
}
const fmt = (s: string | null) => (s ? new Date(s).toLocaleString() : '')

function Stat({ label, value, danger }: { label: string; value: number; danger?: boolean }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${danger && value > 0 ? 'border-red-200 bg-red-50' : 'border-gray-200 bg-white'}`}>
      <div className={`text-xl font-bold ${danger && value > 0 ? 'text-red-700' : 'text-gray-900'}`}>{value.toLocaleString()}</div>
      <div className="text-[11px] text-gray-500">{label}</div>
    </div>
  )
}

export function AdminMessagesPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [hours, setHours] = useState(48)
  const [showResolved, setShowResolved] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const windowMode = typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('window')

  const loadMessages = useCallback(async () => {
    const r = await j('/api/admin/messages')
    if (r.status === 401 || r.status === 403) throw new Error('Admin access required.')
    const d = await r.json()
    setMessages(d.messages || [])
  }, [])
  const loadHealth = useCallback(async (h: number) => {
    const d = await j(`/api/admin/messages/site-health?hours=${h}`).then((x) => x.json()).catch(() => null)
    if (d) setHealth(d)
  }, [])

  useEffect(() => {
    ;(async () => {
      setLoading(true); setErr(null)
      try { await loadMessages(); await loadHealth(hours) }
      catch (e) { setErr(e instanceof Error ? e.message : 'Failed to load.') }
      finally { setLoading(false) }
    })()
  }, [loadMessages, loadHealth, hours])

  const act = async (id: number, action: 'ack' | 'resolve') => {
    await j(`/api/admin/messages/${id}/${action}`, { method: 'POST' })
    await loadMessages()
    window.dispatchEvent(new CustomEvent('titan:alerts-changed'))
  }

  const visible = messages.filter((m) => showResolved || m.status !== 'resolved')
  const openCount = messages.filter((m) => m.status === 'open').length

  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 py-5">
      <div className="mb-1 flex items-center justify-between gap-2 text-sm text-gray-500">
        <div className="flex items-center gap-2"><Link to="/account" className="hover:underline">Admin</Link><span>/</span><span>Message board</span></div>
        {!windowMode && (
          <button onClick={() => window.open('/admin/messages?window=1', '_blank', 'noopener')} className="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-600 hover:border-gray-400 hover:text-gray-800">⧉ Open in new window</button>
        )}
      </div>
      <h1 className="mb-1 text-2xl font-bold text-gray-900">Admin message board</h1>
      <p className="mb-4 max-w-3xl text-sm text-gray-600">Warnings that need a decision (like a hidden part that breaks a kit) plus a live read of major site issues — page errors, cart/checkout failures, and JavaScript errors.</p>

      {err && <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</div>}
      {loading && <div className="py-8 text-center text-sm text-gray-400">Loading…</div>}

      {!loading && (
        <>
          {/* Alerts */}
          <section className="mb-6">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Alerts {openCount > 0 && <span className="ml-1 rounded-full bg-red-600 px-2 py-0.5 text-xs text-white">{openCount} open</span>}</h2>
              <label className="flex items-center gap-1 text-xs text-gray-500"><input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> show resolved</label>
            </div>
            {visible.length === 0 ? (
              <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 py-6 text-center text-sm text-gray-500">No alerts. 🎉</div>
            ) : (
              <div className="space-y-2">
                {visible.map((m) => (
                  <div key={m.id} className={`rounded-xl border p-3 ${m.status === 'resolved' ? 'border-gray-200 bg-gray-50 opacity-70' : SEV_CLS[m.severity] || 'border-gray-200 bg-white'}`}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="rounded bg-white/70 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-600">{KIND_LABEL[m.kind] || m.kind}</span>
                          <span className="text-sm font-semibold text-gray-900">{m.title}</span>
                          {m.occurrences > 1 && <span className="text-[11px] text-gray-500">×{m.occurrences}</span>}
                        </div>
                        <div className="mt-1 text-sm text-gray-700">{m.body}</div>
                        <div className="mt-1 text-[11px] text-gray-500">
                          {m.status === 'resolved' ? `resolved by ${m.resolved_by || 'system'}` : `last seen ${fmt(m.last_seen)}`}
                          {m.context && (m.context as { kit_sku?: string }).kit_sku ? ` · kit ${(m.context as { kit_sku?: string }).kit_sku}` : ''}
                        </div>
                      </div>
                      {m.status !== 'resolved' && (
                        <div className="flex shrink-0 gap-2">
                          {m.status === 'open' && <button onClick={() => act(m.id, 'ack')} className="rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 hover:border-gray-400">Ack</button>}
                          <button onClick={() => act(m.id, 'resolve')} className="rounded-md bg-gray-800 px-2 py-1 text-xs text-white hover:bg-gray-900">Resolve</button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Site health */}
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">
                Site health
                {health && <span className={`ml-2 rounded-full border px-2 py-0.5 text-xs ${SEV_CLS[health.severity] || ''}`}>{health.severity === 'ok' ? 'all clear' : health.severity}</span>}
              </h2>
              <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="rounded-md border border-gray-300 px-2 py-1 text-xs">
                <option value={24}>last 24h</option>
                <option value={48}>last 48h</option>
                <option value={168}>last 7 days</option>
              </select>
            </div>

            {!health?.telemetry_active ? (
              <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 py-6 text-center text-sm text-gray-500">No telemetry captured yet.</div>
            ) : (
              <>
                <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="HTTP errors (4xx/5xx)" value={health.counts.errors_4xx_5xx} />
                  <Stat label="Server errors (5xx)" value={health.counts.errors_5xx} danger />
                  <Stat label="Cart / checkout failures" value={health.counts.cart_failures} danger />
                  <Stat label="JavaScript errors" value={health.counts.js_errors} />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <HealthList title="Cart / checkout / payment errors" empty="No cart or checkout errors." rows={health.cart_checkout_errors.map((r) => ({ a: r.path, b: String(r.status), c: r.c }))} />
                  <HealthList title="Top error pages" empty="No page errors." rows={health.top_error_paths.map((r) => ({ a: r.path, b: String(r.status), c: r.c }))} />
                  <HealthList title="JavaScript errors" empty="No JS errors." rows={health.js_errors_top.map((r) => ({ a: r.detail, b: '', c: r.c }))} />
                  <HealthList title="Bot crawl (errors)" empty="No bot activity." rows={health.bot_errors.map((r) => ({ a: r.bot, b: `${r.errs} err`, c: r.c }))} />
                </div>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}

function HealthList({ title, rows, empty }: { title: string; empty: string; rows: { a: string; b: string; c: number }[] }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-3">
      <div className="mb-2 text-sm font-semibold text-gray-800">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-gray-400">{empty}</div>
      ) : (
        <ul className="space-y-1">
          {rows.map((r, i) => (
            <li key={i} className="flex items-center justify-between gap-2 text-xs">
              <span className="min-w-0 flex-1 truncate text-gray-700" title={r.a}>{r.a || '—'}</span>
              {r.b && <span className="shrink-0 rounded bg-gray-100 px-1 text-[10px] text-gray-500">{r.b}</span>}
              <span className="shrink-0 font-semibold text-gray-800">{r.c.toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default AdminMessagesPage
