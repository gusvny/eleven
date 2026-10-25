/**
 * t261026_01_archive_backfill.mjs — t261026-01 tests.
 *
 * DEFECT under test: the metrics KPI population was template-cut BEFORE the
 * window, and legacy-era rows came back from the list without
 * workflow/created/updated/lane_version (the engine's minimal-row projection
 * drops them; the on-disk ticket store carries them). The face counted 43
 * tickets in every window while the store held 422.
 *
 * Pinned here:
 * - ticket-archive module: store-dir resolution + named disable; per-file fault
 *   isolation (missing/malformed archive.json → named unreadable, never a
 *   throw); a failed listing is never cached as good; backfill fills EMPTY row
 *   fields only, verbatim archive data, nothing invented; lane_version is
 *   never an input to any decision.
 * - metrics face (full + fast): the KPI population is project-level — the
 *   window moves the count across templates; a backfilled legacy row enters its
 *   template's workflows block AND the totals (archive-backed anchor); a
 *   chain-less row is counted in the totals, excluded from the chain blocks,
 *   and the exclusion is counted in a notice (named degrade, no invented
 *   chain); the store delta (tickets the population does not reach) is named in
 *   a notice; epic=<code> scopes the totals to that epic's rows.
 *
 * Run: node server/plugins/workbench/tests/t261026_01_archive_backfill.mjs
 * (cwd = repo root). Fully offline: SANDBAR_METRICS_STUB + SANDBAR_METRICS_DIR +
 * SANDBAR_TICKETS_DIR temp fixtures, zero real ~/.sandbar / admin.py / git.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  freshDir, writeStub, baseStub, closedTicket, NOW, ok, summary, dumpFails,
} from './lib.mjs'

const { buildMetricsResponse, defaultDeps } = await import(new URL('./../src/host/metrics.ts', import.meta.url).pathname)
const ta = await import(new URL('./../src/host/ticket-archive.ts', import.meta.url).pathname)

const saved = {}
for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR', 'SANDBAR_TICKETS_DIR', 'SANDBAR_PROJECTS_YAML']) {
  saved[k] = process.env[k]
  delete process.env[k]
}
// A poisoned home would make resolveTicketsDir hit the real store; every case
// sets SANDBAR_TICKETS_DIR explicitly, and this guard keeps a slip non-fatal.
delete process.env.SANDBAR_PROJECTS_YAML

function section(t) { console.log(`\n== ${t}`) }
const NOW_S = Math.floor(NOW / 1000)

function writeArchive(root, project, id, meta, raw) {
  const dir = join(root, project, 'data', 'tickets', id)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'archive.json'), raw !== undefined ? raw : JSON.stringify({ schema: 'v1', ticket_id: id, meta }), 'utf8')
}

async function withEnv(ticketsRoot, stub, fn) {
  process.env.SANDBAR_TICKETS_DIR = ticketsRoot
  process.env.SANDBAR_METRICS_STUB = writeStub(freshDir('t26-stub-'), stub)
  const cacheRoot = freshDir('t26-cache-')
  process.env.SANDBAR_METRICS_DIR = cacheRoot
  ta.resetArchiveCacheForTests()
  try {
    return await fn()
  } finally {
    delete process.env.SANDBAR_TICKETS_DIR
    delete process.env.SANDBAR_METRICS_STUB
    delete process.env.SANDBAR_METRICS_DIR
    ta.resetArchiveCacheForTests()
    rmSync(cacheRoot, { recursive: true, force: true })
  }
}

const QUICK_STAGES = [{ id: 'ask', role: 'planner', exit: 'agent' }]

// ---------------------------------------------------------------------------
section('A. ticket-archive module: resolution, fault isolation, no invention')
{
  const root = mkdtempSync(join(tmpdir(), 't26-unit-'))
  process.env.SANDBAR_TICKETS_DIR = root
  ta.resetArchiveCacheForTests()
  try {
    const dis = ta.resolveTicketsDir('demo')
    ok('A1 missing store dir → disabled + named reason', dis.enabled === false && String(dis.reason).includes('missing'), JSON.stringify(dis))
    const r0 = await ta.readArchiveIndex('demo')
    ok('A2 disabled read → index null + reason, no throw', r0.index === null && r0.reason !== '')

    // Hard failure is not cached: the same dir appearing later must be read.
    writeArchive(root, 'demo', 't26-a1', { created: NOW_S - 3600, workflow_id: 'dev-lane', lane_version: 'legacy-v1', updated: NOW_S - 60 })
    const r1 = await ta.readArchiveIndex('demo')
    ok('A3 store appears after a failed read → read (failure not cached)', r1.index !== null && r1.index.metas.size === 1, r1.reason)
    const m = r1.index.metas.get('t26-a1')
    ok('A4 meta parsed (created epoch, workflow, legacy lane_version)', m?.created === NOW_S - 3600 && m?.workflow === 'dev-lane' && m?.laneVersion === 'legacy-v1', JSON.stringify(m))

    // Fault isolation: no archive.json (dir only), truncated JSON, wrong types,
    // lane_version absent — the rest of the map is unaffected.
    writeArchive(root, 'demo', 't26-a2', {}, '')                 // truncated JSON
    mkdirSync(join(root, 'demo', 'data', 'tickets', 't26-a3'), { recursive: true }) // no file
    writeArchive(root, 'demo', 't26-a4', { created: 'not-a-number', workflow_id: 42, lane_version: null })
    writeArchive(root, 'demo', 't26-a5', { created: NOW_S - 7200, workflow_id: 'dev-lane', updated: NOW_S - 30 }) // no lane_version
    writeArchive(root, 'demo', 't26-a6', { created: NOW_S - 60, workflow_id: '' })   // chain unknown on disk
    ta.resetArchiveCacheForTests()   // the TTL cache must not serve the pre-write listing
    const r2 = await ta.readArchiveIndex('demo')
    ok('A5 unreadable ids named, never thrown', r2.index !== null && r2.index.unreadable.includes('t26-a2') && r2.index.unreadable.includes('t26-a3'), JSON.stringify(r2.index?.unreadable))
    const m4 = r2.index.metas.get('t26-a4')
    ok('A6 wrong-typed fields degrade to empty (no coercion, no invention)', m4?.created === null && m4?.workflow === '' && m4?.laneVersion === '', JSON.stringify(m4))
    const m5 = r2.index.metas.get('t26-a5')
    ok('A7 absent lane_version → \'\' (recent-archive shape)', m5?.laneVersion === '' && m5?.workflow === 'dev-lane', JSON.stringify(m5))

    // Backfill: fills EMPTY fields only, verbatim; nothing invented.
    const row = { id: 't26-a1', workflow: '', created: null, lane_version: '', updated: '', updated_ts: 0 }
    ok('A8 backfill fills all four from the archive', ta.backfillRowFromArchive(row, m) === true
      && row.workflow === 'dev-lane' && row.created === NOW_S - 3600
      && row.lane_version === 'legacy-v1' && row.updated_ts === NOW_S - 60 && row.updated !== '', JSON.stringify(row))
    const rowFull = { id: 't26-a1', workflow: 'quickmanual', created: 1, lane_version: 'develop-buffer-v1', updated: 'x', updated_ts: 5 }
    ok('A9 backfill never overwrites a non-empty row field', ta.backfillRowFromArchive(rowFull, m) === false
      && rowFull.workflow === 'quickmanual' && rowFull.created === 1 && rowFull.updated_ts === 5)
    const m6 = r2.index.metas.get('t26-a6')
    const rowChainless = { id: 't26-a6', workflow: '', created: null }
    ok('A10 empty archive workflow stays empty (chain unknown ≠ invented)', ta.backfillRowFromArchive(rowChainless, m6) === true
      && rowChainless.workflow === '' && rowChainless.created === NOW_S - 60)
    ok('A11 malformed row is a safe no-op', ta.backfillRowFromArchive(null, m) === false)
    const n = ta.backfillRowsFromArchive([{ id: 't26-a1', workflow: '' }, { id: 't26-a2', workflow: '' }, { id: 'nope', workflow: '' }], r1.index)
    ok('A12 batch backfill counts changed rows only', n === 1)
  } finally {
    delete process.env.SANDBAR_TICKETS_DIR
    ta.resetArchiveCacheForTests()
    rmSync(root, { recursive: true, force: true })
  }
}

// ---------------------------------------------------------------------------
section('B. metrics face: project-level population, named degrades, invariant')
{
  const root = mkdtempSync(join(tmpdir(), 't26-metrics-'))
  const t0 = NOW - 3 * 86400e3
  const closedAt = NOW - 2 * 86400e3
  // Universe: 2 live dev-lane, 1 quickmanual (another template), 1 legacy row
  // (empty workflow, archive-backed), 1 chain-less row with NO archive at all.
  const live1 = closedTicket('t26-b1', baseStub(), { t0, closedAt })
  const live2 = closedTicket('t26-b2', baseStub(), { t0: t0 + 3600e3, closedAt: closedAt + 3600e3 })
  const quick = { ...closedTicket('t26-b3', baseStub(), { t0, closedAt }), workflow: 'quickmanual' }
  const legacy = {
    id: 't26-b4', project: 'demo', epic: 'metrics', title: 'legacy', workflow: '',
    stage: null, stage_state: 'closed', status: 'closed', role: null,
    created: Math.floor(t0 / 1000), close_ts: Math.floor(closedAt / 1000),
    updated: '', updated_ts: 0,
  }
  const chainless = {
    id: 't26-b5', project: 'demo', epic: 'metrics', title: 'chainless', workflow: '',
    stage: null, stage_state: 'closed', status: 'closed', role: null,
    created: Math.floor(t0 / 1000), close_ts: Math.floor(closedAt / 1000),
    updated: '', updated_ts: 0,
  }
  const stub = baseStub({
    workflows: [
      { id: 'dev-lane', name: 'dev-lane', lane: 'lane', stages: [{ id: 'plan', role: 'planner', exit: 'agent' }, { id: 'review', role: 'reviewer', exit: 'human' }, { id: 'implement', role: 'developer', exit: 'agent' }] },
      { id: 'quickmanual', name: 'quickmanual', lane: 'lane', stages: QUICK_STAGES },
    ],
    tickets: [live1, live2, quick, legacy, chainless],
  })
  // Store: archive for the legacy row (names dev-lane — real data, not an
  // invention) and for ONE store-only ticket absent from the live list and the
  // metrics cache (the named store-delta case).
  writeArchive(root, 'demo', 't26-b4', {
    created: Math.floor(t0 / 1000), updated: Math.floor(closedAt / 1000),
    workflow_id: 'dev-lane', lane_version: 'legacy-v1',
  })
  writeArchive(root, 'demo', 't26-b9', { created: Math.floor(t0 / 1000), workflow_id: 'dev-lane' })

  await withEnv(root, stub, async () => {
    const deps = defaultDeps('/stub-repo', () => NOW)
    const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
    ok('B1 200', r.status === 200, JSON.stringify(r.body).slice(0, 300))
    const k = r.body.kpis
    const reason = String(r.body.reason ?? '')
    // The invariant: totals == the population the face actually holds
    // (4 rows in-window: b1,b2,b3,b4; b5 is in-window too → 5; b9 is
    // store-only → named, not counted).
    ok('B2 totals are project-level and windowed (tickets=5, closed=5)',
      k.tickets === 5 && k.closed === 5, JSON.stringify({ k, reason: reason.slice(0, 200) }))
    ok('B3 the window moves the count (30d same, but the template cut no longer pins it)',
      k.tickets !== 43, String(k.tickets))
    const wfDev = (r.body.workflows ?? []).find((w) => w.workflow === 'dev-lane')
    const wfQuick = (r.body.workflows ?? []).find((w) => w.workflow === 'quickmanual')
    ok('B4 backfilled legacy row enters its template block (dev-lane tickets=3)',
      wfDev?.tickets === 3, JSON.stringify(r.body.workflows))
    ok('B5 other templates still span the v2 block (quickmanual tickets=1)', wfQuick?.tickets === 1)
    const chainlessNotice = reason.includes('empty workflow or are absent from the workflow table')
    ok('B6 chain-less row: in totals, out of chain blocks, exclusion counted',
      chainlessNotice && !reason.includes('t26-b5:'), reason.slice(0, 300))
    ok('B7 store delta named on the face (1 store-only ticket)',
      reason.includes('1 tickets in the ticket store (data/tickets) are absent from the metrics population'), reason.slice(0, 400))
    ok('B8 template-chart exclusion counted (quickmanual + chain-less rows out of the per-template charts)',
      reason.includes('2 tickets of other or unknown templates are counted in the project totals but excluded from the per-template charts'), reason.slice(0, 400))
    ok('B9 charts stay per-template (stage axis is the selected chain)',
      JSON.stringify(r.body.charts).includes('plan'), '')

    // Epic scoping: the totals follow the epic filter (the invariant holds per
    // scope, never unconditionally).
    const depsE = defaultDeps('/stub-repo', () => NOW)
    const re = await buildMetricsResponse({ view: 'time', window: '7d', epic: 'metrics' }, depsE)
    ok('B10 epic=<code> totals scope to that epic (same 5 here: all rows carry it)',
      re.body.kpis.tickets === 5, JSON.stringify(re.body.kpis))
  })

  // Epic-scoped difference: give the quickmanual row no epic → epic=metrics drops it.
  await withEnv(root, stub, async () => {
    const quickNoEpic = { ...quick, epic: '' }
    const stub2 = { ...stub, tickets: [live1, live2, quickNoEpic, legacy, chainless] }
    // withEnv already pinned the ORIGINAL stub path; re-pin with stub2 before
    // defaultDeps reads the env (stubDeps reads the env lazily at call time).
    process.env.SANDBAR_METRICS_STUB = writeStub(freshDir('t26-stub-'), stub2)
    const deps = defaultDeps('/stub-repo', () => NOW)
    const r = await buildMetricsResponse({ view: 'time', window: '7d', epic: 'metrics' }, deps)
    ok('B11 epic filter scopes the totals (tickets=4 without the epic-less row)',
      r.body.kpis.tickets === 4, JSON.stringify(r.body.kpis))
  })

  // Malformed archive for the legacy row → named unreadable, row stays
  // chain-less, face still 200 and the invariant path intact.
  {
    const root2 = mkdtempSync(join(tmpdir(), 't26-bad-'))
    writeArchive(root2, 'demo', 't26-b4', {}, '{truncated')
    await withEnv(root2, stub, async () => {
      const deps = defaultDeps('/stub-repo', () => NOW)
      const r = await buildMetricsResponse({ view: 'time', window: '7d' }, deps)
      const reason = String(r.body.reason ?? '')
      ok('B12 malformed archive: face 200, legacy row chain-less (tickets=5 still)',
        r.status === 200 && r.body.kpis.tickets === 5, JSON.stringify({ s: r.status, k: r.body.kpis }))
      ok('B13 malformed archive: dev-lane block back to 2, no invented chain',
        (r.body.workflows ?? []).find((w) => w.workflow === 'dev-lane')?.tickets === 2, JSON.stringify(r.body.workflows))
      ok('B14 malformed archive: unreadable id named', reason.includes('t26-b4') || reason.includes('empty workflow'), reason.slice(0, 300))
    })
    rmSync(root2, { recursive: true, force: true })
  }

  // Fast mode is cache-first (existing contract: 缺票不现算): the chained rows
  // have no cache here, so they are named skips; the chain-less row is counted
  // via its row-anchor synthetic record (fast never needs the store read twice).
  await withEnv(root, stub, async () => {
    const deps = defaultDeps('/stub-repo', () => NOW)
    const rf = await buildMetricsResponse({ view: 'time', window: '7d', mode: 'fast' }, deps)
    const reasonF = String(rf.body.reason ?? '')
    ok('B15 fast mode: chain-less row counted from the row anchor; chained rows are named skips',
      rf.status === 200 && rf.body.kpis.tickets === 1 && reasonF.includes('t26-b1') && reasonF.includes('fast'),
      JSON.stringify({ k: rf.body.kpis, r: reasonF.slice(0, 200) }))
  })
}

const okAll = summary('t261026_01_archive_backfill')
if (!okAll) console.log('FAILED:\n' + dumpFails().map((f) => '  - ' + f).join('\n'))
for (const [k, v] of Object.entries(saved)) {
  if (v === undefined) delete process.env[k]
  else process.env[k] = v
}
process.exit(okAll ? 0 : 1)
