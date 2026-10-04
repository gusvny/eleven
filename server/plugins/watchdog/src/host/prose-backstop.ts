/**
 * prose backstop (t261004-08, pure core) — files a prose "waiting on you" ask as a
 * request row.
 *
 * Background (ticket evidence): the executor wrote "仍等你一句话的：…" inside its own
 * round reports and filed nothing, so the host saw nothing in the panel. The question
 * bridge (t261001-23) only mirrors structured ask_user_question; a prose ask reached
 * no surface at all. This module catches that text: idle past the threshold + recent
 * round text carrying a waiting marker + no unanswered request attributed to the
 * session in the ledger → file exactly one attributed request row + raise exactly one
 * alert.
 *
 * Heuristic disclosure (required by the ticket): text detection is heuristic by
 * nature — the marker list cannot cover paraphrases ("还需要你拍板" style wording is
 * missed). The miss-mode is not silence: stall / self_lock still surface (a missed
 * ask eventually shows up as a stall or a self-lock). The false-positive face is
 * bounded by exact substring matching; negated forms ("不用等了") do not match (the
 * marker list has no negated entries, see PROSE_MARKERS).
 *
 * Idempotency (one row per ask, two layers):
 *  - (a) ledger coverage check: any unanswered request row attributed to the session
 *    = covered, do not file (the ledger is the durable truth; restarts inherit it
 *    naturally); a ledger read failure = explicit failure, never file blind;
 *  - (b) filing journal (append-only jsonl, key = sha256(sessionId+normalized
 *    sentence), records the requestId): the SAME ask instance (its row still
 *    unanswered) never files a second row on later cycles; once that row is ANSWERED,
 *    the same sentence re-appearing = a new ask instance and files exactly one new
 *    row (per-ask-instance idempotency, not once-forever silence — required by the
 *    review acceptance case).
 *
 * Fail loud: unreadable text / unavailable host face → the caller marks unknown + one
 * prose_backstop_unknown alert, never "nothing to report".
 *
 * Co-firing disclosure (review N1): after the backstop files an attributed row, the
 * escalated self_lock will (correctly) fire for that row once the threshold passes.
 * Two different intents (a filing event vs pending-past-threshold) — not the
 * duplicate the ticket bans. Full alert set for a backstop-originated wait =
 * {prose_ask_filed ×1, self_lock ×1}.
 */

import { createHash } from 'node:crypto'

/** Waiting-marker list (exact substrings; English forms case-insensitive). */
export const PROSE_MARKERS = [
  '等你一句话',
  '等宿主',
  '等答复',
  '等你确认',
  'waiting for the host',
  'awaiting your decision',
  'awaiting your answer',
] as const

export interface ProseBackstopConfig {
  enabled: boolean
  idleMinutes: number
}

/** Extract the sentence containing a marker (heuristic split on newline/period/
 *  semicolon; first marker-bearing piece, capped at 200 chars; no marker = null). */
export function findMarkerSentence(text: string): string | null {
  if (typeof text !== 'string' || text === '') return null
  const lower = text.toLowerCase()
  const markerHit = PROSE_MARKERS.find(m => lower.includes(m))
  if (markerHit === undefined) return null
  const pieces = text.split(/[。；;\n\r]+/).map(s => s.trim()).filter(s => s !== '')
  const withMarker = pieces.find(p => p.toLowerCase().includes(markerHit))
  const sentence = withMarker ?? text.trim()
  return sentence.length > 200 ? sentence.slice(0, 200) : sentence
}

/** Idempotency key: sha256(sessionId + '\u0000' + normalized sentence) (normalization
 *  = trim only; case is preserved — English "Waiting…" vs lowercase are two asks). */
export function proseKey(sessionId: string, sentence: string): string {
  return createHash('sha256').update(`${sessionId}\u0000${sentence.trim()}`).digest('hex')
}

/** Journal line (single jsonl row; the caller's io does the write). */
export function journalLine(key: string, requestId: string, nowMs: number): string {
  return JSON.stringify({ key, request_id: requestId, at: nowMs })
}

/** Journal replay: malformed rows counted explicitly (no throw — one bad row does not
 *  erase the muting power of the good ones). */
export function replayJournal(lines: string[]): { entries: Array<{ key: string; requestId: string }>; malformed: number } {
  const entries: Array<{ key: string; requestId: string }> = []
  let malformed = 0
  for (const l of lines) {
    if (l.trim() === '') continue
    try {
      const doc = JSON.parse(l) as { key?: unknown; request_id?: unknown }
      if (typeof doc.key === 'string' && doc.key !== '' && typeof doc.request_id === 'string' && doc.request_id !== '') {
        entries.push({ key: doc.key, requestId: doc.request_id })
      } else malformed += 1
    } catch {
      malformed += 1
    }
  }
  return { entries, malformed }
}

/** Decision input (caller = core: ledger read, text read, row write, alerting). */
export interface ProseBackstopInput {
  cfg: ProseBackstopConfig
  sessionId: string
  /** Recent round text; null = unreadable (the caller handles the unknown face; this just refuses to judge blind). */
  text: string | null
  /** Session idle minutes (only computable from a readable snapshot; null = snapshot missing). */
  idleMinutes: number | null
  /** All unanswered (status==='waiting') ledger rows projected. */
  waitingRows: Array<{ id: string; raisedBy: string }>
  /** Filed-journal entries (startup replay + this process; requestId mutes only while unanswered). */
  journal: Array<{ key: string; requestId: string }>
}

export type ProseBackstopAction =
  | { action: 'off'; reason: string }
  | { action: 'not-idle'; reason: string }
  | { action: 'no-marker'; reason: string }
  | { action: 'skipped-covered-by-ledger'; reason: string }
  | { action: 'already-filed'; reason: string }
  | { action: 'no-session'; reason: string }
  | { action: 'filed'; requestId: string; sentence: string; key: string }

/** Pure decision: file or not. Row writes / alerts live in core (this never touches disk). */
export function decideProseBackstop(input: ProseBackstopInput): ProseBackstopAction {
  const { cfg, sessionId, text, idleMinutes, waitingRows, journal } = input
  if (!cfg.enabled) return { action: 'off', reason: 'prose_backstop.enabled=false — backstop explicitly off' }
  if (sessionId === '') return { action: 'no-session', reason: 'executor session id not declared/adopted — no attribution target to file' }
  if (text === null || idleMinutes === null) {
    // The caller owns the unknown-face escalation + alert; this only refuses to judge blind.
    return { action: 'no-marker', reason: 'recent round text or idle duration unreadable — caller must mark unknown and raise prose_backstop_unknown' }
  }
  if (idleMinutes < cfg.idleMinutes) {
    return { action: 'not-idle', reason: `idle ${Math.floor(idleMinutes)} min < threshold ${cfg.idleMinutes} — not judged a prose ask` }
  }
  const sentence = findMarkerSentence(text)
  if (sentence === null) return { action: 'no-marker', reason: 'no waiting marker in the recent round text — heuristic list missed (miss-mode in module header)' }
  const covered = waitingRows.find(r => r.raisedBy === sessionId)
  if (covered !== undefined) {
    return { action: 'skipped-covered-by-ledger', reason: `ledger already holds an unanswered request from this session (${covered.id}) — covered, not filed again` }
  }
  const key = proseKey(sessionId, sentence)
  // Journal muting applies only while the prior filing for this key is STILL
  // unanswered; its row answered + sentence re-appearing = a new ask instance,
  // exactly one new row (per-ask-instance idempotency — review acceptance case).
  const stillWaitingIds = new Set(waitingRows.map(r => r.id))
  const pendingPrior = journal.find(j => j.key === key && stillWaitingIds.has(j.requestId))
  if (pendingPrior !== undefined) {
    return { action: 'already-filed', reason: `same ask already filed and still unanswered (${pendingPrior.requestId}) — one row per ask, no second row` }
  }
  return { action: 'filed', requestId: '', sentence, key }
}
