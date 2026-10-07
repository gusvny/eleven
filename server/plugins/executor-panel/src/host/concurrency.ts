/**
 * concurrency.ts — the project concurrency-limit read/write faces (t261006-17, CL-2a;
 * design §2.1/§7.9).
 *
 * Source-of-truth discipline (ticket scope 1): every number comes from the engine
 * ledger — the read face spawns the engine's read-only entry
 * `server/tools/ticket.py {"op":"concurrency","project":<key>}` (which serves
 * server/engine/concurrency.py read_state under one flock snapshot). The panel
 * NEVER recomputes positions or waited seconds. An absent/malformed declaration or
 * a malformed ledger arrives as the engine's NAMED refusal text, passed through
 * verbatim — never silently turned into an empty list (fail-closed, rule 9).
 *
 * Write face (ticket scope 5): spawn the engine entry
 * `client.py concurrency-limit-write` (contract pinned with the CL-2b engine
 * mini-ticket; shape mirrors executor-grants-write). While CL-2b has not landed the
 * engine answers "unknown subcommand" -> saved:false with the named
 * `engine entry absent` reason — NEVER a fallback to a local direct write
 * (KI-193: the audited `by` must be the engine-observed identity).
 *
 * Fault-mode table (copied from the executor-grants.ts spawn face; each mode
 * declared carried per the review hook): timeout kill / non-zero exit with a
 * parseable receipt / non-zero exit with an empty receipt / malformed receipt /
 * engine absent or temporalio unvendored / maxBuffer overflow — all carried (see
 * the implementation notes below). Row 8 adjusted: a saved:true receipt must also
 * carry the audit_row shape, else it is refused.
 */

import { execFile as execFileCb } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { enginePython } from './executor-grants.ts'
import { instanceProjectsRoot } from '../../../watchdog/src/host/config.ts'

/** server/tools/ticket.py (the read-face entry; resolved like engineClientPath). */
export function engineTicketPath(): string {
  return fileURLToPath(new URL('../../../../tools/ticket.py', import.meta.url))
}

/** Allowed limit values: an int 1..10 or the string "unlimited" (same rule as the
 *  engine's validate_limit). The constants live in ONE table (CONC_LIMITS): the page
 *  embeds it as JSON next to String(limitStep)/String(concChipState) so the UT and
 *  the page always run one implementation (page-logic discipline). */
export const CONC_LIMITS = { min: 1, max: 10, unlimited: 'unlimited' } as const
export const CONCURRENCY_LIMIT_MIN: number = CONC_LIMITS.min
export const CONCURRENCY_LIMIT_MAX: number = CONC_LIMITS.max
export const CONCURRENCY_UNLIMITED: string = CONC_LIMITS.unlimited
/** Holder reason vocabulary (engine concurrency.py REASON_* is the truth source;
 *  human-hold = keeps its slot while waiting for a human signature). */
export const REASON_HUMAN_HOLD = 'human-hold'

export interface ConcurrencyHolder {
  ticket: string
  since: number | null
  reason: string
  held_s: number | null
}

export interface ConcurrencyQueueEntry {
  ticket: string
  position: number
  since: number | null
  waited_s: number | null
}

export interface ConcurrencyFace {
  ok: true
  project: string
  limit: number | null
  unlimited: boolean
  decl: string
  holders: ConcurrencyHolder[]
  queue: ConcurrencyQueueEntry[]
}

export type ConcurrencyRead = ConcurrencyFace | { ok: false; reason: string }

export interface LimitAuditRow {
  ts: number
  by: string
  from: unknown
  to: unknown
}

export type LimitAuditRead =
  | { ok: true; row: LimitAuditRow; file: string }
  | { ok: false; reason: string; file: string }

export interface ConcurrencySaveOk {
  saved: true
  project: string
  limit: number | null
  audit_row: LimitAuditRow
  decl: string
}

export interface ConcurrencySaveFail {
  saved: false
  reason: string
}

export type ConcurrencySaveOutcome = ConcurrencySaveOk | ConcurrencySaveFail

export interface ConcurrencyWritePayload {
  project: string
  limit: number | 'unlimited'
  by: string
  source: Record<string, unknown>
}

export type ConcurrencyWriteFace = (
  payload: ConcurrencyWritePayload,
  opts?: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv },
) => Promise<ConcurrencySaveOutcome>

function isRootOf(env: NodeJS.ProcessEnv): string | undefined {
  // Same injection priority as executor-grants.ts declarationPath: SANDBAR_PROJECTS_DIR
  // > SANDBAR_WATCHDOG_DIR > the instance projects root (non-default instances and
  // lane benches can isolate through env).
  if (env.SANDBAR_PROJECTS_DIR) return String(env.SANDBAR_PROJECTS_DIR).replace(/\/+$/, '')
  if (env.SANDBAR_WATCHDOG_DIR) return String(env.SANDBAR_WATCHDOG_DIR).replace(/\/+$/, '')
  return instanceProjectsRoot(env)
}

/** This project's concurrency declaration path (same root family as the grants
 *  declaration; PANEL_DIR before WATCHDOG_DIR so a panel-scoped test env aligns). */
export function concurrencyDeclarationPath(key: string, env: NodeJS.ProcessEnv = process.env): string {
  const root = env.SANDBAR_PROJECTS_DIR || env.SANDBAR_PANEL_DIR
    || env.SANDBAR_WATCHDOG_DIR || instanceProjectsRoot(env)
  return String(root).replace(/\/+$/, '') + '/' + String(key) + '/concurrency-limit.json'
}

/** The read-face command (argv array; same execFile shape as the grants spawn). */
export function concurrencyReadArgv(key: string): string[] {
  return [engineTicketPath(), JSON.stringify({ op: 'concurrency', project: key })]
}

/** Parse the read receipt: the ticket.py shell {ok:true,result:face} | {ok:false,error}.
 *  Any malformed shape (non-JSON / wrong shape / holders not an array / wrong limit
 *  type) = a named refusal, NEVER an empty ledger. */
export function parseConcurrencyRead(stdout: string): ConcurrencyRead {
  let doc: unknown
  try {
    doc = JSON.parse(String(stdout).trim() || 'null')
  } catch {
    return { ok: false, reason: 'engine concurrency read produced a non-JSON receipt — treated as a refusal, never as an empty ledger' }
  }
  if (typeof doc !== 'object' || doc === null) {
    return { ok: false, reason: 'engine concurrency read receipt is not a JSON object — treated as a refusal' }
  }
  const d = doc as Record<string, unknown>
  if (d.ok !== true) {
    const why = typeof d.error === 'string' && d.error.length > 0
      ? d.error
      : 'engine concurrency read refused without a named reason'
    return { ok: false, reason: why }
  }
  const f = d.result
  if (typeof f !== 'object' || f === null) {
    return { ok: false, reason: 'engine concurrency read receipt carries no result object — treated as a refusal' }
  }
  const face = f as Record<string, unknown>
  const bad = (why: string): ConcurrencyRead =>
    ({ ok: false, reason: 'engine concurrency face shape is wrong: ' + why + ' — treated as a refusal, never an empty ledger' })
  if (typeof face.project !== 'string' || face.project === '') return bad('project must be a non-empty string')
  if (face.limit !== null && (typeof face.limit !== 'number' || !Number.isFinite(face.limit))) return bad('limit must be a number or null')
  if (typeof face.unlimited !== 'boolean') return bad('unlimited must be a boolean')
  if (typeof face.decl !== 'string' || face.decl === '') return bad('decl must be a path string')
  if (!Array.isArray(face.holders)) return bad('holders must be an array')
  if (!Array.isArray(face.queue)) return bad('queue must be an array')
  const holders: ConcurrencyHolder[] = []
  for (const h of face.holders) {
    if (typeof h !== 'object' || h === null || typeof (h as Record<string, unknown>).ticket !== 'string') {
      return bad('every holder needs a ticket string')
    }
    const hh = h as Record<string, unknown>
    holders.push({
      ticket: hh.ticket as string,
      since: typeof hh.since === 'number' ? hh.since : null,
      reason: typeof hh.reason === 'string' ? hh.reason : '',
      held_s: typeof hh.held_s === 'number' ? hh.held_s : null,
    })
  }
  const queue: ConcurrencyQueueEntry[] = []
  for (let i = 0; i < face.queue.length; i++) {
    const e = face.queue[i]
    if (typeof e !== 'object' || e === null || typeof (e as Record<string, unknown>).ticket !== 'string') {
      return bad('every queue entry needs a ticket string')
    }
    const ee = e as Record<string, unknown>
    queue.push({
      ticket: ee.ticket as string,
      // Position: the engine's array order is the truth; the panel never sorts and
      // never recomputes waited seconds.
      position: typeof ee.position === 'number' ? ee.position : i + 1,
      since: typeof ee.since === 'number' ? ee.since : null,
      waited_s: typeof ee.waited_s === 'number' ? ee.waited_s : null,
    })
  }
  return {
    ok: true, project: face.project,
    limit: face.limit as number | null,
    unlimited: face.unlimited as boolean,
    decl: face.decl, holders, queue,
  }
}

/**
 * The read face (production path): spawn `python ticket.py {"op":"concurrency",...}`.
 * Full-termination recovery: success = parse the receipt; non-zero exit but a
 * parseable stdout = parse anyway (the engine prints before exiting); non-zero exit
 * with an empty receipt / timeout kill / spawn failure / malformed receipt = a named
 * {ok:false, reason}. The engine's named refusal text (declaration absent or
 * malformed, malformed ledger) travels verbatim — never a silent empty list.
 */
export function readConcurrency(
  key: string,
  env: NodeJS.ProcessEnv = process.env,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number } = {},
): Promise<ConcurrencyRead> {
  const run = opts.execFileFn ?? execFileCb
  return new Promise((resolve) => {
    let settled = false
    const finish = (r: ConcurrencyRead): void => {
      if (!settled) { settled = true; resolve(r) }
    }
    try {
      // The engine child must read the SAME root the panel family resolves (env
      // alignment): otherwise an isolated bench env (PANEL/WATCHDOG_DIR set,
      // PROJECTS_DIR unset) silently reads the machine default home root.
      const childEnv: NodeJS.ProcessEnv = {
        ...env,
        SANDBAR_PROJECTS_DIR: String(env.SANDBAR_PROJECTS_DIR || env.SANDBAR_PANEL_DIR
          || env.SANDBAR_WATCHDOG_DIR || instanceProjectsRoot(env)),
      }
      run(enginePython(env), concurrencyReadArgv(key),
        { timeout: opts.timeoutMs ?? 15_000, maxBuffer: 1_000_000, env: childEnv },
        (err, stdout) => {
          const out = String(stdout ?? '')
          if (err && out.trim() === '') {
            const killed = (err as NodeJS.ErrnoException & { killed?: boolean }).killed === true
            finish({
              ok: false,
              reason: (killed ? 'engine concurrency read timed out and was killed: ' : 'engine concurrency read failed: ')
                + String(err.message ?? err).slice(0, 300), // LIST-CAP-OK: error-message length limit, not a list cap
            })
            return
          }
          finish(parseConcurrencyRead(out))
        })
    } catch (e) {
      finish({ ok: false, reason: 'engine concurrency read could not spawn: ' + (e instanceof Error ? e.message : String(e)) })
    }
  })
}

/**
 * Data source for the header audit phrase: the LAST line of
 * <root>/<key>/concurrency-limit-audit.jsonl (the same file the engine appends to).
 * A limit never changed = ok:false + the explicit 'never changed' phrase (never an
 * empty string). A malformed line = a named refusal, no guessing.
 */
export function readLastLimitAudit(key: string, env: NodeJS.ProcessEnv = process.env): LimitAuditRead {
  const root = isRootOf(env)
  const file = root ? root + '/' + String(key) + '/concurrency-limit-audit.jsonl' : ''
  if (!root) {
    return { ok: false, reason: 'projects root not resolvable (no SANDBAR_PROJECTS_DIR, no SANDBAR_WATCHDOG_DIR) — the audit phrase is not known', file: '' }
  }
  let text: string
  try {
    text = readFileSync(file, 'utf-8')
  } catch {
    return { ok: false, reason: 'never changed', file }
  }
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l !== '')
  if (lines.length === 0) return { ok: false, reason: 'never changed', file }
  let row: unknown
  try {
    row = JSON.parse(lines[lines.length - 1])
  } catch (e) {
    return { ok: false, reason: 'the last limit-audit line is malformed: ' + (e instanceof Error ? e.message : String(e)), file }
  }
  if (typeof row !== 'object' || row === null
    || typeof (row as Record<string, unknown>).ts !== 'number'
    || typeof (row as Record<string, unknown>).by !== 'string') {
    return { ok: false, reason: 'the last limit-audit line has an unexpected shape (need ts + by)', file }
  }
  const r = row as Record<string, unknown>
  return { ok: true, row: { ts: r.ts as number, by: r.by as string, from: r.from, to: r.to }, file }
}

/** Declaration-existence probe kept for tests (never touches the engine's judgment;
 *  the engine read face owns refusal decisions). */
export function declarationExists(key: string, env: NodeJS.ProcessEnv = process.env): boolean {
  const root = isRootOf(env)
  if (!root) return false
  return existsSync(root + '/' + String(key) + '/concurrency-limit.json')
}

/** Engine write-receipt parsing (mirrors parseEngineReceipt): a boolean `saved` is
 *  required; a saved:true must ALSO carry the audit_row shape (ts/by/from/to) —
 *  "the receipt says saved but the audit row shape is wrong" = refused, no guessing. */
export function parseConcurrencySaveReceipt(stdout: string): ConcurrencySaveOutcome {
  let doc: unknown
  try {
    doc = JSON.parse(String(stdout).trim() || 'null')
  } catch {
    return { saved: false, reason: 'engine concurrency write receipt is not valid JSON (no fallback, declaration untouched)' }
  }
  if (typeof doc !== 'object' || doc === null || typeof (doc as Record<string, unknown>).saved !== 'boolean') {
    return { saved: false, reason: 'engine concurrency write receipt has an unexpected shape (no fallback, declaration untouched)' }
  }
  const d = doc as Record<string, unknown>
  if (d.saved !== true) {
    return { saved: false, reason: typeof d.reason === 'string' && d.reason !== '' ? d.reason : 'engine concurrency write refused without a named reason' }
  }
  const ar = d.audit_row
  if (typeof ar !== 'object' || ar === null
    || typeof (ar as Record<string, unknown>).ts !== 'number'
    || typeof (ar as Record<string, unknown>).by !== 'string') {
    return { saved: false, reason: 'engine concurrency write receipt claims saved:true but carries no audit_row shape — refused (the audit line is part of the contract)' }
  }
  const row = ar as Record<string, unknown>
  return {
    saved: true,
    project: typeof d.project === 'string' ? d.project : '',
    limit: d.limit === null || d.limit === CONCURRENCY_UNLIMITED ? null : typeof d.limit === 'number' ? d.limit : null,
    audit_row: { ts: row.ts as number, by: row.by as string, from: row.from, to: row.to },
    decl: typeof d.decl === 'string' ? d.decl : '',
  }
}

/** Absent-entry detection (the CL-2b system state): client.py answers an unknown
 *  subcommand with a CJK "unknown subcommand" sentence (U+672A U+77E5 U+5B50
 *  U+547D U+4EE4, exit 0). Matching it yields the ticket-pinned named
 *  `engine entry absent` refusal instead of a misleading "engine failure".
 *  The CJK alternative is written as unicode escapes: the copy-language lint
 *  rightly keeps NEW comment/copy faces English, and this is engine data, not copy. */
const ABSENT_ENTRY_RE = new RegExp('\u672a\u77e5\u5b50\u547d\u4ee4'
  + '|unknown (subcommand|op|command)|unrecognized|invalid choice', 'i')

/** Receipt parsing merged with absent-entry detection: a parse failure whose engine
 *  output names an unknown subcommand becomes the named engine-entry-absent refusal. */
export function parseConcurrencySaveReceiptOrAbsent(stdout: string): ConcurrencySaveOutcome {
  const parsed = parseConcurrencySaveReceipt(stdout)
  if (parsed.saved === false && ABSENT_ENTRY_RE.test(String(stdout))) {
    return { saved: false, reason: 'engine entry absent (CL-2b not landed) — nothing written: '
      + parsed.reason.slice(0, 160) } // LIST-CAP-OK: error-message length limit, not a list cap
  }
  return parsed
}

/**
 * The write face (production path): spawn `client.py concurrency-limit-write`
 * (the CL-2b contract). Full termination, same shape as the grants spawn: timeout
 * kill / non-zero exit with an empty receipt / spawn failure / malformed receipt =
 * saved:false named + the no-fallback suffix. An absent engine entry (unknown
 * subcommand) lands as saved:false via parseConcurrencySaveReceiptOrAbsent — the
 * panel never writes the declaration locally.
 */
export function spawnConcurrencyLimitWrite(
  payload: ConcurrencyWritePayload,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<ConcurrencySaveOutcome> {
  const run = opts.execFileFn ?? execFileCb
  const noFallback = ' (KI-193: no fallback, declaration untouched)'
  // Resolved here directly instead of importing engineClientPath — same URL depth,
  // no extra execution surface pulled in.
  const clientPath = fileURLToPath(new URL('../../../../engine/client.py', import.meta.url))
  return new Promise((resolve) => {
    let settled = false
    const finish = (r: ConcurrencySaveOutcome): void => {
      if (!settled) { settled = true; resolve(r) }
    }
    try {
      run(enginePython(opts.env), [clientPath, 'concurrency-limit-write', JSON.stringify(payload)],
        { timeout: opts.timeoutMs ?? 30_000, maxBuffer: 1_000_000 },
        (err, stdout) => {
          const out = String(stdout ?? '')
          if (err && out.trim() === '') {
            const killed = (err as NodeJS.ErrnoException & { killed?: boolean }).killed === true
            finish({
              saved: false,
              reason: (killed ? 'engine concurrency write timed out and was killed: ' : 'engine concurrency write failed: ')
                + String(err.message ?? err).slice(0, 300) + noFallback, // LIST-CAP-OK: error-message length limit, not a list cap
            })
            return
          }
          finish(parseConcurrencySaveReceiptOrAbsent(out))
        })
    } catch (e) {
      finish({ saved: false, reason: 'engine concurrency write could not spawn: ' + (e instanceof Error ? e.message : String(e)) + noFallback })
    }
  })
}

/** One knob step (pure; the page embeds THIS source — the UT and the page always
 *  run one implementation; reads the CONC_LIMITS table from page scope). */
export function limitStep(current: number | 'unlimited', dir: -1 | 1): number | 'unlimited' {
  if (dir === 1) {
    if (current === CONC_LIMITS.unlimited) return CONC_LIMITS.unlimited
    return current >= CONC_LIMITS.max ? CONC_LIMITS.unlimited : current + 1
  }
  if (current === CONC_LIMITS.unlimited) return CONC_LIMITS.max
  return current <= CONC_LIMITS.min ? CONC_LIMITS.min : current - 1
}

/** The three chip states (design §2.1): room to start one / at the limit / over the
 *  limit. Unlimited = there is always room; over = amber. */
export function concChipState(limit: number | null, unlimited: boolean, atWork: number):
  'room' | 'at' | 'over' {
  if (unlimited || limit === null) return 'room'
  if (atWork > limit) return 'over'
  if (atWork === limit) return 'at'
  return 'room'
}
