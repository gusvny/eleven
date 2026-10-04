/**
 * waiting-on-host face (t261004-08, pure core) — "the executor is waiting on the host"
 * becomes an observable state.
 *
 * Source-of-truth discipline (ticket ruling): dsh 0.1.5 exposes no pending-interaction
 * face on the Session API (the method list is only list/search/create/prompt/
 * updateQueue/cancel/control/page/follow), so this face uses the narrowest honest
 * substitute named by the ticket: the panel request ledger (unanswered rows) + the
 * session snapshot (t260929-08). "A session that is idle while an unanswered request
 * names it" is computable today.
 *
 * Three-valued predicate (review C3): missing snapshot (running unreadable / list
 * failure / session absent) = `unknown` — "not read" is never treated as "idle" (the
 * mirror-image failure the ticket bans: it must never read as normal). Only a readable
 * snapshot is judged: running=true = the session is working (`clear`, pending asks
 * still named in the reason); running=false with unanswered rows attributed to the
 * session = `waiting`.
 *
 * This face only observes (status key); it raises no alert — alerting goes through the
 * self_lock escalation path (same-ticket C1 ruling: one rule, one key). The threshold
 * lives on the alert side, not here: the face is always-on observation.
 */

import type { PendingInteraction } from './self-lock.ts'

export interface WaitingAsk {
  /** Request row id (routes alerts / the panel to the ask). */
  requestId: string
  /** Request kind (question/approval/…). */
  kind: string
  /** Raised-at from the ledger row (explicit null when absent). */
  raisedAt: number | null
}

export interface WaitingFace {
  state: 'clear' | 'waiting' | 'unknown'
  /** Unanswered asks attributed to this session (empty on unknown — nothing was read). */
  asks: WaitingAsk[]
  /** waiting onset = earliest own ask raisedAt; null otherwise. */
  sinceMs: number | null
  /** One machine-readable reason (always set on unknown; pending asks named on clear). */
  reason: string
}

export interface WaitingFaceInput {
  /** pendingProvider output; null = request ledger unreadable (explicit unknown). */
  pending: PendingInteraction[] | null
  /** Declared executor session id; '' = not declared/adopted — no attribution target, explicit unknown. */
  sessionId: string
  /** Session snapshot running bit; null = snapshot missing (explicit unknown, never read as idle). */
  running: boolean | null
  nowMs: number
}

export function detectWaitingFace(input: WaitingFaceInput): WaitingFace {
  const { pending, sessionId, running, nowMs } = input
  if (pending === null) {
    return { state: 'unknown', asks: [], sinceMs: null, reason: 'request ledger unreadable (pendingProvider unavailable) — waiting state is explicitly unknown, never normal' }
  }
  if (sessionId === '') {
    return { state: 'unknown', asks: [], sinceMs: null, reason: 'executor session id not declared/adopted — no attribution target to judge, explicitly unknown' }
  }
  if (running === null) {
    return { state: 'unknown', asks: [], sinceMs: null, reason: 'session snapshot missing (list failure / session absent) — "not read" is not "idle", explicitly unknown' }
  }
  const asks: WaitingAsk[] = pending
    .filter(p => p.raisedBy === sessionId)
    .map(p => ({
      requestId: p.target,
      kind: p.kind,
      raisedAt: typeof p.raisedAt === 'number' && Number.isFinite(p.raisedAt) ? p.raisedAt : null,
    }))
  // Unattributed rows (raised_by empty): never matched, but named explicitly — the
  // attribution gap stays visible, not silent.
  const unattributed = pending.filter(p => typeof p.raisedBy !== 'string' || p.raisedBy === '').length
  const unattrNote = unattributed > 0 ? `; ${unattributed} request(s) lack attribution (not matched, named explicitly)` : ''
  if (asks.length === 0) {
    return { state: 'clear', asks: [], sinceMs: null, reason: `no unanswered request attributed to this session${unattrNote}` }
  }
  if (running === true) {
    return {
      state: 'clear',
      asks,
      sinceMs: null,
      reason: `session running (running=true): ${asks.length} unanswered ask(s) present but not waiting${unattrNote}`,
    }
  }
  const raisedAts = asks.map(a => a.raisedAt).filter((t): t is number => t !== null)
  const since = raisedAts.length > 0 ? Math.min(...raisedAts) : null
  return {
    state: 'waiting',
    asks,
    sinceMs: since,
    reason: `session idle (running=false) with ${asks.length} unanswered ask(s) naming it (earliest ${since !== null ? new Date(since).toISOString() : 'timestamp missing'})${unattrNote}`,
  }
}
