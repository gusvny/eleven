/**
 * Unanswered-approval probe (t261006-05, KI-207 item 1) — pure core.
 *
 * What: turns "the executor session is parked on an approval prompt nobody can
 * answer" into a NAMED verdict, no longer indistinguishable from a long turn.
 * Source of truth = the recent-window records of the host Session API history
 * page/follow (the authorized path proven by t261004-08; on-disk transcript files
 * are NOT used — their dirs are cwd-slug keyed and zstd payload, a path guess is
 * a bet). Event vocabulary anchors: `approval/asked` / `approval/decided` are in
 * dsh known-event-types (engine-side frozen mirror SESSION_TWO_GEN_TYPES in
 * agent_activities.py — same words on both sides, no new coinage).
 *
 * Predicate (order-sensitive; records are in session-stream order): an
 * `approval/asked` still standing after the most recent `approval/decided` =
 * awaiting (that asked's id/at go into the evidence). Neither type in the window
 * = none; records without a single typed event = unknown (an unreadable shape is
 * never faked into "no approval" — same three-valued discipline as
 * waiting-face.ts). Deep-walk id/at extraction carries depth/count caps: a
 * malformed oversized receipt never stalls the tick.
 *
 * Non-guarantees: the recent window is 12 messages — an asked outside the window
 * with its decided inside is missed (the evidence always carries the "in the
 * recent history window" qualifier); the window is re-read every tick, so a
 * mis-window heals next tick. This face only observes; it takes no action.
 */

export type ApprovalWindowState = 'awaiting' | 'clear' | 'none' | 'unknown'

export interface ApprovalWindow {
  state: ApprovalWindowState
  /** Approval id of the latest unanswered asked (null = not extractable; the evidence line still names the ask). */
  approval_id: string | null
  /** When that ask was raised (null = not extractable). */
  asked_at: number | null
  /** Human-readable evidence line (into liveness evidence and the alert detail). */
  evidence: string
}

/** Deep-walk for string/number fields under the given keys (depth <= 6, total <= 200 — malformed deep nesting / oversized receipts never stall the tick). */
function deepFind(v: unknown, keys: string[], out: Array<string | number>, depth: number): void {
  if (out.length >= 200 || depth > 6) return
  if (Array.isArray(v)) {
    for (const item of v) deepFind(item, keys, out, depth + 1)
    return
  }
  if (v !== null && typeof v === 'object') {
    for (const k of Object.keys(v as Record<string, unknown>)) {
      const val = (v as Record<string, unknown>)[k]
      if (keys.includes(k) && (typeof val === 'string' || typeof val === 'number') && val !== '') out.push(val)
      else deepFind(val, keys, out, depth + 1)
    }
  }
}

function firstString(vals: Array<string | number>): string | null {
  for (const v of vals) if (typeof v === 'string') return v
  return null
}

function firstNumber(vals: Array<string | number>): number | null {
  for (const v of vals) if (typeof v === 'number' && Number.isFinite(v)) return v
  return null
}

/** Recent-window approval verdict (pure; records = raw page() records, in stream order). */
export function judgeApprovalWindow(records: unknown[]): ApprovalWindow {
  const none: ApprovalWindow = { state: 'none', approval_id: null, asked_at: null, evidence: '' }
  if (!Array.isArray(records) || records.length === 0) return none
  type Ev = { kind: 'asked' | 'decided'; id: string | null; at: number | null }
  const events: Ev[] = []
  let typed = 0
  for (const rec of records) {
    if (rec === null || typeof rec !== 'object') continue
    const t = (rec as { type?: unknown }).type
    if (typeof t !== 'string' || t === '') continue
    typed += 1
    if (t !== 'approval/asked' && t !== 'approval/decided') continue
    const data = (rec as { data?: unknown }).data
    const found: Array<string | number> = []
    deepFind(data, ['id', 'approvalId', 'approval_id'], found, 0)
    const times: Array<string | number> = []
    deepFind(data, ['at', 'atMs', 'timestamp'], times, 0)
    events.push({ kind: t === 'approval/asked' ? 'asked' : 'decided', id: firstString(found), at: firstNumber(times) })
  }
  // Not a single typed event = unreadable shape (host receipt of another build or
  // malformed) — explicit unknown, never faked into "no approval".
  if (typed === 0) {
    return { state: 'unknown', approval_id: null, asked_at: null,
      evidence: 'Recent history window contains no readable event records (host receipt shape differs or is malformed) — approval state unknown.' }
  }
  if (events.length === 0) return none
  const lastDecidedIdx = events.map(e => e.kind).lastIndexOf('decided')
  const unanswered = lastDecidedIdx < 0 ? events.filter(e => e.kind === 'asked') : events.slice(lastDecidedIdx + 1).filter(e => e.kind === 'asked')
  if (unanswered.length === 0) {
    return { state: 'clear', approval_id: null, asked_at: null,
      evidence: 'No unanswered approval in the recent history window (every approval/asked is followed by approval/decided).' }
  }
  const hit = unanswered[unanswered.length - 1]
  const idPart = hit.id ? ` id=${hit.id}` : ''
  const atPart = hit.at !== null ? ` asked at ${new Date(hit.at).toISOString()}` : ''
  return {
    state: 'awaiting',
    approval_id: hit.id,
    asked_at: hit.at,
    evidence: `Unanswered approval prompt in the recent history window${idPart}${atPart}: approval/asked with no approval/decided after it. ` +
      'An executor session has no approval answerer (KI-208) — this is a parked wait, not a long turn.',
  }
}
