#!/usr/bin/env node
/**
 * t261102-09-file-read.mjs — L1 battery for the guarded file-read route.
 *
 * Scope: the one route the middle column reads through, so it is both the feature door
 * and the only safety gate. Three real defects found in plan review are pinned here:
 *
 *   R15  the session workspace is `Session.header.cwd`, NOT `meta.cwd`. All three shapes
 *        are covered, including "a wrong-shaped fake must be refused" — the guard on the
 *        guard, without which a test built on the same wrong shape stays green.
 *   S1   the lexical containment test runs first and touches no file system, so a path
 *        outside the roots answers the same reason whether it exists or not: the route is
 *        not an existence oracle. The realpath test that follows is the symlink gate.
 *   S5   a present but malformed `session` query is a named 400 (bad-session), never a
 *        silent session-workspace-unknown.
 *
 * Fixtures: mkdtemp registry (SANDBAR_PROJECTS_DIR plus the .migrated marker, no
 * migration chain) and fixture project directories. No real registry, no real repo, no
 * console. Harness shape follows tests/project-routes.mjs (apply plus a mock webServer).
 *
 * Run: node server/plugins/workbench/tests/t261102-09-file-read.mjs
 */
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { apply } from './../node.ts'
import { FILE_READ_PATH } from './../src/client/file-route.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) {
    pass += 1
    console.log(`  ok ${label}`)
  } else {
    fail += 1
    console.error(`  FAIL ${label}`)
  }
}
function section(t) {
  console.log(`\n== ${t}`)
}

const savedEnv = {
  SANDBAR_PROJECTS_DIR: process.env.SANDBAR_PROJECTS_DIR,
  SANDBAR_PROJECTS_YAML: process.env.SANDBAR_PROJECTS_YAML,
}
delete process.env.SANDBAR_PROJECTS_YAML

const mockRes = () => ({
  status: 0,
  body: null,
  writeHead(s) { this.status = s },
  end(b) { this.body = b ? JSON.parse(b) : null },
})

const call = async (handler, url) => {
  const res = mockRes()
  const req = { url, method: 'GET', async *[Symbol.asyncIterator]() { /* no body */ } }
  await handler.handler(req, res)
  return res
}

/** Registry fixture: one .migrated marker plus one project.yaml per entry. */
function writeRegistry(reg, projects) {
  mkdirSync(reg, { recursive: true })
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  for (const p of projects) {
    mkdirSync(join(reg, p.key), { recursive: true })
    writeFileSync(join(reg, p.key, 'project.yaml'),
      `schema: v1\nproject:\n  - key: ${p.key}\n    name: ${p.name ?? p.key}\n    dirs:\n${p.dirs.map((d) => `      - ${d}`).join('\n')}\n`, 'utf8')
  }
}

/** Build the plugin against a fixture repo and a fake sessions service. */
function harness(repo, sessions) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : k === 'sessions' ? sessions : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  return {
    route: routes.find((r) => r.path === FILE_READ_PATH),
    routes,
  }
}

const tmp = mkdtempSync(join(tmpdir(), 't261102-09-'))
const repo = join(tmp, 'repo')
mkdirSync(repo, { recursive: true })

try {
  /* ---------------------------------------------------------------- A. route present */

  section('A. Route registration (client and server share one constant)')
  {
    const reg = join(tmp, 'reg-a')
    const proj = join(tmp, 'proj-a')
    mkdirSync(proj, { recursive: true })
    writeRegistry(reg, [{ key: 'alpha', dirs: [proj] }])
    process.env.SANDBAR_PROJECTS_DIR = reg
    const h = harness(repo, undefined)
    ok(FILE_READ_PATH === '/sandbar-workbench/api/wf/file', 'the constant is the file route under the wf namespace')
    ok(h.route !== undefined && typeof h.route.handler === 'function', 'apply() registered that route on the mock webServer')
    ok(h.routes.filter((r) => r.path === FILE_READ_PATH).length === 1, 'the path is registered exactly once')
  }

  /* ---------------------------------------------------------------- B. session workspace (R15) */

  section('B. Session workspace probe (Session.header.cwd; a wrong shape must be refused)')
  {
    const reg = join(tmp, 'reg-b')
    const proj = join(tmp, 'proj-b')
    mkdirSync(join(proj, 'sub'), { recursive: true })
    writeFileSync(join(proj, 'sub', 'a.md'), '# hello\nsecond line\n', 'utf8')
    writeRegistry(reg, [{ key: 'bravo', dirs: [proj] }])
    process.env.SANDBAR_PROJECTS_DIR = reg

    const real = harness(repo, { get: () => ({ header: { cwd: proj } }) })
    const r1 = await call(real.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('sub/a.md')}`)
    ok(r1.status === 200 && r1.body.ok === true, 'the real shape (header.cwd) reads a relative path')
    ok(r1.body.result?.content === '# hello\nsecond line\n', 'the content comes back verbatim')
    ok(typeof r1.body.result?.path === 'string' && r1.body.result.path.endsWith('sub/a.md'), 'the answer carries the absolute path')

    const onlyMeta = harness(repo, { get: () => ({ meta: { cwd: proj } }) })
    const r2 = await call(onlyMeta.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('sub/a.md')}`)
    ok(r2.body.ok === false && r2.body.reason === 'session-workspace-unknown', 'the wrong shape (meta.cwd only) is refused by name — the guard on the guard')

    const empty = harness(repo, { get: () => ({}) })
    const r3 = await call(empty.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('sub/a.md')}`)
    ok(r3.body.ok === false && r3.body.reason === 'session-workspace-unknown', 'a session with no cwd is refused by name')

    const noService = harness(repo, undefined)
    const r4 = await call(noService.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('sub/a.md')}`)
    ok(r4.body.ok === false && r4.body.reason === 'session-workspace-unknown', 'a missing sessions service is refused by name (no roots fallback)')

    const gone = harness(repo, { get: () => ({ header: { cwd: join(tmp, 'no-such-workspace') } }) })
    const r5 = await call(gone.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('sub/a.md')}`)
    ok(r5.status === 200 && r5.body.ok === false && r5.body.reason === 'session-workspace-unknown',
      'a workspace directory that is gone is refused by name (never a 500)')
  }

  /* ---------------------------------------------------------------- C. absolute scope and refusals */

  section('C. Absolute scope and the refusal matrix')
  {
    const reg = join(tmp, 'reg-c')
    const proj = join(tmp, 'proj-c')
    const sibling = join(tmp, 'proj-c-evil')
    const outside = join(tmp, 'outside-c')
    mkdirSync(join(proj, 'dir'), { recursive: true })
    mkdirSync(sibling, { recursive: true })
    mkdirSync(outside, { recursive: true })
    writeFileSync(join(proj, 'ok.txt'), 'inside\n', 'utf8')
    writeFileSync(join(sibling, 'sib.txt'), 'sibling\n', 'utf8')
    writeFileSync(join(outside, 'out.txt'), 'outside\n', 'utf8')
    writeFileSync(join(proj, 'big.log'), 'x'.repeat(1024 * 1024 + 1), 'utf8')
    writeFileSync(join(proj, 'bin.log'), Buffer.from([0xff, 0xfe, 0x00, 0x41]))
    symlinkSync(join(outside, 'out.txt'), join(proj, 'link.txt'))
    writeRegistry(reg, [{ key: 'charlie', dirs: [proj] }])
    process.env.SANDBAR_PROJECTS_DIR = reg
    const h = harness(repo, undefined)
    const get = (path) => call(h.route, `${FILE_READ_PATH}?path=${encodeURIComponent(path)}`)

    const okRead = await get(join(proj, 'ok.txt'))
    ok(okRead.body.ok === true && okRead.body.result.content === 'inside\n', 'an absolute path inside a root reads')

    const siblingRead = await get(join(sibling, 'sib.txt'))
    ok(siblingRead.body.ok === false && siblingRead.body.reason === 'outside-roots', 'a same-prefix sibling directory (proj-c-evil) is refused')

    const outsideRead = await get(join(outside, 'out.txt'))
    ok(outsideRead.body.ok === false && outsideRead.body.reason === 'outside-roots', 'an existing file outside the roots answers outside-roots')

    const outsideMissing = await get(join(outside, 'no-such-file.md'))
    ok(outsideMissing.body.ok === false && outsideMissing.body.reason === 'outside-roots',
      'a missing path outside the roots answers the same reason (no existence oracle)')

    const missing = await get(join(proj, 'no-such-file.md'))
    ok(missing.body.ok === false && missing.body.reason === 'not-found', 'a missing path inside a root answers not-found')

    const dir = await get(join(proj, 'dir'))
    ok(dir.body.ok === false && dir.body.reason === 'is-directory', 'a directory answers is-directory')

    const big = await get(join(proj, 'big.log'))
    ok(big.body.ok === false && big.body.reason === 'too-large', 'over 1 MiB answers too-large')
    ok(big.body.error.includes(String(1024 * 1024 + 1)), 'the too-large message carries the byte count')

    const bin = await get(join(proj, 'bin.log'))
    ok(bin.body.ok === false && bin.body.reason === 'not-utf8', 'a non-UTF-8 file answers not-utf8')

    const link = await get(join(proj, 'link.txt'))
    ok(link.body.ok === false && link.body.reason === 'outside-roots', 'a symlink pointing outside a root answers outside-roots')
    ok(link.body.error.includes('resolves outside'), 'the symlink refusal names the resolved path')

    const relativeInAbsolute = await get('relative/path.md')
    ok(relativeInAbsolute.body.ok === false && relativeInAbsolute.body.reason === 'bad-path', 'a relative path in the absolute scope answers bad-path')

    ok(outsideRead.status === 200 && outsideRead.body.ok === false, 'a target fault is 200 + ok:false (the repo read-face convention)')
    ok(typeof outsideRead.body.path === 'string' && outsideRead.body.path !== '', 'the failure answer carries the path')
    ok(typeof outsideRead.body.error === 'string' && outsideRead.body.error !== '', 'the failure answer carries human words')
  }

  /* ---------------------------------------------------------------- D. malformed request and registry faults */

  section('D. Malformed requests (400) and registry faults (named 200)')
  {
    const reg = join(tmp, 'reg-d')
    const proj = join(tmp, 'proj-d')
    mkdirSync(proj, { recursive: true })
    writeFileSync(join(proj, 'a.md'), 'x\n', 'utf8')
    writeRegistry(reg, [{ key: 'delta', dirs: [proj] }])
    process.env.SANDBAR_PROJECTS_DIR = reg
    const h = harness(repo, { get: () => ({ header: { cwd: proj } }) })

    const noPath = await call(h.route, FILE_READ_PATH)
    ok(noPath.status === 400 && noPath.body.reason === 'bad-path', 'a missing path is 400 bad-path')
    const blankPath = await call(h.route, `${FILE_READ_PATH}?path=`)
    ok(blankPath.status === 400 && blankPath.body.reason === 'bad-path', 'an empty path is 400 bad-path')

    for (const badSession of ['', 'a b', 'a/b', 'x'.repeat(201), 'a\tb']) {
      const r = await call(h.route, `${FILE_READ_PATH}?session=${encodeURIComponent(badSession)}&path=${encodeURIComponent('a.md')}`)
      ok(r.status === 400 && r.body.reason === 'bad-session', `a malformed session is a named 400: ${JSON.stringify(badSession.slice(0, 12))}`)
    }
    const goodSession = await call(h.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('a.md')}`)
    ok(goodSession.status === 200 && goodSession.body.ok === true, 'a well-formed session still reads')

    // Loader fault: the legacy single-file registry points at a missing file, so
    // loadRegistry() throws and never falls back to the migration seed. A missing
    // registry ROOT would migrate from server/projects.yaml instead — a different
    // branch, and not the fault this leg pins.
    process.env.SANDBAR_PROJECTS_YAML = join(tmp, 'no-such-registry.yaml')
    const broken = harness(repo, undefined)
    const rb = await call(broken.route, `${FILE_READ_PATH}?path=${encodeURIComponent(join(proj, 'a.md'))}`)
    ok(rb.status === 200 && rb.body.ok === false && rb.body.reason === 'no-registered-roots',
      'a registry load failure is the named no-registered-roots (never a 500)')
    delete process.env.SANDBAR_PROJECTS_YAML

    // Empty registry: no entries at all.
    const emptyReg = join(tmp, 'reg-empty')
    mkdirSync(emptyReg, { recursive: true })
    writeFileSync(join(emptyReg, '.migrated'), 'fixture\n', 'utf8')
    process.env.SANDBAR_PROJECTS_DIR = emptyReg
    const empty = harness(repo, undefined)
    const re = await call(empty.route, `${FILE_READ_PATH}?path=${encodeURIComponent(join(proj, 'a.md'))}`)
    ok(re.body.ok === false && re.body.reason === 'no-registered-roots', 'an empty registry is the named no-registered-roots')

    // One registered directory that no longer exists next to a good one: the good one
    // still serves, and the dead one is skipped with a log line.
    const regMixed = join(tmp, 'reg-mixed')
    writeRegistry(regMixed, [{ key: 'echo', dirs: [join(tmp, 'gone-project'), proj] }])
    process.env.SANDBAR_PROJECTS_DIR = regMixed
    const mixed = harness(repo, { get: () => ({ header: { cwd: proj } }) })
    const rm = await call(mixed.route, `${FILE_READ_PATH}?session=session-abc&path=${encodeURIComponent('a.md')}`)
    ok(rm.body.ok === true && rm.body.result.content === 'x\n', 'an unresolvable registered directory is skipped; the good root still serves')
  }
} finally {
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  rmSync(tmp, { recursive: true, force: true })
}

console.log(`\nt261102-09-file-read: pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
