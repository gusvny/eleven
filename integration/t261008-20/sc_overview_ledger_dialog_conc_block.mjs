// sc_overview_ledger_dialog_conc_block.mjs — t261008-20 Overview restructure,
// UPDATED by t261009-37 (host orders 261009 (1)(2)(3)). DELIBERATE口径 CHANGE,
// declared: the source-event DIALOG pattern this scenario pinned (entry text
// exists; ledger content hidden before the click and visible after; focus/Esc
// keyboard round-trip) was REPLACED by host order 261009-(2) — the Ledger face
// now lives INLINE in the Overview Events block, and the Alerts tab is gone with
// its face inline too (261009-(1)); the Open session button is gone (261009-(3)).
// This is a pattern replacement ordered by the host, NOT a silent loosening: the
// D5 keyboard case is RETIRED because its object (the dialog) no longer exists,
// and every other case survives scoped to the inline block. No case was deleted
// to make the suite pass — D2 was rewritten to the new face and D5 retired, and
// new cases pin the replacement (no alerts tab; alerts rows visible inline).
//
// Still owned here (user-perceivable):
//   D1  the tab strip carries no Ledger entry — and (new) no Alerts entry.
//   D2' the events block is VISIBLE on the Overview WITHOUT any entry click;
//       the lone entry link and the dialog do not exist.
//   D2n (new) no Alerts tab; the Alerts block renders the alert rows inline
//       (header count + rows) with the night-muted face in the block.
//   D3  the events block shows MORE THAN THREE wakes — all 6 fixture rows render
//       (the old 3-row cap must not silently survive), newest first.
//   D4  the block states the count and names the real ceiling: the wake count in
//       the block header and the watchdog 20-row window copy.
//   D5  RETIRED with its pattern (the dialog). See the declared-change note above.
//   D6  empty wakes: the block shows the declared empty copy and no fabricated rows.
//   D7  missing wakes key: no rows, page does not throw.
//   D8  malformed `at` in a wake sorts last and renders no NaN (t261004-14 rule).
//   D9  the block is titled 'Concurrent limit' (case-insensitive: .sect uppercases
//       the rendered text), counts in words, NO ticket rows; the chip stays.
//   D10 no audit stamp anywhere ('set by ').
//   D11 negative regression: no data-tab="ledger", no data-tab="alerts", no
//       concList/concAudit, no openSessionBtn, no ledgerDlg — the removed faces
//       cannot come back unnoticed.
//   K1  light AND dark captures (KI-055) of the Overview.
//   X1  zero pageerror / console error across the whole journey.
// Grey-box L3, real browser + page-boundary API stubs, zero docker/Temporal,
// never touches 3099. playwright/chromium missing = ENV_FAIL exit 2 (KI-036
// family); page module missing = FAIL named.
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
const ALERTS = [
  { at: T(3, 12, 7), title: 'Queue t-wake-newest has 0 live pollers', level: 'redline' },
  { at: T(3, 12, 12), title: 'Worker pid 1898 is older than the tree it runs', level: 'warn', night_muted: true },
]

function stubServer(wakes, { omitWakes = false } = {}) {
  return createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      const result = { declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x/ledger.jsonl', unreadable: false, rows_seen: 12480, dupes_skipped: 3, malformed_rows: 0, gaps_seen: 0 }, liveness: { executor: { alive: true } }, alerts: ALERTS }
      if (!omitWakes) result.wakes = wakes
      return json({ ok: true, result })
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, actions: [], degraded: false })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
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

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts has no PANEL_PAGE_HTML export (seam contract)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }
  const html = pageMod.PANEL_PAGE_HTML

  // ---- D11 negative half runs on the STATIC page constant (source-presence guard)
  C.case('D11-no-ledger-tab-marker', !/data-tab="ledger"/.test(html), 'tab strip must carry no Ledger entry')
  C.case('D11-no-alerts-tab-marker', !/data-tab="alerts"/.test(html) && !/id="t-alerts"/.test(html) && !/id="paneAlert"/.test(html), 'no Alerts tab: radio, label and pane are gone (t261009-37)')
  C.case('D11-no-dialog-or-entry', !/id="ledgerDlg"/.test(html) && !/id="ledgerDlgBtn"/.test(html), 'the source-event entry link and dialog are gone (t261009-37)')
  C.case('D11-no-open-session', !/id="openSessionBtn"/.test(html) && !html.includes("'sandbar-executor-panel:open-session'"), 'the Open session button and its postMessage are gone (t261009-37)')
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

    // ---- D1 no Ledger tab, and (t261009-37) no Alerts tab on the served page
    const tabNames = await page.evaluate(() => Array.from(document.querySelectorAll('[data-tab]')).map(e => e.getAttribute('data-tab')))
    C.case('D1-no-ledger-tab', !tabNames.includes('ledger'), `tabs: [${tabNames.join(',')}]`)
    C.case('D1-no-alerts-tab', !tabNames.includes('alerts'), `tabs: [${tabNames.join(',')}]`)

    // ---- D2' the events block is inline: visible WITHOUT any entry click
    C.case('D2-events-block-inline-visible', await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return !!e && e.offsetParent !== null }), 'the events block must be visible on the Overview without any entry click')
    C.case('D2-no-entry-link', await page.evaluate(() => document.getElementById('ledgerDlgBtn') === null), 'the lone source-event entry link is gone')

    // ---- D2n (new) the Alerts face is inline in its block: header count + rows
    C.case('D2n-alerts-block-inline', await page.evaluate(() => { const e = document.getElementById('alertList'); return !!e && e.offsetParent !== null }), 'the alerts rows render inline on the Overview (no tab, no click)')
    C.case('D2n-alerts-count', (await page.textContent('#alertHead')) === String(ALERTS.length), 'the Alerts header carries the real count')
    C.case('D2n-alerts-row-visible', bodyText.includes('Worker pid 1898 is older than the tree it runs'), 'an alert row title is visible on the page')
    C.case('D2n-night-muted-face', /night-muted/i.test(bodyText), 'the night-muted face is present in the block')

    // ---- D9 renamed block, counts in words, no ticket rows
    C.case('D9-title-concurrent-limit', /concurrent limit/i.test(bodyText) && !/Running tickets/i.test(bodyText), 'block title must read "Concurrent limit"')
    C.case('D9-counts-in-words', /2 at work · 1 waiting/.test(bodyText), 'counts line must state holders/queue in words')
    C.case('D9-no-holder-rows', !bodyText.includes('t-holder-alpha') && !bodyText.includes('t-holder-beta'), 'running-ticket rows must not render')
    C.case('D9-chip-present', await page.evaluate(() => { const e = document.getElementById('concChip'); return !!e && e.style.display !== 'none' && e.textContent.length > 0 }), 'three-state chip stays')

    // ---- D10 no audit stamp even with a present+ok audit record
    C.case('D10-no-audit-stamp', !bodyText.includes('set by '), 'audit record was ok:true in the stub — no "set by" display may render')

    // ---- D3 >3 wakes, all rows, newest first (scoped to the inline block)
    const rows = await page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).map(e => e.textContent))
    C.case('D3-more-than-three-wakes', rows.length === WAKES.length && rows.length > 3, `rendered ${rows.length} rows, fixture has ${WAKES.length}`)
    const tickets = await page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .tk')).map(e => e.textContent))
    C.case('D3-newest-first', tickets[0] === 't-wake-newest', `first row ticket=${tickets[0]}`)

    // ---- D4 count stated + real ceiling named
    const blkText = await page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return e ? e.closest('.blk').innerText : '' })
    C.case('D4-count-stated', (await page.textContent('#wakeCount')) === String(WAKES.length), 'the Events header states the wake count')
    C.case('D4-ceiling-named', /last 20 wakes/i.test(blkText), 'the block must name the watchdog 20-row window')
    C.case('D4-ledger-path-in-header', (await page.textContent('#ledgerFile')) === '/x/ledger.jsonl', 'the Events header carries the ledger path')

    // ---- D8 malformed at: sorts last, no NaN
    C.case('D8-malformed-at-last', tickets[tickets.length - 1] === 't-wake-bad-at', `last row ticket=${tickets[tickets.length - 1]}`)
    C.case('D8-malformed-no-nan', !/NaN|invalid date/i.test(blkText), 'malformed at must never render NaN')

    // ---- D5 RETIRED with its pattern (the dialog) — declared口径 change, see header.

    // ---- K1 captures, light and dark (KI-055)
    try {
      mkdirSync(OUT, { recursive: true })
      await page.screenshot({ path: join(OUT, 'overview-blocks-light.png'), fullPage: false })
      C.case('K1-light-capture', existsSync(join(OUT, 'overview-blocks-light.png')), 'integration/t261008-20/out/overview-blocks-light.png')
    } catch (e) { C.case('K1-light-capture', false, String(e).slice(0, 160)) }
    await closePanel(session); session = null
    let dark
    try { dark = await openPanel(pw, html, stub, 'dark') } catch (e) {
      C.case('K1-dark-capture', false, String(e).slice(0, 160)); stub.close(); return C.exit()
    }
    try {
      mkdirSync(OUT, { recursive: true })
      await dark.page.screenshot({ path: join(OUT, 'overview-blocks-dark.png'), fullPage: false })
      C.case('K1-dark-capture', existsSync(join(OUT, 'overview-blocks-dark.png')), 'integration/t261008-20/out/overview-blocks-dark.png')
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
      const noRows = await s3.page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).length)
      const blk3 = await s3.page.evaluate(() => { const e = document.getElementById('ledgerEvents'); return e ? e.closest('.blk').innerText : '' })
      C.case('D7-missing-wakes-key', !/NaN|undefined/.test(blk3) && noRows <= 1, `rows=${noRows}, the block must not throw or fabricate`)
      C.case('D7-missing-no-pageerror', s3.errors.length === 0, s3.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(s3); stubNoWakes.close() }
  } finally {
    if (session) await closePanel(session)
    try { stub.close() } catch { /* already closed */ }
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: scenario crashed:', String(e).slice(0, 300)); process.exit(2) })
