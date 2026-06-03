// capture-v418.mjs — headless screenshot capture for WO v4.18 (Phase 2C-2).
//
// The preview MCP returns screenshots inline only (can't write PNGs to disk), so
// committed PR screenshots (WO §3.4) are produced by this reusable Playwright
// step. Point it at a permitted origin serving the built SPA against a live
// backend (the FastAPI server at :8000 serving /mes-app/, which is in the
// autologin allowlist), and it writes PNGs to docs/screenshots/v4.18/.
//
// Usage (from frontend/):
//   npm i -D playwright && npx playwright install chromium
//   node scripts/capture-v418.mjs                 # defaults to http://localhost:8000
//   MES_BASE=http://localhost:5173 node scripts/capture-v418.mjs
//
// Each shot is independent (try/catch) so one failure doesn't abort the run.

import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://localhost:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.18')
mkdirSync(OUT, { recursive: true })

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(page, name, fn) {
  try {
    if (fn) await fn()
    await page.screenshot({ path: resolve(OUT, name) })
    console.log(`✓ ${name}`)
  } catch (e) {
    console.log(`✗ ${name} — ${e.message}`)
  }
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } })
const page = await ctx.newPage()

// Boot the SPA (autologin fires from this permitted origin) and settle.
await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
await wait(1500)

// Quieter shots: turn off the demo tooltip overlay if present.
await page.click('button[title="Hide demo tooltips"]').catch(() => {})

// Route to the Planning board (client-side nav; avoids SPA-fallback 404s).
await page.click('a[href="/mes-app/planning"]').catch(() => {})
await wait(1200)

await shot(page, 'planning-board-live.png')

await shot(page, 'branch-picker-open.png', async () => {
  await page.click('button[title^="Switch active branch"]')
  await wait(400)
})

await shot(page, 'branch-switch-result.png', async () => {
  // pick a non-current branch from the open dropdown, then let the board re-scope
  const opt = page.locator('[role="menu"] button', { hasText: 'CPT' })
  await opt.click()
  await wait(1500)
})

// Restore JHB so the demo is left populated.
await page.click('button[title^="Switch active branch"]').catch(() => {})
await wait(300)
await page.locator('[role="menu"] button', { hasText: 'JHB' }).click().catch(() => {})
await wait(1200)

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
