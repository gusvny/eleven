// t261004-29 UT: wake on answer (panel side). Mirrors the registered scenario
// contract at the unit level: receipt merge on success, refused answer wakes nobody,
// wake failure never touches the 200, non-receipt results normalized, malformed
// inputs never reach the wake face, and the default caller degrades explicitly when
// no watchdog base is resolvable. All io in-memory (zero 3099/7233, zero network).
import { appendRequest, fsLedgerIo } from '../src/host/requests.ts'
import { createApi } from '../src/host/api.ts'
import { assert, done, freshDir, cleanup, isolatedEnv, fakeClock, authPass } from './lib.mjs'

let count = 0
function n(k) { count += k }
const wd = freshDir(), pan = freshDir()
const env = isolatedEnv(wd, pan)
const clock = fakeClock()
const PROJ = 'alpha'
let seq = 0
function seed(api, question) {
  seq += 1
  const r = appendRequest(fsLedgerIo, env, PROJ, { kind: 'question', question, raised_by: 'executor-x' }, 1_700_000_000_000 + seq)
  return r.row.id
}
function apiWith(wakeImpl) {
  const calls = []
  const a = createApi(env, {
    now: () => clock.now(),
    fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'workbench-workflows' }),
    authFace: authPass, // KI-193: POST faces are credentialed; the stub face keeps the UT on the wake contract
    wakeCaller: async (args) => { calls.push(args); return wakeImpl(args) },
  })
  return { a, calls }
}
async function answer(a, body) {
  return a.handle('POST', '/sandbar-executor-panel/api/requests/answer', new URLSearchParams(), JSON.stringify(body), 'http://console.test')
}

// ① happy path: one wake call with the request id; receipt merged into the 200.
{
  const id = seed(null, 'Sign t-1?')
  const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'delivered' } }))
  const res = await answer(a, { project: PROJ, id, answer: 'yes', by: 'host' })
  assert(res.status === 200 && res.json.ok === true && res.json.answered, 'answer still 200 with answered row')
  assert(res.json.wake && res.json.wake.attempted === true && res.json.wake.woke === true && res.json.wake.reason === 'delivered', 'receipt merged additively (attempted/woke/reason)')
  assert(calls.length === 1 && calls[0].requestId === id && calls[0].project === PROJ, 'wake called once with the answered request identity')
  n(5)
}

// ② refused second answer: no wake call.
{
  const api0 = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'x' } }))
  const id = seed(null, 'Sign t-2?')
  await answer(api0.a, { project: PROJ, id, answer: 'yes' })
  const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'x' } }))
  const res = await answer(a, { project: PROJ, id, answer: 'changed' })
  assert(res.status === 409 && calls.length === 0, 'refused second answer wakes nobody')
  n(1)
}

// ③ wake failure: answer 200 + persisted, attempted=false with named reason.
{
  const id = seed(null, 'Sign t-3?')
  const { a } = apiWith(async () => ({ ok: false, reason: 'transport error: connect ECONNREFUSED' }))
  const res = await answer(a, { project: PROJ, id, answer: 'yes' })
  assert(res.status === 200 && res.json.ok === true, 'answer survives wake failure')
  assert(res.json.wake.attempted === false && res.json.wake.woke === false && /ECONNREFUSED/.test(res.json.wake.reason), 'failure receipt names the transport error')
  const read = await a.handle('GET', '/sandbar-executor-panel/api/requests', new URLSearchParams(`project=${PROJ}`), '')
  const row = read.json.rows.find(x => x.id === id)
  assert(row && row.status === 'answered', 'answer persisted despite wake failure')
  n(3)
}

// ④ non-receipt-shaped result: normalized, never echoed verbatim.
{
  const id = seed(null, 'Sign t-4?')
  const { a } = apiWith(async () => ({ ok: true, receipt: { woke: 'yes', tried: 1 } }))
  const res = await answer(a, { project: PROJ, id, answer: 'yes' })
  assert(res.json.wake.attempted === false && typeof res.json.wake.reason === 'string' && res.json.wake.woke !== 'yes', 'garbage receipt normalized to explicit failure')
  n(1)
}

// ⑤ malformed inputs: named 4xx, wake face never reached.
{
  const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'x' } }))
  const id = seed(null, 'Sign t-5?')
  const badJson = await a.handle('POST', '/sandbar-executor-panel/api/requests/answer', new URLSearchParams(), '{nope', '')
  assert(badJson.status === 400, 'non-JSON body → 400')
  const badId = await answer(a, { project: PROJ, id: 42, answer: 'x' })
  assert(badId.status === 400, 'non-string id → 400')
  const badProj = await answer(a, { project: '../escape', id, answer: 'x' })
  assert(badProj.status === 400, 'malformed project key → 400')
  assert(calls.length === 0, 'malformed inputs never reach the wake face')
  n(4)
}

// ⑥ default caller (no wakeCaller injected): unresolvable base → explicit no-op receipt.
{
  const a = createApi(env, { now: () => clock.now(), fetchTemplateFacts: async () => ({ ok: false, reason: 'stub', source: 'workbench-workflows' }), authFace: authPass })
  const id = seed(null, 'Sign t-6?')
  const res = await a.handle('POST', '/sandbar-executor-panel/api/requests/answer', new URLSearchParams(), JSON.stringify({ project: PROJ, id, answer: 'yes' }), '')
  assert(res.status === 200 && res.json.ok === true, 'default caller: answer still 200')
  assert(res.json.wake.attempted === false && /base not resolvable/.test(res.json.wake.reason), 'default caller without origin: explicit not-attempted receipt')
  n(2)
}

// ⑦ wake caller throwing: caught, answer untouched, failure receipt.
{
  const id = seed(null, 'Sign t-7?')
  const { a } = apiWith(async () => { throw new Error('boom') })
  const res = await answer(a, { project: PROJ, id, answer: 'yes' })
  assert(res.status === 200 && res.json.wake.attempted === false && /boom/.test(res.json.wake.reason), 'throwing caller → failure receipt naming the error')
  n(1)
}
cleanup([wd, pan])
done(count)
