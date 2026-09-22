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
  // Rewritten 2026-09-22 (launch audit) to match how the site actually works
  // today: online orders are for linked trade/fleet accounts on purchase
  // order; everyone else gets a quote or buys at the counter; web orders don't
  // price freight at checkout. Revisit the ordering/payment answers when card
  // checkout goes live. [CONFIRM: …] notes are hidden from the public page.
  faq: {
    title: 'Frequently Asked Questions',
    subtitle: 'Ordering, pickup, shipping, fitment, returns, and installation.',
    description: 'Answers to common questions about ordering, pickup, shipping, fitment, returns, warranty and installation at Nelson Truck Equipment in Portland, OR and Kent, WA.',
    sections: [
      { heading: 'Ordering & accounts', items: [
        { q: 'How do I place an order?', a: 'Trade, fleet and municipal customers with a linked Nelson account can order online on purchase order. Anyone can request a quote from any product page, send us a message from the [Contact page](/contact), or call either counter — Portland 503-548-9300, Kent 253-395-3825 — and we’ll price it and have it ready for pickup or shipping.' },
        { q: 'Do I need an account?', a: 'You can browse, check stock at each branch and request quotes without one. Online checkout is for approved trade accounts; open one from the Open B2B account link and our sales team will link it to your Nelson customer record.' },
        { q: 'How do I set up a wholesale or trade account?', a: 'We offer account pricing to qualified trade, fleet and municipal customers. Use Open B2B account or email sales@nelsontruck.com; once your account is linked, your pricing shows automatically when you’re signed in. [CONFIRM: any application requirements]' },
      ]},
      { heading: 'Payment', items: [
        { q: 'How do I pay?', a: 'Approved accounts order on purchase order with their usual terms. For card or cash, pay at the counter when you pick up, or call either branch. [CONFIRM: phone card payments + any card surcharge]' },
      ]},
      { heading: 'Pickup & shipping', items: [
        { q: 'Can I pick it up today?', a: 'Yes — items marked In stock at Portland or Kent can be picked up at that counter, Monday to Friday, 8am to 5pm. Each product page shows the stock at each branch.' },
        { q: 'Do you ship?', a: 'Yes. Parts ship by parcel carrier and large equipment ships by freight. We’re a Pacific Northwest business and most of our shipments go to Oregon and Washington. [CONFIRM: shipping regions]' },
        { q: 'How much does shipping cost?', a: 'The shipping charge is based on weight, size and destination and is added to your invoice when the order ships. For large or heavy items, ask us for a freight quote before you order.' },
        { q: 'How are large items like snow plows and truck bodies handled?', a: 'Plows, spreaders, truck bodies, liftgates and aerial equipment are usually mounted in our Portland or Kent shop, so you drive in and drive out. We can also quote freight delivery.' },
      ]},
      { heading: 'Fitment & products', items: [
        { q: 'How do I know a part fits my truck?', a: 'Use “Shop your vehicle” to filter the catalog to your year, make and model, or check the fitment on each product page. Not sure? Call either counter or send a message with your vehicle details and we’ll confirm the right part before you buy.' },
        { q: 'What if an item isn’t in stock?', a: 'Many items can be special ordered even when they aren’t on our shelves — the product page shows the status. We’ll often suggest an in-stock alternative, or we’ll source it for you.' },
      ]},
      { heading: 'Returns, warranty & installation', items: [
        { q: 'What is your return policy?', a: 'Unused items in original, resalable packaging may be returned. Contact us with your order or invoice number to start a return. Special-order and installed items may not be returnable. See [Returns & Warranty](/returns). [CONFIRM: return window + any restocking fee]' },
        { q: 'How do warranty claims work?', a: 'We handle warranty work in-house for the brands we sell and install. Contact us with your invoice number and a description of the problem, and we’ll work the claim through the manufacturer’s warranty.' },
        { q: 'Do you install equipment?', a: 'Yes — we install everything we sell, at our Portland and Kent shops: plows and spreaders, truck bodies, liftgates, lighting, van shelving and more. We also build custom — tell us about your project from the [Contact page](/contact).' },
      ]},
      { heading: 'Contact & locations', items: [
        { q: 'Where are you located?', a: 'Portland: 6309 NE Columbia Blvd, Portland, OR 97218. Kent: 20063 84th Ave S, Kent, WA 98032. Both are open Monday to Friday, 8am to 5pm. Family-owned since 1937.' },
        { q: 'How do I contact you?', a: 'Call Portland at 503-548-9300 or Kent at 253-395-3825, email sales@nelsontruck.com, or send a message from the [Contact page](/contact).' },
      ]},
    ],
  },
  about: {
    title: 'About Nelson Truck Equipment',
    subtitle: 'Family-owned and outfitting Pacific Northwest trucks since 1937.',
    description: 'Nelson Truck Equipment — family-owned since 1937: snow plows, truck bodies, tow trucks, aerial lifts, Landoll trailers, van upfits and accessories, installed in Portland, OR and Kent, WA.',
    body: `Nelson Truck Equipment has been outfitting work trucks and vans across the Pacific Northwest since 1937. We’re family-owned, and we still work the way we started: the right equipment, on the shelf when you need it, installed by people who know it.

## What we do

We sell, install and service commercial truck equipment from two shops — **Portland, OR** and **Kent, WA**. That covers snow and ice equipment from Western, Meyer and SnowDogg; truck bodies from Knapheide, CM, Rugby and others; Jerr-Dan tow trucks and tow truck parts; Dur-A-Lift bucket trucks and aerial lifts; Landoll trailers and Landoll parts; Tommy Gate liftgates; Weather Guard and Kargo Master van shelving; and the lighting, hitches, toolboxes and accessories that finish a truck. We also sell steel and aluminum by the pound at the counter.

## Why customers come to us

**Pick it up today.** Thousands of parts sit on our shelves in Portland and Kent. Every product page shows what’s in stock at each branch, so you can grab it off the shelf instead of waiting on a shipment.

**We install everything we sell.** Plows mounted and wired, bodies set on the chassis, liftgates and lighting installed — drive in, drive out.

**Talk to a real expert.** Not sure it fits? Our counter team sorts out fitment and shows you in-stock alternatives on the spot.

**We build custom, too.** Service bodies, racks, one-off fabrication and special upfits — if you can spec it, our shops can build it.

## Who we work with

Contractors, fleets, municipalities, tow operators, utilities and everyday truck owners. Trade and fleet customers can open an account for account pricing and online ordering.

## Visit us

**Portland:** 6309 NE Columbia Blvd, Portland, OR 97218 · 503-548-9300 · Mon–Fri 8am–5pm

**Kent:** 20063 84th Ave S, Kent, WA 98032 · 253-395-3825 · Mon–Fri 8am–5pm

[Contact us](/contact) or [browse the catalog](/catalog).

[CONFIRM: add company history, ownership and team details]`,
  },
  returns: {
    title: 'Returns & Warranty',
    subtitle: 'How returns and warranty claims work.',
    description: 'Nelson Truck Equipment returns and warranty policy — how to return unused items, what can’t be returned, and how manufacturer warranty claims are handled in Portland, OR and Kent, WA.',
    body: `## Returns

Unused items in their original, resalable packaging may be returned. To start a return, contact us with your order or invoice number — call Portland at 503-548-9300 or Kent at 253-395-3825, email [sales@nelsontruck.com](mailto:sales@nelsontruck.com), or use the [Contact page](/contact). We’ll tell you where to bring or send the item.

The quickest way is to bring the item and your invoice to the counter it came from.

[CONFIRM: return window (e.g. 30 days), restocking fee, who pays return shipping]

## What can’t be returned

Special-order items that we ordered in for you (unless they arrived damaged or wrong), items that have been installed, used or modified, and built-to-order equipment such as truck bodies, tow truck bodies and aerial units. [CONFIRM: electrical returns]

## Damaged or wrong items

If something arrives damaged, or isn’t what you ordered, tell us as soon as you can and keep the packaging. Freight damage should be noted on the delivery receipt before you sign. We’ll make it right.

## Warranty

We sell and install equipment from manufacturers such as Western, Meyer, SnowDogg, Knapheide, Jerr-Dan, Dur-A-Lift and Tommy Gate, and we handle warranty work in-house. If you have a problem with something you bought from us, contact us with your invoice number and a description of the issue. We’ll inspect it and work the claim through the manufacturer’s warranty. Warranty terms are set by each manufacturer; product pages link to the manufacturer’s warranty documents where we have them.

[CONFIRM: any Nelson workmanship guarantee on installation]`,
  },
  shipping: {
    title: 'Pickup & Shipping',
    subtitle: 'Pick it up today, or we’ll ship it.',
    description: 'Nelson Truck Equipment pickup and shipping policy — same-day pickup in Portland, OR and Kent, WA, parcel and freight shipping, and how shipping is charged.',
    body: `## Pick it up today

Items shown **In stock** at Portland or Kent can be picked up at that counter, Monday to Friday, 8am to 5pm. Each product page shows stock at each branch. Call ahead if you need a lot of something and we’ll set it aside.

**Portland:** 6309 NE Columbia Blvd, Portland, OR 97218 · 503-548-9300

**Kent:** 20063 84th Ave S, Kent, WA 98032 · 253-395-3825

## Shipping

Parts ship by parcel carrier from whichever branch has them in stock. Large or heavy items — plows, spreaders, bodies, liftgates — ship by freight, or we install them in our shop.

**How shipping is charged:** the shipping charge depends on weight, size and destination and is added to your invoice when the order ships. For large or heavy items, ask us for a freight quote before you order.

[CONFIRM: shipping regions, carriers, any free-shipping threshold]

## Lead times

In-stock items are usually ready the same day for pickup. Special-order items ship once they arrive from the manufacturer; the product page shows when an item is special order, and we’ll keep you posted.

## Installation

Most equipment we sell can be installed at our Portland or Kent shop. Tell us your truck and what you need, and we’ll schedule it — [request a quote](/contact?topic=quote).`,
  },
  privacy: {
    title: 'Privacy & Terms',
    subtitle: 'How we handle your information, and the terms of using this site.',
    description: 'Nelson Truck Equipment privacy policy and terms of use.',
    noindex: true,
    body: `## Privacy

We collect only the information needed to process your orders, provide support, and improve your experience — such as your name, contact details, shipping address, and order history. We do not sell your personal information. If you pay by card, payment details are handled by the card processor and are not stored on our servers.

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
      acceptedAnswer: { '@type': 'Answer', text: stripConfirm(f.a).replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').trim() },
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
                <p className="mt-2 text-gray-600">{renderInline(stripConfirm(f.a).trim(), `faq-${f.q}`)}</p>
              </details>
            ))}
          </div>
        </div>
      ))}
      <p className="mt-6 text-sm">
        Still have a question? <a href="mailto:sales@nelsontruck.com" className="text-red-700 hover:underline">Email our sales team</a> and we’ll get right back to you.
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
