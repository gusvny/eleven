/**
 * one-shot-privilege.ts -- the approval-gated, privilege-scoped ignition for
 * one-shot executor units (t261006-06).
 *
 * What: the one-shot vehicle (one-shot.ts) had no caller and no privilege
 * surface. This module is the pure decision core for the missing two faces:
 *
 *  1. APPROVAL GATE: a unit is spawned only for a request that a human
 *     answered on the panel (the request ledger is the approval truth;
 *     answer rows are append-only and the writer is the server-derived
 *     'host', KI-193). The gate reads the ledger directly (one-way file read
 *     via the shared instance root -- no code import from the panel plugin,
 *     no cycle); any malformed row, including a torn (truncated) last line,
 *     fails the gate closed with a named count.
 *  2. PRIVILEGE SURFACE: elevation is expressed as a declared dedicated
 *     preset (the only channel the host Session API 0.1.5 accepts: create
 *     carries {cwd, agentPreset} and nothing else). The declaration file is
 *     HUMAN-authored (<configDir>/<key>/one-shot-privilege.json) -- agents
 *     have no write path to it and the spawn body must never carry a preset
 *     or a scope (smuggled keys are refused by name; no self-elevation).
 *     The grant expires (max_ttl_ms from the answer's at).
 *  3. ONE EXECUTION PER APPROVAL: the approval is CONSUMED. A request id
 *     that already has a run journal row or a granted privilege-audit row is
 *     refused by name, naming the consuming run. The check is against the
 *     append-only journal + audit, never the mutable lock table.
 *  4. AUDIT BEFORE RUN: the audit row is appended before the session is
 *     created; an append failure refuses the spawn (a privileged execution
 *     without its audit row must not happen). Every attempt, admitted or
 *     refused, lands an audit row.
 *
 * Structure: pure functions + injected reads, same discipline as one-shot.ts
 * (UT all stubs: zero real host, zero ~/.sandbar, zero ports 3099/7233).
 */

import { readRuns, runsPath, type OneShotRunRecord, type OneShotOutcome, type OneShotUnit } from './one-shot.ts'

// ---------- privilege declaration (human-authored; the only preset source) ----------

export interface OneShotPrivilegeDeclaration {
  v: 1
  /** The dedicated high-privilege agent preset the spawned session is
   *  created with (the only elevation channel the host API accepts). */
  preset: string
  /** The writable roots the unit's declared scope is limited to. Each must
   *  be an absolute path. Empty = the project grants no privilege roots and
   *  every spawn is refused (privilege is opt-in, never implied). */
  allowed_roots: string[]
  /** Grant lifetime in ms, counted from the human answer's `at`. */
  max_ttl_ms: number
}

export type PrivilegeDeclVerdict =
  | { ok: true; decl: OneShotPrivilegeDeclaration }
  | { ok: false; error: string }

export const PRIVILEGE_DECL_FILE = 'one-shot-privilege.json'

export const PRIVILEGE_DECL_KEYS = ['v', 'preset', 'allowed_roots', 'max_ttl_ms'] as const

export function privilegeDeclPath(configDir: string, project: string): string {
  return `${configDir}/${project}/${PRIVILEGE_DECL_FILE}`
}

export function validatePrivilegeDeclaration(block: unknown): PrivilegeDeclVerdict {
  if (typeof block !== 'object' || block === null || Array.isArray(block)) {
    return { ok: false, error: 'one-shot privilege declaration must be an object ({v, preset, allowed_roots, max_ttl_ms})' }
  }
  const d = block as Record<string, unknown>
  const problems: string[] = []
  // Unknown keys are refused (fail-closed, KI-149 family): a knob hiding in
  // this declaration would be a second privilege surface.
  const unknown = Object.keys(d).filter((k) => !(PRIVILEGE_DECL_KEYS as readonly string[]).includes(k))
  if (unknown.length > 0) problems.push(`unknown keys rejected: ${unknown.join(', ')}`)
  if (d.v !== 1) problems.push('v must be 1')
  if (typeof d.preset !== 'string' || d.preset === '' || d.preset.length > 120) {
    problems.push('preset must be a non-empty string (<=120 chars)')
  }
  if (!Array.isArray(d.allowed_roots)) {
    problems.push('allowed_roots must be an array of absolute paths')
  } else if (d.allowed_roots.length === 0) {
    // The registered contract pins it at the declaration face: an empty grant
    // is a malformed declaration (privilege is opt-in -- absent/empty both
    // refuse, by name, never silently unprivileged).
    problems.push('allowed_roots must grant at least one absolute path (an empty declaration refuses every spawn)')
  } else {
    for (const r of d.allowed_roots) {
      if (typeof r !== 'string' || !r.startsWith('/') || r.length === 1 || r.includes('..')) {
        problems.push(`allowed_roots entry must be an absolute path without '..' (got ${JSON.stringify(r)})`)
      }
    }
  }
  if (typeof d.max_ttl_ms !== 'number' || !Number.isFinite(d.max_ttl_ms) || d.max_ttl_ms <= 0 || !Number.isInteger(d.max_ttl_ms)) {
    problems.push('max_ttl_ms must be a positive integer (milliseconds)')
  }
  if (problems.length > 0) {
    return { ok: false, error: `one-shot privilege declaration rejected. Problems: ${problems.join('; ')}` }
  }
  return {
    ok: true,
    decl: {
      v: 1,
      preset: d.preset as string,
      allowed_roots: d.allowed_roots as string[],
      max_ttl_ms: d.max_ttl_ms as number,
    },
  }
}

/** Parse + validate the declaration file content (read injected). Absent or
 *  malformed = named refusal, never "no privilege needed". */
export function loadPrivilegeDeclaration(raw: string | null): PrivilegeDeclVerdict {
  if (raw === null) {
    return { ok: false, error: `one-shot privilege declaration absent (${PRIVILEGE_DECL_FILE}) -- privilege is opt-in; a spawn without a declaration is refused, never silently unprivileged` }
  }
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch (e) {
    return { ok: false, error: `one-shot privilege declaration is not valid JSON: ${e instanceof Error ? e.message : String(e)}` }
  }
  return validatePrivilegeDeclaration(doc)
}

// ---------- request ledger (the approval truth; read one-way) ----------

export interface LedgerRequestRow {
  type: 'request'
  id: string
  at: number
  project: string
  kind: string
  expires_at: number | null
  raised_by: string
}

export interface LedgerAnswerRow {
  type: 'answer'
  answer_for: string
  at: number
  by: string
}

export interface ParsedRequestLedger {
  requests: LedgerRequestRow[]
  answers: LedgerAnswerRow[]
  /** Any unparsable line, INCLUDING a torn (truncated) final line: counted,
   *  never dropped -- a nonzero count fails the gate closed. */
  malformed_rows: number
}

export function parseRequestLedger(raw: string): ParsedRequestLedger {
  const requests: LedgerRequestRow[] = []
  const answers: LedgerAnswerRow[] = []
  let malformed = 0
  for (const line of raw.split('\n')) {
    if (line === '') continue
    try {
      const d = JSON.parse(line) as Record<string, unknown>
      if (d.type === 'request' && typeof d.id === 'string' && typeof d.at === 'number' &&
          typeof d.kind === 'string' && typeof d.raised_by === 'string' &&
          (d.expires_at === null || typeof d.expires_at === 'number')) {
        requests.push(d as unknown as LedgerRequestRow)
      } else if (d.type === 'answer' && typeof d.answer_for === 'string' &&
                 typeof d.at === 'number' && typeof d.by === 'string') {
        answers.push(d as unknown as LedgerAnswerRow)
      } else {
        malformed += 1
      }
    } catch {
      malformed += 1 // torn write / truncated last line lands here, counted
    }
  }
  return { requests, answers, malformed_rows: malformed }
}

// ---------- privilege audit (append-only; every attempt lands a row) ----------

export interface PrivilegeAuditRow {
  at: number
  project: string
  request_id: string
  action: string
  approved_by: string
  scope_roots: string[]
  preset: string
  session_id: string | null
  decision: 'granted' | 'refused' | 'settled'
  reason: string
}

export function privilegeAuditPath(dataDir: string, project: string): string {
  return `${dataDir}/${project}.one-shot-privilege-audit.jsonl`
}

export function buildPrivilegeAuditRow(row: PrivilegeAuditRow): string {
  return JSON.stringify(row) + '\n'
}

// ---------- the approval gate ----------

export type ApprovalGateVerdict =
  | { ok: true; approved_by: string; approved_at: number; scope_roots: string[]; preset: string }
  | { ok: false; error: string }

/**
 * The gate. Every refusal names its reason; a malformed ledger line (torn
 * last line included) fails the whole gate closed. One spawn per approval:
 * a request id seen in the run journal or already granted in the audit is
 * consumed and refused by name (the mutable lock is never the source).
 */
export function checkApprovalGate(input: {
  requestId: string
  action: string
  ledgerRaw: string | null
  runsRaw: string | null
  auditRaw: string | null
  decl: OneShotPrivilegeDeclaration
  nowMs: number
}): ApprovalGateVerdict {
  const { requestId, action, decl, nowMs } = input
  if (action === '' || typeof action !== 'string') {
    return { ok: false, error: 'action must be a non-empty string naming the exact privileged action' }
  }
  if (decl.allowed_roots.length === 0) {
    return { ok: false, error: 'privilege declaration grants no allowed_roots -- a privileged unit cannot be scoped; refusing (privilege is opt-in)' }
  }
  if (input.ledgerRaw === null) {
    return { ok: false, error: `request ledger absent for this project -- no approval exists for ${requestId}` }
  }
  const ledger = parseRequestLedger(input.ledgerRaw)
  if (ledger.malformed_rows > 0) {
    return { ok: false, error: `request ledger has ${ledger.malformed_rows} malformed line(s) (torn write counts) -- gate fails closed, nothing spawns` }
  }
  const request = ledger.requests.find((r) => r.id === requestId)
  if (!request) {
    return { ok: false, error: `request ${requestId} not found in the ledger -- nothing to approve` }
  }
  const answer = ledger.answers.filter((a) => a.answer_for === requestId).sort((a, b) => b.at - a.at)[0]
  if (!answer) {
    return { ok: false, error: `request ${requestId} is unanswered -- the human approval IS the gate; nothing spawns` }
  }
  if (answer.by === request.raised_by) {
    return { ok: false, error: `request ${requestId} was answered by its own raiser (${request.raised_by}) -- self-approval can never ignite a privileged unit` }
  }
  if (request.expires_at !== null && nowMs > request.expires_at) {
    return { ok: false, error: `request ${requestId} expired at ${request.expires_at} -- an expired request is not an approval` }
  }
  const approvedAge = nowMs - answer.at
  if (approvedAge > decl.max_ttl_ms) {
    return { ok: false, error: `privilege grant expired (answer at ${answer.at} + max_ttl_ms ${decl.max_ttl_ms} < now ${nowMs}) -- re-approval required` }
  }
  // Consumed check: append-only journal + audit, never the lock table.
  if (input.runsRaw !== null) {
    const { runs } = readRuns(input.runsRaw)
    const prior = runs.find((r: OneShotRunRecord) => r.object_key === `request:${requestId}`)
    if (prior) {
      return { ok: false, error: `approval for request ${requestId} already consumed by run ${prior.session_id} (started ${prior.started_at}) -- one privileged execution per human approval` }
    }
  }
  if (input.auditRaw !== null) {
    for (const line of input.auditRaw.split('\n')) {
      if (line === '') continue
      try {
        const d = JSON.parse(line) as { request_id?: unknown; decision?: unknown; session_id?: unknown }
        if (d.request_id === requestId && d.decision === 'granted') {
          return { ok: false, error: `approval for request ${requestId} already granted (audit row, session ${String(d.session_id)}) -- one privileged execution per human approval` }
        }
      } catch { /* a torn audit line never widens the gate; the pre-run granted row is checked again by the run-journal branch */ }
    }
  }
  return { ok: true, approved_by: answer.by, approved_at: answer.at, scope_roots: decl.allowed_roots, preset: decl.preset }
}

// ---------- the unit briefing (what the spawned session is told) ----------

/** The turn prompt names the object, the exact action, and the privilege
 *  scope, and states the boundary: anything beyond the scope is refused by
 *  the session itself. */
export function composeUnitBriefing(input: {
  objectKey: string
  action: string
  scopeRoots: string[]
  preset: string
  approvedBy: string
  approvedAt: number
}): string {
  return [
    `Object: ${input.objectKey}.`,
    `Exact action: ${input.action}`,
    `Privilege scope: preset ${input.preset}, writable roots [${input.scopeRoots.join(', ')}], ` +
      `approved by ${input.approvedBy} at ${input.approvedAt}.`,
    'Refuse by name anything beyond this scope and file a request row instead; do not wait for a direct reply.',
  ].join(' ')
}

// ---------- body hygiene (the HTTP layer's smuggled-privilege-key check) ----------

/** Keys a spawn body must never carry: preset and scope come only from the
 *  human-authored declaration -- no self-elevation. Returns the offending
 *  key names (empty = clean). */
export function smuggledPrivilegeKeys(body: Record<string, unknown>): string[] {
  return ['preset', 'scope', 'allowed_roots', 'agentPreset', 'max_ttl_ms'].filter((k) => k in body)
}

// ---------- the spawn face (node.ts wires the IO; tests inject stubs) ----------

export type SpawnOutcome =
  | { ok: true; spawn: OneShotOutcome & { action: 'done' } }
  | { ok: false; status: number; error: string }

/**
 * The orchestration behind POST /sandbar-watchdog/api/one-shot/run: load the
 * declaration, run the gate, land the granted audit row BEFORE the run (an
 * append failure refuses the spawn fail-closed), then admit through the
 * one-shot vehicle. Body-level validation (project shape, request_id, smuggled
 * privilege keys) stays in the HTTP layer; everything that decides privilege
 * lives here.
 */
export async function spawnApprovedUnit(deps: {
  read(path: string): Promise<string | null>
  auditAppend(row: PrivilegeAuditRow): Promise<void>
  runUnit(input: { unit: OneShotUnit; presetName: string; briefing: string }): Promise<OneShotOutcome>
  project: string
  requestId: string
  action: string
  declFile: string
  ledgerFile: string
  runsFile: string
  auditFile: string
  nowMs: number
}): Promise<SpawnOutcome> {
  const refuse = async (status: number, reason: string): Promise<SpawnOutcome> => {
    let auditNote = ''
    try {
      await deps.auditAppend({ at: deps.nowMs, project: deps.project, request_id: deps.requestId,
        action: deps.action, approved_by: '', scope_roots: [], preset: '', session_id: null,
        decision: 'refused', reason })
    } catch (e) {
      auditNote = ` (refusal audit append failed: ${e instanceof Error ? e.message : String(e)})`
    }
    return { ok: false, status, error: reason + auditNote }
  }
  const declRaw = await deps.read(deps.declFile)
  const declV = loadPrivilegeDeclaration(declRaw)
  if (!declV.ok) return refuse(409, declV.error)
  const [ledgerRaw, runsRaw, auditRaw] = await Promise.all([
    deps.read(deps.ledgerFile), deps.read(deps.runsFile), deps.read(deps.auditFile),
  ])
  const gate = checkApprovalGate({
    requestId: deps.requestId, action: deps.action, ledgerRaw, runsRaw, auditRaw,
    decl: declV.decl, nowMs: deps.nowMs,
  })
  if (!gate.ok) return refuse(409, gate.error)
  // Audit BEFORE run: a privileged execution without its audit row must not
  // happen -- an append failure refuses the spawn by name (fail closed).
  try {
    await deps.auditAppend({ at: deps.nowMs, project: deps.project, request_id: deps.requestId,
      action: deps.action, approved_by: gate.approved_by, approved_at: gate.approved_at,
      scope_roots: gate.scope_roots, preset: gate.preset, session_id: null,
      decision: 'granted', reason: 'admitted' })
  } catch (e) {
    return refuse(500, `privilege audit append failed: ${e instanceof Error ? e.message : String(e)} — privileged execution without its audit row is refused fail-closed`)
  }
  const briefing = composeUnitBriefing({
    objectKey: `request:${deps.requestId}`, action: deps.action,
    scopeRoots: gate.scope_roots, preset: gate.preset,
    approvedBy: gate.approved_by, approvedAt: gate.approved_at,
  })
  const outcome = await deps.runUnit({ unit: { kind: 'request', id: deps.requestId }, presetName: gate.preset, briefing })
  if (outcome.action === 'done') {
    await deps.auditAppend({ at: deps.nowMs, project: deps.project, request_id: deps.requestId,
      action: deps.action, approved_by: gate.approved_by, scope_roots: gate.scope_roots,
      preset: gate.preset, session_id: outcome.sessionId, decision: 'settled',
      reason: `${outcome.outcome}: ${outcome.summary}`.slice(0, 300) })
      .catch(() => { /* the run journal already carries the terminal state; never mask the outcome */ })
    return { ok: true, spawn: outcome }
  }
  await deps.auditAppend({ at: deps.nowMs, project: deps.project, request_id: deps.requestId,
    action: deps.action, approved_by: gate.approved_by, scope_roots: gate.scope_roots,
    preset: gate.preset, session_id: null, decision: 'refused', reason: outcome.reason })
    .catch(() => {})
  return { ok: false, status: 409, error: outcome.reason }
}
