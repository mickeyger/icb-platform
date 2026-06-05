// capture-v422.mjs — Planning Board source-column fork + workflow screenshots (WO v4.22).
//
// Same pattern as capture-v421.mjs. Point at a permitted autologin origin serving the
// built SPA against the live backend (FastAPI at :8000 serving /mes-app/, reading the
// v4.22-loaded icb_mes). Captures the source badge + filter chip (the §3.4 deliverable)
// and a slot detail. Writes PNGs to docs/screenshots/v4.22/.
//   node scripts/capture-v422.mjs              # MES_BASE defaults to http://127.0.0.1:8000
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://127.0.0.1:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.22')
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

// ── Planning Board — source badges (WB) + the All/Quote-born/Workbook filter chip ──
await page.click('a[href="/mes-app/planning"]').catch(() => {})
await wait(1800)
await shot(page, 'planning-board-source-badges.png')
await shot(page, 'planning-board-fullpage.png', { fullPage: true })

// ── Filter applied: Workbook ──
await page.locator('button', { hasText: /^Workbook$/ }).first().click().catch(() => {})
await wait(700)
await shot(page, 'planning-filter-workbook.png')
// ── Filter applied: Quote-born (board dims/empties — all current jobs are workbook) ──
await page.locator('button', { hasText: 'Quote-born' }).first().click().catch(() => {})
await wait(700)
await shot(page, 'planning-filter-quote-born.png')
await page.locator('button', { hasText: /^All$/ }).first().click().catch(() => {})
await wait(500)

// ── Slot detail — click a scheduled job in the grid (chassis state + receipt tick) ──
await shot(page, 'planning-slot-detail.png', async () => {})
await page.locator('table button').first().click().catch(() => {})
await wait(900)
await shot(page, 'planning-slot-detail.png')

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
