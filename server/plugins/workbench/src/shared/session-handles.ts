/**
 * sandbar-workbench · session handle pure-function layer (console-ui UI-5, t261005-06).
 *
 * Contract source: the 261004 chat identity / session-handle design note
 * under notes/discussions/ (section 2.3):
 *   - session ids are not referenced by numbers — short codes only, no short names;
 *   - short code = first 4 hex chars of the session uuid (`session-09ca0247-…` ->
 *     `09ca`), extended on in-project collision; stable and quotable;
 *   - the project executor session has the fixed name `executor` (no code, no seq);
 *   - `title` still overrides the display when the user renames; no auto-naming;
 *   - `seq` stays history-only and is no longer the shown reference (host 261004:
 *     a number reads wrong as an id).
 *
 * This file also carries the pure-function face of sessions.json (the per-project
 * session ledger file, §2.2):
 *   - parseSessionLedgerFile / serializeSessionLedgerFile: file <-> entry array;
 *     malformed input (bad JSON / non-object / wrong version / dirty entries) is
 *     tolerated to empty or cleaned — never throws (parseLedger discipline);
 *   - mergeLedgerEntries: id-union merge (key=session_id; an existing entry wins
 *     on newer last_opened_at, otherwise incoming fields win; unmentioned stored
 *     entries are kept) — this is where concurrent writes meet, since atomic
 *     rename alone does not protect against lost updates (plan R4 contract);
 *   - mergeExecutorSessions: projects executor session ids declared in
 *     executor-grants.json into display entries with handle='executor' (derived
 *     display, NOT persisted into sessions.json — the grants file stays the
 *     single source of who-is-executor).
 *
 * Pure functions, zero IO: smoke runs them directly (node >= 22.18 native
 * type-stripping); node:fs appears only in src/host/session-ledger-file.ts.
 */

/** Fixed executor session handle (design §2.3 decision; no code). */
export const EXECUTOR_HANDLE = 'executor'

/** Base short-code length; in-project collisions extend to SHORT_CODE_LONG. */
export const SHORT_CODE_LEN = 4
export const SHORT_CODE_LONG = 6

/** sessions.json schema version (design §2.2 value). */
export const SESSIONS_FILE_VERSION = 1

/** One sessions.json entry (file face; snake_case per the design note). */
export interface LedgerFileEntry {
  session_id: string
  /** Readable handle: short code (normal sessions) or the fixed name executor; absent = not assigned yet. */
  handle?: string
  title?: string
  opened_at?: number
  last_opened_at?: number
  cwd?: string
}

/**
 * Short code of a dsh session id: strip the `session-` prefix, take the first N
 * hex chars. Non-`session-` shapes (ticket sessions, bare uuids, malformed) take
 * the first 4 chars too — the code is a reference, not a classifier, so the shape
 * is lenient (classification lives in isGlobalSessionId at the ledger entrance).
 * Non-string / empty returns '' (the caller treats it as unassigned; no fake code).
 */
export function shortCodeOf(sessionId: string, len: number = SHORT_CODE_LEN): string {
  if (typeof sessionId !== 'string' || sessionId === '') return ''
  const bare = sessionId.startsWith('session-') ? sessionId.slice('session-'.length) : sessionId
  return bare.slice(0, Math.max(1, Math.floor(len)))
}

/**
 * Idempotent handle assignment (design §2.3): entries with a handle keep it;
 * executor entries (handle='executor') are outside the code space; the rest get
 * the first free code on the length ladder 4 -> 6 -> 8 (the design pins 4 and 6;
 * 8 is the same rule extended, not a new rule). Still colliding after the ladder
 * (same-prefix uuids) stays unassigned — a missing code beats a fake one.
 * Returns a new array; the input is not mutated.
 */
const CODE_LADDER = [SHORT_CODE_LEN, SHORT_CODE_LONG, 8]

export function assignHandles(entries: readonly LedgerFileEntry[]): LedgerFileEntry[] {
  const list = Array.isArray(entries) ? entries : []
  const used = new Set<string>([EXECUTOR_HANDLE])
  for (const e of list) {
    if (e && typeof e.handle === 'string' && e.handle !== '') used.add(e.handle)
  }
  return list.map(e => {
    if (!e || typeof e.session_id !== 'string' || e.session_id === '') return e
    if (typeof e.handle === 'string' && e.handle !== '') return e
    for (const len of CODE_LADDER) {
      const code = shortCodeOf(e.session_id, len)
      if (code === '') return e
      if (!used.has(code)) {
        used.add(code)
        return { ...e, handle: code }
      }
    }
    return e
  })
}

/** Display handle of an entry: the assigned one, else a temporary short code
 *  (display only, never persisted — assignment lands on the register path, the
 *  display layer never blocks on "unassigned"). */
export function displayHandle(e: LedgerFileEntry | undefined): string {
  if (!e || typeof e.session_id !== 'string' || e.session_id === '') return ''
  if (typeof e.handle === 'string' && e.handle !== '') return e.handle
  return shortCodeOf(e.session_id)
}

/**
 * sessions.json deserialization: bad JSON / non-object top level / wrong version
 * -> empty ledger (read failures never crash; ledger tolerance discipline);
 * non-array sessions -> empty; dirty entries (missing/non-string session_id)
 * dropped; unknown fields dropped (schema is closed, no pass-through).
 */
export function parseSessionLedgerFile(raw: string | null | undefined): LedgerFileEntry[] {
  if (!raw) return []
  let data: unknown
  try { data = JSON.parse(raw) } catch { return [] }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return []
  const doc = data as Record<string, unknown>
  if (doc.version !== SESSIONS_FILE_VERSION) return []
  if (!Array.isArray(doc.sessions)) return []
  const out: LedgerFileEntry[] = []
  for (const item of doc.sessions) {
    if (typeof item !== 'object' || item === null) continue
    const e = item as Record<string, unknown>
    if (typeof e.session_id !== 'string' || e.session_id === '') continue
    out.push({
      session_id: e.session_id,
      ...(typeof e.handle === 'string' && e.handle !== '' ? { handle: e.handle } : {}),
      ...(typeof e.title === 'string' ? { title: e.title } : {}),
      ...(typeof e.opened_at === 'number' && Number.isFinite(e.opened_at) ? { opened_at: e.opened_at } : {}),
      ...(typeof e.last_opened_at === 'number' && Number.isFinite(e.last_opened_at) ? { last_opened_at: e.last_opened_at } : {}),
      ...(typeof e.cwd === 'string' ? { cwd: e.cwd } : {}),
    })
  }
  return out
}

/** sessions.json serialization (pinned schema; non-array input = empty ledger). */
export function serializeSessionLedgerFile(entries: readonly LedgerFileEntry[]): string {
  return JSON.stringify({ version: SESSIONS_FILE_VERSION, sessions: Array.isArray(entries) ? entries : [] }, null, 2) + '\n'
}

/**
 * id-union merge (plan R4 concurrency contract), key=session_id:
 *   - new id: inserted at the head (MRU);
 *   - existing id: the whole entry with the newer last_opened_at wins (same
 *     millisecond = incoming wins, aligned with "most writers replay one UI
 *     action"); stored entries the request does not mention are kept as-is.
 * Returns a new array; the input is not mutated; non-array input = empty base.
 */
export function mergeLedgerEntries(existing: readonly LedgerFileEntry[], incoming: LedgerFileEntry): LedgerFileEntry[] {
  const base = Array.isArray(existing) ? existing.filter(e => e && typeof e.session_id === 'string') : []
  if (!incoming || typeof incoming.session_id !== 'string' || incoming.session_id === '') return base.slice()
  const idx = base.findIndex(e => e.session_id === incoming.session_id)
  if (idx === -1) return [incoming, ...base]
  const cur = base[idx] as LedgerFileEntry
  const curTs = typeof cur.last_opened_at === 'number' ? cur.last_opened_at : -Infinity
  const incTs = typeof incoming.last_opened_at === 'number' ? incoming.last_opened_at : -Infinity
  const winner = incTs >= curTs ? incoming : cur
  const out = base.slice()
  out[idx] = winner
  return out
}

/**
 * Executor projection (derived display, never persisted into sessions.json):
 * executor_sessions ids declared in grants -> display entries with
 * handle='executor'. An id already in the normal ledger is not projected twice
 * (one id, one row; identity follows grants); cwd/opened_at have no declared
 * source and stay empty (the display layer falls back).
 */
export function mergeExecutorSessions(entries: readonly LedgerFileEntry[], executorIds: readonly string[]): LedgerFileEntry[] {
  const base = Array.isArray(entries) ? entries : []
  const known = new Set(base.map(e => e.session_id))
  const projected: LedgerFileEntry[] = []
  for (const id of Array.isArray(executorIds) ? executorIds : []) {
    if (typeof id !== 'string' || id === '' || known.has(id)) continue
    projected.push({ session_id: id, handle: EXECUTOR_HANDLE })
  }
  return [...projected, ...base]
}
