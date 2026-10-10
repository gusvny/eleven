/**
 * t261009-44-shot.mjs — the Certification tab's UI evidence channel (runs like
 * shots.mjs: isolated harness on port 0, zero 3099/7233, real Chromium).
 *
 * Seeds a throwaway project store (the same engine-shaped rows the reader test
 * uses), boots the panel harness against it, opens ?project=certproj, clicks
 * the Certification tab, and captures light + dark screenshots of the tab into
 * .sandbar/screenshots/. Full-termination cleanup on every path.
 *
 * Usage: node tests/t261009-44-shot.mjs   (cwd = repo root or the plugin dir)
 */
import { createRequire } from 'node:module'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const pluginDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repo = resolve(pluginDir, '../../..')
const outDir = join(repo, '.sandbar/screenshots')
mkdirSync(outDir, { recursive: true })

function findPlaywrightCore() {
  let dir = pluginDir
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found: expected server/ui-check/node_modules in this checkout or a sibling of the lane root')
}
const playwright = createRequire(import.meta.url)(findPlaywrightCore())

// ---- seed the throwaway project store with the engine-shaped rows ----
const home = mkdtempSync('/tmp/ep-cert-shot-')
const P = 'certproj'
const dev = join(home, P, 'data', 'develop')
const ledger = join(home, P, 'ledger')
const tick = join(home, P, 'data', 'tickets', 't261009-18')
for (const d of [dev, ledger, tick]) mkdirSync(d, { recursive: true })
writeFileSync(join(dev, 'lines.json'), JSON.stringify([
  { line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host', repositories: [{ name: 'sandbar', branch: 'develop-buffer' }] },
]))
const rows = [
  { kind: 'landing', id: 'ldg-1', ticket: 't261009-18', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '396b221a' }], actor: 'dev', at: Date.now() - 3600_000, seq: 1 },
  { kind: 'landing', id: 'ldg-2', ticket: 't261009-20', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '22233344' }], actor: 'dev', at: Date.now() - 1800_000, seq: 2 },
  { kind: 'landing', id: 'ldg-3', ticket: 't261009-21', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '22233344' }], actor: 'dev', at: Date.now() - 1200_000, seq: 3 },
  { kind: 'certification', id: 'cert-A', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '396b221a' }], run: 'run-green', booked_red: 'known-red@test', judged_by: 'pytest', at: Date.now() - 3000_000, seq: 4 },
  { kind: 'certification', id: 'cert-B', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '22233344' }], run: 'run-red', booked_red: 'known-red@test', judged_by: 'pytest', at: Date.now() - 900_000, seq: 5 },
  { kind: 'freeze', id: 'frz-A', line: 'develop-buffer', cause: 'cert-B', at: Date.now() - 900_000, seq: 6 },
  { kind: 'freeze_change', id: 'fch-1', freeze: 'frz-A', change: 'attribution', by: 'patrol', reason: 'red round cert-B', value: 't261009-20-guard-route', at: Date.now() - 800_000, seq: 7, line: 'develop-buffer' },
]
writeFileSync(join(ledger, 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
const runs = [
  { v: 'run-ledger-v1', id: 'run-green', repos: [{ repo: 'sandbar', revision: '396b221a' }], suite: 'full', source: 'scheduled', env_fp: 'x', conc_width: 1, pool: '', started_at: Date.now() - 3100_000, duration_s: 60, cases: { ran: 498, passed: 498, failed: 0, env_failed: 0 } },
  { v: 'run-ledger-v1', id: 'run-red', repos: [{ repo: 'sandbar', revision: '22233344' }], suite: 'full', source: 'scheduled', env_fp: 'x', conc_width: 1, pool: '', started_at: Date.now() - 950_000, duration_s: 90, cases: { ran: 498, passed: 496, failed: 2, env_failed: 0 } },
]
const runsPath = join(home, 'runs.jsonl')
writeFileSync(runsPath, runs.map((r) => JSON.stringify(r)).join('\n') + '\n')
for (const [tid, title, epic] of [['t261009-18', 'Land a proven lane onto a declared line', 'develop-buffer'], ['t261009-20', 'Guard the route change so pre-change histories replay', 'engine-hardening'], ['t261009-21', 'A ticket that is only waiting holds nothing', 'develop-buffer']]) {
  const d = join(home, P, 'data', 'tickets', tid)
  mkdirSync(d, { recursive: true })
  writeFileSync(join(d, 'archive.json'), JSON.stringify({ schema: 1, ticket_id: tid, meta: { title, epic } }))
}

// ---- boot the harness against the seeded store ----
process.env.SANDBAR_PROJECTS_DIR = home
process.env.SANDBAR_RUNS_LEDGER = runsPath
const { startPluginHarness } = await import(join(pluginDir, 'harness.mjs'))
const H = await startPluginHarness({ panelDir: mkdtempSync('/tmp/ep-cert-shot-panel-'), watchdogDir: mkdtempSync('/tmp/ep-cert-shot-wd-') })
const KEY = P

let browser
try {
  try { browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { browser = await playwright.chromium.launch({ headless: true }) }
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 950 } })
  const page = await ctx.newPage()
  page.on('console', (m) => { if (m.type() === 'error') console.log('console-error:', m.text().slice(0, 200)) })
  page.on('pageerror', (e) => console.log('pageerror:', String(e).slice(0, 300)))
  await page.goto(H.base + '/sandbar-executor-panel?project=' + KEY)
  await page.click('label[for="t-certification"]')
  await page.waitForFunction(() => (document.getElementById('certBody') || {}).innerHTML !== '', { timeout: 15000 }).catch(() => {})
  console.log('certBody html head:', (await page.evaluate(() => (document.getElementById('certBody') || {}).innerHTML || 'EMPTY')).slice(0, 400))
  await page.waitForSelector('#certBig', { timeout: 15000 })
  const state = await page.textContent('#certBig')
  console.log('tab state word:', state)
  await page.screenshot({ path: join(outDir, 't261009-44-certification-light.png'), fullPage: true })
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.waitForTimeout(300)
  await page.screenshot({ path: join(outDir, 't261009-44-certification-dark.png'), fullPage: true })
  console.log('screenshots written to', outDir)
  await ctx.close()
} finally {
  if (browser) await browser.close().catch(() => {})
  await H.close().catch(() => {})
  rmSync(home, { recursive: true, force: true })
}
