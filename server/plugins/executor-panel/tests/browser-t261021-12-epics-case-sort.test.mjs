/**
 * browser-t261021-12-epics-case-sort.test.mjs — the served-page leg of the
 * t261021-12 pair: the Epics tab renders in normal case and its activity sort
 * is live (L3 scenario: a real browser against a stub workbench, isolated port,
 * never 3099/7233).
 *
 * Split note (t261103-27): this leg launched a real browser from inside a file
 * whose name claimed to be pure, so the executor's fail-closed guard refused the
 * whole executor-panel --pure fast lane. The two cheap legs (source contract and
 * fixture) stayed in t261021-12-epics-case-sort.test.mjs; this file carries the
 * browser leg under the name that says so.
 *
 * Two defects (host 261021) — the same two the pure file states:
 * 1. renderEpics built each epic card as class="sect"; the page stylesheet gives
 *    .sect text-transform:uppercase, so the whole tab rendered in capitals.
 * 2. The activity sort read row.updated_ts, but handleEpicTickets stripped the
 *    field — every epic tied at -1 and registry order won.
 *
 * What this leg locks (all user-visible; no internals are read): computed styles
 * on the real page over a stub workbench — summary, ticket title, meta line and
 * the epic code itself are normal case; a real .sect heading stays uppercase;
 * the epic order is newest-activity first; an epic with no readable tickets
 * renders last with the honest 'no activity' face, and a fresh rel-time is sane
 * (ms/s regression tripwire).
 *
 * The leg skips with a named reason when no chromium is available.
 */
import { existsSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { createServer } from 'node:http'
import { PANEL_HTML } from '../src/host/panel-page.ts'

const REPO = join(fileURLToPath(import.meta.url), '..', '..', '..', '..', '..')

let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

// ---- browser leg ----
const EPICS = [
  { code: 'epic-old', retired: false, summary: 'An old epic', started: '09-01' },
  { code: 'epic-new', retired: false, summary: 'A fresh epic', started: '09-02' },
  { code: 'epic-silent', retired: false, summary: 'No readable tickets here', started: '09-03' },
]
const NOW = Date.now()
const TICKETS = {
  'epic-new': [
    { id: 't-new-a', title: 'Newest ticket alpha', status: 'open', stage: 'implement', stage_state: 'running', updated_ts: Math.floor((NOW - 20 * 1000) / 1000) },
    { id: 't-new-b', title: 'Older ticket beta', status: 'open', stage: 'develop', stage_state: 'awaiting-human', updated_ts: Math.floor((NOW - 3 * 3600 * 1000) / 1000) },
  ],
  'epic-old': [
    { id: 't-old-a', title: 'Yesterday ticket', status: 'closed', stage: 'integrate', stage_state: 'done', updated_ts: Math.floor((NOW - 30 * 3600 * 1000) / 1000) },
  ],
  // malformed leg: a garbage time must be absent — the epic then reads 'no activity'
  // and sorts last, never showing a fabricated clock value.
  'epic-silent': [
    { id: 't-sil-a', title: 'Broken clock ticket', status: 'open', stage: 'develop', stage_state: 'awaiting', updated_ts: 'not-a-number' },
  ],
}
const PANEL_ROUTE = '/sandbar-executor-panel'
const panelServer = createServer((req, res) => {
  const u = new URL(req.url ?? '/', 'http://x')
  const json = (code, body) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(body)) }
  if (u.pathname === PANEL_ROUTE || u.pathname === PANEL_ROUTE + '/') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' })
    res.end(PANEL_HTML)
    return
  }
  // The page fetches the epics face same-origin: serve the stub payloads here.
  if (u.pathname === '/sandbar-workbench/api/epics') return json(200, { ok: true, result: { count: EPICS.length, epics: EPICS } })
  const m = u.pathname.match(/^\/sandbar-workbench\/api\/epics\/([a-z0-9-]+)\/tickets$/)
  if (m) {
    // The stub mimics the PRODUCTION endpoint output, i.e. the post-mapper shape:
    // updated_ts already converted to milliseconds at the boundary (handleEpicTickets),
    // malformed values absent — the page never converts units itself.
    const rows = (TICKETS[m[1]] ?? []).map((t) => {
      const r = { ...t }
      if (typeof r.updated_ts === 'number' && r.updated_ts > 0) r.updated_ts = r.updated_ts * 1000
      else delete r.updated_ts
      return r
    })
    return json(200, { ok: true, result: { code: m[1], count: rows.length, tickets: rows } })
  }
  // Every other panel API the page polls may 404 — each loader catches its own
  // failure and never takes the Epics face down with it.
  return json(404, { ok: false, error: 'test page server: no route for ' + u.pathname })
})
await new Promise((r) => panelServer.listen(0, '127.0.0.1', r))
const pageBase = 'http://127.0.0.1:' + panelServer.address().port

function findPlaywrightCore() {
  let dir = REPO
  for (let i = 0; i < 8 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  return null
}
const pwPath = findPlaywrightCore()
if (!pwPath) {
  console.log('skip browser leg — playwright-core not found (the pure legs live in t261021-12-epics-case-sort.test.mjs)')
} else {
  try {
    const { createRequire } = await import('node:module')
    const require = createRequire(import.meta.url)
    const playwright = require(pwPath)
    let browser
    try { browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
    catch { browser = await playwright.chromium.launch({ headless: true }) }
    const page = await browser.newPage()
    page.setDefaultTimeout(15000)
    await page.goto(pageBase + PANEL_ROUTE + '?project=rodalpha')
    await page.click('label[for=t-epics]')
    await page.waitForSelector('.epicCard', { timeout: 15000 })
    await page.waitForFunction(() => document.querySelectorAll('.epicCard').length === 3, { polling: 200 })

    // Expand the top card so ticket rows exist, then measure inside them.
    await page.click('.epicCard .eh[data-epic-head="epic-new"]')
    await page.waitForSelector('.epicCard .mrow .lab b')
    const styles = await page.evaluate(() => {
      const tt = (sel) => { const n = document.querySelector(sel); return n ? getComputedStyle(n).textTransform : 'MISSING:' + sel }
      const card = document.querySelector('.epicCard')
      return {
        card: getComputedStyle(card).textTransform,
        code: tt('.epicCard .eh b'),
        summary: tt('.epicCard .sum'),
        ticketTitle: tt('.epicCard .mrow .lab b'),
        meta: tt('.epicCard .eh .meta'),
        heading: tt('#epicsList .sect.lead') !== 'MISSING:#epicsList .sect.lead' ? tt('#epicsList .sect.lead') : tt('.sect.lead'),
      }
    })
    ok(styles.card === 'none', 'the card itself inherits normal case', styles.card)
    ok(styles.code === 'none', 'the epic code renders normal case (computed)', styles.code)
    ok(styles.summary === 'none', 'the summary line renders normal case (computed)', styles.summary)
    ok(styles.ticketTitle === 'none', 'a ticket title renders normal case (computed)', styles.ticketTitle)
    ok(styles.meta === 'none', 'a meta/count line renders normal case (computed)', styles.meta)
    ok(styles.heading === 'uppercase', 'a real section heading stays uppercase (computed)', styles.heading)

    // Order: newest activity first; the no-readable-tickets epic last, honest face.
    const order = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.epicCard .eh b')).map((n) => n.textContent))
    ok(order.join(',') === 'epic-new,epic-old,epic-silent', 'epics sort by most recently modified ticket, descending', order.join(','))
    const lastRow = await page.evaluate(() => {
      const cards = document.querySelectorAll('.epicCard')
      const last = cards[cards.length - 1]
      return last ? last.querySelector('.eh .meta:last-child').textContent : ''
    })
    ok(lastRow === 'no activity', 'the epic with no readable time says no activity was read (not a fabricated time)', lastRow)

    // ms/s tripwire: a ticket modified ~20s ago must render a SHORT rel-time
    // (a seconds-vs-milliseconds regression renders thousands of days).
    const firstRel = await page.evaluate(() => {
      const card = document.querySelector('.epicCard')
      return card.querySelector('.eh .meta:last-child').textContent
    })
    ok(['just now', '1m ago', '2m ago'].includes(firstRel), 'a fresh ticket renders a sane short rel-time (unit regression tripwire)', firstRel)

    // Screenshot evidence for the UI ticket.
    const shotDir = join(REPO, '.sandbar/screenshots')
    mkdirSync(shotDir, { recursive: true })
    await page.screenshot({ path: join(shotDir, 't261021-12-epics-normal-case.png'), fullPage: false })
    ok(existsSync(join(shotDir, 't261021-12-epics-normal-case.png')), 'after-screenshot saved to .sandbar/screenshots/')

    await browser.close()
  } catch (err) {
    console.log('skip browser leg — ' + String(err instanceof Error ? err.message : err))
  }
}
panelServer.close()

console.log(fails === 0 ? 'done 1' : 'done 0')
process.exit(fails === 0 ? 0 : 1)
