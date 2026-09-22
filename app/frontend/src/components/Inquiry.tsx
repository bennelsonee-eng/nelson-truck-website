import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'

// Quote requests + contact form (launch audit 2026-09-22).
//
// Before this, the "Get Quote" button on every quote-only product had no
// handler, and every other "email us" call to action was a mailto: link that
// only works if the visitor has a mail program set up. Now everything posts to
// POST /api/inquiries, which stores the request and emails the sales inbox.
//
// <InquiryModalHost/> is mounted once at the app root. It opens the form for:
//   * openInquiry({...}) calls (the PDP quote button, "Tell us about your project"), and
//   * any click on a mailto:sales@nelsontruck.com link anywhere on the site --
//     the subject/body of the link pre-fill the message, so the dozen snow-plow
//     "email us a quote" links all land in the same form without editing each one.

export type InquiryKind = 'quote' | 'contact' | 'project'

export interface InquiryPrefill {
  kind?: InquiryKind
  product_sku?: string | null
  product_name?: string | null
  message?: string
  heading?: string
}

export const BRANCHES = [
  {
    key: 'Portland',
    name: 'Portland, OR',
    street: '6309 NE Columbia Blvd',
    cityLine: 'Portland, OR 97218',
    phone: '503-548-9300',
    tel: '+15035489300',
    hours: 'Mon–Fri 8am–5pm',
    map: 'https://www.google.com/maps/search/?api=1&query=6309+NE+Columbia+Blvd+Portland+OR+97218',
  },
  {
    key: 'Kent',
    name: 'Kent, WA',
    street: '20063 84th Ave S',
    cityLine: 'Kent, WA 98032',
    phone: '253-395-3825',
    tel: '+12533953825',
    hours: 'Mon–Fri 8am–5pm',
    map: 'https://www.google.com/maps/search/?api=1&query=20063+84th+Ave+S+Kent+WA+98032',
  },
] as const

const EVENT = 'nelson:inquiry'

export function openInquiry(prefill: InquiryPrefill = {}) {
  window.dispatchEvent(new CustomEvent<InquiryPrefill>(EVENT, { detail: prefill }))
}

function prefillFromMailto(href: string): InquiryPrefill {
  try {
    const q = href.split('?')[1] || ''
    const params = new URLSearchParams(q)
    const subject = params.get('subject') || ''
    const body = params.get('body') || ''
    const kind: InquiryKind = /quote|recommend|spec/i.test(subject) ? 'quote' : /project|custom/i.test(subject) ? 'project' : 'contact'
    return { kind, message: [subject, body].filter(Boolean).join('\n\n') }
  } catch {
    return { kind: 'contact' }
  }
}

const KIND_HEADING: Record<InquiryKind, string> = {
  quote: 'Request a quote',
  contact: 'Contact us',
  project: 'Tell us about your project',
}

export function InquiryForm({ prefill = {}, onDone, dark = false }: { prefill?: InquiryPrefill; onDone?: () => void; dark?: boolean }) {
  const kind: InquiryKind = prefill.kind || 'contact'
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [branch, setBranch] = useState<string>('Either')
  const [quantity, setQuantity] = useState('')
  const [message, setMessage] = useState(prefill.message || '')
  const [website, setWebsite] = useState('') // honeypot
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [doneId, setDoneId] = useState<number | null | undefined>(undefined)

  const label = dark ? 'text-gray-200' : 'text-gray-700'
  const input = 'mt-1 w-full rounded border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-red-600 focus:outline-none focus:ring-1 focus:ring-red-600'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!name.trim()) { setError('Please tell us your name.'); return }
    if (!email.trim() && !phone.trim()) { setError('Please give us an email address or a phone number so we can reply.'); return }
    setBusy(true)
    try {
      const r = await fetch('/api/inquiries', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind,
          name, company: company || null, email: email || null, phone: phone || null,
          branch, product_sku: prefill.product_sku || null, product_name: prefill.product_name || null,
          quantity: quantity ? Number(quantity) : null,
          message: message || null,
          page_url: window.location.pathname + window.location.search,
          website,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setError(typeof d?.detail === 'string' ? d.detail : 'Something went wrong. Please call us at 503-548-9300 (Portland) or 253-395-3825 (Kent).')
        return
      }
      setDoneId(d?.id ?? null)
    } catch {
      setError('Could not send. Please call us at 503-548-9300 (Portland) or 253-395-3825 (Kent).')
    } finally {
      setBusy(false)
    }
  }

  if (doneId !== undefined) {
    return (
      <div className={`rounded border ${dark ? 'border-green-700 bg-green-900/30 text-green-100' : 'border-green-200 bg-green-50 text-green-900'} p-4 text-sm`}>
        <p className="font-semibold">Thanks, {name.split(' ')[0] || 'we got it'} — your request is in.</p>
        <p className="mt-1">Our counter team will get back to you by {email ? 'email' : 'phone'} within one business day.{doneId ? ` Reference #${doneId}.` : ''}</p>
        {onDone && <button type="button" onClick={onDone} className="mt-3 rounded bg-gray-900 px-4 py-2 text-xs font-semibold text-white hover:bg-black">Close</button>}
      </div>
    )
  }

  return (
    <form onSubmit={submit} className="space-y-3" noValidate>
      {prefill.product_sku && (
        <div className={`rounded border ${dark ? 'border-white/20 bg-white/5 text-gray-200' : 'border-gray-200 bg-gray-50 text-gray-700'} px-3 py-2 text-xs`}>
          Product: <span className="font-mono">{prefill.product_sku}</span>{prefill.product_name ? ` — ${prefill.product_name}` : ''}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={`block text-xs font-semibold ${label}`}>Name *
          <input className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
        </label>
        <label className={`block text-xs font-semibold ${label}`}>Company
          <input className={input} value={company} onChange={(e) => setCompany(e.target.value)} autoComplete="organization" />
        </label>
        <label className={`block text-xs font-semibold ${label}`}>Email
          <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
        </label>
        <label className={`block text-xs font-semibold ${label}`}>Phone
          <input className={input} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoComplete="tel" />
        </label>
      </div>
      <fieldset>
        <legend className={`text-xs font-semibold ${label}`}>Which location?</legend>
        <div className="mt-1 flex flex-wrap gap-2">
          {['Portland', 'Kent', 'Either'].map((b) => (
            <label key={b} className={`cursor-pointer rounded border px-3 py-1.5 text-xs ${branch === b ? 'border-red-700 bg-red-700 text-white' : dark ? 'border-white/30 text-gray-200' : 'border-gray-300 text-gray-700'}`}>
              <input type="radio" name="branch" value={b} checked={branch === b} onChange={() => setBranch(b)} className="sr-only" />
              {b === 'Either' ? 'Either one' : b}
            </label>
          ))}
        </div>
      </fieldset>
      {kind === 'quote' && (
        <label className={`block text-xs font-semibold ${label}`}>Quantity
          <input className={`${input} max-w-[8rem]`} type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
      )}
      <label className={`block text-xs font-semibold ${label}`}>
        {kind === 'quote' ? 'Anything we should know? (truck year/make/model, chassis, timing)' : kind === 'project' ? 'What are you building?' : 'How can we help?'}
        <textarea className={`${input} min-h-[96px]`} value={message} onChange={(e) => setMessage(e.target.value)} />
      </label>
      {/* Honeypot: hidden from people, filled by bots. */}
      <input type="text" name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)}
             className="absolute -left-[9999px] h-0 w-0 opacity-0" aria-hidden="true" />
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy} className="rounded bg-red-700 px-5 py-2.5 text-sm font-bold text-white hover:bg-red-800 disabled:opacity-60">
          {busy ? 'Sending…' : kind === 'quote' ? 'Send quote request' : 'Send'}
        </button>
        <span className={`text-xs ${dark ? 'text-gray-400' : 'text-gray-500'}`}>
          Or call Portland <a className="underline" href="tel:+15035489300">503-548-9300</a> · Kent <a className="underline" href="tel:+12533953825">253-395-3825</a>
        </span>
      </div>
    </form>
  )
}

export function InquiryModalHost() {
  const [prefill, setPrefill] = useState<InquiryPrefill | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const onOpen = (e: Event) => {
      setPrefill((e as CustomEvent<InquiryPrefill>).detail || {})
      setNonce((n) => n + 1)
    }
    // Route every mailto:sales@ link on the site through the form.
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      const a = (e.target as Element | null)?.closest?.('a[href^="mailto:sales@nelsontruck.com"]') as HTMLAnchorElement | null
      if (!a) return
      e.preventDefault()
      setPrefill(prefillFromMailto(a.getAttribute('href') || ''))
      setNonce((n) => n + 1)
    }
    window.addEventListener(EVENT, onOpen)
    document.addEventListener('click', onClick)
    return () => {
      window.removeEventListener(EVENT, onOpen)
      document.removeEventListener('click', onClick)
    }
  }, [])

  useEffect(() => {
    if (!prefill) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPrefill(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [prefill])

  if (!prefill) return null
  const kind = prefill.kind || 'contact'
  return (
    <div className="fixed inset-0 z-[1000] flex items-start justify-center overflow-y-auto bg-black/60 px-4 py-10" role="dialog" aria-modal="true"
         aria-labelledby="inquiry-heading" onMouseDown={(e) => { if (e.target === e.currentTarget) setPrefill(null) }}>
      <div className="relative w-full max-w-lg rounded-lg bg-white p-6 shadow-2xl">
        <button type="button" onClick={() => setPrefill(null)} className="absolute right-3 top-3 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700" aria-label="Close">✕</button>
        <h2 id="inquiry-heading" className="text-xl font-bold text-gray-900">{prefill.heading || KIND_HEADING[kind]}</h2>
        <p className="mb-4 mt-1 text-sm text-gray-600">
          {kind === 'quote'
            ? 'Tell us what you need and our counter team will price it — including mounting and install at our Portland or Kent shop.'
            : 'A real person at our Portland or Kent counter will get back to you.'}
        </p>
        <InquiryForm key={nonce} prefill={prefill} onDone={() => setPrefill(null)} />
      </div>
    </div>
  )
}
