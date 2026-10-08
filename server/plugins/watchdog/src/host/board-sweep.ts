/**
 * Board sweep pure core (t261008-39, host order 261008) — the decision core for
 * "standing sweep instruction + bounded disposition vocabulary + persistent re-raise
 * for long-stuck blocks". Zero io, zero delivery (delivery stays on the existing
 * single wakeExecutor channel in exits.ts).
 *
 * Three responsibilities:
 *  - classifyDisposition: from the executor's measured disk facts derive EXACTLY ONE
 *    bounded disposition (retry_qc / rework(to_stage=implement) / file_request),
 *    exhaustive and mutually exclusive, fail-closed (unreadable facts never reach
 *    the executable exits);
 *  - collectStuckRerises: derive from the rolling ledger the tickets stuck in
 *    blocked/refused past the threshold with no recorded action, and emit synthetic
 *    re-raise rows (t261004-29 synthetic-row shape: wake inputs only, NEVER written
 *    to any real ledger); awaiting-human is a queue, not a fault — never collected;
 *  - isReriseRow: strict recognition of the synthetic rows (the explicit raw.rerise
 *    marker only; never derived from stage_state — any row can be blocked).
 *
 * Time semantics (self-declared): a ledger row may lack `at` — such a row ages from
 * the tick's now (first-sighting semantics, same as the ask-mirror watch): a restart
 * can only DELAY a re-raise, never fabricate stuck age.
 */

import type { LedgerRow } from './ledger-tail.ts'

// ---------- disposition vocabulary (exhaustive x mutually exclusive) ----------

/** The executor's measured disk facts (all five readings succeeded = readingsOk). */
export interface DiskFacts {
  /** Whether all five readings (MERGE_HEAD / unmerged count / dirty worktree /
   *  conflict markers / main-is-ancestor) were taken successfully. */
  readingsOk: boolean
  mergeHeadPresent: boolean
  unmergedCount: number
  worktreeDirty: boolean
  conflictMarkers: boolean
  mainIsAncestor: boolean
}

/** The bounded disposition vocabulary: exactly three exits, one conclusion per ticket. */
export type Disposition =
  | { action: 'retry_qc'; why: 'stale block: the disk face is clean and main is an ancestor of the lane HEAD' }
  | { action: 'rework'; requirement: string; why: 'genuinely unresolved: the disk face disagrees with the settled verdict' }
  | { action: 'file_request'; blocker: string; missing: string; default_action: string; why: 'cannot act: readings failed or the facts fit no executable exit' }

function isNonNegativeInt(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0
}

/** Fact-shape check (malformed input fails closed: any missing / non-numeric /
 *  negative field counts as a failed reading). */
export function factsAreReadable(f: DiskFacts): boolean {
  if (typeof f !== 'object' || f === null) return false
  if (typeof f.readingsOk !== 'boolean' || typeof f.mergeHeadPresent !== 'boolean' ||
    typeof f.worktreeDirty !== 'boolean' || typeof f.conflictMarkers !== 'boolean' ||
    typeof f.mainIsAncestor !== 'boolean') return false
  return isNonNegativeInt(f.unmergedCount)
}

/**
 * Disposition decision (a single decision ladder; exhaustive over the 32 boolean
 * fact combinations + malformed inputs; mutual exclusivity is test-pinned):
 *  - unreadable readings -> (c) file_request (names what is missing + a default action);
 *  - clean stale face (MERGE_HEAD absent, zero unmerged entries, clean worktree, no
 *    markers, main is an ancestor) -> (a) retry_qc;
 *  - any disk fact contradicting "settled" -> (b) rework(to_stage=implement), each
 *    with its own named requirement;
 *  - readable facts that fit neither (a) nor (b) (defensive arm, unreachable under
 *    the current vocabulary) -> (c).
 */
export function classifyDisposition(f: DiskFacts): Disposition {
  if (!factsAreReadable(f) || f.readingsOk === false) {
    return {
      action: 'file_request',
      blocker: 'the disk readings could not be taken (missing/malformed facts or a failed git probe)',
      missing: 'a readable lane repo face: MERGE_HEAD presence, unmerged entry count, worktree dirty state, conflict-marker residue, main-is-ancestor',
      default_action: 'retry_qc once the lane repo is readable again (the block may be stale)',
      why: 'cannot act: readings failed or the facts fit no executable exit',
    }
  }
  if (f.unmergedCount > 0) {
    return { action: 'rework', requirement: `resolve ${f.unmergedCount} unmerged index entr${f.unmergedCount === 1 ? 'y' : 'ies'}`, why: 'genuinely unresolved: the disk face disagrees with the settled verdict' }
  }
  if (f.conflictMarkers) {
    return { action: 'rework', requirement: 'remove the leftover conflict markers from the lane face', why: 'genuinely unresolved: the disk face disagrees with the settled verdict' }
  }
  if (f.worktreeDirty) {
    return { action: 'rework', requirement: 'commit or stash the dirty worktree state inside the lane (or name it on the ticket)', why: 'genuinely unresolved: the disk face disagrees with the settled verdict' }
  }
  if (!f.mainIsAncestor) {
    return { action: 'rework', requirement: 're-run the main sync so main becomes an ancestor of the lane HEAD', why: 'genuinely unresolved: the disk face disagrees with the settled verdict' }
  }
  if (!f.mergeHeadPresent) {
    return { action: 'retry_qc', why: 'stale block: the disk face is clean and main is an ancestor of the lane HEAD' }
  }
  // Defensive arm: MERGE_HEAD still present = the lane sits mid-merge; neither (a)'s
  // premise nor (b)'s remedy fits (a mid-merge goes through the operator reset, not
  // an implement rework) — hand it to a human via (c).
  return {
    action: 'file_request',
    blocker: 'MERGE_HEAD is still present: the lane sits mid-merge with a clean face',
    missing: 'an operator-side merge reset (git merge --abort on the operator entry) or a settle re-run grant',
    default_action: 'retry_qc after the operator resets the mid-merge state',
    why: 'cannot act: readings failed or the facts fit no executable exit',
  }
}

// ---------- synthetic-row recognition (strict: the explicit marker only) ----------

/** Strict recognition of a re-raise synthetic row — the explicit raw.rerise === true
 *  marker only; NEVER derived from stage_state (any real ledger row can be blocked;
 *  deriving it would dismantle the self-feed dedupe wholesale). */
export function isReriseRow(row: LedgerRow): boolean {
  return row.raw?.rerise === true
}

// ---------- persistent re-raise for long-stuck blocks ----------

/** Sweep memory (in-memory; lost on restart — first-sighting semantics: a restart
 *  only delays a re-raise, never fakes one). */
export interface SweepMemory {
  /** ticket -> the latest re-raise {at, episode}. The entry is deleted when the
   *  ticket unsticks (synthetic episode keys never accumulate unbounded). */
  rerisen: Map<string, { at: number; episode: number }>
}

export function freshSweepMemory(): SweepMemory {
  return { rerisen: new Map() }
}

const RERISE_STATES = new Set(['blocked', 'refused'])

interface StuckEntry {
  ticket: string
  stageKey: string
  /** Start of the stuck streak (the `at` of the streak's first same-key decision
   *  row; rows without `at` use the tick's now as a lower bound). */
  firstSeenAt: number
  /** Timestamp of a later ledger action on this ticket inside the streak
   *  (null = no recorded action). */
  actionAt: number | null
}

/** Per-ticket derivation (pure): the LATEST ledger row decides the current state —
 *  a ticket counts as stuck only while its last row is blocked/refused (a later
 *  running/unstuck row ends the streak); a stage-key change restarts the streak;
 *  any later non-decision row inside the streak counts as a recorded action (the
 *  ledger has no actor field — verified t260929-04 — so ticket + recency is the
 *  strongest attribution signal, and it errs conservative: fewer, later re-raises).
 *  awaiting-human clears the streak outright. */
function latestStuck(ticket: string, rows: LedgerRow[], nowMs: number): StuckEntry | null {
  let cur: StuckEntry | null = null
  let lastState: string | undefined = undefined
  for (const row of rows) {
    const state = row.stage_state
    lastState = state
    if (state !== undefined && RERISE_STATES.has(state)) {
      const key = `${row.stage ?? ''}|${state}`
      if (cur === null || cur.stageKey !== key) {
        cur = { ticket, stageKey: key, firstSeenAt: row.at ?? nowMs, actionAt: null }
      }
    } else if (cur !== null) {
      if (state !== undefined && state === 'awaiting-human') {
        // A queue state is neither a fault nor an "action": clear the streak.
        cur = null
      } else {
        cur.actionAt = row.at ?? nowMs
      }
    }
  }
  // The last row already left blocked/refused (running / unstuck / terminal) — the
  // ticket is not stuck now, so it is not a re-raise candidate.
  if (lastState === undefined || !RERISE_STATES.has(lastState)) return null
  return cur
}

/** A synthetic re-raise row (t261004-29 row shape; the raw.rerise marker lives only
 *  in in-memory wake inputs, never in any persisted ledger row). */
export function makeReriseRow(
  project: string, e: StuckEntry, episode: number, nowMs: number, thresholdMinutes: number,
): LedgerRow {
  const ageMin = Math.max(0, Math.round((nowMs - e.firstSeenAt) / 60_000))
  const actionClause = e.actionAt !== null
    ? `still blocked after recorded action at ${new Date(e.actionAt).toISOString()}`
    : `still blocked, previously surfaced; no recorded action for ${ageMin} min`
  return {
    idem: `sweep-rerise:${e.ticket}:ep${episode}`,
    project,
    ticket: `sweep-rerise:${e.ticket}:ep${episode}`,
    seq: 0,
    stage: 'sweep-rerise',
    stage_state: e.stageKey.split('|')[1] ?? 'blocked',
    reason: `${actionClause} (threshold ${thresholdMinutes} min; re-surfaced by the standing board sweep)`,
    at: nowMs,
    raw: { rerise: true, real_ticket: e.ticket, first_seen_at: e.firstSeenAt, action_at: e.actionAt, episode },
  }
}

/**
 * Collect this tick's due re-raise rows (pure; mem records only the throttle and
 * the episode). Rules:
 *  - collect only tickets whose latest row is blocked/refused; awaiting-human is
 *    never collected (a queue, not a fault);
 *  - no recorded action: fires at >= threshold; an action recorded while still
 *    stuck: fires at 2x threshold (never punishes an attempt, but long-running
 *    non-progress still reaches the table), with its own reason wording;
 *  - throttled: at most one row per ticket per threshold window (lastReriseAt);
 *    the episode increments per rerise; the entry (and its episode key) is pruned
 *    when the ticket unsticks;
 *  - malformed rows (no ticket) are counted into the returned malformed count —
 *    a named skip, never silent.
 */
export function collectStuckRerises(
  ledgerRows: LedgerRow[], mem: SweepMemory, nowMs: number,
  thresholdMinutes: number, project: string,
): { reriseRows: LedgerRow[]; stuck: Array<{ ticket: string; since: number; minutes: number; episode: number; action: 'none' | 'after_action' }>; malformed: number } {
  const byTicket = new Map<string, LedgerRow[]>()
  let malformed = 0
  for (const row of ledgerRows) {
    if (!row.ticket) { malformed += 1; continue }
    const list = byTicket.get(row.ticket) ?? []
    list.push(row)
    byTicket.set(row.ticket, list)
  }
  const thresholdMs = thresholdMinutes * 60_000
  const stuck: Array<{ ticket: string; since: number; minutes: number; episode: number; action: 'none' | 'after_action' }> = []
  const reriseRows: LedgerRow[] = []
  for (const [ticket, rows] of byTicket) {
    const e = latestStuck(ticket, rows, nowMs)
    if (e === null) {
      mem.rerisen.delete(ticket) // unstuck: the tracker entry (and its episode key) is pruned
      continue
    }
    const need = e.actionAt !== null ? 2 * thresholdMs : thresholdMs
    const age = nowMs - e.firstSeenAt
    const prev = mem.rerisen.get(ticket)
    const episode = (prev?.episode ?? 0)
    stuck.push({ ticket, since: e.firstSeenAt, minutes: Math.floor(age / 60_000), episode, action: e.actionAt !== null ? 'after_action' : 'none' })
    if (age < need) continue
    if (prev !== undefined && nowMs - prev.at < thresholdMs) continue // throttle: one per window
    const newEpisode = episode + 1
    reriseRows.push(makeReriseRow(project, e, newEpisode, nowMs, thresholdMinutes))
    mem.rerisen.set(ticket, { at: nowMs, episode: newEpisode })
  }
  return { reriseRows, stuck, malformed }
}

/** The standing sweep paragraph and its threshold, carried by EVERY brief (English
 *  STE; engine-vocabulary tokens verbatim). Exported: the test pins the wording and
 *  core.ts reuses the anchors — the threshold is never silent. */
export const SWEEP_INSTRUCTION_ANCHOR = 'BOARD SWEEP'
export const SWEEP_THRESHOLD_ANCHOR = 're-raise threshold'

export function sweepInstruction(thresholdMinutes: number): string {
  return [
    `[${SWEEP_INSTRUCTION_ANCHOR} — standing order] On wake, sweep the whole board: list every ticket of this project in a decision state (blocked / refused / awaiting-human).`,
    'For each blocked / refused ticket, read the disk truth FIRST, then return exactly one bounded disposition per ticket, carrying all five measured readings (MERGE_HEAD present/absent, unmerged entry count, worktree dirty state, conflict-marker residue, whether main is an ancestor of the lane HEAD). A conclusion without those readings is not a sweep.',
    'Disposition vocabulary (exhaustive, mutually exclusive): (a) stale block (clean disk face, main is an ancestor) -> retry_qc; (b) genuinely unresolved (unmerged entries, or a dirty worktree, or conflict markers, or main is not an ancestor) -> rework(to_stage=implement) with a named requirement; (c) you cannot act (readings failed or the facts fit no exit) -> file a request naming the blocker, the missing grant/authorisation, and a default action.',
    'awaiting-human is a queue, not a fault: list it, never re-drive it, never raise it as a fault.',
    `[${SWEEP_THRESHOLD_ANCHOR}] A ticket stuck in blocked / refused for more than ${thresholdMinutes} minutes with no recorded action is re-surfaced by the watchdog on later wakes (still blocked, previously surfaced) — one brief does not let it go quiet.`,
  ].join('\n')
}
