// capture-v426.mjs — admin CRUD module screenshots (WO v4.26 §3.6, one per sub-screen).
// FastAPI :8000 serving /mes-app/, migrations 0010 applied + spec_options/rules/lookups seeded,
// autologin = admin → the admin nav + module render. PNGs → docs/screenshots/v4.26/.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://127.0.0.1:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/v4.26')
mkdirSync(OUT, { recursive: true })
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
const page = await ctx.newPage()
const shot = async (name) => { try { await page.screenshot({ path: resolve(OUT, name) }); console.log(`✓ ${name}`) } catch (e) { console.log(`✗ ${name} ${e.message}`) } }

// Load the SPA root first so the React app autologins (a direct deep-link hits the auth guard
// before autologin can run). Then navigate within the SPA via the admin nav + sidebar links.
await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
await wait(2400)
await page.click('button[title="Hide demo tooltips"]').catch(() => {})
await page.click('a[href="/mes-app/admin/spec-options"]').catch(() => {})  // the admin nav entry
await wait(1600)
await shot('admin-spec-options.png')

for (const [res, name] of [['rules', 'admin-rules'], ['lookups', 'admin-lookups'], ['price-overrides', 'admin-price-overrides']]) {
  await page.click(`a[href="/mes-app/admin/${res}"]`).catch(() => {})
  await wait(1300)
  await shot(`${name}.png`)
}

// open the create modal on the rules screen to show the form + formula validate
await page.click('a[href="/mes-app/admin/rules"]').catch(() => {})
await wait(900)
await page.locator('button', { hasText: /^\+ New$/ }).first().click().catch(() => {})
await wait(700)
await shot('admin-rules-create-modal.png')

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
