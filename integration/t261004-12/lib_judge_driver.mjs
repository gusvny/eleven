// lib_judge_driver.mjs — t261004-12 shared gray-box driver (integration-owned, not sc_).
//
// Binds to the watchdog plugin's PUBLIC contract only:
//   - `Watchdog` class (exported by src/host/core.ts) with injected deps
//   - the declared `SessionStatFn` contract, which after t261004-12 also carries the
//     session `running` bit (`boolean | null`)
//   - the user-perceivable faces: `status()` (liveness.executor state + running bit)
//     and the alert ledger entries (rule/level/detail).
// All io is in-memory; the clock is injected; nothing touches 3099/7233 or docker.
// A leg prints `SUMMARY pass=X fail=Y env_fail=Z na=W` and exits 0/1/2 per the
// three-state contract (README execution contract).

import { Watchdog } from '../../server/plugins/watchdog/src/host/core.ts'

const M = 60_000
const NOW0 = 1_700_000_000_000

function assert(cond, msg, res) {
  if (cond) { res.pass += 1; console.log('ok   ' + msg) }
  else { res.fail += 1; console.log('FAIL ' + msg) }
}

function memIo(extraAlertLines = []) {
  const alerts = []
  const lines = [...extraAlertLines]
  return {
    tail: {
      stat: async () => ({ size: 0, ino: 1 }),
      read: async () => '',
    },
    heartbeat: {
      write: async () => {},
      read: async () => { throw new Error('none') },
      mtimeMs: async () => null,
    },
    appendAlerts: async (_p, line) => { alerts.push(JSON.parse(line)) },
    listAlerts: async () => [...lines.map(l => JSON.parse(l)), ...alerts],
    _alerts: alerts,
  }
}

function mkCfg(over = {}) {
  return {
    declared: true, enabled: true, config_error: null,
    provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } },
    config: {
      enabled: true,
      executor_session: 'executor-sb',
      stall_minutes: 15,
      reconcile_seconds: 5,
      alerts: {
        enabled: true, sound: true, desktop: true,
        night: { start: '23:00', end: '07:30', policy: 'redline-only' },
        redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'],
        keep_days: 14,
      },
      ...over,
    },
  }
}

// opts: { running, advanced, long_turn_minutes? } — one watchdog; sig is a mutable
// holder (set({running, advanced}) flips the injected signals between beats);
// beat(t) advances the injected clock and calls tickOnce().
function makeWatchdog({ running, advanced, longTurnCfg } = {}) {
  let now = NOW0
  const sig = { running: running ?? null, advanced: advanced ?? false }
  const io = memIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(longTurnCfg !== undefined ? { long_turn_minutes: longTurnCfg } : {}),
    io,
    boardReader: async () => ({ ok: true, rows: [{ id: 't1', stage_state: 'running' }] }),
    pendingProvider: async () => ({ available: true, pending: null }),
    sessionStat: async () => ({ advanced: sig.advanced, mtimeMs: now, running: sig.running }),
    now: () => now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return {
    w, io, sig,
    set: (over) => { Object.assign(sig, over) },
    beat: async (mins) => { now += mins * M; await w.tickOnce() },
    nowMs: () => now,
  }
}

const liv = (w) => w.status().liveness.executor
const rules = (w) => w.status().alerts.map(a => a.rule)

// ---- leg 1: a busy executor in a long turn is never a stall redline ----
async function legLongTurn() {
  const res = { pass: 0, fail: 0, env_fail: 0, na: 0 }
  // A1: running=true, no message/ledger advance. Establish a progress baseline first
  // (a message lands), then cut the signal — the silence clock must start from that
  // baseline, as in real operation. Silence crosses the 15min stall threshold beat by
  // beat — no stall redline may ever fire while it runs.
  const g = makeWatchdog({ running: true, advanced: true })
  await g.w.start()
  await g.beat(5) // baseline: message landed, last_progress_at set
  g.set({ advanced: false })
  for (let i = 1; i <= 4; i++) await g.beat(5) // 20min silent > stall_minutes
  assert(liv(g.w) !== null, 'A1 status exposes an executor liveness face', res)
  assert(liv(g.w).state !== 'stalled', 'A1 running session silent 20min is NOT stalled', res)
  assert(!rules(g.w).includes('stall'), 'A1 no stall redline fired while running', res)
  assert(liv(g.w).session_running === true, 'A1 status face exposes the running bit (true)', res)
  // A2: keep the same silence going past the long-turn knob (default 45min, separate
  // from stall_minutes). Beats are 5min grace beats — if any beat reset the silence
  // clock (t261001-19 defect-A shape), long_turn would be unreachable.
  for (let i = 5; i <= 9; i++) await g.beat(5) // 45min silent total
  assert(liv(g.w).state === 'long_turn', 'A2 past long_turn_minutes a DISTINCT case appears (not stalled)', res)
  assert(!rules(g.w).includes('stall'), 'A2 long turn still never a stall redline', res)
  const ltAlerts = g.w.status().alerts.filter(a => a.rule === 'executor_long_turn')
  assert(ltAlerts.length >= 1 && ltAlerts[0].level !== 'redline',
    'A2 long turn raises its own warn-level rule, not a redline', res)
  const ev = (liv(g.w).evidence || '') + ' ' + (ltAlerts.map(a => a.detail || '').join(' '))
  assert(/long[ -]?turn|running/i.test(ev), 'A2 evidence names the running/long-turn check that produced it', res)
  // A6: a message lands while running -> progress, back to working.
  const g2 = makeWatchdog({ running: true, advanced: true })
  await g2.w.start()
  await g2.beat(20)
  assert(liv(g2.w).state !== 'stalled' && liv(g2.w).state !== 'long_turn',
    'A6 message landing while running counts as progress (advancing)', res)
  g.w.dispose(); g2.w.dispose()
  return res
}

// ---- leg 2: fallbacks unchanged + status face tells the cases apart ----
async function legFallbacks() {
  const res = { pass: 0, fail: 0, env_fail: 0, na: 0 }
  // B1: running=false, silence past stall_minutes -> stalled, exactly as today.
  const s = makeWatchdog({ running: false, advanced: true })
  await s.w.start()
  await s.beat(5) // progress baseline, then silence
  s.set({ advanced: false })
  await s.beat(16)
  assert(liv(s.w).state === 'stalled', 'B1 not-running session silent 16min = stalled (unchanged)', res)
  assert(rules(s.w).includes('stall'), 'B1 stall redline still fires for not-running silence', res)
  assert(liv(s.w).session_running === false, 'B1 status face exposes the running bit (false)', res)
  assert((liv(s.w).evidence || '').length > 0, 'B1 stall evidence names the check that produced it', res)
  // B2: running unreadable (null) + silent -> explicit unknown, never stalled.
  const u = makeWatchdog({ running: null })
  await u.w.start()
  await u.beat(60)
  assert(liv(u.w).state !== 'stalled', 'B2 unreadable running bit never collapses to stalled', res)
  assert(liv(u.w).state === 'no_signal', 'B2 unreadable bit = explicit no_signal (unknown), not normal', res)
  assert(!rules(u.w).includes('stall'), 'B2 no stall redline on an unreadable bit', res)
  assert(liv(u.w).session_running === null, 'B2 status face shows the bit as unknown (null), not false', res)
  // B3: the stall path stays reachable and unchanged when the bit reads false and the
  // config knob is untouched — long_turn never replaces it at the stall threshold.
  const s2 = makeWatchdog({ running: false, advanced: true })
  await s2.w.start()
  await s2.beat(5)
  s2.set({ advanced: false })
  await s2.beat(45)
  assert(liv(s2.w).state === 'stalled', 'B3 not-running 45min silent = stalled, not long_turn', res)
  s.w.dispose(); u.w.dispose(); s2.w.dispose()
  return res
}

const legs = { 'long-turn': legLongTurn, fallbacks: legFallbacks }
const leg = process.argv[2] || ''
if (!legs[leg]) {
  console.error('ENV_FAIL: unknown or missing leg: %s (expected one of %s)', leg, Object.keys(legs).join(','))
  process.exit(2)
}
try {
  const res = await legs[leg]()
  console.log(`SUMMARY pass=${res.pass} fail=${res.fail} env_fail=${res.env_fail} na=${res.na}`)
  process.exit(res.fail > 0 ? 1 : 0)
} catch (e) {
  console.log('FAIL driver error: ' + (e && e.message))
  console.log(`SUMMARY pass=0 fail=1 env_fail=0 na=0`)
  process.exit(1)
}
