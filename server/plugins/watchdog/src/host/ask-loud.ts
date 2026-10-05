/**
 * ask-loud.ts -- the watchdog judgement for the two silent delivery faces
 * (t261004-44; KI-196 / KI-197; pure cores).
 *
 * Two redlines (ticket C: a silent delivery face must be loud, the message names the
 * session and the face):
 *  - `ask_unmirrored`: a session sits on ask_user_question (a question-kind pending
 *    interaction from the pendingProvider) while no question row for that session
 *    appears in the ledger -- a bridge that does not fire finally has a voice.
 *    Deadline semantics: measured from when the watchdog FIRST observed the pending
 *    ask (with no raisedAt timestamp that is a lower bound of the age -- reporting
 *    late beats never reporting; a missing timestamp never means "never fire");
 *    the watch clears as soon as the row lands.
 *  - `deliver_refused`: a kind=deliver_refused row in the event ledger (a named
 *    deliver refusal) -- the refusal text survives intact into the alert detail, so
 *    "this face is dead" reaches the human, not just the caller.
 *
 * All judgement is pure; io (pending rows / ledger rows) is injected by core.ts.
 * Malformed input (missing fields, non-objects) is skipped with a named count --
 * never thrown, never faked into red or clear.
 */

/** Minimal observation face of an event-ledger row (real shape = ledger-tail's
 *  LedgerRow: known keys top-level, the rest verbatim under raw; both are read,
 *  top-level wins). */
export interface LedgerRowLike {
  kind?: unknown
  raised_by?: unknown
  session?: unknown
  error?: unknown
  at?: unknown
  seq?: unknown
  raw?: Record<string, unknown>
}

function fieldOf(row: LedgerRowLike, key: string): unknown {
  if (row[key] !== undefined) return row[key]
  const raw = row.raw
  return raw !== null && typeof raw === 'object' ? (raw as Record<string, unknown>)[key] : undefined
}

/** Minimal observation face of a pending interaction (pendingProvider row; raisedAt optional). */
export interface PendingAskLike {
  raisedBy?: unknown
  kind?: unknown
  raisedAt?: unknown
}

export type AskMirrorAction =
  | { action: 'raise'; sessionId: string; sinceMs: number; detail: string }
  | { action: 'watch'; sessionId: string; sinceMs: number }
  | { action: 'forget'; sessionId: string }
  | { action: 'none' }

/**
 * ask_unmirrored judgement (one session, one pending ask):
 *  - a question row for the session exists in the ledger (kind=question,
 *    raised_by=session) -> forget (the watch clears);
 *  - no row yet: first-seen = min(recorded firstSeen, the row's raisedAt); age >=
 *    deadline -> raise (names the session and the ask face); otherwise watch
 *    (record the first sighting, judge again next tick).
 * firstSeenMs undefined = first seen this tick -- start from the row's raisedAt when
 * present, else from now.
 */
export function judgeAskMirror(args: {
  pending: PendingAskLike
  ledgerRows: readonly LedgerRowLike[]
  firstSeenMs?: number
  deadlineMs: number
  nowMs: number
}): AskMirrorAction {
  const sid = typeof args.pending.raisedBy === 'string' ? args.pending.raisedBy : ''
  if (sid === '') return { action: 'none' } // no attribution = not judged (same reading as self-lock; never fakes red or clear)
  const mirrored = args.ledgerRows.some((r) =>
    r !== null && typeof r === 'object' && r.kind === 'question' && fieldOf(r, 'raised_by') === sid)
  if (mirrored) return { action: 'forget', sessionId: sid }
  const raisedAt = typeof args.pending.raisedAt === 'number' && Number.isFinite(args.pending.raisedAt)
    ? args.pending.raisedAt
    : null
  const since = Math.min(args.firstSeenMs ?? Number.POSITIVE_INFINITY, raisedAt ?? Number.POSITIVE_INFINITY)
  const sinceMs = Number.isFinite(since) ? since : args.nowMs
  const ageMs = args.nowMs - sinceMs
  if (ageMs >= args.deadlineMs) {
    return {
      action: 'raise',
      sessionId: sid,
      sinceMs,
      detail: `session ${sid} has a pending ask_user_question but no question row landed in the ledger within ${Math.round(args.deadlineMs / 1000)}s (observed since ${sinceMs}) — the question bridge did not fire (ask face, KI-196)`,
    }
  }
  return { action: 'watch', sessionId: sid, sinceMs }
}

/** Observation face of one deliver_refused row (malformed rows return via the
 *  malformed count -- named skip by the caller). */
export interface DeliverRefusalRow {
  sessionId: string
  detail: string
  at: number | null
}

/** Collect the deliver_refused rows from the event ledger (KI-197: the named refusal
 *  must survive all the way into the alert). */
export function collectDeliverRefusals(rows: readonly unknown[]): { refusals: DeliverRefusalRow[]; malformed: number } {
  const refusals: DeliverRefusalRow[] = []
  let malformed = 0
  for (const r of rows) {
    if (r === null || typeof r !== 'object' || (r as LedgerRowLike).kind !== 'deliver_refused') continue
    const row = r as LedgerRowLike
    const sess = fieldOf(row, 'session')
    const sid = typeof sess === 'string' ? sess : ''
    if (sid === '') { malformed += 1; continue } // an unattributed refusal row never fakes an alert target
    const err = fieldOf(row, 'error')
    refusals.push({
      sessionId: sid,
      detail: `delivery face refused for session ${sid}: ${typeof err === 'string' ? err : 'refusal detail unreadable (row malformed)'}`,
      at: typeof fieldOf(row, 'at') === 'number' ? (fieldOf(row, 'at') as number) : null,
    })
  }
  return { refusals, malformed }
}
