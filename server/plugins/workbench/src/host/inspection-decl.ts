/**
 * inspection-decl — read the project's inspection declaration (instance ids and
 * declared scan faces) for the console read faces (t261026-10).
 *
 * Why a reader at all: the inspection period archive (inspection-archive.ts) used to
 * derive "instances" from the ledger FILENAMES alone, so the historical doc-face shard
 * files (inspection-doc-face-<hash>-<period>.json) each became an instance (host report
 * 261026, defect A), and the coverage view's face table was hardcoded empty (defect B).
 * Both fixes key on the DECLARATION (inspection.yaml): the five declared instance ids
 * and each instance's scan_face.
 *
 * No second YAML parser: the YAML subset is parsed ONCE by the engine's own loader.
 * This module spawns the engine the same bounded way inspection-dir.ts (t261021-14)
 * resolves the ledger directory — `python3 -c` with cwd=<repo>/server/engine, python
 * chosen by the venv->python3 fallback, an execFile timeout that terminates the child,
 * and an explicit maxBuffer. The engine side resolves the declaration path with its own
 * chain (resolve_project_decl_path: registry entry paths.inspection_decl, else
 * <dirs[0]>/inspection.yaml, fail-closed) and loads it with load_inspection_decl — the
 * parse truth never leaves inspection_decl.py.
 *
 * Precedent checklist vs inspection-dir.ts (review C2, t261026-10):
 *  - bounded spawn (execFile timeout terminates the child; every path terminal):
 *    CARRIED (same 10 s / 1 MB bounds);
 *  - venv->python3 fallback chain: CARRIED;
 *  - fail-closed named errors, no fallback literal: CARRIED (spawn failure, unusable
 *    stdout, engine-reported load failure all resolve to { ok:false, reason });
 *  - success-only TTL cache (15 s), failed resolutions never cached: CARRIED;
 *  - single-flight per repo+key so concurrent calls share one spawn: CARRIED;
 *  - env fast path with a refused relative value: CARRIED for the engine's own test
 *    overlay env SANDBAR_INSPECTION_DECL (coverage_decl_path single-file mode) — a
 *    relative value is refused, mirroring the engine would-open-cwd divergence risk.
 *
 * Degradation contract (fail-closed, named): when the declaration cannot be read the
 * callers keep working — the archive falls back to filename-derived instances with a
 * named declaration_state, and every face id reads the named 'decl-unreadable' marker.
 * Never a guess, never a silent empty.
 */

import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { isAbsolute, join } from 'node:path'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

/** One declared instance: the fields the read faces consume. */
export interface DeclaredInstance {
  id: string
  /** Declared scan_face (may be '' — the declaration defaults it to test). */
  scan_face: string
  enabled: boolean
}

export type InspectionDeclRead =
  | { ok: true; file: string; instances: DeclaredInstance[] }
  | { ok: false; file: string; reason: string }

export interface DeclOpts {
  /** Overrides process.env (tests inject row-specific values). */
  env?: NodeJS.ProcessEnv
  /** Overrides the spawn timeout (tests; default 10 s). */
  timeoutMs?: number
  /** Injection seam for tests: replaces the engine spawn entirely. */
  spawn?: (key: string | null, declPath: string) => Promise<InspectionDeclRead>
}

const ENGINE_TTL_MS = 15_000
const SPAWN_TIMEOUT_MS = 10_000
const MAX_BUFFER_BYTES = 1024 * 1024

/** Single-entry cache of SUCCESSFUL resolutions only, keyed repo+key. */
let cached: { repo: string; key: string; read: InspectionDeclRead; at: number } | null = null
const inflight = new Map<string, Promise<InspectionDeclRead>>()

/** Test seam: drop the cache so a scenario starts from a cold resolver. */
export function resetInspectionDeclCacheForTests(): void {
  cached = null
  inflight.clear()
}

/** The script runs INSIDE the engine's own truth: path resolution chain and YAML
 *  subset parse both stay in inspection_decl.py. argv: <mode> <value> with mode
 *  'key' (registered project key -> resolve_project_decl_path) or 'path'
 *  (default-repo declaration file). */
const DECL_SCRIPT = `
import json, sys
mode, value = sys.argv[1], sys.argv[2]
try:
    from inspection_decl import load_inspection_decl
    if mode == 'key':
        from inspection_decl import resolve_project_decl_path
        p = resolve_project_decl_path(value)
    else:
        from pathlib import Path
        p = Path(value)
    d = load_inspection_decl(p)
    print(json.dumps({"ok": True, "file": str(p), "instances": [
        {"id": i.id, "scan_face": i.scan_face, "enabled": bool(i.enabled)}
        for i in d.instances]}))
except Exception as e:
    print(json.dumps({"ok": False, "file": "", "reason": "%s: %s" % (type(e).__name__, e)}))
`

async function spawnEngineDecl(repo: string, key: string | null, declPath: string, timeoutMs: number): Promise<InspectionDeclRead> {
  const engineDir = join(repo, 'server', 'engine')
  const venvPy = join(engineDir, '.venv', 'bin', 'python')
  const python = existsSync(venvPy) ? venvPy : 'python3'
  try {
    const { stdout } = await execFileP(
      python,
      ['-c', DECL_SCRIPT, key === null ? 'path' : 'key', key === null ? declPath : key],
      { cwd: engineDir, timeout: timeoutMs, maxBuffer: MAX_BUFFER_BYTES, windowsHide: true },
    )
    let parsed: unknown
    try {
      parsed = JSON.parse(stdout.trim())
    } catch {
      return { ok: false, file: '', reason: 'inspection declaration resolver printed unusable stdout (not JSON)' }
    }
    const d = parsed as Record<string, unknown>
    if (d.ok !== true) {
      const reason = typeof d.reason === 'string' && d.reason.trim() !== ''
        ? d.reason
        : 'inspection declaration resolver reported failure without a reason'
      return { ok: false, file: typeof d.file === 'string' ? d.file : '', reason }
    }
    if (!Array.isArray(d.instances)) {
      return { ok: false, file: '', reason: 'inspection declaration resolver payload has no instances list' }
    }
    const instances: DeclaredInstance[] = []
    for (const it of d.instances) {
      if (it === null || typeof it !== 'object') continue
      const o = it as Record<string, unknown>
      const id = typeof o.id === 'string' ? o.id.trim() : ''
      if (id === '') continue
      instances.push({
        id,
        scan_face: typeof o.scan_face === 'string' ? o.scan_face.trim() : '',
        enabled: o.enabled === true,
      })
    }
    return { ok: true, file: typeof d.file === 'string' ? d.file : '', instances }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { ok: false, file: '', reason: `inspection declaration resolver spawn failed: ${msg}` }
  }
}

/**
 * Read the declared inspection instances for a project. `key === null` means the
 * default repo (the anchor fallback) — the declaration is then the repo-root
 * inspection.yaml. Never throws; the result is always tagged.
 */
export async function readInspectionDeclaration(
  repo: string, key: string | null, opts: DeclOpts = {},
): Promise<InspectionDeclRead> {
  const env = opts.env ?? process.env
  // Engine's own single-file test overlay (coverage_decl_path): honor it so the
  // read faces see the same declaration the engine scenarios see. Relative refused.
  const overlay = env.SANDBAR_INSPECTION_DECL ?? ''
  if (overlay !== '') {
    if (!isAbsolute(overlay)) {
      return { ok: false, file: overlay,
        reason: `SANDBAR_INSPECTION_DECL is a relative path (${overlay}) — the engine would resolve it cwd-relative; set an absolute path or unset it` }
    }
    if (opts.spawn) return opts.spawn(null, overlay)
    return spawnEngineDecl(repo, null, overlay, opts.timeoutMs ?? SPAWN_TIMEOUT_MS)
  }
  const cacheKey = key ?? ''
  const now = Date.now()
  if (cached !== null && cached.repo === repo && cached.key === cacheKey && now - cached.at < ENGINE_TTL_MS) {
    return cached.read
  }
  const declPath = join(repo, 'inspection.yaml')
  const inflightKey = `${repo}\u0000${cacheKey}`
  let p = inflight.get(inflightKey)
  if (p === undefined) {
    p = (opts.spawn
      ? opts.spawn(key, declPath)
      : spawnEngineDecl(repo, key, declPath, opts.timeoutMs ?? SPAWN_TIMEOUT_MS))
      .then((r) => {
        // Successes only — a failed resolution is never cached past its own call.
        if (r.ok) cached = { repo, key: cacheKey, read: r, at: Date.now() }
        return r
      })
      .finally(() => { inflight.delete(inflightKey) })
    inflight.set(inflightKey, p)
  }
  return p
}
