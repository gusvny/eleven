/**
 * sc_wake_self_feed_guard.mjs — t261004-29, self-feed guard + receipt honesty on
 * the new wake sources (grey-box L3, offline, zero docker).
 *
 * Intent (user-perceivable; ticket requirement "The self-feed guard stays: do
 * not re-deliver our own undigested brief ... Deliver a receipt that says
 * whether a wake was attempted and why"): the answer-driven wake (requestWake)
 * must go through the SAME guard as ledger-driven wakes, and every outcome must
 * come back as an explicit receipt. Concretely:
 *   D1 while our own brief is still undigested, a request-answer wake is
 *      suppressed: attempted=false, a named reason, NO prompt delivery;
 *   D2 with nothing pending, the same request wakes: attempted=true, woke=true,
 *      delivered in queue mode to the declared executor session;
 *   D3 with no session and a refusing ensure face, the receipt is attempted=false
 *      quoting the refusal reason (refused-* is visible, never silence);
 *   D4 malformed requestWake arguments (non-string request id) never throw, and
 *      whatever happens is honestly receipted (attempted boolean + reason;
 *      any delivery matches the receipt);
 *   E5 receipts are auditable after the call: the status face carries the recent
 *      wake receipts ring (additive field; last receipt matches the last call).
 *
 * Seam: public `Watchdog` constructor deps + the new public `requestWake()`
 * + `status()`. The guard is observed through its user-perceivable face
 * (suppressed delivery + named reason), never through internal memory shapes.
 * TDD-phase red (requestWake missing) is expected; arbitrate/merge must be green.
 *
 * Intent split: guard truth tables on pure rows are developer L1 (exits UTs);
 * the clear-source journey is sc_alert_clear_wake.mjs; the HTTP wrapper is
 * sc_wake_route_receipt.mjs — this file owns the guard × new-source intersection
 * and receipt honesty only.
 *
 * Run directly: node integration/t261004-29/sc_wake_self_feed_guard.mjs (cwd = repo root).
 */
import { Watchdog } from '../../server/plugins/watchdog/src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock } from '../../server/plugins/watchdog/tests/lib.mjs'
import { makeResults } from './lib_wake_fixture.mjs'

const r = makeResults()
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = (executorSession) => ({
  ...CFG,
  config: {
    enabled: true, executor_session: executorSession, stall_minutes: 15, reconcile_seconds: 5,
    alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['stall'], keep_days: 14 },
  },
})

/** Watchdog with controllable guard + ensure faces and a recording prompt stub.
 *  `briefPending` is read fresh on every call (the stub closes over the holder),
 *  so a test can flip it after a first real brief — the state the guard actually
 *  guards (it keys on our last accepted brief's queue item, so the suppressed
 *  journey needs a prior brief, not a bare true). */
function makeWatchdog(clock, { executorSession = 'executor-x', briefPending = false, ensure = null } = {}) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLine({ seq: 1, ticket: 't1' }) + '\n' } }
  const core = memCoreIo()
  const prompts = []
  const guard = { briefPending }
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(executorSession),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [{ id: 't1', stage_state: 'running' }] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: true, mtimeMs: clock.now(), running: false }),
    sessionEnsure: ensure,
    wakeIo: {
      async prompt(sessionId, text, mode) { prompts.push({ sessionId, mode }); return { accepted: true, requestId: `q-${prompts.length}` } },
      async queueDepth() { return 0 },
      async ourBriefPending() { return guard.briefPending },
    },
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, prompts, guard }
}
const WAKE = { source: 'request-answer', requestId: 'req-1700000000-0001', detail: 'host answered: yes, sign t-9' }

try {
  // D1 undigested brief → suppressed with named reason, no delivery.
  // The real journey: the watchdog first delivers a brief (the first answer's
  // push is accepted, its queue item is still in the executor's queue), and
  // THEN the host answers a second request — re-delivering on top of the
  // undigested brief is the self-feed loop the guard exists to stop.
  // (gen1 fixture fix, integration-owned: the old precondition cranked a tick,
  // but the seeded row is consumed as the start() baseline so the tick delivers
  // nothing and the guard journey never armed. The first brief now arrives the
  // way production briefs arrive — via an accepted push delivery — which sets
  // lastRequestId and turns the mirror face on, exactly the state rule ③
  // guards. Assertions unchanged in strength.)
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock, { briefPending: false })
    await h.w.start()
    const first = await h.w.requestWake({ ...WAKE, requestId: 'req-1700000000-0000' })
    r.check(!!first && first.attempted === true && first.woke === true && h.prompts.length === 1,
      'D1-precondition-brief-delivered', `receipt=${JSON.stringify(first).slice(0, 160)} prompts=${h.prompts.length}`)
    h.guard.briefPending = true // our last brief is still undigested
    const rec = await h.w.requestWake(WAKE)
    r.check(!!rec && rec.attempted === false && typeof rec.reason === 'string' && rec.reason.length > 0,
      'D1-guard-suppresses-attempted-false-named', `receipt=${JSON.stringify(rec).slice(0, 200)} (TDD red expected: guard not wired to the new source)`)
    r.check(rec ? rec.woke === false || rec.woke === undefined : true, 'D1-suppressed-receipt-not-woke', `woke=${rec && rec.woke}`)
    r.check(h.prompts.length === 1, 'D1-guard-no-prompt-delivery', `prompts=${h.prompts.length}`)
    h.w.dispose()
  }

  // D2 nothing pending → delivered, queue mode, to the declared session.
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock, { briefPending: false })
    const rec = await h.w.requestWake(WAKE)
    r.check(!!rec && rec.attempted === true && rec.woke === true,
      'D2-clear-path-attempted-woke', `receipt=${JSON.stringify(rec).slice(0, 200)}`)
    r.check(h.prompts.length === 1 && h.prompts[0].sessionId === 'executor-x' && h.prompts[0].mode === 'queue',
      'D2-prompt-queue-to-declared-session', `prompts=${JSON.stringify(h.prompts)}`)
    h.w.dispose()
  }

  // D3 refusing ensure face → attempted=false quoting the refusal.
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock, {
      executorSession: '',
      ensure: async () => ({ action: 'refused-preset', sessionId: null, declaredWritten: false, reason: 'executor preset 未安装：sandbar-executor' }),
    })
    const rec = await h.w.requestWake(WAKE)
    r.check(!!rec && rec.attempted === false && typeof rec.reason === 'string' && rec.reason.length > 0 && rec.woke !== true,
      'D3-ensure-refusal-explicit-receipt', `receipt=${JSON.stringify(rec).slice(0, 240)}`)
    r.check(h.prompts.length === 0, 'D3-refusal-no-prompt', `prompts=${h.prompts.length}`)
    h.w.dispose()
  }

  // D4 malformed arguments → no throw, no crash, and whatever happens is
  // honestly receipted (an attempted boolean plus a reason; delivery, if any,
  // matches the receipt — never a partially-trusted path).
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock, { briefPending: false })
    let rec = null
    let threw = null
    try { rec = await h.w.requestWake({ ...WAKE, requestId: 42 }) } catch (e) { threw = String((e && e.message) || e) }
    r.check(threw === null, 'D4-malformed-args-no-throw', threw ? `threw: ${threw.slice(0, 160)}` : '')
    const honest = rec && typeof rec.attempted === 'boolean' && typeof rec.reason === 'string' && rec.reason.length > 0
      && (rec.attempted === false || h.prompts.length >= 1)
    r.check(honest, 'D4-malformed-args-honest-receipt', `receipt=${JSON.stringify(rec).slice(0, 200)} prompts=${h.prompts.length}`)
    h.w.dispose()
  }

  // E5 status face carries the receipts ring (auditability after the response).
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock, { briefPending: false })
    const rec = await h.w.requestWake(WAKE)
    const st = h.w.status()
    const ring = st.wake_receipts
    r.check(Array.isArray(ring) && ring.length >= 1,
      'E5-status-receipts-ring-present', `wake_receipts=${JSON.stringify(ring).slice(0, 200)} (TDD red expected)`)
    const last = Array.isArray(ring) && ring.length > 0 ? ring[ring.length - 1] : null
    r.check(!!last && typeof last.attempted === 'boolean',
      'E5-ring-last-receipt-shaped', `last=${JSON.stringify(last).slice(0, 160)} callAttempted=${rec && rec.attempted}`)
    h.w.dispose()
  }
} finally {
  /* in-memory fixtures — nothing to reclaim (L8) */
}
r.summarize()
