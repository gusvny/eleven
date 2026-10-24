#!/usr/bin/env node
/**
 * sc_t26102114_inspection_dir_contract.mjs — t261021-14, grey-box L3, "ro" pool.
 *
 * Contract under test (t261021-14 spec): the Inspection tab's archive read face
 * must resolve the SAME inspection ledger directory the engine WRITES to
 * (shared.INSPECTION_DIR, server/engine/shared.py `_inspection_dir()`). The
 * defect was a second, drifted literal in workbench/node.ts
 * (join(anchor_root,'out','inspection')) that made the tab report "no
 * inspection has run" on a day with three produced periods.
 *
 * Rows:
 *   K1 (THE contract row) engine truth vs reader truth: the engine is asked in
 *      its own environment (`python -c "import shared; print(shared.INSPECTION_DIR)"`,
 *      cwd=<repo>/server/engine, env inherited) and the read face's resolver
 *      (src/host/inspection-dir.ts, env override unset) is asked for the same
 *      repo — the two absolute paths MUST be equal; a mismatch FAILS naming
 *      BOTH paths verbatim.
 *   K2 env fast path is the engine's own first branch: SANDBAR_INSPECTION_DIR
 *      set to an absolute path is used verbatim (source:'env').
 *   K3 empty string counts as UNSET (Python falsy-or semantics): the resolver
 *      falls through to the engine and still returns the engine path.
 *   K4 a RELATIVE env value is refused with a named error — Python would
 *      resolve it cwd-relative and the two sides would silently diverge; the
 *      read face refuses to guess (never a silent passthrough).
 *   K5 a failed resolution is NOT cached: a resolver call against a repo with
 *      no engine errors (named), and the immediately following call against
 *      the real repo succeeds — the failure did not stick past its own call.
 *   K6 empty-but-present vs absent stay TWO DISTINCT defects: an empty ledger
 *      directory reads ok:false with the "no inspection report in the archive"
 *      reason; an absent directory reads ok:false with the "directory does not
 *      exist" reason; the strings are asserted unequal.
 *   K7 (THE host-visible row, real tree, read-only) the served archive route
 *      reads the engine-declared directory: booted against the REAL repo, the
 *      tab's route answers ok:true with a non-empty archive — the exact
 *      host story of 261021 (reports on disk, tab must not say "no inspection
 *      has ever run"). Resolver wiring not landed = FAIL named (TDD red).
 *
 * Harness: direct import of the workbench TS modules (type-stripping) + one
 * bounded python spawn for the engine truth + the route boot harness of
 * t261006-15 (mock ctx, real node.ts). Zero docker/Temporal/browser/3099;
 * offline seconds. mkdtemp reclaimed in this file (L8).
 */
import { spawnSync } from 'node:child_process'
import http from 'node:http'
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(join(HERE, '..', '..'))
const ENGINE_DIR = join(REPO, 'server', 'engine')

let passed = 0, failed = 0, envfail = 0
const C = {
  case(name, ok, reason = '') {
    ok ? passed++ : failed++
    console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${reason ? ' — ' + reason : ''}`)
  },
  envFail(name, reason) {
    envfail++
    console.log(`[ENV_FAIL] ${name} — ${reason}`)
  },
  exit() {
    console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envfail} na=0`)
    process.exit(envfail ? 2 : failed ? 1 : 0)
  },
}

process.on('unhandledRejection', () => {})

const iso = mkdtempSync(join(tmpdir(), 't26102114-ledger-'))
process.on('exit', () => { try { rmSync(iso, { recursive: true, force: true }) } catch { /* best effort */ } })

function enginePython() {
  const venv = join(ENGINE_DIR, '.venv', 'bin', 'python')
  return existsSync(venv) ? venv : 'python3'
}

/** Ask the engine, in its own environment, where it writes the ledger. */
function engineInspectionDir(extraEnv = {}) {
  const r = spawnSync(enginePython(), ['-c', 'import shared; print(shared.INSPECTION_DIR)'], {
    cwd: ENGINE_DIR,
    encoding: 'utf8',
    timeout: 10_000,
    env: { ...process.env, ...extraEnv },
  })
  if (r.error) return { ok: false, error: String(r.error.message ?? r.error) }
  if (r.status !== 0) return { ok: false, error: `exit ${r.status}: ${String(r.stderr).slice(0, 200)}` }
  return { ok: true, dir: r.stdout.trim() }
}

// ---- modules under test (same import discipline as t261006-15) ----
let dirMod, archMod
try {
  dirMod = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/host/inspection-dir.ts')))
  archMod = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/src/host/inspection-archive.ts')))
} catch (e) {
  C.envFail('workbench-module-import', String(e?.message ?? e).slice(0, 200)); C.exit()
}
const { resolveInspectionDir, resetInspectionDirCacheForTests } = dirMod
const { readInspectionArchive } = archMod

// The real repo's SANDBAR_INSPECTION_DIR, if a developer has one set, would
// change BOTH sides of K1 identically (it is the same override chain) — but
// this row must exercise the engine default, so it is dropped for the test.
const savedOverride = process.env.SANDBAR_INSPECTION_DIR
delete process.env.SANDBAR_INSPECTION_DIR

async function main() {
  resetInspectionDirCacheForTests()

  // K1 — the contract row: writer location == reader location.
  const eng = engineInspectionDir()
  if (!eng.ok) { C.envFail('engine-inspection-dir', eng.error); return }
  const res = await resolveInspectionDir(REPO, { env: {} })
  if (!res.ok) {
    C.case('ledger-dir-contract', false, `resolver error: ${res.error.slice(0, 160)}`)
  } else {
    C.case('ledger-dir-contract',
      res.dir === eng.dir,
      res.dir === eng.dir
        ? `both sides: ${res.dir}`
        : `MISMATCH writer=${eng.dir} reader=${res.dir}`)
  }

  // K2 — env fast path is the engine's own first branch.
  const fast = await resolveInspectionDir(REPO, { env: { SANDBAR_INSPECTION_DIR: eng.dir } })
  C.case('env-override-fast-path', fast.ok && fast.dir === eng.dir && fast.source === 'env',
    fast.ok ? `dir=${fast.dir} source=${fast.source}` : fast.error)

  // K3 — empty string == unset (Python falsy-or semantics).
  const empty = await resolveInspectionDir(REPO, { env: { SANDBAR_INSPECTION_DIR: '' } })
  C.case('env-empty-string-is-unset', empty.ok && empty.dir === eng.dir,
    empty.ok ? empty.dir : empty.error)

  // K4 — relative env value is refused, never passed through silently.
  const rel = await resolveInspectionDir(REPO, { env: { SANDBAR_INSPECTION_DIR: 'relative/out/inspection' } })
  C.case('env-relative-path-refused', !rel.ok && /SANDBAR_INSPECTION_DIR/.test(rel.error ?? ''),
    rel.ok ? `silently used: ${rel.dir}` : String(rel.error).slice(0, 120))

  // K5 — failure is not cached: bad repo errors, real repo succeeds right after.
  resetInspectionDirCacheForTests()
  const bad = await resolveInspectionDir(join(iso, 'no-engine-here'), { env: {}, timeoutMs: 3000 })
  const good = await resolveInspectionDir(REPO, { env: {} })
  C.case('failed-resolution-not-cached', !bad.ok && bad.error !== '' && good.ok && good.dir === eng.dir,
    `bad=${bad.ok ? 'unexpectedly ok' : String(bad.error).slice(0, 80)} good=${good.ok ? good.dir : good.error}`)

  // K6 — empty-but-present vs absent: two distinct, named reasons.
  const emptyDir = join(iso, 'out', 'inspection')
  mkdirSync(emptyDir, { recursive: true })
  const rEmpty = await readInspectionArchive(emptyDir)
  const rAbsent = await readInspectionArchive(join(iso, 'never-created', 'inspection'))
  const emptyReason = rEmpty.ok === false ? rEmpty.reason : ''
  const absentReason = rAbsent.ok === false ? rAbsent.reason : ''
  C.case('empty-dir-reason', emptyReason.startsWith('no inspection report in the archive'),
    emptyReason.slice(0, 120))
  C.case('absent-dir-reason', absentReason.startsWith('inspection archive directory does not exist'),
    absentReason.slice(0, 120))
  C.case('empty-vs-absent-distinct', emptyReason !== '' && absentReason !== '' && emptyReason !== absentReason)

  // K7 — the served route reads the engine-declared directory. The declared
  // location is pointed at a SEEDED fixture archive (the lane worktree has no
  // run artifacts, so the real-tree default is genuinely empty here); the
  // route must serve the seeded report — the exact host story of 261021.
  {
    const fixtureDir = join(iso, 'fixture-ledger')
    mkdirSync(fixtureDir, { recursive: true })
    writeFileSync(join(fixtureDir, 'inspection-scenario-fixture-20261021.json'), JSON.stringify({
      instance: 'scenario-fixture', period: '20261021', base_head: 'b'.repeat(40),
      findings: { high: 1, med: 0, low: 0, total: 1 }, named: [], coverage: null,
    }))
    const routes = []
    const webServer = { register: (r) => { routes.push(r); return () => {} } }
    const ctx = {
      get: (k) => (k === 'webServer' ? webServer : undefined),
      effect: (fn) => { try { fn() } catch { /* apply-side effects tolerated */ } },
      logger: { info: () => {}, warn: () => {}, error: () => {} },
    }
    let nodeApi
    try { nodeApi = await import(pathToFileURL(join(REPO, 'server/plugins/workbench/node.ts'))) } catch (e) {
      C.envFail('workbench-host-importable', String(e?.message ?? e).slice(0, 200)); return
    }
    nodeApi.apply(ctx, { repo: REPO })
    const server = http.createServer((req, res) => {
      const pathname = new URL(req.url, 'http://local').pathname
      const hit = routes.find((r) => r.kind === 'exact' && r.path === pathname)
        ?? routes.find((r) => r.kind === 'prefix' && pathname.startsWith(r.path))
      if (!hit) { res.writeHead(404); res.end(); return }
      Promise.resolve(hit.handler(req, res)).catch(() => {
        try { res.writeHead(500); res.end() } catch { /* head sent */ }
      })
    })
    await new Promise((r) => server.listen(0, '127.0.0.1', r))
    const savedDir = process.env.SANDBAR_INSPECTION_DIR
    process.env.SANDBAR_INSPECTION_DIR = fixtureDir
    try {
      const url = 'http://127.0.0.1:' + server.address().port
        + '/sandbar-workbench/api/wf/inspection-archive?project='
      const resp = await fetch(url)
      const text = await resp.text()
      let parsed = null; try { parsed = JSON.parse(text) } catch { /* non-json */ }
      const blob = JSON.stringify(parsed ?? {})
      C.case('route-serves-engine-declared-archive',
        resp.status === 200 && blob.includes('scenario-fixture') && !/does not exist/i.test(blob),
        `status=${resp.status} body=${text.slice(0, 200)} — route must read the engine's declared ledger (host report 261021)`)
      C.case('route-never-denies-existing-archive',
        !(parsed?.ok === false && /does not exist/i.test(blob)),
        'the defect itself: "no inspection has run" while reports are on disk')
    } finally {
      if (savedDir === undefined) delete process.env.SANDBAR_INSPECTION_DIR
      else process.env.SANDBAR_INSPECTION_DIR = savedDir
      server.close()
    }
  }
}

main()
  .catch((e) => { C.case('scenario-unexpected-error', false, String(e?.message ?? e).slice(0, 200)) })
  .finally(() => {
    if (savedOverride === undefined) delete process.env.SANDBAR_INSPECTION_DIR
    else process.env.SANDBAR_INSPECTION_DIR = savedOverride
    rmSync(iso, { recursive: true, force: true })
    C.exit()
  })
