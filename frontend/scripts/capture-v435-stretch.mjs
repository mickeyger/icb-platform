// capture-v435-stretch.mjs — WO v4.35 §3.3b supplementary runbook frames (the 2 new bay states + the
// auto-merge prompt). FastAPI :8000 serving /mes-app/, migration 0024 applied, autologin = admin.
//
// PRE-REQ: stage one ready_to_merge + one pre_assembly bay first, e.g. (against the canonical reseed):
//   python -m scripts.seed_v4_35_demo_reset --commit            # canonical
//   python -c "from app.database import SessionLocal; from app.services import chassis as s; \
//     d=SessionLocal(); b=s.assembly_bays_utilisation(d); \
//     r=next(x for x in b if x.state=='awaiting_attachment'); s.record_panels_arrived_in_bay(d, r.occupant_job_id, r.id); \
//     e=next(x for x in b if x.state=='empty'); \
//     j=__import__('app.models.mes',fromlist=['ProductionJob']); \
//     pj=d.query(j.ProductionJob).filter(j.ProductionJob.status=='in_production').first(); \
//     s.record_panels_arrived_in_bay(d, pj.id, e.id)"            # 1 ready_to_merge + 1 pre_assembly
// Then run this script; afterwards re-run the reset to restore canonical. PNGs → docs/screenshots/runbook/.
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.MES_BASE || 'http://127.0.0.1:8000'
const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(__dirname, '../../docs/screenshots/runbook')
mkdirSync(OUT, { recursive: true })
const wait = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1500, height: 950 } })
const page = await ctx.newPage()
const shot = async (name, target) => {
  try { await (target || page).screenshot({ path: resolve(OUT, name) }); console.log(`✓ ${name}`) }
  catch (e) { console.log(`✗ ${name} ${e.message}`) }
}

await page.goto(`${BASE}/mes-app/`, { waitUntil: 'networkidle' })
await wait(2400)
await page.click('button[title="Hide demo tooltips"]').catch(() => {})
await page.getByTestId('nav-planning').click().catch(() => {})
await page.getByTestId('bay-model').waitFor({ timeout: 15000 }).catch(() => {})
await wait(1200)

// 09 — the bay lanes showing the 6-state mix (pre_assembly + ready_to_merge among the others).
await page.getByTestId('bay-model').scrollIntoViewIfNeeded().catch(() => {})
await shot('09-planning-6-state-bays.png', page.getByTestId('bay-model'))

// 10 — focus the ready_to_merge tile (violet, ↔ Merge + Mark-body-attached affordance).
const rtm = page.locator('[data-testid="assembly-bay"][data-bay-state="ready_to_merge"]').first()
await rtm.scrollIntoViewIfNeeded().catch(() => {})
await shot('10-planning-ready-to-merge-tile.png', rtm)

// 11 — the auto-merge prompt (click the ready_to_merge tile's Mark-body-attached button).
await rtm.getByTestId('merge-button').click().catch(() => {})
await wait(600)
await shot('11-planning-auto-merge-prompt.png', page.getByTestId('merge-prompt'))

await browser.close()
console.log(`\nScreenshots → ${OUT}`)
