// capture-v419.mjs — headless screenshots for WO v4.19 (Phase 2C-3, Costings rewire).
//
// Same pattern as capture-v418.mjs. Point at a permitted autologin origin serving
// the built SPA against a live backend (FastAPI at :8000 serving /mes-app/) and it
// writes PNGs to docs/screenshots/v4.19/. Set up the accept states first (a fully
// accepted calc + an accept-only "partial" calc) so the dashboard shows them.
//
// Usage (from frontend/):
//   npm i -D playwright && npx playwright install chromium
//   node scripts/capture-v419.mjs            # MES_BASE defaults to http://localhost:8000

import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://localhost:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.19')
mkdirSync(OUT, { recursive: true })

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(page, name, fn) {
  try {
    const target = fn ? await fn() : page
    await (target ?? page).screenshot({ path: resolve(OUT, name) })
    console.log(`✓ ${name}`)
  } catch (e) {
    console.log(`✗ ${name} — ${e.message}`)
  }
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 } })
const page = await ctx.newPage()

await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
await wait(1500)
await page.click('button[title="Hide demo tooltips"]').catch(() => {})

// ── Costings dashboard (mixed stages + the set-up accept states) ───────────────
await page.click('a[href="/mes-app/costings"]').catch(() => {})
await wait(1200)
await shot(page, 'costings-dashboard-mixed-stages.png')
await shot(page, 'accept-partial-retry.png', () => page.locator('tr', { hasText: 'Q-32898' }).first())
await shot(page, 'accept-success.png', () => page.locator('tr', { hasText: 'Q-32897' }).first())

// ── Costing detail (lifecycle + live timeline from /api/production-jobs/{id}/timeline) ──
await shot(page, 'costing-detail-timeline.png', async () => {
  await page.locator('tr', { hasText: 'Q-32897' }).first().click()
  await wait(1000)
  return page
})

// ── Pre-Job sign-off section (a Pre-Job Sent costing) ──────────────────────────
await shot(page, 'signoff-section.png', async () => {
  await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
  await wait(800)
  await page.click('a[href="/mes-app/costings"]').catch(() => {})
  await wait(1000)
  await page.locator('tr', { hasText: 'Pre-Job Sent' }).first().click()
  await wait(1000)
  return page
})

// ── Planning board (live ack candidates + grid) + the ack panel ────────────────
await page.click('a[href="/mes-app/planning"]').catch(() => {})
await wait(1200)
await shot(page, 'planning-board-live.png')
await shot(page, 'planning-ack-from-slot.png', async () => {
  await page.locator('button', { hasText: 'Awaiting Planning ack' }).first().click()
  await wait(700)
  return page
})

// ── Branch switch re-scopes the costings dashboard ─────────────────────────────
await shot(page, 'branch-switch-dashboard-refetch.png', async () => {
  await page.click('a[href="/mes-app/costings"]').catch(() => {})
  await wait(1000)
  await page.click('button[title^="Switch active branch"]').catch(() => {})
  await wait(400)
  await page.locator('[role="menu"] button', { hasText: 'CPT' }).click().catch(() => {})
  await wait(1500)
  return page
})

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
