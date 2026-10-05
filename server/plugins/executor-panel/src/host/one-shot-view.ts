/**
 * one-shot-view.ts -- read-only face for one-shot executor sessions
 * (t261004-30).
 *
 * Data sources (both read-only, never written here):
 *  - settle ledger: `<projects_root>/<key>/ledger/executor-settle.jsonl`
 *    (writer = engine executor_oneshot.py, schema v1: the result a one-shot
 *    session files after finishing one bounded unit);
 *  - watchdog-side run journal and object locks:
 *    `<watchdog_data>/<key>.one-shot-runs.jsonl` and
 *    `<watchdog_data>/<key>.one-shot-locks.json` (writer = watchdog
 *    one-shot.ts).
 *
 * Row semantics (same discipline as recent-actions):
 *  R1 malformed rows are counted, never silently dropped, never invented;
 *  R2 unavailable (file absent/unreadable) -> per-face ok:false + a
 *     human-readable reason naming the source path -- an absent settle ledger
 *     is a real empty (no bounded unit has finished yet); an absent lock file
 *     = no in-flight session;
 *  R3 cap of SETTLE_CAP rows; older rows point at the source file;
 *  R4 the parallel cap is read from exactly one place (concurrency.json, the
 *     same file one-shot.ts admission reads); no second default here.
 *
 * IO fully injected (tests use in-memory stubs; default is fs). Zero engine
 * changes, zero touching of port 3099.
 */

import * as fs from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { PROJECT_KEY_RE } from './project-key.ts'
import { watchdogDataDir } from '../../../watchdog/src/host/config.ts'
import { parseLockTable, readRuns, type LockEntry } from '../../../watchdog/src/host/one-shot.ts'

/** Settle-row display cap (about one screen; older rows stay in the source). */
export const SETTLE_CAP = 20

/** Settle row (read-side mirror of engine executor_oneshot.py schema v1). */
export interface SettleRow {
  v: number
  at: number
  project: string
  ticket: string
  session: string
  result: string
  surface: string
}

export interface OneShotFace {
  /** Settle ledger (newest first, capped at SETTLE_CAP). */
  settles: { ok: true; file: string; rows: SettleRow[]; malformed_rows: number; older_rows: number }
    | { ok: false; file: string; reason: string }
  /** Object locks (the in-flight face). Absent file = no in-flight session. */
  locks: { ok: true; file: string; entries: LockEntry[] }
    | { ok: false; file: string; reason: string }
  /** Run journal (newest first, capped at SETTLE_CAP). */
  runs: { ok: true; file: string; rows: ReturnType<typeof readRuns>['runs']; malformed_rows: number }
    | { ok: false; file: string; reason: string }
  /** Parallel cap (the single knob: concurrency.json; absent = default 2,
   *  the same default admission uses). */
  cap: { limit: number | null; source: string; error?: string }
}

/** IO seam (tests inject an in-memory stub; default is fs). */
export interface OneShotIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
}

export const fsOneShotIo: OneShotIo = {
  existsSync: fs.existsSync,
  readFileSync: (f) => fs.readFileSync(f, 'utf8'),
}

/** Settle ledger path (same shape as the engine executor_oneshot.settle_file;
 *  the cross-language drift is pinned by tests on both sides):
 *  SANDBAR_PROJECTS_DIR > SANDBAR_PANEL_DIR > the instance projects root, then
 *  <root>/<key>/ledger/executor-settle.jsonl; SANDBAR_ONESHOT_SETTLE_DIR =>
 *  flat test seam. */
export function oneShotSettleFile(env: NodeJS.ProcessEnv = process.env, key = ''): string {
  const dirOverride = env.SANDBAR_ONESHOT_SETTLE_DIR
  if (dirOverride) return join(dirOverride, key + '.jsonl')
  const root = env.SANDBAR_PROJECTS_DIR || env.SANDBAR_PANEL_DIR
    || (env.DSH_HOME && env.DSH_HOME !== join(env.HOME || '', '.dsh')
      ? join(env.DSH_HOME, 'sandbar', 'projects')
      : join(env.HOME || homedir(), '.sandbar', 'projects'))
  return join(root, key, 'ledger', 'executor-settle.jsonl')
}

function readJsonl<T>(io: OneShotIo, file: string, accept: (d: Record<string, unknown>) => T | null):
  { rows: T[]; malformed_rows: number } | { error: string } {
  if (!io.existsSync(file)) return { error: 'absent' }
  let raw: string
  try {
    raw = io.readFileSync(file)
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) }
  }
  const rows: T[] = []
  let malformed = 0
  for (const line of raw.split('\n')) {
    if (line === '') continue
    try {
      const row = accept(JSON.parse(line) as Record<string, unknown>)
      if (row) rows.push(row)
      else malformed += 1
    } catch {
      malformed += 1
    }
  }
  return { rows, malformed_rows: malformed }
}

function acceptSettle(d: Record<string, unknown>): SettleRow | null {
  if (d.v !== 1 || typeof d.at !== 'number' || typeof d.project !== 'string' ||
      typeof d.ticket !== 'string' || typeof d.session !== 'string' ||
      typeof d.result !== 'string' || typeof d.surface !== 'string') return null
  return d as unknown as SettleRow
}

function instanceRootOf(env: NodeJS.ProcessEnv): string {
  return env.DSH_HOME && env.DSH_HOME !== join(env.HOME || '', '.dsh')
    ? join(env.DSH_HOME, 'sandbar', 'projects')
    : join(env.HOME || homedir(), '.sandbar', 'projects')
}

function watchdogConfigDirOf(env: NodeJS.ProcessEnv): string {
  return env.SANDBAR_WATCHDOG_DIR || join(env.HOME || homedir(), '.sandbar', 'projects')
}

/** Assemble the whole one-shot read face (every unavailable face degrades
 *  explicitly; never rendered as an empty state pretending "all fine"). */
export function readOneShotFace(io: OneShotIo, env: NodeJS.ProcessEnv, key: string): OneShotFace {
  if (!PROJECT_KEY_RE.test(key)) {
    const reason = 'project key shape invalid: ' + JSON.stringify(key).slice(0, 60) // LIST-CAP-OK: error-message length limit, not a list cap
    return {
      settles: { ok: false, file: '', reason },
      locks: { ok: false, file: '', reason: 'project key shape invalid' },
      runs: { ok: false, file: '', reason: 'project key shape invalid' },
      cap: { limit: 2, source: 'default' },
    }
  }
  const settleFile = oneShotSettleFile(env, key)
  const settlesRaw = readJsonl(io, settleFile, acceptSettle)
  const settles = 'error' in settlesRaw
    ? { ok: false as const, file: settleFile, reason: settlesRaw.error === 'absent'
        ? 'no one-shot settle ledger yet (no bounded unit has finished for this project)'
        : 'settle ledger unreadable: ' + settlesRaw.error }
    : {
        ok: true as const, file: settleFile,
        rows: settlesRaw.rows.slice(-SETTLE_CAP).reverse(),
        malformed_rows: settlesRaw.malformed_rows,
        older_rows: Math.max(0, settlesRaw.rows.length - SETTLE_CAP),
      }

  const dataDir = watchdogDataDir(env)
  const lockFile = join(dataDir, key + '.one-shot-locks.json')
  let locks: OneShotFace['locks']
  if (!io.existsSync(lockFile)) {
    locks = { ok: true as const, file: lockFile, entries: [] }
  } else {
    const parsed = parseLockTable(io.readFileSync(lockFile))
    locks = parsed.ok
      ? { ok: true as const, file: lockFile, entries: parsed.table.locks }
      : { ok: false as const, file: lockFile, reason: 'lock table unreadable: ' + parsed.error }
  }

  const runsFile = join(dataDir, key + '.one-shot-runs.jsonl')
  let runs: OneShotFace['runs']
  if (!io.existsSync(runsFile)) {
    runs = { ok: false as const, file: runsFile, reason: 'no one-shot run journal yet' }
  } else {
    const parsed = readRuns(io.readFileSync(runsFile))
    runs = { ok: true as const, file: runsFile, rows: parsed.runs.slice(-SETTLE_CAP).reverse(), malformed_rows: parsed.malformed_rows }
  }

  const capFile = join(watchdogConfigDirOf(env), key, 'concurrency.json')
  let cap: OneShotFace['cap']
  if (!io.existsSync(capFile)) {
    cap = { limit: 2, source: 'default' }
  } else {
    try {
      const v = (JSON.parse(io.readFileSync(capFile)) as { max_running?: unknown }).max_running
      if (v === 'unlimited' || v === 0) cap = { limit: null, source: capFile }
      else if (typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 10) cap = { limit: v, source: capFile }
      else cap = { limit: null, source: capFile, error: 'max_running must be an integer 0-10 (0 = unlimited) or "unlimited"' }
    } catch (e) {
      cap = { limit: null, source: capFile, error: 'concurrency.json unreadable: ' + (e instanceof Error ? e.message : String(e)) }
    }
  }
  return { settles, locks, runs, cap }
}
