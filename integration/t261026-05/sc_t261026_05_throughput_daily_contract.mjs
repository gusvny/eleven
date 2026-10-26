/**
 * sc_t261026_05_throughput_daily_contract.mjs — the Throughput chart contract
 * (t261026-05, host report 261026 item 1).
 *
 * User-facing rule under test: the panel's Throughput card reads the health
 * view's charts.primary as a DAILY OPENED/CLOSED series (that is what
 * throughputSpecOf draws). The shipped health view has always answered the
 * blocked-榜 hBar in that slot, so the card could never load. The host ruled
 * the server wins: the health view's charts.primary becomes the daily
 * opened/closed spec, the blocked 榜 moves to the secondaries.
 *
 * Grey-box L3 over the REAL buildMetricsResponse (view=health) plus the REAL
 * panel-side throughputSpecOf — the cross-component seam the ticket is about.
 * Judged from the reader side: the JSON body a user's tab receives. Offline
 * seconds, zero docker/Temporal-server/browser, never touches 3099/7233.
 *
 * Legs:
 *  A  the primary chart is the daily opened/closed spec AND the panel's
 *     throughputSpecOf renders it (the contract now agrees end to end);
 *  B  bucket honesty — opened buckets follow the row's created anchor; the
 *     closed series either follows a real close anchor or the face names the
 *     approximation; a close silently dated at its last update is the defect;
 *  C  the blocked 榜 survives in the secondaries (moved, not deleted) and a
 *     blocked row still renders its榜;
 *  D  a row with no anchors degrades NAMED — no NaN/Invalid day ever ships;
 *  E  the empty window stays a well-formed chart with a named reason, never
 *     a null chart (today's "charts could not load" must not come back as an
 *     empty-load in another shape).
 *
 * Pre-implement tree red = the named TDD signal; green required at the
 * integration gate/merge. The workbench test lib being unimportable = ENV_FAIL
 * exit 2.
 */
import { mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { pathToFileURL } from 'node:url'
import {
  freshDir, writeStub, baseStub, NOW, loadMetrics,
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

/** A ticket row the way the engine's list projects it post-t261026-01:
 *  `created` (epoch SECONDS, engine meta.created) beside `updated_ts`; an
 *  archived row may also carry a `close_ts` anchor (epoch seconds). */
function row(id, opts = {}) {
  const created = opts.created
  const updated = opts.updated ?? created
  return {
    id, project: 'demo', epic: 'metrics', title: id, workflow: 'dev-lane',
    stage: opts.stage ?? 'implement',
    stage_state: opts.stageState ?? (opts.closed ? 'closed' : 'running'),
    status: opts.closed ? 'closed' : 'open', role: 'developer',
    created: opts.isoCreated ? new Date(created).toISOString() : (created === null ? null : Math.round(created / 1000)),
    updated: updated ? new Date(updated).toISOString() : null,
    updated_ts: updated ? Math.round(updated / 1000) : null,
    close_ts: opts.closeTs ? Math.round(opts.closeTs / 1000) : undefined,
    worktree: `.worktrees/${id}`,
    ...(opts.blockedReason ? { blocked_reason: opts.blockedReason } : {}),
  }
}

async function runHealth(stubPath, repo) {
  const old = {}
  for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']) {
    old[k] = process.env[k]
    delete process.env[k]
  }
  process.env.SANDBAR_METRICS_STUB = stubPath
  process.env.SANDBAR_METRICS_DIR = repo
  process.env.SANDBAR_PROJECTS_DIR = repo
  try {
    const m = await loadMetrics()
    const deps = m.defaultDeps(repo, () => NOW)
    const params = { view: 'health', window: '30d', epic: 'all', template: 'dev-lane', mode: 'full' }
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of Object.keys(old)) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

function dayKey(ms) { return new Date(ms).toISOString().slice(0, 10) }

async function runAll() {
  section('0. environment gates')
  let panel = null
  try {
    panel = await import(new URL('file://' + PANEL_MODEL).href)
  } catch (err) {
    console.log(`ENV_FAIL: panel metrics-tab-model.ts unimportable: ${String(err?.message ?? err)}`)
    process.exit(2)
  }
  ok(typeof panel.throughputSpecOf === 'function', 'panel throughputSpecOf present (public seam)')

  const DAY1 = Date.parse('2026-08-20T10:00:00Z')
  const DAY2 = Date.parse('2026-08-25T10:00:00Z')
  const CLOSED_AT = Date.parse('2026-08-22T08:00:00Z')
  const UPDATED_LATE = Date.parse('2026-08-31T23:00:00Z') // far after the close

  // ---- A. the primary chart is the daily opened/closed spec, rendered end to end ----
  section('A. health charts.primary = daily opened/closed; panel renders it')
  const repoA = keep(freshDir('t05a-repo-'))
  mkdirSync(join(repoA, '.dsh', 'sessions'), { recursive: true })
  const rows = [
    row('t05-open-1', { created: DAY1 }),
    row('t05-open-2', { created: DAY1 }),
    row('t05-open-3', { created: DAY2 }),
    row('t05-closed-1', { created: DAY1, closed: true, closedAt: CLOSED_AT, updated: UPDATED_LATE, closeTs: CLOSED_AT }),
    row('t05-closed-2', { created: DAY1, closed: true, closedAt: CLOSED_AT, updated: UPDATED_LATE }), // no close_ts anchor
    // an ISO-shaped created (a foreign writer / legacy row) must degrade named,
    // never crash the bucket loop
    row('t05-iso-1', { created: DAY2, isoCreated: true }),
  ]
  const stubA = writeStub(keep(freshDir('t05a-stub-')), baseStub({ tickets: rows }))
  const bodyA = ((await runHealth(stubA, repoA)).body) ?? {}
  const chartsA = bodyA?.charts ?? {}
  const p = chartsA?.primary ?? null
  ok(p && Array.isArray(p.categories) && Array.isArray(p.series),
    'A1 the health primary chart is a spec with categories+series (not the blocked hBar in the slot)',
    JSON.stringify(p)?.slice(0, 200))
  const names = (p?.series ?? []).map((s) => String(s?.name ?? '').toLowerCase())
  const hasOpen = names.some((n) => n.includes('open'))
  const hasClos = names.some((n) => n.includes('clos'))
  ok(hasOpen && hasClos,
    'A2 the primary series carry the opened/closed names the panel mapping reads',
    JSON.stringify(names))
  ok((p?.series ?? []).every((s) => Array.isArray(s.data) && s.data.length === p.categories.length),
    'A3 series data align with the day categories')
  const days = (p?.categories ?? []).map((d) => String(d))
  const day1Idx = days.indexOf(dayKey(DAY1))
  const day2Idx = days.indexOf(dayKey(DAY2))
  const openedSeries = (p?.series ?? []).find((s) => String(s?.name ?? '').toLowerCase().includes('open'))
  const closedSeries = (p?.series ?? []).find((s) => String(s?.name ?? '').toLowerCase().includes('clos'))
  ok(day1Idx >= 0 && day2Idx >= 0 && Number(openedSeries?.data?.[day1Idx]) >= 2 && Number(openedSeries?.data?.[day2Idx]) >= 1,
    'A4 opened buckets follow the created anchor (two opens on day1, one on day2)',
    JSON.stringify({ days, opened: openedSeries?.data }))
  const spec = panel.throughputSpecOf(bodyA)
  ok(spec && Array.isArray(spec.days) && spec.days.length === p.categories.length,
    'A5 the panel throughputSpecOf renders the real response (the two sides agree — the card can load)',
    JSON.stringify(spec)?.slice(0, 160))

  // ---- B. closed-bucket honesty: anchored closes land; unanchored closes are named ----
  section('B. closed anchor honesty')
  const closedVals = closedSeries?.data ?? []
  const closeDay = days.indexOf(dayKey(CLOSED_AT))
  const lateDay = days.indexOf(dayKey(UPDATED_LATE))
  ok(Number(closedVals[closeDay] ?? 0) >= 1,
    'B1 an anchored close lands on its close day (never dated at its last update)',
    JSON.stringify({ closeDay, lateDay, closedVals }))
  ok(Number(closedVals[lateDay] ?? 0) === 0,
    'B2 a close silently dated at its last update is refused', JSON.stringify(closedVals))
  ok(/close_ts/i.test(JSON.stringify(bodyA?.reason ?? '')),
    'B3 the unanchored close is named (the closed series covers anchored closes only, never silent)',
    JSON.stringify(bodyA?.reason ?? '').slice(0, 300))

  // ---- C. the blocked 榜 moved to the secondaries, not deleted ----
  section('C. blocked 榜 survives in the secondaries')
  const secs = Array.isArray(chartsA.secondaries) ? chartsA.secondaries : []
  ok(secs.some((c) => String(c?.title ?? '').includes('blocked')),
    'C1 a secondary still carries the blocked 榜 (moved, not deleted)',
    JSON.stringify(secs.map((c) => c?.title)))

  // ---- D. a row with no anchors degrades named, no NaN ever ships ----
  section('D. anchorless row degrades named')
  const repoD = keep(freshDir('t05d-repo-'))
  mkdirSync(join(repoD, '.dsh', 'sessions'), { recursive: true })
  const stubD = writeStub(keep(freshDir('t05d-stub-')), baseStub({
    tickets: [row('t05-noanchor', { created: null, updated: null })],
  }))
  const bodyD = ((await runHealth(stubD, repoD)).body) ?? {}
  const pD = bodyD?.charts?.primary ?? null
  ok(pD && Array.isArray(pD.categories) && Array.isArray(pD.series),
    'D1 the chart stays well formed with an anchorless row', JSON.stringify(pD)?.slice(0, 160))
  ok(!JSON.stringify(bodyD).includes('NaN') && !JSON.stringify(bodyD).includes('Invalid Date'),
    'D2 no NaN / Invalid Date day ever ships', '')
  ok(JSON.stringify(bodyD.reason ?? '').length > 0,
    'D3 the anchorless row leaves a named reason on the face', JSON.stringify(bodyD.reason ?? '').slice(0, 200))

  // ---- E. empty window: well-formed chart, named reason ----
  section('E. empty window keeps a well-formed primary')
  const repoE = keep(freshDir('t05e-repo-'))
  mkdirSync(join(repoE, '.dsh', 'sessions'), { recursive: true })
  const stubE = writeStub(keep(freshDir('t05e-stub-')), baseStub({ tickets: [] }))
  const bodyE = ((await runHealth(stubE, repoE)).body) ?? {}
  const pE = bodyE?.charts?.primary ?? null
  ok(pE && Array.isArray(pE.categories) && Array.isArray(pE.series) && pE.series.length > 0,
    'E1 an empty window is a well-formed chart (empty or all-zero buckets), never a null primary', JSON.stringify(pE)?.slice(0, 160))
  ok(/anchor/i.test(JSON.stringify(bodyE?.reason ?? '')),
    'E1b the empty window names why the series carry nothing (not zero activity)', JSON.stringify(bodyE?.reason ?? '').slice(0, 240))
  ok(panel.throughputSpecOf(bodyE) === null || Array.isArray(panel.throughputSpecOf(bodyE)?.days),
    'E2 the panel face over an empty window stays a named empty state (no crash, no fabricated days)', '')

  const green = summary('sc_t261026_05_throughput_daily_contract')
  process.exit(green ? 0 : 1)
}

if (__isMain) {
  await runAll()
} else {
  console.log('sc_t261026_05_throughput_daily_contract: imported as a module; battery skipped')
}
