// t261005-02 UT: the self-heal (bounded un-park) face. Pins, from public faces:
//   1. config: self_heal family parses, provenance names the knobs, malformed values
//      fail closed, and park_minutes <= long_turn_minutes is rejected (cross-knob guard).
//   2. decision core (pure decideSelfHeal): fires only when all three guards hold;
//      each guard alone holds it off with a named reason; one attempt per park;
//      a new ask id re-arms exactly one fresh attempt.
//   3. L2 stub-io end-to-end through Watchdog: parked ask + silence + pending brief
//      → exactly one cancelTurn + one briefing + status.self_heal.state='fired' +
//      one self_heal_cancel alert row; the next tick holds (no cancel loop).
// Incident-regression tier note: KI-196/197's own faces (question bridge, delivery
// transport) are open debt owned by their tickets — L1/L2 stub-io coverage here is
// the regression for the watchdog-side judgement and receipt, not for those faces.
import { Watchdog } from '../src/host/core.ts'
import { decideSelfHeal, selfHealParkKey, proseMarkerId } from '../src/host/self-heal.ts'
import { parseWatchdogConfig, FACTORY_DEFAULTS } from '../src/host/config.ts'
import { memTailIo, memCoreIo, fakeClock, assert, done } from './lib.mjs'

const NOW = 1_700_000_000_000
const M = 60_000
let n = 0

// ---- 1. config family ----
{
  const ok = parseWatchdogConfig(JSON.stringify({ enabled: true, self_heal: { enabled: false, park_minutes: 90 } }), 'mem.json')
  assert(ok.config_error === null, 'config: valid self_heal parses clean')
  assert(ok.config.self_heal.enabled === false && ok.config.self_heal.park_minutes === 90, 'config: self_heal values pass through')
  assert(ok.provenance.keys['self_heal.enabled'] === 'mem.json#self_heal.enabled', 'config: enabled knob named in provenance (receipt requirement)')
  assert(ok.provenance.keys['self_heal.park_minutes'] === 'mem.json#self_heal.park_minutes', 'config: park knob named in provenance')
  n += 4
}
{
  const dflt = parseWatchdogConfig(JSON.stringify({ enabled: true }), 'mem.json')
  assert(dflt.config.self_heal.enabled === true && dflt.config.self_heal.park_minutes === FACTORY_DEFAULTS.self_heal.park_minutes, 'config: missing self_heal falls to factory (60 > long_turn 45)')
  n += 1
}
{
  for (const bad of [
    { self_heal: 'yes' },
    { self_heal: { enabled: 'true' } },
    { self_heal: { park_minutes: 0 } },
    { self_heal: { park_minutes: -5 } },
    { self_heal: { park_minutes: Number.NaN } },
    { self_heal: { park_minutes: true } },
  ]) {
    const r = parseWatchdogConfig(JSON.stringify(bad), 'mem.json')
    assert(r.config_error !== null && r.enabled === false, `config: malformed ${JSON.stringify(bad)} fails closed`)
    assert(r.config_error.includes('self_heal'), 'config: the knob is named in the error')
  }
  n += 2
}
{
  // Guard compares against a DECLARED long_turn_minutes (the factory default is not a
  // declaration — small park thresholds stay valid without one).
  const noLt = parseWatchdogConfig(JSON.stringify({ self_heal: { park_minutes: 30 } }), 'mem.json')
  assert(noLt.config_error === null, 'config: park without a declared long_turn is valid (factory default is not a declaration)')
  const r = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 60, self_heal: { park_minutes: 30 } }), 'mem.json')
  assert(r.config_error !== null && r.config_error.includes('park_minutes') && r.config_error.includes('long_turn_minutes'), 'config: park_minutes <= declared long_turn_minutes rejected with both knobs named')
  const edge = parseWatchdogConfig(JSON.stringify({ long_turn_minutes: 30, self_heal: { park_minutes: 30 } }), 'mem.json')
  assert(edge.config_error !== null, 'config: park_minutes == declared long_turn_minutes also rejected')
  n += 3
}

// ---- 2. pure decision core ----
function input(over = {}) {
  return {
    sessionId: 'ex',
    asks: [{ requestId: 'ask-1', raisedAt: NOW - 10 * M, hasDefault: false }],
    questionMarker: null,
    silenceMs: 70 * M,
    ourBriefPending: true,
    cfg: { enabled: true, parkMinutes: 60 },
    attempts: new Map(),
    nowMs: NOW,
    ...over,
  }
}
{
  const v = decideSelfHeal(input())
  assert(v.action === 'cancel' && v.receipt !== null, 'core: all three guards hold → cancel')
  assert(v.receipt.ask_id === 'ask-1' && v.receipt.session_id === 'ex' && v.receipt.threshold_minutes === 60 && v.receipt.silence_minutes === 70, 'core: receipt names session, ask, threshold, silence')
  assert(v.receipt.attempt === 1 && v.receipt.ask_has_default === false, 'core: receipt names attempt count and the default bit')
  n += 2
}
{
  const holds = [
    ['face off', input({ cfg: { enabled: false, parkMinutes: 60 } })],
    ['no session id', input({ sessionId: '' })],
    ['no ask (healthy long turn)', input({ asks: [] })],
    ['mirror unreadable', input({ ourBriefPending: null })],
    ['brief consumed', input({ ourBriefPending: false })],
    ['silence under threshold', input({ silenceMs: 59 * M })],
    ['silence unreadable', input({ silenceMs: null })],
    ['already attempted', input({ attempts: new Map([[selfHealParkKey('ex', 'ask-1'), 1]]) })],
  ]
  for (const [name, i] of holds) {
    const v = decideSelfHeal(i)
    assert(v.action === 'hold' && v.receipt === null && typeof v.reason === 'string' && v.reason !== '', `core: ${name} → hold with a named reason`)
  }
  n += 1
}
{
  // one attempt per park, new ask re-arms exactly once
  const v2 = decideSelfHeal(input({ attempts: new Map([[selfHealParkKey('ex', 'ask-1'), 1]]) }))
  assert(v2.action === 'hold' && v2.reason.includes('already fired'), 'core: same park never fires twice')
  const v3 = decideSelfHeal(input({ asks: [{ requestId: 'ask-2', raisedAt: NOW, hasDefault: null }] }))
  assert(v3.action === 'cancel' && v3.receipt.ask_id === 'ask-2' && v3.receipt.attempt === 1, 'core: a new ask id re-arms exactly one fresh attempt')
  n += 2
}
{
  // prose marker without a ledger row: deterministic marker id, fires as its own park
  const v = decideSelfHeal(input({ asks: [], questionMarker: { requestId: null, sentence: 'still waiting for the host' } }))
  assert(v.action === 'cancel' && v.receipt.ask_source === 'prose-marker' && v.receipt.ask_id === proseMarkerId('still waiting for the host'), 'core: a pending question marker fires with a deterministic id')
  // malformed marker shapes must not crash nor fire
  const bad = decideSelfHeal(input({ asks: [{ requestId: '', raisedAt: NOW, hasDefault: null }], questionMarker: null }))
  assert(bad.action === 'hold', 'core: empty ask id with no marker = hold (never fire on a blank target)')
  n += 2
}

// ---- 3. L2 stub-io end-to-end through Watchdog ----
function makeWatchdog({ clock, pending, ourBriefPending, cancelTurn, files }) {
  const core = memCoreIo()
  const calls = { cancel: 0, cancelSid: null, prompts: [], cancelResults: {} }
  const w = new Watchdog('sandbar', {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} },
      config: {
        enabled: true, executor_session: 'ex', stall_minutes: 15, long_turn_minutes: 1, reconcile_seconds: 5,
        waiting_minutes: 5,
        self_heal: { enabled: true, park_minutes: 2 },
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline: ['stall'], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: pending() }),
    waitingRunningLookup: () => true,
    wakeIo: {
      prompt: async (sid, text) => { calls.prompts.push({ sid, text }); return { accepted: true, requestId: `brief-${calls.prompts.length}` } },
      queueDepth: async () => 0,
      ourBriefPending: async () => ourBriefPending(),
      cancelTurn: async (sid) => { calls.cancel += 1; calls.cancelSid = sid; return cancelTurn() },
    },
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: true }),
    sessionEnsure: async ({ declaredSessionId }) => ({ action: 'adopt', sessionId: declaredSessionId, declaredWritten: false, reason: 'adopt', event: null }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  return { w, calls }
}
const askRows = (id) => [{ raisedBy: 'ex', kind: 'question', target: id, sessionRunning: true, raisedAt: NOW, hasDefault: false }]

// 3a. fire path: a wake first (a brief is then pending), then a park past the threshold.
{
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  let asks = []
  let briefPending = false
  let seq = 0
  const { w, calls } = makeWatchdog({ clock, pending: () => asks, ourBriefPending: () => briefPending, cancelTurn: async () => ({ accepted: true }), files })
  await w.start() // tick 1: empty ledger, baseline set
  assert(w.status().self_heal.state === 'idle' && w.status().self_heal.config.park_minutes === 2, 'status: self_heal face present with the declared knobs before any park')
  // one ledger row → the wake exit delivers a brief (requestId recorded, progress baseline moves)
  seq += 1
  files['/ledg/sandbar.jsonl'].content += JSON.stringify({ schema: 'event-ledger-v1', idem: `i${seq}`, project: 'sandbar', ticket: 't1', seq, kind: 'stage-transition', stage: 'implement', stage_state: 'running', at: clock.now() }) + '\n'
  clock.advance(1 * M)
  await w.tickOnce()
  assert(calls.prompts.length === 1, 'setup: the wake delivered exactly one brief')
  assert(w.status().self_heal.state === 'idle' && calls.cancel === 0, 'pre-park: brief pending but no ask yet → hold, no cancel')
  // park: an unanswered ask attributed to the session, silence past park_minutes(2)
  clock.advance(3 * M)
  asks = askRows('ask-1')
  briefPending = true
  await w.tickOnce()
  const face = w.status().self_heal
  assert(calls.cancel === 1 && calls.cancelSid === 'ex', 'fire: exactly one cancel, for the declared session')
  assert(face.state === 'fired', 'fire: status face state=fired')
  assert(face.last_cancel !== null && face.last_cancel.ask_id === 'ask-1' && face.last_cancel.cancel_accepted === true && face.last_cancel.attempt === 1 && face.last_cancel.threshold_minutes === 2, 'fire: the receipt names ask, cancel acceptance, attempt, threshold')
  assert(calls.prompts.length === 2 && calls.prompts[1].text.includes('ask-1') && calls.prompts[1].text.includes('2min'), 'fire: the briefing names the ask and the threshold')
  assert(w.status().alerts.some(a => a.rule === 'self_heal_cancel'), 'fire: a self_heal_cancel alert row is on the read face')
  // next tick, unchanged: hold — one attempt per park, no cancel loop; the receipt
  // stays visible on the face (the state reflects the latest judgement, the receipt persists)
  await w.tickOnce()
  assert(calls.cancel === 1, 'bounded: the second tick does not cancel again')
  assert(w.status().self_heal.last_cancel !== null && w.status().self_heal.last_cancel.ask_id === 'ask-1', 'bounded: the receipt persists (a human still sees it happened)')
  assert(/hold|silence|already fired/.test(w.status().self_heal.reason), 'bounded: the latest judgement keeps an explicit reason')
  // a NEW ask id re-arms exactly one fresh attempt
  clock.advance(3 * M)
  asks = askRows('ask-2')
  await w.tickOnce()
  assert(calls.cancel === 2 && w.status().self_heal.last_cancel.ask_id === 'ask-2', 're-arm: the new ask fires exactly once more')
  w.dispose()
  n += 9
}
// 3b. a healthy long turn (no ask) never cancels, even past the threshold with a pending brief.
{
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const { w, calls } = makeWatchdog({ clock, pending: () => [], ourBriefPending: () => true, cancelTurn: async () => ({ accepted: true }), files })
  await w.start()
  clock.advance(120 * M)
  await w.tickOnce()
  assert(calls.cancel === 0, 'healthy long turn: no ask → no cancel')
  assert(w.status().self_heal.state === 'idle' && w.status().self_heal.reason.includes('guard (a)'), 'healthy long turn: hold reason names guard (a)')
  w.dispose()
  n += 2
}
// 3c. mirror unreadable (ourBriefPending=null) → hold, never cancel on a no-signal read.
{
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const { w, calls } = makeWatchdog({ clock, pending: () => askRows('ask-1'), ourBriefPending: () => null, cancelTurn: async () => ({ accepted: true }), files })
  await w.start()
  clock.advance(120 * M)
  await w.tickOnce()
  assert(calls.cancel === 0 && w.status().self_heal.reason.includes('mirror unreadable'), 'mirror unreadable → hold, named')
  w.dispose()
  n += 1
}
// 3d. cancel face absent → unsupported; cancel refused → failed; both named, still bounded.
// (A wake is seeded first: guard (c) needs a delivered brief to judge "still unconsumed".)
{
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  let result = { accepted: null }
  let asks = askRows('ask-1')
  let seq = 0
  const { w, calls } = makeWatchdog({ clock, pending: () => asks, ourBriefPending: () => true, cancelTurn: async () => result, files })
  await w.start()
  seq += 1
  files['/ledg/sandbar.jsonl'].content += JSON.stringify({ schema: 'event-ledger-v1', idem: `i${seq}`, project: 'sandbar', ticket: 't1', seq, kind: 'stage-transition', stage: 'implement', stage_state: 'running', at: clock.now() }) + '\n'
  clock.advance(1 * M)
  await w.tickOnce() // wake fires → lastRequestId set
  clock.advance(5 * M)
  await w.tickOnce()
  assert(w.status().self_heal.state === 'unsupported' && w.status().self_heal.last_cancel.cancel_accepted === false, 'cancel accepted=null → unsupported, receipt kept')
  assert(calls.cancel === 1, 'unsupported: exactly one attempt was made (no retry loop)')
  result = { accepted: false, error: 'no live agent' }
  asks = askRows('ask-2') // a new park (the ask-1 park already consumed its one attempt)
  clock.advance(5 * M)
  await w.tickOnce()
  assert(w.status().self_heal.state === 'failed' && w.status().self_heal.last_cancel.cancel_error === 'no live agent', 'cancel refused → failed with the named error')
  assert(calls.cancel === 2, 'failed: the new park fired exactly once (no retry loop)')
  w.dispose()
  n += 3
}
// 3e. self_heal.enabled=false → the face is off, no cancel, no unsupported alert noise.
{
  const clock = fakeClock(NOW)
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const { w, calls } = makeWatchdog({ clock, pending: () => askRows('ask-1'), ourBriefPending: () => true, cancelTurn: async () => ({ accepted: true }), files })
  // flip the knob off via the same loader seam
  const cfg = w
  void cfg
  // simplest: separate watchdog with disabled config
  w.dispose()
  const core2 = memCoreIo()
  const w2 = new Watchdog('sandbar', {
    configLoader: () => ({
      declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} },
      config: {
        enabled: true, executor_session: 'ex', stall_minutes: 15, long_turn_minutes: 1, reconcile_seconds: 5,
        waiting_minutes: 5, self_heal: { enabled: false, park_minutes: 2 },
        alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'normal' }, redline: [], keep_days: 14 },
      },
    }),
    io: { tail: memTailIo(files), heartbeat: core2.heartbeat, appendAlerts: core2.appendAlerts, listAlerts: core2.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: askRows('ask-1') }),
    waitingRunningLookup: () => true,
    wakeIo: {
      prompt: async () => ({ accepted: true, requestId: 'b' }),
      queueDepth: async () => 0,
      ourBriefPending: async () => true,
      cancelTurn: async () => { calls.cancel += 1; return { accepted: true } },
    },
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: true }),
    sessionEnsure: async ({ declaredSessionId }) => ({ action: 'adopt', sessionId: declaredSessionId, declaredWritten: false, reason: 'adopt', event: null }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
  })
  await w2.start()
  clock.advance(120 * M)
  await w2.tickOnce()
  assert(calls.cancel === 0 && w2.status().self_heal.state === 'off', 'face off: explicitly off, never cancels')
  w2.dispose()
  n += 1
}
done(n)
