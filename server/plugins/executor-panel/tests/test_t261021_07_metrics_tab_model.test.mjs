/**
 * test_t261021_07_metrics_tab_model.test.mjs — the Metrics tab v2 pure model
 * + chart option factories, L1 (pure node, no browser, no fetch). The page
 * embeds these functions via String(fn), so these tests run THE page's
 * implementation (t261021-07 write-set test file).
 *
 * Truth tables:
 *  - happy path: a full v2 payload (t261021-06 contract shape) maps to the six
 *    KPI tiles, workflow rows, stage drill, epic sort/pick, session rows;
 *  - the certification summary counts verdicts and computes time-to-green;
 *  - chart options carry the declared palette and millions scaling;
 *  - the malformed-input matrix (null / wrong type / missing / arrays where
 *    objects / numbers where strings / empty everything): every value lands
 *    on the honest dash or a named empty state — no crash, no NaN, no
 *    'undefined', no fabricated number.
 */
import { assert, done } from './lib.mjs'
import {
  METRICS_TAB_COPIES, mnum, mstr, mdash, fmtInt, fmtPct01, fmtTokensM, fmtMs, fmtAgo,
  shareBarPct, metricsV2Of, kpiTilesOf, workflowRowsOf, stageRowsOf, epicCardsOf,
  certSummaryOf, throughputSpecOf, tokensStackOf, sessionRowsOf, roleRowsOf,
} from '../src/host/metrics-tab-model.ts'
import { METRICS_SERIES_COLORS, throughputOption, tokensOption } from '../src/host/metrics-tab-charts.ts'

const HOUR = 3600000
const DAY = 24 * HOUR
const NOW = 1_700_000_000_000

// ---- formatting primitives (the dash law) ----
assert(mnum(5) === 5 && mnum(0) === 0, 'mnum keeps finite numbers incl. 0')
assert(mnum('5') === null && mnum(NaN) === null && mnum(true) === null && mnum(null) === null, 'mnum refuses strings/NaN/bool/null')
assert(mstr(' x ') === 'x' && mstr('') === null && mstr(7) === null, 'mstr trims and refuses non-strings')
assert(mdash(null) === '—' && mdash(undefined) === '—' && mdash(3) === '3', 'mdash = honest dash on malformed')
assert(fmtInt(1234) === '1,234' && fmtInt(null) === '—', 'fmtInt groups and dashes')
assert(fmtPct01(0.38) === '38%' && fmtPct01('x') === '—', 'fmtPct01 scales 0..1')
assert(fmtTokensM(4.126e8) === '412.6M' && fmtTokensM(-1) === '—', 'fmtTokensM in millions')
assert(fmtMs(3.5 * HOUR) === '3h 30m' && fmtMs(26 * 60_000) === '26m' && fmtMs(26 * HOUR) === '1d 2h', 'fmtMs mock faces')
assert(fmtAgo(NOW - 18 * 60_000, NOW) === '18m ago' && fmtAgo(NOW + 5, NOW) === '—' && fmtAgo(null, NOW) === '—', 'fmtAgo dashes future/malformed')
assert(shareBarPct(50, 100) === 50 && shareBarPct(50, 0) === 0 && shareBarPct('x', 10) === 0, 'shareBarPct never NaN')

// ---- happy-path payload (frozen v2 shape) ----
function goodPayload() {
  return {
    generated_at: '2026-10-21T00:00:00Z',
    cache: { status: 'hit', source_version: 'v3' },
    kpis: {
      tickets: 191, closed: 168, rework_rate: 0.38, throughput_per_day: 5.6,
      median_lead_time: 3 * HOUR + 40 * 60_000, p90_lead_time: 9 * HOUR, human_wait_share: 0.31,
      tokens_total: 4.126e8, tokens_in_tickets: 3.5e8, tokens_outside_tickets: 6.26e7,
      tokens_per_closed_ticket: 2.08e6,
      tokens_cache_read: 1.05e8, tickets_with_usage: 173, closed_with_usage: 152,
    },
    workflows: [
      { workflow: 'dev-lane', elapsed_ms: 26 * HOUR, rounds_per_ticket: 1.9, tickets: 48, stage_runs: 1284 },
      { workflow: 'light-lane', elapsed_ms: 9 * HOUR, rounds_per_ticket: 1.6, tickets: 31, stage_runs: 96 },
    ],
    stages: [
      { workflow: 'dev-lane', stage: 'plan', runs: 50, elapsed_ms: 4 * HOUR, avg_rounds_per_ticket: 1.04, tickets_reached: 48 },
      { workflow: 'dev-lane', stage: 'implement', runs: 900, elapsed_ms: 20 * HOUR, avg_rounds_per_ticket: 1.1, tickets_reached: 48 },
      { workflow: 'light-lane', stage: 'do', runs: 96, elapsed_ms: 9 * HOUR, avg_rounds_per_ticket: 1.6, tickets_reached: 31 },
    ],
    epics: [
      { epic: 'metrics', tickets: 12, elapsed_ms: 4.5 * HOUR, tokens: 2.37e7, last_activity_ms: NOW - 9.6 * HOUR },
      { epic: 'console-ui', tickets: 31, elapsed_ms: 14 * HOUR, tokens: 9.68e7, last_activity_ms: NOW - 1.05 * HOUR },
      { epic: 'develop-buffer', tickets: 48, elapsed_ms: 26 * HOUR, tokens: 1.824e8, last_activity_ms: NOW - 0.3 * HOUR },
    ],
    project_sessions: {
      total: { in: 2.5e7, out: 1.7e7, cache_read: 3.0e7 },
      buckets: {
        executor: { in: 1.0e7, out: 0.84e7, cache_read: 1.2e7 },
        global: { in: 1.5e7, out: 0.86e7, cache_read: 1.8e7 },
      },
    },
  }
}

const vm = metricsV2Of(goodPayload())
assert(vm.ok === true, 'good payload normalizes ok')

// KPI tiles: six, real values (t261025-13: rework tile removed, three honest
// token tiles with coverage lines, P90 sub computed).
const tiles = kpiTilesOf(vm)
assert(tiles.length === 6, 'six KPI tiles')
assert(tiles[0].value === '5.6/day' && tiles[0].sub === '168 closed of 191 opened', 'tile 1 throughput + split sub-line')
assert(tiles[1].value === '3h 40m' && tiles[1].sub === 'P90 9h 0m', 'tile 2 median + computed P90 sub')
assert(tiles[2].title === 'TOKENS' && tiles[2].value === '517.6M', 'tile 3 tokens = actual traffic incl cache')
assert(tiles[2].sub === '350.0M in tickets · 62.6M outside · 173 of 191 tickets with usage', 'tile 3 split + coverage sub-line')
assert(tiles[3].title === 'FRESH TOKENS PER COVERED TICKET' && tiles[3].value === '2.0M' && tiles[3].sub === '173 of 191 tickets with usage', 'tile 4 fresh per covered + coverage')
assert(tiles[4].title === 'CACHE SHARE' && tiles[4].value === '20%' && tiles[4].sub === '173 of 191 tickets with usage', 'tile 5 cache share + coverage')
assert(tiles[5].value === '31%', 'tile 6 human wait')

// Workflow rows: all when nothing selected; share bars against the max.
const rows = workflowRowsOf(vm, [])
assert(rows.length === 2 && rows[0].name === 'dev-lane' && rows[0].bar === 100 && rows[1].bar === 35, 'workflow rows + share bar pct')
assert(rows[0].rounds === '×1.9 stage runs' && rows[0].sub === '48 tickets · 1,284 stage runs', 'workflow row rounds face + sub-line')
const sel = workflowRowsOf(vm, ['light-lane'])
assert(sel.length === 1 && sel[0].name === 'light-lane' && sel[0].bar === 100, 'selection filters rows, bar rescales')

// Stage drill: only that workflow's chain (never mixed).
const stages = stageRowsOf(vm, 'dev-lane')
assert(stages.length === 2 && stages.every((s) => ['plan', 'implement'].includes(s.stage)), 'stage drill keeps one chain')
assert(stageRowsOf(vm, 'dev-lane')[0].bar === 20, 'stage bar against the chain max')

// Epics: default sort = last activity; top five cap; picked joins.
const cards = epicCardsOf(vm, 'activity', [], NOW)
assert(cards.length === 3 && cards[0].name === 'develop-buffer', 'default sort last activity')
assert(cards[0].activity === '18m ago', 'activity relative face')
const byTokens = epicCardsOf(vm, 'tokens', ['metrics'], NOW)
assert(byTokens[0].name === 'develop-buffer' && byTokens.some((c) => c.name === 'metrics'), 'token sort + picked epic joins')
// A six-epic payload caps at five; the picked sixth joins.
const sixRaw = goodPayload()
sixRaw.epics.push({ epic: 'console-ui-2', tickets: 1, elapsed_ms: HOUR, tokens: 1e5, last_activity_ms: NOW - 30 * DAY })
const capped = epicCardsOf(metricsV2Of(sixRaw), 'activity', ['console-ui-2'], NOW)
assert(capped.length === 4 && capped.some((c) => c.name === 'console-ui-2'), 'picked epic beyond the cap joins')

// Session rows: the mock's two bucket names; cache percent sub-line.
const sess = sessionRowsOf(vm)
assert(sess.length === 2 && sess[0].name === 'executor session' && sess[1].name === 'global session', 'session rows named per the mock')
assert(sess[0].value === '18.4M' && sess[0].sub.includes('cache 39%'), 'session tokens + cache sub-line')
// Role rows: the three role faces stay the named dash (no per-role face exists).
const roles = roleRowsOf(vm)
assert(roles.filter((r) => ['developer', 'integration', 'executor'].includes(r.name)).every((r) => r.value === '—'), 'role rows honest dash')

// ---- certification summary ----
const cert = certSummaryOf({
  ok: true,
  round_faces: { rounds: [
    { run_id: 'a', face: { ts: NOW, outcome: { verdict: 'green' } } },
    { run_id: 'b', face: { ts: NOW + HOUR, outcome: { verdict: 'red' } } },
    { run_id: 'c', face: { ts: NOW + HOUR + 22 * 60_000, outcome: { verdict: 'green' }, flaky_count: 1 } },
    { run_id: 'd', face: { ts: NOW + 2 * HOUR, outcome: { verdict: 'red' } } },
    { run_id: 'e', face: { ts: NOW + 2 * HOUR + 10 * 60_000, outcome: { verdict: 'green' } } },
    { run_id: 'f', face: { ts: NOW + 3 * HOUR, outcome: { verdict: 'red' } } },
    { run_id: 'g', face: { ts: NOW + 3 * HOUR + 40 * 60_000, outcome: { verdict: 'green' } } },
  ] },
})
assert(cert.ok === true && cert.green === 4 && cert.red === 3, 'verdict counts')
assert(cert.flaky === 1, 'flaky from the optional marker')
assert(cert.ttg === '22m', 'time-to-green median of (10m,22m,40m)')
assert(cert.strip.length === 7 && cert.strip[1] === 'red', 'strip sequence kept')
const certNone = certSummaryOf({ ok: false, reason: 'refused' })
assert(certNone.ok === false && certNone.green === null && certNone.ttg === '—', 'cert refusal = named, not zeros')
const certFlakyless = certSummaryOf({ ok: true, round_faces: { rounds: [{ run_id: 'a', face: { outcome: { verdict: 'green' } } }] } })
assert(certFlakyless.flaky === null, 'no flaky face = dash, never 0')

// ---- chart specs ----
const health = { charts: { primary: { categories: ['Oct 01', 'Oct 02'], series: [
  { name: 'created', data: [3, 4] }, { name: 'closed', data: [2, 3] } ] } } }
const spec = throughputSpecOf(health)
assert(spec && spec.days.length === 2 && spec.closed[0] === 2 && spec.opened[0] === 3, 'throughput spec from health view')
const opt = throughputOption(spec)
assert(opt.series[0].type === 'bar' && opt.series[0].name === 'closed' && opt.series[1].type === 'line', 'closed columns + opened line')
assert(opt.series[0].itemStyle.color === METRICS_SERIES_COLORS[0] && opt.series[1].itemStyle.color === METRICS_SERIES_COLORS[1], 'declared palette on the two series')
assert(opt.yAxis.splitLine.show === true, 'gridlines on')

const tokenView = { charts: { primary: { categories: ['Oct 01'], series: [
  { name: 'developer', data: [1e6] }, { name: 'integration', data: [0.5e6] },
  { name: 'executor', data: [0.25e6] }, { name: 'executor session', data: [0.1e6] },
  { name: 'global session', data: [49000] } ] } } }
const stack = tokensStackOf(tokenView)
assert(stack && stack.series.length === 5, 'five series from the token view')
const topt = tokensOption(stack)
assert(topt.series.length === 5 && topt.series.every((s) => s.stack === 'tokens'), 'stacked columns')
assert(topt.series[0].data[0] === 1 && topt.series[4].data[0] === 0.05, 'values scaled to millions')
assert(topt.series[3].itemStyle.color === '#c2255c' && topt.series[4].itemStyle.color === '#495057', 'session colours distinct from role colours')
const cset = new Set(topt.series.map((s) => s.itemStyle.color))
assert(cset.size === 5, 'five distinct series colours')

// ---- malformed-input matrix (external-input rule) ----
const bad = [
  null, undefined, 42, 'nope', [], {}, { kpis: null }, { kpis: 'x' }, { kpis: [] },
  { kpis: { rework_rate: '38%' } }, { kpis: { rework_rate: NaN } },
  { kpis: {}, workflows: 'nope', stages: 7, epics: true, project_sessions: [] },
  { kpis: {}, workflows: [null, 3, { workflow: '' }, { workflow: 'w', tickets: 'many' }] },
  { kpis: {}, project_sessions: { buckets: { executor: 'x', global: null } } },
  { error: 'boom' },
]
for (const b of bad) {
  const v = metricsV2Of(b)
  const t = kpiTilesOf(v.ok === false ? { kpis: {} } : v).map((x) => x.value + x.sub).join('|')
  const label = JSON.stringify(b) ?? String(b)
  assert(!/undefined|NaN/.test(t), 'no undefined/NaN on malformed kpis: ' + label.slice(0, 60))
  assert(workflowRowsOf(v, []).every((r) => !/undefined|NaN/.test(String(r.name) + r.elapsed + r.sub)), 'workflow rows safe: ' + label.slice(0, 60))
  assert(epicCardsOf(v, 'nope', 'notalist', NOW).every((r) => !/undefined|NaN/.test(JSON.stringify(r))), 'epic cards safe')
  assert(sessionRowsOf(v).every((r) => !/undefined|NaN/.test(JSON.stringify(r))), 'session rows safe')
}
assert(metricsV2Of({ kpis: {} }).kpis.tickets === null, 'missing kpi field -> null (dash downstream)')
assert(kpiTilesOf({ kpis: {} }).every((t) => t.value === '—'), 'all-dash KPI row on empty kpis')
// t261025-13 item 2: a one-sided split NAMES the unavailable outside source — a bare dash is the banned defect
assert(kpiTilesOf({ kpis: { tokens_in_tickets: 5e6 } })[2].sub.includes('outside unavailable'), 'half a split = named degrade, not a bare dash')
assert(workflowRowsOf(metricsV2Of({ kpis: {} }), ['ghost']).length === 0, 'unknown chip name = no row')
assert(epicCardsOf(metricsV2Of({ kpis: {} }), 'tokens', [], NOW).length === 0, 'no epics = no cards')
assert(sessionRowsOf({ ok: true, sessions: null }).length === 1 && sessionRowsOf({ ok: true, sessions: null })[0].value === '—', 'null sessions = named empty, not zeros')
assert(throughputSpecOf(null) === null && tokensStackOf({ charts: {} }) === null, 'chart specs null on missing faces (named empty downstream)')
assert(throughputSpecOf({ charts: { primary: { categories: ['d'], series: [{ name: 'x', data: 'nope' }] } } }) === null, 'series with junk data = no spec (named empty)')
const junkOpt = tokensOption({ days: ['d'], series: [{ name: 'developer', data: ['x', null, 1e6] }] })
assert(JSON.stringify(junkOpt.series[0].data) === '[null,null,1]', 'junk stack values -> null points, never NaN')
assert(certSummaryOf(null).ok === false && certSummaryOf('x').green === null, 'cert summary safe on junk')

// ---- embed-closure guard (gate round 1 rework) ----
// The page runs these functions as String(fn) sources, so EVERY module-level
// identifier an embedded body references must exist at page scope. The gate
// red was exactly this: typeof mnum === 'undefined' inside the served page.
// This pin statically locks the page source to the closure.
import { PANEL_PAGE_HTML } from '../src/host/panel-page.ts'
import { DASH } from '../src/host/metrics-tab-model.ts'
import { GRID_LINE, LABEL } from '../src/host/metrics-tab-charts.ts'
{
  const html = PANEL_PAGE_HTML
  const fns = ['metricsV2Of', 'kpiTilesOf', 'workflowRowsOf', 'stageRowsOf', 'epicCardsOf',
    'certSummaryOf', 'throughputSpecOf', 'tokensStackOf', 'sessionRowsOf', 'roleRowsOf',
    'fmtInt', 'fmtTokensM', 'fmtPct01', 'fmtMs', 'fmtAgo',
    'mnum', 'mstr', 'mdash', 'shareBarPct',
    'colorAt', 'commonAxes', 'commonGrid', 'throughputOption', 'tokensOption']
  // The embed list is injected as joined function SOURCES (String(fn) evaluated
  // at module load), so the page carries 'function <name>(' text per embed.
  for (const f of fns) assert(html.includes('function ' + f + '('), 'page embeds ' + f)
  for (const c of ['DASH', 'GRID_LINE', 'LABEL', 'METRICS_SERIES_COLORS']) {
    assert(html.includes('var ' + c + ' ='), 'page aliases module const ' + c)
  }
  assert(html.includes('metrics render failed'), 'a render throw is named apart from the fetch failure (no unreachable masquerade)')
  // B regression pin (gate round 11): the echarts import is LAZY — no
  // page-load module script; the load triggers on the first Metrics open via
  // the named bridge, so PANEL_HTML consumers without the vendor route never
  // see a module MIME/404 error.
  assert(!html.includes('<script type="module">'), 'no page-load module script (the vendor import is lazy)')
  assert(html.includes('function mtEnsureChartLib(') && html.includes('mtEnsureChartLib()'),
    'the chart lib loads lazily via mtEnsureChartLib on first Metrics open')
  // D1 regression pin (gate round 2): the vendor import URL must carry the route
  // WITHOUT an extra quote pair inside it.
  assert(!html.includes('"/sandbar-executor-panel"/vendor'), 'the vendor import URL has no stray quote pair')
  assert(html.includes("import('/sandbar-executor-panel/vendor/echarts.mjs')"),
    'the vendor import URL is the plain route path')
  // D2 regression pin: the metrics cert renderer is distinct from the
  // certification tab's, so hoisting cannot make one dead.
  assert(html.includes('function renderMetricsCert(') && html.includes('function renderCert('),
    'renderMetricsCert and renderCert are two distinct hoisted declarations')
}

done()
