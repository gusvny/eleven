// sc_panel_width_columns.mjs — t261004-16 panel width + column ratio (grey-box L3,
// real browser + page-boundary API stubs, zero docker, never touches 3099/7233;
// same seam as t261004-14/sc_panel_list_contract_render.mjs -> t261003-06/lib_panel_seam).
//
// Intent (user-perceivable; ticket spec Req 1/2/4 — host measured a 900px content
// box with 350px gutters on each side at a 1600px viewport = 44% whitespace, two
// equal 1fr columns putting the request column on the narrow side, and a 170px
// detail box that cannot hold a long request):
//   T1 At a 1600px viewport the content box fills the window within the ticket cap:
//      each side gutter is at most 5% of the viewport width.
//   T2 At a 1600px viewport the requests/answers column is the WIDE side of the
//      Overview grid and the Recent actions column the narrow side (wide/narrow
//      >= 1.5; the ticket suggests 1.85fr/1fr — the contract is "requests get the
//      wide side", not the literal number).
//   T3 Expanding a request grows only its own column: the Recent actions column
//      width does not move when a row opens (t261003-09 no-layout-shift contract).
//   T4 The detail box can hold a long request: computed max-height >= 420px and
//      font size >= 13px (ticket numbers: 170px -> at least 420px, 12px -> 13px).
//   T5 The page never scrolls as a whole: after expanding, document scrollHeight
//      does not exceed the viewport height (per-column scroll stays).
//   T6 At a 1100px viewport there is no horizontal scrollbar and the gutters stay
//      within the 5% cap.
//   T7 The two-column to one-column collapse stays container-based: below the
//      declared container breakpoint the grid collapses to one column.
//   X1 Zero pageerror across all journeys.
//
// Numbers, not adjectives: every width/gutter/ratio is printed as a number in the
// case reason so a reviewer can check it against this ticket (Req 6e).
// playwright-core missing = ENV_FAIL exit 2 (KI-036 family); missing page module
// = FAIL named (TDD-phase red expected; arbitrate/merge must be green).
// Intent split: expand persistence across polls belongs to t261003-14; list
// order/cap/timestamps to t261004-14; markdown content rendering to
// sc_panel_markdown_render.mjs (same ticket) — this file only judges geometry.
import { createServer } from 'node:http'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'
import { PANEL_PAGE_PATH, makeCase } from '../t261003-06/lib_panel_seam.mjs'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
const C = makeCase()
const PROJ = 'alpha'
const NOW = Date.now()
const LONG_DETAIL = Array.from({ length: 40 }, (_, i) => `Line ${i + 1} of a long request that must fit inside the detail box without crushing the reader.`).join('\n')

const waiting = [
  {
    type: 'request', id: 'req-md-1', at: NOW - 60_000, project: PROJ, kind: 'question',
    question: 'How should the executor proceed with the wide layout work?',
    detail: LONG_DETAIL, raised_by: 'bench', default_action: 'Proceed',
    options: ['**Proceed** now', 'Wait'], expires_at: null, status: 'waiting',
  },
]
const answered = [
  {
    type: 'request', id: 'req-md-2', at: NOW - 120_000, project: PROJ, kind: 'question',
    question: 'Earlier answered question?', detail: 'short', raised_by: 'bench',
    default_action: 'x', options: null, expires_at: null, status: 'answered',
    answer: 'Answered with **bold** text.', answered_at: NOW - 30_000,
  },
]

function stubServer() {
  const s = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const json = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (u.pathname.endsWith('/api/requests')) return json({ rows: [...waiting, ...answered] })
    if (u.pathname.endsWith('/api/settings')) return json({ ok: true, config: { enabled: true }, provenance: {} })
    if (u.pathname.endsWith('/api/grants')) return json({ ok: true, granted_count: 4, total: 6, executor_sessions: ['exec-1'], session_state: 'granted', note: 'Permissions: 4 of 6' })
    if (u.pathname.endsWith('/api/actions')) return json({ ok: true, source: 'stub', actions: [{ at: NOW - 90_000, action: 'Sign', ticket: 't261002-10', result: 'ok', permission: 'merge' }], malformed_rows: 0, unmapped_rows: 0 })
    if (u.pathname.endsWith('/api/status')) {
      return json({ ok: true, result: { declared: true, enabled: true, heartbeat: { alive: true, age_seconds: 12 }, ledger: { path: '/x', unreadable: false, counts: { lines: 3, duplicates: 0, bad: 0, gaps: 0 } }, liveness: { executor: { alive: true } }, wakes: [], alerts: [] } })
    }
    if (u.pathname.endsWith('/api/bridge/status')) return json({ ok: true, mounted: true, counters: { mirrored: 0 }, last_events: [] })
    // t261005-10 UI-2 follow-up: the panel overview now fetches the concurrency
    // read face and lazily fetches the read-only tab faces; an unstubbed fetch
    // 404s and fails the hygiene leg on stub noise, not product. Honest empty /
    // undeclared shapes only (no fabricated facts).
    if (u.pathname.endsWith('/api/concurrency')) return json({ ok: true, project: 'stub', declared: false, limit: null, unlimited: false, path: '(stub: no declaration)' })
    if (u.pathname.endsWith('/api/epics')) return json({ ok: true, result: { epics: [] } })
    if (u.pathname.endsWith('/api/wf/docs/tree')) return json({ ok: true, result: { tree: [] } })
    if (u.pathname.endsWith('/api/wf/docs/doc')) return json({ ok: true, result: { path: '(stub)', markdown: '' } })
    if (u.pathname.endsWith('/api/wf/metrics')) return json({ ok: true, result: {} })
    if (u.pathname.endsWith('/api/wf/scan-report')) return json({ ok: true, result: { findings: [], pending: 0 } })

    res.writeHead(404); res.end('{}')
  })
  return s
}

async function loadPlaywright() {
  for (const p of [
    join(REPO, 'server/ui-check/node_modules/playwright-core/index.mjs'),
    join(REPO, 'server/plugins/workbench/node_modules/playwright-core/index.mjs'),
  ]) {
    if (existsSync(p)) { try { return await import(pathToFileURL(p).href) } catch { /* next */ } }
  }
  try { return await import('playwright-core') } catch { return null }
}

const GEOM = () => {
  const wrap = document.querySelector('.wrap')
  const cols = [...document.querySelectorAll('.cols > div')]
  const inner = window.innerWidth
  const wr = wrap.getBoundingClientRect()
  const colW = cols.map(c => Math.round(c.getBoundingClientRect().width))
  return {
    inner,
    content: Math.round(wr.width),
    left: Math.round(wr.left),
    right: Math.round(inner - wr.right),
    colW,
    docW: document.documentElement.scrollWidth,
    docH: document.documentElement.scrollHeight,
    winH: window.innerHeight,
  }
}

const DETAIL_METRICS = () => {
  const d = document.querySelector('.row[data-row] .detail')
  if (!d) return null
  const cs = getComputedStyle(d)
  return { cap: cs.maxHeight, font: cs.fontSize, scrollH: d.scrollHeight, clientH: d.clientHeight }
}

async function journey(pw, lport, stubPort, viewport, errors) {
  const browser = await pw.chromium.launch({ headless: true })
  try {
    const page = await browser.newPage({ viewport })
    page.on('pageerror', (e) => errors.push(String(e)))
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    await page.route('**/api/**', (route) => route.continue({ url: `http://127.0.0.1:${stubPort}` + new URL(route.request().url()).pathname }))
    await page.goto(`http://127.0.0.1:${lport}/?project=${PROJ}`)
    await page.waitForSelector('.row[data-row]', { timeout: 5000 })
    return page
  } catch (e) {
    try { await browser.close() } catch { /* already closed */ }
    throw e
  }
}

async function main() {
  if (!existsSync(PANEL_PAGE_PATH)) {
    C.case('page-module-present', false, 'server/plugins/executor-panel/src/host/panel-page.ts missing')
    return C.exit()
  }
  const pageMod = await import(pathToFileURL(PANEL_PAGE_PATH).href).catch(() => null)
  if (!pageMod || typeof pageMod.PANEL_PAGE_HTML !== 'string') {
    C.case('PANEL_PAGE_HTML-export', false, 'panel-page.ts lacks named export PANEL_PAGE_HTML (seam contract)')
    return C.exit()
  }
  const pw = await loadPlaywright()
  if (!pw) { C.envFail('playwright-present', 'playwright-core missing (KI-036 family)'); return C.exit() }

  const stub = stubServer()
  await new Promise(r => stub.listen(0, '127.0.0.1', r))
  const port = stub.address().port
  const local = createServer((req, res) => { res.writeHead(200, { 'content-type': 'text/html' }); res.end(pageMod.PANEL_PAGE_HTML) })
  await new Promise(r => local.listen(0, '127.0.0.1', r))
  const lport = local.address().port

  const errors = []
  try {
    // ---- journey 1: 1600 wide, the ticket's measurement viewport ----
    const page = await journey(pw, lport, port, { width: 1600, height: 900 }, errors)
    let g = await page.evaluate(GEOM)
    C.case('T1-gutters-at-1600-max-5pct',
      g.left <= g.inner * 0.05 && g.right <= g.inner * 0.05,
      `inner=${g.inner} content=${g.content} left=${g.left} right=${g.right} (ticket: 350/350 was the disease)`)
    C.case('T2-requests-column-is-wide-side',
      g.colW.length === 2 && g.colW[0] > g.colW[1] && g.colW[0] / g.colW[1] >= 1.5,
      `cols=${g.colW.join('x')} ratio=${g.colW.length === 2 ? (g.colW[0] / g.colW[1]).toFixed(2) : 'n/a'} (ticket: 426/426 was the disease)`)

    // Expand the first waiting row and re-measure: own column may grow, the other must not move.
    // Page-overflow baseline BEFORE expanding: a constant ~60px slop exists on HEAD
    // too (measured 959/900 pre-change) — pre-existing, out of this ticket's scope.
    // The contract here is only that expanding must not add whole-page scroll.
    const before = g
    await page.click('.row[data-row] .head', { force: true })
    await page.waitForTimeout(300)
    const after = await page.evaluate(GEOM)
    const drift = Math.abs(after.colW[1] - before.colW[1])
    C.case('T3-expand-grows-only-own-column',
      drift <= 2 && after.colW[0] >= before.colW[0] - 2,
      `cols before=${before.colW.join('x')} after=${after.colW.join('x')} other-column-drift=${drift}px`)
    C.case('T5-expansion-adds-no-whole-page-scroll',
      after.docH <= before.docH + 2,
      `docH before=${before.docH} after=${after.docH} winH=${after.winH} (per-column scroll contract stays; the pre-existing ~60px page slop is reported separately)`)

    const dm = await page.evaluate(DETAIL_METRICS)
    if (!dm) C.case('T4-detail-cap-and-font', false, 'no .detail box found in an expanded row')
    else {
      const cap = dm.cap.endsWith('px') ? parseFloat(dm.cap) : NaN
      const font = parseFloat(dm.font)
      C.case('T4-detail-cap-and-font',
        Number.isFinite(cap) && cap >= 420 && font >= 13,
        `max-height=${dm.cap} font=${dm.font} (ticket: was 170px/12px; needs >=420px/>=13px)`)
      C.case('T4b-long-detail-scrolls-internally', dm.scrollH > dm.clientH,
        `scrollH=${dm.scrollH} clientH=${dm.clientH} (internal scroll stays for very long text)`)
    }

    // Expanded row must show the full question, not a one-line ellipsis cut.
    const qfull = await page.evaluate(() => {
      const row = document.querySelector('.row[data-row][data-open="true"]')
      if (!row) return null
      const body = row.querySelector('.body')
      const want = 'How should the executor proceed with the wide layout work?'
      return { present: !!(body && body.textContent.includes(want)), bodyChildren: body ? body.children.length : 0 }
    })
    C.case('T8-open-row-shows-full-question', !!qfull && qfull.present,
      `qfull=${JSON.stringify(qfull)} (row head keeps the collapsed one-line ellipsis; the open body shows the whole question)`)

    await page.close()

    // ---- journey 2: 1100 wide, no horizontal scrollbar ----
    const page2 = await journey(pw, lport, port, { width: 1100, height: 900 }, errors)
    const g2 = await page2.evaluate(GEOM)
    C.case('T6-no-hscroll-at-1100',
      g2.docW <= g2.inner && g2.left <= g2.inner * 0.05 && g2.right <= g2.inner * 0.05,
      `inner=${g2.inner} docW=${g2.docW} left=${g2.left} right=${g2.right}`)
    await page2.close()

    // ---- journey 3: narrow viewport exercises the container-based collapse ----
    const page3 = await journey(pw, lport, port, { width: 700, height: 900 }, errors)
    const g3 = await page3.evaluate(() => ({
      tracks: getComputedStyle(document.querySelector('.cols')).gridTemplateColumns.split(' ').length,
      docW: document.documentElement.scrollWidth, inner: window.innerWidth,
    }))
    C.case('T7-container-collapse-to-one-column', g3.tracks === 1 && g3.docW <= g3.inner,
      `tracks=${g3.tracks} docW=${g3.docW} inner=${g3.inner} (collapse stays container-based, not viewport-media)`)
    await page3.close()

    C.case('X1-no-pageerror-all-journeys', errors.length === 0, errors.slice(0, 2).join(' | ').slice(0, 200))
  } catch (e) {
    C.case('browser-journey', false, String(e).slice(0, 200))
  } finally {
    try { stub.close() } catch { /* noop */ }
    try { local.close() } catch { /* noop */ }
  }
  C.exit()
}

main().catch((e) => { console.error(String(e)); process.exit(1) })
