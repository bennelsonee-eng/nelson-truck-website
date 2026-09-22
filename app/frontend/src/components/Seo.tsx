/**
 * Per-route <head> manager built on **React 19 native document metadata**:
 * <title>, <meta>, and <link> rendered anywhere in the tree are automatically
 * hoisted into <head> — no react-helmet needed, and it renders server-side
 * natively once the FastAPI SSR layer lands (plan 1.1). JSON-LD <script> tags
 * aren't hoisted (they don't need to be — Google reads JSON-LD anywhere), so
 * they render inline where this component sits.
 */

import { useEffect } from 'react'

/**
 * Single source of truth for the canonical host on the CLIENT. This MUST match
 * the backend's `canonical_base_url` (app/backend/app/config.py) — the launch
 * domain (nelsontruck.com), NOT the Access-gated preview host we build on. When
 * the launch host is finalized (www vs apex), change it in both places.
 */
export const CANONICAL_BASE_URL = 'https://nelsontruck.com'
export const SITE_NAME = 'Nelson Truck Equipment'

/** Absolute URL on the canonical host. Pass-through if already absolute. */
export function absoluteUrl(pathOrUrl: string): string {
  if (!pathOrUrl) return CANONICAL_BASE_URL
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl
  return `${CANONICAL_BASE_URL}${pathOrUrl.startsWith('/') ? '' : '/'}${pathOrUrl}`
}

/** Site-wide Organization JSON-LD (home page). */
export const ORGANIZATION_JSONLD = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  name: SITE_NAME,
  url: CANONICAL_BASE_URL,
  logo: `${CANONICAL_BASE_URL}/brand/nelson-logo.png`,
  description:
    'Pacific Northwest commercial truck-equipment dealer and upfitter since 1937 — snow plows, truck bodies, tow trucks, aerial & bucket trucks, Landoll trailers, liftgates, and accessories. We install everything we sell.',
  foundingDate: '1937',
  areaServed: ['Oregon', 'Washington', 'Pacific Northwest'],
  // TODO: add `sameAs` (Google Business Profile + social) once confirmed.
}

/** Per-branch LocalBusiness JSON-LD (home page and /contact). */
export const LOCALBUSINESS_JSONLD = [
  {
    '@context': 'https://schema.org',
    '@type': 'AutoPartsStore',
    name: 'Nelson Truck Equipment — Portland',
    url: CANONICAL_BASE_URL,
    telephone: '+1-503-548-9300',
    foundingDate: '1937',
    parentOrganization: { '@type': 'Organization', name: SITE_NAME, url: CANONICAL_BASE_URL },
    // Street address + hours as published on nelsontruck.com (checked 2026-09-22).
    address: { '@type': 'PostalAddress', streetAddress: '6309 NE Columbia Blvd', addressLocality: 'Portland', addressRegion: 'OR', postalCode: '97218', addressCountry: 'US' },
    openingHours: 'Mo-Fr 08:00-17:00',
    areaServed: ['Oregon', 'Washington', 'Pacific Northwest'],
  },
  {
    '@context': 'https://schema.org',
    '@type': 'AutoPartsStore',
    name: 'Nelson Truck Equipment — Kent',
    url: CANONICAL_BASE_URL,
    telephone: '+1-253-395-3825',
    foundingDate: '1937',
    parentOrganization: { '@type': 'Organization', name: SITE_NAME, url: CANONICAL_BASE_URL },
    address: { '@type': 'PostalAddress', streetAddress: '20063 84th Ave S', addressLocality: 'Kent', addressRegion: 'WA', postalCode: '98032', addressCountry: 'US' },
    openingHours: 'Mo-Fr 08:00-17:00',
    areaServed: ['Washington', 'Oregon', 'Pacific Northwest'],
  },
]

/** Site-wide WebSite JSON-LD with a SearchAction (enables the sitelinks search box). */
export const WEBSITE_JSONLD = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  name: SITE_NAME,
  url: CANONICAL_BASE_URL,
  potentialAction: {
    '@type': 'SearchAction',
    target: {
      '@type': 'EntryPoint',
      urlTemplate: `${CANONICAL_BASE_URL}/catalog?q={search_term_string}`,
    },
    'query-input': 'required name=search_term_string',
  },
}

/** Trim to a length budget on a word boundary (titles ~60, descriptions ~160). */
export function clamp(text: string | null | undefined, max: number): string {
  const s = (text || '').replace(/\s+/g, ' ').trim()
  if (s.length <= max) return s
  return s.slice(0, max - 1).replace(/\s+\S*$/, '').trim() + '…'
}

/** Serialize JSON-LD, neutralizing any "</script>" that could break out. */
function jsonLdHtml(obj: object): string {
  return JSON.stringify(obj).replace(/</g, '\\u003c')
}

interface SeoProps {
  /** Full <title> (brand suffix not auto-appended — include it if wanted). */
  title: string
  description?: string | null
  /** Canonical PATH (e.g. "/product/ABC"); resolved against the canonical host. */
  path?: string
  /** OG/Twitter image (path or absolute URL). */
  image?: string | null
  /** og:type — "website" (default), "product", etc. */
  type?: string
  /** Emit <meta name="robots" content="noindex,follow"> for thin/gated pages. */
  noindex?: boolean
  /** One or more schema.org JSON-LD objects. */
  jsonLd?: object | object[] | null
}

export function Seo({ title, description, path, image, type = 'website', noindex, jsonLd }: SeoProps) {
  const canonical = path ? absoluteUrl(path) : undefined
  // Every page shares with a picture: its own when it has one, else the
  // branded default (launch audit 2026-09-22 -- the homepage had none).
  const img = absoluteUrl(image || '/og-default.jpg')
  const desc = description ? clamp(description, 300) : undefined
  const blocks = jsonLd ? (Array.isArray(jsonLd) ? jsonLd : [jsonLd]) : []

  // Signal the prerenderer that this route's content + head are in the DOM. On
  // product/category pages <Seo> only renders after data loads, so this fires at
  // the right moment; the prerender service waits on this flag before capturing.
  useEffect(() => {
    ;(window as unknown as { prerenderReady?: boolean }).prerenderReady = true
  })

  return (
    <>
      <title>{title}</title>
      {desc && <meta name="description" content={desc} />}
      {canonical && <link rel="canonical" href={canonical} />}
      {noindex && <meta name="robots" content="noindex,follow" />}

      {/* Open Graph */}
      <meta property="og:site_name" content={SITE_NAME} />
      <meta property="og:title" content={title} />
      {desc && <meta property="og:description" content={desc} />}
      <meta property="og:type" content={type} />
      {canonical && <meta property="og:url" content={canonical} />}
      {img && <meta property="og:image" content={img} />}

      {/* Twitter */}
      <meta name="twitter:card" content={img ? 'summary_large_image' : 'summary'} />
      <meta name="twitter:title" content={title} />
      {desc && <meta name="twitter:description" content={desc} />}
      {img && <meta name="twitter:image" content={img} />}

      {blocks.map((b, i) => (
        <script key={i} type="application/ld+json" dangerouslySetInnerHTML={{ __html: jsonLdHtml(b) }} />
      ))}
    </>
  )
}
