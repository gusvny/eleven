/**
 * sc_wake_on_answer.mjs — t261004-29, wake-on-answer user journey (grey-box L3,
 * offline, zero docker, never touches 3099/7233).
 *
 * Intent (user-perceivable; ticket requirement "an answered request is a
 * wake-worthy event ... Deliver a receipt that says whether a wake was attempted
 * and why"): when the host answers an executor request on the panel, the answer
 * response must carry a wake outcome, and the answer must never be lost or
 * degraded by the wake step. Concretely:
 *   A1 a successful answer calls the wake face exactly once with the answered
 *      request's identity, and the response carries wake.attempted=true;
 *   A2 a rejected second answer of the same request triggers NO wake call
 *      (the ledger already refused the rewrite; waking on a refused answer
 *      would be a phantom);
 *   A3 a wake-face transport failure leaves the answer 200 and persisted, and
 *      the response reports wake.attempted=false with a non-empty named reason
 *      (never silence, never a fabricated "woke");
 *   A4 a wake-face response that is not the receipt shape is normalized to an
 *      explicit failure receipt (external input is never trusted blindly);
 *   A5 malformed answer inputs (non-JSON body, non-string id, malformed project
 *      key) are rejected with a named 4xx and never reach the wake face.
 *
 * Seam: panel `createApi(env, deps)` public factory with an injected wakeCaller
 * stub and a temp-dir request ledger. Missing wakeCaller support = the new
 * behavior is not implemented yet = FAIL (TDD-phase red is expected; the
 * arbitrate/merge phase must be green).
 *
 * Intent split: the watchdog-side receipt/route/guard/alert-clear behavior is
 * judged by the other t261004-29 scenarios; existing panel list/render/order
 * contracts belong to t261004-14/t261004-16 — not repeated here.
 *
 * Run directly: node integration/t261004-29/sc_wake_on_answer.mjs (cwd = repo root).
 */
import { appendRequest, fsLedgerIo } from '../../server/plugins/executor-panel/src/host/requests.ts'
import { createApi } from '../../server/plugins/executor-panel/src/host/api.ts'
import { createHash } from 'node:crypto'
import { makeResults, freshDir, reclaimDir } from './lib_wake_fixture.mjs'

const r = makeResults()
const PROJ = 'alpha'
const HOME = freshDir('sc-t261004-29-answer-')
const env = { ...process.env, SANDBAR_PANEL_DIR: HOME }

try {
  const api = createApi(env, {})

  /** Seed one waiting request (public ledger io); each sub-case gets a fresh row
   *  so answer-once semantics never leak across blocks. */
  let seq = 0
  async function seed(question) {
    seq += 1
    const seeded = appendRequest(fsLedgerIo, env, PROJ,
      { kind: 'question', question, raised_by: 'executor-x' }, 1_700_000_000_000 + seq)
    if (!seeded.ok) { r.record('seed-request', 'fail', `fixture appendRequest refused: ${seeded.error}`); r.summarize() }
    return seeded.row.id
  }
  const reqId = await seed('May I sign ticket t-9?')

  /** Fresh API with a wakeCaller stub recording calls. */
  function apiWith(wakeImpl) {
    const calls = []
    const a = createApi(env, { wakeCaller: async (args) => { calls.push(args); return wakeImpl(args) } })
    return { a, calls }
  }
  // gen1 fixture fix (integration-owned): since KI-193 landed (t261004-18/-34),
  // every panel WRITE requires the console session credential — the same-shaped
  // cookie the console browser carries, keyed to the Host. The journey presents
  // credentialed requests (pattern shared with t260929-03/t261004-18; the
  // uncredentialed-write-refusal face itself is t261004-18's dedicated scenario,
  // not repeated here — intent-level no duplication).
  const HOST = 'console.test'
  const cred = () => ({
    host: HOST,
    cookie: 'dsh-auth-' + createHash('sha256').update(HOST).digest('base64url') + '=v1.AAAA.BBBB',
  })
  async function answer(a, body) {
    return a.handle('POST', '/sandbar-executor-panel/api/requests/answer', new URLSearchParams(), JSON.stringify(body), 'http://console.test', cred())
  }

  // A1 happy path: answer → one wake call with the right identity → receipt merged.
  {
    const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'delivered to executor-x' } }))
    const res = await answer(a, { project: PROJ, id: reqId, answer: 'yes, sign it', by: 'host' })
    const okAnswer = res.status === 200 && res.json && res.json.ok === true
    const wake = okAnswer ? res.json.wake : undefined
    r.check(okAnswer, 'A1-answer-200', `status=${res.status} json=${JSON.stringify(res.json).slice(0, 160)}`)
    r.check(!!wake && wake.attempted === true && wake.woke === true && typeof wake.reason === 'string' && wake.reason.length > 0,
      'A1-receipt-attempted-woke-reason', `wake=${JSON.stringify(wake)}`)
    r.check(calls.length === 1 && String(calls[0].requestId ?? calls[0].request_id ?? '') === reqId,
      'A1-wake-called-once-with-request-id', `calls=${JSON.stringify(calls).slice(0, 200)}`)
  }

  // A2 second answer of the same request: refused, and NO wake call.
  {
    const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'x' } }))
    const res = await answer(a, { project: PROJ, id: reqId, answer: 'changed my mind', by: 'host' })
    r.check(res.status === 409 && res.json && res.json.ok === false && typeof res.json.error === 'string' && res.json.error.length > 0,
      'A2-second-answer-refused-named', `status=${res.status} json=${JSON.stringify(res.json).slice(0, 160)}`)
    r.check(calls.length === 0, 'A2-refused-answer-does-not-wake', `wakeCalls=${calls.length}`)
  }

  // A3 wake transport failure: answer still 200 + persisted; wake.attempted=false named.
  {
    const { a } = apiWith(async () => ({ ok: false, reason: 'transport error: connect ECONNREFUSED watchdog route' }))
    const res = await answer(a, { project: PROJ, id: await seed('Sign t-10?'), answer: 'still yes', by: 'host' })
    const wake = res.json ? res.json.wake : undefined
    r.check(res.status === 200 && res.json && res.json.ok === true,
      'A3-answer-survives-wake-failure', `status=${res.status} json=${JSON.stringify(res.json).slice(0, 160)}`)
    r.check(!!wake && wake.attempted === false && typeof wake.reason === 'string' && wake.reason.length > 0 && wake.woke !== true,
      'A3-wake-failure-explicit', `wake=${JSON.stringify(wake)}`)
    // persisted: a fresh read view shows the request answered.
    const list = await api.handle('GET', '/sandbar-executor-panel/api/requests', new URLSearchParams(`project=${PROJ}`), '', '')
    const row = list.json && Array.isArray(list.json.rows) ? list.json.rows.find(x => x.id === reqId) : null
    r.check(!!row && row.status === 'answered', 'A3-answer-persisted', `row=${JSON.stringify(row).slice(0, 160)}`)
  }

  // A4 non-receipt-shaped wake response is normalized, never trusted blindly.
  {
    const { a } = apiWith(async () => ({ ok: true, receipt: { woke: 'yes', tried: 1 } }))
    const res = await answer(a, { project: PROJ, id: await seed('Sign t-11?'), answer: 'yes again', by: 'host' })
    const wake = res.json ? res.json.wake : undefined
    r.check(res.status === 200 && !!wake && typeof wake.attempted === 'boolean' && typeof wake.reason === 'string' && wake.reason.length > 0 && wake.woke !== 'yes',
      'A4-garbage-receipt-normalized', `status=${res.status} wake=${JSON.stringify(wake)}`)
  }

  // A5 malformed inputs: named 4xx, wake face never reached.
  {
    const { a, calls } = apiWith(async () => ({ ok: true, receipt: { attempted: true, woke: true, reason: 'x' } }))
    const badJson = await a.handle('POST', '/sandbar-executor-panel/api/requests/answer', new URLSearchParams(), '{not json', 'http://console.test', cred())
    r.check(badJson.status === 400 && typeof (badJson.json && badJson.json.error) === 'string' && badJson.json.error.length > 0,
      'A5-non-json-body-400-named', `status=${badJson.status} json=${JSON.stringify(badJson.json).slice(0, 120)}`)
    const badId = await answer(a, { project: PROJ, id: 42, answer: 'x', by: 'host' })
    r.check(badId.status === 400 && typeof (badId.json && badId.json.error) === 'string',
      'A5-non-string-id-400', `status=${badId.status} json=${JSON.stringify(badId.json).slice(0, 120)}`)
    const badProj = await answer(a, { project: '../escape', id: reqId, answer: 'x', by: 'host' })
    r.check(badProj.status === 400, 'A5-malformed-project-400', `status=${badProj.status}`)
    r.check(calls.length === 0, 'A5-malformed-inputs-never-wake', `wakeCalls=${calls.length}`)
  }
} finally {
  reclaimDir(HOME)
}
r.summarize()
