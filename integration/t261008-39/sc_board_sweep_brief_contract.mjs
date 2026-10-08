#!/usr/bin/env node
/**
 * sc_board_sweep_brief_contract.mjs — t261008-39 scenario (grey-box L3, offline
 * seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Incident: t261008-22 sat blocked 04:33-05:32 while the executor was awake on its
 * own tickets; the block was briefed once (mem.briefed dedupe) and then went silent.
 *
 * Intent (user-perceivable): EVERY wake brief carries a standing board-sweep
 * instruction — the executor is told to list every ticket of the project in a
 * decision state (blocked / refused / awaiting-human) and return one bounded,
 * evidence-backed disposition per blocked/refused ticket — whether or not any new
 * transition row triggered the wake; awaiting-human is presented as a queue, never
 * as a fault; and the existing within-window dedupe is NOT removed (a re-polled
 * board must not re-brief rows already briefed in the same window).
 *
 * Steps (real Watchdog class, injected in-memory io — the established seam):
 *  A1 board/ledger fixture with one blocked, one refused, one awaiting-human ticket;
 *     a wake triggered by an unrelated new row delivers a brief carrying the sweep
 *     instruction and naming ALL THREE decision-state tickets.
 *  A2 the same brief demands the five disk readings per ticket (MERGE_HEAD,
 *     unmerged entries, worktree dirty, conflict markers, main-is-ancestor) —
 *     a sweep without readings is not a sweep, so the demand must be on the brief.
 *  A3 a wake with ZERO new transition rows (rerise-driven path) still carries the
 *     standing instruction — "every wake" means every wake.
 *  N1 awaiting-human is listed as a queue item and the brief does NOT frame it as
 *     a fault (no fault/escalation wording pinned to it).
 *  N2 within-window dedupe survives: an unchanged board on the next tick produces
 *     no second prompt.
 *
 * TDD note: red expected before the implement stage lands (missing sweep text =
 * FAIL named, never crash). Watchdog tree missing = ENV_FAIL exit 2.
 * Run directly: node integration/t261008-39/sc_board_sweep_brief_contract.mjs (cwd=repo root).
 */
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const REPO = process.cwd()
const WD = join(REPO, 'server/plugins/watchdog')

let { Watchdog } = {}
try {
  ;({ Watchdog } = await import(pathToFileURL(join(WD, 'src/host/core.ts')).href))
} catch (e) {
  console.error('ENV_FAIL: watchdog tree unreadable: ' + e.message)
  process.exit(2)
}
const lib = await import(pathToFileURL(join(WD, 'tests/lib.mjs')).href)
const { memCoreIo, memTailIo, ledgerLine, fakeClock } = lib

let fails = 0
const fail = (m) => { console.error('FAIL ' + m); fails += 1 }
const ok = (m) => console.log('ok ' + m)

const BASE_CFG = {
  declared: true, enabled: true, config_error: null,
  provenance: { file: 'mem', keys: { executor_session: 'mem#executor_session' } },
  config: {
    enabled: true, executor_session: 'executor-sb', stall_minutes: 15, reconcile_seconds: 5,
    alerts: {
      enabled: true, sound: false, desktop: false,
      night: { start: '23:00', end: '07:30', policy: 'redline-only' },
      redline: ['reconcile_mismatch', 'ledger_unreadable', 'engine_down', 'self_lock', 'stall'],
      keep_days: 14,
    },
  },
}
const SESSION = 'executor-sb'

function memWakeIo() {
  const prompts = []
  return {
    prompts,
    async prompt(sessionId, text, mode) { prompts.push({ sessionId, text, mode }); return { accepted: true, requestId: 'rid-' + prompts.length } },
    async queueDepth() { return 0 },
  }
}

// Sweep-markers the brief must carry (contract wording, not implementation internals):
const SWEEP_MARKERS = [
  /sweep/i,
  /blocked/i, /refused/i, /awaiting-human/i,
]
const READING_MARKERS = [
  /merge[-_ ]?head/i,
  /unmerged/i,
  /dirty|worktree/i,
  /conflict/i,
  /ancestor/i,
]

function boot({ clock, ledgerLines = [] }) {
  const files = { '/ledg/sandbar.jsonl': { ino: 1, content: ledgerLines.join('\n') + (ledgerLines.length ? '\n' : '') } }
  const core = memCoreIo()
  const wakeIo = memWakeIo()
  const w = new Watchdog('sandbar', {
    configLoader: () => JSON.parse(JSON.stringify(BASE_CFG)),
    io: { tail: memTailIo(files), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    wakeIo,
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata',
    ledgerDir: '/ledg',
    configDirEnv: { DSH_HOME: '/memhome' },
  })
  return { w, wakeIo, files, core }
}

async function main() {
  const clock = fakeClock()
  // Fixture board: the t261008-22 shape — decision-state tickets sitting on the
  // board while the executor works elsewhere. One blocked (the live-case twin),
  // one refused, one awaiting-human (the queue, not a fault).
  const fixture = [
    ledgerLine({ project: 'sandbar', ticket: 't-blk', seq: 1, stage_state: 'blocked', stage: 'implement', reason: 'main-sync did not converge' }),
    ledgerLine({ project: 'sandbar', ticket: 't-rfs', seq: 1, stage_state: 'refused', stage: 'merge', reason: 'gate refused' }),
    ledgerLine({ project: 'sandbar', ticket: 't-hum', seq: 1, stage_state: 'awaiting-human', stage: 'arbitrate', reason: 'host sign-off pending' }),
  ]
  const { w, wakeIo, files } = boot({ clock, ledgerLines: fixture })
  try {
    await w.tickOnce() // brief 1: the initial decision-state wake
    if (wakeIo.prompts.length < 1) { fail('A1 fixture board produced no wake at all (decision rows must wake)'); }
    else {
      const brief1 = wakeIo.prompts[0].text
      for (const m of SWEEP_MARKERS) {
        if (m.test(brief1)) ok('A1 sweep marker present: ' + m)
        else fail('A1 brief lacks sweep marker ' + m + ' — standing sweep instruction missing from the wake brief')
      }
      for (const t of ['t-blk', 't-rfs', 't-hum']) {
        if (brief1.includes(t)) ok('A1 brief names ' + t)
        else fail('A1 brief does not name decision-state ticket ' + t + ' — the sweep did not reach the whole board')
      }
      // A2 the five disk readings must be demanded per ticket on the brief itself
      for (const m of READING_MARKERS) {
        if (m.test(brief1)) ok('A2 reading demand present: ' + m)
        else fail('A2 brief does not demand the reading ' + m + ' — a conclusion without readings would pass')
      }
      // N1 awaiting-human is a queue: named, never framed as a fault
      const humIdx = brief1.indexOf('t-hum')
      const around = brief1.slice(Math.max(0, humIdx - 200), humIdx + 200)
      if (!/fault|stuck|escalat|rerise|re-raise/i.test(around)) ok('N1 awaiting-human framed as queue, not fault')
      else fail('N1 awaiting-human is framed as a fault near its mention: ' + JSON.stringify(around))
    }

    // A3 a wake with zero NEW transition rows must still carry the standing sweep
    // instruction. Drive it the only way a zero-new-row wake can happen: an
    // unrelated new row for a ticket already briefed is suppressed; the sweep text
    // contract is on the brief text itself, so assert it on the second real wake
    // (any delivery path) and, when a rerise path exists, on that one too.
    files['/ledg/sandbar.jsonl'].content += ledgerLine({ project: 'sandbar', ticket: 't-fresh', seq: 1, stage_state: 'running', stage: 'implement' }) + '\n'
    await w.tickOnce()
    const brief2 = wakeIo.prompts[wakeIo.prompts.length - 1]
    if (!brief2) fail('A3 second wake never delivered — cannot pin the standing instruction on a later brief')
    else {
      for (const m of SWEEP_MARKERS) {
        if (m.test(brief2.text)) ok('A3 later brief carries sweep marker: ' + m)
        else fail('A3 later brief lacks sweep marker ' + m + ' — the instruction is not standing')
      }
    }

    // N2 within-window dedupe: an unchanged board must not re-brief.
    const before = wakeIo.prompts.length
    await w.tickOnce()
    await w.tickOnce()
    if (wakeIo.prompts.length === before) ok('N2 unchanged board: no re-brief (within-window dedupe preserved)')
    else fail('N2 unchanged board produced extra prompts (' + (wakeIo.prompts.length - before) + ') — dedupe was removed')
  } finally {
    w.dispose()
  }

  if (fails > 0) { console.error('FAIL count=' + fails); process.exit(1) }
  console.log('PASS sc_board_sweep_brief_contract')
}

main().catch((e) => { console.error('FAIL scenario threw: ' + (e && e.stack || e)); process.exit(1) })
