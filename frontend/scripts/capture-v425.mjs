// capture-v425.mjs — read-only BOM rules-engine admin inspection (WO v4.25 §3.7).
//
// Same pattern as capture-v422.mjs. Point at a permitted autologin origin serving the built
// SPA against the live backend (FastAPI :8000 serving /mes-app/, with migration 0009 applied +
// the 9 rules / 6 lookups seeded). Autologin mints the admin user → the admin-gated "Rules" nav
// item shows → the inspector renders the rules / lookups / overrides tables. PNGs → docs/screenshots/v4.25/.
//   node scripts/capture-v425.mjs              # MES_BASE defaults to http://127.0.0.1:8000
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://127.0.0.1:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.25')
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

// ── Admin → Rules (admin-gated nav; autologin user is admin) ──
await page.click('a[href="/mes-app/admin/rules"]').catch(() => {})
await wait(1500)
await shot(page, 'admin-bom-rules.png')
await shot(page, 'admin-bom-rules-fullpage.png', { fullPage: true })

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
