/**
 * sandbar-workbench · pending dismissal store (t261031-06).
 *
 * Why this module exists. The dismiss reason prompt keeps two facts that belong
 * to the REQUEST, not to the panel instance: which row is being dismissed and
 * what the engine answered. Both used to live in WorkbenchSidebar state
 * (`dismissPrompt` / `dismissNotice`), and a refusal renders INSIDE the prompt -
 * so any reset of the sidebar subtree dropped the notice together with the
 * prompt and the person never saw why the dismissal failed.
 *
 * Measured shape (ticket t261031-05, round run-01M67E2QMRBAR3JRFJ2FP72VFZ): the
 * route answered 200 / ok:false while the face recorded `promptOpen:false`,
 * `promptSlots:0`, `noticeAttached:false`, `noticeText:""` and the row still on
 * the board. t261031-06 reproduces that reset from a real condition (a plugin
 * re-register while the refusal is in flight) and keeps the pending dismissal
 * here instead, so a re-created prompt re-opens with the engine's own words.
 *
 * Scope rule: this store is a module singleton, and its state holder is anchored
 * on `globalThis` under a `Symbol.for` key. A component remount alone would need
 * no global anchor - but the reproduced trigger is the shell re-registering the
 * plugin, which re-evaluates the client bundle and would wipe a bare module-level
 * Map. The anchor is what makes "the state lives outside the component" true for
 * the condition that actually loses it. Nothing is persisted: a page reload is a
 * new session, not a remount, and a notice is not carried across page loads.
 *
 * Rules kept by this module:
 * - no IO, no React import, no DOM (tests import it directly under node);
 * - one entry per (project key, ticket id); a new attempt replaces the old one;
 * - a refusal is never overwritten by '' - the notice is the engine's text;
 * - snapshot stability for useSyncExternalStore (rebuilt only on change).
 */

export type DismissAction = 'dismiss' | 'restore'

/** One row's pending dismissal. `phase` says whether an answer is still due. */
export interface PendingDismissal {
  projectKey: string
  ticketId: string
  action: DismissAction
  /** Reason the person typed (kept so a re-created prompt restores it). */
  reason: string
  /** inflight = the write is out; refused = the engine answered and said no. */
  phase: 'inflight' | 'refused'
  /** The engine's refusal verbatim ('' while in flight / after an accept). */
  notice: string
  /** Monotonic-ish ordering stamp (ms); the newest entry owns the prompt slot. */
  at: number
}

/** What a prompt slot needs to name its request. */
export interface DismissTarget {
  projectKey: string
  ticketId: string
  action: DismissAction
}

interface Holder {
  entries: Map<string, PendingDismissal>
  listeners: Set<() => void>
  snapshot: PendingDismissal[] | null
}

/** Symbol.for: the same key across a bundle re-evaluation (see the header). */
const HOLDER_KEY = Symbol.for('sandbar.workbench.dismissPending.v1')

function holder(): Holder {
  const scope = globalThis as unknown as { [key: symbol]: Holder | undefined }
  let h = scope[HOLDER_KEY]
  if (h === undefined) {
    h = { entries: new Map(), listeners: new Set(), snapshot: null }
    scope[HOLDER_KEY] = h
  }
  return h
}

/** Row identity inside the store (project key + ticket id, never the id alone). */
export function pendingDismissalKey(projectKey: string, ticketId: string): string {
  return `${projectKey}\u0000${ticketId}`
}

function notify(h: Holder): void {
  h.snapshot = null
  for (const fn of [...h.listeners]) {
    try { fn() } catch { /* one subscriber must not stop the others */ }
  }
}

/** Subscribe to store changes (useSyncExternalStore protocol). */
export function subscribePendingDismissals(fn: () => void): () => void {
  const h = holder()
  h.listeners.add(fn)
  return () => { h.listeners.delete(fn) }
}

/** Snapshot, oldest first. The reference is stable while nothing changes. */
export function getPendingDismissals(): PendingDismissal[] {
  const h = holder()
  if (h.snapshot === null) h.snapshot = [...h.entries.values()].sort((a, b) => a.at - b.at)
  return h.snapshot
}

/** The entry that owns the single prompt slot (null = nothing pending). */
export function pendingDismissalForPrompt(): PendingDismissal | null {
  const list = getPendingDismissals()
  return list.length === 0 ? null : list[list.length - 1]
}

/** One lookup by row (project key + ticket id). */
export function findPendingDismissal(target: DismissTarget): PendingDismissal | undefined {
  return holder().entries.get(pendingDismissalKey(target.projectKey, target.ticketId))
}

/** Record that a write is out for this row (called before the POST leaves). */
export function beginPendingDismissal(target: DismissTarget, reason: string, at = Date.now()): void {
  const h = holder()
  h.entries.set(pendingDismissalKey(target.projectKey, target.ticketId), {
    projectKey: target.projectKey,
    ticketId: target.ticketId,
    action: target.action,
    reason,
    phase: 'inflight',
    notice: '',
    at,
  })
  notify(h)
}

/** Keep the typed reason with the pending request (survives a remount). */
export function setPendingDismissalReason(target: DismissTarget, reason: string): void {
  const h = holder()
  const key = pendingDismissalKey(target.projectKey, target.ticketId)
  const entry = h.entries.get(key)
  if (entry === undefined || entry.reason === reason) return
  h.entries.set(key, { ...entry, reason })
  notify(h)
}

/**
 * Record the engine's refusal verbatim. The entry is created when it is missing
 * (the answer can land after the instance that sent the request is gone, so the
 * store - not the caller - must be able to carry it alone).
 */
export function notePendingDismissalRefusal(target: DismissTarget, notice: string, at = Date.now()): void {
  const h = holder()
  const key = pendingDismissalKey(target.projectKey, target.ticketId)
  const entry = h.entries.get(key)
  h.entries.set(key, {
    projectKey: target.projectKey,
    ticketId: target.ticketId,
    action: target.action,
    reason: entry?.reason ?? '',
    phase: 'refused',
    notice,
    at: entry?.at ?? at,
  })
  notify(h)
}

/**
 * Forget this row's pending dismissal. Both a lawful accept and a person's
 * cancel end here: nothing is left to re-open, so a later remount shows no
 * prompt (that is the accepted-path contract, not an oversight).
 */
export function forgetPendingDismissal(target: DismissTarget): void {
  const h = holder()
  if (!h.entries.delete(pendingDismissalKey(target.projectKey, target.ticketId))) return
  notify(h)
}

/** Drop every entry (test/teardown seam; the panel never calls it). */
export function resetPendingDismissals(): void {
  const h = holder()
  if (h.entries.size === 0) return
  h.entries.clear()
  notify(h)
}
