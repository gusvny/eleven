/**
 * ticket-overlay-model.ts — pure navigation layer for the ticket-detail
 * middle-column overlay (console-ui epic UI-3, t261005-04).
 *
 * Design source: the 261004 concurrency-limit design notes §7.5.1 / §7.8 (see
 * notes/epics/console-ui.md for the design-base index). Rules carried here:
 *   - The overlay is ALWAYS one layer deep: ticket detail and epic detail share
 *     one overlay container; drilling replaces the content and a breadcrumb
 *     walks back; an overlay on top of an overlay is never allowed.
 *   - Close (×/Esc) at any depth returns straight to the underlying view (the
 *     underlying view is never modified by the overlay).
 *   - ArrowUp/ArrowDown move between the tickets of the current project (read
 *     several tickets in a row without going back to the left column).
 *
 * The single-layer invariant lives in the type: `current` is a single entry or
 * null, never an array — "two stacked layers" is not a representable state. The
 * epic→ticket walk-back is an explicit crumb (the source epic code), not a
 * stack: a stack IS multiple layers, and that is this ticket's hard line.
 *
 * Malformed-input discipline (external data is untrusted, same family as
 * lane-map-model): never throws; non-string ids / empty strings / duplicate
 * entries are skipped and deduplicated; the ArrowUp/ArrowDown behavior at list
 * ends is pinned explicitly to "stop at the end, no wrap-around" (a stated
 * choice, see the neighborTicketId note).
 */

/** One overlay content entry. kind=epic → id is the epic code. */
export interface OverlayEntry {
  kind: 'ticket' | 'epic'
  id: string
}

/** Overlay navigation state: current = the content on show. */
export interface OverlayNav {
  current: OverlayEntry | null
  /** Non-null = the ticket detail on show was drilled into from this epic → the head renders a `← <code>` breadcrumb. */
  crumb: string | null
}

export const EMPTY_OVERLAY: OverlayNav = { current: null, crumb: null }

/* ---------------------------------------------------- open / close / drill */

/** Click a row in the ticket list: open the ticket detail (no breadcrumb; any epic content on show is replaced wholesale). */
export function openTicket(nav: OverlayNav, ticketId: unknown): OverlayNav {
  const id = cleanId(ticketId)
  if (id === null) return nav
  return { current: { kind: 'ticket', id }, crumb: null }
}

/** Click the epic badge inside a ticket detail: same layer, content becomes the epic detail (the source ticket stays in selectedId; the walk-back goes to the epic). */
export function drillToEpic(nav: OverlayNav, epicCode: unknown): OverlayNav {
  const code = cleanId(epicCode)
  if (code === null) return nav
  if (nav.current === null || nav.current.kind !== 'ticket') return nav
  return { current: { kind: 'epic', id: code }, crumb: null }
}

/** Click a ticket row inside the epic detail: same layer, content becomes the ticket detail; crumb = that epic, the head shows the breadcrumb. */
export function drillToTicketFromEpic(nav: OverlayNav, ticketId: unknown, epicCode: unknown): OverlayNav {
  const id = cleanId(ticketId)
  const code = cleanId(epicCode)
  if (id === null) return nav
  // Missing/malformed epic code: still open the ticket, but no breadcrumb (no
  // walk-back target → no dead link; the malformed-epic drill face stays inert,
  // review condition 1).
  return { current: { kind: 'ticket', id }, crumb: code }
}

/** Click the breadcrumb `← <epic>`: same layer, back to the epic detail; crumb cleared. */
export function breadcrumbBack(nav: OverlayNav): OverlayNav {
  if (nav.crumb === null) return nav
  return { current: { kind: 'epic', id: nav.crumb }, crumb: null }
}

/** Close (×/Esc): back to null = the underlying view is exactly as it was. */
export function closeOverlay(_nav: OverlayNav): OverlayNav {
  return EMPTY_OVERLAY
}

/** Single visibility decision for the breadcrumb: only "ticket detail + a source epic" renders `← code`. */
export function crumbOf(nav: OverlayNav): string | null {
  return nav.current !== null && nav.current.kind === 'ticket' ? nav.crumb : null
}

/* ---------------------------------------------------- ArrowUp/ArrowDown ticket walk */

/**
 * ArrowUp/ArrowDown walks the tickets of the current project.
 *
 * End behavior (pinned explicitly, review condition 2): **stop at the end, no
 * wrap-around** — ArrowUp on the first ticket and ArrowDown on the last both
 * stay put. Why: this list is "the current project's ticket list"; jumping to
 * the other end is a long-distance teleport the eye loses track of; for the
 * read-several-tickets flow, "reached the end" is more predictable than
 * "wrapped around". A malformed direction (not 'up'/'down') and a malformed
 * list (non-strings / empty strings / duplicate ids) are skipped and
 * deduplicated, never thrown. Current ticket missing from the list (removed by
 * a list refresh) → stay put.
 */
export function neighborTicketId(rows: unknown, currentId: unknown, direction: unknown): string | null {
  if (direction !== 'up' && direction !== 'down') return cleanId(currentId)
  const cur = cleanId(currentId)
  if (cur === null) return null
  const ids: string[] = []
  if (Array.isArray(rows)) {
    for (const r of rows) {
      const id = cleanId(typeof r === 'object' && r !== null ? (r as { id?: unknown }).id : r)
      if (id !== null && !ids.includes(id)) ids.push(id)
    }
  }
  const i = ids.indexOf(cur)
  if (i === -1) return cur
  const j = direction === 'up' ? i - 1 : i + 1
  if (j < 0 || j >= ids.length) return cur // end stop, no wrap
  return ids[j]
}

/* ---------------------------------------------------- epic-entry fault face (review condition 1) */

/*
 * Fault face of the epic entry (single caliber; the render layer consumes it as written):
 *   - Missing/malformed epic code → drillToEpic / drillToTicketFromEpic are
 *     inert on the crumb (drillToTicketFromEpic still opens the ticket but
 *     produces no dead breadcrumb; drillToEpic stays put). Breadcrumb visibility
 *     has exactly one decision point, crumbOf — a dead `←` with nowhere to go
 *     can never be rendered.
 *   - An epic with an empty ticket list → the content face is the existing
 *     EpicSection empty-state fact line ("No tickets linked to this epic yet.",
 *     the epics.tsx empty-state single point) — not a spinner, not explanatory
 *     prose; this model does not mint a second empty-state copy.
 *   - Epic detail fetch failure → EpicSection's existing error row (this ticket
 *     adds no new degradation path).
 */

/* ---------------------------------------------------- internal */

/** Accept only a non-empty string; everything else (null/undefined/number/object/empty string) is malformed → null. */
function cleanId(v: unknown): string | null {
  return typeof v === 'string' && v.trim() !== '' ? v : null
}
