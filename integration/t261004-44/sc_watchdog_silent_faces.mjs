#!/usr/bin/env node
/**
 * sc_watchdog_silent_faces.mjs — t261004-44 ticket C scenario (grey-box L3, offline
 * seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Intent (user-perceivable): when a session is waiting on ask_user_question and no
 * question row lands in the ledger within the deadline, the watchdog raises a visible
 * REDLINE naming the session and the face — instead of staying clear (KI-196 silence);
 * and a named deliver refusal (`deliver_refused`) becomes a visible redline naming the
 * session and the face (KI-197). A bridge/delivery that dies must never be silent to
 * the night operator.
 *
 * Steps (real Watchdog class, injected in-memory io — the established grey-box seam):
 *  W0 boot: real Watchdog on a clean fixture is running with no false alert.
 *  W1 pending ask, no ledger row past deadline -> redline naming session + ask face.
 *  W2 pending ask, question row landed in time -> no ask alert (clear is correct here).
 *  W3 deliver_refused row in the ledger -> redline naming session + deliver face.
 *  W4 malformed ledger row -> no crash, phase stays running, skip is named.
 *
 * TDD note: red expected before the implement stage lands (W1/W3 alert absent = FAIL
 * named, never crash).
 */
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const WD = join(REPO, 'server/plugins/watchdog')
const req = createRequire(join(WD, 'package.json'))

const { Watchdog } = await import(pathToFileURL(join(WD, 'src/host/core.ts')).href)
const lib = await import(pathToFileURL(join(WD, 'tests/lib.mjs')).href)
const { memCoreIo, memTailIo, ledgerLine, fakeClock } = lib

let fails = 0
const fail = (m) => { console.error('FAIL ' + m); fails += 1 }

const BASE_CFG = {
  declared: true, enabled: true, config_error: null,
  provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } },
  config: {
    enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
    ask_mirror_deadline_s: 120,
    alerts: {
      enabled: true, sound: false, desktop: false,
      night: { start: '23:00', end: '07:30', policy: 'redline-only' },
      redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'],
      keep_days: 14,
    },
  },
}
const SESSION = 'session-sc44-watch'

function alertText(st) {
  return (st.alerts ?? []).map((a) => JSON.stringify(a)).join('\n')
}
function hasAlert(st, { level, needle }) {
  return (st.alerts ?? []).some((a) => {
    const text = JSON.stringify(a)
    return (level ? a.level === level : true) && needle.every((s) => text.includes(s))
  })
}

function boot({ clock, pending = [], ledgerLines = [] }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => JSON.parse(JSON.stringify(BASE_CFG)),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: true }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return w
}

const questionRow = (sid) => ledgerLine({ seq: 9, kind: 'question', raised_by: sid, session: sid, ticket: 't-ask' })
const refusalRow = (sid) => ledgerLine({ seq: 10, kind: 'deliver_refused', session: sid, ticket: 't-del', error: 'deliver: workflow class ExecutorDeliveryWorkflow is not registered on the running worker' })
const pendingAsk = (sid) => ({ raisedBy: sid, kind: 'question', target: 'req-sc44', sessionRunning: true })

try {
  // ── W0: clean boot, no false alarm ──
  {
    const clock = fakeClock()
    const w = boot({ clock, pending: [], ledgerLines: [] })
    await w.start(); await w.tickOnce()
    const st = w.status()
    if (st.phase !== 'running') fail(`W0 clean watchdog not running: phase=${st.phase} lastError=${st.last_error}`)
    if (hasAlert(st, { needle: [SESSION] })) fail('W0 false alert on a clean fixture')
    w.dispose()
  }

  // ── W1: pending ask past deadline, no question row -> redline names session + face ──
  {
    const clock = fakeClock()
    const w = boot({ clock, pending: [pendingAsk(SESSION)], ledgerLines: [] })
    await w.start()
    clock.advance?.(121_000) ?? null
    await w.tickOnce()
    const st = w.status()
    if (!hasAlert(st, { level: 'redline', needle: [SESSION] })) {
      fail(`W1 no redline for a session waiting on ask_user_question with no mirrored row past the deadline — the KI-196 silence face is still open. alerts=${alertText(st).slice(0, 400)}`)
    } else {
      const a = (st.alerts ?? []).find((x) => JSON.stringify(x).includes(SESSION))
      const text = JSON.stringify(a)
      if (!/ask/i.test(text)) fail('W1 redline does not name the ask_user_question face: ' + text.slice(0, 200))
    }
    w.dispose()
  }

  // ── W2: question row landed in time -> clear is correct, no ask redline ──
  {
    const clock = fakeClock()
    const w = boot({ clock, pending: [pendingAsk(SESSION)], ledgerLines: [questionRow(SESSION)] })
    await w.start(); await w.tickOnce()
    const st = w.status()
    if (hasAlert(st, { needle: ['ask'] }) && hasAlert(st, { needle: [SESSION] }))
      fail('W2 mirrored-in-time ask raised a redline (clear must stay clear): ' + alertText(st).slice(0, 300))
    w.dispose()
  }

  // ── W3: deliver_refused row -> redline naming session + deliver face ──
  {
    const clock = fakeClock()
    const w = boot({ clock, pending: [], ledgerLines: [refusalRow(SESSION)] })
    await w.start(); await w.tickOnce()
    const st = w.status()
    if (!hasAlert(st, { level: 'redline', needle: [SESSION] })) {
      fail(`W3 no redline for a named deliver refusal in the ledger — the delivery face dies silently to the operator. alerts=${alertText(st).slice(0, 400)}`)
    } else {
      const a = (st.alerts ?? []).find((x) => JSON.stringify(x).includes(SESSION))
      const text = JSON.stringify(a)
      if (!/deliver/i.test(text)) fail('W3 redline does not name the deliver face: ' + text.slice(0, 200))
      if (!/ExecutorDeliveryWorkflow/.test(text)) fail('W3 redline drops the refusal detail (the named refusal must survive into the alert): ' + text.slice(0, 200))
    }
    w.dispose()
  }

  // ── W4: malformed ledger row -> no crash, named skip, phase stays running ──
  {
    const clock = fakeClock()
    const bad = '{{{not json at all'
    const w = boot({ clock, pending: [], ledgerLines: [bad] })
    await w.start(); await w.tickOnce()
    const st = w.status()
    if (st.phase !== 'running') fail(`W4 malformed ledger row crashed the watchdog: phase=${st.phase}`)
    const lastErr = st.last_error ?? ''
    const named = (st.ledger?.malformed_rows ?? 0) > 0 || lastErr.length > 0 || (st.startup?.malformed ?? 0) > 0
    if (!named) fail(`W4 malformed row silently swallowed (skip must be named): status=${JSON.stringify(st.ledger ?? {})} lastError=${lastErr}`)
    w.dispose()
  }
} catch (e) {
  fail('W9 scenario crashed: ' + (e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : String(e)))
}

console.log(`SC_WATCHDOG_SILENT_FACES fails=${fails}`)
process.exit(fails === 0 ? 0 : 1)
