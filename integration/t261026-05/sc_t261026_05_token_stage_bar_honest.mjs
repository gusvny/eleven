/**
 * sc_t261026_05_token_stage_bar_honest.mjs — the Where-the-tokens-go chart
 * contract (t261026-05, host report 261026 item 2).
 *
 * User-facing rule under test: the token view's charts.primary IS a per-stage
 * bar ("stage token 消耗"). The panel's tokensStackOf card must render the
 * payload's own spec — title, categories and series verbatim — instead of the
 * daily stacked-by-model shape the API never produced (today the card cannot
 * load), and it must carry the API's title, never a panel-invented one.
 * When by_stage is empty in the per-ticket records the near-zero stage bar
 * must be NAMED (zeros that mean "not recorded", not a silent all-flat chart).
 *
 * Grey-box L3: the REAL buildMetricsResponse (view=token) over the standard
 * stubbed temp harness plus cache surgery to force the empty-by_stage shape,
 * and the REAL panel-side tokensStackOf over fabricated malformed payloads.
 * Offline seconds, zero docker/Temporal-server/browser, never touches
 * 3099/7233.
 *
 * Legs:
 *  A  the token primary is the per-stage bar and tokensStackOf renders it
 *     verbatim, title included (the two sides agree — the card can load);
 *  B  an empty by_stage in the records is NAMED on the face (zeros mean
 *     not-recorded, never silent);
 *  C  malformed payloads (missing charts / non-array series / non-string
 *     names) degrade to the named empty state, no crash;
 *  D  the KPI side of the token view is untouched (fresh/actual/cache tiles
 *     keep the first-half contract).
 *
 * Pre-implement tree red = the named TDD signal; green required at the
 * integration gate/merge. Test lib unimportable = ENV_FAIL exit 2.
 */
import { readFileSync, writeFileSync, rmSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import {
  freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents,
  ok as libOk, summary,
} from '../../server/plugins/workbench/tests/lib.mjs'

const ROOT = join(new URL('.', import.meta.url).pathname, '..', '..')
const PANEL_MODEL = join(ROOT, 'server', 'plugins', 'executor-panel', 'src', 'host', 'metrics-tab-model.ts')

const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href

function ok(cond, label, detail = '') { libOk(label, cond, detail) }
function section(t) { console.log(`\n== ${t}`) }

const TMP_DIRS = []
function keep(d) { TMP_DIRS.push(d); return d }
process.on('exit', () => { for (const d of TMP_DIRS) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best effort */ } } })

function putSession(sessDir, events) {
  mkdirSync(sessDir, { recursive: true })
  const raw = join(sessDir, 'raw.jsonl')
  writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
  execFileSync('zstd', ['-f', '-q', raw, '-o', join(sessDir, 'session.jsonl.zstd')])
  rmSync(raw)
}

async function runToken(stubPath, repo, projectsRoot) {
  const old = {}
  for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']) {
    old[k] = process.env[k]
    delete process.env[k]
  }
  process.env.SANDBAR_METRICS_STUB = stubPath
  process.env.SANDBAR_METRICS_DIR = projectsRoot
  process.env.SANDBAR_PROJECTS_DIR = projectsRoot
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps(repo, () => NOW)
    const params = { view: 'token', window: '30d', epic: 'all', template: 'dev-lane', mode: 'full' }
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of Object.keys(old)) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

const TICKET = 't261026-05'

function closedRow() {
  const t0 = Date.parse('2026-08-29T01:00:00Z')
  const closedAt = Date.parse('2026-08-30T06:00:00Z')
  return {
    id: TICKET, project: 'demo', epic: 'metrics', title: TICKET, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
    created: new Date(t0).toISOString(), updated: new Date(closedAt).toISOString(),
    updated_ts: Math.round(closedAt / 1000), worktree: `.worktrees/${TICKET}`,
    timeline: [
      { at: new Date(t0).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(t0 + 3600e3).toISOString(), stage: 'implement', state: 'running' },
      { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' },
    ],
  }
}

async function runAll() {
  section('0. environment gates')
  let panel = null
  try {
    panel = await import(new URL('file://' + PANEL_MODEL).href)
  } catch (err) {
    console.log(`ENV_FAIL: panel metrics-tab-model.ts unimportable: ${String(err?.message ?? err)}`)
    process.exit(2)
  }
  ok(typeof panel.tokensStackOf === 'function', 'panel tokensStackOf present (public seam)')

  // ---- fixture: a closed ticket with a live lane session carrying usage ----
  const repo = keep(freshDir('t05tok-repo-'))
  const projects = keep(freshDir('t05tok-projects-'))
  const stubPath = writeStub(keep(freshDir('t05tok-stub-')), baseStub({ tickets: [closedRow()] }))
  const sess = join(repo, '.worktrees', TICKET, '.dsh', 'sessions', 'slug0', `${TICKET}-developer`)
  putSession(sess, usageEvents())

  const body1 = ((await runToken(stubPath, repo, projects)).body) ?? {}
  const primary = body1?.charts?.primary ?? null

  // ---- A. the per-stage bar is rendered verbatim, title included ----
  section('A. token primary rendered verbatim by the panel card')
  ok(primary && Array.isArray(primary.categories) && Array.isArray(primary.series),
    'A1 the token view carries a primary spec with categories+series', JSON.stringify(primary)?.slice(0, 160))
  const rendered = panel.tokensStackOf(body1)
  ok(rendered && Array.isArray(rendered.categories) && Array.isArray(rendered.series),
    'A2 the panel renders the real response (the card can load)', JSON.stringify(rendered)?.slice(0, 160))
  ok(JSON.stringify(rendered?.categories) === JSON.stringify(primary?.categories),
    'A3 the categories travel verbatim (stage axis, not reinvented)')
  ok(JSON.stringify(rendered?.series) === JSON.stringify((primary?.series ?? []).map((s) => ({
    name: String(s?.name ?? ''), data: Array.isArray(s.data) ? s.data : [],
  }))),
    'A4 the series travel verbatim (names and numbers untouched)', JSON.stringify(rendered?.series)?.slice(0, 200))
  ok(typeof rendered?.title === 'string' && rendered.title === String(primary?.title ?? ''),
    'A5 the card title IS the API title (a stage view, honestly titled — never a panel-invented daily-by-model claim)',
    JSON.stringify({ api: primary?.title, card: rendered?.title }))

  // ---- B. empty by_stage is NAMED, never silent zeros ----
  section('B. empty by_stage named on the face')
  // cache surgery: the first run wrote per-ticket records; empty their by_stage
  // and re-run so the fast path serves records whose stage numbers are zeros.
  const cacheDir = join(projects, 'demo', 'data', 'metrics')
  let surgery = 0
  try {
    for (const f of ['t261026-05.json']) {
      const p = join(cacheDir, f)
      const rec = JSON.parse(readFileSync(p, 'utf8'))
      if (rec?.tokens && typeof rec.tokens === 'object') { rec.tokens.by_stage = {}; writeFileSync(p, JSON.stringify(rec)); surgery++ }
    }
  } catch (err) {
    ok(false, 'B0 cache surgery possible (per-ticket record on disk)', String(err?.message ?? err))
  }
  if (surgery > 0) {
    const body2 = ((await runToken(stubPath, repo, projects)).body) ?? {}
    const allText = JSON.stringify(body2)
    ok(/by_stage/i.test(allText),
      'B1 the empty by_stage is named on the face (zeros mean not-recorded, never silent)', allText.slice(0, 300))
    const p2 = body2?.charts?.primary ?? null
    ok(p2 && Array.isArray(p2.series),
      'B2 the stage bar still ships well formed over empty by_stage', JSON.stringify(p2)?.slice(0, 160))
  }

  // ---- C. malformed payloads degrade to the named empty state ----
  section('C. malformed payloads never crash the card')
  ok(panel.tokensStackOf(null) === null, 'C1 null payload → null (named empty)')
  ok(panel.tokensStackOf({}) === null, 'C2 missing charts → null')
  ok(panel.tokensStackOf({ charts: { primary: { categories: 'nope', series: [] } } }) === null,
    'C3 non-array categories → null')
  ok(panel.tokensStackOf({ charts: { primary: { categories: [], series: 'nope' } } }) === null,
    'C4 non-array series → null')
  const weird = panel.tokensStackOf({ charts: { primary: { categories: [1, null], series: [{ name: 5, data: 'x' }, { data: [] }] } } })
  ok(weird && Array.isArray(weird.series) && weird.series.every((s) => typeof s.name === 'string' && Array.isArray(s.data)),
    'C5 non-string names / non-array data coerce to the declared shape, never throw', JSON.stringify(weird))

  // ---- D. the token KPI tiles are untouched by the chart fix ----
  section('D. token KPI side untouched')
  const k = body1?.kpis ?? {}
  ok(typeof k.tokens_total === 'number' && k.tokens_total > 0,
    'D1 the fresh-token total still aggregates over the same population', JSON.stringify(k.tokens_total))
  ok(typeof k.tokens_cache_read === 'number' && k.tokens_cache_read > 0,
    'D2 the cacheRead tile (v2 Rule 4) still lands', JSON.stringify(k.tokens_cache_read))

  const green = summary('sc_t261026_05_token_stage_bar_honest')
  process.exit(green ? 0 : 1)
}

if (__isMain) {
  await runAll()
} else {
  console.log('sc_t261026_05_token_stage_bar_honest: imported as a module; battery skipped')
}
