import { useLocation } from 'react-router-dom'
import { Seo, LOCALBUSINESS_JSONLD } from '../components/Seo'
import { BRANCHES, InquiryForm } from '../components/Inquiry'
import type { InquiryKind } from '../components/Inquiry'

// /contact — both branches (address, phone, hours) plus a form that reaches
// the counter team (POST /api/inquiries). Launch audit 2026-09-22: the site had
// no contact page at all; every "contact" link was a mailto:.
// ?topic=project opens it as a custom-build inquiry; ?topic=quote as a quote.
export default function ContactPage() {
  const loc = useLocation()
  const topic = new URLSearchParams(loc.search).get('topic')
  const kind: InquiryKind = topic === 'project' ? 'project' : topic === 'quote' ? 'quote' : 'contact'
  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <Seo
        title="Contact Nelson Truck Equipment — Portland, OR & Kent, WA"
        description="Call, visit or send us a message. Nelson Truck Equipment: 6309 NE Columbia Blvd, Portland, OR (503-548-9300) and 20063 84th Ave S, Kent, WA (253-395-3825). Mon–Fri 8am–5pm."
        path="/contact"
        jsonLd={LOCALBUSINESS_JSONLD}
      />
      <h1 className="text-3xl font-bold text-gray-900">Contact us</h1>
      <p className="mt-2 max-w-2xl text-gray-600">
        Talk to a real person at the counter. Call either branch, stop in, or send us a message and we'll get back to you within one business day.
      </p>

      <div className="mt-8 grid gap-8 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          {BRANCHES.map((b) => (
            <div key={b.key} className="rounded-lg border border-gray-200 bg-white p-5">
              <h2 className="text-lg font-bold text-gray-900">{b.name}</h2>
              <address className="mt-2 not-italic text-sm text-gray-700">
                {b.street}<br />{b.cityLine}
              </address>
              <p className="mt-2 text-sm">
                <a href={`tel:${b.tel}`} className="font-semibold text-red-700 hover:underline">{b.phone}</a>
              </p>
              <p className="mt-1 text-sm text-gray-600">{b.hours}</p>
              <a href={b.map} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block text-xs font-semibold text-gray-700 underline hover:text-red-700">
                Directions →
              </a>
            </div>
          ))}
          <p className="text-sm text-gray-600">
            Email: <a href="mailto:sales@nelsontruck.com" className="text-red-700 hover:underline">sales@nelsontruck.com</a>
          </p>
        </div>
        <div className="rounded-lg border border-gray-200 bg-white p-6 lg:col-span-3">
          <h2 className="mb-4 text-lg font-bold text-gray-900">
            {kind === 'project' ? 'Tell us about your project' : kind === 'quote' ? 'Request a quote' : 'Send us a message'}
          </h2>
          <InquiryForm prefill={{ kind }} />
        </div>
      </div>
    </div>
  )
}
