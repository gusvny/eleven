/**
 * inspection-dir — the ONE resolver for the inspection ledger directory on the
 * read side (t261021-14).
 *
 * Defect this fixes: `handleInspectionArchive` used to join the project anchor
 * root with 'out'/'inspection' — a second, drifted copy of where the reports
 * live. The writer's truth is `shared.INSPECTION_DIR` in the engine
 * (server/engine/shared.py `_inspection_dir()`):
 *   SANDBAR_INSPECTION_DIR env override  ->  <server/engine>/out/inspection
 * The console host is TypeScript and cannot import the Python constant, so per
 * the t261021-14 spec the location is resolved ONCE through the engine's own
 * resolver via a small bounded subprocess (same borrowed pattern as
 * `runPocCli`, t260910-04), with no second path literal anywhere in JS.
 *
 * Resolver contract:
 *  - env fast path: a non-empty `SANDBAR_INSPECTION_DIR` is used directly —
 *    this is the SAME first branch of the engine's override chain, not a
 *    duplicate decision. Empty string counts as UNSET (matching Python's
 *    falsy-or semantics in `shared._inspection_dir`). A RELATIVE env value is
 *    refused with a named error — Python would resolve it cwd-relative and the
 *    two sides would silently diverge; the read face refuses to guess.
 *  - engine spawn: `import shared; print(shared.INSPECTION_DIR)` with
 *    cwd=<repo>/server/engine, python chosen by the venv->python3 fallback
 *    chain (swim-lane worktrees usually have no checked-in venv). Bounded:
 *    execFile timeout (10 s — the timeout itself terminates the child, so
 *    every spawn path reaches a terminal state) and an explicit maxBuffer
 *    (1 MB — plenty for one path; an unbounded default could abort with
 *    ENOBUF on a chatty traceback exactly when resolution is already failing).
 *  - stdout is trimmed (whitespace/newline) and must be a non-empty ABSOLUTE
 *    path, else a named error — never a silent fallback to any literal.
 *  - cache: only SUCCESSFUL engine resolutions are cached (single entry,
 *    15 s TTL — this sits behind a polled read face, same discipline as the
 *    line-face TTL). A failed resolution is NEVER cached: the next call
 *    re-spawns, so a fixed environment is seen on the very next request.
 *  - every path terminates: env hit, cache hit, spawn ok, spawn timeout,
 *    spawn error, unusable stdout — all resolve to a tagged result; nothing
 *    throws past the caller, no timers/handles outlive a resolution.
 *
 * Re-land note (implement gen3): gen0–gen2 settles persisted only the
 * integration/ files; this module and the node.ts wiring were dropped three
 * times (arbitrations 261021 x3, code-fault). A byte-identical copy of this
 * file and of the node.ts patch lives in .sandbar/reland/ for operator
 * break-glass restore. Content is the reviewed gen0 design, unchanged.
 */

import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

export type InspectionDirResolution =
  | { ok: true; dir: string; source: 'env' | 'engine' }
  | { ok: false; error: string }

export interface ResolveOpts {
  /** Overrides process.env (tests inject row-specific values). */
  env?: NodeJS.ProcessEnv
  /** Overrides the spawn timeout (tests; default 10 s). */
  timeoutMs?: number
}

const ENGINE_TTL_MS = 15_000
const SPAWN_TIMEOUT_MS = 10_000
const MAX_BUFFER_BYTES = 1024 * 1024

/** Single-entry cache of SUCCESSFUL engine resolutions only (see contract). */
let cached: { repo: string; dir: string; at: number } | null = null
/** Single-flight map: concurrent callers share one spawn per repo. */
const inflight = new Map<string, Promise<InspectionDirResolution>>()

/** Test seam: drop the cache so a scenario starts from a cold resolver. */
export function resetInspectionDirCacheForTests(): void {
  cached = null
  inflight.clear()
}

/** Spawn the engine's own resolver and read its answer (bounded, terminal). */
async function spawnEngineResolver(repo: string, timeoutMs: number): Promise<InspectionDirResolution> {
  const poc = join(repo, 'server', 'engine')
  const venvPy = join(poc, '.venv', 'bin', 'python')
  const python = existsSync(venvPy) ? venvPy : 'python3'
  try {
    const { stdout } = await execFileP(
      python,
      ['-c', 'import shared; print(shared.INSPECTION_DIR)'],
      { cwd: poc, timeout: timeoutMs, maxBuffer: MAX_BUFFER_BYTES, windowsHide: true },
    )
    const dir = stdout.trim()
    if (dir === '') {
      return { ok: false, error: 'engine inspection-dir resolver printed nothing usable (empty stdout)' }
    }
    if (!isAbsolute(dir)) {
      return { ok: false, error: `engine inspection-dir resolver returned a non-absolute path (${dir}) — not a usable ledger directory` }
    }
    return { ok: true, dir, source: 'engine' }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { ok: false, error: `inspection-dir resolver spawn failed: ${msg}` }
  }
}

/**
 * Resolve the inspection ledger directory for the console's repo.
 * See the module contract above; never throws — the result is always tagged.
 */
export async function resolveInspectionDir(repo: string, opts: ResolveOpts = {}): Promise<InspectionDirResolution> {
  const env = opts.env ?? process.env
  const override = env.SANDBAR_INSPECTION_DIR ?? ''
  // Empty string == unset, matching Python `os.environ.get(...) or default`.
  if (override !== '') {
    if (!isAbsolute(override)) {
      return {
        ok: false,
        error: `SANDBAR_INSPECTION_DIR is set to a relative path (${override}) — the engine would resolve it cwd-relative; set an absolute path or unset it`,
      }
    }
    return { ok: true, dir: override, source: 'env' }
  }

  const now = Date.now()
  if (cached !== null && cached.repo === repo && now - cached.at < ENGINE_TTL_MS) {
    return { ok: true, dir: cached.dir, source: 'engine' }
  }

  let p = inflight.get(repo)
  if (p === undefined) {
    p = spawnEngineResolver(repo, opts.timeoutMs ?? SPAWN_TIMEOUT_MS)
      .then((r) => {
        // Successes only — a failed resolution is never cached past its own call.
        if (r.ok) cached = { repo, dir: r.dir, at: Date.now() }
        return r
      })
      .finally(() => { inflight.delete(repo) })
    inflight.set(repo, p)
  }
  return p
}
