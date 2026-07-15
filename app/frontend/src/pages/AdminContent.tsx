import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CONTENT_DEFAULTS, type FaqSection } from './ContentPages'

// Admin editor for the FAQ + trust pages (/admin/content). Edits are stored as
// overrides in content_page (backend require_admin); the public pages fall back
// to the built-in defaults when there's no override. Gated by the admin API
// itself — a 401/403 shows the access-required message.

const SLUGS = ['faq', 'about', 'returns', 'shipping', 'privacy'] as const
type Slug = (typeof SLUGS)[number]

interface Form {
  title: string
  subtitle: string
  body: string
  sections: FaqSection[]
  noindex: boolean
  is_published: boolean
}

function defaultForm(slug: Slug, override: Record<string, unknown> | null): Form {
  const def = CONTENT_DEFAULTS[slug]
  const data = override?.data as { sections?: FaqSection[] } | undefined
  return {
    title: (override?.title as string) || def.title,
    subtitle: (override?.subtitle as string) ?? def.subtitle ?? '',
    body: (override?.body as string) ?? def.body ?? '',
    sections: structuredClone(data?.sections || def.sections || []),
    noindex: (override?.noindex as boolean) ?? def.noindex ?? false,
    is_published: (override?.is_published as boolean) ?? true,
  }
}

export function AdminContentPage() {
  const [slug, setSlug] = useState<Slug>('faq')
  const [overrides, setOverrides] = useState<Record<string, Record<string, unknown>>>({})
  const [form, setForm] = useState<Form | null>(null)
  const [status, setStatus] = useState<'loading' | 'ok' | 'denied' | 'error'>('loading')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  // Load all overrides once (also serves as the auth gate).
  useEffect(() => {
    fetch('/api/admin/content', { credentials: 'include' })
      .then((r) => {
        if (r.status === 401 || r.status === 403) { setStatus('denied'); return null }
        if (!r.ok) { setStatus('error'); return null }
        return r.json()
      })
      .then((rows: Record<string, unknown>[] | null) => {
        if (!rows) return
        const map: Record<string, Record<string, unknown>> = {}
        for (const row of rows) map[row.slug as string] = row
        setOverrides(map)
        setStatus('ok')
      })
      .catch(() => setStatus('error'))
  }, [])

  // Rebuild the form when the selected page (or its loaded override) changes.
  useEffect(() => {
    if (status !== 'ok') return
    setForm(defaultForm(slug, overrides[slug] || null))
    setSaved(null)
  }, [slug, status, overrides])

  const isFaq = slug === 'faq'
  const hasOverride = useMemo(() => !!overrides[slug], [overrides, slug])

  async function save() {
    if (!form) return
    setSaving(true); setSaved(null)
    try {
      const r = await fetch(`/api/admin/content/${slug}`, {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: form.title,
          subtitle: form.subtitle || null,
          body: isFaq ? null : form.body,
          data: isFaq ? { sections: form.sections } : null,
          noindex: form.noindex,
          is_published: form.is_published,
        }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const row = await r.json()
      setOverrides((m) => ({ ...m, [slug]: row }))
      setSaved('Saved. Live now (bots re-render within the hour).')
    } catch (e) {
      setSaved(`Error: ${(e as Error).message}`)
    } finally {
      setSaving(false)
    }
  }

  function revertToDefault() {
    setForm(defaultForm(slug, null))
    setSaved('Reset to the built-in default (not saved yet — click Save to publish).')
  }

  if (status === 'loading') return <div className="p-8 text-gray-500">Loading…</div>
  if (status === 'denied') return (
    <div className="p-8 max-w-lg mx-auto text-center">
      <h1 className="text-xl font-bold mb-2">Admin access required</h1>
      <p className="text-sm text-gray-600 mb-4">Sign in with an admin account to edit content pages.</p>
      <Link to="/login" className="px-4 py-2 bg-red-700 text-white rounded text-sm">Log in</Link>
    </div>
  )
  if (status === 'error' || !form) return <div className="p-8 text-red-600">Couldn’t load content editor.</div>

  const set = (patch: Partial<Form>) => setForm((f) => (f ? { ...f, ...patch } : f))

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-bold mb-1">Content pages</h1>
      <p className="text-sm text-gray-500 mb-5">Edit the FAQ and trust pages. Changes publish immediately; the public site falls back to the built-in copy for any page you haven’t overridden.</p>

      <div className="flex flex-wrap gap-2 mb-6">
        {SLUGS.map((s) => (
          <button key={s} onClick={() => setSlug(s)}
            className={`px-3 py-1.5 rounded text-sm font-medium ${slug === s ? 'bg-red-700 text-white' : 'bg-gray-100 hover:bg-gray-200 text-gray-700'}`}>
            {s}{overrides[s] ? ' •' : ''}
          </button>
        ))}
      </div>

      <div className="space-y-4">
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span>Editing <code className="bg-gray-100 px-1 rounded">/{slug}</code></span>
          <span>{hasOverride ? 'Custom (overriding default)' : 'Using built-in default'}</span>
          <a href={`/${slug}`} target="_blank" rel="noreferrer" className="text-red-700 hover:underline">View page ↗</a>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-gray-700">Title</span>
          <input value={form.title} onChange={(e) => set({ title: e.target.value })}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
        </label>
        <label className="block">
          <span className="text-sm font-medium text-gray-700">Subtitle</span>
          <input value={form.subtitle} onChange={(e) => set({ subtitle: e.target.value })}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
        </label>

        {isFaq ? (
          <FaqEditor sections={form.sections} onChange={(sections) => set({ sections })} />
        ) : (
          <label className="block">
            <span className="text-sm font-medium text-gray-700">Body</span>
            <span className="block text-xs text-gray-400 mb-1">Markdown: <code>## Heading</code>, <code>**bold**</code>, <code>[text](url)</code>. Blank line = new paragraph. <code>[CONFIRM: …]</code> notes are hidden on the public page.</span>
            <textarea value={form.body} onChange={(e) => set({ body: e.target.value })} rows={16}
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm font-mono" />
          </label>
        )}

        <div className="flex flex-wrap items-center gap-5 pt-1">
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.is_published} onChange={(e) => set({ is_published: e.target.checked })} />
            Published
          </label>
          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.noindex} onChange={(e) => set({ noindex: e.target.checked })} />
            noindex (keep out of search)
          </label>
        </div>

        <div className="flex items-center gap-3 pt-2 border-t border-gray-100 mt-2">
          <button onClick={save} disabled={saving}
            className="px-4 py-2 bg-red-700 hover:bg-red-800 disabled:opacity-50 text-white text-sm font-semibold rounded">
            {saving ? 'Saving…' : 'Save & publish'}
          </button>
          <button onClick={revertToDefault} className="px-3 py-2 text-sm text-gray-600 hover:text-gray-900">Reset to default</button>
          {saved && <span className="text-sm text-gray-600">{saved}</span>}
        </div>
      </div>
    </div>
  )
}

// Structured FAQ editor: sections of Q&A with add/remove/reorder-lite.
function FaqEditor({ sections, onChange }: { sections: FaqSection[]; onChange: (s: FaqSection[]) => void }) {
  const update = (fn: (draft: FaqSection[]) => void) => {
    const next = structuredClone(sections)
    fn(next)
    onChange(next)
  }
  return (
    <div className="space-y-5">
      <span className="text-sm font-medium text-gray-700">Questions</span>
      {sections.map((section, si) => (
        <div key={si} className="rounded border border-gray-200 p-3">
          <div className="flex items-center gap-2 mb-2">
            <input value={section.heading}
              onChange={(e) => update((d) => { d[si].heading = e.target.value })}
              placeholder="Section heading"
              className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm font-semibold" />
            <button onClick={() => update((d) => { d.splice(si, 1) })}
              className="text-xs text-gray-400 hover:text-red-600">Remove section</button>
          </div>
          <div className="space-y-3 pl-2 border-l-2 border-gray-100">
            {section.items.map((item, ii) => (
              <div key={ii} className="space-y-1">
                <div className="flex gap-2">
                  <input value={item.q}
                    onChange={(e) => update((d) => { d[si].items[ii].q = e.target.value })}
                    placeholder="Question"
                    className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm font-medium" />
                  <button onClick={() => update((d) => { d[si].items.splice(ii, 1) })}
                    className="text-xs text-gray-400 hover:text-red-600 whitespace-nowrap">✕</button>
                </div>
                <textarea value={item.a}
                  onChange={(e) => update((d) => { d[si].items[ii].a = e.target.value })}
                  placeholder="Answer" rows={2}
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm" />
              </div>
            ))}
            <button onClick={() => update((d) => { d[si].items.push({ q: '', a: '' }) })}
              className="text-xs text-red-700 hover:underline">+ Add question</button>
          </div>
        </div>
      ))}
      <button onClick={() => update((d) => { d.push({ heading: 'New section', items: [{ q: '', a: '' }] }) })}
        className="px-3 py-1.5 rounded bg-gray-100 hover:bg-gray-200 text-sm text-gray-700">+ Add section</button>
    </div>
  )
}
