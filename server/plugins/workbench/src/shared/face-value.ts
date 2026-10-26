/**
 * face-value.ts — THE FUNNEL (t261026-11, host ruling 261026).
 *
 * WHAT: one discriminated union for every "could not read it" answer on a host
 * face, and ONE constructor for each half. A placeholder is not a style choice
 * a reviewer has to notice — this is the only way the type system lets you say
 * "no value":
 *
 *   type FaceValue<T> = { kind: 'value'; v: T } | { kind: 'absent'; reason: string }
 *
 * `absent(reason)` takes the reason as a REQUIRED parameter; a dash without a
 * reason does not compile, and a JS caller passing an empty/whitespace reason
 * (or a non-string) is thrown at — the funnel is never bypassed silently.
 *
 * ONE LITERAL: FACE_DASH is the only placeholder literal in the tree allowed to
 * stand outside a reason. The integration narrow check (piece 3 of the ruling)
 * exempts exactly this module; every other '—' in a host face module is an
 * error against the per-file:line exemption table.
 *
 * SHARED LOCATION: this module lives under workbench/src/shared because BOTH
 * plugins (workbench faces and executor-panel faces) must construct the dash
 * through the same functions — a per-plugin copy would be two funnels, and the
 * narrow check would have two modules to exempt. The panel already imports
 * workbench shared modules (project-identity.ts precedent).
 *
 * EMBED LAW (the t261009-37 lesson): the file imports NOTHING, and every export
 * is closure-free, so the panel page can embed `String(value) / String(absent) /
 * String(renderFace)` verbatim and alias FACE_DASH at page scope next to the
 * copy tables. Any change here must keep that true.
 */

/** The one placeholder literal. Changing the word is a whole-tree decision. */
export const FACE_DASH = '—'

/** A face value: a real value, or an absence that names what could not be read. */
export type FaceValue<T> = { kind: 'value'; v: T } | { kind: 'absent'; reason: string }

/** The reason must be a non-empty string a person can act on. Throws otherwise. */
export function absent<T = never>(reason: string): FaceValue<T> {
  if (typeof reason !== 'string' || reason.trim().length === 0 || /^[—\-.n/a\s]*$/i.test(reason)) {
    throw new Error('face-value: absent() requires a non-empty reason a person can act on')
  }
  return { kind: 'absent', reason }
}

/** Wrap a real value. Never throws. */
export function value<T>(v: T): FaceValue<T> {
  return { kind: 'value', v }
}

/** Render a face value: the formatted value, or THE dash when absent. */
export function renderFace<T>(fv: FaceValue<T>, fmt?: (v: T) => string): string {
  if (fv && fv.kind === 'absent') return FACE_DASH
  if (fv && fv.kind === 'value') {
    return (typeof fmt === 'function') ? fmt(fv.v) : String(fv.v)
  }
  // A hand-built literal that is neither half is the wrong shape — refuse loudly.
  throw new Error('face-value: renderFace() got a value that did not come from value()/absent()')
}

/** The absence's reason, or '' for a value (callers that need to surface it). */
export function reasonOf<T>(fv: FaceValue<T>): string {
  return (fv && fv.kind === 'absent') ? fv.reason : ''
}
