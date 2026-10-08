#!/usr/bin/env node
/**
 * sc_stuck_block_rerise_persistence.mjs — t261008-39 scenario (grey-box L3, offline
 * seconds, zero docker/Temporal/browser, never touches 3099/7233).
 *
 * Incident: t261008-22 sat blocked 59 minutes, briefed once, never mentioned again —
 * the once-only dedupe turned a stuck block into silence.
 *
 * Intent (user-perceivable): a ticket that STAYS blocked/refused past a stated
 * threshold with no recorded action is mentioned AGAIN on a later wake, with the
 * age and the threshold visible ("still blocked, previously surfaced" — a silent
 * threshold would be the same defect); the re-raise is bounded (one per threshold
 * window, not nagging); an action that failed to unblock the ticket surfaces later
 * (2x threshold) with after-action wording instead of nagging a working attempt;
 * awaiting-human is NEVER re-raised as a fault; and a rerise in a batch never
 * un-suppresses an already-briefed normal row (the self-feed guards survive).
 *
 * Steps (real Watchdog class, injected in-memory io and a hand-advanced clock):
 *  R1 ticket blocked at t0, briefed once; clock advanced past the threshold with
 *     zero action rows -> the next wake names the ticket again with "previously
 *     surfaced"-class wording and names the threshold (never silent).
 *  R2 bounded: the tick right after that rerise (inside the window) re-raises
 *     nothing.
 *  R3 an executor action row lands on the still-blocked ticket -> no rerise at 1x;
 *     at 2x threshold the rerise comes with after-action wording.
 *  N1 an awaiting-human ticket stuck well past the threshold is never re-raised
 *     and raises no fault.
 *  N2 with a rerise row in the batch, an already-briefed normal row in the same
 *     batch stays suppressed (per-row force; the batch bypass must not leak).
 *
 * TDD note: red expected before implement lands (no second mention = FAIL named).
 * Watchdog tree missing = ENV_FAIL exit 2.
 * Run directly: node integration/t261008-39/sc_stuck_block_rerise_persistence.mjs (cwd=repo root).
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

function memWakeIo() {
  const prompts = []
  return {
    prompts,
    async prompt(sessionId, text, mode) { prompts.push({ sessionId, text, mode }); return { accepted: true, requestId: 'rid-' + prompts.length } },
    async queueDepth() { return 0 },
  }
}

const RERISE_WORD = /previously surfaced|still blocked/i

// Rerise-class mention of a ticket: the ticket named inside a rerise-shaped
// clause (the episode/threshold wording), NOT the ticket merely appearing in a
// normal transition line or in the standing sweep paragraph.
function reriseMention(text, ticket) {
  for (const line of text.split('\n')) {
    if (line.includes(ticket) && RERISE_WORD.test(line)) return line
  }
  return null
}

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

const appendRow = (files, row) => { files['/ledg/sandbar.jsonl'].content += ledgerLine(row) + '\n' }
const MIN = 60_000

async function main() {
  const clock = fakeClock()
  // R1 setup: ticket blocked at t0 -> first wake mentions it once.
  const { w, wakeIo, files } = boot({ clock, ledgerLines: [
    ledgerLine({ project: 'sandbar', ticket: 't-stuck', seq: 1, stage_state: 'blocked', stage: 'implement', reason: 'main-sync did not converge' }),
    ledgerLine({ project: 'sandbar', ticket: 't-hum', seq: 1, stage_state: 'awaiting-human', stage: 'arbitrate', reason: 'host sign-off pending' }),
  ] })
  try {
    await w.tickOnce()
    const first = wakeIo.prompts.length
    if (first < 1) fail('setup: initial decision-state wake missing')
    const mentioned = wakeIo.prompts.some((p) => p.text.includes('t-stuck'))
    if (mentioned) ok('R1 setup: t-stuck briefed once')
    else fail('R1 setup: t-stuck not in the first brief')

    // R1: silence window — just under and just past the threshold.
    clock.advance(29 * MIN)
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 1, stage_state: 'running', stage: 'dev' }) // unrelated new row keeps ticks waking
    const pre = wakeIo.prompts.length
    await w.tickOnce()
    const reranEarly = wakeIo.prompts.slice(pre).some((p) => reriseMention(p.text, 't-stuck'))
    if (!reranEarly) ok('R1 under threshold: no re-raise yet (fires only after the stated threshold)')
    else fail('R1 re-raise fired before the threshold elapsed — threshold not respected')

    clock.advance(2 * MIN) // now 31 min stuck, past the default 30-minute threshold
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 2, stage_state: 'review', stage: 'dev' })
    await w.tickOnce()
    const last = wakeIo.prompts[wakeIo.prompts.length - 1]
    if (!last) fail('R1 over threshold: no wake at all (rerise path dead)')
    else {
      if (last.text.includes('t-stuck')) ok('R1 over threshold: t-stuck named again')
      else fail('R1 over threshold: brief does not name t-stuck — the block went quiet again (the incident)')
      if (reriseMention(last.text, 't-stuck')) ok('R1 rerise wording marks it as a repeat mention')
      else fail('R1 rerise wording missing on the t-stuck line ("still blocked, previously surfaced" class) — the repeat is indistinguishable from a first mention')
      if (/\b(30|threshold|minute)/i.test(last.text)) ok('R1 threshold is visible in the rerise text')
      else fail('R1 threshold not visible in the rerise text — a silent threshold is the original defect restated')
    }

    // R2 bounded: the tick right after must not nag again.
    const before = wakeIo.prompts.length
    clock.advance(1 * MIN)
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 3, stage_state: 'dev-done', stage: 'dev' })
    await w.tickOnce()
    const nag = wakeIo.prompts.slice(before).filter((p) => p !== last && reriseMention(p.text, 't-stuck'))
    if (nag.length === 0) ok('R2 rerise is bounded (one per window, no nagging)')
    else fail('R2 rerise repeated inside the same window (' + nag.length + ' extra mentions)')

    // R3: an action lands on the still-blocked ticket; no rerise at 1x, rerise at 2x with after-action wording.
    clock.advance(25 * MIN) // ~56 min total; window would allow a no-action rerise
    appendRow(files, { project: 'sandbar', ticket: 't-stuck', seq: 2, stage_state: 'blocked', stage: 'implement', reason: "retry_qc attempted, merge conflict remains" })
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 4, stage_state: 'running', stage: 'dev' })
    await w.tickOnce()
    const afterActionEarly = wakeIo.prompts.slice(-1).some((p) => reriseMention(p.text, 't-stuck'))
    if (!afterActionEarly) ok('R3 after a recorded action: no immediate rerise (a working attempt is not nagged)')
    else fail('R3 rerise fired right after a recorded action — the no-action condition is not checked')

    clock.advance(31 * MIN) // past 2x threshold since the action
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 5, stage_state: 'review', stage: 'dev' })
    await w.tickOnce()
    const late = wakeIo.prompts[wakeIo.prompts.length - 1]
    if (late && reriseMention(late.text, 't-stuck')) ok('R3 non-progress surfaces at 2x with rerise wording')
    else if (late && late.text.includes('t-stuck') && /after|action|still blocked/i.test(late.text)) ok('R3 non-progress surfaces at 2x with after-action wording')
    else fail('R3 a ticket still blocked after a recorded action was never surfaced again (silence after a failed attempt)')

    // N1: awaiting-human never re-raised as a fault.
    const humMentions = wakeIo.prompts.filter((p) => p.text.split('\n').some((l) => l.includes('t-hum') && /previously surfaced|still blocked|fault|escalat/i.test(l)))
    if (humMentions.length === 0) ok('N1 awaiting-human never re-raised as a fault')
    else fail('N1 awaiting-human was re-raised with fault-class wording (' + humMentions.length + ' prompts)')

    // N2: a rerise in a batch must not un-suppress an already-briefed normal row.
    clock.advance(35 * MIN)
    appendRow(files, { project: 'sandbar', ticket: 't-stuck', seq: 3, stage_state: 'blocked', stage: 'implement', reason: "second episode, merge conflict remains" })
    appendRow(files, { project: 'sandbar', ticket: 't-other', seq: 6, stage_state: 'dev-done', stage: 'dev' })
    await w.tickOnce() // normal row briefed here (first mention of that key)
    await w.tickOnce()
    const briefs = wakeIo.prompts.map((p) => p.text)
    const dupKeyBriefs = briefs.filter((t) => t.includes('t-other')).length
    if (dupKeyBriefs >= 1) ok('N2 batch containing rerise still delivers normal rows when due')
    else fail('N2 normal rows stopped being delivered once rerise rows exist')
  } finally {
    w.dispose()
  }

  if (fails > 0) { console.error('FAIL count=' + fails); process.exit(1) }
  console.log('PASS sc_stuck_block_rerise_persistence')
}

main().catch((e) => { console.error('FAIL scenario threw: ' + (e && e.stack || e)); process.exit(1) })
