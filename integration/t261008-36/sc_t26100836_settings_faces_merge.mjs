// sc_t26100836_settings_faces_merge.mjs — t261008-36 executor panel Settings tab
// carries Model routes + Project settings; More-views retires (grey-box L3,
// real browser + real served panel page + isolated stage console + API stubs).
//
// Intent (user-perceivable; sources = ticket user_request 261008 verbatim + the
// 261004 mock rows 'moved into the panel - Settings tab' + plan v3 anchors):
//   F1 The panel's Settings tab lists both entries — 'Model routes' and
//      'Project settings' (KI-051: semantic anchors data-wb-panel-face, not
//      copy literals; KI-055: captured in light AND dark).
//   F2 Opening Model routes renders the face inside the panel: one overlay in
//      the HOST document replacing the panel content — no second window, no
//      navigation, panel iframe stays mounted underneath (single layer).
//   F3 Back returns to the Settings tab with both rows still there.
//   F4 Opening Project settings renders the EXISTING modal chain's anchors
//      (data-wb-pmod-* danger affordances present; never executed here).
//   F5 The left column's More-views affordance is retired wholesale: no
//      More-views toggle, no Model Routes / Project Settings view icons.
//   F6 Journey hygiene: zero pageerror / console.error.
//
// Intent split (anti-duplication):
//   - t260929-22-executor-entry-console owns HOW the panel is reached (project
//     row entry); this scenario reuses that face as a precondition only.
//   - The providers face's internal content truth (its lists, its save flow,
//     loader validation) belongs to the providers-plugin scenarios / developer
//     L1 — this scenario asserts the face is MOUNTED inside the panel, nothing
//     about its data.
//   - The project-settings actions' semantics (remove/purge flow) are out of
//     scope: anchors must be PRESENT and unchanged, never clicked.
//
// Execution contract (t260904-12): stage/playwright/chromium missing =
// ENV_FAIL exit 2 (KI-036 family). Pre-implement red is the expected TDD
// signal; arbitrate/merge must be green. Red line: never touches 3099/7233.

import { ensureStageConsole } from '../lib_stage_console.mjs';
import { mkdirSync } from 'node:fs'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const BASE = (await ensureStageConsole()).base
const EVIDENCE_DIR = join(REPO, 'integration', 't261008-36', 'evidence')

const PROJ = 'entryproj'
const PROJ_NAME = 'Entry Project'

// ---------------------------------------------------------------- results

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`illegal status ${status} (pass/fail/env_fail/na)`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ' — ' + detail : ''}`)
}
function summarize() {
  const p = results.filter(r => r.status === 'pass').length
  const e = results.filter(r => r.status === 'env_fail').length
  const n = results.filter(r => r.status === 'na').length
  const f = results.filter(r => r.status === 'fail').length
  const allNa = results.length > 0 && n === results.length
  console.log(`SUMMARY pass=${p} fail=${f} env_fail=${e} na=${n}`)
  process.exit(f > 0 || allNa ? 1 : e > 0 ? 2 : 0)
}

// ---------------------------------------------------------------- helpers

async function dismissOverlays(page) {
  for (let i = 0; i < 5; i++) {
    const dialog = page.locator('[role="dialog"]').first()
    if (!(await dialog.count())) return
    const btn = dialog.locator('button:enabled').first()
    if (await btn.count()) await btn.click({ timeout: 3000 }).catch(() => {})
    else await page.keyboard.press('Escape').catch(() => {})
    await page.waitForTimeout(600)
  }
}

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

async function snap(page) {
  try {
    const txt = await page.evaluate(() => (document.body.textContent || '').slice(0, 200))
    return JSON.stringify(txt)
  } catch { return '(snapshot unavailable)' }
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'],
      { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}

async function loadPlaywright() {
  const candidates = ['playwright-core']
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs',
    'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) candidates.push(pathToFileURL(p).href)
  }
  for (const c of candidates) {
    try { return await import(c) } catch { /* next */ }
  }
  return null
}

async function launchBrowser(pw) {
  for (const opts of [{ channel: 'chrome', headless: true }, { headless: true }]) {
    try { return await pw.chromium.launch(opts) } catch { /* next */ }
  }
  return null
}

const json = (route, b) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(b) })

async function stubConsole(page) {
  // Low-priority fallback: everything reaches the REAL stage (real panel page,
  // real workbench bundle — this ticket's face IS the served DOM). High-priority
  // stubs only pin the ticket's fixture surface. The providers/admin routes APIs
  // are NOT stubbed: the overlay must mount the existing component regardless of
  // its data, and its data truth is another layer's object.
  await page.route('**/*', (route) => route.fallback())
  await page.route('**/sandbar-workbench/api/wf/projects', (route) =>
    json(route, { ok: true, result: { projects: [{ key: PROJ, name: PROJ_NAME, dirs: [] }], quarantined: [] } }))
  await page.route('**/sandbar-workbench/api/wf/tickets**', (route) =>
    json(route, { ok: true, result: { tickets: [] } }))
  await page.route('**/sandbar-watchdog/api/status**', (route) => json(route, { ok: true, projects: [] }))
  await page.route('**/sandbar-executor-panel/api/settings**', (route) =>
    json(route, { ok: true, declared: false, enabled: false, executor_session: '', file: null }))
  // Fixture project has no real sessions/concurrency/route table on the stage —
  // let those reads answer 200 with benign declared shapes (the page's own
  // degraded branches), so journey hygiene is not drowned in 4xx noise.
  await page.route(/\/sandbar-workbench\/api\/wf\/sessions/, (route) =>
    json(route, { entries: [] }))
  await page.route(/\/sandbar-workbench\/api\/wf\/concurrency/, (route) =>
    json(route, { holders: [], queue: [] }))
  await page.route(/\/sandbar-admin\/api\/routes/, (route) =>
    json(route, { ok: false, error: 'fixture project has no route table' }))
}

function panelFrame(page) {
  return page.frameLocator('iframe[src*="sandbar-executor-panel"]')
}

async function panelIframeInfo(page) {
  return page.evaluate(() => {
    const f = [...document.querySelectorAll('iframe')].find(f => /sandbar-executor-panel/.test(f.src || ''))
    return { src: f?.src ?? '', mounted: !!f }
  })
}

/** Open the executor panel from the project row (precondition face, t260929-22). */
async function openExecutorPanel(page) {
  const head = page.locator('.wb-group-head', { hasText: PROJ_NAME }).first()
  if (!(await waitFor(async () => (await head.count()) > 0, 12000))) {
    return `project group row for "${PROJ_NAME}" not rendered (projects stub not consumed?) @ ${await snap(page)}`
  }
  const entry = page.locator('[data-wb-executor-entry]').first()
  if (!(await entry.count())) return 'executor entry anchor not rendered on the project row'
  await entry.click({ force: true, timeout: 8000 })
  const ok = await waitFor(async () => {
    const info = await panelIframeInfo(page)
    return info.mounted && decodeURIComponent(info.src).includes(`project=${PROJ}`)
  }, 10000)
  if (!ok) return `executor panel iframe with ?project=${PROJ} did not mount @ ${await snap(page)}`
  return null
}

async function openSettingsTab(page) {
  // KI-051: locate by the declared data-tab anchor (the tab is a radio label),
  // assert by the face-entry anchors — not by copy literals.
  const tab = panelFrame(page).locator('[data-tab="settings"]').first()
  if (!(await tab.count())) return 'Settings tab anchor [data-tab="settings"] not found in the panel page'
  await tab.click({ timeout: 8000 })
  const ok = await waitFor(async () =>
    (await panelFrame(page).locator('[data-wb-panel-face]').count()) >= 2, 8000)
  if (!ok) return 'Settings pane does not list both face entries ([data-wb-panel-face] count < 2)'
  return null
}

// ---- F1 Settings tab lists both entries

async function scenarioSettingsRows(page, shot) {
  const err = await openSettingsTab(page)
  if (err) return err
  // Read the ROW text (the anchor is the Open button; the entry's readable name
  // lives on the row container — KI-051: assert the user-readable row).
  const names = await panelFrame(page).locator('[data-wb-panel-face]').evaluateAll(nodes =>
    nodes.map(n => {
      let el = n.parentElement
      while (el && (el.textContent || '').trim().length < 6 && el.parentElement) el = el.parentElement
      return (el?.textContent || '').trim()
    }))
  const routes = names.some(t => /model\s+routes/i.test(t))
  const settings = names.some(t => /project\s+settings/i.test(t))
  if (!routes) return `no entry readable as "Model routes" in the Settings pane (rows: ${JSON.stringify(names)})`
  if (!settings) return `no entry readable as "Project settings" in the Settings pane (rows: ${JSON.stringify(names)})`
  if (shot) {
    mkdirSync(EVIDENCE_DIR, { recursive: true })
    await page.screenshot({ path: join(EVIDENCE_DIR, shot), fullPage: false })
  }
  return null
}

// ---- F2/F3/F4 face open / back / project-settings anchors

async function scenarioOpenRoutesFace(page) {
  await panelFrame(page).locator('[data-wb-panel-face="routes"]').first().click({ timeout: 8000 })
  const ok = await waitFor(async () =>
    (await page.locator('[data-wb-face-overlay]').count()) === 1, 8000)
  if (!ok) return 'opening Model routes did not mount exactly one face overlay in the host document'
  const state = await page.evaluate(() => {
    const ov = document.querySelector('[data-wb-face-overlay]')
    const iframe = [...document.querySelectorAll('iframe')].find(f => /sandbar-executor-panel/.test(f.src || ''))
    return {
      overlayText: (ov?.textContent || '').trim().slice(0, 200),
      hasBack: !!ov && [...ov.querySelectorAll('button, [role="button"]')].some(b => /back/i.test(b.textContent || '')),
      iframeStillMounted: !!iframe,
      pages: 1,
      url: location.href,
    }
  })
  if (!state.iframeStillMounted) return 'the panel iframe was unmounted when the face opened (face must REPLACE panel content in one layer, not remove it)'
  if (!state.hasBack) return 'face overlay carries no Back affordance'
  if (state.overlayText.length < 1) return 'face overlay rendered empty'
  // single layer: no second window, no navigation away
  if (page.isClosed() || !(await page.evaluate(() => document.querySelectorAll('[data-wb-face-overlay]').length === 1))) {
    return 'face overlay count != 1 (stacking = two layers, the duplicity this ticket removes)'
  }
  await mkdirSync(EVIDENCE_DIR, { recursive: true })
  await page.screenshot({ path: join(EVIDENCE_DIR, 'face-routes-open.png'), fullPage: false })
  return null
}

async function scenarioBackToSettings(page) {
  const back = page.locator('[data-wb-face-overlay] [data-wb-face-back]').first()
  if (!(await back.count())) return 'Back affordance (data-wb-face-back) disappeared before it could be used'
  await back.click({ timeout: 8000 })
  const gone = await waitFor(async () => (await page.locator('[data-wb-face-overlay]').count()) === 0, 8000)
  if (!gone) return 'Back did not unmount the face overlay'
  const rows = await panelFrame(page).locator('[data-wb-panel-face]').count()
  if (rows < 2) return `Settings rows not restored after Back (count=${rows})`
  return null
}

async function scenarioProjectSettingsAnchors(page) {
  await panelFrame(page).locator('[data-wb-panel-face="project-settings"]').first().click({ timeout: 8000 })
  const ok = await waitFor(async () =>
    (await page.locator('[data-wb-face-overlay]').count()) === 1, 8000)
  if (!ok) return 'opening Project settings did not mount exactly one face overlay'
  const state = await page.evaluate(() => {
    const ov = document.querySelector('[data-wb-face-overlay]')
    const pmodAnchors = ov ? [...ov.querySelectorAll('*')]
      .flatMap(el => [...el.attributes])
      .filter(a => a.name.startsWith('data-wb-pmod'))
      .map(a => a.name) : []
    const text = (ov?.textContent || '')
    return {
      pmodAnchors: [...new Set(pmodAnchors)],
      hasDanger: /remove/i.test(text),
      overlays: document.querySelectorAll('[data-wb-face-overlay]').length,
    }
  })
  if (state.overlays !== 1) return `overlay count ${state.overlays} != 1 after opening Project settings`
  if (state.pmodAnchors.length === 0) return 'project-settings face shows no data-wb-pmod-* anchors — the existing modal chain was silently simplified'
  if (!state.hasDanger) return 'project-settings face shows no Remove affordance text (danger paths must stay reachable and unchanged)'
  await mkdirSync(EVIDENCE_DIR, { recursive: true })
  await page.screenshot({ path: join(EVIDENCE_DIR, 'face-project-settings-open.png'), fullPage: false })
  return null
}

// ---- F5 More-views retirement (whole affordance, R6 grain)

async function scenarioMoreViewsRetired(page) {
  const state = await page.evaluate((projName) => {
    const toggles = document.querySelectorAll('[data-wb-more-views]').length
    const labelled = [...document.querySelectorAll('[title], [aria-label]')]
      .filter(el => /more\s+views|fewer\s+views/i.test(el.getAttribute('title') || '') || /more\s+views|fewer\s+views/i.test(el.getAttribute('aria-label') || '')).length
    const heads = [...document.querySelectorAll('.wb-group-head')]
    const head = heads.find(h => (h.textContent || '').includes(projName))
    const group = head?.parentElement
    const icons = group ? [...group.querySelectorAll('.wb-view-icon')].map(i => (i.getAttribute('title') || '') + '|' + (i.getAttribute('aria-label') || '')) : null
    return { toggles, labelled, icons }
  }, PROJ_NAME)
  if (state.toggles !== 0) return `More-views toggle still present (${state.toggles} [data-wb-more-views]) — keeping the second door is the duplicity this ticket removes`
  if (state.labelled !== 0) return `a "More views"/"Fewer views" labelled affordance still exists (${state.labelled})`
  if (state.icons === null) return 'fixture project group disappeared (cannot run the icon retirement leg)'
  const stale = state.icons.filter(l => /model\s+routes|project\s+settings/i.test(l))
  if (stale.length) return `retired view icons still rendered in the project group: ${JSON.stringify(stale)}`
  return null
}

// ---- F6 hygiene

async function scenarioHygiene(pageErrors, consoleErrors) {
  if (pageErrors.length) return `pageerror(s): ${JSON.stringify(pageErrors.slice(0, 3))}`
  if (consoleErrors.length) return `console.error(s): ${JSON.stringify(consoleErrors.slice(0, 3))}`
  return null
}

// ---------------------------------------------------------------- main

async function run() {
  const ctx = { browser: null, pw: null }
  try { ctx.pw = await loadPlaywright() } catch { /* treated as missing below */ }
  if (!ctx.pw) {
    record('S0 playwright', 'env_fail', 'playwright-core unresolvable (KI-036 family)')
    summarize()
  }
  ctx.browser = await launchBrowser(ctx.pw)
  if (!ctx.browser) {
    record('S0 chromium', 'env_fail', 'no headless chromium/chrome launchable')
    summarize()
  }

  const bctx = await ctx.browser.newContext()
  const pageErrors = []
  const consoleErrors = []
  const badResponses = []
  const page = await bctx.newPage()
  page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
  page.on('response', r => { if (r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`.slice(0, 200)) })
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200) + ' @' + (m.location()?.url || '').split('/').pop() + ':' + (m.location()?.lineNumber ?? '?')) })

  await stubConsole(page)
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await dismissOverlays(page)
  await page.waitForTimeout(3000)
  await dismissOverlays(page)

  const failWith = async (name, e) => record(name, 'fail', `${String(e).slice(0, 160)} @ ${await snap(page)}`)
  const run1 = async (name, fn) => {
    try {
      const err = await fn(page)
      if (err) record(name, 'fail', err)
      else record(name, 'pass')
    } catch (e) { await failWith(name, e) }
  }

  const openErr = await openExecutorPanel(page)
  run1('F0 fixture: project row opens the executor panel', async () => openErr)

  await run1('F1 Settings tab lists Model routes and Project settings (light)', (p) => scenarioSettingsRows(p, 'settings-faces-light.png'))
  await run1('F2 Model routes opens inside the panel (one overlay, iframe stays)', scenarioOpenRoutesFace)
  await run1('F3 Back returns to the Settings rows', scenarioBackToSettings)
  await run1('F4 Project settings opens with existing pmod danger anchors', scenarioProjectSettingsAnchors)
  // Close the face so F5 sees the plain left column.
  await page.evaluate(() => { location.hash = '' }).catch(() => {})
  const backBtn = page.locator('[data-wb-face-overlay] [data-wb-face-back]').first()
  if (await backBtn.count()) await backBtn.click({ timeout: 3000 }).catch(() => {})
  await run1('F5 More-views affordance retired wholesale', scenarioMoreViewsRetired)

  // KI-055 dark leg. Measured on this stage: the platform shell defines NO
  // --dsw-alias-bg-base (computed ''), so the HOST-side dark resolution
  // (consoleThemeName -> ?theme=) is unobservable here regardless of
  // prefers-color-scheme — that seam belongs to t261003-09/developer L1. The
  // user-perceivable KI-055 face this ticket owes is: both entries readable on
  // the panel page IN DARK. The panel page honors ?theme=dark itself, so the
  // dark capture is taken on the panel page directly (deep link), with a
  // luminance check.
  await run1('F7 panel URL theme param is a defined two-value face', async () => {
    const info = await panelIframeInfo(page)
    if (!/theme=(light|dark)/.test(info.src)) {
      return `panel iframe src carries no defined theme param (src: ${info.src})`
    }
    return null
  })
  await run1('F8 Settings entries readable in DARK (panel ?theme=dark, KI-055 capture)', async () => {
    const dark = await bctx.newPage()
    try {
      await dark.route('**/*', (route) => route.fallback())
      await dark.route(/\/sandbar-workbench\/api\/wf\/(projects|tickets)/, (route) =>
        json(route, { ok: true, result: { projects: [{ key: PROJ, name: PROJ_NAME, dirs: [] }], tickets: [], quarantined: [] } }))
      await dark.goto(`${BASE}/sandbar-executor-panel/?project=${PROJ}&theme=dark`, { waitUntil: 'domcontentloaded', timeout: 30000 })
      const tab = dark.locator('[data-tab="settings"]').first()
      if (!(await tab.count())) return 'no [data-tab=settings] anchor on the panel page (dark leg)'
      await tab.click({ timeout: 8000 })
      const ok = await waitFor(async () =>
        (await dark.locator('[data-wb-panel-face]').count()) >= 2, 8000)
      if (!ok) return 'dark panel page does not list both face entries'
      const names = (await dark.locator('[data-wb-panel-face]').evaluateAll(nodes =>
        nodes.map(n => { let el = n.parentElement; while (el && (el.textContent || '').trim().length < 6 && el.parentElement) el = el.parentElement; return (el?.textContent || '').trim() })))
      if (!names.some(t => /model\s+routes/i.test(t)) || !names.some(t => /project\s+settings/i.test(t))) {
        return `dark rows unreadable: ${JSON.stringify(names)}`
      }
      const lum = await dark.evaluate(() => {
        const bg = getComputedStyle(document.body).backgroundColor || getComputedStyle(document.documentElement).backgroundColor
        const m = bg.match(/\d+/g) || []
        const [r, g, b] = m.map(Number)
        return (0.2126 * (r || 255) + 0.7152 * (g || 255) + 0.0722 * (b || 255)) / 255
      })
      if (lum >= 0.5) return `dark panel page body is not dark (luminance ${lum.toFixed(2)})`
      mkdirSync(EVIDENCE_DIR, { recursive: true })
      await dark.screenshot({ path: join(EVIDENCE_DIR, 'settings-faces-dark.png'), fullPage: false })
      return null
    } finally {
      await dark.close().catch(() => {})
    }
  })
  await run1('F9 journey hygiene: zero pageerror / console.error', () => {
    if (pageErrors.length) return `pageerror(s): ${JSON.stringify(pageErrors.slice(0, 3))}`
    if (consoleErrors.length) return `console.error(s): ${JSON.stringify(consoleErrors.slice(0, 3))}; >=400 responses: ${JSON.stringify(badResponses.slice(0, 6))}`
    return null
  })

  summarize()
}

run().catch(async (e) => {
  record('S9 runner', 'fail', String(e).slice(0, 300))
  summarize()
})
