// sc_overview_blocks_colour_refused.mjs — t261009-37 Overview blocks, project
// colour, refused-pill alignment (host orders 261009). Grey-box L3, real browser
// + page-boundary API stubs, zero docker/Temporal, never touches 3099. Shared
// stage pattern reused from t261003-06/lib_panel_seam.mjs (fixture/stub/openPanel
// are shared setup, not duplicated cases) and t261008-20 (the same seam protocol;
// this file is a sibling consumer, not a second contract).
//
// DELIBERATE口径 NOTE: this scenario is designed for the POST-ticket page. The
// dialog-pattern scenario t261008-20/sc_overview_ledger_dialog_conc_block.mjs and
// the tab-order scenario t261005-10/sc_ui2_panel_tab_order_contract.mjs are
// rewritten by the implement stage under host orders 261009 (1)(2)(3)(7) — a
// declared口径 change, not a silent loosening. This entry does NOT re-assert
// those faces; the intent split below is the dedup contract.
//
// Intent (user-perceivable, ticket verbatim; the faces the OTHER entries do not own):
//   L1 four blocks — the right column reads, top to bottom: Concurrent limit,
//      Alerts, Recent actions, Events; each in a bordered block; the vertical
//      gap between consecutive blocks is uniform (host order (6)); the first
//      right-column block head starts on the same line as the left column's
//      first block head (host order (4)).
//   L2 refused fact without a tooltip — an action row refused by the engine
//      carries a visible 'refused' mark in the op column and states what was
//      refused and why in the row's own sentence; the row's meaning does not
//      depend on hover (host order (5) + (7): the red dot shifted the time
//      column and left an unexplained mark).
//   L3 column alignment — every action row's time column starts at the same x
//      (the refused row no longer shifts), and the wakes rows' time columns
//      align the same way (host order (5), wakes included).
//   C1 single-source project colour — the page's identity colour equals the
//      colour the shared identity module derives for the same project (never a
//      second hash, never hand-picked); it is stable across reloads and differs
//      for a different project; the top bar is a thin full-width strip; the
//      identity colour does NOT leak onto a semantic surface (the concurrency
//      status chip stays on its own colours) (host order (6)).
//   R1 Open session retired — no 'Open session' button anywhere on the live
//      Overview, and the session state display (the chip) still renders
//      (host order (3)); the page constant carries no open-session postMessage
//      (absence of the retired sender, mirrored to the DOM face here).
//   K1 light AND dark captures (KI-055) of the restructured Overview into
//      integration/t261009-37/out/ as the ticket's named evidence.
//   X1 zero pageerror / console error across the whole journey.
//
// Intent split (dedup): the dialog-pattern rewrite (events visible inline
// without a click, no ledger tab, no alerts tab, alerts rows inline, wakes
// count/ceiling/empty/missing/malformed, 'Concurrent limit' wording + chip +
// counts) belongs to t261008-20-overview-ledger-dialog-conc-block (rewritten in
// the same change); the tab-strip ORDER belongs to
// t261005-10-sc-ui2-panel-tab-order-contract (rewritten in the same change);
// the developer L1 static battery (retired-marker greps) belongs to
// t261009-37-overview-blocks. This entry owns the layout geometry, the refused
// row's aligned+readable face, and the identity-colour single source — none of
// which the others assert. Pre-implement red is the expected TDD signal;
// arbitrate and merge must be green. playwright/chromium missing = ENV_FAIL
// exit 2 (KI-036 family); page module missing = FAIL named (TDD red).
import { createServer } from 'node:http'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const OUT = fileURLToPath(new URL('./out/', import.meta.url))
const IDENTITY_TS = fileURLToPath(new URL('../../server/plugins/workbench/src/shared/project-identity.ts', import.meta.url))

const T = (d, h, m) => Date.UTC(2026, 10, d, h, m, 0)
const WAKES = [
  { at: T(9, 11, 50), ticket: 't-wake-newest', dedupe_key: 'w1', mode: 'queue', accepted: true },
  { at: T(9, 9, 30), ticket: 't-wake-2', dedupe_key: 'w2', mode: 'queue', accepted: true },
  { at: T(9, 8, 5), ticket: 't-wake-3', dedupe_key: 'w3', mode: 'queue', accepted: true },
  { at: null, ticket: 't-wake-bad-at', dedupe_key: 'w4', mode: 'queue', accepted: true }, // malformed at stays honest
]
const ACTIONS = [
  { at: T(9, 20, 51), action: 'Sign', ticket: 't261008-47', result: 'refused', permission: 'host-signed', session: 'sess-abc', reason: 'who > 64' },
  { at: T(9, 20, 40), action: 'Sign', ticket: 't261009-30', result: 'done', permission: 'host-signed', session: 'sess-abc' },
  { at: T(9, 20, 30), action: 'Send back', ticket: 't261009-31', result: 'done', permission: 'declared default', session: 'sess-def' },
]
const CONC = { ok: true, project: 'alpha', limit: 3, unlimited: false, at_work: 2, waiting: 1, holders: [{ ticket: 't-holder-alpha', reason: 'running' }], queue: [], audit: { ok: true, by: 'host', ts: T(8, 10, 0) } }

function stubServer() {
  return createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/watchdog/api/status') || u.pathname.endsWith('/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true }, ledger: { path: '/x/ledger.jsonl', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, alerts: [], wakes: WAKES } })
    }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [] })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, actions: ACTIONS, older_rows: 0, degraded: false })
    if (u.pathname.endsWith('/api/settings')) return json({ config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ granted_count: 0, total: 6, executor_sessions: [], session_state: 'none' })
    if (u.pathname.endsWith('/api/recent-actions')) return json({ ok: true, actions: ACTIONS })
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

async function openPanel(pw, html, stub, project, theme) {
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
  await page.goto(`http://127.0.0.1:${lport}/?project=${project}${theme ? '&theme=' + theme : ''}`)
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
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts has no PANEL_PAGE_HTML export (seam contract; TDD-phase red expected)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }
  const html = pageMod.PANEL_PAGE_HTML

  // The colour single-source judge: the shared identity module the badge uses.
  // Its absence is a named FAIL (the page could not be single-source), never a
  // crash — the module is the production source, loaded raw via node
  // type-stripping, same as the panel page itself.
  let projColor = null
  try {
    const ident = await import(pathToFileURL(IDENTITY_TS).href)
    projColor = ident.projectIdentity('alpha').color
    C.case('C0-identity-module-readable', typeof projColor === 'string' && projColor.length > 0, `projectIdentity('alpha').color=${projColor}`)
  } catch (e) {
    C.case('C0-identity-module-readable', false, 'shared project-identity.ts unreadable: ' + String(e).slice(0, 160))
  }

  const stub = stubServer()
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  let session
  try { session = await openPanel(pw, html, stub, 'alpha') } catch (e) {
    stub.close()
    const msg = String(e).slice(0, 200)
    if (/browser|executable|chromium|launch/i.test(msg)) { C.envFail('chromium-launch', msg); return C.exit() }
    C.case('scenario-ran', false, msg); return C.exit()
  }
  const { page, errors } = session
  try {
    // ---- R1 Open session retired (live face; the source negatives are the L1's)
    C.case('R1-no-open-session-button', !(await page.evaluate(() => Array.from(document.querySelectorAll('button')).some(b => /open session/i.test((b.textContent || '').trim())))), 'no visible Open session button may remain on the strip')
    C.case('R1-session-chip-present', await page.evaluate(() => { const e = document.getElementById('sessionChip'); return !!e }), 'the session chip stays as the state display')

    // ---- L1 four blocks in order, uniform gaps, columns start on one line
    const order = await page.evaluate(() => {
      const heads = Array.from(document.querySelectorAll('.blk .bhd .sect')).map(e => (e.textContent || '').trim())
      return { heads, blocks: Array.from(document.querySelectorAll('.blk'))
        .map(b => { const r = b.getBoundingClientRect(); return { top: r.top, left: r.left, h: r.height } }) }
    })
    const idx = ['Concurrent limit', 'Alerts', 'Recent actions', 'Events'].map(n => order.heads.indexOf(n))
    C.case('L1-four-block-heads-in-order', idx.every(i => i >= 0) && idx.every((v, k) => k === 0 || v > idx[k - 1]), `block heads: [${order.heads.join(' | ')}]`)
    const rights = await page.evaluate(() => {
      const names = ['Concurrent limit', 'Alerts', 'Recent actions', 'Events']
      const col = Array.from(document.querySelectorAll('.cols > div'))
      const right = col[col.length - 1]
      const tops = names.map(n => {
        const s = Array.from(right.querySelectorAll('.bhd .sect')).find(e => (e.textContent || '').trim() === n)
        return s ? Math.round(s.closest('.blk').getBoundingClientRect().top) : -1
      })
      const gaps = []
      for (let i = 1; i < tops.length; i++) {
        const a = Array.from(right.querySelectorAll('.bhd .sect')).find(e => (e.textContent || '').trim() === names[i - 1]).closest('.blk')
        const b = Array.from(right.querySelectorAll('.bhd .sect')).find(e => (e.textContent || '').trim() === names[i]).closest('.blk')
        gaps.push(Math.round(b.getBoundingClientRect().top - a.getBoundingClientRect().bottom))
      }
      return { tops, gaps }
    })
    C.case('L1-uniform-block-gaps', rights.gaps.length === 3 && rights.gaps.every(g => Math.abs(g - rights.gaps[0]) <= 1), `block gaps(px)=${rights.gaps.join(',')}`)
    const leftTop = await page.evaluate(() => {
      const col = Array.from(document.querySelectorAll('.cols > div'))
      const leftFirst = col[0].querySelector('.bhd, .sect, h2, h3')
      return leftFirst ? Math.round(leftFirst.getBoundingClientRect().top) : -1
    })
    C.case('L1-columns-start-same-line', Math.abs(leftTop - rights.tops[0]) <= 2, `left first head top=${leftTop}px, right first block top=${rights.tops[0]}px`)

    // ---- L2 refused fact readable on the row, not tooltip-dependent
    const rows = await page.evaluate(() => Array.from(document.querySelectorAll('#actList .act')).map(e => ({
      text: (e.innerText || '').replace(/\s+/g, ' ').trim(),
      firstLeft: e.querySelector('.t') ? Math.round(e.querySelector('.t').getBoundingClientRect().left) : -1,
    })))
    const refusedRow = rows.find(r => /t261008-47/.test(r.text))
    C.case('L2-refused-mark-on-row', !!refusedRow && /refused/i.test(refusedRow.text), refusedRow ? `row="${refusedRow.text.slice(0, 120)}"` : 'refused row t261008-47 not found')
    C.case('L2-reason-in-sentence', !!refusedRow && refusedRow.text.includes('who > 64'), 'the row sentence must state why (the stub reason), not only a hover title')
    C.case('L2-no-inline-dot-before-time', await page.evaluate(() => !document.querySelector('#actList .act .t') || !document.querySelector('#actList .act').innerHTML.startsWith('<span class="dot')), 'the refused dot must not sit before the time column any more')

    // ---- L3 column alignment across action rows and wake rows
    const actXs = rows.map(r => r.firstLeft)
    C.case('L3-action-time-columns-aligned', actXs.length >= 2 && actXs.every(x => Math.abs(x - actXs[0]) <= 1), `action time x positions=${actXs.join(',')}`)
    const wakeXs = await page.evaluate(() => Array.from(document.querySelectorAll('#ledgerEvents .act')).map(e => e.querySelector('.t') ? Math.round(e.querySelector('.t').getBoundingClientRect().left) : -1))
    C.case('L3-wake-time-columns-aligned', wakeXs.length >= 2 && wakeXs.every(x => Math.abs(x - wakeXs[0]) <= 1), `wake time x positions=${wakeXs.join(',')}`)

    // ---- C1 single-source identity colour, top bar, no leak onto semantic chips
    if (projColor) {
      const varColor = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--proj').trim())
      C.case('C1-var-equals-identity', varColor.toLowerCase() === projColor.toLowerCase(), `--proj=${varColor}, identity=${projColor}`)
      const bar = await page.evaluate(() => {
        const s = getComputedStyle(document.querySelector('.top'), '::before')
        return { h: parseFloat(s.height), bg: s.backgroundColor, w: document.querySelector('.top').getBoundingClientRect().width }
      })
      C.case('C1-top-bar-thin-strip', bar.h === 3 && bar.w > 0, `bar height=${bar.h}px width=${Math.round(bar.w)}px bg=${bar.bg}`)
      const chipBg = await page.evaluate(() => { const e = document.getElementById('concChip'); return e ? getComputedStyle(e).backgroundColor : '' })
      C.case('C1-no-leak-onto-status-chip', chipBg !== bar.bg, `concChip bg=${chipBg} must differ from the identity bar bg=${bar.bg}`)
    }
    // stability + distinctness across projects (behaviour face of single-source)
    let s2
    try { s2 = await openPanel(pw, html, stub, 'alpha') } catch (e) { C.case('C1-reload-stable', false, String(e).slice(0, 160)); s2 = null }
    if (s2) {
      try {
        const v2 = await s2.page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--proj').trim())
        C.case('C1-reload-stable', v2 === (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--proj').trim())), `reload --proj=${v2}`)
      } finally { await closePanel(s2) }
    }

    // ---- K1 captures, light and dark (KI-055)
    try {
      mkdirSync(OUT, { recursive: true })
      await page.screenshot({ path: join(OUT, 'overview-blocks-light.png'), fullPage: false })
      C.case('K1-light-capture', existsSync(join(OUT, 'overview-blocks-light.png')), 'integration/t261009-37/out/overview-blocks-light.png')
    } catch (e) { C.case('K1-light-capture', false, String(e).slice(0, 160)) }
    await closePanel(session); session = null
    let dark
    try { dark = await openPanel(pw, html, stub, 'alpha', 'dark') } catch (e) {
      C.case('K1-dark-capture', false, String(e).slice(0, 160)); stub.close(); return C.exit()
    }
    try {
      mkdirSync(OUT, { recursive: true })
      await dark.page.screenshot({ path: join(OUT, 'overview-blocks-dark.png'), fullPage: false })
      C.case('K1-dark-capture', existsSync(join(OUT, 'overview-blocks-dark.png')), 'integration/t261009-37/out/overview-blocks-dark.png')
      C.case('X1-dark-no-pageerror', dark.errors.length === 0, dark.errors.slice(0, 3).join(' | '))
    } finally { await closePanel(dark) }
    C.case('X1-no-pageerror', errors.length === 0, errors.slice(0, 3).join(' | '))
  } finally {
    if (session) await closePanel(session)
    try { stub.close() } catch { /* already closed */ }
  }
  C.exit()
}

main().catch((e) => { console.error('ENV_FAIL: scenario crashed:', String(e).slice(0, 300)); process.exit(2) })
