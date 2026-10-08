/**
 * inspection-exit-model — pure model for the inspection ticket exit block
 * (t261008-22). Zero react / zero io — node-importable unit-tested truth tables
 * (ticket-list-model.ts layering precedent); the .tsx component only consumes.
 */

/** Exit block visibility: inspection rows only, and only when there is something to
 *  say — a blocked face (actions) or a voided face (the recorded disposition). */
export function inspectionExitVisible(detail: {
  kind?: unknown
  status?: unknown
  voided?: unknown
}): boolean {
  if (detail === null || typeof detail !== 'object') return false
  if (detail.kind !== 'inspection') return false
  return Boolean(detail.voided) || detail.status === 'blocked'
}

/** Shape + require-a-reason pre-check (the same named refusals the server repeats).
 *  Returns the validated payload or a named error; never throws. */
export function buildExitPayload(
  action: 'rerun' | 'void',
  detail: { id?: unknown; instance_id?: unknown; period?: unknown; project?: unknown },
  projectKey: string | undefined,
  reason: string,
): { ok: true; payload: Record<string, string> } | { ok: false; error: string } {
  const instance = typeof detail.instance_id === 'string' ? detail.instance_id.trim() : ''
  const period = typeof detail.period === 'string' ? detail.period.trim() : ''
  if (instance === '') return { ok: false, error: 'This ticket carries no instance identity — the exit cannot address a period (resolve the identity first).' }
  if (period === '') return { ok: false, error: 'This ticket carries no period — the exit cannot address a period (resolve the period first).' }
  const r = reason.trim()
  if (r === '') return { ok: false, error: `A reason is required for ${action === 'rerun' ? 'a re-run' : 'a void'} — it is the human signature. Write why, then retry.` }
  const payload: Record<string, string> = { project: projectKey ?? '', instance, period, reason: r }
  if (action === 'void') {
    payload.ticket_id = typeof detail.id === 'string' ? detail.id : ''
    if (payload.ticket_id === '') return { ok: false, error: 'This ticket carries no id — a void cannot be addressed.' }
  }
  return { ok: true, payload }
}
