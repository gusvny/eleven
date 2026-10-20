#!/usr/bin/env node
/**
 * t261019-12 — /api/epics serves docs/epics front-matter; the status vocabulary is dead.
 *
 * Grey-box L3 (integration-owned), ticket t261019-12, authority
 * docs/design/epic-registry-v1.md (4561583e). The REAL workbench route face
 * (server/plugins/workbench/node.ts, mounted via apply()) over a fixture epic
 * directory through SANDBAR_EPICS_DIR (the documented operator override — same
 * technique as tests/epics-api.mjs). Offline seconds, zero docker/Temporal/
 * browser, never touches 3099/7233.
 *
 * User-perceivable contract under test:
 *   A THE LIST — GET /sandbar-workbench/api/epics returns code + retired +
 *     summary + started per epic (the ONLY document prose reaching the surface
 *     is summary); a malformed doc never reads as healthy (fail-closed: a
 *     defect face or a named per-item error, never a silently normal row).
 *   B THE HARD CUT — a missing epic directory is a NAMED error, never an
 *     empty 200 pretending "no epics"; a live doc under notes/epics only is
 *     not served.
 *   C THE DEAD VOCABULARY — POST /epics/<code>/close and /epics/<code>/status
 *     are gone (4xx, never a 200 that rewrites a status row); GET detail and
 *     GET /tickets survive (read-only contract, Temporal aggregation intact).
 *
 * Intent split: the enforcement journey (validate_epic_code refusal +
 * store-move resolution) belongs to sc_t26101912_epic_refusal_hard_cut; the
 * Epics tab render (mock face) belongs to the executor-panel tests; parser
 * unit matrices belong to developer L1.
 *
 * Pre-implement tree: A/C red = the named TDD signal; green required at the
 * integration gate / merge. node or node.ts unresolvable = ENV_FAIL exit 2.
 * Contract: PASS/FAIL/ENV_FAIL only — no SKIP.
 */

import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
let mod
try {
  mod = await import(join(ROOT, 'server/plugins/workbench/node.ts'))
} catch (e) {
  console.error(`ENV_FAIL: workbench node.ts unresolvable: ${e && e.message}`)
  process.exit(2)
}
const { apply } = mod

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo })
  const find = (kind, path) => routes.find(r => r.kind === kind && r.path === path)
  return {
    exactEpics: find('exact', '/sandbar-workbench/api/epics'),
    prefixEpics: find('prefix', '/sandbar-workbench/api/epics'),
  }
}
const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const call = async (handler, url, method = 'GET', bodyObj) => {
  const res = mockRes()
  const payload = bodyObj === undefined ? [] : [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* payload } }
  await handler.handler(req, res)
  return res
}

const GOOD = (code, retired, summary) =>
  `---\ncode: ${code}\nretired: ${retired}\nsummary: ${summary}\nstarted: 2026-10-19\n---\n\n# ${code}\n\nIntent and problem.\n`

const tmp = await mkdtemp(join(tmpdir(), 'integ-t26101912-'))
const savedEnv = process.env.SANDBAR_EPICS_DIR
try {
  // ------------------------------------------------------------- A. the list
  section('A /api/epics serves code + retired + summary + started; summary is the only prose')
  const epicsDir = join(tmp, 'docs', 'epics')
  await mkdir(epicsDir, { recursive: true })
  await writeFile(join(epicsDir, 'live-epic.md'),
    GOOD('live-epic', 'false', 'It still takes tickets.'), 'utf8')
  await writeFile(join(epicsDir, 'dead-epic.md'),
    GOOD('dead-epic', 'true', 'It no longer takes tickets.'), 'utf8')
  await writeFile(join(epicsDir, 'defect.md'), '# no front matter\n', 'utf8')
  const repoA = join(tmp, 'repo-a')
  await mkdir(join(repoA, 'server'), { recursive: true })
  await writeFile(join(repoA, 'server', 'admin.py'),
    `import json, sys\nprint(json.dumps({"ok": True, "result": {"count": 0, "tickets": []}}))\n`, 'utf8')
  process.env.SANDBAR_EPICS_DIR = epicsDir
  const h = makeHarness(repoA)
  ok(h.exactEpics !== undefined && h.prefixEpics !== undefined, 'epics routes mounted')
  let r = await call(h.exactEpics, '/sandbar-workbench/api/epics')
  ok(r.status === 200, 'GET list -> 200')
  const items = (r.body && r.body.result && (r.body.result.epics || r.body.result.items || r.body.result.list))
    || (Array.isArray(r.body && r.body.result) ? r.body.result : null)
  ok(Array.isArray(items) && items.length === 3, 'list carries every stored epic incl. the defect face')
  const live = items && items.find(x => x.code === 'live-epic')
  const dead = items && items.find(x => x.code === 'dead-epic')
  ok(live && live.retired === false, 'live-epic surfaces retired:false (a boolean, not prose)')
  ok(dead && dead.retired === true, 'dead-epic surfaces retired:true')
  ok(live && typeof live.summary === 'string' && live.summary.startsWith('It still takes tickets'),
    'summary is the surfaced prose')
  ok(live && live.title === undefined && live.status === undefined,
    'no title/status vocabulary on the wire (the state retired, not a status cell)')
  const defect = items && items.find(x => x.code === 'defect')
  ok(defect && (defect.retired === true || defect.defect !== undefined),
    'malformed doc fails closed: defect face or retired-equivalent, never a healthy row')

  // --------------------------------------------------------- B. the hard cut
  section('B missing docs/epics is a named error; notes/epics is not a second source')
  process.env.SANDBAR_EPICS_DIR = join(tmp, 'no-such-dir')
  const hB = makeHarness(repoA)
  r = await call(hB.exactEpics, '/sandbar-workbench/api/epics')
  ok(r.status >= 400 || (r.body && r.body.ok === false),
    'missing epic dir -> named error, never an empty 200')
  const corpse = join(tmp, 'corpse', 'notes', 'epics')
  await mkdir(corpse, { recursive: true })
  await writeFile(join(corpse, 'ghost.md'), GOOD('ghost', 'false', 'Ghost prose.'), 'utf8')
  process.env.SANDBAR_EPICS_DIR = join(tmp, 'corpse', 'docs', 'epics')
  const hC = makeHarness(repoA)
  r = await call(hC.exactEpics, '/sandbar-workbench/api/epics')
  ok(r.status >= 400 || (r.body && r.body.ok === false),
    'a live doc under notes/epics only is NOT served (no silent fallback)')

  // -------------------------------------------------- C. the dead vocabulary
  section('C close/status routes are dead; detail and /tickets survive')
  process.env.SANDBAR_EPICS_DIR = epicsDir
  const hD = makeHarness(repoA)
  r = await call(hD.prefixEpics, '/sandbar-workbench/api/epics/dead-epic/close', 'POST')
  ok(r.status >= 400, 'POST close -> gone (4xx), never a 200 status-row rewrite')
  r = await call(hD.prefixEpics, '/sandbar-workbench/api/epics/dead-epic/status', 'POST', { status: 'x' })
  ok(r.status >= 400, 'POST status -> gone (4xx), never a 200 vocabulary write')
  r = await call(hD.prefixEpics, '/sandbar-workbench/api/epics/live-epic')
  ok(r.status === 200, 'GET detail survives (read-only contract)')
  r = await call(hD.prefixEpics, '/sandbar-workbench/api/epics/live-epic/tickets')
  ok(r.status === 200 && r.body && r.body.ok === true,
    'GET /tickets survives (Temporal aggregation intact)')
  // the refusal face is visible from the API consumer side too: a retired epic
  // cannot be opened against — engine-level refusal is scenario 1's intent; here
  // we pin that the list row says retired:true so the UI badge cannot lie
  r = await call(hD.exactEpics, '/sandbar-workbench/api/epics')
  const after = (r.body && r.body.result && (r.body.result.epics || r.body.result.items || r.body.result.list)) || []
  ok(after.find(x => x.code === 'dead-epic')?.retired === true,
    'after all route probes the badge fact is still retired:true (no write crept in)')
} catch (e) {
  console.error(`FAIL harness exception: ${e && e.stack || e}`)
  fail++
} finally {
  if (savedEnv === undefined) delete process.env.SANDBAR_EPICS_DIR
  else process.env.SANDBAR_EPICS_DIR = savedEnv
  await rm(tmp, { recursive: true, force: true }).catch(() => {})
}

console.log(`\nPASS=${pass} FAIL=${fail}`)
process.exit(fail === 0 ? 0 : 1)
