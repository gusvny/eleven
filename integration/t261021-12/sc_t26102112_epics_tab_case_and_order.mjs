/**
 * sc_t26102112_epics_tab_case_and_order.mjs — t261021-12: the Epics tab reads
 * in normal case and is ordered by each epic's most recently modified ticket.
 *
 * Grey-box L3 (integration-owned), real browser + page-boundary API stubs,
 * offline seconds, zero docker/Temporal, never touches 3099 (t261003-06 /
 * t261008-20 seam family: the served body is the production PANEL_PAGE_HTML
 * export, API edges stubbed at the fetch boundary).
 *
 * User-perceivable contract under test (ticket t261021-12, host order 261021):
 *   A THE CASE — on the Epics tab the epic code, the summary line, a ticket
 *     title and a meta/counts line render in normal case (computed style
 *     text-transform: none); a REAL section heading stays uppercase.
 *   B THE ORDER — the epic list is ordered by each epic's most recently
 *     modified ticket, descending (max of the ticket last-modified values),
 *     regardless of the source list order; an epic with no readable tickets
 *     sorts LAST and its row says no activity was read (never a fabricated
 *     time, never a bogus relative value).
 *   C THE TICKET LIST — inside an epic the tickets read newest-first by the
 *     same last-modified field; a row with a malformed time sorts last and
 *     breaks nothing.
 *   D SANITY — the newest epic's relative time reads as recent (just
 *     now / minutes), not a garbage value in days; zero pageerror.
 *
 * Intent split (no intent-level duplication): the payload's boundary
 * conversion + absent rule belong to sc_t26102112_epic_tickets_time_payload
 * (the endpoint face); the /api/epics list shape belongs to
 * t261019-12-epics-api-store-move; the tab strip order belongs to
 * t261005-10-ui2-panel-tab-order-contract; the epics tab listing rows / detail
 * walk-back belongs to t261005-10-ui2-epics-docs-metrics-tabs-journey (it owns
 * presence and degradation, NOT case or activity ordering — this entry's
 * unique object). Page-side sort-helper truth tables are developer L1.
 *
 * Pre-implement tree: A and B red (uppercase card, all epics tie) = the named
 * TDD signal; green required at the integration gate / merge.
 * playwright-core/chromium missing = ENV_FAIL exit 2 (KI-036 family);
 * page module missing = FAIL named (TDD red). PASS/FAIL/ENV_FAIL only.
 */

import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const C = makeCase()
const PROJ = 'alpha'
const NOW = Date.now()
const S = 1000

// Source list deliberately in the WRONG order: no-activity epic first, older
// epic second, newest epic last. A pass proves the render ordered by activity.
const EPICS = [
  { code: 'epic-quiet', retired: false, summary: 'Quiet epic with no readable tickets.', started: '2026-10-01' },
  { code: 'epic-older', retired: false, summary: 'Older epic, last touched a day ago.', started: '2026-10-02' },
  { code: 'epic-new', retired: false, summary: 'Newest epic, touched moments ago.', started: '2026-10-03' },
]
// Ticket times are in MILLISECONDS — the payload shape after the boundary
// conversion (the conversion itself is owned by the payload scenario).
const TICKETS = {
  'epic-new': [
    { id: 't-n2', title: 'Just touched', status: 'running', stage: 'implement', stage_state: 'running', updated_ts: NOW - 30 * S },
    { id: 't-n1', title: 'Touched an hour ago', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: NOW - 3600 * S },
  ],
  'epic-older': [
    { id: 't-o1', title: 'Touched a day ago', status: 'closed', stage: 'verify', stage_state: 'awaiting', updated_ts: NOW - 86400 * S },
    { id: 't-o2', title: 'Malformed time row', status: 'open', stage: 'plan', stage_state: 'awaiting', updated_ts: 'bogus' },
  ],
  'epic-quiet': [],
}

function mainRepoRoot() {
  try {
    const common = execFileSync('git', ['rev-parse', '--git-common-dir'], { cwd: fileURLToPath(new URL('../..', import.meta.url)), encoding: 'utf8', timeout: 5000 }).trim()
    if (common) return resolve(fileURLToPath(new URL('../..', import.meta.url)), common, '..')
  } catch { /* not a worktree */ }
  return fileURLToPath(new URL('../..', import.meta.url))
}
async function loadPlaywright() {
  const main = mainRepoRoot()
  for (const sub of ['server/ui-check/node_modules/playwright-core/index.mjs', 'server/plugins/workbench/node_modules/playwright-core/index.mjs']) {
    const p = join(main, sub)
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts lacks the PANEL_PAGE_HTML export (seam contract; TDD-phase red expected)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }

  const json = (res, code, obj) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj)) }
  const stub = createServer((req, res) => {
    const u = new URL(req.url ?? '/', 'http://x')
    if (u.pathname === '/' || u.pathname === '/panel') {
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
      res.end(pageMod.PANEL_PAGE_HTML)
      return
    }
    if (u.pathname === '/sandbar-workbench/api/epics') {
      json(res, 200, { ok: true, result: { count: EPICS.length, epics: EPICS } })
      return
    }
    const m = u.pathname.match(/^\/sandbar-workbench\/api\/epics\/([^/]+)\/tickets$/)
    if (m) {
      const code = decodeURIComponent(m[1])
      if (code in TICKETS) json(res, 200, { ok: true, result: { code, count: TICKETS[code].length, buckets: {}, tickets: TICKETS[code] } })
      else json(res, 200, { ok: true, result: { code, degraded: true, reason: 'not stubbed' } })
      return
    }
    // Every other edge the page probes degrades honestly; nothing here may crash it.
    json(res, 404, { ok: false, error: 'not stubbed: ' + u.pathname })
  })
  await new Promise((res, rej) => { stub.once('error', rej); stub.listen(0, '127.0.0.1', () => res()) })
  const base = `http://127.0.0.1:${stub.address().port}`

  const browser = await pw.chromium.launch({ headless: true }).catch(() => null)
  if (!browser) { C.envFail('chromium-present', 'chromium missing (KI-036 family)'); stub.close(); return C.exit() }
  const page = await browser.newPage()
  const pageErrors = []
  page.on('pageerror', (e) => pageErrors.push(String(e)))

  try {
    await page.goto(base + '/', { waitUntil: 'domcontentloaded' })
    // Testability seam (the page's own declared seam): pick the project, which
    // triggers the epics load; then switch to the Epics tab.
    await page.evaluate(() => window.__panelSelect('alpha'))
    await page.evaluate(() => { const l = document.querySelector('label[for="t-epics"]'); if (l) l.click() })
    await page.waitForSelector('[data-epic-head="epic-new"]', { timeout: 8000 })
    await page.waitForSelector('[data-ticket="t-n2"]', { timeout: 8000 }).catch(() => {})

    // ---- A: the case face ----
    const tx = (sel) => page.$eval(sel, (el) => getComputedStyle(el).textTransform)
    // Every epic card head's code <b>, the summary line, a ticket title, a meta line.
    const cardSels = [
      ['[data-epic-head="epic-new"] b', 'epic code'],
      ['[data-epic-head="epic-new"] ~ .sum', 'summary line'],
    ]
    for (const [sel, label] of cardSels) {
      const el = await page.$(sel)
      if (!el) { C.case('case-normal-' + label, false, 'anchor missing: ' + sel); continue }
      C.case('case-normal-' + label, (await tx(sel)) === 'none',
        `text-transform=${await tx(sel)} (want none)`)
    }
    // Expand the newer epic (cards are single-open) and check a ticket title,
    // its meta line and the epic head counts line.
    await page.evaluate(() => { const h = document.querySelector('[data-epic-head="epic-new"]'); if (h) h.click() })
    await page.waitForSelector('[data-ticket="t-n2"]', { timeout: 8000 })
    for (const [sel, label] of [
      ['[data-ticket="t-n2"] b', 'ticket title'],
      ['[data-ticket="t-n2"] .meta', 'ticket meta line'],
      ['[data-epic-head="epic-new"] .meta', 'epic head counts line'],
    ]) {
      const el = await page.$(sel)
      if (!el) { C.case('case-normal-' + label, false, 'anchor missing: ' + sel); continue }
      C.case('case-normal-' + label, (await tx(sel)) === 'none',
        `text-transform=${await tx(sel)} (want none)`)
    }
    // A REAL section heading stays uppercase (the Overview's section head lives
    // in the DOM on every tab; text-transform resolves even while its pane hides).
    const headTx = await page.$eval('#waitHead', (el) => getComputedStyle(el).textTransform)
    C.case('case-heading-stays-uppercase', headTx === 'uppercase', `#waitHead text-transform=${headTx} (want uppercase)`)

    // ---- B: the epic order + the no-activity face ----
    const order = await page.$$eval('[data-epic-head]', (ns) => ns.map((n) => n.dataset.epicHead))
    C.case('order-by-last-activity-desc',
      JSON.stringify(order) === JSON.stringify(['epic-new', 'epic-older', 'epic-quiet']),
      `rendered order=${JSON.stringify(order)} (want newest-first, quiet last; source order was the reverse)`)
    const quietText = await page.$eval('[data-epic-head="epic-quiet"]', (n) => n.parentElement ? n.parentElement.textContent : n.textContent)
      .catch(() => '')
    C.case('no-activity-face', /no activity/i.test(quietText),
      `quiet epic head text=${JSON.stringify(quietText.slice(0, 120))} (want a no-activity face, not a fabricated time)`)

    // ---- C: per-epic ticket list newest-first; malformed last ----
    // Cards are single-open: assert epic-new's order while it is expanded, then
    // expand epic-older (which collapses epic-new) and assert its order there.
    const newOrder = await page.$$eval('[data-epic="epic-new"]', (ns) => ns.map((n) => n.dataset.ticket))
    C.case('tickets-newest-first',
      JSON.stringify(newOrder) === JSON.stringify(['t-n2', 't-n1']),
      `epic-new tickets=${JSON.stringify(newOrder)} (want newest first)`)
    await page.evaluate(() => { const h = document.querySelector('[data-epic-head="epic-older"]'); if (h) h.click() })
    await page.waitForSelector('[data-ticket="t-o1"]', { timeout: 8000 })
    const olderOrder = await page.$$eval('[data-epic="epic-older"]', (ns) => ns.map((n) => n.dataset.ticket))
    C.case('tickets-malformed-sorts-last',
      JSON.stringify(olderOrder) === JSON.stringify(['t-o1', 't-o2']),
      `epic-older tickets=${JSON.stringify(olderOrder)} (want valid first, malformed last)`)

    // ---- D: sanity ----
    const rel = await page.$eval('[data-epic-head="epic-new"]', (n) => n.textContent)
    C.case('rel-time-sane', /just now|\d+m ago/.test(rel) && !/\d{3,}d ago/.test(rel),
      `epic-new head=${JSON.stringify(rel.slice(0, 120))} (want a recent relative time)`)
    C.case('zero-pageerror', pageErrors.length === 0, pageErrors.join(' | ').slice(0, 300))
  } catch (e) {
    C.case('journey-completes', false, String(e && e.stack || e).slice(0, 400))
  } finally {
    await browser.close().catch(() => {})
    stub.close()
  }
  return C.exit()
}

main()
