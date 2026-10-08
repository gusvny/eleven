/**
 * inspection-disposition — the human exit face for a mechanically-rejected
 * (blocked) inspection ticket (t261008-22, host order 261008, plan v2 Step 3).
 *
 * Two actions, one write face, both host-only (KI-193 gate applied in api.ts before
 * any parse/write; the writer is named by the credential, fixed 'host'; a body `by`
 * only lands as by_claimed — writer_mismatch visible, never silent):
 *   - rerun: `inspection_trigger.py trigger --instance <i> --period <p>
 *     --reopen-reason <reason>` — the EXISTING engine entry (plan red rule: no second
 *     spawn path, no UI-side dedup rules; the engine's named refusals pass through
 *     verbatim, including the in-flight refusal "a live inspection for this period
 *     already exists ... named cancel first, then re-run").
 *   - void:  `inspection_trigger.py void --instance <i> --period <p> --ticket-id <t>
 *     --who host --reason <reason>` — the engine's named void for terminal
 *     blocked-completed tickets (t261008-22; ticket-cancel is a documented no-op on
 *     that population, so void is the engine's own ledger face, not a terminate).
 *
 * Borrowed-surface fault modes (plan v2 §surface 3 — each carried over from
 * inspection-triggers.ts):
 *   - B2 spawn full terminal state: success / spawn error / timeout (SIGTERM -> grace
 *     -> SIGKILL) / any exception path all terminate -> wait -> capture exit; stdout/
 *     stderr drained continuously; child env whitelisted; a receipt that does not
 *     match its shape -> ok:false with a named reason, never trusted blindly.
 *   - B4 read side: malformed rows counted, never silently dropped, never fabricated;
 *     append is a whole-file rewrite tmp->rename — a crash leaves either the old or
 *     the new file.
 *   - B3 delegation: inspection_trigger.py's own fail-closed validation stays the
 *     single truth — this layer only pre-checks shapes and REQUIRES a reason. A
 *     reason-less attempt is refused BY NAME before any spawn or ledger write (zero
 *     side effects — asserted in tests by the spawn/append faces never being called).
 *
 * Attribution ledger: <projects_root>/<key>/inspection/disposition-records.jsonl —
 * one row per attempt (success or failure both keep a name), same family as the
 * t261006-15 trigger-records ledger.
 */

import { spawn } from 'node:child_process'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { PROJECT_KEY_RE } from './project-key.ts'
import {
  type TriggerIo, fsTriggerIo, TRIGGER_INSTANCE_RE, REASON_MAX_CHARS,
  BY_CLAIMED_MAX_CHARS, RECEIPT_EXCERPT_CHARS, TRIGGER_SPAWN_TIMEOUT_MS,
  TRIGGER_KILL_GRACE_MS,
} from './inspection-triggers.ts'
import { LIST_CONTRACTS } from './list-contracts.ts'

/** List cap declared once (t261004-14 discipline): never an inlined number. */
export const DISPOSITION_RECORDS_CAP: number =
  (LIST_CONTRACTS as Record<string, { cap: number }>).inspection_disposition_records.cap as number

/** Period shape (same lexer family as the engine's PERIOD_RE: YYYYMMDD or
 *  YYYYMMDD-<bucket>; whether the period exists is judged by the engine). */
export const DISPOSITION_PERIOD_RE = /^\d{8}(-[1-9]\d*)?$/
/** Ticket-id shape (t<YYMMDD>-<seq>; the ticket's identity is judged by the engine). */
export const DISPOSITION_TICKET_ID_RE = /^t\d{6}-\d{1,4}$/

/** Input bounds (over-bound = a named-criterion refusal, not a silent truncation). */
export const DISPOSITION_REASON_MAX_CHARS = REASON_MAX_CHARS

/** Tail window for the read side (rows are small; 256KB covers hundreds). */
export const DISPOSITION_TAIL_BYTES = 256 * 1024

export type DispositionIo = TriggerIo
export const fsDispositionIo: DispositionIo = fsTriggerIo

/** Ledger file path: env SANDBAR_DISPOSITION_RECORDS_DIR (flat test seam) wins;
 *  default is <projects_root>/<key>/inspection/disposition-records.jsonl. */
export function dispositionRecordsFile(env: NodeJS.ProcessEnv = process.env, key = ''): string {
  const dir = env.SANDBAR_DISPOSITION_RECORDS_DIR
  if (dir) return join(dir, key, 'disposition-records.jsonl')
  const root = env.SANDBAR_PROJECTS_DIR || join(homedir(), '.sandbar', 'projects')
  return join(root, key, 'inspection', 'disposition-records.jsonl')
}

export interface RerunInput {
  project: string
  instance: string
  period: string
  reason: string
}

export interface VoidInput {
  project: string
  instance: string
  period: string
  ticket_id: string
  reason: string
}

export type DispositionValidation<T> =
  | { ok: true; value: T; by_claimed?: string; writer_mismatch?: boolean }
  | { ok: false; error: string }

interface BodyBase {
  project: string
  instance: string
  period: string
  reason: string
}

/** Shared shape pre-check (named criterion: names the failing rule and what arrived;
 *  B3: semantic rules — instance enabled, period state, ticket identity — belong to
 *  inspection_trigger.py). */
function validateBase(body: unknown): DispositionValidation<BodyBase> {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return { ok: false, error: 'body must be a JSON object' }
  }
  const b = body as Record<string, unknown>
  const project = b.project
  if (typeof project !== 'string' || project === '') {
    return { ok: false, error: 'project is required (a non-empty string)' }
  }
  if (!PROJECT_KEY_RE.test(project)) {
    return { ok: false, error: `project shape is invalid: '${project}' (need ^[a-z0-9][a-z0-9-]{0,40}$)` }
  }
  const instance = b.instance
  if (typeof instance !== 'string' || instance === '') {
    return { ok: false, error: 'instance is required (a non-empty string, e.g. integration-tests)' }
  }
  if (!TRIGGER_INSTANCE_RE.test(instance)) {
    return { ok: false, error: `instance shape is invalid: '${instance}' (need ${TRIGGER_INSTANCE_RE.source})` }
  }
  const period = b.period
  if (typeof period !== 'string' || period.trim() === '') {
    return { ok: false, error: 'period is required (a non-empty string, e.g. 20261002)' }
  }
  if (!DISPOSITION_PERIOD_RE.test(period)) {
    return { ok: false, error: `period shape is invalid: '${period}' (need YYYYMMDD or YYYYMMDD-<bucket>)` }
  }
  const reason = b.reason
  if (typeof reason !== 'string' || reason.trim() === '') {
    return { ok: false, error: 'reason is required (a reason-less exit is refused by name — it is the human signature)' }
  }
  if (reason.length > DISPOSITION_REASON_MAX_CHARS) {
    return { ok: false, error: `reason is too long: ${reason.length} chars (cap ${DISPOSITION_REASON_MAX_CHARS})` }
  }
  return { ok: true, value: { project, instance, period, reason } }
}

function byClaim(body: Record<string, unknown>): { by_claimed?: string; writer_mismatch?: boolean } {
  const mismatch = body.by !== undefined && body.by !== null && body.by !== 'host'
  return mismatch
    ? { by_claimed: String(body.by).slice(0, BY_CLAIMED_MAX_CHARS), writer_mismatch: true }
    : {}
}

export function validateRerunInput(body: unknown): DispositionValidation<RerunInput> {
  const base = validateBase(body)
  if (!base.ok) return base
  return { ok: true, value: base.value, ...byClaim(body as Record<string, unknown>) }
}

export function validateVoidInput(body: unknown): DispositionValidation<VoidInput> {
  const base = validateBase(body)
  if (!base.ok) return base
  const b = body as Record<string, unknown>
  const ticket_id = b.ticket_id
  if (typeof ticket_id !== 'string' || ticket_id.trim() === '') {
    return { ok: false, error: 'ticket_id is required (the ticket being voided — void never applies to a whole period blindly)' }
  }
  if (!DISPOSITION_TICKET_ID_RE.test(ticket_id)) {
    return { ok: false, error: `ticket_id shape is invalid: '${ticket_id}' (need t<YYMMDD>-<seq>)` }
  }
  return { ok: true, value: { ...base.value, ticket_id }, ...byClaim(b) }
}

// ---- attribution ledger (one row per attempt, success or failure) ----

export interface DispositionRecord {
  at: number
  by: 'host'
  by_claimed?: string
  writer_mismatch?: boolean
  action: 'rerun' | 'void'
  project: string
  instance: string
  period: string
  ticket_id?: string
  reason: string
  spawn: { ok: boolean; ticket_id?: string; voided?: boolean; error?: string }
}

/** Append one row (atomic: read old -> concat -> tmp -> rename — B4). */
export function appendDispositionRecord(
  io: DispositionIo, env: NodeJS.ProcessEnv, key: string, record: DispositionRecord,
): { ok: true; file: string } | { ok: false; file: string; error: string } {
  const file = dispositionRecordsFile(env, key)
  let existing = ''
  try {
    if (io.existsSync(file)) existing = io.readFileSync(file)
  } catch (err) {
    return { ok: false, file, error: `existing disposition record unreadable: ${err instanceof Error ? err.message : String(err)}` }
  }
  try {
    io.writeFileAtomic(file, existing + JSON.stringify(record) + '\n')
  } catch (err) {
    return { ok: false, file, error: `disposition record write failed: ${err instanceof Error ? err.message : String(err)}` }
  }
  return { ok: true, file }
}

export type DispositionRecordsRead =
  | { ok: true; source: string; rows: DispositionRecord[]; malformed_rows: number; hidden_rows: number }
  | { ok: false; source: string; reason: string }

/** Read side (read-only): tail -> parse line by line (bad lines counted, never
 *  silently dropped, never fabricated) -> explicit newest-first by at -> cap + hidden. */
export function readDispositionRecords(io: DispositionIo, env: NodeJS.ProcessEnv, key: string): DispositionRecordsRead {
  const file = dispositionRecordsFile(env, key)
  if (!io.existsSync(file)) {
    return { ok: false, source: file, reason: 'no disposition record yet (file absent — no rerun or void has been attempted for this project)' }
  }
  let text = ''
  try {
    text = io.readTail ? io.readTail(file, DISPOSITION_TAIL_BYTES) : io.readFileSync(file)
  } catch (err) {
    return { ok: false, source: file, reason: `disposition record unreadable: ${err instanceof Error ? err.message : String(err)}` }
  }
  const rows: (DispositionRecord & { __seq: number })[] = []
  let malformed = 0
  let seq = 0
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    seq += 1
    try {
      const doc = JSON.parse(line) as Record<string, unknown>
      const valid = typeof doc.at === 'number' && Number.isFinite(doc.at)
        && doc.by === 'host' && (doc.action === 'rerun' || doc.action === 'void')
        && typeof doc.instance === 'string' && typeof doc.period === 'string'
        && typeof doc.reason === 'string' && typeof doc.spawn === 'object' && doc.spawn !== null
      if (!valid) { malformed += 1; continue }
      rows.push({ ...(doc as unknown as DispositionRecord), __seq: seq })
    } catch {
      malformed += 1 // torn line / bad JSON: counted and visible, never fabricated
    }
  }
  rows.sort((a, b) => {
    const av = Number.isFinite(a.at) ? a.at : -Infinity
    const bv = Number.isFinite(b.at) ? b.at : -Infinity
    return bv - av || a.__seq - b.__seq
  })
  const hidden = Math.max(0, rows.length - DISPOSITION_RECORDS_CAP)
  return {
    ok: true, source: file,
    rows: rows.slice(0, DISPOSITION_RECORDS_CAP).map(({ __seq, ...r }) => r),
    malformed_rows: malformed, hidden_rows: hidden,
  }
}

// ---- spawn face (B2 full terminal state; single low-level helper, two actions) ----

export type SpawnToolResult =
  | { ok: true; doc: Record<string, unknown> }
  | { ok: false; error: string }

export type SpawnRerunFace = (args: RerunInput) => Promise<SpawnToolResult>
export type SpawnVoidFace = (args: VoidInput) => Promise<SpawnToolResult>

/**
 * Default spawn faces: python3 server/engine/inspection_trigger.py <subcommand …>.
 * Child env whitelisted; stdout/stderr drained continuously; timeout SIGTERM ->
 * grace -> SIGKILL; every path waits the child and captures its exit (the epic-next
 * dropped-terminate lesson). Receipt: a single-line JSON {ok, result|error} on
 * stdout — a receipt that does not match is ok:false with a named reason, never
 * trusted blindly. The engine's named errors surface VERBATIM (prefixed only by the
 * tool name — never reworded, never swallowed: the in-flight refusal text is a
 * ticket-face datum, plan red rule 3).
 */
function spawnInspectionCli(
  env: NodeJS.ProcessEnv, cliArgs: string[],
  opts: { python?: string; script?: string; timeoutMs?: number },
): Promise<SpawnToolResult> {
  const python = opts.python ?? env.SANDBAR_INSPECTION_PYTHON ?? 'python3'
  const script = opts.script ?? join(env.SANDBAR_REPO || process.cwd(), 'server', 'engine', 'inspection_trigger.py')
  const timeoutMs = opts.timeoutMs ?? TRIGGER_SPAWN_TIMEOUT_MS
  return new Promise<SpawnToolResult>((resolve) => {
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(python, [script, ...cliArgs], {
        env: {
          HOME: env.HOME || '',
          PATH: env.PATH || '/usr/bin:/bin',
          // The void/trigger engine face reads the ledger dir from this env — pass
          // it through when the console process carries an explicit override.
          ...(env.SANDBAR_INSPECTION_DIR ? { SANDBAR_INSPECTION_DIR: env.SANDBAR_INSPECTION_DIR } : {}),
          ...(env.SANDBAR_PROJECTS_DIR ? { SANDBAR_PROJECTS_DIR: env.SANDBAR_PROJECTS_DIR } : {}),
          ...(env.DSH_HOME ? { DSH_HOME: env.DSH_HOME } : {}),
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      })
    } catch (err) {
      resolve({ ok: false, error: `spawn failed: ${err instanceof Error ? err.message : String(err)}` })
      return
    }
    let out = ''
    let errText = ''
    let settled = false
    const finish = (r: SpawnToolResult) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (killer) clearTimeout(killer)
      resolve(r)
    }
    let killer: NodeJS.Timeout | undefined
    const killTree = () => {
      try { child.kill('SIGKILL') } catch { /* already exited */ }
    }
    const timer = setTimeout(() => {
      try { child.kill('SIGTERM') } catch { /* already exited */ }
      killer = setTimeout(killTree, TRIGGER_KILL_GRACE_MS)
    }, timeoutMs)
    child.stdout?.on('data', (d: Buffer) => { out += d.toString('utf8') })
    child.stderr?.on('data', (d: Buffer) => { errText += d.toString('utf8') })
    child.on('error', (err) => finish({ ok: false, error: `spawn failed: ${err.message}` }))
    child.on('close', (code) => {
      // Receipt shape check: the last non-empty stdout line (single-line JSON contract).
      // A non-zero exit still tries the receipt first — the tool's named refusal (the
      // in-flight ordering refusal) is more useful than "exit code N".
      const line = out.trim().split('\n').filter(Boolean).pop() || ''
      let doc: { ok?: unknown; result?: unknown; error?: unknown } | null = null
      try { doc = JSON.parse(line) } catch { /* fallthrough */ }
      if (doc && typeof doc === 'object' && doc.ok === true) {
        finish({ ok: true, doc: (doc.result ?? {}) as Record<string, unknown> })
        return
      }
      if (doc && typeof doc === 'object' && doc.ok === false && typeof doc.error === 'string') {
        finish({ ok: false, error: `inspection_trigger.py: ${doc.error}` })
        return
      }
      if (code !== 0) {
        const why = errText.trim().split('\n').pop() || `exit code ${code}`
        finish({ ok: false, error: `inspection_trigger.py failed: ${why}` })
        return
      }
      const why = `receipt is not {ok:...} (got: ${line.slice(0, RECEIPT_EXCERPT_CHARS) || '<empty>'})`
      finish({ ok: false, error: `inspection_trigger.py: ${why}` })
    })
  })
}

export function makeDefaultSpawnRerun(
  env: NodeJS.ProcessEnv = process.env,
  opts: { python?: string; script?: string; timeoutMs?: number } = {},
): SpawnRerunFace {
  return (args) => spawnInspectionCli(env, [
    'trigger', '--instance', args.instance, '--period', args.period,
    '--reopen-reason', args.reason,
  ], opts)
}

export function makeDefaultSpawnVoid(
  env: NodeJS.ProcessEnv = process.env,
  opts: { python?: string; script?: string; timeoutMs?: number } = {},
): SpawnVoidFace {
  // The void signature is named by the credential (fixed 'host' — KI-193 discipline,
  // same as the trigger ledger's by); a caller-reported by never becomes the signature.
  return (args) => spawnInspectionCli(env, [
    'void', '--instance', args.instance, '--period', args.period,
    '--ticket-id', args.ticket_id, '--who', 'host', '--reason', args.reason,
  ], opts)
}

export { TRIGGER_SPAWN_TIMEOUT_MS, TRIGGER_KILL_GRACE_MS }
