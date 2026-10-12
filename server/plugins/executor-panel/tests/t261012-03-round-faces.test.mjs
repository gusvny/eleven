/**
 * t261012-03-round-faces.test.mjs — the Rounds table's read face UT (the
 * adapter as the ONE reader of the runner's published faces, t261012-03).
 *
 * Layers:
 *  1. the REAL adapter's round-faces functions over a REAL fixture face tree
 *     (tmp dir, the SANDBAR_LINE_ROUND_FACE_DIR seam; no ~/.sandbar, no
 *     3099/7233): live/terminal/named-absence/unreadable states, counts_note
 *     passthrough, retention-transcendent listing, failures parsed from the
 *     retained log (garbled lines skipped, honest cap), the Wrote join (cert /
 *     freeze / could-not-run / multiple facts / malformed rows), and the
 *     trigger join from run headers.
 *  2. the `round` mode's spawn face over the REAL adapter subprocess: named
 *     refusals for a malformed run id (charset, `..`), an unknown run, and the
 *     four settled spawn paths on the reader side (stubbed execFile).
 *  3. the main receipt's round_faces section via the REAL adapter subprocess
 *     over a seeded project store (same builder as certification-reader.test).
 *  4. malformed-input discipline: an empty face file, a non-JSON face, a face
 *     dir without read permission, a suite.log missing — each a named state.
 */
import { execFile } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync, chmodSync } from 'node:fs'
import { join } from 'node:path'
import { execFileSync, spawnSync } from 'node:child_process'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import { spawnCertificationRead, spawnCertificationRound, parseRoundReceipt, certificationAdapterPath } from '../src/host/certification-reader.ts'

let n = 0
const dirs = []
const tmp = () => { const d = freshDir('rf-'); dirs.push(d); return d }

const adapter = certificationAdapterPath()
// the adapter imports the engine modules: run it under the SAME interpreter
// chain the reader uses (enginePython's venv fallback)
const PY = 'server/engine/.venv/bin/python'
function pyBin() { try { execFileSync(PY, ['-c', 'print(1)'], { cwd: repoRoot() }); return PY } catch { return 'python3' } }
function repoRoot() { return new URL('../../../..', import.meta.url).pathname }
/** Import the adapter module and call ONE function with ONE JSON argument;
 *  the answer comes back as one JSON line on stdout. */
function callAdapter(fn, arg, env = {}) {
  const script = `
import json, sys, os
os.environ.update(json.loads(sys.argv[2]))
import importlib.util
spec = importlib.util.spec_from_file_location('cert_adapter', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fn = getattr(m, ${JSON.stringify(fn)})
print(json.dumps(fn(**json.loads(sys.argv[1]))))
`
  const p = spawnSync(pyBin(), ['-c', script, JSON.stringify(arg), JSON.stringify(env)], { encoding: 'utf8', timeout: 60_000, cwd: repoRoot() })
  if (p.status !== 0) throw new Error('adapter harness failed: ' + p.stderr.slice(0, 400))
  return JSON.parse(p.stdout.trim().split('\n').pop())
}

function seedFaces(root, opts = {}) {
  // layout (the WRITER's own, lib_round_face): <root> is the FACE dir; the
  // rounds live at <root>/rounds — current.json, <run>/face.json, <run>/suite.log
  const faceDir = root
  const R = join(root, 'rounds')
  root = R
  mkdirSync(R, { recursive: true })
  const w = (p, obj) => writeFileSync(join(root, p), typeof obj === 'string' ? obj : JSON.stringify(obj) + '\n')
  const face = (run, over = {}) => ({
    run_id: run, line: 'develop-buffer', revision: { sandbar: '353b2479' },
    started_at: '2026-10-11T22:13:09Z', updated_at: '2026-10-11T22:25:00Z',
    state: 'done', pool: 'ro',
    counts: { ran: 10, pass: 8, fail: 2, env_fail: 0 },
    last_scenario: { name: 'sc-x', verdict: 'FAIL' },
    outcome: { verdict: 'red', reason: '2 failing scenarios' },
    ...over,
  })
  if (!opts.noLive) w('current.json', face('run-live', { state: 'running', outcome: null, counts: { ran: 4, pass: 4, fail: 0, env_fail: 0 }, counts_note: opts.liveNote }))
  mkdirSync(join(root, 'run-live'), { recursive: true })
  if (!opts.noRunA) {
    mkdirSync(join(root, 'run-a'), { recursive: true })
    w(join('run-a', 'face.json'), face('run-a', { started_at: '2026-10-11T16:49:00Z' }))
    w(join('run-a', 'suite.log'), [
      '点名 [t-x]（池=ro）',
      'PASS [t-ok] (0.1 s)',
      'FAIL [t-bad] exit=1 (1.0 s)',
      'ENV_FAIL [t-env] exit=2 (0.2 s)',
      'PASS [t-ok2] (0.3 s)',
      'garbled line that matches nothing',
      'INTEG_SUMMARY {"ran":4,"pass":2,"fail":1,"not_checked":1}',
    ].join('\n') + '\n')
  }
  if (opts.emptyDir) mkdirSync(join(root, 'run-empty'), { recursive: true })
  if (opts.tornFace) {
    mkdirSync(join(root, 'run-torn'), { recursive: true })
    w(join('run-torn', 'face.json'), '{"run_id": "run-torn", "sta')
  }
  if (opts.badDir) mkdirSync(join(root, 'run-bad'), { recursive: true })
  return faceDir
}

const runModeEnv = (root) => ({ ...process.env, SANDBAR_LINE_ROUND_FACE_DIR: root })

// ---- 1a. read_round_faces: the section's named states ----
{
  const root = seedFaces(tmp())
  const sec = callAdapter('read_round_faces', { project: 'proj-x' }, { SANDBAR_LINE_ROUND_FACE_DIR: root })
  assert(sec.dir === join(root, 'rounds'), 'the section names the ROUNDS dir (override carries the face dir, one level up)')
  assert(sec.live && sec.live.ok === true && sec.live.face.run_id === 'run-live' && sec.live.face.state === 'running', 'the live face reads from current.json')
  assert(sec.rounds.length === 2 && sec.rounds[0].run_id === 'run-a' && sec.rounds[0].face.outcome.verdict === 'red', 'the terminal face reads verbatim')
  assert(sec.rounds[1].run_id === 'run-live' && sec.rounds[1].absent === 'terminal face not written', "the live run's own dir without a terminal face names its absence")
  n += 3

  // absence = idle: no current.json means NO live slot, terminal rows still render
  const idle = callAdapter('read_round_faces', { project: 'p' }, { SANDBAR_LINE_ROUND_FACE_DIR: join(tmp(), 'missing-face-dir') })
  assert(idle.error && idle.error.includes('rounds path unreadable'), 'a missing rounds dir names the section error')
  const root2 = seedFaces(tmp(), { noLive: true })
  const sec2 = callAdapter('read_round_faces', { project: 'proj-x' }, { SANDBAR_LINE_ROUND_FACE_DIR: root2 })
  assert(sec2.live === undefined && sec2.rounds.some((e) => e.run_id === 'run-a' && e.face), 'no current.json = no live slot (absence is idle), terminal rows remain')
  n += 2

  // per-file named states: run dir without a face, torn face, unreadable dir
  const root3 = seedFaces(tmp(), { emptyDir: true, tornFace: true, badDir: true })
  chmodSync(join(root3, 'rounds', 'run-bad'), 0o000)
  try {
    const sec3 = callAdapter('read_round_faces', { project: 'proj-x' }, { SANDBAR_LINE_ROUND_FACE_DIR: root3 })
    const byId = Object.fromEntries(sec3.rounds.map((e) => [e.run_id, e]))
    assert(byId['run-empty'] && byId['run-empty'].absent === 'terminal face not written', 'a run dir without its face names the absence')
    assert(byId['run-torn'] && /not valid JSON/.test(byId['run-torn'].reason), 'a torn face names itself, never counts')
    assert(byId['run-bad'] && /face unreadable/.test(byId['run-bad'].reason), 'an unreadable face file names the OSError')
    n += 3
  } finally {
    chmodSync(join(root3, 'rounds', 'run-bad'), 0o755)
  }

  // no silent retention assumption: 12 run dirs all reach the receipt (cap is
  // declared, not the writer's keep window)
  const root4 = tmp()
  // a SIBLING dir beside rounds/ must never render as a phantom run row
  // (the acceptance_walkthrough gen1 probe: writer-layout tree + env set)
  mkdirSync(join(root4, 'projects'), { recursive: true })
  for (let i = 0; i < 12; i++) {
    mkdirSync(join(root4, 'rounds', 'run-' + String(i).padStart(2, '0')), { recursive: true })
    writeFileSync(join(root4, 'rounds', 'run-' + String(i).padStart(2, '0'), 'face.json'), JSON.stringify({ run_id: 'run-' + String(i).padStart(2, '0'), state: 'done', started_at: '2026-10-11T' + String(10 + i) + ':00:00Z', counts: { ran: 1, pass: 1, fail: 0, env_fail: 0 }, outcome: { verdict: 'green', reason: '' } }))
  }
  const sec4 = callAdapter('read_round_faces', { project: 'proj-x' }, { SANDBAR_LINE_ROUND_FACE_DIR: root4 })
  assert(sec4.rounds.length === 12 && !sec4.rounds.some((e) => e.run_id === 'projects'), 'every run dir reaches the receipt, and the face dir\'s SIBLING dirs never render as phantom run rows (writer-layout regression)')
  assert(sec4.rounds[0].run_id === 'run-11' && sec4.rounds[11].run_id === 'run-00', 'rows sort newest-first by the face started_at')
  n += 2
}

// ---- 1b. parse_failures: pinned vocabulary, garbled skipped, honest cap ----
{
  const log = Array.from({ length: 25 }, (_, i) => `FAIL [t-fail-${i}] exit=1 (1.${i} s)`).join('\n')
    + '\nPASS [t-pass-1] (0.1 s)\nENV_FAIL [t-env] exit=2 (0.2 s)\ngarbage line\n'
  const f = callAdapter('parse_failures', { log_text: log })
  assert(f.judged === 27, 'the judged count names every recognizable line (garbage skipped)')
  assert(f.rows.length === 20 && f.more === 6, `the cap is honest: 20 rows + 6 more (got ${f.rows.length}/${f.more})`)
  assert(f.rows.every((r) => r.verdict === 'fail' || r.verdict === 'env_fail'), 'only non-PASS verdicts are failure rows')
  assert(f.rows[0].verdict === 'fail' && f.rows[0].duration === '1.0 s', 'failure rows carry name, verdict and duration')
  assert(f.last && f.last.verdict === 'ENV_FAIL' && f.last.name === 't-env', 'the last judged line is named with its own verdict token')
  const empty = callAdapter('parse_failures', { log_text: 'nothing recognizable here' })
  assert(empty.judged === 0 && empty.rows.length === 0, 'a log with no recognizable lines parses to nothing — never invented rows')
  n += 6
}

// ---- 1c. wrote_clauses: the ONE Wrote line's facts from the delivery ledger ----
{
  const home = tmp()
  const P = 'wroteproj'
  const ledger = join(home, P, 'ledger')
  mkdirSync(ledger, { recursive: true })
  const rows = [
    { kind: 'landing', id: 'ldg-1', ticket: 't-1', line: 'l', run: 'not-a-run-field-mismatch', at: 1, seq: 1 },
    { kind: 'certification', id: 'cert-1', line: 'l', run: 'run-w', at: 2, seq: 2 },
    { kind: 'certification', id: 'cert-2', line: 'l', run: 'run-w', at: 3, seq: 3 },
    { kind: 'freeze', id: 'frz-1', line: 'l', cause: 'cert-1', at: 4, seq: 4 },
    { kind: 'range_growth', id: 'rg-1', line: 'l', run: 'run-w', at: 5, seq: 5 },
  ]
  writeFileSync(join(ledger, 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  const env = { ...process.env, SANDBAR_PROJECTS_DIR: home }
  const script = `
import json, sys, os
sys.argv = ['certification-adapter.py']
import importlib.util
spec = importlib.util.spec_from_file_location('cert_adapter', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
old = m.wrote_clauses
m.wrote_clauses = None  # guard: call through the module with env in place
os.environ.update(${JSON.stringify({ SANDBAR_PROJECTS_DIR: home })})
import importlib
print(json.dumps(old(${JSON.stringify(P)}, 'run-w')))
`
  const p = spawnSync(pyBin(), ['-c', script], { encoding: 'utf8', timeout: 60_000, cwd: repoRoot() })
  if (p.status !== 0) throw new Error('wrote harness failed: ' + p.stderr.slice(0, 400))
  const [clauses, note] = JSON.parse(p.stdout.trim().split('\n').pop())
  assert(clauses.length === 4, `every citing fact renders (${clauses.length} clauses)`)
  assert(clauses.some((c) => c.includes('cert-1')) && clauses.some((c) => c.includes('cert-2')), 'both certification rows render — ONE line, N clauses, none dropped')
  assert(clauses.some((c) => c.startsWith('freeze frz-1 opened')), 'the freeze the cert opened renders as its own clause')
  assert(clauses.some((c) => c.startsWith('range_growth rg-1')), 'a foreign-kind citing row renders, never silently dropped')
  assert(note === '', 'no unrecognized-kind note when all kinds are known to the join')
  n += 5
}

// ---- 2. the `round` mode over the REAL adapter subprocess ----
{
  const root = seedFaces(tmp())
  const good = await spawnCertificationRound('proj-x', 'run-a', { env: runModeEnv(root) })
  assert(good.ok === true && good.run === 'run-a', 'the round mode answers for a retained run')
  assert(good.face && good.face.outcome.verdict === 'red', 'the terminal face travels verbatim')
  assert(good.failures && good.failures.rows.length === 2 && good.failures.judged === 4, `failures parsed from the retained log (${JSON.stringify(good.failures && good.failures.rows.length)})`)
  assert(good.failures.rows.some((r) => r.verdict === 'env_fail'), 'an env_fail row stays env_fail (never folded into fail)')
  assert(good.wrote.length === 1 && good.wrote[0].includes('no ledger record cites this run') === false || good.wrote.length === 0, 'the wrote facts ride (possibly empty for an uncited run)')
  assert(good.log_path.endsWith(join('run-a', 'suite.log')), 'the retained log path is named')
  assert(good.trigger === null || typeof good.trigger === 'string', 'the trigger is the header word or a named null')
  n += 6

  // refusals
  const traversal = await spawnCertificationRound('proj-x', '../escape', { env: runModeEnv(root) })
  assert(traversal.ok === false && traversal.reason.includes('malformed run id'), 'a traversal run id refuses at the reader boundary')
  const bad = await spawnCertificationRound('proj-x', 'not ok!', { env: runModeEnv(root) })
  assert(bad.ok === false && bad.reason.includes('malformed run id'), 'a charset-violating run id refuses at the reader boundary')
  const unknown = await spawnCertificationRound('proj-x', 'run-nope', { env: runModeEnv(root) })
  assert(unknown.ok === true && unknown.face === null && /no terminal face/.test(unknown.face_reason), 'an unknown run id names the absence — never a guessed face')
  n += 3

  // the four settled spawn paths (stubbed execFile), round mode
  const stub = (behavior) => (cmd, args, opts, cb) => {
    if (behavior === 'receipt-on-error') { const e = new Error('exit 1'); cb(e, JSON.stringify({ ok: false, reason: 'round says no' })); return }
    if (behavior === 'empty-on-error') { const e = new Error('exit 1'); cb(e, ''); return }
    if (behavior === 'spawn-throw') { throw new Error('no such interpreter') }
    if (behavior === 'timeout') { const e = new Error('killed'); e.killed = true; cb(e, ''); return }
    cb(null, JSON.stringify({ ok: true, project: 'p', run: 'r', wrote: [], face: null, face_reason: null, failures: null, failures_absent: null, log_path: '', log_absent: null }))
  }
  const okR = await spawnCertificationRound('p', 'r', { execFileFn: stub('ok') })
  assert(okR.ok === true && okR.wrote.length === 0, 'the ok path settles')
  const carried = await spawnCertificationRound('p', 'r', { execFileFn: stub('receipt-on-error') })
  assert(carried.ok === false && carried.reason.includes('round says no'), 'a non-zero exit still carries a parseable receipt')
  const failed = await spawnCertificationRound('p', 'r', { execFileFn: stub('empty-on-error') })
  assert(failed.ok === false && failed.reason.includes('round read failed'), 'an empty stdout names the failure')
  const killed = await spawnCertificationRound('p', 'r', { execFileFn: stub('timeout') })
  assert(killed.ok === false && killed.reason.includes('timed out and was killed'), 'a timeout kill names itself')
  const thrown = await spawnCertificationRound('p', 'r', { execFileFn: stub('spawn-throw') })
  assert(thrown.ok === false && thrown.reason.includes('could not spawn'), 'a spawn error settles the promise')
  n += 5

  // strict receipt parse
  assert(parseRoundReceipt('not json {').ok === false, 'a malformed round receipt refuses by name')
  assert(parseRoundReceipt('{"ok":true,"project":"p"}').ok === false, 'a receipt missing its facts shape refuses')
  n += 2

  // missing retained log = named absence (never an empty failures table implying zero)
  const noLog = await spawnCertificationRound('proj-x', 'run-live', { env: runModeEnv(root) })
  assert(noLog.ok === true && noLog.face && noLog.face.state === 'running', 'the live run answers from the run dir (its terminal face was written by the fixture seed)')
  const rootNoLog = seedFaces(tmp(), { noLive: false })
  rmSync(join(rootNoLog, 'rounds', 'run-a', 'suite.log'))
  const absent = await spawnCertificationRound('proj-x', 'run-a', { env: runModeEnv(rootNoLog) })
  assert(absent.ok === true && absent.failures === null && absent.failures_absent === 'retained log not written', 'a missing retained log names its absence')
  n += 2
}

// ---- 3. the main receipt carries the round_faces section (real subprocess, seeded store) ----
{
  const home = tmp()
  const P = 'rfproj'
  const dev = join(home, P, 'data', 'develop')
  const ledger = join(home, P, 'ledger')
  mkdirSync(dev, { recursive: true }); mkdirSync(ledger, { recursive: true })
  writeFileSync(join(dev, 'lines.json'), JSON.stringify([
    { line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host', repositories: [{ name: 'sandbar', branch: 'develop-buffer' }] },
  ]))
  writeFileSync(join(ledger, 'delivery.jsonl'), '')
  const runsPath = join(home, 'runs.jsonl')
  writeFileSync(runsPath, '')
  const root = seedFaces(tmp())
  const env = { ...process.env, SANDBAR_PROJECTS_DIR: home, SANDBAR_RUNS_LEDGER: runsPath, SANDBAR_LINE_ROUND_FACE_DIR: root }
  const read = await spawnCertificationRead(P, { env })
  assert(read.ok === true, 'the seeded store reads')
  assert(read.round_faces && read.round_faces.live && read.round_faces.live.ok === true, 'the main receipt carries the live face')
  assert(read.round_faces.rounds.some((e) => e.run_id === 'run-a' && e.face && e.face.outcome.verdict === 'red'), 'the main receipt carries the terminal faces')
  n += 3

  // fault 2 (acceptance_walkthrough gen1): a refusal receipt STILL carries the
  // round-faces section — the Rounds table is not hostage to lines.json
  const homeNoDecl = tmp()
  mkdirSync(join(homeNoDecl, 'rfnodecl', 'data', 'develop'), { recursive: true })
  const readNoDecl = await spawnCertificationRead('rfnodecl', { env: { ...process.env, SANDBAR_PROJECTS_DIR: homeNoDecl, SANDBAR_LINE_ROUND_FACE_DIR: root } })
  assert(readNoDecl.ok === false, 'a store without a declaration refuses by name')
  assert(readNoDecl.round_faces && readNoDecl.round_faces.live && readNoDecl.round_faces.live.ok === true, 'the refusal receipt still carries the live face (the table survives the declaration)')

  // a section-level error degrades the SECTION inside an otherwise-ok receipt
  const envBad = { ...env, SANDBAR_LINE_ROUND_FACE_DIR: join(root, 'nope') }
  const readBad = await spawnCertificationRead(P, { env: envBad })
  assert(readBad.ok === true && readBad.round_faces && /rounds path unreadable/.test(readBad.round_faces.error), 'an unreadable face dir degrades the section by name, the receipt stays ok')
  n += 1
}

assert(n >= 40, `coverage count sanity (${n})`)
done(n)
