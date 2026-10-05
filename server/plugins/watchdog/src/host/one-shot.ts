/**
 * one-shot.ts -- one-shot executor sessions (t261004-30).
 *
 * What: bounded small work must not queue behind the resident session's long
 * turn. The watchdog hands one bounded unit to a one-shot session: wake, read
 * the ledgers, do EXACTLY that one thing, write the result, exit. Three faces:
 *  1. PER-OBJECT lock: the same ticket / request / alert key never has two
 *     sessions at once. The lock is released on exit; an abnormal exit is
 *     reclaimed by timeout (one stuck session must not hold an object forever).
 *  2. ONE parallel cap: admission reads the project concurrency declaration
 *     (host decision 261004). This module is the only read point; no second
 *     knob exists (see readConcurrencyLimit / validateOneShotBlock).
 *  3. All-terminal-states: normal / error / timeout / cancel every exit path
 *     releases the lock and clears the in-flight slot.
 *
 * Structure: pure decision core (deriveObjectKey / admitUnit /
 * reclaimStaleLocks / releaseLock / reapSessions / reapExpiredRuns /
 * validateOneShotBlock) + injected IO (lock file, run journal, session create,
 * turn execution, clock). UT all stubs: zero real host, zero ~/.sandbar, zero
 * ports 3099/7233 -- same discipline as session-create.ts. Adopt is DELIBERATELY
 * absent here: a one-shot session is never declared by a human and never
 * adopted; it is always created fresh and exits.
 */

// ---------- object key (vocabulary twin of engine executor_oneshot.py; a
// drift is pinned red by unit tests on both sides) ----------

export type ObjectKind = 'ticket' | 'request' | 'alert'

export interface OneShotUnit {
  kind: ObjectKind
  /** Object id (ticket id / request id / alert key): 1-120 printable ASCII,
   *  no whitespace. `key` is accepted as an alias (harness seam uses it). */
  id?: string
  key?: string
}

const OBJECT_ID_RE = /^[!-~]{1,120}$/

export type DerivedKey =
  | { ok: true; key: string }
  | { ok: false; error: string }

export function deriveObjectKey(unit: OneShotUnit): DerivedKey {
  const kind = (unit as { kind?: unknown }).kind
  if (kind !== 'ticket' && kind !== 'request' && kind !== 'alert') {
    return { ok: false, error: `unit.kind must be ticket|request|alert (got ${String(kind)})` }
  }
  const id = unit.id ?? unit.key
  if (typeof id !== 'string' || !OBJECT_ID_RE.test(id)) {
    return { ok: false, error: 'unit.id must be 1-120 printable ASCII characters with no whitespace' }
  }
  return { ok: true, key: `${kind}:${id}` }
}

// ---------- lock table (per object; file-backed so a crashed process leaves
// the lock visible; timeout reclaim is the safety net) ----------

export interface LockEntry {
  object_key: string
  session_id: string
  acquired_at: number
  heartbeat_at: number
}

export interface LockTable {
  v: 1
  locks: LockEntry[]
}

export const DEFAULT_LOCK_TIMEOUT_MS = 30 * 60 * 1000

export function lockFilePath(dataDir: string, project: string): string {
  return `${dataDir}/${project}.one-shot-locks.json`
}

export function serializeLockTable(table: LockTable): string {
  return JSON.stringify(table) + '\n'
}

/** Lock-table read: malformed = named error (fail closed -- never silently
 *  treat as empty, that would wash the locks away). */
export function parseLockTable(raw: string): { ok: true; table: LockTable } | { ok: false; error: string } {
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { ok: false, error: `one-shot lock table is not valid JSON: ${e instanceof Error ? e.message : String(e)}` }
  }
  const d = doc as { v?: unknown; locks?: unknown }
  if (!d || d.v !== 1 || !Array.isArray(d.locks)) {
    return { ok: false, error: 'one-shot lock table shape is wrong (expected {v:1, locks:[...]})' }
  }
  for (const l of d.locks) {
    const e = l as Partial<LockEntry>
    if (typeof e.object_key !== 'string' || e.object_key === '' ||
        typeof e.session_id !== 'string' || e.session_id === '' ||
        typeof e.acquired_at !== 'number' || typeof e.heartbeat_at !== 'number') {
      return { ok: false, error: 'one-shot lock table has a malformed lock entry' }
    }
  }
  return { ok: true, table: doc as LockTable }
}

/** Timeout reclaim: a lock whose heartbeat is older than timeoutMs belongs to a
 *  dead session -- remove it and name it (never silently). */
export function reclaimStaleLocks(table: LockTable, nowMs: number, timeoutMs: number):
  { table: LockTable; reclaimed: string[] } {
  const kept: LockEntry[] = []
  const reclaimed: string[] = []
  for (const l of table.locks) {
    if (nowMs - l.heartbeat_at > timeoutMs) {
      reclaimed.push(`${l.object_key} (session ${l.session_id})`)
    } else {
      kept.push(l)
    }
  }
  return { table: { v: 1, locks: kept }, reclaimed }
}

export function findLock(table: LockTable, objectKey: string): LockEntry | undefined {
  return table.locks.find((l) => l.object_key === objectKey)
}

/** Only the holder releases (nobody else can let go of your lock). */
export function releaseLock(table: LockTable, objectKey: string, sessionId: string):
  { ok: true; table: LockTable } | { ok: false; error: string } {
  const lock = findLock(table, objectKey)
  if (!lock) return { ok: false, error: `no lock held on ${objectKey}` }
  if (lock.session_id !== sessionId) {
    return { ok: false, error: `lock on ${objectKey} is held by ${lock.session_id}, not ${sessionId} -- only the holder releases` }
  }
  return { ok: true, table: { v: 1, locks: table.locks.filter((l) => l !== lock) } }
}

// ---------- the parallel cap (the single knob read point) ----------

/**
 * The project concurrency declaration (host decision 261004: an integer 1-10,
 * 0 / "unlimited" = unlimited) has ONE declaration file:
 * `<configDir>/<key>/concurrency.json` under key `max_running`. Absent = the
 * design default 2 (start small). This is the ONLY read point; the
 * Running-tickets ticket must write this same file and reuse this reader --
 * two knobs is a red line.
 */
export function readConcurrencyLimit(
  io: { readText(path: string): Promise<string> },
  file: string,
): Promise<{ ok: true; limit: number | null; source: string } | { ok: false; error: string }> {
  return io.readText(file).then((raw) => {
    let doc: unknown
    try {
      doc = JSON.parse(raw)
    } catch (e) {
      return { ok: false as const, error: `concurrency declaration is not valid JSON: ${e instanceof Error ? e.message : String(e)}` }
    }
    const v = (doc as { max_running?: unknown } | null)?.max_running
    if (v === 'unlimited' || v === 0) return { ok: true as const, limit: null, source: file }
    if (typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 10) {
      return { ok: true as const, limit: v, source: file }
    }
    return { ok: false as const, error: 'concurrency.max_running must be an integer 0-10 (0 = unlimited) or "unlimited"' }
  }).catch((e: unknown) => {
    // Absent = default 2 (the single default place); unreadable (permissions
    // etc.) = named error -- never pretend it was absent.
    const code = (e as { code?: string } | null)?.code
    if (code === 'ENOENT') return { ok: true as const, limit: 2, source: 'default' }
    return { ok: false as const, error: `concurrency declaration unreadable: ${e instanceof Error ? e.message : String(e)}` }
  })
}

/** Admission (pure): held > cap; limit null/<=0 = unlimited. Active = the lock
 *  count (one lock = one in-flight session -- a one-shot session is NOT a
 *  ticket and never consumes a running-ticket slot). */
export function admitUnit(input: {
  objectKey: string
  table: LockTable
  limit: number | null
  nowMs: number
}): { action: 'start' | 'object-held' | 'at-cap'; reason: string } {
  const { objectKey, table, limit } = input
  const held = findLock(table, objectKey)
  if (held) {
    return { action: 'object-held', reason: `object ${objectKey} is locked by session ${held.session_id} since ${held.acquired_at} -- one session per object` }
  }
  if (limit !== null && limit > 0 && table.locks.length >= limit) {
    return { action: 'at-cap', reason: `parallel cap reached (${table.locks.length}/${limit}) -- the unit waits for a slot` }
  }
  void input.nowMs
  return { action: 'start', reason: `admitted (${table.locks.length} active)` }
}

/**
 * The one_shot config block carries NO cap (a cap hiding here would be a
 * second knob = red). Known keys only: enabled / retention_days /
 * lock_timeout_ms. Unknown keys are refused (fail closed, KI-149 family).
 */
export const ONE_SHOT_BLOCK_KEYS = ['enabled', 'retention_days', 'lock_timeout_ms'] as const

export function validateOneShotBlock(block: unknown): { ok: true } | { ok: false; error: string } {
  if (typeof block !== 'object' || block === null || Array.isArray(block)) {
    return { ok: false, error: 'one_shot must be an object ({enabled, retention_days, lock_timeout_ms})' }
  }
  const b = block as Record<string, unknown>
  const unknown = Object.keys(b).filter((k) => !(ONE_SHOT_BLOCK_KEYS as readonly string[]).includes(k))
  if (unknown.length > 0) {
    return { ok: false, error: `Unknown keys rejected (fail-closed; the parallel cap lives only in the shared concurrency declaration, not here): ${unknown.join(', ')}` }
  }
  const problems: string[] = []
  if ('enabled' in b && typeof b.enabled !== 'boolean') problems.push('one_shot.enabled must be a boolean')
  if ('retention_days' in b && (typeof b.retention_days !== 'number' || !Number.isFinite(b.retention_days) || b.retention_days < 0)) {
    problems.push('one_shot.retention_days must be a number >= 0 (0 = never expire by age)')
  }
  if ('lock_timeout_ms' in b && (typeof b.lock_timeout_ms !== 'number' || !Number.isFinite(b.lock_timeout_ms) || b.lock_timeout_ms <= 0)) {
    problems.push('one_shot.lock_timeout_ms must be a positive number (milliseconds)')
  }
  if (problems.length > 0) return { ok: false, error: `watchdog.json one_shot rejected. Problems: ${problems.join('; ')}` }
  return { ok: true }
}

// ---------- run journal + retention (7 days / summary before delete /
// referenced sessions never deleted) ----------

export interface OneShotRunRecord {
  session_id: string
  project: string
  object_key: string
  started_at: number
  ended_at: number
  outcome: 'ok' | 'failed' | 'abandoned'
  summary: string
}

export function runsPath(dataDir: string, project: string): string {
  return `${dataDir}/${project}.one-shot-runs.jsonl`
}

export function reapedPath(dataDir: string, project: string): string {
  return `${dataDir}/${project}.one-shot-reaped.jsonl`
}

/** Malformed rows are counted, never silently dropped (session-create discipline). */
export function readRuns(raw: string): { runs: OneShotRunRecord[]; malformed_rows: number } {
  const runs: OneShotRunRecord[] = []
  let malformed = 0
  for (const line of raw.split('\n')) {
    if (line === '') continue
    try {
      const d = JSON.parse(line) as Partial<OneShotRunRecord>
      if (typeof d.session_id === 'string' && typeof d.object_key === 'string' &&
          typeof d.started_at === 'number' && typeof d.ended_at === 'number' &&
          (d.outcome === 'ok' || d.outcome === 'failed' || d.outcome === 'abandoned')) {
        runs.push(d as OneShotRunRecord)
      } else {
        malformed += 1
      }
    } catch {
      malformed += 1
    }
  }
  return { runs, malformed_rows: malformed }
}

/** Pure reap decision: expired = ended_at older than retentionDays (<=0 =
 *  never reap). Referenced sessions (watchdog config / authorization
 *  declarations / unanswered request owners, unioned by the caller) are NEVER
 *  deleted. A session whose summary fails (summarizeOk=false for the whole
 *  batch's failure injection; per-row in the IO wrapper) is skipped, never
 *  deleted without its summary. */
export function reapSessions(input: {
  sessions: Array<{ session_id: string; ended_at: number }>
  nowMs: number
  retentionDays: number
  referencedSessionIds: ReadonlySet<string>
  summarizeOk: boolean
}): { deleted: string[]; summaries: string[]; skipped: string[] } {
  const { sessions, nowMs, retentionDays, referencedSessionIds, summarizeOk } = input
  if (retentionDays <= 0) return { deleted: [], summaries: [], skipped: [] }
  const cutoff = nowMs - retentionDays * 24 * 60 * 60 * 1000
  const deleted: string[] = []
  const summaries: string[] = []
  const skipped: string[] = []
  for (const s of sessions) {
    if (s.ended_at >= cutoff) continue
    if (referencedSessionIds.has(s.session_id)) continue
    if (!summarizeOk) {
      skipped.push(s.session_id)
      continue
    }
    summaries.push(s.session_id) // the summary is written BEFORE the delete
    deleted.push(s.session_id)
  }
  return { deleted, summaries, skipped }
}

export interface ReapOutcome {
  deleted: number
  kept_referenced: number
  summaries_written: number
  malformed_rows: number
}

/** IO wrapper over reapSessions for the on-disk run journal: per-row summary
 *  append first; an append failure keeps the row (never deletes silently). */
export function reapExpiredRuns(io: {
  append(path: string, line: string): Promise<void>
  writeText(path: string, data: string): Promise<void>
}, input: {
  runsRaw: string
  runsFile: string
  reapedFile: string
  nowMs: number
  retentionDays: number
  referencedSessionIds: ReadonlySet<string>
}): Promise<ReapOutcome> {
  const { runs, malformed_rows } = readRuns(input.runsRaw)
  if (input.retentionDays <= 0) {
    return Promise.resolve({ deleted: 0, kept_referenced: 0, summaries_written: 0, malformed_rows })
  }
  const cutoff = input.nowMs - input.retentionDays * 24 * 60 * 60 * 1000
  const kept: OneShotRunRecord[] = []
  let deleted = 0
  let keptReferenced = 0
  let summaries = 0
  const pending: Promise<void>[] = []
  for (const r of runs) {
    if (r.ended_at >= cutoff) {
      kept.push(r)
      continue
    }
    if (input.referencedSessionIds.has(r.session_id)) {
      keptReferenced += 1
      kept.push(r)
      continue
    }
    deleted += 1
    // Summary before delete; a failed summary keeps the row.
    pending.push(
      io.append(input.reapedFile, JSON.stringify({
        type: 'one-shot-reap-summary', at: input.nowMs,
        session_id: r.session_id, project: r.project, object_key: r.object_key,
        outcome: r.outcome, started_at: r.started_at, ended_at: r.ended_at,
        summary: r.summary,
      }) + '\n').then(
        () => { summaries += 1 },
        () => { kept.push(r); deleted -= 1 },
      ),
    )
  }
  return Promise.all(pending).then(() =>
    io.writeText(input.runsFile, kept.map((r) => JSON.stringify(r) + '\n').join(''))
      .then(() => ({ deleted, kept_referenced: keptReferenced, summaries_written: summaries, malformed_rows })))
}

// ---------- orchestration: the full lifecycle of one bounded unit ----------

export interface OneShotIo {
  readText(path: string): Promise<string>
  writeText(path: string, data: string): Promise<void>
  append(path: string, line: string): Promise<void>
}

/** Session create path (node.ts implements it with the host Session API; tests
 *  inject stubs) -- same shape as session-create.ts SessionCreateIo, but a
 *  one-shot session only ever creates: there is no adopt. */
export interface OneShotSessionIo {
  create(input: { cwd: string; agentPreset: string }): Promise<{ ok: true; sessionId: string } | { ok: false; error: string }>
  /** Run one bounded unit (host-side prompt delivery, wait for the receipt).
   *  outcome.summary = the one-page takeaway. */
  runTurn(sessionId: string): Promise<{ ok: boolean; summary: string }>
}

export type OneShotOutcome =
  | { action: 'done'; sessionId: string; objectKey: string; outcome: 'ok' | 'failed'; summary: string }
  | { action: 'object-held' | 'at-cap'; reason: string }
  | { action: 'refused'; reason: string }

/**
 * One bounded unit: read lock table -> timeout reclaim -> admit -> create
 * session -> take lock -> run -> FINALLY release (normal / error / timeout /
 * cancel all pass through here) -> append the run record. A failed create
 * takes no lock (no session, no lock-leak surface).
 */
export async function runOneShotUnit(deps: {
  project: string
  dataDir: string
  cwd: string
  unit: OneShotUnit
  limit: number | null
  lockTimeoutMs?: number
  presetName?: string
  io: OneShotIo
  sessions: OneShotSessionIo
  nowMs: number
}): Promise<OneShotOutcome> {
  const key = deriveObjectKey(deps.unit)
  if (!key.ok) return { action: 'refused', reason: key.error }
  const lockFile = lockFilePath(deps.dataDir, deps.project)
  let table: LockTable = { v: 1, locks: [] }
  try {
    const raw = await deps.io.readText(lockFile)
    const parsed = parseLockTable(raw)
    if (!parsed.ok) return { action: 'refused', reason: parsed.error }
    const cleaned = reclaimStaleLocks(parsed.table, deps.nowMs, deps.lockTimeoutMs ?? DEFAULT_LOCK_TIMEOUT_MS)
    table = cleaned.table
    if (cleaned.reclaimed.length > 0) {
      await deps.io.writeText(lockFile, serializeLockTable(table))
    }
  } catch (e) {
    const code = (e as { code?: string } | null)?.code
    if (code !== 'ENOENT') {
      return { action: 'refused', reason: `one-shot lock table unreadable: ${e instanceof Error ? e.message : String(e)}` }
    }
  }

  const admission = admitUnit({ objectKey: key.key, table, limit: deps.limit, nowMs: deps.nowMs })
  if (admission.action !== 'start') return { action: admission.action, reason: admission.reason }

  const created = await deps.sessions.create({ cwd: deps.cwd, agentPreset: deps.presetName ?? 'sandbar-executor' })
  if (!created.ok) {
    return { action: 'refused', reason: `one-shot session create failed: ${created.error}` }
  }
  const sessionId = created.sessionId
  table.locks.push({ object_key: key.key, session_id: sessionId, acquired_at: deps.nowMs, heartbeat_at: deps.nowMs })
  await deps.io.writeText(lockFile, serializeLockTable(table))

  let outcome: 'ok' | 'failed' = 'failed'
  let summary = ''
  try {
    const turn = await deps.sessions.runTurn(sessionId)
    outcome = turn.ok ? 'ok' : 'failed'
    summary = turn.summary
  } catch (e) {
    outcome = 'failed'
    summary = `runTurn threw: ${e instanceof Error ? e.message : String(e)}`
  } finally {
    // All terminal states: a throw / cancel (abort bubbles as an exception)
    // still passes through this path and releases the lock.
    try {
      const raw = await deps.io.readText(lockFile)
      const parsed = parseLockTable(raw)
      if (parsed.ok) {
        const rel = releaseLock(parsed.table, key.key, sessionId)
        if (rel.ok) await deps.io.writeText(lockFile, serializeLockTable(rel.table))
      }
    } catch { /* lock file unreadable: timeout reclaim is the net; never mask the outcome */ }
  }

  const record: OneShotRunRecord = {
    session_id: sessionId, project: deps.project, object_key: key.key,
    started_at: deps.nowMs, ended_at: deps.nowMs, outcome, summary,
  }
  try {
    await deps.io.append(runsPath(deps.dataDir, deps.project), JSON.stringify(record) + '\n')
  } catch { /* a failed run-record append never swallows the outcome */ }
  return { action: 'done', sessionId, objectKey: key.key, outcome, summary }
}

/** Settle note path (the watchdog-side one-page-takeaway journal; the engine
 *  settle row is executor_oneshot.py's face). */
export function settleNotePath(dataDir: string, project: string): string {
  return `${dataDir}/${project}.one-shot-settle.jsonl`
}

/** Reference-face collector (referenced sessions are never deleted): sessions
 *  named in the watchdog config + authorization declarations + unanswered
 *  request owners -- the caller feeds the lists, this unions and dedupes. */
export function collectReferencedSessions(inputs: Array<string[] | null | undefined>): Set<string> {
  const out = new Set<string>()
  for (const list of inputs) {
    for (const id of list ?? []) {
      if (typeof id === 'string' && id !== '') out.add(id)
    }
  }
  return out
}

/** Factory defaults for the one_shot config block (config.ts mirrors them; a
 *  drift is pinned by unit tests). */
export function oneShotDefaults(): { enabled: boolean; retention_days: number; lock_timeout_ms: number } {
  return { enabled: true, retention_days: 7, lock_timeout_ms: DEFAULT_LOCK_TIMEOUT_MS }
}
