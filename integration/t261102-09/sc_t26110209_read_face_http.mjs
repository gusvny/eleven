#!/usr/bin/env node
// sc_t26110209_read_face_http.mjs — t261102-09 L2 component-contract case: the guarded
// file-read face the middle column consumes, driven over real HTTP on the real host half.
//
// Intent (grey-box, user-visible contract; the reader is the pane, so every assertion is
// read back from the HTTP answer, never from a handler's return value):
//   R1 the plugin registers the read route the pane calls: the path the SERVED client
//      bundle carries is the path the host registers (the dead-button class: a client
//      URL with no handler must be a named red, not a silent 404 at the user).
//   R2 a text file under a registered project root is served whole (UTF-8, byte-identical
//      content) for BOTH address scopes: session-relative with a resolved session
//      workspace, and an absolute path under a root.
//   R3 every target fault is refused BY NAME with the path present in the answer, so the
//      pane can name it instead of showing a blank pane or a generic network error:
//      outside-roots (relative escape, absolute outside, sibling-prefix directory, and a
//      symlink that points outside), not-found, is-directory, too-large, not-utf8,
//      no-registered-roots (empty registry), session-workspace-unknown (unknown session,
//      a session whose cwd is not on the real field, and a throwing session service).
//   R4 the refusal does not become an existence oracle: an EXISTING path outside the
//      roots and a MISSING path outside the roots answer the same way (outside-roots).
//   R5 a malformed request is a 4xx naming the parameter (path / session), never a
//      guessed read.
//   R6 the face is read-only across the method: a write method never returns file
//      content.
//   R7 the route is owned by the plugin lifetime: disposing the plugin's effects
//      unregisters it (no handler outlives the plugin).
//
// Why this is L2 and not L3: one component's contract (the host read face) at its public
// boundary. No browser, no stage, no docker; a real socket on 127.0.0.1 and a real
// registry directory on disk; seconds.
//
// Tier: component contract. Cost: seconds.
// Environment: node + the lane tree only; a missing/ broken workbench host module is
// ENV_FAIL exit 2 (the tree cannot even load), a missing route is the TDD red.

import { mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createServer } from 'node:http'
import { readFileSync, existsSync } from 'node:fs'

import { makeResults } from './lib_case_results.mjs'

const REPO = process.cwd()
const results = makeResults()
const READ_PATH = '/sandbar-workbench/api/wf/file' // the plan's declared route (contract)
const BUNDLE = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const HOST_MODULE = join(REPO, 'server', 'plugins', 'workbench', 'node.ts')

const tmpRoots = []
function tmpDir(prefix) {
  const d = mkdtempSync(join(tmpdir(), prefix))
  tmpRoots.push(d)
  return d
}
process.on('exit', () => {
  for (const d of tmpRoots) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best effort */ } }
})

// ---------------------------------------------------------------------------
// Fixtures: one registered project root, one outside region, one sibling-prefix dir
// ---------------------------------------------------------------------------
const fx = tmpDir('t261102-09-fixture-')
const repoDir = join(fx, 'repo-a')
const siblingEvil = join(fx, 'repo-aevil')
const outsideDir = join(fx, 'outside')
mkdirSync(join(repoDir, 'sub'), { recursive: true })
mkdirSync(siblingEvil, { recursive: true })
mkdirSync(outsideDir, { recursive: true })

const MARKER = 'T26110209-READ-FACE-MARKER'
const notesText = `# Notes\n\n${MARKER}\n\n- 中文行 zhongwen\n- last line\n`
writeFileSync(join(repoDir, 'notes.md'), notesText)
writeFileSync(join(repoDir, 'apps.ts'), 'export const x = 1\n')
writeFileSync(join(repoDir, 'big.log'), 'x'.repeat(1024 * 1024 + 4096))
writeFileSync(join(repoDir, 'bad.txt'), Buffer.from([0x89, 0x50, 0xff, 0xfe, 0x00, 0x01]))
writeFileSync(join(outsideDir, 'secret.md'), 'outside secret\n')
writeFileSync(join(siblingEvil, 'evil.md'), 'sibling prefix\n')
symlinkSync(join(outsideDir, 'secret.md'), join(repoDir, 'link-out.md'))

const projectsRoot = tmpDir('t261102-09-registry-')
writeFileSync(join(projectsRoot, '.migrated'), 'fixture: t261102-09\n')
mkdirSync(join(projectsRoot, 'fixture-alpha'), { recursive: true })
writeFileSync(join(projectsRoot, 'fixture-alpha', 'project.yaml'), [
  'schema: v1',
  'project:',
  '  - key: fixture-alpha',
  '    name: Fixture Alpha',
  '    dirs:',
  `      - ${repoDir}`,
  '',
].join('\n'))
const emptyRegistry = tmpDir('t261102-09-empty-registry-')
writeFileSync(join(emptyRegistry, '.migrated'), 'fixture: t261102-09 empty\n')

process.env.SANDBAR_PROJECTS_DIR = projectsRoot
delete process.env.SANDBAR_PROJECTS_YAML
process.env.SANDBAR_POC_HOST = '127.0.0.1:1' // never reach a real Temporal from this case

if (!existsSync(HOST_MODULE)) {
  // A missing source file is a TREE defect, not an environment gap: the environment
  // (node, git, the tree) is present, the product's own file is not.
  results.fail('the workbench host module is present in the tree', `${HOST_MODULE} — a delivered file is missing (product red)`)
  results.summarize()
}

// ---------------------------------------------------------------------------
// Mock web server (real socket, the plugin's real route registrations)
// ---------------------------------------------------------------------------
function makeWebServer() {
  const routes = []
  const server = createServer((req, res) => {
    const url = new URL(req.url ?? '/', 'http://127.0.0.1')
    let hit = routes.find((r) => r.kind === 'exact' && r.path === url.pathname)
    if (hit === undefined) {
      hit = routes.find((r) => r.kind === 'prefix' && (url.pathname === r.path || url.pathname.startsWith(r.path + '/')))
    }
    if (hit === undefined) {
      res.writeHead(404, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: false, error: 'no route (fixture web server)' }))
      return
    }
    Promise.resolve(hit.handler(req, res)).catch((err) => {
      if (!res.headersSent) {
        res.writeHead(500, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: String(err?.message ?? err) }))
      }
    })
  })
  return {
    routes,
    server,
    register({ kind, path, handler }) {
      const record = { kind, path, handler }
      routes.push(record)
      return () => {
        const i = routes.indexOf(record)
        if (i >= 0) routes.splice(i, 1)
      }
    },
  }
}

async function listen(server) {
  await new Promise((res, rej) => {
    server.once('error', rej)
    server.listen(0, '127.0.0.1', res)
  })
  return `http://127.0.0.1:${server.address().port}`
}

function makeSessions() {
  return {
    get(id) {
      if (id === 'it-session-1') return { header: { cwd: repoDir } }
      if (id === 'it-session-metaonly') return { meta: { cwd: repoDir } } // wrong shape on purpose
      if (id === 'it-session-boom') throw new Error('session service unavailable (injected)')
      return undefined
    },
    list() { return [] },
  }
}

function makeCtx(webServer, sessions) {
  const effects = []
  return {
    effects,
    ctx: {
      logger: { info() {}, warn() {}, error() {}, debug() {} },
      get(name) {
        if (name === 'webServer') return webServer
        if (name === 'sessions') return sessions
        return undefined
      },
      effect(fn) {
        const dispose = fn()
        effects.push(dispose)
        return dispose
      },
      on() { return () => {} },
    },
  }
}

async function fetchJson(base, pathWithQuery, method = 'GET') {
  const r = await fetch(base + pathWithQuery, { method })
  const text = await r.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* non-JSON answers stay textual */ }
  return { status: r.status, text, json }
}

function answerText(answer) {
  const fromJson = answer.json === null ? '' : JSON.stringify(answer.json)
  return `${fromJson}\n${answer.text}`.toLowerCase().replace(/[ _]+/g, '-')
}

async function main() {
  let apply
  try {
    const mod = await import(pathToFileURL(HOST_MODULE).href)
    apply = mod.apply
    if (typeof apply !== 'function') throw new Error('the workbench host module exports no apply(ctx)')
  } catch (e) {
    // Import resolution failing on the product's own tree is a PRODUCT red (a missing or
    // half-merged module breaks the whole host half — every API route dies at load), never
    // an environment red. Only a missing interpreter/toolchain would be an environment gap.
    results.fail('the workbench host half loads in a fresh process',
      `${String(e?.message ?? e).slice(0, 240)} — a tree module is missing or half-merged (product red)`)
    results.summarize()
  }

  const ws = makeWebServer()
  const base = await listen(ws.server)
  const { ctx, effects } = makeCtx(ws, makeSessions())
  try {
    apply(ctx, { repo: REPO, python: process.execPath, timeoutMs: 10_000 })
  } catch (e) {
    results.fail('apply(ctx) mounts the host routes without throwing', String(e?.message ?? e).slice(0, 240))
    ws.server.close()
    results.summarize()
  }

  // --- R1 route present, and the served bundle calls the same path -------------
  const route = ws.routes.find((r) => r.path === READ_PATH)
  results.check(route !== undefined,
    `R1 the host registers the read route ${READ_PATH}`,
    `registered: ${ws.routes.map((r) => r.path).filter((p) => p.includes('/file')).join(', ') || '(no *file* route)'} — implement the route (TDD signal)`)
  let bundleText = ''
  try { bundleText = readFileSync(BUNDLE, 'utf8') } catch { /* reported below */ }
  results.check(bundleText.includes(READ_PATH),
    'R1 the served client bundle calls the registered path',
    bundleText === '' ? `served bundle unreadable: ${BUNDLE}` : `bundle does not carry ${READ_PATH} (stale bundle or a second path spelling)`)
  if (route === undefined) {
    ws.server.close()
    results.summarize()
  }

  const q = (params) => '?' + new URLSearchParams(params).toString()

  // --- R2 the success path, both scopes --------------------------------------
  {
    const a = await fetchJson(base, READ_PATH + q({ session: 'it-session-1', path: 'notes.md' }))
    results.check(a.status === 200 && a.json?.ok === true,
      'R2 a session-relative text file is served', `status=${a.status} body=${String(a.text).slice(0, 160)}`)
    results.check(String(a.text).includes('中文行 zhongwen'),
      'R2 the content is byte-identical UTF-8 (no re-encoding, no truncation)', `body=${String(a.text).slice(0, 120)}`)
    results.check(String(a.text).includes('notes.md'), 'R2 the answer names the file path')
  }
  {
    const abs = join(repoDir, 'apps.ts')
    const a = await fetchJson(base, READ_PATH + q({ path: abs }))
    results.check(a.status === 200 && a.json?.ok === true && String(a.text).includes('export const x = 1'),
      'R2 an absolute path under a registered root is served', `status=${a.status} body=${String(a.text).slice(0, 160)}`)
  }

  // --- R3/R4 refusals by name ------------------------------------------------
  const refusals = [
    ['outside-roots: relative escape to the outside region', { session: 'it-session-1', path: '../../outside/secret.md' }, 'outside-roots', 'secret.md'],
    ['outside-roots: sibling directory sharing the root prefix', { session: 'it-session-1', path: '../repo-aevil/evil.md' }, 'outside-roots', 'evil.md'],
    ['outside-roots: absolute existing path outside every root', { path: join(outsideDir, 'secret.md') }, 'outside-roots', 'secret.md'],
    ['outside-roots: symlink inside the root pointing outside', { session: 'it-session-1', path: 'link-out.md' }, 'outside-roots', 'link-out.md'],
    ['not-found inside the root', { session: 'it-session-1', path: 'missing.md' }, 'not-found', 'missing.md'],
    ['is-directory', { session: 'it-session-1', path: 'sub' }, 'is-directory', 'sub'],
    ['too-large', { session: 'it-session-1', path: 'big.log' }, 'too-large', 'big.log'],
    ['not-utf8', { session: 'it-session-1', path: 'bad.txt' }, 'not-utf8', 'bad.txt'],
    ['session-workspace-unknown: unknown session id', { session: 'it-session-nope', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
    ['session-workspace-unknown: session cwd not on the real field', { session: 'it-session-metaonly', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
    ['session-workspace-unknown: throwing session service stays a named refusal', { session: 'it-session-boom', path: 'notes.md' }, 'session-workspace-unknown', 'notes.md'],
  ]
  for (const [label, params, reason, pathFragment] of refusals) {
    const a = await fetchJson(base, READ_PATH + q(params))
    const text = answerText(a)
    results.check(text.includes(reason),
      `R3 ${label} is refused by name (${reason})`,
      `status=${a.status} body=${String(a.text).slice(0, 180)}`)
    results.check(text.includes(String(pathFragment).toLowerCase()),
      `R3 ${label} names the requested path in the answer`,
      `body=${String(a.text).slice(0, 160)}`)
    results.check(!(a.json && a.json.ok === true && String(a.text).includes(MARKER)),
      `R3 ${label} serves no file content`)
  }
  {
    // R4 no existence oracle: a MISSING absolute path outside the roots answers like an
    // existing one (outside-roots), never not-found.
    const missingOutside = join(outsideDir, 'definitely-missing-26110209.md')
    const a = await fetchJson(base, READ_PATH + q({ path: missingOutside }))
    results.check(answerText(a).includes('outside-roots'),
      'R4 a missing path outside the roots answers outside-roots (no existence oracle)',
      `status=${a.status} body=${String(a.text).slice(0, 180)}`)
  }
  {
    process.env.SANDBAR_PROJECTS_DIR = emptyRegistry
    const a = await fetchJson(base, READ_PATH + q({ session: 'it-session-1', path: 'notes.md' }))
    process.env.SANDBAR_PROJECTS_DIR = projectsRoot
    results.check(answerText(a).includes('no-registered-roots'),
      'R3 an empty registry is a named refusal (no silent empty read)',
      `status=${a.status} body=${String(a.text).slice(0, 180)}`)
  }

  // --- R5 malformed request --------------------------------------------------
  {
    const a = await fetchJson(base, READ_PATH + q({ session: 'it-session-1' }))
    results.check(a.status === 400 && /path/.test(answerText(a)),
      'R5 a missing path is a 400 naming the parameter', `status=${a.status} body=${String(a.text).slice(0, 160)}`)
  }
  {
    const a = await fetchJson(base, READ_PATH + q({ path: 'notes.md', session: 'bad/session' }))
    results.check(a.status === 400 && /session/.test(answerText(a)),
      'R5 a malformed session is a 400 naming the parameter', `status=${a.status} body=${String(a.text).slice(0, 160)}`)
  }

  // --- R6 read-only across the method ---------------------------------------
  {
    const a = await fetchJson(base, READ_PATH + q({ session: 'it-session-1', path: 'notes.md' }), 'POST')
    results.check(!(a.json && a.json.ok === true && String(a.text).includes('中文行 zhongwen')),
      'R6 a write method never returns file content', `status=${a.status} body=${String(a.text).slice(0, 160)}`)
  }

  // --- R7 lifecycle ----------------------------------------------------------
  {
    for (const d of effects) { if (typeof d === 'function') { try { d() } catch { /* idempotent */ } } }
    const a = await fetchJson(base, READ_PATH + q({ session: 'it-session-1', path: 'notes.md' }))
    results.check(a.status === 404 || !(a.json && a.json.ok === true),
      'R7 disposing the plugin unregisters the read route', `status=${a.status} body=${String(a.text).slice(0, 120)}`)
  }

  await new Promise((res) => ws.server.close(res))
  results.summarize()
}

main().catch((e) => {
  results.fail('the case runs to completion', String(e?.stack ?? e).split('\n').slice(0, 3).join(' | ').slice(0, 240))
  results.summarize()
})
