/**
 * queue-model — left-column ticket order (CL-3, t261006-18) pure-function layer.
 *
 * Design source: the 261004 concurrency-limit design notes §2.2 / §7.2 and the
 * concurrency-limit epic ticket-order item 3. Zero react / platform deps; node
 * imports it directly (type stripping, same layering as ticket-list-model.ts).
 *
 * Iron rule (the ticket's own wording): the UI must NOT compute the order
 * locally. Everything here either (a) projects the engine's read face
 * (`concurrency.read_state` via GET /sandbar-workbench/api/wf/concurrency)
 * onto render inputs, or (b) builds the new-order permutation to POST back.
 * No function keeps a client-side queue: after every move the caller re-reads
 * the same face and renders from that.
 *
 * Malformed-face discipline: a face that is not an object, has non-array
 * holders/queue, entries without a ticket id, or duplicate queue ids parses to
 * `null` — the caller renders the order-free list and shows no invented order
 * (never a fabricated position number).
 */

/** Minimal shape of the engine's read face we consume (concurrency._face + keys). */
export interface ConcFaceRaw {
  holders?: unknown
  queue?: unknown
}

/** Normalized face: holder ticket -> reason ('running' | 'human-hold'), queue ids in engine order. */
export interface ConcFace {
  holderReason: Record<string, string>
  /** Queue ticket ids, position 1..n = engine order (the start order). */
  queue: string[]
}

/**
 * Unwrap a read-face HTTP reply into the raw face. Two lawful shapes exist:
 * the host wraps (`{ok:true, result:<face>}`) and a bare read_state is accepted
 * too (the reply contract allows it). A `{ok:false,...}` refusal or anything
 * else unwraps to null — the caller renders the order-free list.
 */
export function concFaceFromReply(reply: unknown): unknown {
  if (reply === null || typeof reply !== 'object' || Array.isArray(reply)) return null
  const r = reply as { ok?: unknown; result?: unknown }
  if (r.ok === true && r.result !== undefined && r.result !== null) return r.result
  if ('ok' in r) return null // explicit refusal / unknown ok shape: never guess a face out of it
  return r
}

/** Parse + validate the read face. Returns null on any malformed input. */
export function parseConcFace(raw: unknown): ConcFace | null {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  const r = raw as ConcFaceRaw
  const holderReason: Record<string, string> = {}
  if (r.holders !== undefined) {
    if (!Array.isArray(r.holders)) return null
    for (const h of r.holders) {
      if (h === null || typeof h !== 'object') return null
      const id = (h as { ticket?: unknown }).ticket
      if (typeof id !== 'string' || id === '') return null
      holderReason[id] = String((h as { reason?: unknown }).reason ?? '')
    }
  }
  const queue: string[] = []
  if (r.queue !== undefined) {
    if (!Array.isArray(r.queue)) return null
    for (const e of r.queue) {
      let id: unknown = e
      if (e !== null && typeof e === 'object') id = (e as { ticket?: unknown }).ticket
      if (typeof id !== 'string' || id === '') return null
      if (queue.includes(id)) return null // duplicate queue entry: never render an ambiguous order
      queue.push(id)
    }
  }
  return { holderReason, queue }
}

/** Row classification from the face (plus the row's own paused flag). */
export type OrderKind = 'queued' | 'atwork' | 'hold' | 'paused'

/**
 * Classify one ticket row. `paused` is the engine row's own pause flag
 * (host-paused tickets hold no slot, so the face never lists them — the pause
 * flag is the only source). Returns undefined for rows the face says nothing
 * about (closed tickets, unknown ids): they get no order marks at all.
 */
export function orderKindOf(id: string, face: ConcFace | null, paused?: boolean): OrderKind | undefined {
  if (face === null) return undefined
  if (face.queue.includes(id)) return 'queued'
  const reason = face.holderReason[id]
  if (reason === 'running') return 'atwork'
  if (reason === 'human-hold') return 'hold'
  if (paused === true) return 'paused'
  return undefined
}

/**
 * New queue after moving one queued ticket one slot up (-1) or down (+1).
 * Returns null when the move is impossible (edge of the queue, id not in the
 * queue, malformed direction) — the caller then POSTs nothing.
 */
export function moveTicket(queue: string[], id: string, dir: number): string[] | null {
  if (dir !== -1 && dir !== 1) return null
  const i = queue.indexOf(id)
  if (i < 0) return null
  const j = i + dir
  if (j < 0 || j >= queue.length) return null
  const next = queue.slice()
  ;[next[i], next[j]] = [next[j], next[i]]
  return next
}

/**
 * New queue after dropping `dragId` onto `dropId`'s slot (the handgrip path —
 * arrows use moveTicket). Returns null unless both ids are queued.
 */
export function reorderMoveTo(queue: string[], dragId: string, dropId: string): string[] | null {
  const from = queue.indexOf(dragId)
  const to = queue.indexOf(dropId)
  if (from < 0 || to < 0 || from === to) return null
  const next = queue.slice()
  next.splice(from, 1)
  next.splice(to, 0, dragId)
  return next
}

/**
 * Guard for the POST body: the order must be a permutation of the face's
 * current queue (the engine's own reorder() refuses anything else — mirroring
 * the check client-side turns an obvious mistake into a no-op instead of a
 * round-trip refusal). Returns null when `order` is not a permutation.
 */
export function permutationOf(queue: string[], order: unknown): string[] | null {
  if (!Array.isArray(order)) return null
  const want: string[] = []
  for (const t of order) {
    if (typeof t !== 'string' || t === '') return null
    want.push(t)
  }
  if (want.length !== queue.length) return null
  const a = [...queue].sort()
  const b = [...want].sort()
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return null
  return want
}

/**
 * Progress dots for line 2: ten cells, lit up to the current stage (design
 * §7.2; `dots` is the ruled default — the bar alternative is out of scope
 * here). `stageIndex` is 0-based; a closed ticket lights all cells; an
 * unknown/unplaced stage lights none (never a fabricated mid-point).
 */
export const STAGE_DOTS_TOTAL = 10

export function stageDotsLit(stageIndex: number, closed = false): number {
  if (closed) return STAGE_DOTS_TOTAL
  if (!Number.isInteger(stageIndex) || stageIndex < 0) return 0
  return Math.min(stageIndex + 1, STAGE_DOTS_TOTAL)
}

/** Project-row counts from the face: `X at work · Y waiting`. Raw numbers only — the sentence lives in CSS/none. */
export function faceCounts(face: ConcFace | null): { atWork: number; waiting: number } {
  if (face === null) return { atWork: 0, waiting: 0 }
  return { atWork: Object.keys(face.holderReason).length, waiting: face.queue.length }
}
