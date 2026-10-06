// one-shot spawn endpoint UT (t261006-06): route-table parity entry, write
// credential gate (401 before anything), unapproved request never reaches the
// spawn caller, answered request forwards {project, request_id, action} and
// nothing else (no smuggled privilege keys), watchdog refusal / non-receipt /
// throw all normalize into spawned:false with a named reason. All stubs:
// zero real watchdog, zero ~/.sandbar, zero network.
import { assert, done, freshDir, cleanup, isolatedEnv, memLedgerIo, fakeClock, panelCookieFor } from './lib.mjs'
import { createApi, PANEL_API_ROUTES } from '../src/host/api.ts'

let n = 0
const clock = fakeClock()
const Q = (s = '') => new URLSearchParams(s)

assert(PANEL_API_ROUTES.some((r) => r.path === '/sandbar-executor-panel/api/one-shot/spawn' && r.methods.includes('POST')), 'spawn route in table, POST-only')
n += 1

const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const reqRow = JSON.stringify({ type: 'request', id: 'req-1', at: 1, project: 'alpha', kind: 'approval', question: 'q', detail: '', default_action: '', expires_at: null, raised_by: 'session-exec' }) + '\n'
const ansRow = JSON.stringify({ type: 'answer', answer_for: 'req-1', at: 2, by: 'host', answer: 'approved' }) + '\n'

function makeApi(over = {}, files = {}) {
  const calls = []
  const api = createApi(env, {
    now: () => clock.now(),
    ledgerIo: memLedgerIo({ [`${pan}/alpha/requests.jsonl`]: reqRow + ansRow, ...files }),
    spawnCaller: async (a) => { calls.push(a); return over.spawnResult ? over.spawnResult(a) : { ok: true, receipt: { action: 'done', sessionId: 's-1' } } },
    ...over.deps,
  })
  return { api, calls }
}

const COOKIE = panelCookieFor('127.0.0.1:3099')
const auth = { host: '127.0.0.1:3099', cookie: COOKIE }

// 401 before anything: no credential, spawn caller never called.
{
  const { api, calls } = makeApi()
  const r = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'rotate key' }), '', {})
  assert(r.status === 401 && calls.length === 0, 'no credential: 401, nothing forwarded')
  n += 1
}

// GET refused (405), non-JSON body refused (400).
{
  const { api, calls } = makeApi()
  const g = await api.handle('GET', '/sandbar-executor-panel/api/one-shot/spawn', Q('project=alpha'), '', '', auth)
  assert(g.status === 405 && calls.length === 0, 'GET on spawn face refused')
  const b = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), 'not json', '', auth)
  assert(b.status === 400 && calls.length === 0, 'non-JSON body refused')
  const m = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1' }), '', auth)
  assert(m.status === 400 && m.json.error.includes('action'), 'missing action refused')
  n += 3
}

// Unapproved: waiting request never reaches the caller.
{
  const waitingFiles = { [`${pan}/alpha/requests.jsonl`]: reqRow }
  const { api, calls } = makeApi({}, waitingFiles)
  const r = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'rotate key' }), '', auth)
  assert(r.status === 409 && calls.length === 0 && r.json.error.includes('not answered'), 'unapproved request spawns nothing at the panel face')
  n += 1
}

// Unknown request: 404.
{
  const { api, calls } = makeApi()
  const r = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-404', action: 'x' }), '', auth)
  assert(r.status === 404 && calls.length === 0, 'unknown request: 404, nothing forwarded')
  n += 1
}

// Approved: forwarded with exactly the whitelist payload; receipt surfaced.
{
  const { api, calls } = makeApi()
  const r = await api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'rotate key', preset: 'evil', scope: ['/etc'] }), '', auth)
  assert(r.status === 200 && r.json.ok === true && r.json.spawn.spawned === true, 'approved request forwards and reports spawned')
  assert(calls.length === 1 && calls[0].requestId === 'req-1' && calls[0].action === 'rotate key', 'forwarded args are {project, request_id, action}')
  assert(!('preset' in calls[0]) && !('scope' in calls[0]), 'smuggled privilege keys never forwarded')
  n += 3
}

// Watchdog refusal / non-receipt / throw: explicit spawned:false, named reason.
{
  const a = makeApi({ spawnResult: () => ({ ok: false, reason: 'approval for request req-1 already consumed by run s-9' }) })
  const r = await a.api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'x' }), '', auth)
  assert(r.status === 200 && r.json.spawn.spawned === false && r.json.spawn.reason.includes('already consumed'), 'watchdog refusal surfaces as spawned:false with the named reason')
  n += 1
  const b = makeApi({ spawnResult: () => ({ ok: false, reason: 'watchdog spawn endpoint HTTP 500' }) })
  const r2 = await b.api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'x' }), '', auth)
  assert(r2.json.spawn.spawned === false && r2.json.spawn.reason.includes('HTTP 500'), 'watchdog failure named, never pretend-spawned')
  n += 1
  const c = makeApi({ spawnResult: () => { throw new Error('boom') } })
  const r3 = await c.api.handle('POST', '/sandbar-executor-panel/api/one-shot/spawn', Q(), JSON.stringify({ project: 'alpha', request_id: 'req-1', action: 'x' }), '', auth)
  assert(r3.json.spawn.spawned === false && r3.json.spawn.reason.includes('boom'), 'caller throw normalized to explicit failure')
  n += 1
}

cleanup([wd, pan])
done(n)
