/**
 * tests/t261026-05-health-throughput.mjs — t261026-05 server-side faces:
 *  - view=health charts.primary IS the daily opened/closed series (doc winner:
 *    the server), bucketed by the REAL created/close_ts anchors, with a named
 *    gap for closed rows without close_ts (review condition C1) and a named
 *    empty state when no row carries an anchor;
 *  - the blocked 榜 moved to secondaries[0] (the panel never reads secondaries);
 *  - the additive perf block names cache hit vs compute (health: direct-query);
 *  - the token view names the by_stage gap instead of silent zeros;
 *  - the declared roots (Rule 5) flow into project_sessions/role_aggregate.
 *
 * Direct run: node server/plugins/workbench/tests/t261026-05-health-throughput.mjs
 * Full stub env (SANDBAR_METRICS_STUB + SANDBAR_METRICS_DIR + SANDBAR_DSH_HOME):
 * zero real ~/.sandbar / ~/.dsh / admin.py / git touches. Session fixtures need
 * system zstd (cases SKIP without it, never FAIL).
 */
import { mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents, makeSession, ok as libOk, dumpFails } from './lib.mjs'

const __isMain = process.argv[1] !== undefined
  && import.meta.url === pathToFileURL(process.argv[1]).href
function ok(cond, label, detail = '') { libOk(label, cond, detail) }
function section(t) { console.log(`\n== ${t}`) }

const HAS_ZSTD = (() => {
  try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }); return true } catch { return false }
})()

const DAY = 86_400_000

/** A health-view row: machine fields only (the direct-query path reads no timeline). */
function hRow(id, opts = {}) {
  return {
    id, project: 'demo', epic: opts.epic ?? 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: opts.stage_state ?? (opts.status === 'closed' ? 'closed' : 'running'),
    status: opts.status ?? 'open', role: 'developer',
    updated: new Date(NOW).toISOString(),
    updated_ts: Math.round(NOW / 1000),
    worktree: `.worktrees/${id}`,
    ...(opts.created !== undefined ? { created: Math.round(opts.created / 1000) } : {}),
    ...(opts.close_ts !== undefined ? { close_ts: Math.round(opts.close_ts / 1000) } : {}),
  }
}

async function runMetrics(m, env, params) {
  const keys = ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_DSH_HOME', 'SANDBAR_PROJECTS_DIR', 'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']
  const old = {}
  for (const k of keys) { old[k] = process.env[k]; delete process.env[k] }
  Object.assign(process.env, env)
  try {
    const deps = m.defaultDeps(env.repo, () => NOW)
    const q = { view: 'time', window: '7d', epic: 'all', template: 'dev-lane', mode: 'full', ...params }
    return await m.buildMetricsResponse(q, deps)
  } finally {
    for (const k of keys) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

async function runAll() {
  const m = await loadMetrics()
  const oldDsh = process.env.SANDBAR_DSH_HOME
  const dshHome = freshDir('hl-dsh-home-')
  process.env.SANDBAR_DSH_HOME = dshHome
  try {
    /* ---- A. daily throughput on the health view ---- */
    section('A. health: charts.primary = daily opened/closed')
    {
      const repo = freshDir('hl-repo-')
      const cacheDir = freshDir('hl-cache-')
      const stubPath = writeStub(freshDir('hl-stub-'), baseStub({
        tickets: [
          hRow('o1', { created: NOW - 3 * DAY }),
          hRow('c1', { status: 'closed', created: NOW - 5 * DAY, close_ts: NOW - 2 * DAY }),
          hRow('c2', { status: 'closed', created: NOW - 1 * DAY }), // no close_ts anchor
        ],
      }))
      const r = (await runMetrics(m, { SANDBAR_METRICS_STUB: stubPath, SANDBAR_METRICS_DIR: cacheDir, repo }, { view: 'health' })).body
      const p = r.charts?.primary
      ok(p && p.kind === 'bar' && Array.isArray(p.categories) && p.categories.length > 0,
        'A: primary is a bar with day buckets', JSON.stringify(p?.categories))
      ok(p?.series?.[0]?.name === 'opened' && p?.series?.[1]?.name === 'closed',
        'A: series named opened/closed (the panel name contract)', JSON.stringify(p?.series?.map((s) => s.name)))
      const sum = (a) => a.reduce((x, y) => x + y, 0)
      ok(sum(p.series[0].data) === 3 && sum(p.series[1].data) === 1,
        'A: 3 created in window; 1 anchored close bucketed (c2 is not silently dropped)', JSON.stringify({ o: p.series[0].data, c: p.series[1].data }))
      ok(typeof r.reason === 'string' && r.reason.includes('no close_ts anchor') && r.reason.includes('1 closed'),
        'A: the unanchored close is a named gap, never a silent drop', r.reason)
      const blockedSec = (r.charts?.secondaries ?? []).find((s) => String(s.title ?? '').startsWith('blocked 榜'))
      ok(blockedSec !== undefined, 'A: blocked 榜 lives in secondaries[0] now', JSON.stringify((r.charts?.secondaries ?? []).map((s) => s.title)))
      ok(r.perf && r.perf.cache === 'n/a (direct-query)' && typeof r.perf.ms_total === 'number',
        'A: perf block names the direct-query cache semantics', JSON.stringify(r.perf))
    }

    /* ---- B. named empty + window=all weekly buckets + span cap ---- */
    section('B. health: empty anchors, week buckets, span cap')
    {
      const repo = freshDir('hl-repo2-')
      const stubPath = writeStub(freshDir('hl-stub2-'), baseStub({
        tickets: [hRow('x1', { created: NOW - 200 * DAY, close_ts: NOW - 199 * DAY, status: 'closed' })],
      }))
      const env = { SANDBAR_METRICS_STUB: stubPath, SANDBAR_METRICS_DIR: freshDir('hl-cache2-'), repo }
      const rAll = (await runMetrics(m, env, { view: 'health', window: 'all' })).body
      ok(String(rAll.charts?.primary?.title ?? '').includes('week'), 'B: span > 92d buckets by week', rAll.charts?.primary?.title)
      ok(rAll.charts.primary.categories.length <= 40 && rAll.charts.primary.categories.length >= 20,
        'B: week bucket count bounded', String(rAll.charts.primary.categories.length))
      const emptyRepo = freshDir('hl-repo3-')
      const emptyStub = writeStub(freshDir('hl-stub3-'), baseStub({
        tickets: [hRow('x2', { status: 'open' })], // no created anchor at all
      }))
      const rE = (await runMetrics(m, { SANDBAR_METRICS_STUB: emptyStub, SANDBAR_METRICS_DIR: freshDir('hl-cache3-'), repo: emptyRepo }, { view: 'health', window: 'all' })).body
      ok(sum0(rE.charts?.primary?.series) && typeof rE.reason === 'string' && rE.reason.includes('no row carries a created/close_ts anchor'),
        'B: anchor-less rows -> empty series + named reason (empty ≠ zero activity)', rE.reason)
    }

    /* ---- C. token view: by_stage gap named, never silent zeros ---- */
    section('C. token view: by_stage emptiness is a named gap')
    if (!HAS_ZSTD) {
      console.log('SKIP: no zstd on PATH; session fixtures cannot be built')
    } else {
      const repo = freshDir('hl-repo4-')
      const id = 't261026-05'
      // Per-ticket lane session: <repo>/<worktree>/.sandbar/.dsh/sessions/<slug>/<id>-<role>/
      // (makeSession targets the repo-root tree, which the per-ticket reader never scans).
      const sess = join(repo, '.worktrees', id, '.dsh', 'sessions', 'slug0', `${id}-developer`)
      mkdirSync(sess, { recursive: true })
      const { writeFileSync } = await import('node:fs')
      const raw = join(sess, 'raw.jsonl')
      writeFileSync(raw, usageEvents().map((e) => JSON.stringify(e)).join('\n') + '\n')
      execFileSync('zstd', ['-f', '-q', raw, '-o', join(sess, 'session.jsonl.zstd')])
      rmSync(raw)
      const stubPath = writeStub(freshDir('hl-stub4-'), baseStub({
        tickets: [hRow(id, { status: 'closed', created: NOW - DAY })], // no timeline -> by_stage empty
      }))
      const r = (await runMetrics(m, { SANDBAR_METRICS_STUB: stubPath, SANDBAR_METRICS_DIR: freshDir('hl-cache4-'), SANDBAR_DSH_HOME: dshHome, repo }, { view: 'token' })).body
      const prim = r.charts?.primary
      ok(prim && String(prim.title ?? '').includes('stage token'), 'C: token primary stays the per-stage spec', prim?.title)
      ok(typeof r.reason === 'string' && r.reason.includes('tokens.by_stage is empty'),
        'C: the all-zero stage bar carries the named by_stage gap', r.reason)
      ok(r.perf && ['hit', 'computed'].includes(r.perf.cache) && typeof r.perf.records_from_cache === 'number',
        'C: data views carry the perf hit/compute split', JSON.stringify(r.perf))
      ok(typeof r.project_sessions_degrade === 'object' && Array.isArray(r.project_sessions_degrade.searchedRoots),
        'C: project_sessions_degrade names BOTH declared roots', JSON.stringify(r.project_sessions_degrade?.searchedRoots))
      ok(Array.isArray(r.role_aggregate?.searchedRoots) && r.role_aggregate.searchedRoots.length === 2,
        'C: role_aggregate names both declared roots', JSON.stringify(r.role_aggregate?.searchedRoots))
    }
    void rmSync
  } finally {
    if (oldDsh === undefined) delete process.env.SANDBAR_DSH_HOME
    else process.env.SANDBAR_DSH_HOME = oldDsh
  }
  console.log('t261026-05-health-throughput done')
  dumpFails()
}

function sum0(series) {
  if (!Array.isArray(series)) return false
  return series.every((s) => Array.isArray(s.data) && s.data.every((v) => v === 0))
}

if (__isMain) await runAll()
else console.log('t261026-05-health-throughput: imported as a module; battery skipped')
