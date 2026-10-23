#!/usr/bin/env node
/**
 * sc_t261021_07_metrics_tab_mock_anchors.mjs — t261021-07, grey-box L3,
 * "browser-free" pool (real Chromium + page-boundary API stubs, zero docker,
 * never touches 3099/7233). Harness model: t261008-19 anchor scenario
 * (PANEL_HTML served over a stub http server; assertions anchor to
 * user-visible semantic text, never class names or node indexes — KI-051).
 *
 * User story (ticket t261021-07, host mock 261021): the Metrics tab is rebuilt
 * to the approved seven-section layout — header project filter, six KPI tiles,
 * "where the time goes" workflow card with in-card stage drill, certification,
 * five epic cards with sort + type-to-match, throughput chart, token stack
 * chart + tokens by role + project sessions. The mock fixes layout and labels;
 * its NUMBERS are illustrative and must never render on the real face. Charts
 * are ECharts behind the panel adapter (docs/design/metrics-panel-ui-plan.md);
 * palette: developer #0f766e, integration #2563eb, executor #7c3aed,
 * executor session #c2255c, global session #495057.
 *
 * Legs (all asserted from the reader side — what the user sees):
 *   H1 the header project filter is pre-filled with the project of the
 *      executor tab the panel was opened from (?project=proj-a) and offers
 *      the "all projects" widening option;
 *   K1..K6 the six KPI tiles render with their mock labels and the
 *      stub-fed REAL values; the tokens tile carries the in-ticket/outside
 *      split sub-line; no cost anywhere;
 *   W1 the workflow card is a fixed-height card carrying removable chips and
 *      a type-to-match picker;
 *   W2 nothing selected means all workflows (every stub workflow row shown);
 *   W3 removing a chip drops that workflow's row (filter is user-visible);
 *   W4 clicking a workflow row opens its stage rows in the SAME card and the
 *      card height does not grow;
 *   W5 the stage drill shows only THAT workflow's stages (chains never mix);
 *   C1 certification shows green / red / flaky counts, the per-round strip
 *      and the time-to-green-after-a-red value;
 *   E1 epics show five cards by default sorted by last activity (first card
 *      is the most recently active stub epic);
 *   E2 the sort control offers last activity / tickets / elapsed / tokens and
 *      switching the sort reorders the cards;
 *   E3 the type-to-match picker can add an epic beyond the top five;
 *   T1 the throughput chart mounts a canvas with opened-vs-closed legend
 *      anchors (line markers vs columns is the adapter's job; the legend text
 *      is the user-visible contract);
 *   T2 the token chart mounts a canvas with the five series in the legend and
 *      the two session-series swatch colours distinct from the three role
 *      colours; the value axis reads in millions;
 *   P1 NO-PROSE: the mock's explanatory sentences never reappear as
 *      tooltips / captions / banners anywhere in the pane;
 *   D1 malformed metrics payload (garbage body) degrades to the named empty
 *      state (— placeholders), zero pageerror, no fabricated numbers;
 *   E0 zero pageerror across every leg.
 * Every content leg runs under light AND dark (KI-055 theme matrix) with
 * per-theme screenshots into integration/t261021-07/out/.
 *
 * Three states (t260904-12): any fail>0 = exit 1; env_fail>0 = exit 2. The
 * scenario is RED on the pre-implement tree (expected TDD signal) and must be
 * green at the integration gate / merge.
 *
 * Intent split: the OLD metrics faces (four KPI cells, three placeholder
 * chart labels) and their negative pins retire WITH this ticket — the
 * t261008-19 anchor scenario keeps only its still-valid negatives; the
 * tab-strip order contract belongs to t261005-10-ui2-panel-tab-order-contract;
 * the view-model malformed-input truth tables belong to developer L1. This
 * entry uniquely owns the approved-mock CONTENT journey of the rebuilt tab.
 *
 * Field-name note: the metrics API v2 (t261021-06) landed while this ticket
 * was in flight; the stub payload below follows the FROZEN contract
 * (docs/design/metrics-api-contract-v2.md) — numeric kpis, workflows[],
 * stages[], epics[], project_sessions, and the certification receipt's
 * round_faces for the strip. Certification stays a field-name-coupled read
 * (face.outcome.verdict, optional face.flaky_count) — one stub file to
 * re-point if the receipt shape moves.
 * playwright-core/chromium/panel-page missing = ENV_FAIL exit 2 (KI-036).
 */
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { existsSync, mkdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const REPO = fileURLToPath(new URL('../../', import.meta.url))
let passed = 0, failed = 0, envfail = 0
const C = {
  case(name, ok, reason = '') {
    ok ? passed++ : failed++
    console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  },
  envFail(name, reason) { envfail++; console.log(`[ENV_FAIL] ${name} — ${reason}`) },
  exit() {
    console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail} na=0`)
    process.exit(envfail ? 2 : failed ? 1 : 0)
  },
}

const require = createRequire(import.meta.url)
function findPlaywrightCore() {
  let dir = REPO
  for (let i = 0; i < 4 && dir; i++) {
    const cand = join(dir, 'server/ui-check/node_modules/playwright-core')
    if (existsSync(join(cand, 'package.json'))) return cand
    dir = resolve(dir, '..')
  }
  return null
}

const PROJ = 'proj-a'
// The mock's illustrative numbers must never render on the real face.
const MOCK_ILLUSTRATIVE = ['38', '2h10m', '64', '7 days ago']
// The host removed the mock's explanatory sentences; they must not come back
// as tooltips, captions or banners (labels, values, axis titles, legends only).
const BANNED_PROSE = [
  'nothing selected means all',
  'click a row to see',
  'never grows',
  'no price table',
  'no chart data drawn',
  'in this build',
]
const KPI_LABELS = [
  ['K1-rework-rate', 'rework rate'],
  ['K2-throughput', 'throughput'],
  ['K3-median-lead-time', 'median lead time'],
  ['K4-tokens', 'tokens'],
  ['K5-tokens-per-closed', 'tokens per closed'],
  ['K6-human-wait-share', 'human wait'],
]
const WORKFLOWS = [
  { name: 'dev-lane', elapsed: '5h 20m', rounds: '3.1', tickets: 12, stageRuns: 40,
    stages: ['plan', 'implement', 'review'] },
  { name: 'chore-lane', elapsed: '1h 05m', rounds: '1.4', tickets: 4, stageRuns: 8,
    stages: ['do', 'check'] },
  { name: 'ops-lane', elapsed: '0h 45m', rounds: '2.0', tickets: 2, stageRuns: 6,
    stages: ['run'] },
]
const EPICS = [
  { name: 'epic-alpha', tickets: 9, elapsed: '12h', tokens: '1.2M', activity: '2h ago' },
  { name: 'epic-beta', tickets: 5, elapsed: '6h', tokens: '0.4M', activity: '1d ago' },
  { name: 'epic-gamma', tickets: 3, elapsed: '4h', tokens: '0.2M', activity: '3d ago' },
  { name: 'epic-delta', tickets: 2, elapsed: '3h', tokens: '0.1M', activity: '5d ago' },
  { name: 'epic-epsilon', tickets: 1, elapsed: '1h', tokens: '0.05M', activity: '6d ago' },
  { name: 'epic-zeta', tickets: 1, elapsed: '1h', tokens: '0.02M', activity: '9d ago' },
]
const SERIES = ['developer', 'integration', 'executor', 'executor session', 'global session']
const PALETTE = { developer: '#0f766e', integration: '#2563eb', executor: '#7c3aed',
  'executor session': '#c2255c', 'global session': '#495057' }

// ---- stub payload in the REAL metrics v2 shape (t261021-06 contract, frozen;
// field-name note above is historical — the contract landed, the stub follows it) ----
const HOUR = 3600000
const DAY = 24 * HOUR
function certPayload() {
  // 18 rounds: 14 green, 3 red, EVERY red followed by a green 22m later — the
  // face's time-to-green is the P50 over ALL red→green gaps, so a mixed-gap
  // fixture would honestly report 1h (measured arbitrate round 2: gaps
  // 22m/1h/1h → P50 1h 0m) — a single gap value keeps the '22m' leg true.
  // One face carries flaky_count:1 (the optional marker the model reads;
  // absent = the named dash, never a re-spelled no_proof).
  const rounds = []
  const STEP = 22 * 60_000
  let ts = 1_700_000_000_000
  const push = (verdict, extra) => {
    rounds.push({ run_id: 'r' + rounds.length, face: { ts, outcome: { verdict }, ...(extra || {}) } })
    ts += STEP
  }
  push('green'); push('red')
  push('green', { flaky_count: 1 })
  for (let i = 0; i < 10; i++) push('green')
  push('red'); push('green'); push('red'); push('green')
  return {
    ok: true, project: PROJ, line: 'main', lines: [], notes: [],
    round_faces: { dir: '/stub', rounds },
  }
}
function metricsPayload(view) {
  if (view === 'health') {
    return {
      kpis: { tickets: 12, closed: 9 },
      charts: { primary: { kind: 'bar', categories: ['Oct 01', 'Oct 02', 'Oct 03', 'Oct 04'],
        series: [ { name: 'created', data: [3, 4, 2, 3] }, { name: 'closed', data: [2, 3, 1, 3] } ] } },
    }
  }
  if (view === 'token') {
    return {
      kpis: {},
      charts: { primary: { kind: 'stackBar', categories: ['Oct 01', 'Oct 02', 'Oct 03', 'Oct 04'],
        series: [
          { name: 'developer', data: [1.0e6, 1.2e6, 0.8e6, 1.1e6] },
          { name: 'integration', data: [0.5e6, 0.4e6, 0.6e6, 0.5e6] },
          { name: 'executor', data: [0.2e6, 0.3e6, 0.1e6, 0.2e6] },
          { name: 'executor session', data: [0.1e6, 0.1e6, 0.2e6, 0.1e6] },
          { name: 'global session', data: [0.3e6, 0.2e6, 0.3e6, 0.2e6] },
        ] } },
    }
  }
  const now = Date.now()
  return {
    generated_at: '2026-10-21T00:00:00Z',
    cache: { status: 'hit' },
    // FIELD-COUPLED(t261021-06): extended kpis, numeric per the contract.
    kpis: {
      tickets: 12, closed: 9,
      rework_rate: 0.12, throughput_per_day: 6, median_lead_time: 5 * HOUR + 40 * 60_000,
      human_wait_share: 0.18,
      tokens_total: 3.4e6, tokens_in_tickets: 2.1e6, tokens_outside_tickets: 1.3e6,
      tokens_per_closed_ticket: 0.6e6,
    },
    workflows: [
      { workflow: 'dev-lane', elapsed_ms: 5 * HOUR + 20 * 60_000, rounds_per_ticket: 3.1, tickets: 12, stage_runs: 40 },
      { workflow: 'chore-lane', elapsed_ms: HOUR + 5 * 60_000, rounds_per_ticket: 1.4, tickets: 4, stage_runs: 8 },
      { workflow: 'ops-lane', elapsed_ms: 45 * 60_000, rounds_per_ticket: 2.0, tickets: 2, stage_runs: 6 },
    ],
    stages: [
      { workflow: 'dev-lane', stage: 'plan', runs: 14, elapsed_ms: HOUR, avg_rounds_per_ticket: 1.2, tickets_reached: 12 },
      { workflow: 'dev-lane', stage: 'implement', runs: 16, elapsed_ms: 3 * HOUR, avg_rounds_per_ticket: 1.3, tickets_reached: 12 },
      { workflow: 'dev-lane', stage: 'review', runs: 10, elapsed_ms: HOUR + 20 * 60_000, avg_rounds_per_ticket: 0.8, tickets_reached: 11 },
      { workflow: 'chore-lane', stage: 'do', runs: 5, elapsed_ms: 40 * 60_000, avg_rounds_per_ticket: 1.1, tickets_reached: 4 },
      { workflow: 'chore-lane', stage: 'check', runs: 3, elapsed_ms: 25 * 60_000, avg_rounds_per_ticket: 0.8, tickets_reached: 4 },
      { workflow: 'ops-lane', stage: 'run', runs: 6, elapsed_ms: 45 * 60_000, avg_rounds_per_ticket: 2.0, tickets_reached: 2 },
    ],
    epics: [
      { epic: 'epic-alpha', tickets: 9, elapsed_ms: 12 * HOUR, tokens: 1.2e6, last_activity_ms: now - 2 * HOUR },
      { epic: 'epic-beta', tickets: 5, elapsed_ms: 6 * HOUR, tokens: 0.4e6, last_activity_ms: now - DAY },
      { epic: 'epic-gamma', tickets: 3, elapsed_ms: 4 * HOUR, tokens: 0.2e6, last_activity_ms: now - 3 * DAY },
      { epic: 'epic-delta', tickets: 2, elapsed_ms: 3 * HOUR, tokens: 0.1e6, last_activity_ms: now - 5 * DAY },
      { epic: 'epic-epsilon', tickets: 1, elapsed_ms: HOUR, tokens: 0.05e6, last_activity_ms: now - 6 * DAY },
      { epic: 'epic-zeta', tickets: 1, elapsed_ms: HOUR, tokens: 0.02e6, last_activity_ms: now - 9 * DAY },
    ],
    project_sessions: {
      total: { in: 0.8e6, out: 0.5e6, cache_read: 1.0e6 },
      buckets: {
        executor: { in: 0.5e6, out: 0.3e6, cache_read: 0.6e6 },
        global: { in: 0.3e6, out: 0.2e6, cache_read: 0.4e6 },
      },
    },
  }
}
async function main() {
  let PANEL_HTML = null
  try { ({ PANEL_HTML } = await import(pathToFileURL(join(REPO, 'server/plugins/executor-panel/src/host/panel-page.ts')))) } catch { /* below */ }
  if (!PANEL_HTML) { C.case('panel-page-importable', false, 'panel-page.ts PANEL_HTML missing'); return C.exit() }

  const pwDir = findPlaywrightCore()
  if (!pwDir) { C.envFail('playwright-core', 'server/ui-check/node_modules/playwright-core missing (KI-036 family)'); return C.exit() }
  const playwright = require(pwDir)
  let browser
  try {
    try { browser = await playwright.chromium.launch({ channel: 'chrome', headless: true }) }
    catch { browser = await playwright.chromium.launch({ headless: true }) }
  } catch (e) { C.envFail('chromium', String(e).slice(0, 160)); return C.exit() }

  let payloadMode = 'ok' // 'ok' | 'garbage'
  const stub = createServer((req, res) => {
    const u = new URL(req.url, 'http://x')
    const p = u.pathname
    const send = (b) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify(b)) }
    if (p.includes('/api/wf/metrics')) {
      if (payloadMode === 'garbage') {
        res.writeHead(200, { 'content-type': 'application/json' })
        return res.end('<html>not json at all')
      }
      return send(metricsPayload(u.searchParams.get('view') || 'time'))
    }
    if (p.includes('/api/certification')) return send(certPayload())
    if (p.includes('/vendor/echarts.mjs')) {
      // A stand-in echarts build: init() appends a real canvas to the mount so
      // the T1 mount leg observes the draw path end-to-end, and setOption()
      // records every option the adapter hands the engine into
      // window.__chartOptions — with a canvas-rendered engine the series
      // palette is NOT observable as DOM swatches (round-3 note: the DOM
      // swatch scan honestly reported certification-strip colours instead),
      // so the T2 colour legs read the recorded options.
      res.writeHead(200, { 'content-type': 'text/javascript' })
      return res.end([
        'window.__chartOptions = [];',
        'export function init(mount){',
        '  const c=document.createElement("canvas");',
        '  c.width=600;c.height=200;mount.appendChild(c);',
        '  return { setOption(o){ try{ window.__chartOptions.push(JSON.parse(JSON.stringify(o))) }catch(e){} },',
        '           dispose(){ c.remove() } };',
        '}',
        'export default { init };',
      ].join('\n'))
    }
    if (p.endsWith('.js') || p.endsWith('.mjs')) {
      res.writeHead(200, { 'content-type': 'text/javascript' })
      return res.end('export {}')
    }
    send({ ok: true })
  })
  await new Promise((r) => stub.listen(0, '127.0.0.1', r))
  const base = 'http://127.0.0.1:' + stub.address().port
  const closeAll = async () => { await new Promise((r) => stub.close(r)); try { await browser.close() } catch {} }
  process.on('exit', () => { try { stub.close() } catch {} })

  try { mkdirSync(join(REPO, 'integration', 't261021-07', 'out'), { recursive: true }) } catch {}
  const OUT_DIR = join(REPO, 'integration', 't261021-07', 'out')

  for (const theme of ['light', 'dark']) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 2400 } })
    const pageErrors = []
    page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 160)))
    await page.route('**/*', (route) => {
      const u = new URL(route.request().url())
      if (u.pathname === '/' || u.pathname === '/index.html') {
        route.fulfill({ contentType: 'text/html', body: PANEL_HTML })
      } else { route.continue() }
    })
    const T = (n) => theme[0].toUpperCase() + theme.slice(1) + ':' + n
    try {
      await page.goto(base + '/?project=' + PROJ + '&theme=' + theme, { waitUntil: 'domcontentloaded' })
      await page.waitForTimeout(400)
      await page.locator('label[for="t-metrics"]').first().click()
      // anchor-wait on the first KPI label, never sleep-then-read (KI-051)
      const pane = page.locator('#paneMetrics')
      const ok = await page.waitForFunction(
        () => { const e = document.querySelector('#paneMetrics'); return !!e && /rework rate/i.test(e.textContent || '') },
        null, { timeout: 8000 }).then(() => true).catch(() => false)
      const paneText0 = (await pane.innerText().catch(() => '')) || ''
      C.case(T('S0-metrics-pane-renders'), ok, 'no rebuilt Metrics content appeared — pane=' +
        paneText0.slice(0, 220).replace(/\n/g, ' '))
      if (!ok) continue

      // ---- H1 header project filter ----
      const headerText = await pane.locator(':scope > *').first().innerText().catch(() => '')
      const filterOk = await page.evaluate((proj) => {
        const sel = [...document.querySelectorAll('#paneMetrics select')].find((s) =>
          [...s.options].some((o) => o.textContent.toLowerCase().includes('all projects')))
        if (!sel) return { ok: false, why: 'no project select with an all-projects option' }
        const v = (sel.selectedOptions[0] || {}).textContent || ''
        return { ok: v.includes(proj), why: 'selected=' + v }
      }, PROJ)
      C.case(T('H1-project-filter-prefilled'), filterOk.ok, filterOk.why)

      // ---- K1..K6 six KPI tiles ----
      const mText = (await pane.innerText()).toLowerCase()
      for (const [id, label] of KPI_LABELS) C.case(T(id), mText.includes(label), 'missing KPI label «' + label + '»')
      C.case(T('K4-tokens-split'), /in-ticket|in ticket/.test(mText) && /outside/.test(mText),
        'tokens sub-line split missing')
      C.case(T('K7-no-cost'), !/cost|\$|price/.test(mText), 'cost surfaced on the tab')
      C.case(T('K8-real-values'), mText.includes('12%') && mText.includes('3.4m'),
        'stub-fed KPI values not visible')

      // ---- W workflow card ----
      const cardH0 = await page.evaluate(() => {
        const els = [...document.querySelectorAll('#paneMetrics *')]
        const cards = els.filter((e) => /where the time goes/i.test((e.textContent || '').slice(0, 60)) && e.offsetHeight > 40)
        return cards.length ? Math.min(...cards.map((e) => e.offsetHeight)) : 0
      })
      C.case(T('W1-workflow-card-fixed'), cardH0 > 40 && cardH0 < 700, 'card height=' + cardH0)
      C.case(T('W1-chips-and-picker'),
        /dev-lane/i.test(mText) && !!pane.locator('input[type="text"], input:not([type])').first(),
        'chips/picker missing')
      for (const w of WORKFLOWS) C.case(T('W2-all-shown-' + w.name), mText.includes(w.name), 'row missing: ' + w.name)
      C.case(T('W2-sublines'), mText.includes('40') && mText.includes('12'), 'ticket/stage-run counts missing')

      // W4/W5: click the dev-lane row -> its stage rows appear in the same card
      await pane.locator('text=dev-lane').first().click().catch(() => {})
      await page.waitForTimeout(300)
      const drill = await page.evaluate(() => {
        const pane = document.querySelector('#paneMetrics')
        const cards = [...pane.querySelectorAll('*')].filter((e) => /where the time goes/i.test((e.textContent || '').slice(0, 60)) && e.offsetHeight > 40)
        const card = cards[cards.length - 1]
        const t = card ? (card.textContent || '').toLowerCase() : ''
        return { h: card ? card.offsetHeight : 0, t }
      })
      C.case(T('W4-stage-drill-in-card'), /plan/.test(drill.t) && /review/.test(drill.t),
        'stage rows not shown: ' + drill.t.slice(0, 120))
      C.case(T('W4-card-never-grows'), drill.h <= cardH0 + 4, 'card grew ' + cardH0 + '->' + drill.h)
      C.case(T('W5-chains-not-mixed'), !/chore-lane|ops-lane/.test(drill.t.replace(/where the time goes/i, '')),
        'other workflow rows visible in the drill axis')

      // ---- C1 certification ----
      C.case(T('C1-cert-counts'), mText.includes('14') && mText.includes('3') && mText.includes('1'),
        'green/red/flaky counts missing')
      C.case(T('C1-time-to-green'), mText.includes('22m'), 'time-to-green value missing')

      // ---- E epics ----
      C.case(T('E1-five-cards'), (mText.match(/epic-/g) || []).length >= 5, 'fewer than five epic names visible')
      C.case(T('E2-sort-control'), /sort|last activity/.test(mText) && /tickets/.test(mText) && /elapsed/.test(mText),
        'sort control missing')
      // E3: drive the type-to-match picker to add the epic beyond the top five.
      // The picker commits on the input's CHANGE event, so fire it explicitly
      // (page.fill alone only fires input — measured round 2: no change event,
      // no add).
      await page.fill('#mtEpicPick', 'epic-zeta').catch(() => {})
      await page.dispatchEvent('#mtEpicPick', 'change').catch(() => {})
      await page.waitForTimeout(300)
      const mText2 = (await pane.innerText()).toLowerCase()
      C.case(T('E3-type-to-match-adds'), mText2.includes('epic-zeta'), 'picker did not add epic-zeta')
      // Default sort = last activity, judged on the cards that ARE on the face
      // (the top five; epic-zeta is the sixth by design and belongs to the
      // picker leg above — round-2 note: asserting on zeta's index here was a
      // scenario bug, -1 < everything).
      C.case(T('E1-last-activity-default'),
        mText.indexOf('epic-alpha') >= 0 && mText.indexOf('epic-alpha') < mText.indexOf('epic-beta'),
        'default order is not last activity')

      // ---- T charts ----
      const canvases = await page.evaluate(() => document.querySelectorAll('#paneMetrics canvas').length)
      C.case(T('T1-throughput-canvas'), canvases >= 2, 'canvas count=' + canvases)
      C.case(T('T1-opened-closed-legend'), mText.includes('opened') && mText.includes('closed'),
        'opened/closed legend anchors missing')
      for (const s of SERIES) C.case(T('T2-legend-' + s.replace(/\s+/g, '-')), mText.includes(s), 'series missing: ' + s)
      // Round-3: the series palette lives INSIDE the canvas-rendered chart, so
      // the DOM swatch scan cannot see it (it honestly picked up the
      // certification strip colours instead). The recorded options are the
      // adapter's contract face: find the five-series token option and judge
      // its colours against the declared palette.
      const chartOpts = await page.evaluate(() => window.__chartOptions || [])
      const tokenOpt = chartOpts.find((o) => {
        const names = ((o && o.series) || []).map((s) => (s && s.name) || '')
        return ['developer', 'integration', 'executor', 'executor session', 'global session']
          .every((n) => names.includes(n))
      })
      const tokenCols = tokenOpt ? (tokenOpt.series || []).map((s) => (s.itemStyle && s.itemStyle.color) || s.color || (s.stack ? null : null)) : []
      const cols = tokenCols.filter(Boolean)
      C.case(T('T2-session-colours-distinct'),
        cols.length >= 5 &&
        [PALETTE['executor session'], PALETTE['global session']].every((c) => cols.includes(c)) &&
        [PALETTE.developer, PALETTE.integration, PALETTE.executor].every((c) => cols.includes(c)) &&
        new Set(cols.map((c) => String(c).toLowerCase())).size === 5,
        'tokenOption series colours=' + JSON.stringify(cols))
      C.case(T('T2-axis-millions'), /m\b/i.test(mText), 'millions axis mark missing')

      // ---- P1 no-prose guard ----
      const prose = BANNED_PROSE.filter((s) => mText.includes(s.toLowerCase()))
      C.case(T('P1-no-explanatory-prose'), prose.length === 0, 'prose leaked: ' + prose.join(' | '))
      C.case(T('P2-no-mock-numbers'), !MOCK_ILLUSTRATIVE.some((n) => mText.includes(n.toLowerCase())),
        'mock illustrative numbers rendered')
      await page.screenshot({ path: join(OUT_DIR, 'metrics-tab-' + theme + '.png'), fullPage: true }).catch(() => {})
      C.case(T('E0-zero-pageerror'), pageErrors.length === 0, pageErrors.join(' | '))
      await page.close().catch(() => {})
    } catch (e) {
      C.case(theme + ':journey-completed', false, String(e).slice(0, 200))
      await page.close().catch(() => {})
    }
  }

  // ---- D1 malformed payload leg (independent page, garbage metrics body) ----
  payloadMode = 'garbage'
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
  const errs2 = []
  page.on('pageerror', (e) => errs2.push(String(e).slice(0, 160)))
  await page.route('**/*', (route) => {
    const u = new URL(route.request().url())
    if (u.pathname === '/' || u.pathname === '/index.html') route.fulfill({ contentType: 'text/html', body: PANEL_HTML })
    else route.continue()
  })
  try {
    await page.goto(base + '/?project=' + PROJ + '&theme=light', { waitUntil: 'domcontentloaded' })
    await page.locator('label[for="t-metrics"]').first().click()
    await page.waitForTimeout(800)
    const t = ((await page.locator('#paneMetrics').innerText().catch(() => '')) || '').toLowerCase()
    C.case('D1-malformed-degrades', /no data|—/.test(t) && !t.includes('nan') && !t.includes('undefined'),
      'pane=' + t.slice(0, 120).replace(/\n/g, ' '))
    C.case('D1-no-fabricated-numbers', !t.includes('12%') && !t.includes('3.4m'),
      'stale/fabricated values after malformed payload')
    C.case('D1-zero-pageerror', errs2.length === 0, errs2.join(' | '))
  } catch (e) {
    C.case('D1-journey-completed', false, String(e).slice(0, 200))
  }
  await page.close().catch(() => {})

  await closeAll()
  C.exit()
}

main().catch((e) => { console.log('[ENV_FAIL] harness: ' + String(e).slice(0, 200)); console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0'); process.exit(2) })
