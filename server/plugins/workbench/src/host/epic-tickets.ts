/**
 * Epic tickets payload row mapper (t261021-12).
 *
 * `handleEpicTickets` used to map each ticket to id/title/status/stage/stage_state
 * only, dropping the ticket's last-modified time — so the per-epic newest-first
 * sort (byUpdatedDesc) and the Epics-tab activity sort (epicLastActivity) were both
 * dead: every row read -1, everything tied, registry order won.
 *
 * This function is the single boundary for the time field:
 * - source: the ticket list's existing `updated_ts` (epoch SECONDS, per
 *   server/tools/ticket.py which passes the engine row through untouched);
 * - converted ONCE here to MILLISECONDS, the unit the page compares against
 *   `Date.now()` (relTime, landedToday, both sorts);
 * - a malformed value (missing / not a finite number / <= 0 after the CLI's own
 *   0-fallback) is ABSENT from the row — never zero, never now.
 */
export function epicTicketRow(t: unknown): Record<string, string | number> {
  const src = (t ?? {}) as Record<string, unknown>
  const row: Record<string, string | number> = {
    id: String(src.id ?? ''),
    title: String(src.title ?? ''),
    status: String(src.status ?? ''),
    stage: String(src.stage ?? ''),
    stage_state: String(src.stage_state ?? ''),
  }
  const ts = src.updated_ts
  if (typeof ts === 'number' && Number.isFinite(ts) && ts > 0) {
    row.updated_ts = ts * 1000
  }
  return row
}
