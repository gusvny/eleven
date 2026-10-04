/**
 * sc_alert_clear_wake.mjs — t261004-29, cleared-alert wake journey (grey-box L3,
 * offline fault injection on the public Watchdog face, zero docker).
 *
 * Intent (user-perceivable; ticket requirement "a cleared alert is a wake-worthy
 * event ... one wake per fire episode" per the reviewed plan): when a redline
 * alert the watchdog raised stops holding, the executor gets one wake — and
 * exactly one per fire episode, stable across the fire→clear→re-fire cycle and
 * across restarts. Concretely:
 *   C1 precondition (existing behavior): a stalled executor raises the stall
 *      redline alert (status().alerts names rule=stall, level=redline);
 *   C2 when the alert condition clears (the session advances again), exactly one
 *      NEW wake delivery happens, in queue mode (an alert clear is information,
 *      not a redline interrupt — steer stays redline-only);
 *   C3 a following unchanged tick wakes nobody again (same episode, no re-wake);
 *   C4 re-fire then clear again → exactly one more wake (a NEW episode is
 *      wake-worthy again);
 *   C5 a fresh process starting on an already-clear state wakes nobody
 *      (startup state is not a previous-tick set — no phantom clear).
 *
 * Seam: public `Watchdog` constructor deps (configLoader / io / boardReader /
 * sessionStat / wakeIo / now / dataDir / ledgerDir — the same injected-deps
 * shape the plugin composes in node.ts) + public `status()` / `tickOnce()`.
 * Wake delivery is observed through the injected wakeIo prompt stub — the
 * user-perceivable "the executor was prodded" fact, not internal flags.
 * TDD-phase red on C2/C4 is expected; arbitrate/merge must be green.
 *
 * Intent split: the wake decision internals (①/②/③ guard truth tables) are
 * developer L1 (exits UTs); the self-feed guard on the NEW sources is judged in
 * sc_wake_self_feed_guard.mjs; the stall-detection mechanics themselves belong
 * to t261001-19's battery — this file only uses them as a raise/clear crank.
 *
 * Run directly: node integration/t261004-29/sc_alert_clear_wake.mjs (cwd = repo root).
 */
import { Watchdog } from '../../server/plugins/watchdog/src/host/core.ts'
import { memTailIo, memCoreIo, ledgerLine, fakeClock } from '../../server/plugins/watchdog/tests/lib.mjs'
import { makeResults } from './lib_wake_fixture.mjs'

const r = makeResults()
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = () => ({
  ...CFG,
  config: {
    enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
    alerts: {
      enabled: true, sound: true, desktop: true,
      night: { start: '23:00', end: '07:30', policy: 'redline-only' },
      redline: ['stall', 'executor_missing'], keep_days: 14,
    },
  },
})

/** Build a Watchdog on in-memory io with a flip-able session-advance signal.
 *  `advanceState.advanced` is read fresh every tick (the stub closes over it). */
function makeWatchdog(clock) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLine({ seq: 1, ticket: 't1' }) + '\n' } }
  const core = memCoreIo()
  const advanceState = { advanced: false }
  const prompts = []
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [{ id: 't1', stage_state: 'running' }] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: advanceState.advanced, mtimeMs: clock.now(), running: false }),
    wakeIo: {
      async prompt(sessionId, text, mode) { prompts.push({ sessionId, mode, text: String(text).slice(0, 80) }); return { accepted: true, requestId: `q-${prompts.length}` } },
      async queueDepth() { return 0 },
      async ourBriefPending() { return false },
    },
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, prompts, advanceState }
}

/** The alert-condition crank: false = stalled (rule fires), true = advancing
 *  (rule does not fire = the clear condition). */
function setAdvancing(h, v) { h.advanceState.advanced = v }

try {
  // C1 raise: 15+ min silence with a live-but-quiet session → stall redline.
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock)
    await h.w.start()
    clock.advance(16 * 60_000)
    await h.w.tickOnce()
    const stall = h.w.status().alerts.find(a => a.rule === 'stall')
    r.check(!!stall && stall.level === 'redline', 'C1-stall-redline-raised', `alerts=${JSON.stringify(h.w.status().alerts.map(a => a.rule)).slice(0, 160)}`)
    h.w.dispose()
  }

  // C2/C3 fire → clear → one queue-mode wake; unchanged tick wakes nobody.
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock)
    await h.w.start()
    clock.advance(16 * 60_000)
    await h.w.tickOnce()
    const promptsAfterRaise = h.prompts.length
    setAdvancing(h, true)
    await h.w.tickOnce()
    const cleared = h.prompts.length - promptsAfterRaise
    r.check(cleared === 1, 'C2-clear-wakes-exactly-once', `newPrompts=${cleared} total=${h.prompts.length} (TDD red expected until implement lands)`)
    r.check(h.prompts.length > 0 && h.prompts[h.prompts.length - 1].mode === 'queue',
      'C2-clear-wake-is-queue-mode', `mode=${h.prompts.length ? h.prompts[h.prompts.length - 1].mode : 'none'} (steer stays redline-only)`)
    await h.w.tickOnce()
    r.check(h.prompts.length === promptsAfterRaise + 1, 'C3-unchanged-tick-no-rewake', `prompts=${h.prompts.length}`)
    h.w.dispose()
  }

  // C4 re-fire → clear again → one more wake (new episode).
  {
    const clock = fakeClock()
    const h = makeWatchdog(clock)
    await h.w.start()
    clock.advance(16 * 60_000)
    await h.w.tickOnce() // fire episode 1
    const base = h.prompts.length
    setAdvancing(h, true)
    await h.w.tickOnce() // clear 1 → wake
    const afterClear1 = h.prompts.length
    r.check(afterClear1 === base + 1, 'C4-episode1-clear-wakes', `prompts=${h.prompts.length} base=${base}`)
    setAdvancing(h, false)
    clock.advance(16 * 60_000)
    await h.w.tickOnce() // fire episode 2
    setAdvancing(h, true)
    await h.w.tickOnce() // clear 2 → wake again
    r.check(h.prompts.length === afterClear1 + 1, 'C4-refired-clear-wakes-again', `prompts=${h.prompts.length} afterClear1=${afterClear1} (TDD red expected)`)
    h.w.dispose()
  }

  // C5 restart on already-clear state → no phantom clear wake.
  {
    const clock = fakeClock()
    const h1 = makeWatchdog(clock)
    await h1.w.start()
    clock.advance(16 * 60_000)
    await h1.w.tickOnce() // fire
    setAdvancing(h1, true)
    await h1.w.tickOnce() // clear
    h1.w.dispose()
    const h2 = makeWatchdog(clock) // fresh process, state already clear
    await h2.w.start()
    await h2.w.tickOnce()
    const clearWakes = h2.prompts.length
    r.check(clearWakes === 0, 'C5-restart-no-phantom-clear-wake', `promptsOnFreshProcess=${clearWakes}`)
    h2.w.dispose()
  }
} finally {
  /* in-memory fixtures — nothing to reclaim (L8) */
}
r.summarize()
