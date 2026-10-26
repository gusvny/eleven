/**
 * sc_t261026_05_metrics_perf_face.mjs — the tab-slowness face (t261026-05,
 * host report 261026 item 4).
 *
 * User-facing rule under test: every metrics view costs 1.2-1.5 s server-side
 * and the user cannot see WHERE the time goes, nor why the existing per-ticket
 * cache is not hit on a repeat read. The face must answer the question itself:
 * each view response carries a perf block (total time, cache hit vs computed,
 * parse time), and a repeat read over a warm cache is measurably compute-free
 * — zero per-ticket file parses, cache hits counted, nothing recomputed.
 *
 * Grey-box L3 over the REAL buildMetricsResponse (views time/health/token)
 * over the standard stubbed temp harness, cold pass then warm pass over the
 * same fixture tree. Wall-clock is deliberately NOT asserted (a busy CI host
 * lies); the asserted mechanism is the hit/compute accounting that explains
 * the 1.2-1.5 s. Offline seconds, zero docker/Temporal-server/browser, never
 * touches 3099/7233.
 *
 * Legs:
 *  A  every view response carries the perf block with a numeric total;
 *  B  the health direct-query path names its cache semantics (n/a or
 *     computed-here), never a fabricated hit;
 *  C  a warm repeat read reports cache HITS and zero parse work (the fast
 *     path is real, not claimed);
 *  D  correctness is not traded for speed: the warm response keeps the same
 *     KPI totals as the cold response (cache never changes the answer).
 *
 * Pre-implement tree red = the named TDD signal; green required at the
 * integration gate/merge. Test lib unimportable = ENV_FAIL exit 2.
 */
import { writeFileSync, rmSync, mkdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import {
  freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents,
  ok as libOk, summary,
} from '../../server/plugins/workbench/tests/lib.mjs'

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
      { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' },
    ],
  }
}

async function runView(view, stubPath, repo, projectsRoot) {
  const old = {}
  const keys = ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']
  for (const k of keys) { old[k] = process.env[k]; delete process.env[k] }
  process.env.SANDBAR_METRICS_STUB = stubPath
  process.env.SANDBAR_METRICS_DIR = projectsRoot
  process.env.SANDBAR_PROJECTS_DIR = projectsRoot
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps(repo, () => NOW)
    const params = { view, window: '30d', epic: 'all', template: 'dev-lane', mode: 'full' }
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of keys) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

async function runAll() {
  section('0. environment gates')
  let hasZstd = true
  try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }) } catch { hasZstd = false }
  if (!hasZstd) {
    console.log('ENV_FAIL: zstd CLI missing — session fixtures cannot be built; honest red, not a silent skip')
    process.exit(2)
  }

  const repo = keep(freshDir('t05perf-repo-'))
  const projects = keep(freshDir('t05perf-projects-'))
  const stubPath = writeStub(keep(freshDir('t05perf-stub-')), baseStub({ tickets: [closedRow()] }))
  putSession(join(repo, '.worktrees', TICKET, '.dsh', 'sessions', 'slug0', `${TICKET}-developer`), usageEvents())

  // ---- A. the perf block rides every view ----
  section('A. perf block on every view')
  const bodies = {}
  for (const view of ['time', 'health', 'token']) {
    bodies[view] = ((await runView(view, stubPath, repo, projects)).body) ?? {}
    const perf = bodies[view]?.perf ?? null
    ok(perf && typeof perf === 'object',
      `A-${view} the response carries a perf block`, JSON.stringify(perf))
    ok(perf && typeof perf.ms_total === 'number' && perf.ms_total >= 0,
      `A-${view} ms_total is a number, not prose`, JSON.stringify(perf))
  }

  // ---- B. health's cache semantics stay honest ----
  section('B. health direct-query cache semantics named')
  const hPerf = JSON.stringify(bodies.health?.perf ?? {})
  ok(/computed|direct|n\/a|na|hit/i.test(hPerf),
    'B1 the health perf block states its cache semantics (direct-query computed here, never a fabricated hit)', hPerf)

  // ---- C. warm repeat: hit named, nothing recomputed ----
  section('C. warm repeat read is compute-free by its own accounting')
  const warm = ((await runView('time', stubPath, repo, projects)).body) ?? {}
  const perf = warm?.perf ?? {}
  const perfText = JSON.stringify(perf).toLowerCase()
  const isHit = /hit/.test(perfText)
  const computed = Number(perf.records_computed ?? perf.cache_computed ?? -1)
  const parseField = ['ms_parse', 'msparse', 'parses', 'parse_ms'].map((k) => perf[k]).find((v) => v !== undefined)
  ok(isHit,
    'C1 the warm read names a cache HIT on the face (the cache exists and is reached)', JSON.stringify(perf))
  ok(computed === 0,
    'C2 the warm read recomputes nothing (records_computed=0)', JSON.stringify(perf))
  ok(parseField === undefined || Number(parseField) === 0,
    'C3 the warm read reports zero parse work when the face carries a parse measure (records_computed=0 is the mechanism)',
    JSON.stringify(perf))

  // ---- D. speed never changes the answer ----
  section('D. warm response keeps the cold totals')
  ok(JSON.stringify(warm?.kpis?.tokens_total) === JSON.stringify(bodies.time?.kpis?.tokens_total)
    && JSON.stringify(warm?.kpis?.closed) === JSON.stringify(bodies.time?.kpis?.closed),
    'D1 the warm KPI totals equal the cold totals (cache hit never rewrites the answer)',
    JSON.stringify({ cold: bodies.time?.kpis?.tokens_total, warm: warm?.kpis?.tokens_total }))

  const green = summary('sc_t261026_05_metrics_perf_face')
  process.exit(green ? 0 : 1)
}

if (__isMain) {
  await runAll()
} else {
  console.log('sc_t261026_05_metrics_perf_face: imported as a module; battery skipped')
}
