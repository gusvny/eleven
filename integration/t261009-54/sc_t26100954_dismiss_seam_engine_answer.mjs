#!/usr/bin/env node
/**
 * sc_t26100954_dismiss_seam_engine_answer.mjs — the left-column dismiss button's
 * answer side: the panel POST op route → the engine's own dismiss/restore op →
 * the audit journal → the ticket-list face (ticket t261009-54).
 *
 * Run directly: node integration/t261009-54/sc_t26100954_dismiss_seam_engine_answer.mjs
 * (cwd = repo root), or through the registry entry in integration/run_scenarios.py.
 *
 * Grey-box L3, offline seconds, zero docker / Temporal-server / real browser,
 * never touches 3099. The incident: the host pressed dismiss on a failed
 * ticket and nothing happened — the button posted to a route the panel's op
 * table refused (404 未知操作 dismiss), so the click was proven (t261009-43
 * read the client source text) while "something answers" never was. This entry
 * owns the answer side END TO END over the REAL seam:
 *
 *   real node.ts POST dispatch  →  admin.py call contract
 *     →  REAL server/tools/ticket.py op=dismiss|restore
 *     →  REAL server/engine/ticket_dismiss.py journal (a file on disk)
 *     →  journal read back FROM THE FILE (reader-side evidence, not the POST's ok)
 *     →  ticket-list face reports the row dismissed / un-dismissed.
 *
 * The only stubbed pieces are the process boundary fixtures the panel itself
 * treats as externals: admin.py (a thin passthrough that shells the REAL
 * ticket.py and logs every payload it receives) and the engine venv python
 * (serves ticket-list from the REAL journal via the REAL read face — the same
 * substitution the panel's runPocCli boundary implies). No dismissal logic is
 * stubbed: the route, the op, the journal and the read face are all the
 * production modules.
 *
 * Legs:
 *  A  a dismiss POST answers 200 ok:true with the engine's own receipt, and the
 *     journal FILE gains exactly one row whose who is the REQUEST's operator
 *     identity (the audit anchor — a route-hard-coded identity would pass a
 *     click test and fail an audit), reason verbatim; the ticket-list face then
 *     reports the row as dismissed (at/who/reason) — the face change comes from
 *     the engine payload, and the who→by mapping plus the declared caller
 *     project are visible in the payload admin.py actually received.
 *  B  restore brings the row back: a second journal row (append-only, last row
 *     wins), and the list face reports the ticket NOT dismissed again.
 *  C  the engine's state contract holds and its refusals pass through verbatim
 *     and zero-write: a dismiss AFTER a restore is ALLOWED (last-row-wins
 *     reversibility, never refused on any-row-exists); a dismiss while the
 *     standing action IS dismiss and a restore on a never-dismissed ticket
 *     each answer ok:false quoting the standing disposition, journal bytes
 *     identical — never a 404, never an empty body, never a success.
 *  D  shape/existence refusals pass through verbatim and zero-write: empty
 *     reason (never defaulted), agent-role who (an agent may not dismiss a
 *     ticket it failed), missing who, unknown ticket — each ok:false with the
 *     engine's named reason, journal digest unchanged.
 *  E  the route invents nothing: a truly empty reason still reaches the engine
 *     and is refused there (the client-side trim gate is not the only guard),
 *     and the payload admin.py received carries reason exactly as the client
 *     sent it ('' — no default), the who arriving as `by` unmangled.
 *  F  the one-route shape holds: an unknown op still gets the named 404 face
 *     listing the available ops (dismiss/restore now among them); a GET on the
 *     op path is 405; a malformed JSON body is a named 400.
 *
 * Intent split: developer L1 (tests/t261009-54-dismiss-route.mjs) owns the
 * route's mapping truth tables over a FAKE admin; t261009-31's entries own the
 * journal/op contract in isolation; t261009-43 owns the left-column face and
 * the click-side wiring shape. This entry owns what none of those can: the
 * route answered by the REAL engine op with the journal landing on disk and
 * the list face actually changing — the evidence class the dead-button
 * incident showed missing. Engine/ticket sources or python3 missing = ENV_FAIL
 * exit 2; route faces not landed = FAIL named (TDD red); green required at the
 * integration gate / merge.
 */
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, rmSync, existsSync, copyFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { apply } from './../../server/plugins/workbench/node.ts'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const ROUTE = '/sandbar-workbench/api/wf/tickets'
const TICKET = 't54-dead-failed'
const FRESH = 't54-never-dismissed'

let pass = 0, fail = 0, na = 0
function ok(cond, label, detail = '') {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}${detail ? ' — ' + detail : ''}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------- environment gates (three-state, exit 2) ---------------- */

const py = spawnSync('python3', ['-c', 'print(1)'])
if (py.error || py.status !== 0) { console.log('ENV_FAIL: python3 runtime missing'); process.exit(2) }
const needed = [
  'server/plugins/workbench/node.ts',
  'server/tools/ticket.py',
  'server/engine/ticket_dismiss.py',
  'server/engine/audit.py',
  'server/engine/shared.py',
]
for (const rel of needed) {
  if (!existsSync(join(ROOT, rel))) { console.log(`ENV_FAIL: production tree missing ${rel}`); process.exit(2) }
}

/* ---------------- fixture repo: real modules, fake process boundary ---------------- */

const ENGINE_STUB = `#!/usr/bin/env python3
"""Fake engine venv python: serves ticket-list (the panel's list face and
ticket.py's existence gate) from the REAL dismissal journal via the REAL
read face. Everything else answers an empty ok."""
import sys, json, os
ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ENGINE_DIR)
sub = sys.argv[2] if len(sys.argv) > 2 else ''
if sub != 'ticket-list':
    print(json.dumps({'ok': True, 'result': {}}))
    raise SystemExit(0)
import ticket_dismiss as td
rows = td.read_dismiss_journal(None)
tickets = []
for tid in os.environ.get('T54_TICKET_IDS', '${TICKET},${FRESH}').split(','):
    row = {'id': tid, 'project': 'alpha', 'epic': '', 'role': 'developer',
           'status': 'failed', 'title': 'dead failed ticket',
           'workflow': 'DevLaneWorkflow', 'stage': 'review',
           'stage_state': 'failed', 'paused': False, 'paused_phase': '',
           'handoff_count': 0, 'pending_count': 0, 'worktree': '',
           'workspace': None, 'created': 1000, 'updated': '10-10 09:00',
           'updated_ts': 1760000000, 'engine': 'v2', 'exec_status': 'FAILED',
           'close_ts': 0}
    face = td.dismissed_face(td.dismissed_ticket_row(rows, tid))
    if face is not None:
        row['dismissed'] = face
    tickets.append(row)
print(json.dumps({'ok': True, 'result': {'count': len(tickets), 'tickets': tickets}}))
`

const ADMIN_STUB = `#!/usr/bin/env python3
"""Fake admin.py: a logging passthrough. Shells the REAL ticket.py copy with
the payload verbatim and relays its structured receipt + exit code. Every
payload the route sent is appended to T54_ADMIN_LOG (one JSON per line)."""
import json, os, subprocess, sys
args = sys.argv[1:]
tool = args[1] if len(args) > 1 else ''
payload = args[2] if len(args) > 2 else '{}'
with open(os.environ['T54_ADMIN_LOG'], 'a', encoding='utf-8') as f:
    f.write(payload + chr(10))
if tool != 'ticket':
    if tool == 'workflow':
        print(json.dumps({'ok': True, 'result': {'workflows': []}}))
        raise SystemExit(0)
    print(json.dumps({'ok': False, 'error': 'fake admin: unexpected tool %r' % tool}))
    raise SystemExit(1)
ticket_py = os.path.join(os.environ['T54_FAKE_REPO'], 'server', 'tools', 'ticket.py')
p = subprocess.run([sys.executable, ticket_py, payload], capture_output=True, text=True)
sys.stdout.write(p.stdout or json.dumps({'ok': False, 'error': (p.stderr or 'ticket.py produced no output')[:400]}))
raise SystemExit(p.returncode or 0)
`

function makeRepo(tmp) {
  const repo = join(tmp, 'repo')
  mkdirSync(join(repo, 'server', 'tools'), { recursive: true })
  mkdirSync(join(repo, 'server', 'engine'), { recursive: true })
  // REAL production modules under test, isolated env
  copyFileSync(join(ROOT, 'server/tools/ticket.py'), join(repo, 'server/tools/ticket.py'))
  for (const f of ['ticket_dismiss.py', 'audit.py', 'shared.py']) {
    copyFileSync(join(ROOT, 'server/engine', f), join(repo, 'server/engine', f))
  }
  // project registry (findProject whitelist data source, t260910-04 fixture shape)
  const reg = join(tmp, 'registry')
  mkdirSync(join(reg, 'alpha'), { recursive: true })
  writeFileSync(join(reg, 'alpha', 'project.yaml'),
    'schema: v1\nproject:\n  - key: alpha\n    name: seam\n    dirs:\n      - ' + join(tmp, 'alpha') + '\n', 'utf8')
  writeFileSync(join(reg, '.migrated'), 'fixture\n', 'utf8')
  writeFileSync(join(repo, 'server', 'admin.py'), ADMIN_STUB, 'utf8')
  const engineBin = join(repo, 'server', 'engine', '.venv', 'bin', 'python')
  mkdirSync(dirname(engineBin), { recursive: true })
  writeFileSync(engineBin, ENGINE_STUB, 'utf8')
  chmodSync(engineBin, 0o755)
  return repo
}

function makeHarness(repo, adminLog) {
  const routes = []
  const ws = { register: (r) => { routes.push(r); return () => {} } }
  const ctx = {
    effect: (fn) => { fn() },
    logger: { info() {}, warn() {} },
    get: (k) => (k === 'webServer' ? ws : undefined),
    on: () => () => {},
  }
  apply(ctx, { repo, python: 'python3' })
  // list/create live on the exact route; the op dispatch (<id>/<op>) on the prefix route
  const ticketsList = routes.find(r => r.kind !== 'prefix' && r.path === ROUTE)
  const ticketsOp = routes.find(r => r.kind === 'prefix' && r.path === ROUTE)
  return { tickets: ticketsOp, ticketsList }
}

const mockRes = () => ({
  status: 0, body: null, raw: null,
  writeHead(s) { this.status = s },
  end(b) { this.raw = b ?? ''; try { this.body = JSON.parse(b) } catch { this.body = null } },
})
const call = async (handler, url, method = 'GET', bodyObj) => {
  const res = mockRes()
  const chunks = bodyObj === undefined ? [] : [Buffer.from(JSON.stringify(bodyObj))]
  const req = { url, method, async *[Symbol.asyncIterator]() { yield* chunks } }
  await handler.handler(req, res)
  return res
}

const journalPath = (tmp) => join(tmp, 'journal', 'ticket-dismiss.jsonl')
const readRows = (tmp) => {
  try {
    return readFileSync(journalPath(tmp), 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l))
  } catch { return [] }
}
const digest = (tmp) => {
  try { return createHash('sha256').update(readFileSync(journalPath(tmp))).digest('hex') } catch { return 'absent' }
}
const adminPayloads = (adminLog) => readFileSync(adminLog, 'utf8').split('\n').filter(l => l.trim()).map(l => JSON.parse(l))

/* ---------------- env pinning (restored in finally) ---------------- */

const savedEnv = { ...process.env }
process.env.SANDBAR_PROJECTS_YAML = ''

let tmp = null
try {
  /* ---------------- A+B: the answer side, end to end ---------------- */
  section('A dismiss POST → real engine op → journal row on disk → list face dismissed')
  tmp = mkdtempSync(join(tmpdir(), 't54-seam-'))
  process.env.SANDBAR_PROJECTS_DIR = join(tmp, 'registry')
  process.env.SANDBAR_DISMISS_DIR = join(tmp, 'journal')
  process.env.T54_FAKE_REPO = join(tmp, 'repo')
  process.env.T54_ADMIN_LOG = join(tmp, 'admin-log.jsonl')
  const repo = makeRepo(tmp)
  const h = makeHarness(repo)
  ok(!!h.tickets, 'panel tickets route registered')
  const WHO = 'host-person-x'
  const r = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST',
    { who: WHO, reason: 'dead for 3 days' })
  ok(r.status === 200, 'dismiss answers 200 (not the old 未知操作 404)', `status=${r.status} body=${JSON.stringify(r.body)}`)
  ok(r.body?.ok === true, 'engine receipt ok:true passes through verbatim')
  ok(r.body?.result?.dismissed?.who === WHO, 'receipt names the request identity as the disposer')
  const rows = readRows(tmp)
  ok(rows.length === 1, 'exactly one journal row written', `rows=${rows.length}`)
  const row = rows[0] ?? {}
  ok(row.who === WHO && row.reason === 'dead for 3 days' && row.action === 'dismiss' && row.ticket_id === TICKET,
    'journal row: who=request identity (audit anchor), reason verbatim, action, ticket id',
    JSON.stringify(row))
  const sent = adminPayloads(process.env.T54_ADMIN_LOG).at(-1) ?? {}
  ok(sent.by === WHO && sent.reason === 'dead for 3 days' && sent.op === 'dismiss' && sent.id === TICKET,
    'route mapped who→by with the request values (no sidebar constant)', JSON.stringify(sent))
  ok(sent.caller_project === 'alpha', 'declared caller project travels with the write (t260928-24 identity gate)')

  const lr = await call(h.ticketsList, `${ROUTE}?project=alpha`)
  const lrow = (lr.body?.result?.tickets ?? []).find(t => t.id === TICKET)
  ok(!!lrow?.dismissed && lrow.dismissed.who === WHO && lrow.dismissed.reason === 'dead for 3 days',
    'ticket-list face reports the row dismissed with the voucher (at/who/reason)',
    JSON.stringify(lrow?.dismissed))

  section('B restore brings the row back (append-only, last row wins)')
  const rr = await call(h.tickets, `${ROUTE}/${TICKET}/restore?project=alpha`, 'POST',
    { who: WHO, reason: 'put it back' })
  ok(rr.status === 200 && rr.body?.ok === true, 'restore answers 200 ok:true')
  const rows2 = readRows(tmp)
  ok(rows2.length === 2 && rows2[1].action === 'restore', 'second journal row appended, action=restore', JSON.stringify(rows2[1] ?? {}))
  const lr2 = await call(h.ticketsList, `${ROUTE}?project=alpha`)
  const lrow2 = (lr2.body?.result?.tickets ?? []).find(t => t.id === TICKET)
  ok(lrow2 && lrow2.dismissed === undefined, 'list face reports the ticket NOT dismissed after restore')

  section('C state refusals pass through verbatim, zero-write; reversibility holds')
  // after B the standing action is restore, so ONE more dismiss is legal (last-row-wins
  // reversibility); only a dismiss while the standing action IS dismiss is refused.
  const beforeC = digest(tmp)
  const rowsBeforeC = readRows(tmp).length
  const c0 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST',
    { who: WHO, reason: 'dismiss again after restore' })
  ok(c0.status === 200 && c0.body?.ok === true, 'dismiss after a restore is ALLOWED (reversibility, never refused on any-row-exists)', `status=${c0.status} body=${JSON.stringify(c0.body)}`)
  ok(readRows(tmp).length === rowsBeforeC + 1, 'the legal re-dismiss appends exactly one more row')
  const settled = digest(tmp)   // after the legal re-dismiss: the refusal baseline
  const c1 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST',
    { who: WHO, reason: 'again' })
  ok(c1.status === 200 && c1.body?.ok === false, 're-dismiss: refusal is JSON ok:false on 200 — never a 404, never empty', `status=${c1.status} body=${JSON.stringify(c1.body)}`)
  ok(String(c1.body?.error ?? '').includes('already dismissed'), 're-dismiss refusal quotes the standing disposition', String(c1.body?.error))
  // a ticket that was never dismissed refuses restore (second fixture id)
  const c2 = await call(h.tickets, `${ROUTE}/${FRESH}/restore?project=alpha`, 'POST',
    { who: WHO, reason: 'nothing to restore' })
  ok(c2.status === 200 && c2.body?.ok === false && String(c2.body?.error ?? '').includes('not dismissed'), 'restore-when-not-dismissed refused by name', `body=${JSON.stringify(c2.body)}`)
  ok(digest(tmp) === settled, 'state refusals are zero-write (journal digest unchanged)', `settled=${settled} after=${digest(tmp)}`)

  section('D shape/existence refusals: verbatim reason, zero-write, never defaulted')
  const beforeD = digest(tmp)
  const d1 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST', { who: WHO, reason: '   ' })
  ok(d1.body?.ok === false && String(d1.body?.error ?? '').includes('reason'),
    'empty reason refused with the ENGINE reason (route did not default or paper over)', String(d1.body?.error))
  const d2 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST',
    { who: 'developer', reason: 'an agent trying' })
  ok(d2.body?.ok === false && String(d2.body?.error ?? '').includes('agent role name'),
    'agent-role who refused: an agent may not dismiss a ticket it failed', String(d2.body?.error))
  const d3 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST', { reason: 'no identity' })
  ok(d3.body?.ok === false && String(d3.body?.error ?? '').includes('who'), 'missing who refused by name')
  const d4 = await call(h.tickets, `${ROUTE}/t54-ghost/dismiss?project=alpha`, 'POST', { who: WHO, reason: 'ghost' })
  ok(d4.body?.ok === false && String(d4.body?.error ?? '').includes('unknown ticket'), 'unknown ticket refused by the existence gate', String(d4.body?.error))
  ok(digest(tmp) === beforeD, 'all shape/existence refusals zero-write (journal digest unchanged)')

  section('E the route invents nothing (payload admin received == what client sent)')
  const e1 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'POST', { who: WHO, reason: '' })
  ok(e1.status === 200 && e1.body?.ok === false && String(e1.body?.error ?? '').includes('reason'),
    'truly empty reason also refused by the engine (no client-side-only gate)', String(e1.body?.error))
  const lastPayload = adminPayloads(process.env.T54_ADMIN_LOG).at(-1) ?? {}
  ok(lastPayload.op === 'dismiss' && lastPayload.by === WHO && lastPayload.reason === '',
    'empty reason reached the engine as empty string — no default injected', JSON.stringify(lastPayload))

  section('F one-route shape: named 404 for unknown op, 405 on GET, named 400 on bad JSON')
  const f1 = await call(h.tickets, `${ROUTE}/${TICKET}/frobnicate?project=alpha`, 'POST', { who: WHO })
  // pin the stable host-copy anchor 未知操作 (node.ts `未知操作 ${op}（可用：…）`)
  // and the op name separately — the interpolated whole sentence is never a
  // literal in the product source, so pinning it verbatim would rot by design.
  ok(f1.status === 404 && String(f1.body?.error ?? '').includes('未知操作')
    && String(f1.body?.error ?? '').includes('frobnicate'),
    'unknown op keeps the named 404 face', JSON.stringify(f1.body))
  ok(String(f1.body?.error ?? '').includes('dismiss') && String(f1.body?.error ?? '').includes('restore'),
    'the 404 face now lists dismiss/restore among the available ops')
  const f2 = await call(h.tickets, `${ROUTE}/${TICKET}/dismiss?project=alpha`, 'GET')
  ok(f2.status === 405, 'op path is POST-only (GET 405)')
  const badRes = mockRes()
  const badReq = { url: `${ROUTE}/${TICKET}/dismiss?project=alpha`, method: 'POST', async *[Symbol.asyncIterator]() { yield Buffer.from('{not json') } }
  await h.tickets.handler(badReq, badRes)
  ok(badRes.status === 400 && String(badRes.body?.error ?? '').includes('JSON'), 'malformed JSON body is a named 400')

  rmSync(tmp, { recursive: true, force: true })
  tmp = null
} catch (err) {
  fail++
  console.error(`FAIL scenario threw — ${err instanceof Error ? err.stack : String(err)}`)
} finally {
  if (tmp) { try { rmSync(tmp, { recursive: true, force: true }) } catch {} }
  for (const k of ['SANDBAR_PROJECTS_DIR', 'SANDBAR_PROJECTS_YAML', 'SANDBAR_DISMISS_DIR', 'T54_FAKE_REPO', 'T54_ADMIN_LOG', 'T54_TICKET_IDS']) {
    if (savedEnv[k] === undefined) delete process.env[k]; else process.env[k] = savedEnv[k]
  }
}

console.log(`\nSUMMARY pass=${pass} fail=${fail} na=${na}`)
process.exit(fail > 0 ? 1 : 0)
