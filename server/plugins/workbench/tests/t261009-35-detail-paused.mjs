// t261009-35 UT — detail face carries paused/paused_phase + the derived op (API face, fake engine).
//
// Run: node server/plugins/workbench/tests/t261009-35-detail-paused.mjs (exit 0 = pass).
// No network / no real repo / no real Temporal / no console.
//
// Background: the engine snapshot carries paused/paused_phase at top level
// (TicketPauseMixin). The list face already merges both keys; the detail face
// (ticket show -> GET /wf/tickets/<id>) dropped them, so availableOps(detail)
// always offered Pause and a person could not resume from the detail. Fix =
// _v2_query projects both keys (same normalization as the row face: bool /
// str-or-'' ; absent key = False / '' , never 'unknown'). This UT pins two layers:
//   A. host detail-route passthrough shape (a fake admin stands in for the
//      ticket show receipt — node.ts passes it through verbatim and invents no
//      keys: a receipt without the keys yields a response without them, never a
//      fabricated False/''). The normalization contract itself is pinned by the
//      python UT test_t261009_35_v2_query_pause.py — the two layers split the
//      work; a UT never impersonates the engine.
//   B. derivation layer: pauseOpOf truth table (incl. malformed input:
//      undefined / '' / non-boolean) and the detail decision card
//      (decisionCard reads detail.paused === true) — the last hop of the chain
//      that makes the button render Resume.
//
// The against-the-real-engine chain assertion lives in
// integration/t261009-35/sc_detail_pause_faces.mjs (engine integration gate
// tier; unit tier never runs integration entries).
//
// review_plan condition 1 absorbed: the non-boolean-truthy paused assertion is
// bool coercion (bool('yes') === True), NOT verbatim passthrough.

import { mkdtempSync, mkdirSync, rmSync, writeFileSync, chmodSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { apply } from './../node.ts'
import { pauseOpOf } from '../src/client/ticket-list-model.ts'
import { decisionCard } from '../src/client/ticket-detail-column-model.ts'

let pass = 0, fail = 0
/** Every mkdtemp lands here; the finally block reclaims all of them (tmp
 *  hygiene: registry + exit hook, no orphan fixture dirs). */
const tmps = []
function mkTmp(tag) { const d = mkdtempSync(join(tmpdir(), `wb-t935-${tag}-`)); tmps.push(d); return d }
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------- fake-repo harness (t260910-04 shape) ---------------- */

const savedEnv = process.env.SANDBAR_PROJECTS_DIR
delete process.env.SANDBAR_PROJECTS_YAML

/** Fake repo: registry (key=alpha) + fake admin.py (a node script standing in
 *  for the ticket show receipt). */
function makeRepo(tmp, showResult) {
  const repo = join(tmp, 'repo')
  const reg = join(tmp, 'registry')
  mkdirSync(join(reg, 'alpha'), { recursive: true })
  writeFileSync(join(reg, 'alpha', 'project.yaml'),
    'schema: v1\nproject:\n  - key: alpha\n    name: jia\n    dirs:\n      - /tmp/alpha\n', 'utf8')
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  process.env.SANDBAR_PROJECTS_DIR = reg

  mkdirSync(join(repo, 'server'), { recursive: true })
  const payload = JSON.stringify(showResult ?? null)
  const adminScript = `
const args = process.argv.slice(2); // ['call', tool, argsJSON]
const tool = args[1] ?? '';
let op = '';
try { op = (JSON.parse(args[2] ?? '{}') ?? {}).op ?? '' } catch { op = '' }
if (tool === 'workflow') {
  console.log(JSON.stringify({ ok: true, result: { workflows: [{ id: 'wf1' }] } }));
  process.exit(0);
}
if (tool === 'ticket' && op === 'show') {
  const p = ${payload};
  // An engine-level failure receipt (ok:false with kind) goes up verbatim —
  // the admin face never wraps a failure into ok:true.
  if (p && p.ok === false) { console.log(JSON.stringify(p)); process.exit(0); }
  console.log(JSON.stringify({ ok: true, result: p }));
  process.exit(0);
}
console.log(JSON.stringify({ ok: false, error: 'FAKE-ADMIN: unexpected call ' + tool + '/' + op }));
process.exit(1);
`
  writeFileSync(join(repo, 'server', 'admin.py'), adminScript, 'utf8')

  // Fake engine venv python (the detail route never consumes it; placeholder
  // so a stray call cannot reach a real engine).
  const engineBin = join(repo, 'server', 'engine', '.venv', 'bin', 'python')
  mkdirSync(dirname(engineBin), { recursive: true })
  writeFileSync(engineBin, `#!/usr/bin/env node\nprocess.stdout.write('{"ok":false,"error":"FAKE-ENGINE"}')\n`, 'utf8')
  chmodSync(engineBin, 0o755)
  return repo
}

function makeHarness(repo) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo, python: process.execPath })
  // The detail route is the prefix registration (TICKETS_PREFIX, see node.ts
  // attach); the exact list route shares the same path string — pick by
  // kind=prefix or we grab the list handler (400 without project).
  const find = (p) => routes.find(r => r.path === p && r.kind === 'prefix')
  return { detail: find('/sandbar-workbench/api/wf/tickets') }
}

const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b ?? ''; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const callDetail = async (handler, id) => {
  const res = mockRes()
  const req = { url: `/sandbar-workbench/api/wf/tickets/${id}`, method: 'GET', async *[Symbol.asyncIterator]() { yield* [] } }
  await handler.handler(req, res)
  return res
}

/** Detail show receipt base shape (a subset of the post-fix ticket.py
 *  _v2_query meta shape). */
function showMeta(over = {}) {
  return {
    id: 't261009-35', project: 'alpha', status: 'running',
    title: 'detail carries pause', workflow_id: 'dev-lane',
    stage: 'implement', stage_state: 'running',
    paused: true, paused_phase: 'at_gate',
    worktree: '', engine: 'template-as-code-v2',
    ...over,
  }
}

try {
  /* ---------------- A host detail-route passthrough ---------------- */
  section('A detail face passes paused/paused_phase through (host layer verbatim, no invented keys)')
  {
    const tmp = mkTmp('a')
    const repo = makeRepo(tmp, showMeta())
    const { detail } = makeHarness(repo)
    const res = await callDetail(detail, 't261009-35')
    ok(res.status === 200, 'A1 detail GET 200')
    ok(res.body?.result?.paused === true && res.body?.result?.paused_phase === 'at_gate',
       `A2 paused/paused_phase pass through verbatim (got ${JSON.stringify({ p: res.body?.result?.paused, ph: res.body?.result?.paused_phase })})`)
    ok(res.body?.result?.stage_state === 'running', 'A3 other keys still pass through (stage_state)')
  }
  {
    // A receipt without the two keys (old ticket / degraded shape) -> the host
    // passes the absence through and never fabricates False/'' on the engine's
    // behalf. (The False/'' normalization lives in ticket.py; pinned by the py
    // UT. The host only relays.)
    const tmp = mkTmp('b')
    const m = showMeta(); delete m.paused; delete m.paused_phase
    const repo = makeRepo(tmp, m)
    const { detail } = makeHarness(repo)
    const res = await callDetail(detail, 't261009-35')
    ok(res.status === 200 && !('paused' in (res.body?.result ?? {})) && !('paused_phase' in (res.body?.result ?? {})),
       'A4 receipt without the keys -> response without them (host invents nothing; normalization lives in the engine)')
  }
  {
    // Engine receipt ok:false -> the detail route keeps its split-by-kind
    // error contract (KI-025; unchanged by this ticket).
    const tmp = mkTmp('c')
    const repo = makeRepo(tmp, { ok: false, kind: 'not_found', error: 'no such ticket' })
    const { detail } = makeHarness(repo)
    const res = await callDetail(detail, 't-nope')
    ok(res.status === 404, `A5 ok:false(kind=not_found) -> 404 (got ${res.status})`)
  }

  /* ---------------- B derivation layer: pauseOpOf + detail decision card ---------------- */
  section('B derivation-layer truth table (incl. malformed input)')
  {
    ok(pauseOpOf(true) === 'resume', 'B1 pauseOpOf(true)===resume (a paused ticket offers Resume)')
    ok(pauseOpOf(false) === 'pause', 'B2 pauseOpOf(false)===pause')
    // Malformed input: the detail pair missing (post-normalization the engine
    // always sends the keys, but degraded/old shapes can still lack them)
    // -> pause, never a wrong Resume.
    ok(pauseOpOf(undefined) === 'pause', 'B3 pauseOpOf(undefined)===pause (missing key)')
    ok(pauseOpOf('') === 'pause', 'B4 pauseOpOf("")===pause (empty string)')
    ok(pauseOpOf(null) === 'pause', 'B5 pauseOpOf(null)===pause (null)')
    // Non-boolean truthy values follow bool-coercion semantics (the engine
    // normalizes bool('yes')===True; both ends agree).
    ok(pauseOpOf('yes') === 'resume' && pauseOpOf(1) === 'resume',
       "B6 non-boolean truthy ('yes'/1)===resume (bool-coercion semantics, same as engine normalization)")
  }
  {
    const d = showMeta()
    ok(decisionCard(d, null)?.title === 'Paused by you', 'B7 decision card reads detail.paused===true -> Paused by you')
    const d2 = showMeta({ paused: false })
    ok(decisionCard(d2, null)?.title === 'At work: implement', 'B8 not paused -> At work (no pause card)')
    const d3 = showMeta(); delete d3.paused
    ok(decisionCard(d3, null)?.title === 'At work: implement', 'B9 missing paused key -> never treated as paused (malformed degrade)')
  }

  console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
  process.exit(fail === 0 ? 0 : 1)
} finally {
  for (const d of tmps) { try { rmSync(d, { recursive: true, force: true }) } catch { /* best-effort */ } }
  if (savedEnv === undefined) delete process.env.SANDBAR_PROJECTS_DIR
  else process.env.SANDBAR_PROJECTS_DIR = savedEnv
}
