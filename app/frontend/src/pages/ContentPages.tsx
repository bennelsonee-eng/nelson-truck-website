import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Seo, SITE_NAME } from '../components/Seo'

// Static content + trust pages (FAQ, About, Returns/Warranty, Shipping, Privacy).
//
// The drafted copy below is the DEFAULT. Admins can override any page from
// /admin/content (stored in the content_page table); the override wins, else the
// default renders — so the pages always work even with an empty table.
//
// AEO note: the FAQ renders every answer in the DOM (native <details>, collapsed
// via the browser, not conditionally mounted) so the prerenderer + crawlers see
// the full text, and it emits FAQPage JSON-LD.
//
// Business specifics are marked [CONFIRM: …] — stripped from the public render,
// but visible in the admin editor so Ben knows what to fill in.

export interface FaqSection { heading: string; items: { q: string; a: string }[] }
export interface ContentDefault {
  title: string
  subtitle?: string
  description: string
  body?: string          // markdown for prose pages
  sections?: FaqSection[] // FAQ
  noindex?: boolean
}

export const CONTENT_DEFAULTS: Record<string, ContentDefault> = {
  faq: {
    title: 'Frequently Asked Questions',
    subtitle: 'Ordering, shipping, fitment, returns, and more.',
    description: 'Answers to common questions about ordering, payment, shipping, fitment, returns, warranty, and service at Titan Truck Equipment.',
    sections: [
      { heading: 'Ordering & accounts', items: [
        { q: 'How do I place an order?', a: 'Browse or search the catalog, add items to your cart, and check out online. Commercial and municipal customers can also order by purchase order — email sales@titantruck.com or call us and we’ll help you get the right parts.' },
        { q: 'Do I need an account to order?', a: 'No — you can shop and order as a guest. Creating an account lets you track orders, reorder quickly, and (for trade customers) see your wholesale pricing.' },
        { q: 'How do I set up a wholesale or trade account?', a: 'We offer wholesale pricing to qualified trade, fleet, and municipal accounts. Contact sales@titantruck.com to apply; once approved, your account pricing shows automatically when you’re signed in. [CONFIRM: any application requirements]' },
      ]},
      { heading: 'Payment', items: [
        { q: 'What payment methods do you accept?', a: 'We accept major credit cards at checkout. Approved trade, fleet, and government accounts may also order on purchase order with terms. [CONFIRM: accepted cards + PO terms]' },
      ]},
      { heading: 'Shipping', items: [
        { q: 'Where do you ship?', a: 'We ship throughout the Pacific Northwest and beyond, from our Spokane, WA headquarters and Boise, ID location. [CONFIRM: nationwide vs. regional shipping]' },
        { q: 'How much does shipping cost?', a: 'Shipping is calculated at checkout based on the items, weight, and destination. Oversized items ship by freight. [CONFIRM: free-shipping threshold, if any]' },
        { q: 'How are large items like snow plows shipped?', a: 'Heavy or oversized equipment — snow plows, spreaders, service bodies — ships by freight carrier. We’ll quote freight and coordinate delivery; some large equipment is also available for pickup or installation at our locations.' },
        { q: 'How soon will my order ship?', a: 'In-stock items typically ship within [CONFIRM: e.g. 1–2 business days]. Special-order items ship once they arrive from the manufacturer — lead times are shown on the product page and we’ll keep you updated.' },
      ]},
      { heading: 'Fitment & products', items: [
        { q: 'How do I know a part fits my truck?', a: 'Use “Shop your vehicle” to filter the catalog to parts that fit your year, make, and model, or check the fitment listed on each product. Not sure? Email or call us with your vehicle details and we’ll confirm the right part before you buy.' },
        { q: 'What if an item is out of stock or special order?', a: 'Many items are available as special orders even when not in stock — the product page shows the status and estimated lead time. When something is unavailable, we’ll often suggest an in-stock alternative, or you can contact us and we’ll source it.' },
      ]},
      { heading: 'Returns, warranty & service', items: [
        { q: 'What is your return policy?', a: 'Unused items in original, resalable packaging may be returned. Contact sales@titantruck.com to start a return and we’ll walk you through it. Special-order and installed items may not be returnable. [CONFIRM: return window + any restocking fee]' },
        { q: 'How do warranty claims work?', a: 'We’re a direct dealer for Western, Meyer, SnowDogg, and Buyers/SaltDogg, and we handle warranty work in-house. If you have an issue, contact us with your order details and we’ll help you resolve it through the manufacturer’s warranty.' },
        { q: 'Do you install equipment?', a: 'Yes — we install snow and ice equipment and truck upfits at our Spokane and Boise locations. [CONFIRM: install scheduling / which locations]' },
      ]},
      { heading: 'Contact & locations', items: [
        { q: 'Where are you located?', a: 'Titan Truck Equipment is headquartered in Spokane, WA, with a location in Boise, ID, serving the Pacific Northwest. Family-owned since 1971. [CONFIRM: addresses + hours]' },
        { q: 'How do I contact you?', a: 'Email sales@titantruck.com or call us [CONFIRM: phone number]. We’re happy to help with fitment, quotes, freight, and orders.' },
      ]},
    ],
  },
  about: {
    title: 'About Titan Truck Equipment',
    subtitle: 'Family-owned and outfitting Pacific Northwest trucks since 1971.',
    description: 'Titan Truck Equipment — family-owned since 1971, outfitting commercial trucks and vans across the Pacific Northwest from Spokane, WA and Boise, ID.',
    body: `Titan Truck Equipment has been outfitting commercial trucks and vans across the Pacific Northwest since 1971. Family-owned and operated, we supply and install snow and ice equipment, truck accessories, and work-ready upfits for contractors, fleets, municipalities, and everyday drivers.

We’re a direct dealer for the brands the region relies on — including Western, Meyer, SnowDogg, and Buyers/SaltDogg — and we back what we sell with in-house service and warranty work. With locations in **Spokane, WA** (headquarters) and **Boise, ID**, we combine a deep parts catalog with real fitment expertise, so you get the right equipment the first time.

Whether you’re plowing snow, building out a service van, or equipping a fleet, our team is here to help. [Get in touch](mailto:sales@titantruck.com) or [browse the catalog](/catalog).

[CONFIRM: company history details, ownership/team, addresses & hours]`,
  },
  returns: {
    title: 'Returns & Warranty',
    subtitle: 'How returns and warranty claims work.',
    description: 'Titan Truck Equipment returns and warranty policy — how to return unused items and how manufacturer warranty claims are handled.',
    body: `## Returns

Unused items in their original, resalable packaging may be returned. To start a return, email [sales@titantruck.com](mailto:sales@titantruck.com) with your order number and we’ll guide you through the process. Please note that special-order items and items that have been installed may not be eligible for return.

[CONFIRM: return window (e.g. 30 days), restocking fee, who pays return shipping]

## Warranty

We’re a direct dealer for Western, Meyer, SnowDogg, and Buyers/SaltDogg, and we perform warranty work in-house. If you have a warranty issue, contact us with your order details and we’ll help you resolve it under the manufacturer’s warranty.

[CONFIRM: warranty terms / any Titan-specific guarantees]`,
  },
  shipping: {
    title: 'Shipping Policy',
    subtitle: 'How and where we ship.',
    description: 'Titan Truck Equipment shipping policy — shipping costs, freight for oversized equipment, lead times, and service area across the Pacific Northwest.',
    body: `Orders ship from our Spokane, WA and Boise, ID locations. Shipping cost is calculated at checkout based on the items, weight, and destination.

**Oversized equipment** — snow plows, spreaders, and service bodies — ships by freight carrier. We’ll quote freight and coordinate delivery, and many large items are also available for pickup or installation at our locations.

**Lead times:** in-stock items typically ship within a couple of business days; special-order items ship once they arrive from the manufacturer, with estimated lead times shown on the product page.

[CONFIRM: shipping regions (regional vs nationwide), free-shipping threshold, carrier(s), in-stock ship window, pickup details]`,
  },
  privacy: {
    title: 'Privacy & Terms',
    subtitle: 'How we handle your information, and the terms of using this site.',
    description: 'Titan Truck Equipment privacy policy and terms of use.',
    noindex: true,
    body: `## Privacy

We collect only the information needed to process your orders, provide support, and improve your experience — such as your name, contact details, shipping address, and order history. We do not sell your personal information. Payment details are handled securely by our payment processor and are not stored on our servers.

## Terms of use

By using this site you agree to use it lawfully and not to misuse or attempt to disrupt it. Product information, pricing, and availability are subject to change without notice. We work to keep listings accurate but are not liable for typographical errors.

[CONFIRM: this is placeholder copy — have it reviewed by legal before launch; add cookie/analytics disclosure if analytics are added]`,
  },
}

// --------------------------------------------------------------------------- //
// Minimal markdown renderer: paragraphs, ## headings, **bold**, [text](url).
// [CONFIRM: …] notes are stripped from the public render.
// --------------------------------------------------------------------------- //

function stripConfirm(s: string): string {
  return s.replace(/\[CONFIRM:[^\]]*\]/g, '').replace(/[ \t]+\n/g, '\n')
}

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // Tokenize **bold** and [text](url) left to right.
  const re = /(\*\*([^*]+)\*\*)|(\[([^\]]+)\]\(([^)]+)\))/g
  let last = 0, m: RegExpExecArray | null, i = 0
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index))
    if (m[1]) {
      nodes.push(<strong key={`${keyBase}-b${i}`}>{m[2]}</strong>)
    } else if (m[3]) {
      const href = m[5]
      const internal = href.startsWith('/')
      nodes.push(internal
        ? <Link key={`${keyBase}-l${i}`} to={href} className="text-red-700 hover:underline">{m[4]}</Link>
        : <a key={`${keyBase}-l${i}`} href={href} className="text-red-700 hover:underline">{m[4]}</a>)
    }
    last = m.index + m[0].length; i++
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

function Markdown({ md }: { md: string }) {
  const blocks = stripConfirm(md).split(/\n\n+/).map((b) => b.trim()).filter(Boolean)
  return (
    <>
      {blocks.map((block, i) => block.startsWith('## ')
        ? <h2 key={i} className="text-base font-bold text-gray-900 mt-5 mb-2">{renderInline(block.slice(3), `h${i}`)}</h2>
        : <p key={i} className="mt-3">{renderInline(block, `p${i}`)}</p>)}
    </>
  )
}

// --------------------------------------------------------------------------- //

interface EffectiveContent { title: string; subtitle?: string; description: string; body?: string; sections?: FaqSection[]; noindex: boolean }

// Fetch the admin override for a slug and merge it over the built-in default.
function useContent(slug: string): EffectiveContent {
  const def = CONTENT_DEFAULTS[slug]
  const [ov, setOv] = useState<Record<string, unknown> | null>(null)
  useEffect(() => {
    let alive = true
    fetch(`/api/content/${slug}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (alive) setOv(d) })
      .catch(() => {})
    return () => { alive = false }
  }, [slug])
  const data = ov?.data as { sections?: FaqSection[] } | undefined
  return {
    title: (ov?.title as string) || def.title,
    subtitle: (ov?.subtitle as string) ?? def.subtitle,
    description: def.description,
    body: (ov?.body as string) ?? def.body,
    sections: data?.sections || def.sections,
    noindex: (ov?.noindex as boolean) ?? def.noindex ?? false,
  }
}

function ContentLayout({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <div className="bg-white">
      <section className="bg-gray-900">
        <div className="max-w-3xl mx-auto px-6 py-10">
          <h1 className="text-3xl md:text-4xl font-extrabold text-white tracking-tight">{title}</h1>
          {subtitle && <p className="mt-2 text-sm text-gray-300">{subtitle}</p>}
        </div>
      </section>
      <div className="max-w-3xl mx-auto px-6 py-8 text-sm text-gray-700 leading-relaxed">{children}</div>
    </div>
  )
}

export function FaqPage() {
  const c = useContent('faq')
  const sections = c.sections || []
  const faqJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: sections.flatMap((s) => s.items).map((f) => ({
      '@type': 'Question',
      name: f.q,
      acceptedAnswer: { '@type': 'Answer', text: stripConfirm(f.a).trim() },
    })),
  }
  return (
    <ContentLayout title={c.title} subtitle={c.subtitle}>
      <Seo title={`${c.title} | ${SITE_NAME}`} description={c.description} path="/faq" noindex={c.noindex} jsonLd={faqJsonLd} />
      {sections.map((section) => (
        <div key={section.heading} className="mb-6">
          <h2 className="text-base font-bold text-gray-900 mb-2">{section.heading}</h2>
          <div className="divide-y divide-gray-100 border-t border-b border-gray-100">
            {section.items.map((f) => (
              <details key={f.q} className="group py-3">
                <summary className="cursor-pointer list-none flex justify-between items-center font-medium text-gray-900">
                  <span>{f.q}</span>
                  <span className="ml-4 text-gray-400 group-open:rotate-45 transition-transform">+</span>
                </summary>
                <p className="mt-2 text-gray-600">{stripConfirm(f.a).trim()}</p>
              </details>
            ))}
          </div>
        </div>
      ))}
      <p className="mt-6 text-sm">
        Still have a question? <a href="mailto:sales@titantruck.com" className="text-red-700 hover:underline">Email our sales team</a> and we’ll get right back to you.
      </p>
    </ContentLayout>
  )
}

function ProsePage({ slug, path }: { slug: string; path: string }) {
  const c = useContent(slug)
  return (
    <ContentLayout title={c.title} subtitle={c.subtitle}>
      <Seo title={`${c.title} | ${SITE_NAME}`} description={c.description} path={path} noindex={c.noindex} />
      {c.body ? <Markdown md={c.body} /> : null}
    </ContentLayout>
  )
}

export function AboutPage() { return <ProsePage slug="about" path="/about" /> }
export function ReturnsPage() { return <ProsePage slug="returns" path="/returns" /> }
export function ShippingPage() { return <ProsePage slug="shipping" path="/shipping" /> }
export function PrivacyPage() { return <ProsePage slug="privacy" path="/privacy" /> }
