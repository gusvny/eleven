/**
 * Self-heal decision core (t261005-02, pure) — the bounded un-park path for a session
 * parked on an unanswered ask (KI-196/197 live evidence: a turn can sit forever on an
 * ask nobody answers; nothing cancelled it and nothing reported it).
 *
 * The ticket fixes the fire condition as exactly three guards, ALL required (fail
 * closed — any unreadable input holds, never fires):
 *   (a) an unanswered ask attributed to the session (waiting face) or a pending
 *       question marker (prose-backstop row);
 *   (b) silence above the declared threshold (self_heal.park_minutes);
 *   (c) our own wake briefing still unconsumed in the session's queue — the parked
 *       turn never drained it. Mirror unreadable (null) = hold: a no-signal read is
 *       never treated as "consumed" nor as "pending".
 *
 * Bounded: one attempt per park. The park key is `sessionId + ':' + askId`; a NEW ask
 * id re-arms exactly one fresh attempt (a new park is a new situation), the same ask
 * never fires twice. Attempt state lives in memory on the Watchdog instance (declared
 * in the receipt as `attempt: N`); a console restart re-arms one attempt — guards
 * (a)+(b)+(c) still all have to hold again, and the receipt answers "was this the
 * first attempt" from that counter.
 *
 * "Never on a healthy long turn" is enforced at two layers: the parse-time cross-knob
 * guard in config.ts (park_minutes > long_turn_minutes, config_error otherwise), and
 * guard (a) here — a healthy long turn has no unanswered ask attributed to it.
 *
 * This module only decides and shapes the receipt; the cancel call, the briefing
 * delivery, the alert row and the status key live in core.ts / node.ts / exits.ts.
 */

import { createHash } from 'node:crypto'

export interface SelfHealAsk {
  /** Request row id of the unanswered ask (waiting-face output). */
  requestId: string
  /** Raised-at from the ledger row (null when the row lacks a readable at). */
  raisedAt: number | null
  /** Whether the ask row declares an acceptable default (KI-198 family read-only
   *  observation; null = the row does not expose the bit — named, never guessed). */
  hasDefault: boolean | null
}

export interface SelfHealInput {
  /** Declared executor session id; '' = no attribution target, hold. */
  sessionId: string
  /** Unanswered asks attributed to this session (waiting face asks + default bit). */
  asks: SelfHealAsk[]
  /** A pending question marker without a ledger row (prose backstop), if any.
   *  requestId = the filed row id, or null when only the marker sentence exists. */
  questionMarker: { requestId: string | null; sentence: string } | null
  /** Silence clock: nowMs - lastProgressAt; null = no progress baseline ever (hold —
   *  the threshold has nothing to be measured against, never fire blind). */
  silenceMs: number | null
  /** Our latest briefing still unconsumed in the session queue (mirror read);
   *  null = mirror unreadable (hold, named). */
  ourBriefPending: boolean | null
  cfg: { enabled: boolean; parkMinutes: number }
  /** Attempt counts per park key already consumed this process (memory truth). */
  attempts: Map<string, number>
  nowMs: number
}

export interface SelfHealReceipt {
  at: number
  session_id: string
  ask_id: string
  /** Where the parked ask was seen: a ledger request row or a prose marker. */
  ask_source: 'ledger-ask' | 'prose-marker'
  /** Read-only observation for requirement (3): does the parked ask carry a default
   *  an absent host could accept? null = the row does not expose the bit. */
  ask_has_default: boolean | null
  threshold_minutes: number
  silence_minutes: number
  /** 1-based: how many times this park key has fired (restart re-arms, see header). */
  attempt: number
  /** Session running bit at decision time (observation only, not a guard). */
  session_running: boolean | null
}

export type SelfHealVerdict =
  | { action: 'hold'; reason: string; receipt: null }
  | { action: 'cancel'; reason: string; receipt: SelfHealReceipt }

/** Park key: one attempt per (session, ask instance). */
export function selfHealParkKey(sessionId: string, askId: string): string {
  return `${sessionId}:${askId}`
}

/** Stable id for a marker without a ledger row: sha256 of the marker sentence
 *  (deterministic across ticks — the same sentence is the same park). */
export function proseMarkerId(sentence: string): string {
  return `prose-marker:${createHash('sha256').update(sentence.trim()).digest('hex').slice(0, 16)}`
}

/** The parked ask this verdict is about: earliest-raised attributed ask, else the
 *  prose marker. Deterministic on ties (first in the waiting-face order). */
export function pickParkedAsk(input: Pick<SelfHealInput, 'asks' | 'questionMarker'>): { id: string; source: 'ledger-ask' | 'prose-marker'; hasDefault: boolean | null } | null {
  const sorted = [...input.asks].sort((a, b) => {
    const ra = typeof a.raisedAt === 'number' && Number.isFinite(a.raisedAt) ? a.raisedAt : Number.POSITIVE_INFINITY
    const rb = typeof b.raisedAt === 'number' && Number.isFinite(b.raisedAt) ? b.raisedAt : Number.POSITIVE_INFINITY
    return ra - rb
  })
  const first = sorted[0]
  if (first !== undefined && typeof first.requestId === 'string' && first.requestId !== '') {
    return { id: first.requestId, source: 'ledger-ask', hasDefault: typeof first.hasDefault === 'boolean' ? first.hasDefault : null }
  }
  if (input.questionMarker !== null) {
    const id = input.questionMarker.requestId ?? proseMarkerId(input.questionMarker.sentence)
    return { id, source: 'prose-marker', hasDefault: null }
  }
  return null
}

/** The self-heal judgement (pure; every hold path names the guard that held). */
export function decideSelfHeal(input: SelfHealInput): SelfHealVerdict {
  const { cfg } = input
  if (!cfg.enabled || !(cfg.parkMinutes > 0)) {
    return { action: 'hold', reason: `self_heal face off (enabled=${cfg.enabled}, park_minutes=${cfg.parkMinutes}) — observation only, never cancel`, receipt: null }
  }
  if (typeof input.sessionId !== 'string' || input.sessionId === '') {
    return { action: 'hold', reason: 'no executor session id declared/adopted — no attribution target, explicitly hold', receipt: null }
  }
  const parked = pickParkedAsk(input)
  if (parked === null) {
    return { action: 'hold', reason: 'no unanswered ask attributed to this session and no pending question marker — guard (a) not met; a long turn without an ask is healthy and never cancelled', receipt: null }
  }
  if (input.ourBriefPending !== true && input.ourBriefPending !== false) {
    return { action: 'hold', reason: 'queue mirror unreadable (ourBriefPending=null) — no-signal is never treated as pending or consumed; hold', receipt: null }
  }
  if (input.ourBriefPending === false) {
    return { action: 'hold', reason: 'our last briefing was consumed (queue drained) — the turn is not wedged on an undelivered brief; hold', receipt: null }
  }
  if (typeof input.silenceMs !== 'number' || !Number.isFinite(input.silenceMs) || input.silenceMs < 0) {
    return { action: 'hold', reason: 'silence clock unreadable (no progress baseline) — the threshold has nothing to be measured against; hold', receipt: null }
  }
  const thresholdMs = cfg.parkMinutes * 60_000
  if (input.silenceMs < thresholdMs) {
    return { action: 'hold', reason: `silence ${Math.round(input.silenceMs / 60_000)}min < park threshold ${cfg.parkMinutes}min — hold`, receipt: null }
  }
  const key = selfHealParkKey(input.sessionId, parked.id)
  const attempt = (input.attempts.get(key) ?? 0) + 1
  if (attempt > 1) {
    return { action: 'hold', reason: `park ${key} already fired ${attempt - 1} attempt(s) this process — one attempt per park, no cancel loop`, receipt: null }
  }
  return {
    action: 'cancel',
    reason: `session ${input.sessionId} parked on ask ${parked.id} (${parked.source}) past the ${cfg.parkMinutes}min park threshold with our briefing still unconsumed — cancel that turn once`,
    receipt: {
      at: input.nowMs,
      session_id: input.sessionId,
      ask_id: parked.id,
      ask_source: parked.source,
      ask_has_default: parked.hasDefault,
      threshold_minutes: cfg.parkMinutes,
      silence_minutes: Math.round(input.silenceMs / 60_000),
      attempt,
      session_running: null,
    },
  }
}

/** Briefing text delivered after the cancel: names the session, the ask and the
 *  threshold (requirement 1), and states the ask-discipline expectation (3). */
export function buildSelfHealBrief(project: string, receipt: SelfHealReceipt, defaultNote: string): string {
  return [
    `【watchdog self-heal · ${project}】`,
    `Your previous turn was parked on an unanswered ask (${receipt.ask_id}, source ${receipt.ask_source}) for ${receipt.silence_minutes} minutes (threshold ${receipt.threshold_minutes}min) with the watchdog briefing undelivered.`,
    `The watchdog cancelled that turn once to un-wedge the session (attempt ${receipt.attempt}); the queued briefing is retained.`,
    defaultNote,
    'Re-read the ledger, then continue: re-raise the ask with an acceptable default, or proceed by that default. Never park again without a default.',
  ].join('\n')
}
