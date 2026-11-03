/**
 * smoke/t261102-09-file-face.mjs — host half-smoke for the middle-column file read.
 *
 * Run: node smoke/t261102-09-file-face.mjs (node >= 22 native type-stripping, imports
 * node.ts directly, no build needed, no docker, never touches 3099 — it listens on an
 * ephemeral loopback port and closes it).
 *
 * What it pins (ticket t261102-09, spec item 6: reading goes through a guarded face, and a
 * path outside every registered project directory is refused BY NAME):
 *   A. The route is registered under the path the served bundle calls.
 *   B. A session-relative file and an absolute file under a registered root are served
 *      whole (UTF-8 byte-identical, the path named in the answer).
 *   C. Every target fault is a named refusal carrying the requested path: outside-roots
 *      (relative escape, sibling directory sharing the root prefix, existing absolute
 *      path, symlink pointing outside), not-found, is-directory, too-large, not-utf8,
 *      session-workspace-unknown (unknown id, cwd on the wrong field, a throwing service).
 *   D. No existence oracle: a MISSING path outside the roots answers outside-roots, not
 *      not-found. An empty registry refuses by name instead of reading nothing.
 *   E. A malformed request is a 400 naming the parameter; a write verb returns no content.
 *   F. Disposing the plugin unregisters the route.
 *
 * Fixtures live in mkdtemp directories and are removed at the end; the registry is a
 * fixture tree (SANDBAR_PROJECTS_DIR), so no real registry, repo or console is touched.
 */

import { createServer } from 'node:http'
import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const HERE = new URL('.', import.meta.url).pathname
const HOST_MODULE = join(HERE, '..', 'node.ts')
const REPO = join(HERE, '..', '..', '..', '..')
const READ_PATH = '/sandbar-workbench/api/wf/file'
const MARKER = '中文行 zhongwen'

let passed = 0
let failed = 0
function ok(cond, label, extra = '') {
  if (cond) {
    passed += 1
    console.log(`  ok ${label}`)
  } else {
    failed += 1
    console.log(`  FAIL ${label}${extra === '' ? '' : ` (${extra})`}`)
  }
}
function section(title) {
  console.log(`\n== ${title}`)
}

const savedEnv = {
  SANDBAR_PROJECTS_DIR: process.env.SANDBAR_PROJECTS_DIR,
  SANDBAR_PROJECTS_YAML: process.env.SANDBAR_PROJECTS_YAML,
}
delete process.env.SANDBAR_PROJECTS_YAML

const tmpRoots = []
function tmpDir(prefix) {
  const dir = mkdtempSync(join(tmpdir(), prefix))
  tmpRoots.push(dir)
  return dir
}

const fx = tmpDir('t261102-09-smoke-')
const repoDir = join(fx, 'repo-a')
const siblingEvil = join(fx, 'repo-aevil')
const outsideDir = join(fx, 'outside')
mkdirSync(join(repoDir, 'sub'), { recursive: true })
mkdirSync(siblingEvil, { recursive: true })
mkdirSync(outsideDir, { recursive: true })
writeFileSync(join(repoDir, 'notes.md'), `# Notes\n\n- ${MARKER}\n`, 'utf8')
writeFileSync(join(repoDir, 'big.log'), 'x'.repeat(1024 * 1024 + 4096), 'utf8')
writeFileSync(join(repoDir, 'bad.txt'), Buffer.from([0x89, 0x50, 0xff, 0xfe]))
writeFileSync(join(outsideDir, 'secret.md'), 'outside secret\n', 'utf8')
writeFileSync(join(siblingEvil, 'evil.md'), 'sibling prefix\n', 'utf8')
symlinkSync(join(outsideDir, 'secret.md'), join(repoDir, 'link-out.md'))

const projectsRoot = tmpDir('t261102-09-smoke-registry-')
writeFileSync(join(projectsRoot, '.migrated'), 'smoke fixture\n', 'utf8')
mkdirSync(join(projectsRoot, 'fixture-alpha'), { recursive: true })
writeFileSync(join(projectsRoot, 'fixture-alpha', 'project.yaml'), [
  'schema: v1',
  'project:',
  '  - key: fixture-alpha',
  '    name: Fixture Alpha',
  '    dirs:',
  `      - ${repoDir}`,
  '',
].join('\n'), 'utf8')
const emptyRegistry = tmpDir('t261102-09-smoke-empty-')
writeFileSync(join(emptyRegistry, '.migrated'), 'smoke fixture\n', 'utf8')
process.env.SANDBAR_PROJECTS_DIR = projectsRoot

const routes = []
const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1')
  const hit = routes.find((r) => r.kind === 'exact' && r.path === url.pathname)
  if (hit === undefined) {
    res.writeHead(404, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ ok: false, error: 'no route (smoke fixture server)' }))
    return
  }
  Promise.resolve(hit.handler(req, res)).catch((err) => {
    if (!res.headersSent) {
      res.writeHead(500, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: false, error: String(err?.message ?? err) }))
    }
  })
})
const webServer = {
  register({ kind, path, handler }) {
    const record = { kind, path, handler }
    routes.push(record)
    return () => {
      const at = routes.indexOf(record)
      if (at >= 0) routes.splice(at, 1)
    }
  },
}

const sessions = {
  get(id) {
    if (id === 'it-session-1') return { header: { cwd: repoDir } }
    if (id === 'it-session-metaonly') return { meta: { cwd: repoDir } }
    if (id === 'it-session-boom') throw new Error('session service unavailable (injected)')
    return undefined
  },
}
const effects = []
const ctx = {
  logger: { info() {}, warn() {}, error() {}, debug() {} },
  get: (name) => (name === 'webServer' ? webServer : name === 'sessions' ? sessions : undefined),
  effect(fn) {
    const dispose = fn()
    effects.push(dispose)
    return dispose
  },
  on: () => () => {},
}

try {
  const mod = await import(pathToFileURL(HOST_MODULE).href)
  try {
    mod.apply(ctx, { repo: REPO, python: process.execPath, timeoutMs: 5_000 })
    ok(true, 'apply(ctx) mounts the host routes')
  } catch (err) {
    ok(false, 'apply(ctx) mounts the host routes', String(err?.message ?? err))
  }
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const base = `http://127.0.0.1:${server.address().port}`
  const get = async (query, method = 'GET') => {
    const res = await fetch(base + READ_PATH + query, { method })
    const text = await res.text()
    let json = null
    try {
      json = JSON.parse(text)
    } catch {
      json = null
    }
    return { status: res.status, text, json }
  }
  const query = (params) => '?' + new URLSearchParams(params).toString()
  // The scenario face folds the answer the same way: lower case, spaces and underscores
  // become dashes, so a reason code reads as one token.
  const folded = (answer) => `${answer.json === null ? '' : JSON.stringify(answer.json)}\n${answer.text}`
    .toLowerCase()
    .replace(/[ _]+/g, '-')

  section('A. Route registration')
  ok(routes.some((entry) => entry.path === READ_PATH), `the host registers ${READ_PATH}`)

  section('B. Served reads (UTF-8 byte-identical)')
  {
    const answer = await get(query({ session: 'it-session-1', path: 'notes.md' }))
    ok(answer.status === 200 && answer.json?.ok === true, 'a session-relative file is served')
    ok(answer.text.includes(MARKER), 'the content is byte-identical UTF-8')
    ok(answer.text.includes('notes.md'), 'the answer names the file path')
  }
  {
    const answer = await get(query({ path: join(repoDir, 'notes.md') }))
    ok(answer.status === 200 && answer.json?.ok === true, 'an absolute file under a registered root is served')
  }

  section('C. Refusals by name (the requested path travels with the reason)')
  const refusals = [
    ['relative escape', { session: 'it-session-1', path: '../../outside/secret.md' }, 'outside-roots', 'secret.md'],
    ['sibling prefix', { session: 'it-session-1', path: '../repo-aevil/evil.md' }, 'outside-roots', 'evil.md'],
    ['absolute outside', { path: join(outsideDir, 'secret.md') }, 'outside-roots', 'secret.md'],
    ['symlink outside', { session: 'it-session-1', path: 'link-out.md' }, 'outside-roots', 'link-out.md'],
    ['not found', { session: 'it-session-1', path: 'missing.md' }, 'not-found', 'missing.md'],
    ['directory', { session: 'it-session-1', path: 'sub' }, 'is-directory', 'sub'],
    ['too large', { session: 'it-session-1', path: 'big.log' }, 'too-large', 'big.log'],
    ['not utf-8', { session: 'it-session-1', path: 'bad.txt' }, 'not-utf8', 'bad.txt'],
    ['unknown session', { session: 'it-session-nope', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
    ['cwd on the wrong field', { session: 'it-session-metaonly', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
    ['throwing session service', { session: 'it-session-boom', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
  ]
  for (const [label, params, reason, fragment] of refusals) {
    const answer = await get(query(params))
    const text = folded(answer)
    ok(text.includes(reason) && text.includes(fragment.toLowerCase()), `${label} is refused as ${reason} and names ${fragment}`,
      `status=${answer.status} body=${answer.text.slice(0, 140)}`)
    ok(!(answer.json && answer.json.ok === true), `${label} serves no content`)
  }

  section('D. No existence oracle, and a dead registry refuses by name')
  {
    const answer = await get(query({ path: join(outsideDir, 'definitely-missing.md') }))
    ok(folded(answer).includes('outside-roots'), 'a missing path outside the roots answers outside-roots')
  }
  {
    process.env.SANDBAR_PROJECTS_DIR = emptyRegistry
    const answer = await get(query({ session: 'it-session-1', path: 'notes.md' }))
    process.env.SANDBAR_PROJECTS_DIR = projectsRoot
    ok(folded(answer).includes('no-registered-roots'), 'an empty registry is refused by name (no silent empty read)')
  }

  section('E. Malformed request and read-only method')
  ok((await get(query({ session: 'it-session-1' }))).status === 400, 'a missing path is a 400')
  ok((await get(query({ path: 'notes.md', session: 'bad/session' }))).status === 400, 'a malformed session is a 400')
  {
    const answer = await get(query({ session: 'it-session-1', path: 'notes.md' }), 'POST')
    ok(!(answer.json && answer.json.ok === true && answer.text.includes(MARKER)), 'a write verb never returns file content')
  }

  section('F. Lifecycle')
  for (const dispose of effects) {
    try {
      if (typeof dispose === 'function') dispose()
    } catch {
      // Idempotent teardown.
    }
  }
  {
    const answer = await get(query({ session: 'it-session-1', path: 'notes.md' }))
    ok(answer.status === 404 || !(answer.json && answer.json.ok === true), 'disposing the plugin unregisters the route')
  }
} finally {
  await new Promise((resolve) => server.close(resolve))
  for (const dir of tmpRoots) {
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      // Best effort: a leaked tmp directory is not a product fault.
    }
  }
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
}

console.log(`\nSUMMARY pass=${passed} skip=0 fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
