import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Nelson site uses 5175 (dev) / 4175 (preview) so it can run alongside the
    // Titan site (5174/4174) and Nelson ERP (5173/4173) on the same machine.
    port: 5175,
    // strictPort: fail fast if 5175 is taken instead of silently falling back to a
    // random port — that fallback was confusing in past sessions ("Vite said it
    // started but I can't find it") so we make the collision visible.
    strictPort: true,
    // Bind to all interfaces so Tailscale + LAN access works (UFW + Cloudflare gate public access)
    host: true,
    proxy: {
      // Nelson backend runs on 8002 (Titan backend is 8001).
      '/api':    'http://localhost:8002',
      // Static plow / truck imagery served by the backend's StaticFiles mount
      '/static': 'http://localhost:8002',
      // SEO surfaces served by the backend's seo router. Without these, Vite's
      // SPA fallback would answer /robots.txt and /sitemap*.xml with the empty
      // HTML shell (200), hiding them from crawlers. Regex key (leading ^) so it
      // matches the sitemap index AND the paginated children (sitemap-products-3.xml).
      '/robots.txt':    'http://localhost:8002',
      '/llms.txt':      'http://localhost:8002',
      '^/sitemap.*\\.xml$': 'http://localhost:8002',
    },
    // Allow any host (for Tailscale IP, Cloudflare hostnames, etc.). Network-level gating is via UFW + Tailscale + Cloudflare.
    allowedHosts: true,
  },
  preview: {
    port: 4175,
    strictPort: true,
    host: true,
  },
  // Split React + Router into a long-cached vendor chunk (rarely changes, so
  // repeat visits and post-deploy revisits skip re-downloading it). Route-level
  // lazy chunks (mockups, admin-kits) are created automatically from the dynamic
  // import()s in App.tsx.
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },

  // SPA fallback — serve index.html for client-side routes
  appType: 'spa',
})
