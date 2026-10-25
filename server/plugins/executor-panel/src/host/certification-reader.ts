/**
 * certification-reader.ts — the Certification tab's read face (t261009-44
 * Slice 2, plan §"the projection seam").
 *
 * What this module is: ONE seam between the panel and the engine's develop
 * projections. The engine-side rules live in server/engine (freeze_state,
 * ticket_wait_state, ticket_outcome, run_verdict); this file never
 * re-implements a count — it spawns the engine interpreter over
 * certification-adapter.py (same-repo relative resolution) and parses ONE
 * strict JSON receipt, then hands the input to the Slice 1 pure model
 * (`deriveCertificationFace`, imported across plugins like the identity
 * module already is). Missing files / malformed rows / engine refusals travel
 * as the adapter's named reasons — nothing is invented here either.
 *
 * Borrow discipline (review C1 — take/leave, made explicit):
 *   CARRIED from executor-grants.ts's spawn face: enginePython venv fallback
 *   chain (SANDBAR_ENGINE_PYTHON → server/engine/.venv/bin/python → python3),
 *   full-termination recovery (success / non-zero exit / timeout kill / spawn
 *   error all settle the Promise, no dangling handles), strict single-JSON
 *   receipt parsing (any malformed receipt = explicit refusal, no guessing).
 *   NOT carried: the grants write-path credential + attribution gate (this is
 *   a READ face — the route is GET-only, no write path exists in this slice)
 *   and the concurrency.ts stale-cache heal (a stateless read, no cache).
 */

import { execFile as execFileCb } from 'node:child_process'
import { enginePython } from './executor-grants.ts'
import { concurrencyProjectsRoot } from './concurrency.ts'
import {
  deriveCertificationFace,
  type CertificationFace,
  type CertificationInput,
} from '../../../workbench/src/client/certification-model.ts'

/** One declared line, as the line picker renders it. */
export interface CertLine {
  line_id?: unknown
  scope?: unknown
  owner?: unknown
}

/** One line's slice of the adapter receipt: an input or a named degradation. */
export type CertLineRead =
  | { ok: true; input: CertificationInput }
  | { ok: false; reason: string }

/** The adapter receipt, validated to shape (never trusted blindly). */
export type CertRead =
  | {
      ok: true
      project: string
      lines: CertLine[]
      per_line: Record<string, CertLineRead>
      meta_notes: string[]
      runs_note: string
      /** t261012-03: the Rounds table's source — the runner's published faces. */
      round_faces: RoundFacesSection
    }
  | {
      ok: false
      reason: string
      /** t261012-03 fault 2: a refusal receipt still carries the round-faces
       *  section when the adapter managed to read it — the Rounds table is
       *  independent of the line declaration's readability. */
      round_faces?: RoundFacesSection
    }

/** The route's answer: the derived face plus the raw input arrays the panel
 *  needs to build links (certs, runs, outcomes ride along verbatim). */
export type CertFaceRead =
  | {
      ok: true
      project: string
      line: string
      lines: CertLine[]
      face: CertificationFace
      raw: CertificationInput
      notes: string[]
      /** t261016-09 (D3): the Rounds table's source travels on the SUCCESS
       *  envelope too. It used to ride only the refusal path, so the page saw
       *  `round_faces === undefined` on every readable receipt and the Rounds
       *  table rendered its no-section banner over an empty tbody. */
      round_faces: RoundFacesSection
    }
  | { ok: false; reason: string; round_faces?: RoundFacesSection }

export type CertReadFace = (
  args: { project: string; line?: string },
  opts?: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv },
) => Promise<CertFaceRead>

/** t261012-03: the adapter's `round_faces` section, validated softly — every
 *  per-file state stays a named state (face / absent / reason); a section the
 *  receipt does not carry degrades to a named section error, never to rows
 *  of zeros. */
export interface RoundFacesSection {
  dir: string
  error?: string
  live?: { ok: true; face: Record<string, unknown> } | { ok: false; reason: string }
  rounds?: Array<Record<string, unknown>>
  older?: number
}

/** t261012-03: the `round` mode's receipt — one round's dialog facts from the
 *  retained evidence. Each absence (no terminal face, no log) is its own
 *  named field, never an empty default. */
export interface RoundRead {
  ok: boolean
  project?: string
  run?: string
  face?: Record<string, unknown> | null
  face_reason?: string | null
  failures?: Record<string, unknown> | null
  failures_absent?: string | null
  wrote?: string[]
  wrote_note?: string
  trigger?: string | null
  trigger_note?: string
  log_path?: string
  log_absent?: string | null
  reason?: string
}

export type CertRoundRead = RoundRead & { ok: true; project: string; run: string }

/** Adapter script path (same-repo relative: src/host -> this file's sibling). */
export function certificationAdapterPath(): string {
  return new URL('./certification-adapter.py', import.meta.url).pathname
}

/** The WRITE adapter's path (t261025-12): promote-adapter.py sits beside the
 *  read adapter — same directory discipline, same spawn face. */
export function promoteAdapterPath(): string {
  return new URL('./promote-adapter.py', import.meta.url).pathname
}


function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** Receipt parsing: the adapter prints ONE JSON line; anything else is an
 *  explicit refusal (the adapter's stderr traceback names itself upstream). */
export function parseCertReceipt(stdout: string): CertRead {
  let doc: unknown
  try {
    doc = JSON.parse(String(stdout).trim() || 'null')
  } catch {
    return { ok: false, reason: 'certification receipt is not valid JSON (no fallback, no invented face)' }
  }
  if (!isObj(doc) || typeof doc.ok !== 'boolean') {
    return { ok: false, reason: 'certification receipt has an unexpected shape (no fallback, no invented face)' }
  }
  if (doc.ok === false) {
    const rfSection = isObj(doc.round_faces) ? doc.round_faces : null
    return {
      ok: false,
      reason: typeof doc.reason === 'string' && doc.reason ? doc.reason : 'certification read refused (reason absent)',
      round_faces: rfSection
        ? {
            dir: typeof rfSection.dir === 'string' ? rfSection.dir : '',
            error: typeof rfSection.error === 'string' ? rfSection.error : undefined,
            live: rfSection && isObj(rfSection.live)
              ? (rfSection.live.ok === true
                ? { ok: true, face: (isObj(rfSection.live.face) ? rfSection.live.face : {}) as Record<string, unknown> }
                : { ok: false, reason: typeof rfSection.live.reason === 'string' ? rfSection.live.reason : 'live face unreadable (reason absent)' })
              : undefined,
            rounds: Array.isArray(rfSection.rounds) ? rfSection.rounds as Array<Record<string, unknown>> : [],
            older: typeof rfSection.older === 'number' && Number.isFinite(rfSection.older) ? rfSection.older : undefined,
          }
        : undefined,
    }
  }
  if (typeof doc.project !== 'string' || !Array.isArray(doc.lines)
    || !isObj(doc.per_line)) {
    return { ok: false, reason: 'certification receipt is missing its lines/per_line face' }
  }
  const perLine: Record<string, CertLineRead> = {}
  for (const [k, v] of Object.entries(doc.per_line)) {
    if (!isObj(v) || typeof v.ok !== 'boolean') {
      return { ok: false, reason: `certification receipt line ${k} has an unexpected shape` }
    }
    if (v.ok === true) {
      perLine[k] = { ok: true, input: v.input as CertificationInput }
    } else {
      perLine[k] = { ok: false, reason: typeof v.reason === 'string' ? v.reason : 'line refused (reason absent)' }
    }
  }
  const section = isObj(doc.round_faces) ? doc.round_faces : null
  return {
    ok: true,
    project: doc.project,
    lines: doc.lines as CertLine[],
    per_line: perLine,
    meta_notes: Array.isArray(doc.meta_notes) ? (doc.meta_notes as string[]) : [],
    runs_note: typeof doc.runs_note === 'string' ? doc.runs_note : '',
    round_faces: {
      dir: typeof section?.dir === 'string' ? section.dir : '',
      error: typeof section?.error === 'string'
        ? section.error
        : (section ? undefined : 'the receipt carries no round_faces section (older adapter) — the Rounds table cannot be drawn from this answer'),
      live: section && isObj(section.live)
        ? (section.live.ok === true
          ? { ok: true, face: (isObj(section.live.face) ? section.live.face : {}) as Record<string, unknown> }
          : { ok: false, reason: typeof section.live.reason === 'string' ? section.live.reason : 'live face unreadable (reason absent)' })
        : undefined,
      rounds: section && Array.isArray(section.rounds) ? section.rounds as Array<Record<string, unknown>> : [],
      older: section && typeof section.older === 'number' && Number.isFinite(section.older) ? section.older : undefined,
    } satisfies RoundFacesSection,
  }
}

/** t261012-03: the `round` mode's receipt parse — strict like its sibling:
 *  ok:false travels with its named reason; an ok:true receipt missing its
 *  facts shape refuses by name. */
export function parseRoundReceipt(stdout: string): RoundRead {
  let doc: unknown
  try {
    doc = JSON.parse(String(stdout).trim() || 'null')
  } catch {
    return { ok: false, reason: 'round receipt is not valid JSON (no fallback, no invented face)' }
  }
  if (!isObj(doc) || typeof doc.ok !== 'boolean') {
    return { ok: false, reason: 'round receipt has an unexpected shape (no fallback, no invented face)' }
  }
  if (doc.ok === false) {
    return { ok: false, reason: typeof doc.reason === 'string' && doc.reason ? doc.reason : 'round read refused (reason absent)' }
  }
  if (typeof doc.project !== 'string' || typeof doc.run !== 'string'
    || !Array.isArray(doc.wrote)) {
    return { ok: false, reason: 'round receipt is missing its project/run/wrote facts' }
  }
  return {
    ok: true,
    project: doc.project,
    run: doc.run,
    face: isObj(doc.face) ? doc.face as Record<string, unknown> : null,
    face_reason: typeof doc.face_reason === 'string' ? doc.face_reason : null,
    failures: isObj(doc.failures) ? doc.failures as Record<string, unknown> : null,
    failures_absent: typeof doc.failures_absent === 'string' ? doc.failures_absent : null,
    wrote: doc.wrote as string[],
    wrote_note: typeof doc.wrote_note === 'string' ? doc.wrote_note : '',
    trigger: typeof doc.trigger === 'string' ? doc.trigger : null,
    trigger_note: typeof doc.trigger_note === 'string' ? doc.trigger_note : '',
    log_path: typeof doc.log_path === 'string' ? doc.log_path : '',
    log_absent: typeof doc.log_absent === 'string' ? doc.log_absent : null,
  }
}

/**
 * Spawn the adapter (full-termination recovery, same four settled paths as
 * the grants spawn face). The project key is validated upstream (route);
 * here it is still passed as ONE argv — no shell, no splicing.
 * t261012-03: generalized to take the whole argv tail so the `round` mode
 * rides the SAME four settled paths — one spawn face, two modes.
 */
/** 261013 (the empty-Rounds report): the adapter reads run headers from
 *  $SANDBAR_RUNS_LEDGER and refuses by name when it is unset (it never guesses
 *  a lane tree root). The panel never set it, so every certification read
 *  failed named and the Rounds table rendered empty. Point it at the project's
 *  runs store (the same projects root the engine reads) when the caller did
 *  not pin one explicitly. */
function withRunsLedger(
  project: string,
  opts: { env?: NodeJS.ProcessEnv },
): { env: NodeJS.ProcessEnv } {
  const env = { ...(opts.env ?? process.env) }
  if (!env.SANDBAR_RUNS_LEDGER) {
    env.SANDBAR_RUNS_LEDGER = concurrencyProjectsRoot(env)
      + '/' + String(project) + '/ledger/scenario-runs.jsonl'
  }
  return { env }
}

type SpawnResult<T> = { parse: (stdout: string) => T; label: string }
function spawnAdapter<T>(
  argvTail: string[],
  spec: SpawnResult<T>,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
  scriptPath: string = certificationAdapterPath(),
): Promise<T | { ok: false; reason: string }> {
  const run = opts.execFileFn ?? execFileCb
  return new Promise((resolve) => {
    let settled = false
    const finish = (r: T | { ok: false; reason: string }): void => {
      if (!settled) { settled = true; resolve(r) }
    }
    try {
      run(enginePython(opts.env), [scriptPath, ...argvTail],
        { timeout: opts.timeoutMs ?? 30_000, maxBuffer: 1_000_000, env: opts.env },
        (err, stdout) => {
          // A non-zero exit may still carry the full JSON receipt on stdout —
          // parseable wins over the error text (same stance as the grants face).
          const out = String(stdout ?? '')
          if (err && out.trim() === '') {
            const killed = (err as NodeJS.ErrnoException & { killed?: boolean }).killed === true
            finish({ ok: false, reason: (killed
              ? `${spec.label} timed out and was killed: `
              : `${spec.label} failed: `)
              + String(err.message ?? err).slice(0, 300) }) // LIST-CAP-OK: error-message length limit, not a list cap
            return
          }
          finish(spec.parse(out))
        })
    } catch (e) {
      finish({ ok: false, reason: `${spec.label} could not spawn: ` + (e instanceof Error ? e.message : String(e)) })
    }
  })
}

export function spawnCertificationRead(
  project: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<CertRead> {
  return spawnAdapter<CertRead>([project], { parse: parseCertReceipt, label: 'certification read' },
    { ...opts, ...withRunsLedger(project, opts) })
}

/** t261012-03: the `round` mode — the dialog's one fetch per open. The run id
 *  is validated HERE too (charset + no `..`), not only adapter-side: a plugin
 *  boundary does not rely on the spawned process alone to refuse garbage. */
const RUN_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
export function spawnCertificationRound(
  project: string,
  runId: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<RoundRead> {
  if (!RUN_ID_RE.test(runId) || runId.includes('..')) {
    return Promise.resolve({ ok: false, reason: `malformed run id ${JSON.stringify(runId.slice(0, 80))}` }) // LIST-CAP-OK: error-message length limit, not a list cap
  }
  return spawnAdapter<RoundRead>(['round', project, runId], { parse: parseRoundReceipt, label: 'round read' },
    { ...opts, ...withRunsLedger(project, opts) })
}

/** Line choice: the query's `line` when given (unknown = named refusal), else
 *  the single declared line; several lines without a choice refuse by name —
 *  the picker exists for exactly that, the route never guesses one. */
export function pickLine(read: CertRead, wanted?: string): { ok: true; line: string } | { ok: false; reason: string } {
  if (read.ok === false) return { ok: false, reason: read.reason }
  const ids = (read.lines ?? []).map((l) => String(l?.line_id ?? '')).filter(Boolean)
  if (wanted && wanted.trim()) {
    const w = wanted.trim()
    if (!ids.includes(w)) {
      return { ok: false, reason: `line '${w}' is not declared (have: ${ids.length ? ids.join(', ') : 'none'})` }
    }
    return { ok: true, line: w }
  }
  if (ids.length === 1) return { ok: true, line: ids[0] }
  return { ok: false, reason: ids.length === 0
    ? 'no line is declared for this project'
    : `several lines are declared (${ids.join(', ')}) — pass ?line=<line-id>` }
}

/** The whole route body: read → pick the line → derive the Slice 1 face. */
export async function certificationFace(
  args: { project: string; line?: string },
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<CertFaceRead> {
  const read = await spawnCertificationRead(args.project, opts)
  if (read.ok === false) return { ok: false, reason: read.reason }
  const pick = pickLine(read, args.line)
  if (pick.ok === false) return { ok: false, reason: pick.reason }
  const one = read.per_line[pick.line]
  if (!one) return { ok: false, reason: `line '${pick.line}' has no receipt slice (adapter inconsistency)` }
  if (one.ok === false) return { ok: false, reason: one.reason }
  const face = deriveCertificationFace(one.input)
  return {
    ok: true,
    project: read.project,
    line: pick.line,
    lines: read.lines,
    face,
    raw: one.input,
    notes: [...read.meta_notes, ...(read.runs_note ? [read.runs_note] : [])],
    // t261016-09 (D3): the section rides the success envelope (see the type).
    round_faces: read.round_faces,
  }
}

// ---- the two controls' faces (t261025-12) --------------------------------

/** The `queue-state` mode's receipt: four named facts about what a queued
 *  round waits on. Every sub-face degrades to its own named entry — the
 *  receipt is ok:true whenever the adapter answered. */
export type QueueStateRead = {
  ok: true
  project: string
  marker: { present: boolean; path: string }
  guard: { held: boolean; path: string }
  in_flight: { running: boolean; run: unknown; note: string | null }
  runners: Array<{ line: string | null; state: string; error?: string }>
}

/** The `promote-preview` mode's receipt: the writer's own validate pass per
 *  line. `promotable` is the count truth; `promoteBlock` carries the first
 *  line's named refusal when nothing is eligible. */
export type PromotePreviewRead =
  | {
      ok: true
      project: string
      lines: Array<Record<string, unknown>>
      promotable: number
      promoteBlock: string
    }
  | { ok: false; reason: string }

/** The `promote-latest` mode's receipt: the newest promotion row read back
 *  from the delivery ledger (null when none yet — an answer, not a refusal). */
export type PromoteLatestRead =
  | { ok: true; project: string; promotion: Record<string, unknown> | null; promotions: number }
  | { ok: false; reason: string }

/** The WRITE adapter's receipt: the recorded row, or the engine's named
 *  refusal verbatim (never translated, never genericized). */
export type PromoteWriteRead =
  | { ok: true; row: Record<string, unknown> }
  | { ok: false; reason: string }

function parseNamedReceipt(stdout: string, label: string): { ok: false; reason: string } | { ok: true; doc: Record<string, unknown> } {
  let doc: unknown
  try {
    doc = JSON.parse(String(stdout).trim() || 'null')
  } catch {
    return { ok: false, reason: `${label} receipt is not valid JSON (no fallback, no invented face)` }
  }
  if (!isObj(doc) || typeof doc.ok !== 'boolean') {
    return { ok: false, reason: `${label} receipt has an unexpected shape (no fallback, no invented face)` }
  }
  if (doc.ok === false) {
    return { ok: false, reason: typeof doc.reason === 'string' && doc.reason ? doc.reason : `${label} refused (reason absent)` }
  }
  return { ok: true, doc }
}

export function parseQueueStateReceipt(stdout: string): QueueStateRead | { ok: false; reason: string } {
  const base = parseNamedReceipt(stdout, 'queue-state')
  if (!base.ok) return base
  const d = base.doc
  const marker = isObj(d.marker) ? d.marker : {}
  const guard = isObj(d.guard) ? d.guard : {}
  const flight = isObj(d.in_flight) ? d.in_flight : null
  if (!Array.isArray(d.runners)) {
    return { ok: false, reason: 'queue-state receipt is missing its runners face' }
  }
  return {
    ok: true,
    project: typeof d.project === 'string' ? d.project : '',
    marker: { present: marker.present === true, path: typeof marker.path === 'string' ? marker.path : '' },
    guard: { held: guard.held === true, path: typeof guard.path === 'string' ? guard.path : '' },
    in_flight: flight
      ? { running: flight.running === true, run: flight.run ?? null, note: typeof flight.note === 'string' ? flight.note : null }
      : { running: false, run: null, note: 'in-flight face absent from the receipt' },
    runners: d.runners as QueueStateRead['runners'],
  }
}

export function parsePromotePreviewReceipt(stdout: string): PromotePreviewRead {
  const base = parseNamedReceipt(stdout, 'promote-preview')
  if (!base.ok) return base
  const d = base.doc
  if (!Array.isArray(d.lines) || typeof d.promotable !== 'number' || typeof d.promoteBlock !== 'string') {
    return { ok: false, reason: 'promote-preview receipt is missing its lines/promotable/promoteBlock face' }
  }
  return {
    ok: true,
    project: typeof d.project === 'string' ? d.project : '',
    lines: d.lines as Array<Record<string, unknown>>,
    promotable: d.promotable,
    promoteBlock: d.promoteBlock,
  }
}

export function parsePromoteLatestReceipt(stdout: string): PromoteLatestRead {
  const base = parseNamedReceipt(stdout, 'promote-latest')
  if (!base.ok) return base
  const d = base.doc
  if (typeof d.promotions !== 'number') {
    return { ok: false, reason: 'promote-latest receipt is missing its promotions count' }
  }
  return {
    ok: true,
    project: typeof d.project === 'string' ? d.project : '',
    promotion: isObj(d.promotion) ? d.promotion : null,
    promotions: d.promotions,
  }
}

export function parsePromoteWriteReceipt(stdout: string): PromoteWriteRead {
  const base = parseNamedReceipt(stdout, 'promote write')
  if (!base.ok) return base
  const d = base.doc
  if (!isObj(d.row)) {
    return { ok: false, reason: 'promote write receipt carries no row (adapter inconsistency)' }
  }
  return { ok: true, row: d.row }
}

export function spawnQueueState(
  project: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<QueueStateRead | { ok: false; reason: string }> {
  return spawnAdapter<QueueStateRead>(['queue-state', project], { parse: parseQueueStateReceipt, label: 'queue-state' },
    { ...opts, ...withRunsLedger(project, opts) })
}

export function spawnPromotePreview(
  project: string,
  lineId: string | null,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<PromotePreviewRead> {
  const tail = lineId ? ['promote-preview', project, lineId] : ['promote-preview', project]
  return spawnAdapter<PromotePreviewRead>(tail, { parse: parsePromotePreviewReceipt, label: 'promote-preview' },
    { ...opts, ...withRunsLedger(project, opts) })
}

export function spawnPromoteLatest(
  project: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<PromoteLatestRead> {
  return spawnAdapter<PromoteLatestRead>(['promote-latest', project], { parse: parsePromoteLatestReceipt, label: 'promote-latest' },
    { ...opts, ...withRunsLedger(project, opts) })
}

/** The signed act itself: the WRITE adapter calls the engine's
 *  `promote_buffer` — the panel never reimplements the writer. The signer
 *  travels as ONE argv item; a timeout / crash / non-zero exit with no
 *  receipt all settle as named refusals (full-termination recovery). */
export function spawnPromoteWrite(
  project: string,
  lineId: string,
  signer: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<PromoteWriteRead> {
  return spawnAdapter<PromoteWriteRead>([project, lineId, signer],
    { parse: parsePromoteWriteReceipt, label: 'promote write' },
    { ...opts, ...withRunsLedger(project, opts), timeoutMs: opts.timeoutMs ?? 120_000 },
    promoteAdapterPath())
}
