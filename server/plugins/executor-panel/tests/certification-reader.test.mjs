/**
 * certification-reader.test.mjs — t261009-44 Slice 2, the read seam's UT.
 *
 * Layers covered:
 *  1. receipt parsing (stubbed stdout): valid / malformed JSON / wrong shape /
 *     named refusal — every malformed receipt is an explicit reason, never a
 *     guessed face (KI discipline: same stance as the grants receipt parse).
 *  2. the spawn face (stubbed execFile): non-zero exit with a parseable receipt
 *     (receipt wins), non-zero exit with empty stdout, timeout kill, spawn
 *     error — all four paths settle, no dangling handles.
 *  3. the REAL adapter over the REAL engine projections in a throwaway project
 *     store (SANDBAR_PROJECTS_DIR tmp; no ~/.sandbar, no 3099/7233): the happy
 *     scenario, the fail-closed run-header rule, the cited-run-missing rule,
 *     and the malformed-ledger degradations at the engine readers' own
 *     strictness (review C2b: a row the engine reader rejects produces a named
 *     reason, never a silently dropped row).
 *  4. line choice: single line auto-picked; several lines refuse without
 *     ?line=; an unknown line refuses by name.
 */
import { execFile } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { assert, done, freshDir, cleanup } from './lib.mjs'
import {
  parseCertReceipt, spawnCertificationRead, certificationFace, certificationAdapterPath, pickLine,
} from '../src/host/certification-reader.ts'

let n = 0
const dirs = []
const tmp = () => { const d = freshDir('cert-'); dirs.push(d); return d }

// ---- 1. receipt parsing ----
{
  const ok = parseCertReceipt(JSON.stringify({ ok: true, project: 'p', lines: [{ line_id: 'l1' }], per_line: { l1: { ok: true, input: {} } }, meta_notes: [], runs_note: '' }))
  assert(ok.ok === true && ok.project === 'p' && ok.lines.length === 1, 'valid receipt parses')
  assert(parseCertReceipt('not json {').ok === false, 'malformed JSON receipt refuses by name')
  assert(parseCertReceipt('').ok === false, 'empty receipt refuses')
  assert(parseCertReceipt('{"ok":1}').ok === false, 'wrong ok shape refuses')
  const refused = parseCertReceipt(JSON.stringify({ ok: false, reason: 'line declaration missing: x' }))
  assert(refused.ok === false && refused.reason.includes('line declaration missing'), 'named refusal travels verbatim')
  assert(parseCertReceipt(JSON.stringify({ ok: true, project: 'p' })).ok === false, 'receipt missing per_line refuses')
  assert(parseCertReceipt(JSON.stringify({ ok: true, project: 'p', lines: [], per_line: { l: {} } })).ok === false, 'line slice without ok shape refuses')
  n += 7
}

// ---- 2. spawn face fault modes (stubbed execFile) ----
{
  const receipt = JSON.stringify({ ok: false, reason: 'engine says no' })
  const stub = (behavior) => (cmd, args, opts, cb) => {
    if (behavior === 'receipt-on-error') { const e = new Error('exit 1'); cb(e, receipt); return }
    if (behavior === 'empty-on-error') { const e = new Error('exit 1'); cb(e, ''); return }
    if (behavior === 'spawn-throw') { throw new Error('no such interpreter') }
    if (behavior === 'timeout') { const e = new Error('killed'); e.killed = true; cb(e, ''); return }
    cb(null, receipt)
  }
  const good = await spawnCertificationRead('p', { execFileFn: stub('ok') })
  assert(good.ok === false && good.reason === 'engine says no', 'ok receipt path settles')
  const carried = await spawnCertificationRead('p', { execFileFn: stub('receipt-on-error') })
  assert(carried.ok === false && carried.reason === 'engine says no', 'non-zero exit still carries a parseable receipt')
  const failed = await spawnCertificationRead('p', { execFileFn: stub('empty-on-error') })
  assert(failed.ok === false && failed.reason.includes('certification read failed'), 'non-zero exit with empty stdout names the failure')
  const killed = await spawnCertificationRead('p', { execFileFn: stub('timeout') })
  assert(killed.ok === false && killed.reason.includes('timed out and was killed'), 'timeout kill names itself')
  const thrown = await spawnCertificationRead('p', { execFileFn: stub('spawn-throw') })
  assert(thrown.ok === false && thrown.reason.includes('could not spawn'), 'spawn error settles the promise')
  n += 5
}

// ---- 3. the real adapter over the real engine projections ----
const P = 'certproj'

function seedProject(home, opts = {}) {
  const dev = join(home, P, 'data', 'develop')
  const ledger = join(home, P, 'ledger')
  const tick = join(home, P, 'data', 'tickets', 't261009-18')
  mkdirSync(dev, { recursive: true }); mkdirSync(ledger, { recursive: true }); mkdirSync(tick, { recursive: true })
  writeFileSync(join(dev, 'lines.json'), JSON.stringify([
    { line_id: 'develop-buffer', scope: 'epic develop-buffer', owner: 'host', repositories: [{ name: 'sandbar', branch: 'develop-buffer' }] },
  ]))
  // Rows in the engine's own shapes (same builders as the t261009-41 fixture).
  const rows = [
    { kind: 'landing', id: 'ldg-1', ticket: 't261009-18', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '396b221a' }], actor: 'dev', at: 1000, seq: 1 },
    { kind: 'certification', id: 'cert-A', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: '396b221a' }], run: 'run-green', booked_red: 'known-red@test', judged_by: 'pytest', at: 2000, seq: 2 },
  ]
  writeFileSync(join(ledger, 'delivery.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n') + '\n')
  writeFileSync(join(ledger, 'promotion.jsonl'), JSON.stringify({ kind: 'promotion', id: 'prom-A', certification: 'cert-A', line: 'develop-buffer', repos: [{ repo: 'sandbar', revision: 'aaa11111' }], tickets: ['t261009-18'], main_before: [{ repo: 'sandbar', revision: 'aaa11111' }], main_after: [{ repo: 'sandbar', revision: 'bbb22222' }], signer: 'host', at: 3000, seq: 1 }) + '\n')
  const runHeader = { v: 'run-ledger-v1', id: 'run-green', repos: [{ repo: 'sandbar', revision: '396b221a' }], suite: 'full', source: 'scheduled', env_fp: 'x', conc_width: 1, pool: '', started_at: 900, duration_s: 1.0, cases: { ran: 10, passed: 10, failed: 0, env_failed: 0 }, verdict: 'green' }
  const runsPath = join(home, 'runs.jsonl')
  writeFileSync(runsPath, (opts.runsLines ?? [JSON.stringify(runHeader)]).join('\n') + '\n')
  writeFileSync(join(tick, 'archive.json'), JSON.stringify({ schema: 1, ticket_id: 't261009-18', meta: { title: 'Land a proven lane', epic: 'develop-buffer' } }))
  return runsPath
}

function adapterEnv(home, runsPath) {
  return { ...process.env, SANDBAR_PROJECTS_DIR: home, SANDBAR_RUNS_LEDGER: runsPath }
}

{
  const home = tmp()
  const runsPath = seedProject(home)
  const read = await spawnCertificationRead(P, { env: adapterEnv(home, runsPath) })
  assert(read.ok === true && read.project === P, 'adapter reads the seeded store')
  const one = read.per_line['develop-buffer']
  assert(one && one.ok === true, 'line derives')
  const inp = one.input
  assert(Array.isArray(inp.waitStates) && inp.waitStates.length === 1
    && inp.waitStates[0].state === 'certified' && inp.waitStates[0].covered_by === 'cert-A',
  'ticket_wait_state comes from the engine (covered_by cert-A)')
  assert(inp.outcomes.length === 1 && inp.outcomes[0].delivered_in === 'prom-A'
    && inp.outcomes[0].ending === 'ended', 'ticket_outcome comes from the engine (delivered in prom-A)')
  assert(inp.freeze && inp.freeze.frozen === false, 'freeze_state comes from the engine (not frozen)')
  assert(inp.certs.length === 1 && inp.certs[0].id === 'cert-A', 'cert rows ride along for links')
  assert(inp.runs.length === 1 && inp.runs[0].verdict === 'green' && inp.runs[0].source === 'scheduled',
  'run headers ride along with the engine verdict')
  assert(inp.ticketMeta['t261009-18'].title === 'Land a proven lane', 'ticket title comes from the ticket store')
  n += 7

  const face = await certificationFace({ project: P }, { env: adapterEnv(home, runsPath) })
  assert(face.ok === true && face.line === 'develop-buffer', 'single line is auto-picked')
  assert(face.face.deliveredTotal === 1 && face.face.promotable === 0
    && face.face.state === 'GREEN', 'derived face: delivered 1, promotable 0, GREEN')
  assert(face.face.rounds.length === 1 && face.face.rounds[0].trigger === 'auto'
    && face.face.rounds[0].verdict === 'green' && /^line sandbar:[0-9a-f]{8}$/.test(face.face.rounds[0].measured),
  'rounds face: auto trigger, green verdict, line <repo>:<sha8> shape (F6)')
  n += 2

  // fail-closed run-header rule: certs on the line + no READABLE runs ledger =
  // named refusal. 261013: the panel now POINTS the adapter at the project's
  // runs store (it used to spawn without SANDBAR_RUNS_LEDGER, so every read
  // degraded and the Rounds table rendered empty) — so the reachable
  // fail-closed case is "the store the panel points at is absent/unreadable",
  // still a named refusal, never a default green.
  const noRuns = await spawnCertificationRead(P, { env: { ...process.env, SANDBAR_PROJECTS_DIR: home } })
  assert(noRuns.ok === true && noRuns.per_line['develop-buffer'].ok === false
    && /run headers|SANDBAR_RUNS_LEDGER/.test(noRuns.per_line['develop-buffer'].reason),
  'absent run headers fail the line CLOSED (never a default green)')
  n += 1

  // cited run missing from the headers: 261013 the display DEGRADES per-round
  // (renders the readable rounds, names the lost records) instead of refusing
  // the whole line — the green JUDGMENT stays fail-closed (an absent run reads
  // not-green, never promoted). Never an invented verdict.
  const other = await certificationFace({ project: P }, { env: adapterEnv(home, seedRunsOther(home)) })
  assert(other.ok === true && other.face && (other.notes || []).some((x) => /run records absent for cited round/.test(x)),
    'a lost run record degrades the display named, never invented; green judgment stays closed')
  n += 1

  // malformed delivery row: the engine reader counts it, the seam refuses by name
  const home2 = tmp()
  const runs2 = seedProject(home2)
  const { appendFileSync } = await import('node:fs')
  appendFileSync(join(home2, P, 'ledger', 'delivery.jsonl'), 'garbage {\n')
  const bad = await spawnCertificationRead(P, { env: adapterEnv(home2, runs2) })
  assert(bad.ok === false && bad.reason.includes('delivery ledger has 1 malformed line'), 'malformed delivery row degrades by name (engine reader strictness)')
  n += 1

  // malformed run-header row: same strictness on the runs ledger
  const home3 = tmp()
  const runs3 = seedProject(home3, { runsLines: [JSON.stringify({ v: 'run-ledger-v1', id: 'run-green' }), '[1,2]'] })
  const badRuns = await spawnCertificationRead(P, { env: adapterEnv(home3, runs3) })
  assert(badRuns.ok === false && badRuns.reason.includes('run headers ledger has 1 malformed line'), 'malformed run-header row degrades by name')
  n += 1

  // missing line declaration
  const home4 = tmp()
  seedProject(home4)
  rmSync(join(home4, P, 'data', 'develop', 'lines.json'))
  const noDecl = await spawnCertificationRead(P, { env: adapterEnv(home4, join(home4, 'runs.jsonl')) })
  assert(noDecl.ok === false && noDecl.reason.includes('LineDeclarationError'), 'missing line declaration degrades by name')
  n += 1
}

function seedRunsOther(home) {
  const p = join(home, 'runs-other.jsonl')
  writeFileSync(p, JSON.stringify({ v: 'run-ledger-v1', id: 'run-OTHER', repos: [], suite: 'full', source: 'scheduled', env_fp: 'x', conc_width: 1, pool: '', started_at: 900, duration_s: 1.0, cases: { ran: 10, passed: 10, failed: 0, env_failed: 0 }, verdict: 'green' }) + '\n')
  return p
}

// ---- 4. line choice ----
{
  const multi = { ok: true, project: 'p', lines: [{ line_id: 'a' }, { line_id: 'b' }], per_line: {}, meta_notes: [], runs_note: '' }
  assert(pickLine(multi).ok === false && pickLine(multi).reason.includes('pass ?line='), 'several lines without a choice refuse by name')
  assert(pickLine(multi, 'b').ok === true && pickLine(multi, 'b').line === 'b', 'a chosen line is honoured')
  assert(pickLine(multi, 'zzz').ok === false && pickLine(multi, 'zzz').reason.includes("line 'zzz' is not declared"), 'unknown line refuses by name')
  const single = { ...multi, lines: [{ line_id: 'only' }] }
  assert(pickLine(single).line === 'only', 'single line auto-picks')
  n += 4
}

assert(typeof certificationAdapterPath() === 'string' && certificationAdapterPath().endsWith('certification-adapter.py'), 'adapter path resolves to its sibling file')
n += 1

// ---- 5. t261027-16: the size death refuses BY NAME; the window travels ----
{
  // the spawn buffer death: execFile answers "stdout maxBuffer length exceeded"
  // with EMPTY stdout — the refusal must name the size, never "not valid JSON"
  const stub = (code, msg) => (cmd, args, opts, cb) => {
    const e = new Error(msg)
    if (code) e.code = code
    cb(e, '')
  }
  const byCode = await spawnCertificationRead('p', { execFileFn: stub('ENOBUFS', 'spawn ENOBUFS') })
  assert(byCode.ok === false && byCode.reason.includes('receipt too large')
    && byCode.reason.includes('spawn buffer'), 'ENOBUFS refuses by name (receipt too large)')
  assert(!byCode.reason.includes('not valid JSON'), 'the size death never reads back as malformed JSON')
  const byMsg = await spawnCertificationRead('p', { execFileFn: stub(null, 'stdout maxBuffer length exceeded') })
  assert(byMsg.ok === false && byMsg.reason.includes('receipt too large'), 'maxBuffer message refuses by name')
  // a maxBuffer-shaped error WITH a parseable receipt still parses (receipt wins)
  const withReceipt = await spawnCertificationRead('p', {
    execFileFn: (cmd, args, opts, cb) => {
      const e = new Error('stdout maxBuffer length exceeded'); e.code = 'ENOBUFS'
      cb(e, JSON.stringify({ ok: false, reason: 'receipt too large: 1406555 bytes, window shown=20 total=3600 older=3580 cap=20', runs_window: { shown: 20, total: 3600, older: 3580, cap: 20 } }))
    },
  })
  assert(withReceipt.ok === false && withReceipt.reason.startsWith('receipt too large:')
    && withReceipt.runs_window && withReceipt.runs_window.total === 3600, 'adapter oversize refusal + window travel verbatim')
  n += 4

  // the window rides the success receipt; absent on older receipts; a
  // malformed window degrades to absent (soft validation, never guessed)
  const mk = (extra) => parseCertReceipt(JSON.stringify({
    ok: true, project: 'p', lines: [{ line_id: 'l1' }],
    per_line: { l1: { ok: true, input: {} } }, meta_notes: [], runs_note: '', ...extra,
  }))
  const win = mk({ runs_window: { shown: 20, total: 3600, older: 3580, cap: 20 } })
  assert(win.ok === true && win.runs_window && win.runs_window.older === 3580, 'success receipt carries runs_window')
  const noWin = mk({})
  assert(noWin.ok === true && noWin.runs_window === undefined, 'window absent on older receipts (never guessed)')
  const badWin = mk({ runs_window: { shown: 'many', total: 3600 } })
  assert(badWin.ok === true && badWin.runs_window === undefined, 'malformed window degrades to absent')
  n += 3

  // the real adapter on a small ledger: no window, nothing hidden
  const home = tmp()
  const runsPath = seedProject(home)
  const face = await certificationFace({ project: P }, { env: adapterEnv(home, runsPath) })
  assert(face.ok === true && face.runs_window && face.runs_window.older === 0, 'small ledger: window states nothing hidden (older 0)')
  n += 1
}

cleanup(dirs)
done(n)
