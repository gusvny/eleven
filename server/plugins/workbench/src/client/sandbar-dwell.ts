/**
 * sandbar-dwell —— closed dev-lane ticket dwell window for the sidebar groups
 * (pure logic layer, zero react/platform deps so node can black-box import it,
 * same layering precedent as ticket-list-model.ts).
 *
 * Host order 261008 option A: the sidebar Settings popover (gear + "Sandbar
 * dwell" input) is retired, so the dwell window is PINNED at 24 hours. The
 * window behaviour itself stays real: a closed dev-lane ticket leaves the left
 * column 24 h after it closes (close_ts, falling back to created). Inspection
 * rows never go through this window — their closed-row window is the engine's
 * own R8 window (two-window split, see sidebar.tsx group assembly).
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
}

/** Open = lifecycle not closed out; project groups always list these. */
export const isDwellOpen = (t: DwellTicket): boolean =>
  t.status !== 'closed' && t.status !== 'verified'

/**
 * Dwell predicate: closed rows stay while close_ts (fallback created) is
 * inside the pinned window. Boundary is strict `<` — a row at exactly 24 h
 * has left.
 */
export const inSandbar = (t: DwellTicket, nowS: number): boolean => {
  if (isDwellOpen(t)) return true
  const h = sandbarHours()
  if (h <= 0) return false
  const ts = t.close_ts || t.created || 0
  return ts > 0 && nowS - ts < h * 3600
}
