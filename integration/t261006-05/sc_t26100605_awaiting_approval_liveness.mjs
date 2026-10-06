#!/usr/bin/env node
/**
 * sc_t26100605_awaiting_approval_liveness.mjs — t261006-05 scenario ② (grey-box L3,
 * offline seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Intent (user-perceivable, KI-207 item 1): an executor session parked on an
 * UNANSWERED approval must be a NAMED liveness state on the host-facing surface —
 * never indistinguishable from a long turn. Incident 261006: approval/asked at
 * 03:29:43 (id ea1dc845-...), zero writes for four hours, the watchdog read
 * "session_running: true (long turn in progress)" — waiting looked like working.
 *
 * Public seams (landed): approval-face.ts exports judgeApprovalWindow(records)
 * (three-valued: awaiting | clear | none | unknown); liveness.ts exports
 * judgeExecutor accepting `unansweredApproval` ({approval_id, asked_at, evidence}
 * | null) and the state 'awaiting_approval'.
 *
 * Steps:
 *  A1 asked without decided + running=true -> state 'awaiting_approval' with the
 *     id named in the evidence (NOT long_turn — the incident fingerprint).
 *  A2 asked then decided -> no false waiting state (judgeApprovalWindow clear).
 *  A3 unreadable/shapeless records -> judgeApprovalWindow 'unknown', never a
 *     silent none; malformed rows never crash.
 *  A4 no approval signal at all -> the base truth table unchanged (advancing).
 *  A5 host-facing leg: a real Watchdog with an approvalProvider reporting an
 *     unanswered approval raises the redline alert naming the approval id
 *     (review condition 2: state face AND alert face, not half-wired).
 *
 * Intent split: judgeExecutor's base truth table and judgeApprovalWindow's
 * per-literal matrices belong to the developer L1 battery (watchdog tests); this
 * entry pins the incident fingerprint at the public liveness seam and the
 * alert-face wiring through the real Watchdog core seam.
 *
 * TDD note: red expected before the implement stage lands. Watchdog tree missing
 * = ENV_FAIL exit 2.
 */
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const WD = join(REPO, 'server/plugins/watchdog')
const req = createRequire(join(WD, 'package.json'))

let liveness, approvalFace, core, lib
try {
  liveness = await import(pathToFileURL(join(WD, 'src/host/liveness.ts')).href)
  approvalFace = await import(pathToFileURL(join(WD, 'src/host/approval-face.ts')).href)
  core = await import(pathToFileURL(join(WD, 'src/host/core.ts')).href)
  lib = await import(pathToFileURL(join(WD, 'tests/lib.mjs')).href)
} catch (e) {
  console.log(JSON.stringify({ name: 't261006-05-awaiting-approval-liveness', suite: 't261006-05-awaiting-approval-liveness', status: 'not-checked', cause: 'external', reason: 'watchdog module import failed', evidence: String(e).slice(0, 300) }))
  process.exit(2)
}

const SUITE = 't261006-05-awaiting-approval-liveness'
let fails = 0
const out = (name, ok, reason, evidence) => {
  console.log(JSON.stringify({ name, suite: SUITE, status: ok ? 'pass' : 'fail', cause: 'self', reason, evidence: String(evidence).slice(0, 300) }))
  if (!ok) fails += 1
}

const NOW = 1_000_000
const ASKED_AT = NOW - 4 * 3600_000
const approvalId = 'ea1dc845-incident'
const BASE_INPUT = {
  sessionKnown: true, ledgerAdvanced: false, sessionProgress: false,
  lastWakeAt: NOW - 60_000, sessionRunning: true,
}

// A1 the incident fingerprint: unanswered approval + running=true -> named
// awaiting state, evidence carries the id; never long_turn.
try {
  const st = liveness.judgeExecutor({
    ...BASE_INPUT,
    unansweredApproval: { approval_id: approvalId, asked_at: ASKED_AT, evidence: 'approval/asked id ' + approvalId },
  }, NOW, 15, NOW - 60_000, 45)
  const ok = st.state === 'awaiting_approval' && JSON.stringify(st).includes(approvalId)
  out('A1-unanswered-approval-named-not-long-turn',
    ok, "expected state 'awaiting_approval' naming the id; got " + st.state,
    JSON.stringify(st).slice(0, 250))
} catch (e) {
  out('A1-unanswered-approval-named-not-long-turn', false, 'judgeExecutor unansweredApproval input missing or threw', String(e))
}

// A2 asked then decided: no false waiting state at the reader.
try {
  const w = approvalFace.judgeApprovalWindow([
    { type: 'approval/asked', data: { id: approvalId, at: ASKED_AT } },
    { type: 'approval/decided', data: { id: approvalId, at: ASKED_AT + 1000 } },
  ])
  out('A2-decided-approval-no-false-waiting',
    w.state === 'clear', "expected 'clear', got " + w.state, JSON.stringify(w).slice(0, 250))
} catch (e) {
  out('A2-decided-approval-no-false-waiting', false, 'judgeApprovalWindow threw', String(e))
}

// A3 the reader truth table: asked-without-decided -> awaiting with id;
// shapeless records -> named unknown, never a silent none; junk rows no crash.
try {
  const waiting = approvalFace.judgeApprovalWindow([
    { type: 'assistant/message', data: {} },
    { type: 'approval/asked', data: { id: approvalId, at: ASKED_AT } },
  ])
  const unknown = approvalFace.judgeApprovalWindow([7, null, { data: {} }, 'x'])
  const emptyNone = approvalFace.judgeApprovalWindow([])
  out('A3-approval-window-truth-table',
    waiting.state === 'awaiting' && waiting.approval_id === approvalId
    && unknown.state === 'unknown' && emptyNone.state === 'none',
    'asked-without-decided -> awaiting(id); shapeless -> unknown; empty -> none',
    JSON.stringify({ waiting, unknown, emptyNone }).slice(0, 250))
} catch (e) {
  out('A3-approval-window-truth-table', false, 'judgeApprovalWindow missing or threw', String(e))
}

// A4 no approval signal at all: today's truth table unchanged (running=true,
// silence 1min < thresholds -> advancing, exactly the pre-ticket behavior).
try {
  const st = liveness.judgeExecutor(BASE_INPUT, NOW, 15, NOW - 60_000, 45)
  out('A4-no-approval-truth-table-unchanged',
    st.state === 'advancing', 'base state drifted, got ' + st.state, 'state=' + st.state)
} catch (e) {
  out('A4-no-approval-truth-table-unchanged', false, 'base judgeExecutor threw', String(e))
}

// A5 host-facing leg: the real Watchdog turns the awaiting state into a redline
// alert naming the approval id (state face AND alert face).
try {
  const { memCoreIo, memTailIo, fakeClock } = lib
  const clock = fakeClock()
  const BASE_CFG = {
    declared: true, enabled: true, config_error: null,
    provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } },
    config: {
      enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
      ask_mirror_deadline_s: 120, long_turn_minutes: 45,
      alerts: {
        enabled: true, sound: false, desktop: false,
        night: { start: '23:00', end: '07:30', policy: 'redline-only' },
        redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall', 'executor_awaiting_approval'],
        keep_days: 14,
      },
    },
  }
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: '' } }
  const coreIo = memCoreIo()
  const w = new core.Watchdog('sandbar', {
    configLoader: () => JSON.parse(JSON.stringify(BASE_CFG)),
    io: { tail: memTailIo(files), heartbeat: coreIo.heartbeat, appendAlerts: coreIo.appendAlerts, listAlerts: coreIo.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: true }),
    approvalProvider: async () => ({ available: true, awaiting: true, approval_id: approvalId, asked_at: ASKED_AT, evidence: 'approval/asked id ' + approvalId + ' in the recent history window' }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  await w.tickOnce()
  const alerts = JSON.stringify(coreIo.appended ?? [])
  const ok = alerts.includes('executor_awaiting_approval') && alerts.includes(approvalId)
  out('A5-watchdog-raises-named-approval-redline',
    ok, 'the real Watchdog must raise a redline naming the rule and the approval id',
    alerts.slice(0, 280))
} catch (e) {
  out('A5-watchdog-raises-named-approval-redline', false, 'Watchdog core seam or approvalProvider dep missing/threw', String(e))
}

if (fails) {
  console.log('SUMMARY: ' + SUITE + ' FAIL=' + fails)
  process.exit(1)
}
console.log('SUMMARY: ' + SUITE + ' all pass')
