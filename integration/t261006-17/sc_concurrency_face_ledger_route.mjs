// sc_concurrency_face_ledger_route.mjs — t261006-17 (CL-2) scenario 1.
//
// intent: the panel read face reads the ENGINE ledger, never recomputes, and
// never turns a broken ledger into an empty list. Reader = the panel HTTP
// route GET /sandbar-executor-panel/api/concurrency?project=<key> (the same
// face the console browser calls); the engine chain behind it is the REAL
// ticket.py op=concurrency against an isolated SANDBAR_PROJECTS_DIR — writer
// stdout is not evidence, every number is read back through the route.
//
// Sub-cases:
//  F1 ledger→face: fixture ledger (limit 2, holders: one running + one
//     human-hold, queue of 2 with 1-based positions and waited_s) — the route
//     returns exactly the ledger's numbers; the face numbers agree with an
//     independent read of the state file (observing command printed).
//  F2 malformed ledger: state file replaced by invalid JSON — the route
//     carries the engine's named refusal VERBATIM (quoting the absolute state
//     path); holders/queue absent, NEVER empty arrays.
//  F3 missing declaration: concurrency-limit.json removed — named
//     absent-declaration refusal quoting the absolute declaration path.
//  F4 project switch: a second project key with different numbers — the same
//     route switches limit + numbers with the key (one face, per-key state).
//
// intent split: declaration truth table + engine read-face shape = t261004-32
// (not re-asserted); save/audit = sc_concurrency_save_gate; Overview DOM =
// sc_concurrency_overview_ui; developer L1 owns pure-function truth tables.
//
// Three states: node missing = ENV_FAIL exit 2; panel harness/route not landed
// = FAIL naming the missing face (TDD-phase red expected); green at gate.
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { loadPanelHarness, makeIsoDir, makeCase } from '../t260929-03/lib_panel_harness.mjs'
import { REPO, engineRead, seedProject } from './lib_t26100617.mjs'

const C = makeCase()
if (!existsSync(process.execPath)) { C.envFail('node-runtime', 'node not on PATH'); process.exit(2) }

let mod
try { mod = await loadPanelHarness() } catch (e) { C.case('harness-load', false, String(e.message || e)); C.exit() }
if (!mod || typeof mod.startHarness !== 'function') {
  C.case('harness-present', false,
    'panel test seam absent: server/plugins/executor-panel/harness.mjs (TDD-phase red expected)')
  C.exit()
}

const iso = makeIsoDir('t26100617-face-')
const root = iso.dir
// The panel spawn chain must see the SAME isolated root the fixtures live in
// (engine's declared env contract, SANDBAR_PROJECTS_DIR).
process.env.SANDBAR_PROJECTS_DIR = root

const HUMAN_HOLD = {
  ticket: 't-seed-1', since: Date.now() / 1000 - 600, reason: 'running', held_s: 600,
}
const holders = [
  HUMAN_HOLD,
  { ticket: 't-seed-2', since: Date.now() / 1000 - 300, reason: 'human-hold', held_s: 300 },
]
const queue = [
  { ticket: 't-seed-3', position: 1, since: Date.now() / 1000 - 120, waited_s: 120 },
  { ticket: 't-seed-4', position: 2, since: Date.now() / 1000 - 60, waited_s: 60 },
]

let H
try {
  H = await mod.startHarness({ port: 0, panelDir: join(root, '_panel'), watchdogDir: join(root, '_panel') })
} catch (e) { C.case('harness-boot', false, String(e).slice(0, 300)); C.exit() }

async function getFace(key) {
  const r = await fetch(H.base + '/sandbar-executor-panel/api/concurrency?project=' + encodeURIComponent(key))
  let body = null
  try { body = await r.json() } catch { /* non-JSON body handled by caller */ }
  return { status: r.status, body }
}

// ---------- F1 ledger → face ----------
seedProject(root, 'alpha',
  { version: 1, limit: 2 },
  { version: 1, limit: 2, unlimited: false, holders, queue })
{
  const engine = engineRead(root, 'alpha')
  C.case('F1.engine-read-face-present', engine.rc === 0,
    'real ticket.py op=concurrency must serve the fixture root: rc=' + engine.rc + ' ' + (engine.stderr || engine.stdout).slice(0, 200))
  const { status, body } = await getFace('alpha')
  C.case('F1.route-200', status === 200, 'status=' + status)
  const ok = body && body.ok !== false
  C.case('F1.face-serves', !!ok, 'body=' + JSON.stringify(body).slice(0, 300))
  if (ok) {
    const holders = body.holders || body.at_work_list || []
    const queue = body.queue || body.waiting_list || []
    C.case('F1.limit-from-ledger', body.limit === 2, 'limit=' + JSON.stringify(body.limit))
    C.case('F1.holders-count-2', holders.length === 2, 'holders=' + holders.length)
    C.case('F1.queue-count-2', queue.length === 2, 'queue=' + queue.length)
    C.case('F1.human-hold-carried', holders.some(h => (h.reason || '') === 'human-hold'),
      'the human-hold holder must reach the face (amber-dot source)')
    C.case('F1.queue-positions-engine-owned',
      JSON.stringify(queue.map(q => q.position)) === JSON.stringify([1, 2]),
      'positions=' + JSON.stringify(queue.map(q => q.position)))
    C.case('F1.waited-seconds-present', queue.every(q => Number(q.waited_s ?? q.waitedSeconds) > 0),
      'waited_s must come through, not be recomputed to 0')
    const atWork = body.at_work ?? body.atWork
    const waiting = body.waiting
    C.case('F1.counts-at-work', atWork === undefined || atWork === 2, 'at_work=' + atWork)
    C.case('F1.counts-waiting', waiting === undefined || waiting === 2, 'waiting=' + waiting)
    console.log('  [observer] python3 -c "import json;print(json.load(open(\'' +
      join(root, 'alpha', 'concurrency-state.json') + '\'))"')
  }
}

// ---------- F2 malformed ledger ----------
{
  // restore the declaration so F4 compares two fully-seeded projects
  writeFileSync(join(root, 'alpha', 'concurrency-limit.json'), JSON.stringify({ version: 1, limit: 2 }))
  const p = join(root, 'alpha', 'concurrency-state.json')
  writeFileSync(p, '{ this is not json')
  const engine = engineRead(root, 'alpha') // engine face on the now-broken ledger
  const { status, body } = await getFace('alpha')
  const reason = String((body && body.reason) || '')
  C.case('F2.route-refuses', body && body.ok === false,
    'a malformed ledger is a named refusal, never an empty list: ' + JSON.stringify(body).slice(0, 300))
  C.case('F2.refusal-verbatim-path', reason.includes(join(root, 'alpha', 'concurrency-state.json')),
    'refusal must quote the absolute state path, got: ' + reason.slice(0, 300))
  C.case('F2.refusal-matches-engine-text', engine.rc !== 0 && reason.length > 0 &&
    engineRefusalEcho(engine, reason),
    'the face must carry the engine refusal, not reword it')
  C.case('F2.no-empty-lists', body && body.holders === undefined && body.queue === undefined,
    'holders/queue must be ABSENT on refusal (empty array would read as "nobody working")')
  C.case('F2.not-500', status >= 400 ? status < 500 || status === 200 : true,
    'a contract refusal is 2xx/4xx-shaped, never a crash 5xx: status=' + status)
}

function engineRefusalEcho(engine, reason) {
  // The engine prints the ValueError text to stderr; the route must quote it,
  // not reword it: a distinctive fragment of the engine's first stderr line
  // must appear in the face reason.
  // ticket.py prints the refusal as {"ok":false,"error":...} on stdout (rc!=0);
  // fall back to stderr text if a future engine switches channels.
  let line = ''
  try { line = String(JSON.parse(engine.stdout).error || '') } catch { line = engine.stderr || '' }
  line = line.split('\n').find(l => l.trim().length > 0) || ''
  // anchor on the engine's naming phrase (up to the first ':'), which is the
  // part a rewording would lose; the path face is already checked above.
  const frag = line.replace(/^ValueError:\s*/, '').split(':')[0].trim()
  return frag.length > 0 && reason.includes(frag)
}

// ---------- F3 missing declaration ----------
{
  const { unlinkSync } = await import('node:fs')
  try { unlinkSync(join(root, 'alpha', 'concurrency-limit.json')) } catch { /* already absent */ }
  try { writeFileSync(join(root, 'alpha', 'concurrency-state.json'),
    JSON.stringify({ version: 1, limit: 2, unlimited: false, holders, queue })) } catch { /* refixtured */ }
  const engine = engineRead(root, 'alpha')
  const { body } = await getFace('alpha')
  const reason = String((body && body.reason) || '')
  C.case('F3.route-refuses-absent-decl', body && body.ok === false,
    'absent declaration = named refusal: ' + JSON.stringify(body).slice(0, 200))
  C.case('F3.refusal-quotes-decl-path', reason.includes(join(root, 'alpha', 'concurrency-limit.json')),
    'refusal must quote the absolute declaration path: ' + reason.slice(0, 200))
  C.case('F3.engine-agrees-refusal', engine.rc !== 0, 'engine itself must refuse (fixture sanity)')
}

// ---------- F4 project switch ----------
{
  seedProject(root, 'beta', { version: 1, limit: 'unlimited' },
    { version: 1, limit: null, unlimited: true, holders: [], queue: [] })
  const a = await getFace('alpha')
  const b = await getFace('beta')
  C.case('F4.beta-serves', b.status === 200 && b.body && b.body.ok !== false,
    JSON.stringify(b.body).slice(0, 200))
  C.case('F4.unlimited-carried', b.body && (b.body.unlimited === true || b.body.limit === null),
    'unlimited must surface as unlimited/null, never as a number: ' + JSON.stringify(b.body && b.body.limit))
  C.case('F4.limit-switches-with-key', a.body && b.body && a.body.limit !== b.body.limit,
    'switching project switches the limit: alpha=' + a.body.limit + ' beta=' + b.body.limit)
  C.case('F4.holders-do-not-bleed', b.body && Array.isArray(b.body.holders) ? b.body.holders.length === 0 : true,
    'beta has no holders; alpha holders must not bleed across keys')
}

await H.close()
iso.clean()
C.exit()
