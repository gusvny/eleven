/**
 * charter-title.ts — detect session titles that are the raw charter injection
 * text (t261008-01, console session labels).
 *
 * The platform derives a session's durable title from the first message; our
 * project sessions open with the charter injection, so sessions created before
 * t261008-01 carry titles that start with the machine marker comment (and the
 * charter file's own doc comment). Those titles must not be shown as a row
 * label — the session handle shows instead (Measure 1). Sessions created after
 * t261008-01 get a human-readable first line (composeCharterInjection) and
 * never match this predicate.
 *
 * Conservative on purpose: only the injection's own comment shapes match —
 * the marker line (`CHARTER_MARKER`, same-source constant, R7 anti-drift) or an
 * HTML comment that names the charter (`workbench:kind:charter` /
 * `session_charter`). A user title that merely starts with `<!--` stays raw.
 * Pure module: one same-source import, never throws, non-string → false.
 */

import { CHARTER_MARKER } from '../host/session-charter.ts'

/**
 * True when the title is (or starts with) the raw charter injection text.
 * @param title the display title under test (first message first line origin).
 */
export function isCharterRawTitle(title: unknown): boolean {
  if (typeof title !== 'string') return false
  const first = title.split('\n').map(l => l.trim()).find(l => l !== '')
  if (first === undefined) return false
  if (first === CHARTER_MARKER || first.startsWith(CHARTER_MARKER)) return true
  return first.startsWith('<!--') && (first.includes('workbench:kind:charter') || first.includes('session_charter'))
}
