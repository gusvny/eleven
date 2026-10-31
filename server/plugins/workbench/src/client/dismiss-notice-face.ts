/**
 * sandbar-workbench · the refusal face for a pending dismissal (t261031-06).
 *
 * The engine's refusal renders INSIDE the dismiss prompt. When no prompt slot
 * can exist for that row, the refusal still must not be dropped silently: this
 * module names the condition that stopped the prompt from rendering and builds
 * the one face line that carries the engine's own words.
 *
 * Pure model - no React, no IO. The panel feeds it the face it just computed
 * (project groups on the face, their row ids, the unowned inspection group) and
 * renders one line per stranded refusal.
 *
 * Conditions are exactly the ones that can happen here:
 *   group-gone      the project block that owned the row is not on the face
 *                   (removed / quarantined / a registry re-read without it);
 *   group-collapsed the block is on the face but folded, so its prompt slot is
 *                   not rendered until the person opens it (self-healing: the
 *                   line disappears and the prompt re-opens on expand);
 *   row-gone        the row left the face while the answer was in flight, so a
 *                   retry prompt would point at nothing.
 */

import type { PendingDismissal } from './dismiss-pending-store.ts'

export type DismissStrandCondition = 'group-gone' | 'group-collapsed' | 'row-gone'

/** One project block as the face actually stands right now. */
export interface DismissFaceGroup {
  projectKey: string
  collapsed: boolean
  ticketIds: string[]
  dismissedIds: string[]
}

/** The left column's row face (the only thing that decides prompt slots). */
export interface DismissFace {
  groups: DismissFaceGroup[]
  /** True when the unowned inspection group is rendered at all. */
  unownedOnFace: boolean
  unownedIds: string[]
}

export interface StrandedRefusal {
  entry: PendingDismissal
  condition: DismissStrandCondition
  /** Steady-language clause naming the failed condition. */
  detail: string
}

/**
 * Refusals whose prompt slot cannot exist on this face, in store order.
 * A refusal that CAN render is not listed - it renders in its prompt slot.
 */
export function strandedRefusals(pending: PendingDismissal[], face: DismissFace): StrandedRefusal[] {
  const out: StrandedRefusal[] = []
  for (const entry of pending) {
    if (entry.phase !== 'refused' || entry.notice === '') continue
    if (entry.projectKey === '') {
      if (!face.unownedOnFace) {
        out.push({ entry, condition: 'group-gone', detail: 'the inspection group that held the row is not on the face' })
      } else if (!face.unownedIds.includes(entry.ticketId)) {
        out.push({ entry, condition: 'row-gone', detail: 'the row is no longer on the face' })
      }
      continue
    }
    const group = face.groups.find(g => g.projectKey === entry.projectKey)
    if (group === undefined) {
      out.push({ entry, condition: 'group-gone', detail: `project group "${entry.projectKey}" is not on the face` })
      continue
    }
    if (group.collapsed) {
      out.push({ entry, condition: 'group-collapsed', detail: `project group "${entry.projectKey}" is collapsed` })
      continue
    }
    if (!group.ticketIds.includes(entry.ticketId) && !group.dismissedIds.includes(entry.ticketId)) {
      out.push({ entry, condition: 'row-gone', detail: 'the row is no longer on the face' })
    }
  }
  return out
}

/** Row keys of the stranded refusals (the prompt slot must skip these). */
export function strandedKeys(strands: StrandedRefusal[]): Set<string> {
  return new Set(strands.map(s => `${s.entry.projectKey}\u0000${s.entry.ticketId}`))
}

/**
 * One visible line: which condition failed, and the engine's refusal verbatim
 * (quoted, never paraphrased - the person must be able to read the engine's own
 * words even when the prompt cannot open).
 *
 * The condition is named twice on purpose: the token (`group-gone` /
 * `group-collapsed` / `row-gone`) is the same word the face carries in its
 * `data-dismiss-unrenderable-condition` attribute, so a reader of the printed
 * line and a reader of the DOM name the SAME thing, and the clause after it says
 * what that means in plain words.
 */
export function strandedRefusalLine(s: StrandedRefusal): string {
  const what = s.entry.action === 'dismiss' ? 'Dismiss' : 'Restore'
  return `${what} of ${s.entry.ticketId} was refused, and the notice cannot show in its row prompt:`
    + ` ${s.condition} - ${s.detail}. The engine said: ${JSON.stringify(s.entry.notice)}`
}
