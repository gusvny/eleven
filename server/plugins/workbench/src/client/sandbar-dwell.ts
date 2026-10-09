/**
 * sandbar-dwell —— closed dev-lane ticket dwell window for the sidebar groups
 * (pure logic layer, zero react/platform deps so node can black-box import it,
 * same layering precedent as ticket-list-model.ts).
 *
 * Host order 261008 option A: the sidebar Settings popover (gear + "Sandbar
 * dwell" input) is retired, so the dwell window is PINNED at 24 hours. The
 * window behaviour itself stays real: a closed dev-lane ticket leaves the left
 * column 24 h after it closes (close_ts, falling back to created). t261009-43:
 * a failure-class terminal status settles like a closed one and then obeys the
 * same pinned window, so a dead failed row retires too. Inspection rows never
 * go through this window — their closed-row window is the engine's
 * own R8 window (two-window split, see sidebar.tsx group assembly); for them
 * the human dismissal (t261009-43) is the retirement mechanism.
 *
 * Stored-value policy (chosen over clamp): the legacy localStorage key is
 * IGNORED and removed, not clamped. With the knob gone, any surviving stored
 * value (e.g. a previously typed 999) silently steering a user-visible window
 * is exactly the failure this retirement must rule out; clamping would keep
 * hidden state alive for values above the pin.
 *
 * NOTE: sandbarHours() is now the pin point of this whole rule — the one-shot
 * legacy-key removal inside it is deliberate and idempotent, not dead weight.
 * Do not "simplify" the delete away: that resurrects hidden stored state with
 * no knob to clear it.
 */

import { deriveTicketState } from './ticket-list-model.ts'

/** Legacy localStorage key written by the retired dwell-hours input. */
const SANDBAR_KEY = 'sandbar-workbench-sandbar-v1'

/** The pinned dwell window in hours (host order 261008 option A). */
export const SANDBAR_DEFAULT_H = 24

/**
 * Single reader of the dwell window: always the pinned 24 h. As a one-shot
 * side effect it deletes the legacy stored key so a stale custom value can
 * never steer the window while the knob is gone (idempotent, guarded for
 * non-browser environments).
 */
export function sandbarHours(): number {
  if (typeof localStorage !== 'undefined') {
    try {
      localStorage.removeItem(SANDBAR_KEY)
    } catch {
      // Storage may be unavailable (privacy mode, sandboxed frame); the pin
      // itself never depends on storage, so ignoring this is safe.
    }
  }
  return SANDBAR_DEFAULT_H
}

/** Minimal structural view of a ticket row the window rule needs. */
export interface DwellTicket {
  /** Lifecycle state; open = not settled-terminal (dispatched/settled/rework). */
  status: string
  /** Close time (unix seconds); falls back to created when missing. */
  close_ts?: number
  created?: number
  /** t261009-43: the five-state derivation's second/third inputs. The failure-
   * class settlement below needs them to recognize a failed workflow; both are
   * optional so existing callers (and old cached rows) keep compiling. */
  stage_state?: string
  exec_status?: string
}

/**
 * Open = lifecycle not closed out; project groups always list these.
 * t261009-43 (the dwell-rule hole): a FAILURE-CLASS TERMINAL status settles
 * like a closed one — before this change every status except closed/verified
 * counted as open, so a workflow that ended FAILED stayed listed forever no
 * matter how old it was (73 h / 110 h / 249 h measured on the live board).
 * The failure verdict is NOT re-derived here: it delegates to the five-state
 * single point (deriveTicketState in ticket-list-model.ts) and deliberately
 * passes NO voided argument — a voided row must never enter the client window
 * through this path (inspection rows bypass inSandbar entirely, and passing
 * `voided` would silently change that for a dev-lane row shape). Unknown
 * statuses still derive to active = open, unchanged.
 */
export const isDwellOpen = (t: DwellTicket): boolean => {
  if (t.status === 'closed' || t.status === 'verified') return false
  return deriveTicketState(t.status, t.stage_state, t.exec_status) !== 'failed'
}

/**
 * Dwell predicate: closed rows stay while close_ts (fallback created) is
 * inside the pinned window. Boundary is strict `<` — a row at exactly 24 h
 * has left. Since t261009-43 a failed row obeys the same window from the same
 * timestamps: the failure settles the ticket, the pinned 24 h retires it.
 */
export const inSandbar = (t: DwellTicket, nowS: number): boolean => {
  if (isDwellOpen(t)) return true
  const h = sandbarHours()
  if (h <= 0) return false
  const ts = t.close_ts || t.created || 0
  return ts > 0 && nowS - ts < h * 3600
}
