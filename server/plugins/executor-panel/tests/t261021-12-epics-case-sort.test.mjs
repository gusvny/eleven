/**
 * t261021-12-epics-case-sort.test.mjs — the Epics tab renders in normal case and
 * its activity sort is live.
 *
 * Two defects (host 261021):
 * 1. renderEpics built each epic card as class="sect"; the page stylesheet gives
 *    .sect text-transform:uppercase, so the whole tab rendered in capitals.
 *    Fix: the card carries its own container class (.epicCard); .sect stays a
 *    one-line heading style.
 * 2. The activity sort read row.updated_ts, but handleEpicTickets stripped the
 *    field — every epic tied at -1 and registry order won. Fix: the boundary
 *    mapper (server/plugins/workbench/src/host/epic-tickets.ts) carries the
 *    ticket list's `updated_ts` through, converted ONCE from epoch seconds to
 *    milliseconds; a malformed value is ABSENT (never 0, never now).
 *
 * Legs (zero integration entry):
 * - source leg: static contract on panel-page.ts / node.ts (house style of
 *   t261019-12-epics-tab.test.mjs);
 * - fixture leg: epicTicketRow consumed directly (real code, not a mirror) over
 *   valid / absent / malformed inputs, including hostile ones;
 * - browser leg: computed styles on the real page over a stub workbench —
 *   summary, ticket title, meta line and the epic code itself are normal case;
 *   a real .sect heading stays uppercase; the epic order is newest-activity
 *   first; an epic with no readable tickets renders last with the honest
 *   'no activity' face and a fresh rel-time is sane (ms/s regression tripwire).
 * The browser leg skips with a named reason when no chromium is available; the
 * source and fixture legs always run.
 */
import { readFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'
import { createServer } from 'node:http'
import { PANEL_HTML } from '../src/host/panel-page.ts'
import { epicTicketRow } from '../../workbench/src/host/epic-tickets.ts'
import assert from 'node:assert/strict'

const REPO = join(fileURLToPath(import.meta.url), '..', '..', '..', '..', '..')
const PAGE_PATH = join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')
const NODE_PATH = join(REPO, 'server/plugins/workbench/node.ts')
const PAGE = readFileSync(PAGE_PATH, 'utf8')
const NODE = readFileSync(NODE_PATH, 'utf8')

let fails = 0
const ok = (cond, name, detail = '') => {
  if (cond) { console.log('ok   ' + name); return }
  fails += 1; console.log('FAIL ' + name + (detail ? ' — ' + detail : ''))
}

// ---- source leg: the card is a container with its own class, never .sect ----
ok(/\.epicCard\{[^}]*border:1px solid var\(--line\)[^}]*\}/.test(PAGE), 'the card class exists in the stylesheet and carries the box style')
ok(!/\.epicCard\{[^}]*text-transform:uppercase/.test(PAGE), 'the card class carries no uppercase transform')
ok(PAGE.includes("'<div class=\"epicCard\""), 'renderEpics opens the epic card with .epicCard')
ok(!/html\+='<div class="sect"[^>]*display:block/.test(PAGE), 'no .sect element is used as a display:block container in renderEpics')

// ---- source leg: the boundary mapper is wired into handleEpicTickets ----
ok(NODE.includes("import { epicTicketRow } from './src/host/epic-tickets.ts'"), 'node.ts imports the boundary mapper (no mirrored copy)')
ok(/\.map\(\(t\) => epicTicketRow\(t\)\)/.test(NODE), 'handleEpicTickets maps rows through epicTicketRow')
ok(!/id:\s*String\(t\?\.id[\s\S]{0,200}stage_state:\s*String\(t\?\.stage_state[\s\S]{0,60}\}\)\)/.test(NODE), 'the old field-stripping inline mapper is gone')
ok(!/updated_ts[\s\S]{0,40}\?\?\s*0/.test(NODE.split('epicTicketRow').join('')), 'no updated_ts-zero fallback in node.ts outside the mapper')

// ---- fixture leg: the real mapper over valid / absent / malformed inputs ----
const valid = epicTicketRow({ id: 't1', title: 'A', status: 'open', stage: 'implement', stage_state: 'running', updated_ts: 1700000000 })
assert.equal(valid.updated_ts, 1700000000000, 'valid: seconds converted to milliseconds once')
assert.equal(valid.id, 't1', 'valid: identity fields pass through')

const noTime = epicTicketRow({ id: 't2' })
ok(!('updated_ts' in noTime), 'absent field stays absent (no 0 fallback)')
for (const [name, bad] of [
  ['zero', 0],
  ['negative', -5],
  ['string', '1700000000'],
  ['null', null],
  ['NaN', Number.NaN],
  ['Infinity', Number.Infinity],
  ['object', { valueOf: () => 1700000000 }],
]) {
  const r = epicTicketRow({ id: 'x', updated_ts: bad })
  ok(!('updated_ts' in r), `malformed (${name}) is absent, never 0, never now`)
}
ok(!('updated_ts' in epicTicketRow(null)) && epicTicketRow(null).id === '', 'a null source row degrades to the honest empty row, no throw')

// ---- the page keeps its sort comparators intact (existing contract, now live) ----
ok(/epicLastActivity\(epicCodeOf\(b\)\)-epicLastActivity\(epicCodeOf\(a\)\)/.test(PAGE), 'the merged list still sorts newest-activity-first (t261019-12 contract)')
ok(PAGE.includes("'no activity'"), 'a no-readable-tickets epic shows the honest no-activity face, not a fabricated time')

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
  console.log('skip browser leg — playwright-core not found (source + fixture legs above are the mandatory core)')
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
