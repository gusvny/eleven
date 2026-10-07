/**
 * inspection-triggers — the on-demand full-library inspection trigger write face
 * (t261006-15, plan D3/D4).
 *
 * Computation core of POST /sandbar-executor-panel/api/inspection/trigger (api.ts is
 * the HTTP shell). Permission and attribution (261004 host ruling): the executor
 * CANNOT trigger — an on-demand full review is host-only. The route sits behind the
 * panel's KI-193 write credential gate (method-based, applied in api.ts before any
 * parse/write). The writer is named by the credential, fixed 'host'; a body `by` only
 * lands as by_claimed (writer_mismatch visible, never silent — auditSource precedent).
 * The attribution account lives in the project's own directory (same family as the
 * executor action ledger):
 *   <projects_root>/<key>/inspection/trigger-records.jsonl
 * This is a DIFFERENT ledger from t261006-12's reviewed-file ledger (this one records
 * "who triggered, when, what scope, why" — not "which files were reviewed").
 *
 * Borrowed-surface fault modes (plan §1b, each landed here):
 *  - B2 spawn full terminal state: success / spawn error / timeout (SIGTERM -> grace ->
 *    SIGKILL) / any exception path all terminate -> wait -> capture exit; stdout/stderr
 *    drained continuously (pipes never clog); child env whitelisted; a receipt that
 *    does not match its shape -> ok:false with a named reason, never trusted blindly
 *    (defaultSpawnCaller precedent).
 *  - B4 read side: malformed rows counted, never silently dropped, never fabricated;
 *    missing/malformed at sorts last; the cap comes from the list contract; append is
 *    a whole-file rewrite tmp->rename (session-ledger-file.ts precedent) — a crash
 *    leaves either the old or the new file, never a torn line; a torn line found at
 *    read time is counted and visible.
 *  - B3 delegation: inspection_trigger.py's own fail-closed validation of
 *    instance/period stays the single truth — this layer only pre-checks shapes and
 *    requires a reason (the tool has no reason flag; the reason lives in this ledger).
 *    The tool's named errors are surfaced verbatim, never swallowed or reworded.
 */

import { spawn } from 'node:child_process'
import { join } from 'node:path'
import * as fs from 'node:fs'
import { homedir } from 'node:os'
import { PROJECT_KEY_RE } from './project-key.ts'
import { LIST_CONTRACTS } from './list-contracts.ts'

/** List cap declared once (t261004-14 discipline): never an inlined number. */
export const TRIGGER_RECORDS_CAP: number = LIST_CONTRACTS.inspection_trigger_records.cap as number

/** Instance shape (same whitelist family as the project key); whether the instance is
 *  enabled is judged by inspection_trigger.py — this layer does not copy that rule. */
export const TRIGGER_INSTANCE_RE = /^[a-z0-9][a-z0-9-]{0,40}$/

/** Input bounds (over-bound = a named-criterion refusal, not a silent truncation). */
export const SCOPE_MAX_CHARS = 200
export const REASON_MAX_CHARS = 500

/** t261006-15 payload bounds (not list caps; declared by name per the t261004-14
 *  binding rule): the echoed by-claim and the malformed-receipt excerpt are field
 *  bounds on what lands in one record line, never a list truncation. */
export const BY_CLAIMED_MAX_CHARS = 100
export const RECEIPT_EXCERPT_CHARS = 200

/** Read-side tail window: rows are small (<=1KB); 256KB covers hundreds of rows,
 *  far beyond the display cap. */
export const TAIL_BYTES = 256 * 1024

export interface TriggerIo {
  existsSync(file: string): boolean
  readFileSync(file: string): string
  /** Whole-file atomic rewrite (tmp->rename inside the implementation; injectable for tests). */
  writeFileAtomic(file: string, content: string): void
  /** Tail read (production path; falls back to readFileSync). */
  readTail?(file: string, maxBytes: number): string
}

function fsWriteAtomic(file: string, content: string): void {
  // The record append face owns creating the project account directory — a fresh
  // project's first trigger must succeed (arbitrate gen0 Red 2: the tmp write hit
  // ENOENT on <projects>/<key>/inspection/ before the rename ever ran).
  fs.mkdirSync(join(file, '..'), { recursive: true })
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`
  fs.writeFileSync(tmp, content)
  try {
    fs.renameSync(tmp, file)
  } catch (err) {
    try { fs.unlinkSync(tmp) } catch { /* a failed tmp cleanup must not mask the original error */ }
    throw err
  }
}

function fsReadTail(file: string, maxBytes: number): string {
  const fd = fs.openSync(file, 'r')
  try {
    const size = fs.fstatSync(fd).size
    const start = Math.max(0, size - maxBytes)
    const len = size - start
    const buf = Buffer.alloc(len)
    fs.readSync(fd, buf, 0, len, start)
    let text = buf.toString('utf8')
    // The first line is probably cut by the window: drop it (a torn JSON counts as
    // malformed anyway — dropping it here is the honest reading).
    if (start > 0) text = text.slice(text.indexOf('\n') + 1)
    return text
  } finally {
    fs.closeSync(fd) // full terminal state: the fd closes on every path
  }
}

export const fsTriggerIo: TriggerIo = {
  existsSync: fs.existsSync,
  readFileSync: (f) => fs.readFileSync(f, 'utf8'),
  writeFileAtomic: fsWriteAtomic,
  readTail: fsReadTail,
}

/** Ledger file path: env SANDBAR_TRIGGER_RECORDS_DIR (flat test seam) wins; default
 *  is <projects_root>/<key>/inspection/trigger-records.jsonl. */
export function triggerRecordsFile(env: NodeJS.ProcessEnv = process.env, key = ''): string {
  const dir = env.SANDBAR_TRIGGER_RECORDS_DIR
  if (dir) return join(dir, key, 'trigger-records.jsonl')
  const root = env.SANDBAR_PROJECTS_DIR || join(homedir(), '.sandbar', 'projects')
  return join(root, key, 'inspection', 'trigger-records.jsonl')
}

export interface TriggerInput {
  project: string
  instance: string
  scope: string
  reason: string
}

export type TriggerValidation =
  | { ok: true; value: TriggerInput; by_claimed?: string; writer_mismatch?: boolean }
  | { ok: false; error: string }

/** Shape pre-check (named criterion: names the failing rule and what arrived; B3:
 *  semantic rules belong to inspection_trigger.py). */
export function validateTriggerInput(body: unknown): TriggerValidation {
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
  const scope = b.scope
  if (typeof scope !== 'string' || scope.trim() === '') {
    return { ok: false, error: 'scope is required (a non-empty string, e.g. "server/plugins only")' }
  }
  if (scope.length > SCOPE_MAX_CHARS) {
    return { ok: false, error: `scope is too long: ${scope.length} chars (cap ${SCOPE_MAX_CHARS})` }
  }
  const reason = b.reason
  if (typeof reason !== 'string' || reason.trim() === '') {
    return { ok: false, error: 'reason is required (why now — it is recorded with the trigger)' }
  }
  if (reason.length > REASON_MAX_CHARS) {
    return { ok: false, error: `reason is too long: ${reason.length} chars (cap ${REASON_MAX_CHARS})` }
  }
  const mismatch = b.by !== undefined && b.by !== null && b.by !== 'host'
  return {
    ok: true,
    value: { project, instance, scope, reason },
    ...(mismatch ? { by_claimed: String(b.by).slice(0, BY_CLAIMED_MAX_CHARS), writer_mismatch: true } : {}),
  }
}

/** One attribution row. The spawn slot records what actually happened to that spawn
 *  (an attempt is recorded, success or failure — both keep a name). */
export interface TriggerRecord {
  at: number
  by: 'host'
  by_claimed?: string
  writer_mismatch?: boolean
  project: string
  instance: string
  scope: string
  reason: string
  spawn: { ok: boolean; ticket_id?: string; error?: string }
}

/** Append one row (atomic: read old -> concat -> tmp -> rename). A crash leaves the
 *  old or the new file, never a torn line. */
export function appendTriggerRecord(
  io: TriggerIo, env: NodeJS.ProcessEnv, key: string, record: TriggerRecord,
): { ok: true; file: string } | { ok: false; file: string; error: string } {
  const file = triggerRecordsFile(env, key)
  let existing = ''
  try {
    if (io.existsSync(file)) existing = io.readFileSync(file)
  } catch (err) {
    return { ok: false, file, error: `existing trigger record unreadable: ${err instanceof Error ? err.message : String(err)}` }
  }
  try {
    io.writeFileAtomic(file, existing + JSON.stringify(record) + '\n')
  } catch (err) {
    return { ok: false, file, error: `trigger record write failed: ${err instanceof Error ? err.message : String(err)}` }
  }
  return { ok: true, file }
}

export type TriggerRecordsRead =
  | { ok: true; source: string; rows: TriggerRecord[]; malformed_rows: number; hidden_rows: number }
  | { ok: false; source: string; reason: string }

/**
 * Read side (read-only): tail read -> parse line by line (bad lines counted, never
 * silently dropped, never fabricated) -> EXPLICIT newest-first by at (missing/malformed
 * at sorts last; equal at keeps file order, stable) -> cap + hidden count.
 */
export function readTriggerRecords(io: TriggerIo, env: NodeJS.ProcessEnv, key: string): TriggerRecordsRead {
  const file = triggerRecordsFile(env, key)
  if (!io.existsSync(file)) {
    return { ok: false, source: file, reason: 'no trigger record yet (file absent — no on-demand review has been started for this project)' }
  }
  let text = ''
  try {
    text = io.readTail ? io.readTail(file, TAIL_BYTES) : io.readFileSync(file)
  } catch (err) {
    return { ok: false, source: file, reason: `trigger record unreadable: ${err instanceof Error ? err.message : String(err)}` }
  }
  const rows: (TriggerRecord & { __seq: number })[] = []
  let malformed = 0
  let seq = 0
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    seq += 1
    try {
      const doc = JSON.parse(line) as Record<string, unknown>
      const valid = typeof doc.at === 'number' && Number.isFinite(doc.at)
        && doc.by === 'host' && typeof doc.instance === 'string'
        && typeof doc.scope === 'string' && typeof doc.reason === 'string'
        && typeof doc.spawn === 'object' && doc.spawn !== null
      if (!valid) { malformed += 1; continue }
      rows.push({ ...(doc as unknown as TriggerRecord), __seq: seq })
    } catch {
      malformed += 1 // torn line / bad JSON: counted and visible, never fabricated
    }
  }
  rows.sort((a, b) => {
    const av = Number.isFinite(a.at) ? a.at : -Infinity
    const bv = Number.isFinite(b.at) ? b.at : -Infinity
    return bv - av || a.__seq - b.__seq // missing/malformed at last; equal at keeps file order (stable)
  })
  const hidden = Math.max(0, rows.length - TRIGGER_RECORDS_CAP)
  return {
    ok: true, source: file,
    rows: rows.slice(0, TRIGGER_RECORDS_CAP).map(({ __seq, ...r }) => r),
    malformed_rows: malformed, hidden_rows: hidden,
  }
}

// ---- spawn face (B2 full terminal state) ----

export interface SpawnReceipt {
  ok: true
  ticket_id?: string
}
export type SpawnResult = SpawnReceipt | { ok: false; error: string }
export type SpawnTriggerFace = (args: TriggerInput) => Promise<SpawnResult>

/** Spawn timeout (a trigger starts one workflow; the RPC is normally sub-second —
 *  30s is an explicit bound, not the expected duration). */
export const TRIGGER_SPAWN_TIMEOUT_MS = 30_000
/** Grace after SIGTERM before SIGKILL (teardown must not wait forever). */
export const TRIGGER_KILL_GRACE_MS = 5_000

/**
 * Default spawn face: python3 server/engine/inspection_trigger.py trigger --instance <id>
 * (--repo-root is not passed: the tool anchors at its own repo; project attribution is
 * this ledger's job and the project repo anchor belongs to the archive read side — the
 * two responsibilities stay separate). Child env whitelisted; stdout/stderr drained
 * continuously; timeout SIGTERM -> grace -> SIGKILL; every path waits the child and
 * captures its exit (the epic-next dropped-terminate lesson). Receipt: a single-line
 * JSON {ok, result|error} on stdout (client.py/scan_schedule.py contract) — a receipt
 * that does not match is ok:false with a named reason, never trusted blindly.
 */
export function makeDefaultSpawnTrigger(
  env: NodeJS.ProcessEnv = process.env,
  opts: { python?: string; script?: string; timeoutMs?: number } = {},
): SpawnTriggerFace {
  const python = opts.python ?? env.SANDBAR_INSPECTION_PYTHON ?? 'python3'
  const script = opts.script ?? join(env.SANDBAR_REPO || process.cwd(), 'server', 'engine', 'inspection_trigger.py')
  const timeoutMs = opts.timeoutMs ?? TRIGGER_SPAWN_TIMEOUT_MS
  return (args) => new Promise<SpawnResult>((resolve) => {
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(python, [script, 'trigger', '--instance', args.instance], {
        env: {
          HOME: env.HOME || '',
          PATH: env.PATH || '/usr/bin:/bin',
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
    const finish = (r: SpawnResult) => {
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
      // Receipt shape check: take the last non-empty stdout line (single-line JSON
      // contract). A non-zero exit still tries the receipt first — the tool's named
      // error (e.g. "instance not enabled") is more useful than "exit code N".
      const line = out.trim().split('\n').filter(Boolean).pop() || ''
      let doc: { ok?: unknown; result?: unknown; error?: unknown } | null = null
      try { doc = JSON.parse(line) } catch { /* fallthrough */ }
      if (doc && typeof doc === 'object' && doc.ok === true && code === 0) {
        const r = doc.result as Record<string, unknown> | undefined
        const ticketId = r && typeof r.ticket_id === 'string' ? r.ticket_id : undefined
        finish({ ok: true, ...(ticketId ? { ticket_id: ticketId } : {}) })
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
      const why = `receipt is not {ok:true,...} (got: ${line.slice(0, RECEIPT_EXCERPT_CHARS) || '<empty>'})`
      finish({ ok: false, error: `inspection_trigger.py: ${why}` })
    })
  })
}
