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
 *
 * t261028-17: the name shown is the ticket's own name. A row whose name the engine
 * could not resolve carries an empty `title` (the engine puts the diagnostic in
 * `identity_note` instead); here it falls back to the ticket id, so the Epics tab
 * never shows a status sentence where a ticket name belongs. The fallback keys on
 * emptiness only — never on matching a known message text.
 */
export function epicTicketRow(t: unknown): Record<string, string | number> {
  const src = (t ?? {}) as Record<string, unknown>
  const id = String(src.id ?? '')
  const row: Record<string, string | number> = {
    id,
    title: titleOrTicketId(src.title, id),
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

/**
 * The name slot for one Epics-tab row: the ticket's own title when it has one, the
 * ticket id otherwise. Empty / blank / non-string names are ABSENT (they are not
 * names), so the id stands in — a readable row, never a blank and never a sentence.
 */
export function titleOrTicketId(title: unknown, id: unknown): string {
  const name = typeof title === 'string' ? title.trim() : ''
  if (name !== '') return name
  return String(id ?? '')
}
