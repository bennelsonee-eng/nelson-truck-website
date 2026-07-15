// Titan prerenderer — Sprint-2 SEO, Pillar 2.
//
// Renders the real SPA (served by nginx on ORIGIN) to fully-formed HTML using
// headless Chromium, so search engines / social / AI crawlers that don't run JS
// well get content + head + JSON-LD instead of the empty React shell. nginx
// routes only bot user-agents here; humans keep the SPA. Because it renders the
// actual app, the output matches what users see (no duplicate templates, no
// cloaking) — it just reuses the React 19 head + content we already ship.
//
// Protocol (matches the classic `prerender` nginx recipe): a request path is the
// full target URL, e.g. GET /http://localhost:8080/product/ABC . We only render
// URLs under ORIGIN (allowlist) so this can't be used as an open proxy.
//
// Readiness: the SPA sets window.prerenderReady=true (via <Seo>) once a route's
// data + head are in the DOM; we wait for that (bounded), then capture.

import http from 'node:http'
import { chromium } from 'playwright'

const PORT = Number(process.env.PRERENDER_PORT || 3001)
const ORIGIN = (process.env.PRERENDER_ORIGIN || 'http://localhost:8080').replace(/\/$/, '')
const CACHE_TTL_MS = Number(process.env.PRERENDER_TTL_MS || 3_600_000) // 1 hour
const CACHE_MAX = Number(process.env.PRERENDER_CACHE_MAX || 1000)
const NAV_TIMEOUT = Number(process.env.PRERENDER_NAV_TIMEOUT || 15_000)
const READY_TIMEOUT = Number(process.env.PRERENDER_READY_TIMEOUT || 8_000)
const MAX_CONCURRENCY = Number(process.env.PRERENDER_CONCURRENCY || 3)

// --- tiny LRU cache (Map preserves insertion order) ---
const cache = new Map()
function cacheGet(key) {
  const hit = cache.get(key)
  if (!hit) return null
  if (Date.now() - hit.t > CACHE_TTL_MS) { cache.delete(key); return null }
  // refresh recency
  cache.delete(key); cache.set(key, hit)
  return hit.html
}
function cacheSet(key, html) {
  cache.set(key, { html, t: Date.now() })
  while (cache.size > CACHE_MAX) cache.delete(cache.keys().next().value)
}

// --- concurrency gate ---
let active = 0
const queue = []
function acquire() {
  if (active < MAX_CONCURRENCY) { active++; return Promise.resolve() }
  return new Promise((resolve) => queue.push(resolve))
}
function release() {
  active--
  const next = queue.shift()
  if (next) { active++; next() }
}

let browser = null
async function getBrowser() {
  if (browser && browser.isConnected()) return browser
  browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
  return browser
}

async function render(targetUrl) {
  const b = await getBrowser()
  // UA contains "Prerender" so nginx never re-routes our own fetch as a bot.
  const ctx = await b.newContext({ userAgent: 'Mozilla/5.0 (compatible; TitanPrerender/1.0; +headless)' })
  const page = await ctx.newPage()
  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT })
    await page
      .waitForFunction('window.prerenderReady === true', { timeout: READY_TIMEOUT })
      .catch(() => {}) // fall through on timeout — capture whatever rendered
    return await page.content()
  } finally {
    await ctx.close()
  }
}

const server = http.createServer(async (req, res) => {
  if (req.url === '/healthz') {
    res.writeHead(200, { 'Content-Type': 'text/plain' })
    return res.end('ok')
  }
  // Strip the leading slash → the full target URL (kept encoded).
  const target = req.url.slice(1)
  if (!target.startsWith(ORIGIN + '/') && target !== ORIGIN) {
    res.writeHead(400, { 'Content-Type': 'text/plain' })
    return res.end('prerender: target not allowed')
  }

  const cached = cacheGet(target)
  if (cached) {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'X-Prerender-Cache': 'HIT' })
    return res.end(cached)
  }

  await acquire()
  try {
    const html = await render(target)
    cacheSet(target, html)
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'X-Prerender-Cache': 'MISS' })
    res.end(html)
  } catch (e) {
    console.error(`[prerender] ${target} -> ${e.message}`)
    res.writeHead(500, { 'Content-Type': 'text/plain' })
    res.end('prerender error')
  } finally {
    release()
  }
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[prerender] listening on 127.0.0.1:${PORT}, origin=${ORIGIN}, ttl=${CACHE_TTL_MS}ms`)
})

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    try { if (browser) await browser.close() } catch {}
    process.exit(0)
  })
}
