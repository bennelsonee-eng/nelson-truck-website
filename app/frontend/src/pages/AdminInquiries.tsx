import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Seo } from '../components/Seo'

// /admin/inquiries — every quote request / contact message / project inquiry
// sent from the site (POST /api/inquiries), newest first. Each one is also
// emailed to the inquiry alert address; this list is the record that can't be
// lost to a mail outage.

interface Inquiry {
  id: number
  created_at: string | null
  kind: string
  status: string
  name: string
  company: string | null
  email: string | null
  phone: string | null
  branch: string | null
  product_sku: string | null
  product_name: string | null
  quantity: number | null
  message: string | null
  page_url: string | null
  handled_at: string | null
  handled_by: string | null
  notes: string | null
}

const KIND_LABEL: Record<string, string> = { quote: 'Quote', contact: 'Contact', project: 'Project' }

export default function AdminInquiriesPage() {
  const [items, setItems] = useState<Inquiry[]>([])
  const [status, setStatus] = useState<'new' | 'handled' | ''>('new')
  const [openCount, setOpenCount] = useState(0)
  const [subs, setSubs] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    const r = await fetch(`/api/admin/inquiries${status ? `?status=${status}` : ''}`, { credentials: 'include' })
    if (!r.ok) { setError(r.status === 401 || r.status === 403 ? 'Admins only.' : `Could not load (${r.status}).`); return }
    const d = await r.json()
    setItems(d.items || [])
    setOpenCount(d.open || 0)
    setSubs(d.newsletter_subscribers || 0)
  }, [status])

  useEffect(() => { load() }, [load])

  async function mark(id: number, next: 'new' | 'handled') {
    const r = await fetch(`/api/admin/inquiries/${id}`, {
      method: 'PATCH', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: next }),
    })
    if (r.ok) load()
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <Seo title="Inquiries — Admin" path="/admin/inquiries" noindex />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Inquiries</h1>
          <p className="text-sm text-gray-600">Quote requests and messages from the website. {openCount} open · {subs} newsletter subscribers.</p>
        </div>
        <div className="flex gap-2 text-sm">
          {(['new', 'handled', ''] as const).map((s) => (
            <button key={s || 'all'} type="button" onClick={() => setStatus(s)}
                    className={`rounded border px-3 py-1.5 ${status === s ? 'border-red-700 bg-red-700 text-white' : 'border-gray-300 text-gray-700 hover:bg-gray-50'}`}>
              {s === 'new' ? 'Open' : s === 'handled' ? 'Handled' : 'All'}
            </button>
          ))}
        </div>
      </div>
      {error && <p className="mt-4 text-red-700">{error}</p>}
      {!error && items.length === 0 && <p className="mt-8 text-gray-500">Nothing here.</p>}
      <div className="mt-6 space-y-3">
        {items.map((i) => (
          <div key={i.id} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-500">
                  #{i.id} · {KIND_LABEL[i.kind] || i.kind} · {i.created_at ? new Date(i.created_at).toLocaleString() : ''}{i.branch ? ` · ${i.branch}` : ''}
                </div>
                <div className="mt-1 font-semibold text-gray-900">{i.name}{i.company ? ` — ${i.company}` : ''}</div>
                <div className="mt-0.5 text-sm text-gray-700">
                  {i.email && <a className="text-red-700 hover:underline" href={`mailto:${i.email}`}>{i.email}</a>}
                  {i.email && i.phone && ' · '}
                  {i.phone && <a className="hover:underline" href={`tel:${i.phone}`}>{i.phone}</a>}
                </div>
                {i.product_sku && (
                  <div className="mt-1 text-sm text-gray-700">
                    Product: <Link className="font-mono text-red-700 hover:underline" to={`/product/${encodeURIComponent(i.product_sku)}`}>{i.product_sku}</Link>
                    {i.product_name ? ` — ${i.product_name}` : ''}{i.quantity ? ` · qty ${i.quantity}` : ''}
                  </div>
                )}
              </div>
              <div>
                {i.status === 'new'
                  ? <button type="button" onClick={() => mark(i.id, 'handled')} className="rounded bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-black">Mark handled</button>
                  : <button type="button" onClick={() => mark(i.id, 'new')} className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50">Reopen</button>}
                {i.handled_by && <div className="mt-1 text-right text-[11px] text-gray-500">by {i.handled_by}</div>}
              </div>
            </div>
            {i.message && <p className="mt-3 whitespace-pre-line rounded bg-gray-50 p-3 text-sm text-gray-800">{i.message}</p>}
            {i.page_url && <div className="mt-2 text-[11px] text-gray-400">Sent from {i.page_url}</div>}
          </div>
        ))}
      </div>
    </div>
  )
}
