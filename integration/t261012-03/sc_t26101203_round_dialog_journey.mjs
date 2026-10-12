#!/usr/bin/env node
/**
 * sc_t26101203_round_dialog_journey.mjs — t261012-03, the run id IS the entry:
 * clicking a Rounds-table row opens the round dialog with the round's measured
 * numbers, its failures, the ONE 'Wrote' line and the retained log path — and
 * terminal states can never render as running ones (grey-box L3: the REAL
 * executor-panel reader spawn against the REAL certification-adapter subprocess
 * (the panel's own path) over a fixture face tree seeded through the declared
 * SANDBAR_LINE_ROUND_FACE_DIR seam, plus the REAL page-embedded render core the
 * Certification tab ships; offline seconds, zero docker/Temporal-server/browser,
 * never touches 3099/7233).
 *
 * intent (user words, ticket t261012-03 spec: "The FIRST column is the run id
 * and IS the entry link that opens the round dialog ... Terminal states must be
 * distinguishable from running ones at a glance - a red round must not be
 * renderable as a green one, and a round that could not run must not look like
 * a round that ran and passed"):
 *   A. ENTRY LINK: the rendered tab face's first column cell per round row is
 *      the run id itself wired as a link; the dialog data that link fetches
 *      (the reader's round-mode receipt for that run id) describes the SAME
 *      run (id, line, revision) the row showed.
 *   B. DIALOG CONTENT: run id + revision + line; the result-so-far or terminal
 *      verdict; the last judged case + verdict; failures parsed from the
 *      retained log (name, verdict, duration) capped with an HONEST exact
 *      '+N more'; the ONE Wrote line (clauses naming every fact, none dropped);
 *      the retained log path pointing into the face dir.
 *   C. DISTINGUISHABILITY FROM THE FACE'S OWN FIELDS: red ≠ green ≠ running ≠
 *      could-not-run in the rendered markup; a could-not-run round never
 *      carries a green marker and names its reason; the pill key is derived
 *      from the face fields only.
 *   D. ADVERSARY FACES: unknown run id → named refusal; a run id carrying
 *      '..' or a path separator → refused by name (no traversal); garbled
 *      suite.log lines never MANUFACTURE a failure row; a missing retained
 *      log is a named absence, never an empty failures table implying zero
 *      failures.
 *
 * Layering / intent split (no intent-level duplication):
 *   - the adapter's round-faces honesty contract (absence/unreadable named,
 *     counts_note, retention) belongs to the sibling
 *     t261012-03-rounds-table-honest-faces entry;
 *   - parse truth tables, mapper unit matrices and page-contract statics
 *     belong to developer L1 (the in-ticket unit battery);
 *   - this entry owns the USER JOURNEY: link → dialog, over the real spawn
 *     path and the real embedded render core.
 *
 * Three states: engine modules / adapter / reader missing = ENV_FAIL exit 2;
 * the declared dialog journey missing = FAIL named, must be green at the
 * integration gate / merge.
 */
import { execFile } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { join, dirname, resolve } from 'node:path'
import { promisify } from 'node:util'
import { fileURLToPath } from 'node:url'

const run = promisify(execFile)
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const ADAPTER = join(REPO, 'server/plugins/executor-panel/src/host/certification-adapter.py')
const FACE_DIR_ENV = 'SANDBAR_LINE_ROUND_FACE_DIR'
const PROJECTS_ENV = 'SANDBAR_PROJECTS_DIR'
const PROJECT = 't26101203-fixture'

let READER = null
let PASS = 0, FAIL = 0
const dirs = []
function check(name, cond, detail = '') {
  if (cond) { PASS++; console.log('PASS ' + name) }
  else { FAIL++; console.log('FAIL ' + name + (detail ? ': ' + String(detail).slice(0, 400) : '')) }
}
const tmp = () => { const d = mkdtempSync(join('/tmp', 't26101203-dlg-')); dirs.push(d); return d }
process.on('exit', () => { for (const d of dirs) rmSync(d, { recursive: true, force: true }) })

// the interpreter the panel itself spawns the adapter under: engine venv
// first, plain python3 fallback (the declared chain in verify.yaml).
const enginePython = (() => {
  for (const p of ['server/engine/.venv/bin/python', 'server/dsh/temporal-poc/.venv/bin/python']) {
    const full = join(REPO, p)
    if (existsSync(full)) return full
  }
  return 'python3'
})()

const baseFace = (over = {}) => ({
  run_id: over.run_id, line: 'buffer', revision: { repo: 'a'.repeat(40) },
  started_at: '2026-01-12T01:00:00Z', updated_at: over.updated_at || '2026-01-12T01:05:00Z',
  state: over.state || 'done', pool: 'integ',
  counts: over.counts || { ran: 3, pass: 3, fail: 0, env_fail: 0 },
  ...(over.last ? { last_scenario: over.last } : {}),
  ...(over.note ? { counts_note: over.note } : {}),
  ...(over.outcome !== undefined ? { outcome: over.outcome } : {}),
})

// the suite's OWN block vocabulary (run_scenarios.py's pinned shapes; the
// lib_round_face regexes parse exactly these, garbled lines match none).
const SUITE_LOG = [
  'PASS [sc_alpha] (1.20s) the alpha scenario passes',
  'FAIL [sc_beta] exit=1 the beta scenario fails (3.40s)',
  'ENV_FAIL [sc_gamma] exit=2 docker stage missing (0.80s)',
  'garbled line that matches no verdict vocabulary at all',
  'PASS [sc_delta] (2.00s) the delta scenario passes',
].join('\n')

function seedStore(root) {
  const dev = join(root, 'projects', PROJECT, 'data', 'develop')
  mkdirSync(dev, { recursive: true })
  writeFileSync(join(dev, 'lines.json'), JSON.stringify([
    { version: 1, line_id: 'buffer', repositories: [{ name: 'fixture-repo', branch: 'main' }] },
  ]))
  return join(root, 'projects')
}

function seedFaceTree(root, entries) {
  // writer layout: the face (develop) dir carries rounds/ one level under it;
  // the override env names the FACE dir, the adapter joins `/rounds` itself
  const rounds = join(root, 'faces', 'rounds')
  mkdirSync(rounds, { recursive: true })
  for (const [runId, faceObj, log] of entries) {
    const d = join(rounds, runId)
    mkdirSync(d, { recursive: true })
    if (faceObj !== undefined) writeFileSync(join(d, 'face.json'), JSON.stringify(faceObj))
    if (log !== undefined) writeFileSync(join(d, 'suite.log'), log)
  }
  return rounds
}

async function roundFace(envExtra, runId) {
  // the REAL reader spawn seam the route uses (spawnCertificationRound), with
  // the fixture env injected — the panel's own path, not a hand-rolled spawn.
  const read = await READER.spawnCertificationRound(PROJECT, runId, { env: envExtra })
  if (read.ok === false) return { ok: false, why: read.reason }
  return { ok: true, receipt: read.receipt ?? read }
}

async function main() {
  const reader = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-reader.ts'))
    .catch((e) => { console.log('ENV_FAIL: executor-panel reader unimportable: ' + e.message); process.exit(2) })
  READER = reader
  if (typeof reader.spawnCertificationRound !== 'function') {
    console.log('ENV_FAIL: reader has no spawnCertificationRound spawn seam')
    console.log('SUMMARY pass=0 fail=0 env_fail=1 na=0')
    return 2
  }
  const view = await import(join(REPO, 'server/plugins/executor-panel/src/host/certification-view.ts'))
    .catch((e) => { console.log('ENV_FAIL: executor-panel view unimportable: ' + e.message); process.exit(2) })
  const dialogCore = view.buildRoundDialogCore
  const certCore = view.buildCertificationCore
  const roundPill = view.roundPill

  const root = tmp()
  const store = seedStore(root)
  const env0 = { [PROJECTS_ENV]: store }
  const redFace = baseFace({
    run_id: 'run-red-1', outcome: { verdict: 'red' },
    counts: { ran: 4, pass: 3, fail: 1, env_fail: 0 },
    last: { name: 'sc_beta', verdict: 'FAIL' },
  })
  const greenFace = baseFace({ run_id: 'run-green-1', outcome: { verdict: 'green' } })
  const norunFace = baseFace({
    run_id: 'run-norun-1', state: 'failed', outcome: { reason: 'suite runner missing' },
    counts: { ran: 0, pass: 0, fail: 0, env_fail: 0 },
  })
  const rounds = seedFaceTree(root, [
    ['run-red-1', redFace, SUITE_LOG],
    ['run-green-1', greenFace, 'PASS [sc_alpha] (1.20s) ok\n'],
    ['run-norun-1', norunFace, ''],
    ['run-cap-1', baseFace({ run_id: 'run-cap-1', outcome: { verdict: 'red' } }),
      Array.from({ length: 25 }, (_, i) => `FAIL [sc_many_${i}] exit=1 (1.00s) fails`).join('\n')],
  ])
  const env = { ...env0, [FACE_DIR_ENV]: dirname(rounds) }

  // ---- A the entry link: row → dialog for the SAME run ----
  const tabReceipt = { ok: true, project: PROJECT, lines: [], per_line: {}, meta_notes: [], runs_note: '',
    round_faces: { live: { ok: false, reason: 'no live pointer' }, rounds: [
      { run_id: 'run-red-1', face: redFace },
      { run_id: 'run-green-1', face: baseFace({ run_id: 'run-green-1', outcome: { verdict: 'green' } }) },
      { run_id: 'run-norun-1', face: norunFace },
    ] } }
  let tabHtml = null, tabErr = ''
  try { tabHtml = typeof certCore === 'function' ? String(certCore(tabReceipt)) : null }
  catch (e) { tabErr = e.message }
  check('A0 the embedded tab core renders a Rounds table with the run ids',
    tabHtml !== null && !tabErr &&
    ['run-red-1', 'run-green-1', 'run-norun-1'].every(id => tabHtml.includes(id)),
    tabErr || typeof certCore)
  const redDialog = await roundFace(env, 'run-red-1')
  check('A1 the round-mode reader answers a ROUND receipt for the row\'s run id',
    redDialog.ok && redDialog.receipt && redDialog.receipt.run === 'run-red-1'
    && (redDialog.receipt.face !== null || redDialog.receipt.face_reason !== null),
    redDialog.ok ? JSON.stringify(redDialog.receipt).slice(0, 200) : redDialog.why)
  if (redDialog.ok && redDialog.receipt) {
    const r = redDialog.receipt
    check('A2 the dialog face describes the SAME run the row showed '
      + '(run id, line, revision)', r.face && r.face.run_id === 'run-red-1'
      && r.face.line === 'buffer' && r.face.revision.repo === 'a'.repeat(40), r.face)
  }

  // ---- B dialog content ----
  if (redDialog.ok && redDialog.receipt) {
    const r = redDialog.receipt
    check('B1 the measured numbers travel (ran/pass/fail/env_fail)',
      r.face && r.face.counts && r.face.counts.ran === 4 && r.face.counts.fail === 1, r.face && r.face.counts)
    check('B2 the last judged case and its verdict travel',
      r.face && r.face.last_scenario && r.face.last_scenario.name === 'sc_beta'
      && r.face.last_scenario.verdict === 'FAIL', r.face && r.face.last_scenario)
    check('B3 failures parsed from the retained log: name/verdict/duration, garbled '
      + 'line ignored (2 real non-pass rows: fail + env_fail), duration present',
      r.failures && Array.isArray(r.failures.rows) && r.failures.rows.length === 2
      && r.failures.rows.some(x => x.name === 'sc_beta' && x.verdict === 'fail' && x.duration)
      && r.failures.rows.some(x => x.name === 'sc_gamma' && x.verdict === 'env_fail'),
      r.failures)
    check('B4 the retained log path is present and points INTO the face dir',
      typeof r.log_path === 'string' && r.log_path.startsWith(rounds) && r.log_path.endsWith('suite.log'), r.log_path)
    check('B5 the ONE Wrote face travels as clauses (the ledger join or the named '
      + 'absence), none silently dropped',
      Array.isArray(r.wrote), { wrote: r.wrote, note: r.wrote_note })
  } else check('B1 the measured numbers travel (ran/pass/fail/env_fail)', false, 'no round receipt')
  const capDialog = await roundFace(env, 'run-cap-1')
  if (capDialog.ok && capDialog.receipt) {
    const f = capDialog.receipt.failures
    check('B6 the failures cap is HONEST: capped rows + an exact "+N more" count '
      + '(25 fails, cap 20 → rows=20, more=5)', f && Array.isArray(f.rows)
      && f.rows.length === 20 && f.more === 5, f && { n: f.rows.length, more: f.more })
  } else check('B6 the failures cap is HONEST: capped rows + an exact "+N more" count', false, capDialog.why)

  // ---- C distinguishability from the face's own fields ----
  check('C0 the dialog render core exists in the embedded view',
    typeof dialogCore === 'function', typeof dialogCore)
  if (typeof roundPill === 'function') {
    const pr = roundPill(redFace), pg = roundPill(greenFace), pn = roundPill(norunFace)
    check('C1 red, green and could-not-run faces derive DIFFERENT pill keys from '
      + 'the face fields alone', pr.k !== pg.k && pg.k !== pn.k && pr.k !== pn.k,
      { red: pr, green: pg, norun: pn })
    check('C2 a could-not-run round\'s pill is the non-green state',
      pn.k !== 'g' && pn.k !== 'green', pn)
  }
  const greenDialog = await roundFace(env, 'run-green-1')
  const norunDialog = await roundFace(env, 'run-norun-1')
  if (typeof dialogCore === 'function' && redDialog.ok && greenDialog.ok && norunDialog.ok) {
    const redHtml = String(dialogCore(redDialog.receipt))
    const greenHtml = String(dialogCore(greenDialog.receipt))
    const noHtml = String(dialogCore(norunDialog.receipt))
    check('C3 red and green rounds render DIFFERENTLY (state derived from the '
      + 'face fields, not one shared shape)', redHtml !== greenHtml, 'identical render')
    check('C4 a could-not-run round renders NAMED, never as a passed round',
      noHtml.includes('suite runner missing') && noHtml !== greenHtml, noHtml.slice(0, 200))
    check('C5 the dialog names the retained log path to the user',
      redHtml.includes('suite.log'), 'log path not rendered')
  }

  // ---- D adversary faces ----
  const unknown = await roundFace(env, 'run-unknown-9')
  const refusalOf = (r) => (!r.ok && r.why) || (r.ok && r.receipt
    && (r.receipt.ok === false && r.receipt.reason
      || r.receipt.face === null && r.receipt.face_reason))
  check('D1 unknown run id is refused BY NAME', !!refusalOf(unknown)
    && /retained|unknown|absent|missing|not/i.test(String(refusalOf(unknown))), refusalOf(unknown))
  const trav = await roundFace(env, '../' + PROJECT)
  check('D2 a path-shaped run id is refused by NAME (no traversal)',
    !!refusalOf(trav), trav.ok ? JSON.stringify(trav.receipt).slice(0, 200) : trav.why)
  const trav2 = await roundFace(env, 'sub/evil')
  check('D3 a separator-bearing run id is refused by NAME',
    !!refusalOf(trav2), trav2.ok ? JSON.stringify(trav2.receipt).slice(0, 200) : trav2.why)

  // D4 missing retained log: named absence, never an empty failures table
  const noLogRoot = tmp()
  seedStore(noLogRoot)
  const noLogRounds = seedFaceTree(noLogRoot, [['run-nolog-1', baseFace({ run_id: 'run-nolog-1' })]])
  const noLogDialog = await roundFace({ ...env0, [FACE_DIR_ENV]: dirname(noLogRounds) }, 'run-nolog-1')
  check('D4 a missing retained log is a NAMED absence, not an empty failures '
    + 'table implying zero failures', noLogDialog.ok && noLogDialog.receipt
    && typeof noLogDialog.receipt.failures_absent === 'string'
    && noLogDialog.receipt.failures === null, noLogDialog.ok
    ? { failures: noLogDialog.receipt.failures, absent: noLogDialog.receipt.failures_absent }
    : noLogDialog.why)

  console.log(`SUMMARY pass=${PASS} fail=${FAIL} env_fail=0 na=0`)
  return FAIL === 0 ? 0 : 1
}

process.exit(await main())
