/**
 * i01_stale_watchdog_e2e.mjs — t260902-03 host stale watchdog, end-to-end (hermetic).
 *
 * User story: after a host-half change lands on disk (merge), the running console process
 * keeps executing old code ("一日三咬"). The watchdog must detect this at runtime: the
 * /suyou-workbench/api/build-info endpoint compares the boot-time fingerprint of the host
 * source files (node.ts + src/host/*.ts) against the current on-disk content and reports
 * stale=true, so every view can show the "restart console" banner.
 *
 * High-level steps (all hermetic: in-process handlers on a mock webServer, fixture repo in
 * a temp dir, zero real ports, zero 3099 contact):
 *   T1 fresh boot            -> 200, result.stale=false, bootFingerprint === diskFingerprint.
 *   T2 mtime-only touch      -> still stale=false (content hash, not mtime — checkout touch
 *                               must not false-positive).
 *   T3 content change        -> result.stale=true, diskFingerprint !== bootFingerprint
 *                               (simulates a host-half merge landing on disk).
 *   T4 boot hash pinned      -> a second apply() in the same process must NOT reset the
 *                               boot fingerprint; stale stays true after T3.
 *   T5 all files missing     -> 200 {stale:false, error:<human>} — cannot judge = no banner.
 *   T6 concurrent polls      -> 5 parallel requests, all 200, identical verdict/fingerprint.
 *
 * Contract pinned by this baseline (implementation must conform, house envelope style):
 *   - exact route GET /suyou-workbench/api/build-info registered on the webServer.
 *   - 200 envelope: { ok: true, result: { stale: boolean, bootFingerprint?: string,
 *                     diskFingerprint: string, missing: string[], error?: string } }.
 *
 * Exit contract (integration/README.md): last stdout line `SUMMARY pass=N skip=M fail=K`;
 * exit 1 iff fail>0. Pre-implementation this baseline is RED by design (acceptance bar).
 */

let passed = 0
let failed = 0
let skipped = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const [maj, min] = process.versions.node.split('.').map(Number)
if (maj < 22 || (maj === 22 && min < 18)) {
  console.log(`SKIP: node ${process.versions.node} < 22.18 (no native type-stripping for .ts imports)`)
  console.log('SUMMARY pass=0 skip=1 fail=0')
  process.exit(0)
}

const { mkdtemp, mkdir, rm, writeFile, utimes } = await import('node:fs/promises')
const { tmpdir } = await import('node:os')
const { join } = await import('node:path')

let apply
try {
  ;({ apply } = await import('./../node.ts'))
} catch (err) {
  console.log(`FAIL: cannot import server/dsh/workbench/node.ts: ${String(err && err.message ? err.message : err)}`)
  console.log('SUMMARY pass=0 skip=0 fail=1')
  process.exit(1)
}

const PATH = '/suyou-workbench/api/build-info'

/** Capture registered routes on a mock webServer, the agent-live.mjs shape. */
function makeCtx() {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  return { ctx, routes }
}

function mockRes() {
  return {
    status: 0, body: null, raw: null,
    writeHead(s) { this.status = s },
    end(b) { this.raw = b; this.body = b ? JSON.parse(b) : null },
  }
}
const mockReq = (url, method = 'GET') => ({ url, method, async *[Symbol.asyncIterator]() {} })

async function call(route, url, method = 'GET') {
  const res = mockRes()
  await route.handler(mockReq(url, method), res)
  return res
}

const tmp = await mkdtemp(join(tmpdir(), 'wb-stale-it01-'))
try {
  /* Fixture repo: the watched list always includes server/dsh/workbench/node.ts
   * (handwritten HOST_SOURCE_FILES); any watched filenames absent from the fixture land
   * in missing[] at both boot and poll time, so verdicts below stay meaningful.
   * T2/T3 therefore touch node.ts — the one file guaranteed to be watched. */
  const repo = join(tmp, 'repo')
  const wb = join(repo, 'server', 'dsh', 'workbench')
  await mkdir(join(wb, 'src', 'host'), { recursive: true })
  await writeFile(join(wb, 'node.ts'), 'export const BOOT = 1\n', 'utf8')
  await writeFile(join(wb, 'src', 'host', 'a.ts'), 'export const A = 1\n', 'utf8')
  await writeFile(join(wb, 'src', 'host', 'b.ts'), 'export const B = 1\n', 'utf8')
  await mkdir(join(repo, 'notes', 'epics'), { recursive: true })

  const { ctx, routes } = makeCtx()
  apply(ctx, { repo })
  const route = routes.find(r => r.kind === 'exact' && r.path === PATH)
  section('T1 fresh boot')
  if (route === undefined) {
    ok(false, `${PATH} exact route registered (found: ${routes.map(r => r.path).join(', ') || 'none'})`)
  } else {
    const r = await call(route, PATH)
    const res = r.body?.result
    ok(r.status === 200 && r.body?.ok === true, `GET ${PATH} -> 200 ok:true (got ${r.status})`)
    ok(res && res.stale === false, 'result.stale=false on fresh boot')
    ok(typeof res?.bootFingerprint === 'string' && res.bootFingerprint.length > 0, 'bootFingerprint non-empty string')
    ok(res?.bootFingerprint === res?.diskFingerprint, 'bootFingerprint === diskFingerprint')
    ok(Array.isArray(res?.missing), 'result.missing is an array')

    section('T2 mtime-only touch (checkout touch must not false-positive)')
    const now = new Date()
    await utimes(join(wb, 'node.ts'), now, now)
    const r2 = await call(route, PATH)
    ok(r2.status === 200 && r2.body?.result?.stale === false, 'stale stays false after mtime-only touch on a watched file (content hash, not mtime)')

    section('T3 content change lands on disk (host-half merge)')
    await writeFile(join(wb, 'node.ts'), 'export const BOOT = 2\n', 'utf8')
    const r3 = await call(route, PATH)
    const res3 = r3.body?.result
    ok(r3.status === 200 && res3?.stale === true, 'stale=true after host file content change')
    ok(res3?.diskFingerprint !== res3?.bootFingerprint, 'diskFingerprint !== bootFingerprint')
    ok(res3?.bootFingerprint === res?.bootFingerprint, 'bootFingerprint unchanged vs T1')

    section('T4 second apply() must not reset the boot fingerprint')
    const second = makeCtx()
    apply(second.ctx, { repo })
    const route2 = second.routes.find(r => r.kind === 'exact' && r.path === PATH)
    if (route2 === undefined) {
      ok(false, 'route re-registered on second apply')
    } else {
      const r4 = await call(route2, PATH)
      ok(r4.status === 200 && r4.body?.result?.stale === true, 'stale stays true after second apply (boot hash pinned)')
      ok(r4.body?.result?.bootFingerprint === res?.bootFingerprint, 'bootFingerprint identical to first boot')
    }

    section('T6 concurrent polls agree')
    const results = await Promise.all(Array.from({ length: 5 }, () => call(route, PATH)))
    ok(results.every(x => x.status === 200), '5 parallel polls all 200')
    ok(results.every(x => x.body?.result?.stale === true), '5 parallel polls all stale=true')
    ok(new Set(results.map(x => x.body?.result?.diskFingerprint)).size === 1, '5 parallel polls identical diskFingerprint')

    section('T0 method guard (read-only watchdog)')
    const r0 = await call(route, PATH, 'POST')
    ok(r0.status === 405, `POST -> 405 (got ${r0.status})`)
  }

  section('T5 all watched files missing -> cannot judge, no false alarm')
  const repoEmpty = join(tmp, 'repo-empty')
  await mkdir(join(repoEmpty, 'notes', 'epics'), { recursive: true })
  const third = makeCtx()
  apply(third.ctx, { repo: repoEmpty })
  const route3 = third.routes.find(r => r.kind === 'exact' && r.path === PATH)
  if (route3 === undefined) {
    ok(false, 'route registered for empty repo')
  } else {
    const r5 = await call(route3, PATH)
    const res5 = r5.body?.result
    ok(r5.status === 200, `all-missing repo -> 200 (got ${r5.status})`)
    ok(res5?.stale === false, 'stale=false when fingerprint cannot be computed')
    ok(typeof res5?.error === 'string' && res5.error.length > 0, 'human-readable error present')
  }
} finally {
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nSUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
