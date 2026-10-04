// lib_copy_face_driver.mjs — t261004-24 gray-box driver (integration-owned, not sc_).
//
// Locks the user-perceivable LANGUAGE contract of the console-visible watchdog copy
// (t261004-24, executor request -0003): alert titles, liveness evidence and settings
// validation messages that reach the panel must be English per the writing standard
// (docs/reference/writing-standard.md §1/§2), while KEEPING the deciding precision
// (which check decided: the running bit, the stall threshold, the long-turn threshold).
//
// Binding is light on purpose: we assert the LANGUAGE family (no CJK ideographs, no
// fullwidth/CJK punctuation) and the precision carriers (session id verbatim, threshold
// numbers present, the deciding source named) — never an exact English sentence.
// Behavior semantics (which state fires when) belong to t261004-12; this driver only
// exercises enough of the public face to obtain the strings.
//
// All io in-memory; injected clock; nothing touches 3099/7233 or docker.
// A leg prints `SUMMARY pass=X fail=Y env_fail=Z na=W` and exits 0/1 per contract.

import { Watchdog } from '../../server/plugins/watchdog/src/host/core.ts'
import { parseWatchdogConfig } from '../../server/plugins/watchdog/src/host/config.ts'

const M = 60_000
const NOW0 = 1_700_000_000_000

// CJK ideographs + CJK punctuation/fullwidth forms. English STE copy carries none of
// these; numbers, parens and ASCII punctuation are the expected shape.
const CJK = /[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]/

function assert(cond, msg, res) {
  if (cond) { res.pass += 1; console.log('ok   ' + msg) }
  else { res.fail += 1; console.log('FAIL ' + msg) }
}

function memIo() {
  const alerts = []
  return {
    tail: { stat: async () => ({ size: 0, ino: 1 }), read: async () => '' },
    heartbeat: {
      write: async () => {},
      read: async () => { throw new Error('none') },
      mtimeMs: async () => null,
    },
    appendAlerts: async (_p, line) => { alerts.push(JSON.parse(line)) },
    listAlerts: async () => [...alerts],
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

function makeWatchdog({ running, advanced, cfgOver = {} } = {}) {
  let now = NOW0
  const sig = { running: running ?? null, advanced: advanced ?? false }
  const io = memIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => mkCfg(cfgOver),
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
  }
}

const liv = (w) => w.status().liveness.executor
const noCjk = (s) => !CJK.test(s || '')

// ---- leg 1: alert + evidence copy language (the t261004-12 new copy) ----
async function legAlertCopy() {
  const res = { pass: 0, fail: 0, env_fail: 0, na: 0 }
  // long-turn case (the exact copy named in the ticket): title + detail reach the panel.
  const g = makeWatchdog({ running: true, advanced: true })
  await g.w.start()
  await g.beat(5)
  g.set({ advanced: false })
  for (let i = 1; i <= 9; i++) await g.beat(5) // 45min silent -> long_turn
  const lt = g.w.status().alerts.filter(a => a.rule === 'executor_long_turn')
  assert(lt.length >= 1, 'C1 long-turn alert obtained from the public alert face', res)
  const title = (lt[0] && (lt[0].title || lt[0].rule)) || ''
  const detail = (lt[0] && (lt[0].detail || '')) || ''
  const ev = (liv(g.w).evidence || '')
  assert(noCjk(title), 'C1 long-turn ALERT TITLE is English copy (got: ' + title + ')', res)
  assert(noCjk(detail), 'C1 long-turn alert DETAIL (evidence) is English copy', res)
  assert(noCjk(ev), 'C1 status-face evidence string is English copy (got: ' + ev.slice(0, 80) + ')', res)
  assert(title.includes('executor-sb'), 'C1 title still names the session id verbatim (precision kept)', res)
  assert(/45/.test(detail + ' ' + ev) && /running/i.test(detail + ' ' + ev),
    'C1 evidence still carries the deciding precision: long-turn threshold number + running bit', res)

  // stall case: evidence must stay English AND name the stall threshold it decided on.
  const s = makeWatchdog({ running: false, advanced: true, cfgOver: { stall_minutes: 16 } })
  await s.w.start()
  await s.beat(5)
  s.set({ advanced: false })
  await s.beat(17)
  const sev = liv(s.w).evidence || ''
  const sd = (s.w.status().alerts.filter(a => a.rule === 'stall')[0] || {}).detail || ''
  assert(liv(s.w).state === 'stalled', 'C2 stall case obtained (behavior unchanged)', res)
  assert(noCjk(sev), 'C2 stall evidence is English copy (got: ' + sev.slice(0, 80) + ')', res)
  assert(noCjk(sd), 'C2 stall alert detail is English copy', res)
  assert(/16/.test(sev + ' ' + sd) && /running/i.test(sev + ' ' + sd),
    'C2 stall evidence still names the stall threshold + the running=false source', res)

  // degraded-heartbeat reason (readHeartbeat fallback strings) — status-face copy too.
  const hb = s.w.status().heartbeat
  assert(hb.alive === false, 'C3 degraded heartbeat face obtained', res)
  assert(noCjk(hb.reason), 'C3 heartbeat degradation reason is English copy (got: ' + hb.reason + ')', res)
  g.w.dispose(); s.w.dispose()
  return res
}

// ---- leg 2: settings validation copy returned to the panel/operator ----
async function legConfigCopy() {
  const res = { pass: 0, fail: 0, env_fail: 0, na: 0 }
  const cases = [
    ['enabled', '{"enabled": "yes"}'],
    ['executor_session', '{"executor_session": ""}'],
    ['stall_minutes', '{"stall_minutes": -1}'],
    ['long_turn_minutes', '{"long_turn_minutes": "x"}'],
    ['reconcile_seconds', '{"reconcile_seconds": 1}'],
  ]
  for (const [key, raw] of cases) {
    const r = parseWatchdogConfig(raw, 'watchdog.json')
    const msg = r.config_error || ''
    assert(r.config_error !== null && r.config_error !== '',
      'C4 ' + key + ': a refused save returns an explicit error', res)
    assert(msg.includes(key),
      'C4 ' + key + ': error names the offending key (precision kept)', res)
    assert(noCjk(msg),
      'C4 ' + key + ': settings validation copy is English (got: ' + msg + ')', res)
  }
  // a valid doc still parses clean (no false refusal introduced by the rewording).
  const ok = parseWatchdogConfig('{"enabled": true}', 'watchdog.json')
  assert(ok.config_error === null, 'C4 valid config still parses with no error', res)
  return res
}

const legs = [
  ['alert-copy', legAlertCopy],
  ['config-copy', legConfigCopy],
]

let failed = false
for (const [name, fn] of legs) {
  const r = await fn()
  console.log(`SUMMARY leg=${name} pass=${r.pass} fail=${r.fail} env_fail=${r.env_fail} na=${r.na}`)
  if (r.fail > 0) failed = true
}
process.exit(failed ? 1 : 0)
