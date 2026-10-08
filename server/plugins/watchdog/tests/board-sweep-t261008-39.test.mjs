// t261008-39 UT: standing board sweep + bounded dispositions + persistent re-raise.
// Covers: classifyDisposition truth table (all 32 boolean fact combos + malformed),
// collectStuckRerises (threshold boundary, no-action vs after-action regimes,
// awaiting-human negative, acted-in-window negative WITH a rerise row in the batch,
// stuck→unstuck→stuck episode rotation, restart no-fake-\"previously\", no-ledger-write
// lock, per-row force scoping [R2]), buildBrief standing instruction (zero rows and
// with rows), and the L3 two-ticket fixture on one wake. All io in-memory stubs.
import { Watchdog } from '../src/host/core.ts'
import { classifyDisposition, collectStuckRerises, freshSweepMemory, isReriseRow, makeReriseRow, factsAreReadable } from '../src/host/board-sweep.ts'
import { buildBrief, freshWakeMemory, wakeExecutor } from '../src/host/exits.ts'
import { memTailIo, memCoreIo, fakeClock, assert, done } from './lib.mjs'

let n = 0
const BASE = 1_700_000_000_000
const MIN = 60_000
const row = (over = {}) => ({ idem: `r${Math.random()}`, project: 'sandbar', ticket: 't1', seq: 0, stage: 'implement', stage_state: 'running', at: BASE, raw: {}, ...over })

// ---- ① disposition truth table: exhaustive over the boolean fact space + malformed ----
{
  let combos = 0
  for (let mask = 0; mask < 32; mask++) {
    const f = {
      readingsOk: true,
      mergeHeadPresent: !!(mask & 1),
      unmergedCount: (mask & 2) ? 2 : 0,
      worktreeDirty: !!(mask & 4),
      conflictMarkers: !!(mask & 8),
      mainIsAncestor: !(mask & 16),
    }
    const d = classifyDisposition(f)
    combos++
    const clean = !f.mergeHeadPresent && f.unmergedCount === 0 && !f.worktreeDirty && !f.conflictMarkers && f.mainIsAncestor
    if (clean) {
      assert(d.action === 'retry_qc', `combo ${mask} (clean stale face) -> retry_qc`)
    } else if (f.unmergedCount > 0 || f.conflictMarkers || f.worktreeDirty || !f.mainIsAncestor) {
      assert(d.action === 'rework' && d.requirement.length > 0, `combo ${mask} (unresolved face) -> rework with a named requirement`)
    } else {
      // MERGE_HEAD still present with an otherwise clean face = mid-merge -> file_request
      assert(d.action === 'file_request', `combo ${mask} (mid-merge) -> file_request`)
    }
  }
  assert(combos === 32, 'all 32 boolean fact combinations classified, exactly one disposition each')
  // malformed readings: fail-closed to file_request, never (a)/(b)
  for (const bad of [
    { readingsOk: false, mergeHeadPresent: false, unmergedCount: 0, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: -1, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: 1.5, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    { readingsOk: true, mergeHeadPresent: false, unmergedCount: '0', worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true },
    null,
  ]) {
    assert(classifyDisposition(bad).action === 'file_request', 'malformed/failed readings fail closed to file_request')
  }
  assert(factsAreReadable({ readingsOk: true, mergeHeadPresent: false, unmergedCount: 0, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true }), 'factsAreReadable accepts a well-formed fact set')
  n += 38
}

// ---- ② rerise tracker: threshold, regimes, exclusions, bounding ----
{
  const blocked = (tid, at, stage = 'implement') => row({ ticket: tid, stage, stage_state: 'blocked', at })
  const mem = freshSweepMemory()

  // no-action regime: fires only at/after the threshold
  let r = collectStuckRerises([blocked('tA', BASE)], mem, BASE + 29 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 0 && r.stuck.length === 1, '29 min < threshold 30: stuck is listed but not rerisen')
  r = collectStuckRerises([blocked('tA', BASE)], mem, BASE + 30 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 1 && r.reriseRows[0].ticket === 'sweep-rerise:tA:ep1', 'at exactly the threshold the rerise fires (episode 1)')
  assert(isReriseRow(r.reriseRows[0]), 'the synthetic row carries the explicit raw.rerise marker')
  assert(/no recorded action for 30 min/.test(r.reriseRows[0].reason) && /threshold 30 min/.test(r.reriseRows[0].reason), 'the reason names the age AND the threshold (never silent)')
  // throttle: one per window
  r = collectStuckRerises([blocked('tA', BASE)], mem, BASE + 31 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 0 && r.stuck.length === 1, 'within the same window the rerise is throttled (still listed as stuck)')
  // next window: a new episode fires again
  r = collectStuckRerises([blocked('tA', BASE)], mem, BASE + 61 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 1 && r.reriseRows[0].ticket === 'sweep-rerise:tA:ep2', 'after a full window a new episode rerises (ep2)')
  n += 6

  // awaiting-human: never collected, never rerisen
  const mem2 = freshSweepMemory()
  r = collectStuckRerises([row({ ticket: 'tB', stage_state: 'awaiting-human', at: BASE - 10 * MIN })], mem2, BASE + 90 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 0 && r.stuck.length === 0, 'awaiting-human is a queue, NOT a fault: never rerisen')
  // refused counts as a fault state
  r = collectStuckRerises([row({ ticket: 'tC', stage_state: 'refused', at: BASE })], mem2, BASE + 30 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 1, 'refused stuck past the threshold rerises like blocked')
  n += 2

  // after-action regime: recorded action while still blocked -> 2x threshold, named reason
  const mem3 = freshSweepMemory()
  const acted = [blocked('tD', BASE), row({ ticket: 'tD', stage: 'implement', stage_state: 'running', at: BASE + 5 * MIN }), blocked('tD', BASE + 6 * MIN)]
  r = collectStuckRerises(acted, mem3, BASE + 30 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 0 && r.stuck[0].action === 'after_action', 'an action recorded inside the stuck streak holds the rerise past 1x threshold')
  r = collectStuckRerises(acted, mem3, BASE + 60 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 1 && /after recorded action/.test(r.reriseRows[0].reason), 'still blocked at 2x threshold with a recorded action: rerisen with the after-action wording')
  n += 2

  // unstuck clears the tracker (episode keys pruned, no unbounded growth)
  const mem4 = freshSweepMemory()
  collectStuckRerises([blocked('tE', BASE)], mem4, BASE + 30 * MIN, 30, 'sandbar')
  collectStuckRerises([blocked('tE', BASE), row({ ticket: 'tE', stage_state: 'running', at: BASE + 31 * MIN })], mem4, BASE + 40 * MIN, 30, 'sandbar')
  assert(!mem4.rerisen.has('tE'), 'unstuck: the tracker entry (and its episode key) is pruned')
  // stuck -> unstuck -> stuck again: a fresh episode, it rerises again
  const mem5 = freshSweepMemory()
  collectStuckRerises([blocked('tF', BASE)], mem5, BASE + 30 * MIN, 30, 'sandbar')
  const r5 = collectStuckRerises([blocked('tF', BASE), row({ ticket: 'tF', stage_state: 'running', at: BASE + 31 * MIN }), row({ ticket: 'tF', stage_state: 'blocked', at: BASE + 40 * MIN })], mem5, BASE + 70 * MIN, 30, 'sandbar')
  assert(r5.reriseRows.length === 1 && /:ep2$/.test(r5.reriseRows[0].ticket), 're-stuck after unstuck starts a fresh episode and rerises again')
  n += 2

  // rows without at: first-sighting lower bound (delayed, never faked)
  const mem6 = freshSweepMemory()
  r = collectStuckRerises([row({ ticket: 'tG', stage_state: 'blocked', at: undefined })], mem6, BASE + 5 * MIN, 30, 'sandbar')
  assert(r.reriseRows.length === 0, 'a row without at ages from first sighting (no fake age)')
  n += 1

  // malformed row (no ticket) counted, not silent
  const mem7 = freshSweepMemory()
  r = collectStuckRerises([row({ ticket: undefined })], mem7, BASE, 30, 'sandbar')
  assert(r.malformed === 1, 'a ledger row without a ticket is a counted, named skip')
  n += 1
}

// ---- ③ per-row force scoping [R2]: rerise row does not un-suppress normal dedupe ----
{
  const mem = freshWakeMemory()
  const normal = row({ ticket: 'tN', stage: 'implement', stage_state: 'running' })
  const rerise = makeReriseRow('sandbar', { ticket: 'tS', stageKey: 'implement|blocked', firstSeenAt: BASE, actionAt: null }, 1, BASE, 30)
  const io = { async prompt(sid, text, mode) { return { accepted: true, requestId: 'rid1' } }, async queueDepth() { return 0 } }
  // first wake briefs the normal row
  const w1 = await wakeExecutor(io, 'sandbar', 'sb', [normal], null, 'info', mem)
  assert(w1.woke, 'first wake delivers the normal row')
  // second wake: same normal row (already briefed) + a rerise row in the SAME batch
  const prompts2 = []
  const io2 = { async prompt(sid, text, mode) { prompts2.push(text); return { accepted: true, requestId: 'rid2' } }, async queueDepth() { return 0 } }
  const w2 = await wakeExecutor(io2, 'sandbar', 'sb', [normal, rerise], null, 'info', mem, [rerise], 30)
  assert(w2.woke && prompts2.length === 1, 'a rerise row in the batch still wakes')
  assert(prompts2[0].includes('[re-raise] tS'), 'the brief names the rerisen ticket')
  assert(!prompts2[0].includes('tN implement→running（') || prompts2[0].indexOf('tN implement→running') === -1, 'the already-briefed normal row is NOT re-briefed (dedupe held WITH a rerise row present)')
  assert(!/tN/.test(prompts2[0]), 'the briefed ticket does not appear in the rerise brief at all')
  n += 4
}

// ---- ④ standing sweep instruction in every brief + L3 fixture on one wake ----
{
  const b0 = buildBrief('sandbar', [], null)
  assert(b0.includes('BOARD SWEEP') && b0.includes('blocked / refused / awaiting-human'), 'empty-row brief still carries the standing sweep instruction')
  assert(b0.includes('re-raise threshold') && b0.includes('30'), 'the brief echoes the threshold in plain text (never silent)')
  assert(b0.includes('retry_qc') && b0.includes('rework(to_stage=implement)'), 'the brief names the bounded disposition vocabulary')
  assert(b0.includes('MERGE_HEAD') && b0.includes('main is an ancestor of the lane HEAD'), 'the brief demands all five readings per ticket')
  assert(b0.includes('awaiting-human is a queue, not a fault'), 'the brief pins awaiting-human as queue-not-fault')
  const b1 = buildBrief('sandbar', [row({ ticket: 'tZ', stage: 'merge_check', stage_state: 'blocked' })], null)
  assert(b1.includes('BOARD SWEEP') && b1.includes('tZ merge_check→blocked'), 'brief with transitions carries BOTH the instruction and the rows')
  n += 6

  // L3 fixture: one stale-blocked ticket + one genuinely unresolved ticket, one wake
  const stale = classifyDisposition({ readingsOk: true, mergeHeadPresent: false, unmergedCount: 0, worktreeDirty: false, conflictMarkers: false, mainIsAncestor: true })
  const unresolved = classifyDisposition({ readingsOk: true, mergeHeadPresent: false, unmergedCount: 3, worktreeDirty: true, conflictMarkers: true, mainIsAncestor: false })
  assert(stale.action === 'retry_qc', 'L3: the stale-blocked fixture classifies to retry_qc')
  assert(unresolved.action === 'rework' && /unmerged/.test(unresolved.requirement), 'L3: the unresolved fixture classifies to rework with a named requirement')
  const rr = [
    makeReriseRow('sandbar', { ticket: 't-stale', stageKey: 'implement|blocked', firstSeenAt: BASE, actionAt: null }, 1, BASE, 30),
    makeReriseRow('sandbar', { ticket: 't-unresolved', stageKey: 'merge_check|blocked', firstSeenAt: BASE, actionAt: BASE + MIN }, 1, BASE, 30),
  ]
  const brief = buildBrief('sandbar', [], null, rr, 30)
  assert(brief.includes('t-stale') && brief.includes('t-unresolved'), 'L3: one brief names BOTH stuck tickets')
  assert(brief.includes('no recorded action') && brief.includes('after recorded action'), 'L3: the two stuck tickets carry their two different regimes')
  n += 4
}

// ---- ⑤ no-ledger-write lock (source-level) + end-to-end tick with a rerise wake ----
{
  const { readFileSync } = await import('node:fs')
  const sweepSrc = readFileSync(new URL('../src/host/board-sweep.ts', import.meta.url), 'utf8')
  assert(!/appendFile|writeFileSync|appendAlerts/.test(sweepSrc), 'source lock: the sweep core never writes any ledger/alert face')
  const exitsSrc = readFileSync(new URL('../src/host/exits.ts', import.meta.url), 'utf8')
  assert(exitsSrc.includes('isReriseRow(r) && !isReriseRow(r)') || exitsSrc.includes('!isReriseRow(r)'), 'source lock: the batch bypass excludes rerise rows (R2)')
  n += 2

  // end-to-end: a blocked ticket older than the threshold wakes through the real tick
  const clock = fakeClock(BASE)
  const CFG = { declared: true, enabled: true, config_error: null, provenance: { file: 'mem', keys: {} } }
  const resolved = { ...CFG, config: { enabled: true, executor_session: 'sb', stall_minutes: 15, long_turn_minutes: 45, blocked_rerise_minutes: 30, reconcile_seconds: 5, waiting_minutes: 5, prose_backstop: { enabled: false, idle_minutes: 10 }, self_heal: { enabled: false, park_minutes: 60 }, one_shot: { enabled: false, retention_days: 7, lock_timeout_ms: 1 }, ask_mirror_deadline_s: 120, alerts: { enabled: true, sound: true, desktop: true, night: { start: '23:00', end: '07:30', policy: 'redline-only' }, redline: [], keep_days: 14 } } }
  const core = memCoreIo()
  const prompts = []
  const w = new Watchdog('sandbar', {
    configLoader: () => resolved,
    io: { tail: memTailIo({}), heartbeat: core.heartbeat, appendAlerts: core.appendAlerts, listAlerts: core.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    wakeIo: {
      async prompt(sid, text, mode) { prompts.push(text); return { accepted: true, requestId: `rid-${prompts.length}` } },
      async queueDepth() { return 0 },
    },
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata', ledgerDir: '/ledg',
  })
  // seed the rolling ledger directly with a stuck blocked row, then advance past the threshold
  w['ledgerRows'].push(row({ ticket: 't22', stage: 'implement', stage_state: 'blocked', at: BASE }))
  clock.set(BASE + 31 * MIN)
  await w.tickOnce()
  assert(prompts.length === 1, 'one tick past the threshold produces exactly one wake')
  assert(prompts[0].includes('[re-raise] t22') && prompts[0].includes('no recorded action for 31 min'), 'the wake names the stuck ticket with its age and the threshold')
  assert(prompts[0].includes('BOARD SWEEP'), 'the wake brief carries the standing sweep instruction')
  const st = w.status()
  assert(st.sweep_rerise.threshold_minutes === 30 && st.sweep_rerise.rerised === 1, 'the status face exposes the threshold and the rerise count')
  assert(st.sweep_rerise.stuck.length === 1 && st.sweep_rerise.stuck[0].ticket === 't22', 'the status face lists the stuck ticket')
  // guard ③ suppression: the stuck ticket stays visible on the status face
  const core2 = memCoreIo()
  const prompts2 = []
  const w2 = new Watchdog('sandbar', {
    configLoader: () => resolved,
    io: { tail: memTailIo({}), heartbeat: core2.heartbeat, appendAlerts: core2.appendAlerts, listAlerts: core2.listAlerts },
    boardReader: async () => ({ ok: true, rows: [] }),
    wakeIo: {
      async prompt(sid, text, mode) { prompts2.push(text); return { accepted: true, requestId: `rid-${prompts2.length}` } },
      queueDepth: async () => 3, // an undigested brief sits in the queue
    },
    pendingProvider: async () => ({ available: true, pending: [] }),
    sessionStat: async () => ({ advanced: false, mtimeMs: clock.now(), running: false }),
    now: clock.now,
    dataDir: '/memdata', ledgerDir: '/ledg',
  })
  w2['ledgerRows'].push(row({ ticket: 't22', stage: 'implement', stage_state: 'blocked', at: BASE }))
  await w2.tickOnce()
  const st2 = w2.status()
  assert(prompts2.length === 0, 'guard ③: the rerise wake is suppressed while a brief sits undigested')
  assert(st2.sweep_rerise.suppressed === true && st2.sweep_rerise.stuck.length === 1 && /suppressed/.test(st2.sweep_rerise.reason), 'suppressed rerise stays visible on the status face with a named reason (review note 2)')
  assert(st2.sweep_rerise.stuck[0].ticket === 't22' && st2.sweep_rerise.threshold_minutes === 30, 'the stuck ticket and threshold are readable even while suppressed')
  w.dispose(); w2.dispose(); n += 6
}

done(n)
