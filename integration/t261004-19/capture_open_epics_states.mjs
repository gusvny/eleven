// capture_open_epics_states.mjs — t261004-19 acceptance-walkthrough evidence
// (one-shot, not a registered scenario): the Grants page "Open tickets in
// these epics" section with the declaration as the host left it —
// engine-hardening authorized (switch on), localization not (switch off) —
// in light and dark, BEFORE any save. Complements the implement-stage capture
// (whose screenshots show the post-save state where both are on).
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { createRequire } from 'node:module'

const REPO = resolve(import.meta.dirname, '../..')
const OUT = join(REPO, '.sandbar', 'evidence')
mkdirSync(OUT, { recursive: true })

function findPlaywrightCore() {
  let dir = REPO
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  throw new Error('playwright-core not found')
}
const require = createRequire(import.meta.url)
const playwright = require(findPlaywrightCore())
async function launchBrowser() {
  try { return await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
  catch { return await playwright.chromium.launch({ headless: true }) }
}

const wd = mkdtempSync(join(tmpdir(), 't26100419-oo-'))
const KEY = 'evproj'
const epicsDir = join(wd, 'epics')
mkdirSync(epicsDir, { recursive: true })
writeFileSync(join(epicsDir, 'engine-hardening.md'),
  '# 立项单\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `engine-hardening` |\n| 状态 | 已立项（执行中） |\n', 'utf8')
writeFileSync(join(epicsDir, 'localization.md'),
  '# 立项单\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `localization` |\n| 状态 | 草稿（设计稿已成） |\n', 'utf8')
process.env.SANDBAR_EPICS_DIR = epicsDir
process.env.SANDBAR_WATCHDOG_DIR = wd
process.env.SANDBAR_PROJECTS_DIR = wd
process.env.SANDBAR_PANEL_DIR = wd

const mod = await import('file://' + join(REPO, 'server/plugins/executor-panel/harness.mjs'))
const H = await mod.startHarness({ port: 0, panelDir: wd, watchdogDir: wd, workbenchBase: 'http://127.0.0.1:9' })
// Host already authorized engine-hardening only: the saved declaration on disk
// is the pre-journey state the section must reflect (one on, one off).
const decl = { version: 1, grants: { 'open-ticket': true }, executor_sessions: ['sess-ev-1'], open_ticket_epics: ['engine-hardening'], open_ticket_cap: 3, updated_by: 'host', updated_at: Date.now() }
mkdirSync(join(wd, KEY), { recursive: true })
writeFileSync(join(wd, KEY, 'executor-grants.json'), JSON.stringify(decl, null, 2), 'utf8')

const browser = await launchBrowser()
try {
  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage()
    page.setDefaultTimeout(15000)
    await page.goto(`${H.base}/sandbar-executor-panel?project=${KEY}&theme=${theme}`)
    await page.waitForTimeout(400)
    const out = join(OUT, `t26100419-open-epics-${theme}-one-on-one-off.png`)
    await page.screenshot({ path: out, fullPage: false })
    console.log('screenshot', theme, '->', out)
    const sec = await page.locator('#openEpics').innerText()
    console.log('section text:', sec.replace(/\n+/g, ' | '))
    const states = await page.locator('#openEpics .sw.grant[data-epic]').evaluateAll(
      (els) => els.map((e) => `${e.dataset.epic}=${e.dataset.on}`))
    console.log('switch states:', states.join(' '))
    await page.close()
  }
} finally {
  await browser.close().catch(() => {})
  await H.close?.().catch?.(() => {})
  // L8 tmp hygiene: reclaim the scratch dir on every exit path
  rmSync(wd, { recursive: true, force: true })
}
console.log('done')
