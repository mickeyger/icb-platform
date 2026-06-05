// capture-v421.mjs — Planning Board screenshot for WO v4.21 (Phase 2D-2, workbook ETL).
//
// Same pattern as capture-v418/v419.mjs. Point at a permitted autologin origin serving
// the built SPA against the live backend (FastAPI at :8000 serving /mes-app/, reading the
// v4.21-loaded icb_mes). The acceptance gate is the Planning Board showing the real
// workbook-imported jobs (production-jobs-spine). Writes PNGs to docs/screenshots/v4.21/.
//
// Usage (from frontend/):
//   node scripts/capture-v421.mjs              # MES_BASE defaults to http://127.0.0.1:8000
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://127.0.0.1:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.21')
mkdirSync(OUT, { recursive: true })
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(page, name, { fullPage = false } = {}) {
  try {
    await page.screenshot({ path: resolve(OUT, name), fullPage })
    console.log(`✓ ${name}`)
  } catch (e) {
    console.log(`✗ ${name} — ${e.message}`)
  }
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
const page = await ctx.newPage()

await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
await wait(1800)
await page.click('button[title="Hide demo tooltips"]').catch(() => {})

// ── Planning Board — the real workbook-imported jobs (the v4.21 acceptance gate) ──
await page.click('a[href="/mes-app/planning"]').catch(() => {})
await wait(1800)
await shot(page, 'planning-board-workbook-jobs.png')
await shot(page, 'planning-board-fullpage.png', { fullPage: true })

// ── Costings dashboard (calculations-spine: the 6 real UAT quotes) for context ───
await page.click('a[href="/mes-app/costings"]').catch(() => {})
await wait(1500)
await shot(page, 'costings-dashboard.png')

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
