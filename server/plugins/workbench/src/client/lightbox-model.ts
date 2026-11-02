/**
 * lightbox-model.ts — the shared lightbox's pure contract (epic artifact-face, slice 3,
 * ticket t261030-36). Extracted from `index.tsx` so the screenshot-evidence lightbox and
 * the artifact image view use ONE component, ONE key contract and ONE navigation rule.
 *
 * No React, no DOM, no node imports: the console bundle carries it, `smoke/evidence-lightbox.mjs`
 * loads the built bundle and asserts the re-exported names, and the L1 battery drives the
 * malformed-input cases directly.
 */

/** The key contract: Esc closes; the arrows page only outside an editable target. */
export const LIGHTBOX_KEYS = { close: 'Escape', prev: 'ArrowLeft', next: 'ArrowRight' } as const

/**
 * Cycle `index` by `delta` over a list. Malformed input (an empty list, an out-of-range or
 * non-integer index, a non-integer delta) lands on a safe index and never throws: while the
 * lightbox is open the list can shrink when its source is re-read.
 */
export function lightboxNav(items: readonly unknown[], index: unknown, delta: unknown): number {
  const n = Array.isArray(items) ? items.length : 0
  if (n <= 0) return 0
  const i = typeof index === 'number' && Number.isInteger(index) && index >= 0 && index < n ? index : 0
  const d = typeof delta === 'number' && Number.isInteger(delta) ? delta : 0
  return ((i + d) % n + n) % n
}
