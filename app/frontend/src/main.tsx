import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './styles/index.css'
import App from './App'

// Prerender readiness flag (Sprint-2 Pillar 2). The headless-Chrome prerenderer
// waits for window.prerenderReady === true before capturing HTML, so bots get
// fully-rendered content, not the empty shell. Starts false; the <Seo> component
// flips it true once a route's data + head are in place (it only mounts after
// data loads on product/category pages). Meaningless/harmless for real users.
;(window as unknown as { prerenderReady?: boolean }).prerenderReady = false

// --- Client-side error telemetry (Phase 2 site-health) --------------------
// Report uncaught errors + promise rejections + chunk-load failures to the
// backend so the nightly health report can surface "pages that don't load" and
// JS breakage. Capped per page load so an error loop can't flood the endpoint.
;(() => {
  let sent = 0
  const CAP = 8
  const post = (body: Record<string, unknown>) => {
    if (sent >= CAP) return
    sent++
    try {
      fetch('/api/telemetry/js-error', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, path: location.pathname + location.search }),
        keepalive: true,
      }).catch(() => {})
    } catch { /* never let telemetry break the app */ }
  }
  window.addEventListener('error', (e: ErrorEvent) => {
    const msg = e.message || ''
    const isChunk = /chunk|dynamically imported module|import\(\)/i.test(msg)
    post({
      kind: isChunk ? 'chunk_load' : 'error',
      message: msg, source: e.filename || '', line: e.lineno, col: e.colno,
      stack: e.error && e.error.stack ? String(e.error.stack).slice(0, 3000) : '',
    })
  })
  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    const r = e.reason
    post({
      kind: 'unhandledrejection',
      message: r && r.message ? String(r.message) : String(r).slice(0, 500),
      stack: r && r.stack ? String(r.stack).slice(0, 3000) : '',
    })
  })
})()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
)
