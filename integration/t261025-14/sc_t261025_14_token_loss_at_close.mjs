/**
 * sc_t261025_14_token_loss_at_close.mjs — token loss at close (t261025-14).
 *
 * Grey-box L3 scenario. User-facing rule under test (ticket body, item 1 + 3):
 *   "a closed ticket never loses its usage, and a missing face is named,
 *   never a silent zero."
 *
 * The lane session file dies with the lane at teardown; the archive
 * (<projects-root>/<key>/data/tickets/<id>/sessions/) is the surviving copy
 * (engine archive intake path 3). The metrics face must fall back to the
 * archive when the lane is gone, heal a cached tokens=null record once the
 * archive exists, name a missing face instead of zero-filling, and keep
 * tokens_outside_tickets honest (a zero-usage project block never fabricates
 * a number; null carries the named tickets-only caliber).
 *
 * Seam note (declared in the accepted plan): the archive root/key are derived
 * from the metrics cache dir convention <root>/<key>/data/metrics, so every
 * run pairs SANDBAR_PROJECTS_DIR with SANDBAR_METRICS_DIR under that layout.
 *
 * Drives the REAL buildMetricsResponse over the standard fully-stubbed temp
 * harness (SANDBAR_METRICS_STUB + SANDBAR_METRICS_DIR + SANDBAR_PROJECTS_DIR),
 * real zstd session fixtures, same technique as workbench/tests/
 * metrics-v2-blocks.mjs. Offline seconds, zero docker/Temporal-server/browser,
 * never touches 3099/7233.
 *
 * Run: node integration/t261025-14/sc_t261025_14_token_loss_at_close.mjs
 * Pre-implement the declared surface is absent = the named TDD signal (FAIL
 * naming the missing face); green required at the integration gate/merge.
 * zstd missing = ENV_FAIL exit 2 (never a silent SKIP).
 */
import { mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs'
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
function reclaim() {
  for (const d of TMP_DIRS) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best effort */ } }
}
process.on('exit', reclaim)

const HAS_ZSTD = (() => {
  try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }); return true } catch { return false }
})()

/** Compress events into a zstd session file at an arbitrary session dir. */
function putSession(sessDir, events) {
  if (!HAS_ZSTD) return false
  try {
    mkdirSync(sessDir, { recursive: true })
    const raw = join(sessDir, 'raw.jsonl')
    writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
    execFileSync('zstd', ['-f', '-q', raw, '-o', join(sessDir, 'session.jsonl.zstd')])
    rmSync(raw)
    return true
  } catch { return false }
}

/** Archive-shaped session copy: <projects>/<key>/data/tickets/<id>/sessions/<sub>/ */
function putArchivedSession(projectsRoot, key, ticketId, sub, events) {
  return putSession(join(projectsRoot, key, 'data', 'tickets', ticketId, 'sessions', sub), events)
}

/** Closed ticket row (stub find returns it as the show body, timeline on row). */
function closedTicketRow(id, closedAt) {
  return {
    id, project: 'demo', epic: 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
    updated: new Date(closedAt).toISOString(),
    worktree: `.worktrees/${id}`,
    timeline: [
      { at: new Date(closedAt - 3 * 3600e3).toISOString(), stage: 'plan', state: 'running' },
      { at: new Date(closedAt - 2 * 3600e3).toISOString(), stage: 'review', state: 'running' },
      { at: new Date(closedAt - 3600e3).toISOString(), stage: 'implement', state: 'running' },
      { at: new Date(closedAt).toISOString(), stage: 'implement', state: 'closed' },
    ],
  }
}

/** Env for one projects root. SANDBAR_METRICS_DIR is a ROOT: the cache lands at
 *  <root>/<key>/data/metrics, and the archive seam derives (root,key) from that
 *  dir — so both env vars point at the same projects root by design. */
function mkEnv(projectsRoot, repo, stubPath) {
  return {
    SANDBAR_METRICS_STUB: stubPath,
    SANDBAR_METRICS_DIR: projectsRoot,
    SANDBAR_PROJECTS_DIR: projectsRoot,
    repo,
  }
}

async function runMetrics(m, env) {
  const old = {}
  for (const k of ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']) {
    old[k] = process.env[k]
    delete process.env[k]
  }
  Object.assign(process.env, env)
  try {
    const deps = m.defaultDeps(env.repo, () => NOW)
    const params = { view: 'time', window: '7d', epic: 'all', template: 'dev-lane', mode: 'full' }
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of Object.keys(old)) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

function epicOf(body, name = 'metrics') {
  return Array.isArray(body?.epics) ? body.epics.find((e) => e?.epic === name) : null
}

async function runAll() {
  section('0. environment gates')
  if (!HAS_ZSTD) {
    console.log('ENV_FAIL: zstd CLI missing — session fixtures cannot be built; honest red, not a silent skip')
    process.exit(2)
  }
  ok(typeof HAS_ZSTD === 'boolean', 'zstd present, fixtures buildable')

  const CLOSED = Date.parse('2026-08-30T06:00:00Z')
  const ID = 't261025-14'  // legal ticket-id shape (the archive seam refuses foreign shapes by design)

  // ---- Stage 1: lane gone, archive holds the sessions → usage is NOT lost ----
  section('A. loss at close: lane gone, archive holds sessions → tokens non-null')
  const repo = keep(freshDir('t14-repo-'))
  const stubDir = keep(freshDir('t14-stub-'))
  const projects = keep(freshDir('t14-projects-'))
  mkdirSync(join(repo, '.worktrees', ID), { recursive: true }) // lane torn down: worktree empty
  let fixturesOk = true
  fixturesOk = putArchivedSession(projects, 'demo', ID, `${ID}-developer`, usageEvents()) && fixturesOk
  ok(fixturesOk, 'archive fixture written (data/tickets/<id>/sessions/**)')

  const stubPath = writeStub(stubDir, baseStub({ tickets: [closedTicketRow(ID, CLOSED)] }))
  const m = await loadMetrics()
  const body = ((await runMetrics(m, mkEnv(projects, repo, stubPath))).body) ?? {}
  const epic = epicOf(body)
  ok(typeof epic?.tokens === 'number' && epic.tokens > 0,
    'A1 closed ticket with a dead lane keeps its usage via the archive (tokens non-null, not a silent zero)',
    JSON.stringify(epic?.tokens))
  // The declared per-ticket record contract (v3) keeps the cacheRead dimension
  // through the fallback — read the cache file on the reader side.
  let recCacheRead = null
  try {
    recCacheRead = JSON.parse(readFileSync(join(projects, 'demo', 'data', 'metrics', `${ID}.json`), 'utf8'))?.tokens?.cacheRead  // cache = <root>/<key>/data/metrics
  } catch { /* absent */ }
  ok(typeof recCacheRead === 'number' && recCacheRead > 0,
    'A2 the cacheRead dimension survives the archive round trip on the per-ticket record', JSON.stringify(recCacheRead))
  ok(typeof epic?.reason !== 'string' || epic.reason === '',
    'A3 no missing-face reason while the archive answers', JSON.stringify(epic?.reason))

  // ---- Stage 2: healing — a tokens=null cached record repairs once the archive exists ----
  section('B. healing: cached tokens=null record recomputed after the archive appears')
  const projectsBefore = keep(freshDir('t14-projects-heal-')) // NO archive yet
  const envHeal = mkEnv(projectsBefore, repo, stubPath)
  const bodyBefore = ((await runMetrics(m, envHeal)).body) ?? {}
  const epicBefore = epicOf(bodyBefore)
  ok(epicBefore?.tokens === null,
    'B1 no lane, no archive yet: tokens=null (never zero-filled)', JSON.stringify(epicBefore?.tokens))
  ok(typeof epicBefore?.reason === 'string' && epicBefore.reason.length > 0,
    'B2 the missing face is NAMED with a reason', JSON.stringify(epicBefore?.reason))
  // Now the archive appears (the close-out copy lands) and the record must heal.
  putArchivedSession(projectsBefore, 'demo', ID, `${ID}-developer`, usageEvents())
  const bodyAfter = ((await runMetrics(m, envHeal)).body) ?? {}
  const epicAfter = epicOf(bodyAfter)
  ok(typeof epicAfter?.tokens === 'number' && epicAfter.tokens > 0,
    'B3 the cached tokens=null record heals once the archive exists (no permanent null)', JSON.stringify(epicAfter?.tokens))
  ok(epicAfter?.tokens === epic?.tokens,
    'B4 healed record matches the direct-compute record (same archive, same number)', JSON.stringify(epicAfter?.tokens))

  // ---- Stage 3: lane alive wins; archive only a fallback ----
  section('C. lane alive: lane sessions win, archive not consulted')
  const repoLive = keep(freshDir('t14-repo-live-'))
  const projectsLive = keep(freshDir('t14-projects-live-'))
  mkdirSync(join(repoLive, '.worktrees', ID, '.dsh', 'sessions', 'slug0', `${ID}-developer`), { recursive: true })
  const laneEvents = usageEvents().map((e) => e.type === 'assistant/message'
    ? { ...e, data: { usage: { inputTokens: 1000, outputTokens: 100, cacheReadTokens: 7 } } }
    : e)
  const laneOk = putSession(join(repoLive, '.worktrees', ID, '.dsh', 'sessions', 'slug0', `${ID}-developer`), laneEvents)
  ok(laneOk, 'lane session fixture written')
  // decoy archive with small numbers — must be ignored while the lane lives
  putArchivedSession(projectsLive, 'demo', ID, `${ID}-developer`, usageEvents())
  const stubLive = writeStub(keep(freshDir('t14-stub-live-')), baseStub({ tickets: [closedTicketRow(ID, CLOSED)] }))
  const liveBody = ((await runMetrics(m, mkEnv(projectsLive, repoLive, stubLive))).body) ?? {}
  const liveEpic = epicOf(liveBody)
  // Control: the SAME lane with NO archive on disk. If the numbers match the
  // decoy run, the archive was never consulted while the lane lives.
  const projectsCtl = keep(freshDir('t14-projects-livectl-'))
  const ctlBody = ((await runMetrics(m, mkEnv(projectsCtl, repoLive, stubLive))).body) ?? {}
  const ctlEpic = epicOf(ctlBody)
  ok(typeof liveEpic?.tokens === 'number' && liveEpic.tokens > 100,
    'C1 lane alive: the total exceeds the archive decoy alone (lane source dominates)', JSON.stringify(liveEpic?.tokens))
  ok(JSON.stringify(liveEpic?.tokens) === JSON.stringify(ctlEpic?.tokens),
    'C2 lane alive: with-archive and without-archive runs agree byte for byte (archive not consulted)', JSON.stringify(ctlEpic?.tokens))

  // ---- Stage 4: corrupt file among good ones → named, never silent, never crash ----
  section('D. corrupt archive file: named reason, good files still aggregate')
  const projectsCorrupt = keep(freshDir('t14-projects-corrupt-'))
  fixturesOk = putArchivedSession(projectsCorrupt, 'demo', ID, `${ID}-developer`, usageEvents()) && fixturesOk
  // pseudo-zstd garbage next to the good file
  mkdirSync(join(projectsCorrupt, 'demo', 'data', 'tickets', ID, 'sessions', `${ID}-reviewer`), { recursive: true })
  writeFileSync(join(projectsCorrupt, 'demo', 'data', 'tickets', ID, 'sessions', `${ID}-reviewer`, 'session.jsonl.zstd'), 'not-zstd-at-all')
  const corruptBody = ((await runMetrics(m, mkEnv(projectsCorrupt, repo, stubPath))).body) ?? {}
  const corruptEpic = epicOf(corruptBody)
  ok(typeof corruptEpic?.tokens === 'number' && corruptEpic.tokens > 0,
    'D1 good files still aggregate next to a corrupt one (one bad file never zeroes the face)', JSON.stringify(corruptEpic?.tokens))
  ok(JSON.stringify(corruptBody).includes('reason'),
    'D2 the corrupt file leaves a named reason somewhere on the face (never silent)', '')

  // ---- Stage 5: tokens_outside_tickets honest degradation ----
  section('E. tokens_outside_tickets: zero-usage block never fabricates a number; null names the tickets-only caliber')
  const repoZero = keep(freshDir('t14-repo-zero-'))
  const projectsZero = keep(freshDir('t14-projects-zero-'))
  // project-level session file present but carrying ZERO usage events
  putSession(join(repoZero, '.dsh', 'sessions', 'executor', 'manual-1'), [
    { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
  ])
  const zeroBody = ((await runMetrics(m, mkEnv(projectsZero, repoZero, stubPath))).body) ?? {}
  ok(zeroBody.kpis?.tokens_outside_tickets === null || zeroBody.kpis?.tokens_outside_tickets === 0,
    'E1 a zero-usage project block degrades to null or an honest 0 — never a fabricated positive', JSON.stringify(zeroBody.kpis?.tokens_outside_tickets))
  // block absent entirely → null is legal, but only named
  const noneBody = ((await runMetrics(m, mkEnv(keep(freshDir('t14-projects-none-')), repo, stubPath))).body) ?? {}
  ok(noneBody.kpis?.tokens_outside_tickets === null,
    'E2 no project-level block: null (existing degrade), never a fabricated 0', JSON.stringify(noneBody.kpis?.tokens_outside_tickets))
  // The tickets-only notice surfaces on the merged reason face (notices join into body.reason).
  const allText = JSON.stringify(noneBody)
  ok(allText.includes('tickets only'),
    'E3 the null carries the named tickets-only caliber on the face (the reader can tell what the total covers)',
    JSON.stringify(noneBody.reason ?? '').slice(0, 400))

  // ---- Stage 6: window discipline on archived sessions ----
  section('F. window: archived events outside the closed window never enter the stage slice')
  const projectsWin = keep(freshDir('t14-projects-win-'))
  // events stamped far outside the ticket life (creation..close) → stage slice excludes them
  putArchivedSession(projectsWin, 'demo', ID, `${ID}-developer`, [
    { type: 'request/context', data: { provider: 'deepseek', model: 'v3.2' }, time: 1 },
    { type: 'assistant/message', data: { usage: { inputTokens: 100, outputTokens: 10, cacheReadTokens: 5 } }, time: 2 },
    { type: 'assistant/message', data: { usage: { inputTokens: 999999, outputTokens: 999999, cacheReadTokens: 999999 } }, time: 4e9 },
  ])
  const winBody = ((await runMetrics(m, mkEnv(projectsWin, repo, stubPath))).body) ?? {}
  const winEpic = epicOf(winBody)
  ok(typeof winEpic?.tokens === 'number' && winEpic.tokens > 0,
    'F1 the archived ticket still aggregates (total present)', JSON.stringify(winEpic?.tokens))
  // The declared per-ticket record's stage slice must respect closed_ms: the
  // out-of-life bursts must not appear in ANY stage row.
  let byStage = null
  try {
    byStage = JSON.parse(readFileSync(join(projectsWin, 'demo', 'data', 'metrics', `${ID}.json`), 'utf8'))?.tokens?.by_stage ?? {}
  } catch { /* absent */ }
  const stageIn = Object.values(byStage).reduce((s2, r) => s2 + (r?.in ?? 0), 0)
  ok(stageIn < 999999,
    'F2 the out-of-life event bursts never enter the stage slice (stage in total far below the burst size)',
    JSON.stringify(byStage))

  const green = summary('sc_t261025_14_token_loss_at_close')
  process.exit(green ? 0 : 1)
}

if (__isMain) {
  await runAll()
} else {
  console.log('sc_t261025_14_token_loss_at_close: imported as a module; battery skipped (run the file directly)')
}
