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
    }
  | { ok: false; reason: string }

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
    }
  | { ok: false; reason: string }

export type CertReadFace = (
  args: { project: string; line?: string },
  opts?: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv },
) => Promise<CertFaceRead>

/** Adapter script path (same-repo relative: src/host -> this file's sibling). */
export function certificationAdapterPath(): string {
  return new URL('./certification-adapter.py', import.meta.url).pathname
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
    return { ok: false, reason: typeof doc.reason === 'string' && doc.reason ? doc.reason : 'certification read refused (reason absent)' }
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
  return {
    ok: true,
    project: doc.project,
    lines: doc.lines as CertLine[],
    per_line: perLine,
    meta_notes: Array.isArray(doc.meta_notes) ? (doc.meta_notes as string[]) : [],
    runs_note: typeof doc.runs_note === 'string' ? doc.runs_note : '',
  }
}

/**
 * Spawn the adapter (full-termination recovery, same four settled paths as
 * the grants spawn face). The project key is validated upstream (route);
 * here it is still passed as ONE argv — no shell, no splicing.
 */
export function spawnCertificationRead(
  project: string,
  opts: { execFileFn?: typeof execFileCb; timeoutMs?: number; env?: NodeJS.ProcessEnv } = {},
): Promise<CertRead> {
  const run = opts.execFileFn ?? execFileCb
  return new Promise((resolve) => {
    let settled = false
    const finish = (r: CertRead): void => {
      if (!settled) { settled = true; resolve(r) }
    }
    try {
      run(enginePython(opts.env), [certificationAdapterPath(), project],
        { timeout: opts.timeoutMs ?? 30_000, maxBuffer: 1_000_000, env: opts.env },
        (err, stdout) => {
          // A non-zero exit may still carry the full JSON receipt on stdout —
          // parseable wins over the error text (same stance as the grants face).
          const out = String(stdout ?? '')
          if (err && out.trim() === '') {
            const killed = (err as NodeJS.ErrnoException & { killed?: boolean }).killed === true
            finish({ ok: false, reason: (killed
              ? 'certification read timed out and was killed: '
              : 'certification read failed: ')
              + String(err.message ?? err).slice(0, 300) }) // LIST-CAP-OK: error-message length limit, not a list cap
            return
          }
          finish(parseCertReceipt(out))
        })
    } catch (e) {
      finish({ ok: false, reason: 'certification read could not spawn: ' + (e instanceof Error ? e.message : String(e)) })
    }
  })
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
  }
}
