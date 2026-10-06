/**
 * session-ledger-file.ts - host read/write face of sessions.json, the
 * per-project session ledger file (console-ui UI-5, t261005-06; source of
 * truth: the 261004 chat identity / session-handle design note under
 * notes/discussions/, section 2.2).
 *
 * The declaration lives at `<projects_root>/<key>/sessions.json`, in the same
 * family as executor-grants.json / watchdog.json (project-level ledger,
 * host-only write). localStorage is demoted to a cache (lossy; rebuilt from
 * the project file). Schema and the pure-function face live in
 * src/shared/session-handles.ts.
 *
 * Borrowing ledger (from executor-panel/src/host/executor-grants.ts; the
 * landed form of the review R2 table - carried / not carried, per item):
 *   - Carried: root resolution chain SANDBAR_PROJECTS_DIR > SANDBAR_WATCHDOG_DIR
 *     > instanceProjectsRoot(); atomic write (validate -> tmp -> re-read the
 *     bytes and re-validate -> rename; any refusal removes tmp and leaves the
 *     on-disk file byte-identical); read-side tolerance (missing/bad file ->
 *     empty ledger, never throws).
 *   - Not carried as an auth guarantee: the EXECUTOR_SURFACE lock - the surface
 *     is caller-self-reported (KI-193), so this module keeps it only as a
 *     DECLARED refusal behavior (guarded by an injection test), not as security.
 *   - Not carried: a concurrency write lock - grants has none to carry;
 *     sessions.json converges through the id-union merge (pure
 *     mergeLedgerEntries, plan R4 contract); the same-millisecond lost-update
 *     window is accepted and declared.
 *   - Not carried: hot reload / file watcher - the reader is the client, which
 *     fetches on demand (plan R5 contract); no long-lived runtime consumes the
 *     KI-198-family "saved but not live" face here.
 *   - Not carried: an append-only audit ledger - updated_by/updated_at inside
 *     the file is enough at this scale; the KI-193 "source differs from
 *     declaration" alarm is the caller's (route layer) duty, which echoes the
 *     self-reported surface back.
 *
 * KI-193 stance (plan R1, declared here - never silent): the POST route on top
 * of this module is a plugin write endpoint and inherits the KI-193 exposure
 * (the console token gate does not cover plugin routes). This module invents no
 * plugin-local credential; it does shape validation + declared refusal +
 * records the self-reported source. The structural fix (an identity face for
 * write endpoints) is KI-193's own ticket, outside this one.
 */

import { existsSync, mkdirSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { instanceProjectsRoot } from '../../../watchdog/src/host/config.ts'
import {
  assignHandles,
  SESSIONS_FILE_VERSION,
  mergeLedgerEntries,
  parseSessionLedgerFile,
  serializeSessionLedgerFile,
} from '../shared/session-handles.ts'
import type { LedgerFileEntry } from '../shared/session-handles.ts'

/** Typed refusal: status = suggested HTTP status (403 declared refusal / 400 bad shape). */
export class SessionLedgerError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'SessionLedgerError'
    this.status = status
  }
}

/** Declaration root (same chain as executor-grants.ts grantsConfigDir;
 *  SANDBAR_PANEL_DIR is not carried - the session ledger belongs to the
 *  project-ledger family, the panel directory is not its fallback). */
export function sessionLedgerConfigDir(env: NodeJS.ProcessEnv = process.env): string {
  return env.SANDBAR_PROJECTS_DIR || env.SANDBAR_WATCHDOG_DIR || instanceProjectsRoot(env)
}

/** Absolute path of the project session ledger file (the truth path acceptance reads back). */
export function sessionLedgerPath(key: string, env: NodeJS.ProcessEnv = process.env): string {
  return join(sessionLedgerConfigDir(env), key, 'sessions.json')
}

/** Path of the executor declaration file (same root file as executor-grants.ts - read-only for executor_sessions). */
function grantsPath(key: string, env: NodeJS.ProcessEnv): string {
  return join(sessionLedgerConfigDir(env), key, 'executor-grants.json')
}

export interface LedgerFileRead {
  ok: boolean
  file: string
  /** File mtime (ms; plan R5 freshness contract: the reply carries it so a
   *  display face can show staleness later). */
  mtime: number | null
  entries: LedgerFileEntry[]
}

/** Read the ledger file: missing file/bad JSON/wrong shape -> ok:true + empty
 *  entries (tolerance discipline: an empty ledger beats a crash); stat failure
 *  -> mtime null. entries is always an array. */
export function readLedgerFile(key: string, env: NodeJS.ProcessEnv = process.env): LedgerFileRead {
  const file = sessionLedgerPath(key, env)
  let mtime: number | null = null
  try { mtime = statSync(file).mtimeMs } catch { /* missing file is the normal case */ }
  let raw: string | null = null
  try {
    if (existsSync(file)) raw = readFileSync(file, 'utf8')
  } catch { raw = null }
  return { ok: true, file, mtime, entries: parseSessionLedgerFile(raw) }
}

/** Read the declared executor sessions (read-only executor_sessions from
 *  grants; missing file/bad JSON -> empty list, never throws - a grants-side
 *  fault must not take the session list down). */
export function readExecutorSessionIds(key: string, env: NodeJS.ProcessEnv = process.env): string[] {
  try {
    if (!existsSync(grantsPath(key, env))) return []
    const doc = JSON.parse(readFileSync(grantsPath(key, env), 'utf8')) as { executor_sessions?: unknown }
    const ids = doc?.executor_sessions
    if (!Array.isArray(ids)) return []
    return ids.filter((s): s is string => typeof s === 'string' && s !== '')
  } catch { return [] }
}

/** Entry validation before a write (second gate after the route layer; returns [normalized, error]). */
export function validateSessionEntry(body: unknown): [LedgerFileEntry, string | null] {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return [{} as LedgerFileEntry, `body must be a JSON object (got ${body === null ? 'null' : typeof body})`]
  }
  const b = body as Record<string, unknown>
  if (typeof b.session_id !== 'string' || b.session_id === '') {
    return [{} as LedgerFileEntry, 'session_id must be a non-empty string']
  }
  if (b.session_id.length > 256) {
    return [{} as LedgerFileEntry, `session_id over the 256-char limit (got ${b.session_id.length})`]
  }
  // Declared refusal (KI-193 stance: not auth, a declared behavior — a write
  // carrying the executor identity is always refused and never recorded, self-report
  // included; the injection test guards this).
  if (b.surface === 'executor-session') {
    return [{} as LedgerFileEntry, 'writes carrying the executor identity are refused: the session ledger is a host-only face']
  }
  const out: LedgerFileEntry = { session_id: b.session_id }
  if (b.handle !== undefined) {
    if (typeof b.handle !== 'string' || b.handle === '') return [{} as LedgerFileEntry, 'handle must be a non-empty string when present']
    out.handle = b.handle
  }
  if (b.title !== undefined) {
    if (typeof b.title !== 'string') return [{} as LedgerFileEntry, 'title must be a string when present']
    out.title = b.title.slice(0, 500)
  }
  for (const k of ['opened_at', 'last_opened_at'] as const) {
    if (b[k] !== undefined) {
      if (typeof b[k] !== 'number' || !Number.isFinite(b[k])) {
        return [{} as LedgerFileEntry, `${k} must be a finite number (ms timestamp) when present`]
      }
      out[k] = b[k]
    }
  }
  if (b.cwd !== undefined) {
    if (typeof b.cwd !== 'string') return [{} as LedgerFileEntry, 'cwd must be a string when present']
    out.cwd = b.cwd
  }
  return [out, null]
}

export interface SaveEntryResult {
  ok: boolean
  file: string
  entries: LedgerFileEntry[]
  /** The entry's final handle in the written file (assignment lands here: a
   *  normal entry missing a handle gets the short-code ladder; the executor
   *  fixed name is never rewritten). */
  handle: string
}

/**
 * Register one session entry (id-union merge + atomic write). Any refusal:
 * tmp removed, on-disk file byte-identical, SessionLedgerError with a plain
 * reason. Missing directories are created (mkdir -p semantics, same as the
 * grants write path).
 */
export function saveSessionEntry(
  key: string,
  entry: LedgerFileEntry,
  env: NodeJS.ProcessEnv = process.env,
): SaveEntryResult {
  const [normalized, err] = validateSessionEntry(entry)
  if (err !== null) {
    // Declared refusal (KI-193): an executor-identity write gets its own 403
    // (the route layer passes the status through); every other shape error is a
    // 400. The surface is self-reported — this is a declared behavior, not auth.
    const refused = typeof entry === 'object' && entry !== null && (entry as Record<string, unknown>).surface === 'executor-session'
    throw new SessionLedgerError(refused ? 403 : 400, err)
  }
  const file = sessionLedgerPath(key, env)
  const current = readLedgerFile(key, env).entries
  // Handle assignment lands here: an existing handle is kept (idempotent); a
  // missing handle gets the pure-function ladder (collision extension inside
  // assignHandles). The executor fixed name never enters the code space.
  const merged = mergeLedgerEntries(current, normalized)
  // assignHandles is idempotent: entries with a handle are untouched, missing
  // ones get codes (the incoming entry included); the executor fixed name sits
  // in the used set from the start and never enters the code space.
  const withHandles = assignHandles(merged)
  const finalEntry = withHandles.find(e => e.session_id === normalized.session_id) ?? normalized
  const serialized = serializeSessionLedgerFile(withHandles)
  const tmp = file + '.tmp'
  try {
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(tmp, serialized, 'utf8')
    // Re-read the bytes and re-validate: a corrupted tmp never reaches the disk (grants discipline).
    const back = parseSessionLedgerFile(readFileSync(tmp, 'utf8'))
    if (!back.some(e => e.session_id === normalized.session_id)) {
      throw new SessionLedgerError(500, 'atomic-write self-check failed: the written bytes do not round-trip to the saved entry')
    }
    renameSync(tmp, file)
  } catch (e) {
    try { if (existsSync(tmp)) unlinkSync(tmp) } catch { /* tmp cleanup failure never masks the main error */ }
    throw e
  }
  return { ok: true, file, entries: withHandles, handle: finalEntry.handle ?? '' }
}

/** Re-export of the file schema version (route-layer replies; single source). */
export { SESSIONS_FILE_VERSION }
