import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In the unified monorepo the React MES app is served by FastAPI under
// /mes-app/ (same origin, port 8000). The Vite dev server (5173) is only used
// for hot-reload work and proxies API + Jinja MES routes back to FastAPI:8000,
// so the app can use same-origin relative URLs everywhere.
//
// (The old optimizeDeps.noDiscovery workaround for spaces in the source path is
// gone — the monorepo path has no spaces.)
export default defineConfig({
  base: '/mes-app/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/mes': 'http://localhost:8000',
    },
  },
})
