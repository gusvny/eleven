/**
 * session-handle.ts — session handle short codes (console-ui epic item UI-1,
 * t261005-09). Design source: notes/discussions/261004-chat project identity and
 * session handles (section 2.3, Chinese-named file in notes/discussions/).
 *
 * Rule (host-decided): a session is referenced by a short code, never by the
 * numeric registration seq:
 *   - code = first 4 hex chars of the session uuid (`session-09ca0247-…` → `09ca`);
 *   - intra-project collision → extend to the first 6 hex chars;
 *   - collision beyond 6 chars → `<first-6-hex>-<last-4-of-id>` (e.g. `ab12cd-9f3e`),
 *     deterministic and unique whenever the uuid tail is unique;
 *   - the executor session's handle is the fixed literal `executor`
 *     (EXECUTOR_HANDLE). No console face marks a session as the executor session
 *     today — the true source is `<projects_root>/<key>/sessions.json` and lands
 *     with epic item UI-5; until then callers must not guess an executor marker
 *     locally (render only when the face supplies the data).
 *
 * Malformed input follows the existing discipline: never throws, degrades to a
 * stable derived string from whatever the id contains (empty id → `----`).
 * Pure module: zero imports, `taken` is read-only (not mutated).
 */

/** Fixed handle of the project executor session (UI-5 face supplies the marking). */
export const EXECUTOR_HANDLE = 'executor'

/** Placeholder for an empty/unusable id (visible, clearly not a real code). */
export const HANDLE_PLACEHOLDER = '----'

/** Lowercase-alphanumeric tail characters used by the beyond-6 fallback. */
function tail4(id: string): string {
  const cleaned = id.replace(/[^0-9a-zA-Z]/g, '')
  return cleaned.slice(-4) || '0000'
}

/**
 * Derive the display handle for one session id.
 * @param id session uuid as carried by the ledger (`session-…`) — never empty in
 *        practice, but tolerated (placeholder).
 * @param taken handles already used in the same project (read-only).
 */
export function sessionHandle(id: string, taken: readonly string[] = []): string {
  if (typeof id !== 'string' || id.length === 0) return HANDLE_PLACEHOLDER
  // Strip the conventional `session-` prefix so the code comes from the uuid body.
  const body = id.startsWith('session-') ? id.slice('session-'.length) : id
  const hex = body.replace(/[^0-9a-fA-F]/g, '')
  if (hex.length === 0) return HANDLE_PLACEHOLDER
  const lower = hex.toLowerCase()
  const takenSet = new Set(taken)
  for (const width of [4, 6] as const) {
    const candidate = lower.slice(0, width)
    if (!takenSet.has(candidate)) return candidate
  }
  // Beyond 6: first-6 + tail-4 of the raw id (deterministic, tail-unique).
  const base = lower.slice(0, 6)
  const suffix = `${base}-${tail4(body.toLowerCase())}`
  return takenSet.has(suffix) ? `${suffix}-${tail4(lower + body.toLowerCase())}` : suffix
}
