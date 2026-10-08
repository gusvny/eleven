#!/usr/bin/env node
// t261008-21 scenario: the sidebar Settings popover is retired and the closed
// dev-lane dwell window is pinned at 24 hours (host order 261008 option A).
// (Grey-box L3, browser-free pool; harness mirrors t261008-02 / t260915-19.)
//
// User story: the host opens the workbench. The bottom of the left column used
// to carry a gear ("Settings") that opened a popover with a "Sandbar dwell"
// number input and a placeholder line about a quiet in-progress threshold
// (M2c). Option A retires the whole popover; the dwell window stays real and
// fixed at 24 hours — a closed dev-lane ticket disappears from the left column
// 24 hours after it closes, with no knob left to change that. A user who typed
// a custom value into localStorage before the retirement must not end up with
// that hidden value still steering the now-knobless window.
//
// Layers (mirrors the two-layer family):
//   S0 build-contract (pure node, runs anywhere): twin shipped bundles in sync
//      (KI-052) and the popover literals absent from the shipped bundle — the
//      rendered face is fully determined by the bundles.
//   S1 real browser DOM assertions with API-boundary stubs only (browser,
//      React and bundles all real; production 3099 never touched), under light
//      AND dark (KI-055 theme matrix), each leg seeded with a STALE dwell value
//      (999) in localStorage.
// Three states (t260912 contract): last line SUMMARY pass/fail/env_fail/na;
// fail>0 or all-na = exit 1; env_fail>0 = exit 2. Pre-implement red is the
// expected TDD signal; the entry must be green at arbitrate/merge.
//
// Intent split (anti-duplication): the window rule's unit truth table, the
// close_ts->created fallback and the source-anchor faces are the developer L1
// battery (tests/t261008-21-sidebar-dwell-pinned.mjs); this entry pins what a
// READER sees after a real render: no gear, no popover, footer not reflowed,
// stale localStorage not steering the window, and the inspection row not
// passing through the client window (two-window split, t260915-19/-16 own the
// sort/triage contracts — only the non-filtering face is re-asserted here as a
// regression guard). playwright-core/chromium/console missing = ENV_FAIL exit 2
// (KI-036 family).

import { bootConsole, teardownOnExit, makeRegistryRoot, writeProjectEntry, makeTicketStub, benchAuthUrl, REPO_ROOT } from '../t260904-17/lib_fix17.mjs';
import { readFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'

const REPO = REPO_ROOT
const OUT_DIR = join(REPO, 'integration', 't261008-21', 'out')
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'sidebar.tsx')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
// Ticket-visible literals of the retired popover (anchored, not whole sentences).
const POPOVER_LITERALS = ['Sandbar dwell', 'Quiet in-progress threshold', 'wb-sb-setpop', 'setSandbarHours']
const STALE_KEY = 'sandbar-workbench-sandbar-v1'
const STALE_VALUE = '999'

let BASE = ''
let bench = null
try {
  const projectsRoot = makeRegistryRoot('t261008-21-registry-')
  writeProjectEntry(projectsRoot, 'fixture-alpha', 'fixture-alpha', ['/tmp/fx-alpha'])
  bench = await bootConsole(projectsRoot, makeTicketStub())
  BASE = bench.base
  await benchAuthUrl(bench)
  teardownOnExit(bench.teardown)
} catch (e) {
  console.log(`[ENV_FAIL] stage console unavailable: ${String(e).slice(0, 200)}`)
  console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
  process.exit(2)
}

const results = []
const STATUSES = new Set(['pass', 'fail', 'env_fail', 'na'])
function record(name, status, detail = '') {
  if (!STATUSES.has(status)) throw new Error(`bad status word ${status}`)
  results.push({ name, status, detail })
  console.log(`[${status.toUpperCase()}] ${name}${detail ? ` — ${detail}` : ''}`)
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

// ---------------------------------------------------------------- fixtures

const PROJ_A = 'fixture-alpha'
const NOW_S = Math.floor(Date.now() / 1000)
const H = 3600
const FRESH_ID = 'devfixa2101fresh'   // closed 1h ago  -> must render
const STALE_ID = 'devfixa2102stale'   // closed 25h ago -> must be filtered
const EDGE_ID = 'devfixa2103edge'     // closed exactly 24h ago -> filtered (strict <)
const INS_OLD_ID = 'insfixa2104old'   // inspection closed 30h ago -> must STILL render (engine R8 window owns it)

function devRow(id, title, closeTs, status = 'closed') {
  return {
    id, role: 'developer', status, title,
    workflow: 'dev-lane', stage: 'settle', stage_state: 'closed',
    handoff_count: 0, pending_count: 0, worktree: '', updated: '—',
    updated_ts: closeTs, created: closeTs - 86400, close_ts: closeTs,
    engine: 'template-as-code-v2', exec_status: 'RUNNING',
  }
}
const DEV_ROWS = [
  devRow(FRESH_ID, 'alpha fresh closed ticket', NOW_S - 1 * H),
  devRow(STALE_ID, 'alpha stale closed ticket', NOW_S - 25 * H),
  devRow(EDGE_ID, 'alpha edge closed ticket', NOW_S - 24 * H),
  devRow(FRESH_ID + 'open', 'alpha running ticket', 0, 'dispatched'),
]
function insRow(over) {
  return {
    id: '', kind: 'inspection', engine: 'inspection', project: PROJ_A, epic: '',
    title: '', template: 'inspection-lite', instance_id: 'fixture-alpha', period: '20261008',
    stage: 'close', stage_state: 'closed', status: 'closed', decision: '',
    findings: { high: 0, med: 0, low: 0, total: 0 }, heartbeat: false, report_path: '',
    awaiting_gate: false, human_gate: null, blocked_reason: '', gate_error: '',
    created: NOW_S - 31 * H, updated: '—', updated_ts: NOW_S - 30 * H,
    paused: false, paused_phase: '', handoff_count: 0, pending_count: 0,
    worktree: '', workspace: null, role: null, proposal_id: '', workflow: '',
    close_ts: NOW_S - 30 * H, authz_active: 0, exec_status: 'RUNNING',
    ...over,
  }
}
const INS_ROWS = [insRow({ id: INS_OLD_ID, title: 'Inspection fixture-alpha · closed 30h ago' })]
const WORKFLOWS = [{
  id: 'dev-lane', name: 'dev lane', lane: 'worktree',
  stages: [
    { id: 'implement', name: 'implement', role: 'developer', parts: ['agent'] },
    { id: 'settle', name: 'settle', role: 'developer', parts: ['agent'] },
  ],
}]

// ---------------------------------------------------------------- S0 build-contract

function buildContract() {
  if (!existsSync(LIB_JS) || !existsSync(LIB_CJS)) {
    record('S0 bundles-present', 'fail', 'lib/client.js or lib/client.cjs missing — workbench not built')
    return
  }
  const js = readFileSync(LIB_JS, 'utf8')
  if (js !== readFileSync(LIB_CJS, 'utf8')) {
    record('S0 bundles-in-sync', 'fail', 'twin bundles out of sync — rebuild (KI-052)')
    return
  }
  const leaks = POPOVER_LITERALS.filter(l => js.includes(l))
  record('S0 bundle-free-of-popover', leaks.length ? 'fail' : 'pass',
    leaks.length ? `shipped bundle still carries popover literal(s): ${leaks.join(', ')} (pre-implement red expected)`
      : `twin bundles in sync; none of ${POPOVER_LITERALS.join(' / ')} ships in the bundle`)
}

// ---------------------------------------------------------------- S1 real browser

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

async function waitFor(cond, ms) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) {
    try { if (await cond()) return true } catch { /* keep polling */ }
    await new Promise(r => setTimeout(r, 250))
  }
  try { return await cond() } catch { return false }
}

function routeStubs(route) {
  const url = new URL(route.request().url())
  const path = url.pathname.replace(/\/+$/, '')
  if (path === '/sandbar-workbench/api/wf/projects') {
    return route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { projects: [
        { key: PROJ_A, name: 'fixture-alpha', primary: '/tmp/fx-alpha', dirs: ['/tmp/fx-alpha'] },
      ], quarantined: [] } }),
    })
  }
  if (path === '/sandbar-workbench/api/wf/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: DEV_ROWS, workflows: WORKFLOWS } }) })
  }
  if (path === '/sandbar-workbench/api/wf/inspection/tickets') {
    return route.fulfill({ contentType: 'application/json',
      body: JSON.stringify({ ok: true, result: { tickets: INS_ROWS, count: INS_ROWS.length } }) })
  }
  return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'fixture stub: unknown route' }) })
}

// In-page reader face of the left column. Binding kept shallow: assertions fall
// on reader-visible text and button semantics inside the sidebar, never on
// internal names or execution order.
async function sidebarFaces(page, ids) {
  return page.evaluate(([freshId, staleId, edgeId, insOldId]) => {
    const sb = document.querySelector('.wb-sb')
    if (!sb) return { sidebar: false }
    const visible = (el) => {
      if (!el) return false
      const r = el.getBoundingClientRect()
      return r.width > 0 && r.height > 0
    }
    const text = sb.textContent || ''
    // The gear: any visible button whose accessible name is "Settings"
    // (title attr or aria-label — semantic anchor, not a class name).
    const gear = [...sb.querySelectorAll('button')].some(b =>
      visible(b) && (b.title === 'Settings' || b.getAttribute('aria-label') === 'Settings'))
    const inputs = [...sb.querySelectorAll('input')].filter(visible).length
    const foot = [...sb.querySelectorAll('div')].find(d => visible(d) && /(^|\s)wb-sb-foot(\s|$)/.test(d.className || ''))
    const footButtons = foot ? [...foot.querySelectorAll('button')].filter(visible).length : -1
    const rowHas = (id) => text.includes(id)
    return {
      sidebar: true,
      gear,
      dwellInput: inputs,
      dwellText: text.includes('Sandbar dwell'),
      m2cText: text.includes('Quiet in-progress threshold'),
      footPresent: !!foot,
      footButtons,
      freshVisible: rowHas(freshId),
      staleVisible: rowHas(staleId),
      edgeVisible: rowHas(edgeId),
      insOldVisible: rowHas(insOldId),
    }
  }, ids)
}

async function runLeg(browser, colorScheme, shotName) {
  const ctx = await browser.newContext()
  try {
    // The rejected state the ticket calls out: a value the user typed into the
    // (now retired) dwell input before the removal. Seeded BEFORE first load.
    await ctx.addInitScript(([key, val]) => { try { localStorage.setItem(key, val) } catch { /* fresh */ } },
      [STALE_KEY, STALE_VALUE])
    const page = await ctx.newPage()
    const pageErrors = []
    page.on('pageerror', e => pageErrors.push(String(e).slice(0, 200)))
    if (colorScheme) await page.emulateMedia({ colorScheme })
    await page.route('**/sandbar-workbench/api/**', routeStubs)
    await bench.goto(page, { waitUntil: 'networkidle' })
    const landed = await waitFor(async () => {
      return page.evaluate(() => !!document.querySelector('.wb-sb')).catch(() => false)
    }, 15000)
    if (!landed) {
      record(`S1 precheck (${shotName})`, 'env_fail', `left column did not render (stub not consumed? stage=${BASE})`)
      return
    }
    await page.waitForTimeout(2000)
    record(`S1 precheck (${shotName})`, 'pass', `sidebar rendered with stale localStorage ${STALE_KEY}=${STALE_VALUE} (${colorScheme || 'light (default)'})`)

    const f = await sidebarFaces(page, [FRESH_ID, STALE_ID, EDGE_ID, INS_OLD_ID])

    // F1 the gear is gone (semantic anchor: no button named Settings).
    const f1 = f.sidebar && !f.gear
    record(`F1 no-settings-gear (${shotName})`, f1 ? 'pass' : 'fail',
      f1 ? 'no visible button named "Settings" in the sidebar'
        : 'a Settings gear button still renders in the sidebar footer (pre-implement red expected)')

    // F2 the popover and both of its lines are gone.
    const f2 = !f.dwellText && !f.m2cText && f.dwellInput === 0
    record(`F2 no-popover-faces (${shotName})`, f2 ? 'pass' : 'fail',
      f2 ? 'no "Sandbar dwell" input, no "Quiet in-progress threshold" line, no popover input anywhere in the sidebar'
        : `popover faces still render (dwellText=${f.dwellText}, m2cText=${f.m2cText}, visible inputs=${f.dwellInput}) (pre-implement red expected)`)

    // F3 the footer keeps whatever else it had — it still renders and, after
    // this ticket, carries no button at all (the gear was its only button).
    const f3 = f.footPresent && f.footButtons === 0
    record(`F3-footer-intact (${shotName})`, f3 ? 'pass' : 'fail',
      f3 ? 'sidebar footer strip still renders, now buttonless (not reflowed away)'
        : `footer face wrong (present=${f.footPresent}, visible buttons=${f.footButtons})`)

    // F4 the pinned window still works AND the stale stored value does not
    // steer it: with 999 seeded, a ticket closed 1h ago renders, one closed
    // 25h ago does not (under the old reader a 999h window would show it).
    const f4 = f.freshVisible && !f.staleVisible
    record(`F4 dwell-pinned-24h-stale-ignored (${shotName})`, f4 ? 'pass' : 'fail',
      f4 ? `with stale ${STALE_VALUE}h seeded: fresh (1h) rendered, stale (25h) filtered — window pinned at 24h`
        : `window wrong under stale seed (freshVisible=${f.freshVisible}, staleVisible=${f.staleVisible}) — hidden stored value still steering the window, or the window itself broke (pre-implement red expected)`)

    // F5 boundary face: closed exactly 24h ago is already outside (strict <).
    const f5 = !f.edgeVisible
    record(`F5 boundary-24h-exact-filtered (${shotName})`, f5 ? 'pass' : 'fail',
      f5 ? 'ticket closed exactly 24h ago is filtered'
        : 'ticket closed exactly 24h ago still renders — boundary semantics changed')

    // F6 the inspection row does not pass through the client window: closed
    // 30h ago, it must still render (its window is the engine's R8, not this
    // client constant). Regression guard — the two-window split must survive
    // the popover retirement untouched.
    const f6 = f.insOldVisible
    record(`F6 inspection-row-bypasses-window (${shotName})`, f6 ? 'pass' : 'fail',
      f6 ? 'inspection closed row (30h) still rendered — client window does not touch inspection rows'
        : 'inspection closed row vanished — the client 24h window leaked onto inspection rows (reject rule)')

    try {
      mkdirSync(OUT_DIR, { recursive: true })
      await page.screenshot({ path: join(OUT_DIR, shotName), fullPage: false })
    } catch (e) {
      console.log(`[WARN] screenshot ${shotName} failed: ${String(e).slice(0, 120)}`)
    }
    record(`S1 page-health (${shotName})`, pageErrors.length ? 'fail' : 'pass',
      pageErrors.length ? `pageerror ×${pageErrors.length}: ${pageErrors.slice(0, 3).join(' | ')}` : 'zero pageerror')
  } finally {
    await ctx.close().catch(() => {})
  }
}

// ---------------------------------------------------------------- main

buildContract()

const pw = await loadPlaywright()
if (!pw) {
  console.log('[ENV_FAIL] playwright-core unavailable (KI-036 family)')
  summarize()
}
const browser = await launchBrowser(pw)
if (!browser) {
  console.log('[ENV_FAIL] chromium unavailable (KI-036 family)')
  summarize()
}
try {
  await runLeg(browser, null, 'sidebar-footer-light.png')
  await runLeg(browser, 'dark', 'sidebar-footer-dark.png')
} finally {
  await browser.close().catch(() => {})
}
summarize()
