// t261004-29 UT: wake on answered request / cleared alert.
// Covers: synthetic row shapes (exits.ts), requestWake receipt honesty (every path),
// the reused self-feed guard ③ on the new source, session-ensure/throttle behavior,
// and alert-clear transition detection (fire → clear → wake, no re-wake, re-fire →
// clear → wake again, restart → no phantom clear). All io is in-memory stubs
// (zero real ~/.sandbar, zero 3099/7233) — same discipline as core.test.mjs.
import { Watchdog } from '../src/host/core.ts'
import { requestAnswerRow, alertClearedRow, worthWaking, freshWakeMemory } from '../src/host/exits.ts'
import { memTailIo, memCoreIo, fakeClock, assert, done } from './lib.mjs'

let n = 0
const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
const mkCfg = (over = {}) => ({ ...CFG, config: { enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: ['reconcile_degraded', 'stall'], keep_days: 14 }, ...over } })

function memWakeIo({ ourBriefPending = null } = {}) {
  const prompts = []
  return {
    prompts,
    async prompt(sessionId, text, mode) { prompts.push({ sessionId, text, mode }); return { accepted: true, requestId: `rid-${prompts.length}` } },
    async queueDepth() { return 0 },
    ...(ourBriefPending ? { ourBriefPending } : {}),
  }
}

function makeDeps({ clock, boardOk = true, wakeIo = null, sessionEnsure = null, executor_session = 'executor-sb', declared = true }) {
  const core = memCoreIo()
  const resolved = mkCfg({ executor_session })
  resolved.declared = declared
  const w = new Watchdog('sandbar', {
    configLoader: () => resolved,
    io: { tail: memTailIo({}), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => boardOk ? { ok: true, rows: [] } : { ok: false, rows: [], error: 'stub: board down' },
    wakeIo,
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    ...(sessionEnsure ? { sessionEnsure } : {}),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return w
}

// ---- ① synthetic rows: shapes, worthWaking, per-id / per-episode tickets ----
{
  const r1 = requestAnswerRow('sandbar', 'req-1', 'host', 'yes')
  assert(worthWaking(r1), 'request-answer row passes the worthWaking gate')
  assert(r1.ticket === 'request-req-1' && r1.stage === 'request' && r1.stage_state === 'answered', 'request row carries stage/stage_state and embeds the request id in ticket')
  const r2 = requestAnswerRow('sandbar', 'req-2', 'host')
  assert(r2.ticket !== r1.ticket, 'a different request id is a different ticket (guard ① cannot swallow it)')
  const c1 = alertClearedRow('sandbar', 'reconcile_degraded:sandbar@/memhome', 1_700_000_000_000)
  assert(worthWaking(c1), 'alert-cleared row passes the worthWaking gate')
  const c2 = alertClearedRow('sandbar', 'reconcile_degraded:sandbar@/memhome', 1_700_000_060_000)
  assert(c2.ticket !== c1.ticket, 'a new fire episode is a new ticket (re-clear wakes again)')
  n += 5
}

// ---- ② requestWake happy path: attempted/woke/reason + queue mode + receipt ring ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo()
  const w = makeDeps({ clock, wakeIo })
  const rec = await w.requestWake({ requestId: 'req-9', by: 'host', detail: 'sign it' })
  assert(rec.attempted === true && rec.woke === true && rec.mode === 'queue' && rec.accepted === true, 'happy path: attempted+woke, queue mode (an answer is never steer)')
  assert(rec.source === 'request-answer' && rec.request_id === 'req-9' && rec.reason.length > 0, 'receipt carries source/request_id/reason')
  assert(wakeIo.prompts.length === 1 && wakeIo.prompts[0].sessionId === 'executor-sb', 'one prompt to the declared session')
  assert(wakeIo.prompts[0].text.includes('req-9') && wakeIo.prompts[0].text.includes('answered'), 'the brief says why the executor was woken (answered request quoted)')
  assert(w.status().wake_receipts.length === 1 && w.status().wake_receipts[0].woke === true, 'receipt ring exposed on the status face')
  w.dispose(); n += 5
}

// ---- ③ self-feed guard ③ stays: our undigested brief suppresses the wake, named ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo({ ourBriefPending: async () => true })
  const w = makeDeps({ clock, wakeIo })
  const rec1 = await w.requestWake({ requestId: 'req-1' }) // no brief id on record; mirror is the deciding leg here
  assert(rec1.attempted === false && /undigested/.test(rec1.reason), 'mirror reports pending with no brief on record: suppressed, named')
  const rec2 = await w.requestWake({ requestId: 'req-2' })
  assert(rec2.attempted === false && rec2.woke === false && /undigested/.test(rec2.reason), 'undigested brief: suppressed again, reason names the pending brief (no re-delivery)')
  assert(wakeIo.prompts.length === 0, 'no prompt while our brief is undigested')
  w.dispose(); n += 3
}

// ---- ③b mirror-first leg: pending brief suppresses even with no brief id on record ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo({ ourBriefPending: async () => true })
  const w = makeDeps({ clock, wakeIo })
  const rec = await w.requestWake({ requestId: 'req-0' })
  assert(rec.attempted === false && rec.woke === false && /undigested/.test(rec.reason), 'mirror-first: pending brief suppresses the push with a named reason (no brief id needed)')
  assert(wakeIo.prompts.length === 0, 'mirror-first: nothing delivered')
  w.dispose(); n += 2
}

// ---- ④ no wake transport: attempted=false with an explicit reason ----
{
  const clock = fakeClock()
  const w = makeDeps({ clock, wakeIo: null })
  const rec = await w.requestWake({ requestId: 'req-3' })
  assert(rec.attempted === false && rec.woke === false && rec.reason.length > 0, 'no wakeIo: attempted=false, reason named (never silence)')
  w.dispose(); n += 1
}

// ---- ⑤ undeclared project: zero-behavior receipt ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo()
  const w = makeDeps({ clock, wakeIo, declared: false })
  const rec = await w.requestWake({ requestId: 'req-4' })
  assert(rec.attempted === false && wakeIo.prompts.length === 0 && /not declared|zero-behavior/.test(rec.reason), 'undeclared project: explicit no-op receipt, no prompt')
  w.dispose(); n += 1
}

// ---- ⑥ no session + refusing ensure: woke=false quoting refusal; throttle shared ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo()
  let ensureCalls = 0
  const w = makeDeps({ clock, wakeIo, executor_session: '', sessionEnsure: async () => { ensureCalls += 1; return { action: 'refused-preset', sessionId: null, event: null, declaredWritten: false, reason: 'preset missing (stub refusal)' } } })
  const rec = await w.requestWake({ requestId: 'req-5' })
  assert(rec.attempted === false && rec.woke === false && /preset missing/.test(rec.reason), 'un-ensurable session: attempted=false quoting the refusal reason (nothing was delivered)')
  const bad = await w.requestWake({ requestId: 42 })
  assert(bad.attempted === false && bad.request_id === null && /non-empty/.test(bad.reason), 'malformed request id: explicit failure receipt, no throw, no prompt')
  assert(ensureCalls === 1, 'ensure invoked once for the push path')
  assert(wakeIo.prompts.length === 0, 'no prompt without a session')
  clock.advance(60_000) // one minute later: still inside SESSION_ENSURE_RETRY_MS (5min)
  const rec2 = await w.requestWake({ requestId: 'req-6' })
  assert(ensureCalls === 1, 'throttle window: ensure NOT re-invoked within SESSION_ENSURE_RETRY_MS')
  assert(rec2.attempted === false && rec2.woke === false, 'throttled answer still lands attempted=false (no prompt possible)')
  n += 1
  w.dispose(); n += 3
}

// ---- ⑦ alert clear: fire → clear wakes once; unchanged tick wakes nobody ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo()
  let down = true
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg({}),
    io: (() => { const c = memCoreIo(); return { tail: memTailIo({}), heartbeat: c.heartbeat, appendAlerts: c.appendAlerts, listAlerts: c.listAlerts } })(),
    boardReader: async () => down ? { ok: false, rows: [], error: 'stub: board down' } : { ok: true, rows: [] },
    wakeIo,
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  await w.start() // tick 1: board down → reconcile_degraded raised
  const withAlert = w.status().alerts.some(a => a.rule === 'reconcile_degraded')
  assert(withAlert, 'precondition: the redline alert fired (status face)')
  const promptsAfterFire = wakeIo.prompts.length
  down = false
  await w.tickOnce() // tick 2: condition cleared → one synthetic clear wake
  const v2 = w.status().last_wake_verdict
  assert(wakeIo.prompts.length === promptsAfterFire + 1, 'clear produces exactly one new delivery')
  assert(wakeIo.prompts[wakeIo.prompts.length - 1].text.includes('cleared'), 'the brief says the alert cleared')
  assert(v2 !== null && v2.woke === true, 'clear tick verdict: woke=true')
  const receipts = w.status().wake_receipts
  await w.tickOnce() // tick 3: unchanged → nobody woken
  assert(wakeIo.prompts.length === promptsAfterFire + 1, 'unchanged tick wakes nobody (same episode)')
  assert(/无新账本行|no new/.test(w.status().last_wake_verdict.reason) || w.status().last_wake_verdict.woke === false, 'unchanged tick verdict is explicit no-wake')
  assert(receipts.length === 0, 'tick-path wakes ride last_wake_verdict, not the push receipt ring')
  w.dispose(); n += 5
}

// ---- ⑧ re-fire → clear again wakes once more (new episode); restart → no phantom ----
{
  const clock = fakeClock()
  const wakeIo = memWakeIo()
  let down = true
  const mk = () => new Watchdog('sandbar', {
    configLoader: () => mkCfg({}),
    io: (() => { const c = memCoreIo(); return { tail: memTailIo({}), heartbeat: c.heartbeat, appendAlerts: c.appendAlerts, listAlerts: c.listAlerts } })(),
    boardReader: async () => down ? { ok: false, rows: [], error: 'stub: board down' } : { ok: true, rows: [] },
    wakeIo,
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  const w = mk()
  await w.start()
  down = false; await w.tickOnce() // clear #1
  const afterFirst = wakeIo.prompts.length
  assert(afterFirst >= 1, 'first clear delivered')
  clock.advance(60_000); down = true; await w.tickOnce() // re-fire (new touch time = new episode id)
  down = false; await w.tickOnce() // clear #2 (new episode)
  assert(wakeIo.prompts.length === afterFirst + 1, 're-fire then clear wakes exactly once more (new episode)')
  w.dispose()
  // C5: a fresh process on an already-clear state wakes nobody.
  down = false
  const w2 = mk()
  await w2.start()
  assert(wakeIo.prompts.length === afterFirst + 1, 'restart on a clear state emits no phantom clear wake')
  w2.dispose(); n += 3
}

done(n)
