// sc_overview_ledger_dialog_conc_block.mjs — t261008-20 Overview restructure
// (host order 261008): the Ledger tab folds into an Overview dialog beside
// 'Recent actions', wakes render uncapped (>3), 'Running tickets' becomes
// 'Concurrent limit' with no ticket list, the audit stamp goes. Grey-box L3,
// real browser + page-boundary API stubs, zero docker/Temporal, never touches
// 3099. Shared stage pattern reused from t261004-13 (fixture/stub/openPanel are
// shared setup, not duplicated cases).
//
// Intent (user-perceivable, ticket verbatim + accepted plan rev2):
//   D1 the tab strip carries no Ledger entry — the ledger tab is gone, not hidden.
//   D2 the Overview entry 'Recent actions (view source event)' exists and opens
//      the ledger dialog (content not visible before the click, visible after).
//   D3 the dialog shows MORE THAN THREE wakes — all 6 fixture rows render (the
//      old 3-row cap must not silently survive), newest first.
//   D4 the dialog states the count and names the real ceiling: 'Wakes · 6' and
//      the watchdog 20-row window copy (the limit is named, not silently applied).
//   D5 keyboard: focus moves into the dialog on open; Esc closes it; the close
//      control closes it; focus returns to the entry (reachable AND dismissible).
//   D6 empty wakes: the dialog shows the declared empty copy and no fabricated
//      rows (the ticket: 'says so when the list is empty').
//   D7 missing wakes key: the dialog renders no rows and the page does not throw
//      (external-input missing/late/malformed discipline).
//   D8 malformed `at` in a wake sorts last and renders no NaN (t261004-14 rule
//      must survive the uncap — the incident regression, dialog edition).
//   D9 the block is titled 'Concurrent limit', keeps the counts line in words
//      ('2 at work · 1 waiting'), and renders NO ticket rows (holder tickets are
//      absent from the face); the chip stays.
//   D10 no audit stamp anywhere: no 'set by ' text even when the audit record is
//      present and ok (the writer's audit file is out of scope; the display goes).
//   D11 negative regression: no 'data-tab="ledger"', no concList/concAudit
//      element, no holder-row markup — the removed faces cannot come back
//      unnoticed.
//   K1 light AND dark captures (KI-055) of the Overview with the dialog open.
//   X1 zero pageerror / console error across the whole journey.
//
// Intent split: the wakes order/cap CONTRACT declaration belongs to
// t261004-14/sc_panel_list_contract_render (updated in the same change); the
// tab-strip ORDER contract belongs to t261005-10/sc_ui2_panel_tab_order_contract
// (ORDER updated in the same change); the dated-format parity belongs to
// t261004-13 A4 (updated in the same change). This entry owns the NEW user
// journey: dialog reachability, the >3 wake face, the renamed conc block, the
// stamp's absence. Pre-implement red is the expected TDD signal; arbitrate and
// merge must be green. playwright/chromium missing = ENV_FAIL exit 2 (KI-036
// family); page module missing = FAIL named (TDD red).
import { createServer } from 'node:http'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const OUT = fileURLToPath(new URL('./out/', import.meta.url))

// Two cross-day timestamps + three more, all in the past; expectation values are
// computed on the same machine/TZ by the shared t261004-13 helper pattern — here
// we only assert ORDER and count, not the rendered time text (owned by A4).
const T = (d, h, m) => Date.UTC(2026, 9, d, h, m, 0)
const WAKES = [
  { at: T(3, 11, 50), ticket: 't-wake-newest', dedupe_key: 'w1', mode: 'queue', accepted: true },
  { at: T(3, 9, 30), ticket: 't-wake-2', dedupe_key: 'w2', mode: 'queue', accepted: true },
  { at: T(2, 21, 10), ticket: 't-wake-3', dedupe_key: 'w3', mode: 'queue', accepted: true },
  { at: T(2, 15, 0), ticket: 't-wake-4', dedupe_key: 'w4', mode: 'queue', accepted: true },
  { at: T(2, 8, 5), ticket: 't-wake-5', dedupe_key: 'w5', mode: 'queue', accepted: true },
  { at: null, ticket: 't-wake-bad-at', dedupe_key: 'w6', mode: 'queue', accepted: true }, // malformed at
]
const HOLDERS = [
  { ticket: 't-holder-alpha', reason: 'running' },
  { ticket: 't-holder-beta', reason: 'human-hold' },
]
const CONC = { ok: true, project: PROJ, limit: 3, unlimited: false, at_work: 2, waiting: 1, holders: HOLDERS, queue: [], audit: { ok: true, by: 'host', ts: T(1, 10, 0) } }

function stubServer(wakes, { omitWakes = false } = {}) {
  return createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      const result = { declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, alerts: [] }
      if (!omitWakes) result.wakes = wakes
      return json({ ok: true, result })
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, rows: [], degraded: false })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/concurrency')) return json(CONC)
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })
    res.writeHead(404); res.end('{}')
  })
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: REPO, encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(REPO, common, '..')
  } catch { /* not a worktree */ }
  return REPO
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}
const REPO = fileURLToPath(new URL('../../', import.meta.url))

async function launchBrowser(pw) {
  try { return await pw.chromium.launch({ headless: true }) } catch (e) {
    try { return await pw.chromium.launch({ headless: true, channel: 'chrome' }) } catch (e2) {
      throw new Error('browser-launch-unavailable: ' + String(e2).slice(0, 160))
    }
  }
}

async function openPanel(pw, html, stub, theme) {
  const port = stub.address().port
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(html) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port
  const browser = await launchBrowser(pw)
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${port}` + new URL(route.request().url()).pathname }))
  await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}${theme ? '&theme=' + theme : ''}`)
  await page.waitForTimeout(600)
  return { browser, page, local, errors }
}
async function closePanel({ browser, local }) {
  if (browser) { try { await browser.close() } catch { /* noop */ } }
  local.close()
}
const ENTRY = 'Recent actions (view source event)'
async function openDialog(page) {
  await page.click(`text=${ENTRY}`)
  await page.waitForTimeout(250)
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts has no PANEL_PAGE_HTML export (seam contract; TDD-phase red expected)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }
  const html = pageMod.PANEL_PAGE_HTML

  // ---- D11 negative half runs on the STATIC page constant (source-presence guard)
  C.case('D11-no-ledger-tab-marker', !/data-tab="ledger"/.test(html), 'tab strip must carry no Ledger entry')
  C.case('D11-no-concList-concAudit', !/id="concList"/.test(html) && !/id="concAudit"/.test(html), 'removed list container and audit span must be gone')
  C.case('D11-no-holder-row-markup', !/Holds a slot/.test(html) && !/dot blue/.test(html), 'old running-ticket row markup must not survive anywhere')

  const stub = stubServer(WAKES)
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session
  try { session = await openPanel(pw, html, stub) } catch (e) {
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg); return C.exit()
  }
  const { page, errors } = session
  try {
    const bodyText = await page.evaluate(() => document.body.innerText)

    // ---- D1 no Ledger tab on the served page
    const tabNames = await page.evaluate(() => Array.from(document.querySelectorAll('[data-tab]')).map(e => e.getAttribute('data-tab')))
    C.case('D1-no-ledger-tab', !tabNames.includes('ledger'), `tabs: [${tabNames.join(',')}]`)

    // ---- D9 renamed block, counts in words, no ticket rows
    C.case('D9-title-concurrent-limit', /Concurrent limit/.test(bodyText) && !/Running tickets/.test(bodyText), 'block title must read "Concurrent limit"')
    C.case('D9-counts-in-words', /2 at work · 1 waiting/.test(bodyText), 'counts line must state holders/queue in words')
    C.case('D9-no-holder-rows', !bodyText.includes('t-holder-alpha') && !bodyText.includes('t-holder-beta'), 'running-ticket rows must not render')
    C.case('D9-chip-present', await page.evaluate(() => { const e = document.getElementById('concChip'); return !!e && e.style.display !== 'none' && e.textContent.length > 0 }), 'three-state chip stays')

    // ---- D10 no audit stamp even with a present+ok audit record
    C.case('D10-no-audit-stamp', !bodyText.includes('set by '), 'audit record was ok:true in the stub — no "set by" display may render')

    // ---- D2 entry exists and opens the dialog; content hidden before
    C.case('D2-entry-present', bodyText.includes(ENTRY), `entry text "${ENTRY}" must exist on the Overview`)
    const beforeOpen = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return !!e && e.offsetParent === null })
    await openDialog(page)
    const afterOpen = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return !!e && e.offsetParent !== null })
    C.case('D2-entry-opens-dialog', beforeOpen && afterOpen, `ledger content hidden before=${beforeOpen} visible after=${afterOpen}`)

    // ---- D3 >3 wakes, all rows, newest first
    const rows = await page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).map(e => e.textContent))
    C.case('D3-more-than-three-wakes', rows.length === WAKES.length && rows.length > 3, `rendered ${rows.length} rows, fixture has ${WAKES.length}`)
    const tickets = await page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .tk')).map(e => e.textContent))
    C.case('D3-newest-first', tickets[0] === 't-wake-newest', `first row ticket=${tickets[0]}`)

    // ---- D4 count stated + real ceiling named
    const dlgText = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return e ? (e.closest('[data-open]') || document.body).innerText : '' })
    C.case('D4-count-stated', new RegExp('wakes\\s*·\\s*' + WAKES.length, 'i').test(dlgText), 'dialog must state the wake count (case-insensitive: the heading is uppercased by CSS)')
    C.case('D4-ceiling-named', /last 20 wakes/i.test(dlgText), 'dialog must name the watchdog 20-row window')

    // ---- D8 malformed at: sorts last, no NaN
    C.case('D8-malformed-at-last', tickets[tickets.length - 1] === 't-wake-bad-at', `last row ticket=${tickets[tickets.length - 1]}`)
    C.case('D8-malformed-no-nan', !/NaN|invalid date/i.test(dlgText), 'malformed at must never render NaN')

    // ---- D5 keyboard: focus in, Esc closes, close control closes, focus restores
    const focusIn = await page.evaluate(() => {
      const a = document.activeElement
      const d = document.getElementById('ledgerEvents')
      if (!a || a.tagName !== 'BUTTON' || !d) return false
      const dlg = d.closest('[data-open]')
      return !!dlg && dlg.contains(a)
    })
    C.case('D5-focus-moves-into-dialog', focusIn, `activeElement=${await page.evaluate(() => document.activeElement && document.activeElement.tagName)}`)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
    const afterEsc = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return !!e && e.offsetParent === null })
    C.case('D5-esc-closes', afterEsc, 'Esc must close the dialog')
    const focusBack = await page.evaluate((t) => { const a = document.activeElement; return !!a && (a.textContent || '').includes(t) }, ENTRY)
    C.case('D5-focus-restores-to-entry', focusBack, 'focus must return to the entry button')
    await openDialog(page)
    const closedByBtn = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button')).filter(b => /^close$/i.test((b.textContent || '').trim()) && b.offsetParent !== null)
      if (btns.length === 0) return false
      btns[0].click()
      return true
    })
    await page.waitForTimeout(200)
    const hiddenAgain = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return !!e && e.offsetParent === null })
    C.case('D5-close-control', closedByBtn && hiddenAgain, `a visible Close control exists=${closedByBtn} and closes the dialog=${hiddenAgain}`)
    await openDialog(page)

    // ---- K1 captures, light and dark (KI-055)
    try {
      mkdirSync(OUT, { recursive: true })
      await page.screenshot({ path: join(OUT, 'overview-dialog-light.png'), fullPage: false })
      C.case('K1-light-capture', existsSync(join(OUT, 'overview-dialog-light.png')), 'integration/t261008-20/out/overview-dialog-light.png')
    } catch (e) { C.case('K1-light-capture', false, String(e).slice(0, 160)) }
    await closePanel(session); session = null
    let dark
    try { dark = await openPanel(pw, html, stub, 'dark') } catch (e) {
      C.case('K1-dark-capture', false, String(e).slice(0, 160)); stub.close(); return C.exit()
    }
    try {
      await openDialog(dark.page)
      mkdirSync(OUT, { recursive: true })
      await dark.page.screenshot({ path: join(OUT, 'overview-dialog-dark.png'), fullPage: false })
      C.case('K1-dark-capture', existsSync(join(OUT, 'overview-dialog-dark.png')), 'integration/t261008-20/out/overview-dialog-dark.png')
      C.case('X1-dark-no-pageerror', dark.errors.length === 0, dark.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(dark) }
    C.case('X1-no-pageerror', errors.length === 0, errors.slice(0, 3).join(' | '))

    // ---- D6 empty wakes (fresh page, own stub)
    stub.close()
    const stubEmpty = stubServer([])
    await new Promise(r => stubEmpty.listen(0, '127.0.0.1', r))
    let s2
    try { s2 = await openPanel(pw, html, stubEmpty) } catch (e) {
      stubEmpty.close(); C.case('D6-empty-wakes', false, String(e).slice(0, 160)); return C.exit()
    }
    try {
      await openDialog(s2.page)
      const emptyRows = await s2.page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).length)
      const emptyText = await s2.page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return e ? e.innerText : '' })
      C.case('D6-empty-wakes', emptyRows <= 1 && /no wakes/i.test(emptyText), `rows=${emptyRows} text="${emptyText.slice(0, 80)}"`)
      C.case('D6-empty-no-pageerror', s2.errors.length === 0, s2.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(s2); stubEmpty.close() }

    // ---- D7 missing wakes key (fresh page, own stub)
    const stubNoWakes = stubServer([], { omitWakes: true })
    await new Promise(r => stubNoWakes.listen(0, '127.0.0.1', r))
    let s3
    try { s3 = await openPanel(pw, html, stubNoWakes) } catch (e) {
      stubNoWakes.close(); C.case('D7-missing-wakes-key', false, String(e).slice(0, 160)); return C.exit()
    }
    try {
      await openDialog(s3.page)
      const noRows = await s3.page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).length)
      const dlg3 = await s3.page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return e ? (e.closest('[data-open]') || document.body).innerText : '' })
      C.case('D7-missing-wakes-key', !/NaN|undefined/.test(dlg3) && noRows <= 1, `rows=${noRows}, dialog must not throw or fabricate (scoped to the dialog; the separate limit-row "declared in undefined." finding is reported, not asserted here)`)
      C.case('D7-missing-no-pageerror', s3.errors.length === 0, s3.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(s3); stubNoWakes.close() }
  } finally {
    if (session) await closePanel(session)
    try { stub.close() } catch { /* already closed */ }
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: scenario crashed:', String(e).slice(0, 300)); process.exit(2) })
