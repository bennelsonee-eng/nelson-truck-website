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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>
)
