/**
 * face-overlay-model.ts — t261008-36: the pure decision layer for the panel
 * Settings entries -> host-side face overlay.
 *
 * The panel page's open-face message is EXTERNAL INPUT (a postMessage payload), so
 * the decision is a pure function: node imports it directly for the unit test
 * (tests/t261008-36-face-overlay.mjs), and the page and the test always run one
 * implementation. Decision rules (ticket requirement 5 + review R2/R3):
 *  - face must be in {'routes','project-settings'} — any value outside the whitelist
 *    is rejected;
 *  - the payload's projectKey must equal this view's projectKey byte for byte (the
 *    panel's own context, never the console's view registry) — a mismatch, including
 *    a stale frame replaying after a project switch, is rejected;
 *  - a non-object / null / missing field / wrong type is malformed input: rejected,
 *    never thrown.
 * Rejected = the handler ignores the message (the accepted surface does not grow,
 * the review-C3 discipline). The panel-side buttons are fixed shape and only send
 * whitelisted faces, so there is no dead silent button on the panel side.
 */

/** The two existing faces the panel Settings entries may open (whitelist; one word,
 *  one meaning; no third spelling). */
export type PanelFace = 'routes' | 'project-settings'

/** open-face payload whitelist (same surface as the OPEN_FACE_MSG_TYPE branch in
 *  executor-view.tsx). */
export const PANEL_FACES: ReadonlyArray<PanelFace> = ['routes', 'project-settings']

/** The open-face message type (single source; executor-view.tsx re-exports it to
 *  keep the existing constant surface). */
export const OPEN_FACE_MSG_TYPE = 'sandbar-executor-panel:open-face'

/**
 * Judge one open-face message payload: valid -> return the face; every other shape
 * -> null (the caller ignores it). expectedProjectKey is the projectKey prop this
 * view (the host) holds — byte-for-byte equality is required. The type field is
 * checked here too: this function is the first gate on external input and does not
 * trust the caller to have filtered the type.
 */
export function panelFaceFromMessage(data: unknown, expectedProjectKey: string): PanelFace | null {
  if (!data || typeof data !== 'object') return null
  const d = data as { type?: unknown; face?: unknown; projectKey?: unknown }
  if (d.type !== OPEN_FACE_MSG_TYPE) return null
  if (typeof d.face !== 'string') return null
  if (!(PANEL_FACES as ReadonlyArray<string>).includes(d.face)) return null
  if (typeof d.projectKey !== 'string') return null
  if (d.projectKey !== expectedProjectKey) return null
  return d.face
}
