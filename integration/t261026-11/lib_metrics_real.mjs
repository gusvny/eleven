/**
 * lib_metrics_real.mjs — the REAL metrics payload, captured from the producer.
 *
 * Ticket t261026-11 (the degrade matrix on every read face). The matrix
 * template's rule: the fifth shape is the PRODUCER'S REAL PAYLOAD, and a
 * hand-written stub proves nothing. So the metrics-face scenarios do not ship
 * a stale checked-in fixture — they regenerate the payload at run time by
 * driving the REAL buildMetricsResponse (workbench/src/host/metrics.ts) over
 * the standard fully-stubbed temp harness, the same technique as
 * integration/t261025-14 (whose lib.mjs helpers are reused here). Fixture
 * freshness is mechanical: the fixture is born fresh every run.
 *
 * Offline seconds; needs zstd (for the real archived session fixture); zero
 * docker/Temporal-server/browser; never touches 3099/7233.
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import {
  freshDir, writeStub, baseStub, NOW, loadMetrics, usageEvents,
} from '../../server/plugins/workbench/tests/lib.mjs'

const TMP_DIRS = []
function keep(d) { TMP_DIRS.push(d); return d }
let cleaned = false
process.on('exit', () => {
  if (cleaned) return
  cleaned = true
  for (const d of TMP_DIRS) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best effort */ } }
})

export const HAS_ZSTD = (() => {
  try { execFileSync('zstd', ['--version'], { stdio: 'ignore' }); return true } catch { return false }
})()

/** One archived session under <projects>/<key>/data/tickets/<id>/sessions/<sub>/ */
function putArchivedSession(projectsRoot, key, ticketId, sub, events) {
  try {
    const sessDir = join(projectsRoot, key, 'data', 'tickets', ticketId, 'sessions', sub)
    mkdirSync(sessDir, { recursive: true })
    const raw = join(sessDir, 'raw.jsonl')
    writeFileSync(raw, events.map((e) => JSON.stringify(e)).join('\n') + '\n')
    execFileSync('zstd', ['-f', '-q', raw, '-o', join(sessDir, 'session.jsonl.zstd')])
    rmSync(raw)
    return true
  } catch { return false }
}

/** Closed ticket row — the stub's show body / list row (t261025-14 shape). */
function closedTicketRow(id, closedAt) {
  return {
    id, project: 'demo', epic: 'metrics', title: id, workflow: 'dev-lane',
    stage: 'implement', stage_state: 'closed', status: 'closed', role: 'developer',
    closed_at: closedAt, created_at: closedAt - 86400000, updated_at: closedAt,
  }
}

function mkEnv(projects, repo, stubPath) {
  return {
    SANDBAR_METRICS_STUB: stubPath,
    SANDBAR_METRICS_DIR: projects,
    SANDBAR_PROJECTS_DIR: projects,
    repo,
  }
}

async function runMetrics(m, env, params) {
  const keys = ['SANDBAR_METRICS_STUB', 'SANDBAR_METRICS_DIR', 'SANDBAR_PROJECTS_DIR',
    'SANDBAR_PROJECTS_YAML', 'SANDBAR_USAGE_LEDGER_DIR']
  const old = {}
  for (const k of keys) { old[k] = process.env[k]; delete process.env[k] }
  Object.assign(process.env, env)
  try {
    const deps = m.defaultDeps(env.repo, () => NOW)
    return await m.buildMetricsResponse(params, deps)
  } finally {
    for (const k of keys) {
      if (old[k] === undefined) delete process.env[k]
      else process.env[k] = old[k]
    }
  }
}

/**
 * The producer's real answer, regenerated fresh every run: one closed ticket
 * whose lane is gone and whose archive holds a real session, so the token and
 * caliber faces have live numbers to disagree about.
 */
export async function realMetricsBody() {
  if (!HAS_ZSTD) {
    return { env_fail: 'zstd CLI missing — the real metrics payload cannot be regenerated from the producer' }
  }
  const CLOSED = Date.parse('2026-08-30T06:00:00Z')
  const ID = 't261026-11'
  const repo = keep(freshDir('t11-repo-'))
  const stubDir = keep(freshDir('t11-stub-'))
  const projects = keep(freshDir('t11-projects-'))
  mkdirSync(join(repo, '.worktrees', ID), { recursive: true })
  putArchivedSession(projects, 'demo', ID, `${ID}-developer`, usageEvents())
  const stubPath = writeStub(stubDir, baseStub({ tickets: [closedTicketRow(ID, CLOSED)] }))
  const m = await loadMetrics()
  const res = await runMetrics(m, mkEnv(projects, repo, stubPath),
    { view: 'time', window: '7d', epic: 'all', template: 'dev-lane', mode: 'full' })
  const body = res?.body ?? null
  if (!body || typeof body !== 'object') {
    return { env_fail: `the producer refused: status=${res?.status} body=${JSON.stringify(res?.body).slice(0, 120)}` }
  }
  return { body }
}
