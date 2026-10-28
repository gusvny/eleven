/**
 * tests/t261028-56-verdict-readers.mjs — the last three readers of the gate
 * receipt family (after t261028-46 and t261028-48).
 *
 * Root cause (host methodology 260907: one reported symptom is a SAMPLE, the
 * same mechanism must be classified on every face): the engine writes a gate
 * receipt in TWO shapes —
 *
 *   - SCRIPT gates: `{check, level: 'green'|'red', count}` (no `green`);
 *   - AGENT/HUMAN gates: `{item, by, done, green}`.
 *
 * Three readers still judged one shape / truthiness:
 *
 *   - d2StatusLine (index.tsx): verdict by `g?.green` and a HARDCODED
 *     "(merge_check green)" → a green script gate printed nothing, and an agent
 *     run of ANOTHER stage printed the wrong stage name (false attribution);
 *   - status-card.ts "All prior gates green": `go.green !== true` → a green
 *     script gate never reached the sign-off card;
 *   - dev_lane.py merge_check red_count: `not c.get("green")` → every green
 *     script row counted as a red, so the count contradicted the face.
 *
 * Every one of them now goes through the ONE rule in lane-map-model
 * (`readGateRunVerdict` / `gateRunStage` / `gateApprovalSuffix`) or its proven
 * mirror in dev_lane (`gate_row_verdict` / `gate_row_name` / `gate_row_reds`).
 *
 * Run: node server/plugins/workbench/tests/t261028-56-verdict-readers.mjs
 * Covers:
 *   A. ANTI-PROOF: today's truthiness + hardcoded literal, re-expressed
 *      verbatim, mislabels a script-gate run (no green shown) and an agent run
 *      of another stage (wrong stage named). The shared rule does neither.
 *   B. Status line: both shapes through gateApprovalSuffix; the stage name comes
 *      from the data; red / absent / malformed never announce green.
 *   C. Status card: both shapes reach "All prior gates green"; a red gate never
 *      does; the card names the run it quotes.
 *   D. CLIENT/ENGINE AGREEMENT: the SAME receipt rows are fed through the client
 *      reader (buildChecksDetail) and the engine's count (dev_lane, real
 *      interpreter) and the two must agree — red count and per-row verdict.
 *   E. ONE rule: no reader keeps a private copy of the verdict/name predicate
 *      (source scan on the three fixed sites); the shipped bundle carries it.
 *   F. Malformed / absent faces: no throw, nothing invented.
 *
 * No console, no port 3099, no integration run: pure functions + source text +
 * one local python interpreter (the lane's own engine venv).
 */

import { execFileSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  buildChecksDetail, gateApprovalSuffix, gateRunStage, readGateRunVerdict, receiptRowView,
} from '../src/client/lane-map-model.ts'
import { buildStatusCard } from '../src/host/status-card.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = (() => {
  let d = here
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()
const wbDir = join(repo, 'server/plugins/workbench')
const readSrc = (rel) => readFileSync(join(wbDir, rel), 'utf8')
const readRepo = (rel) => readFileSync(join(repo, rel), 'utf8')

// Import specifiers used by the source locks below are assembled from pieces, so
// a source-text assertion is never itself an import statement the repo's
// relative-import lint (L3) must resolve.
const PM_MODEL = '.' + '/problems-model.ts'
const LM_MODEL = '..' + '/client/lane-map-model.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── Real receipt shapes (verbatim keys, measured on live ticket faces) ── */

// verify_lane code / cs-machine-qc: SCRIPT rows {check, level, count}
const SCRIPT_RUN_GREEN = {
  stage: 'verify_lane', label: 'verify_lane code',
  level: 'green', red_count: 0, exit_code: 0,
  checks: [
    { check: 'write-set whitelist', level: 'green', count: 0 },
    { check: 'lint', level: 'green', count: 0 },
    { check: 'type check', level: 'green', count: 0 },
  ],
}
const SCRIPT_RUN_RED = {
  stage: 'verify_lane', label: 'verify_lane code',
  level: 'red', red_count: 2, exit_code: 1,
  checks: [
    { check: 'write-set whitelist', level: 'red', count: 2 },
    { check: 'lint', level: 'green', count: 0 },
    { check: 'type check', level: 'green', count: 0 },
  ],
}
// merge_check: AGENT rows {item, green, id, detail, …}
const AGENT_RUN_GREEN = {
  stage: 'merge_check', label: 'merge_check (programmatic checks)',
  green: true, red_count: 0, exit_code: 0,
  checks: [
    { item: 'Lane branch has commits', green: true, id: 'lane_commits', detail: '3 commits' },
    { item: 'In-lane verify_lane code is green', green: true, id: 'verify_lane_code' },
  ],
}
const AGENT_RUN_RED = {
  stage: 'merge_check', label: 'merge_check (programmatic checks)',
  green: false, red_count: 1, exit_code: 0,
  checks: [
    { item: 'Lane branch has commits', green: true, id: 'lane_commits', detail: '3 commits' },
    { item: 'Worktree is clean', green: false, id: 'clean', detail: 'dirty files: 2' },
  ],
}
// An agent run of ANOTHER stage whose label says something else — the shape the
// t261008-07 scenario carries (stage review_plan, label merge_check). A face that
// prints a literal instead of `stage` mislabels it.
const OTHER_STAGE_RUN = {
  stage: 'review_plan', label: 'merge_check',
  green: true, red_count: 0, exit_code: 0,
  checks: [{ item: 'plan reviewed', green: true, id: 'plan_ok' }],
}

/* ── A. ANTI-PROOF: today's reading, verbatim, on the two real shapes ── */

// d2StatusLine before this ticket (index.tsx: `g?.green ? ' (merge_check green)' : ''`)
const oldStatusSuffix = (g) => (g?.green ? ' (merge_check green)' : '')
// status-card before this ticket: `if (go.green !== true) continue` then `${stage || 'programmatic check'}`
const oldSignWhat = (run) => {
  if (run.green !== true) return null
  const stage = typeof run.stage === 'string' ? run.stage : ''
  return `All prior gates green: ${stage || 'programmatic check'} (ready to sign)`
}
{
  // A green SCRIPT gate: the old truthiness read sees no `green` → the status
  // line silently claims nothing while the gate IS green.
  ok(oldStatusSuffix(SCRIPT_RUN_GREEN) === '', 'A: anti-proof — old truthiness prints no green for a green script gate')
  ok(gateApprovalSuffix(SCRIPT_RUN_GREEN) === ' (verify_lane green)',
    'A: shared rule — the same script gate reads green, named from the data')
  // An agent run of ANOTHER stage: the old literal names merge_check regardless.
  ok(oldStatusSuffix(OTHER_STAGE_RUN) === ' (merge_check green)',
    'A: anti-proof — old literal mislabels a review_plan run as merge_check')
  ok(gateApprovalSuffix(OTHER_STAGE_RUN) === ' (review_plan green)',
    'A: shared rule — the stage named is the one the run actually is (never the label, never a literal)')
  // Same defect class on the sign-off card.
  ok(oldSignWhat(SCRIPT_RUN_GREEN) === null,
    'A: anti-proof — old `green !== true` drops the green script gate from the sign-off card')
  ok(oldSignWhat(AGENT_RUN_GREEN).includes('merge_check'), 'A: old rule worked only for the agent shape it assumed')
}

/* ── B. Status line (d2StatusLine via the shared suffix) ── */
{
  ok(gateApprovalSuffix(AGENT_RUN_GREEN) === ' (merge_check green)', 'B: agent shape — unchanged wording')
  ok(gateApprovalSuffix(AGENT_RUN_RED) === '', 'B: red agent run announces nothing')
  ok(gateApprovalSuffix(SCRIPT_RUN_RED) === '', 'B: red script run announces nothing')
  ok(gateApprovalSuffix(undefined) === '', 'B: no gate run → no suffix (no invented green)')
  ok(gateApprovalSuffix({}) === '', 'B: a run with no verdict field → no suffix')
  ok(gateApprovalSuffix({ green: 'maybe' }) === '', 'B: an unknown verdict word invents nothing')
  ok(gateApprovalSuffix({ level: 'green' }) === ' (gate green)',
    'B: a nameless green run falls back to the neutral word, not to a stage it is not')
  ok(gateApprovalSuffix({ stage: 'verify_lane', verdict: 'green' }) === ' (verify_lane green)',
    'B: the `verdict` field is read too (same field order as the rows)')
  ok(gateApprovalSuffix({ stage: 'x', green: false, level: 'green' }) === '',
    'B: conflicting signals resolve red (a face never upgrades a run)')
  ok(readGateRunVerdict(SCRIPT_RUN_GREEN).source === 'level', 'B: verdict source is named per field')
  ok(gateRunStage({ label: 'only a label' }) === 'only a label', 'B: label is the fallback name')
  ok(gateRunStage({}) === '', 'B: no name in the data → empty (the caller supplies its word)')

  // Source lock: d2StatusLine consumes the shared suffix and keeps no literal.
  const idx = readSrc('src/client/index.tsx')
  ok(idx.includes(PM_MODEL) && idx.includes('gateProblemRows') && idx.includes('lastGateRun'),
    'B: index.tsx imports the shared last-run reader (both entry shapes tolerated)')
  ok(/import \{[^}]*gateApprovalSuffix[^}]*\} from '\.\/lane-map-model\.ts'/.test(idx),
    'B: index.tsx imports the shared approval suffix from the model')
  ok(idx.includes('${gateApprovalSuffix(g)}'), 'B: the awaiting-human line is built by the shared suffix')
  ok(!idx.includes("' (merge_check green)'"), 'B: the hardcoded stage literal is gone from the status line')
}

/* ── C. Status card: "All prior gates green" ── */
{
  const card = (runs) => buildStatusCard({
    stage_state: 'awaiting-human',
    human_context: { merge: { context_text: 'sign here' } },
    stage_acceptance: [],
    gate_runs: runs,
    timeline: [{ at: 'T1', stage: 'merge', state: 'awaiting-human', reason: 'waiting' }],
  })
  const signLine = (c) => (c?.signWhat ?? []).find(s => s.startsWith('All prior gates green'))
  ok(signLine(card([SCRIPT_RUN_GREEN])) === 'All prior gates green: verify_lane (ready to sign)',
    'C: script shape (level) reaches the card, named from the data')
  ok(signLine(card([AGENT_RUN_GREEN])) === 'All prior gates green: merge_check (ready to sign)',
    'C: agent shape — unchanged wording')
  ok(signLine(card([SCRIPT_RUN_RED])) === undefined, 'C: a red script gate is never announced green')
  ok(signLine(card([AGENT_RUN_RED])) === undefined, 'C: a red agent gate is never announced green')
  ok(signLine(card([{ stage: 'gate' }])) === undefined, 'C: a run with no verdict field is not green')
  // The last green run wins even when newer red runs follow (unchanged scan order).
  ok(signLine(card([SCRIPT_RUN_GREEN, AGENT_RUN_RED])) === 'All prior gates green: verify_lane (ready to sign)',
    'C: the newest green run is the one quoted (scan order unchanged)')

  const src = readSrc('src/host/status-card.ts')
  ok(src.includes('gateRunStage') && src.includes('readGateRunVerdict') && src.includes(LM_MODEL),
    'C: the host reads the client model pure accessors (no second implementation; host-to-client import is already the pattern here)')
  ok(src.includes('readGateRunVerdict(go).green !== true'), 'C: the card judges the run through the shared verdict rule')
  ok(src.includes('gateRunStage(go) ||'), 'C: the card names the run from the data')
  ok(!src.includes('go.green !== true'), 'C: the private truthiness predicate is gone')
}

/* ── D. CLIENT/ENGINE AGREEMENT on the SAME fixture ── */

// Rows chosen to hit every branch of the rule: script green/red, agent
// green/red, id-only green (agent_activities D4 shape), no-signal row, a bare
// scalar row, and two junk values that are not rows at all.
const AGREEMENT_ROWS = [
  { check: 'write-set whitelist', level: 'green', count: 0 },
  { check: 'lint', level: 'red', count: 2, note: 'two files touched' },
  { item: 'Lane branch has commits', green: true, id: 'lane_commits' },
  { item: 'Worktree is clean', green: false, id: 'clean', detail: 'dirty files: 2' },
  { id: 'id_only_green', green: true },
  { item: 'no verdict field at all' },
  { verdict: 'green', item: 'run-style wording on a row' },
  { item: 'conflicting', green: false, level: 'green' },
  'bare scalar row',
  null,
  7,
  true,
]

function clientRedCount(rows) {
  // The face the host opens: no run-level red_count in the fixture, so the
  // Check-details model derives the count from the rows it shows.
  return buildChecksDetail({ gate_runs: [{ stage: 'fixture_gate', checks: rows }] })[0].redCount
}

function pythonJson(engineDir, rows) {
  const py = join(repo, 'server/engine/.venv/bin/python')
  if (!existsSync(py)) throw new Error(`engine venv python missing: ${py} — the client/engine agreement fixture needs the lane's engine interpreter`)
  const code = [
    'import json, sys',
    'sys.path.insert(0, sys.argv[1])',
    'import dev_lane',
    'rows = json.loads(sys.stdin.read())',
    'print(json.dumps({',
    '  "reds": len(dev_lane.gate_row_reds(rows)),',
    '  "verdicts": [dev_lane.gate_row_verdict(r) for r in rows],',
    '  "names": [dev_lane.gate_row_name(r) for r in rows],',
    '}))',
  ].join('\n')
  const out = execFileSync(py, ['-c', code, join(repo, 'server/engine')],
    { input: JSON.stringify(rows), encoding: 'utf8', timeout: 120000 })
  return JSON.parse(out.trim().split('\n').at(-1))
}

{
  // The client's per-row view: a dropped row is not shown; a shown row carries
  // the verdict the engine's Face prints.
  const clientViews = AGREEMENT_ROWS.map(r => receiptRowView(r))
  const clientReds = clientRedCount(AGREEMENT_ROWS)
  let engine = null
  try {
    engine = pythonJson(join(repo, 'server/engine'), AGREEMENT_ROWS)
  } catch (e) {
    ok(false, `D: the engine side ran at all (${e.message})`)
  }
  if (engine) {
    ok(engine.reds === clientReds,
      `D: the engine's red count equals the face's red count on the same rows (engine=${engine.reds}, face=${clientReds})`)
    // Per-row verdict agreement: green on the client must be green in the engine.
    const mismatched = AGREEMENT_ROWS
      .map((r, i) => ({ i, client: clientViews[i] !== null && clientViews[i].green, engine: engine.verdicts[i] === true }))
      .filter(x => x.client !== x.engine)
    ok(mismatched.length === 0,
      `D: per-row green agrees for every row (mismatches: ${JSON.stringify(mismatched)})`)
    // Row-name agreement: the same readable name on both sides (scalars name
    // themselves; junk names nothing).
    const nameMismatch = AGREEMENT_ROWS
      .map((r, i) => ({ i, client: (clientViews[i] && clientViews[i].item) || '', engine: engine.names[i] || '' }))
      .filter(x => x.client !== x.engine)
    ok(nameMismatch.length === 0,
      `D: per-row name agrees for every row (mismatches: ${JSON.stringify(nameMismatch)})`)
    // The same fixture through the ENGINE's historical predicate (anti-proof):
    // every green script row was counted as a red.
    const oldEngineCount = AGREEMENT_ROWS
      .filter(c => !(c !== null && typeof c === 'object' && c.green === true)).length
    ok(oldEngineCount !== engine.reds,
      `D: anti-proof — the retired engine predicate counts ${oldEngineCount} reds, the shared rule ${engine.reds}`)
  }
  // And the client alone: a fully green script run is 0 red, the run verdict is green.
  const greenRun = buildChecksDetail({ gate_runs: [SCRIPT_RUN_GREEN] })[0]
  ok(greenRun.redCount === 0 && greenRun.green === true,
    'D: face — a fully green script run is green with 0 red (the count the engine now writes)')
}

/* ── E. ONE rule: no reader keeps a private copy ── */
{
  const model = readSrc('src/client/lane-map-model.ts')
  ok((model.match(/export function readGateRunVerdict\b/g) || []).length === 1,
    'E: the run-verdict reader is defined exactly once')
  ok((model.match(/export function gateRunStage\b/g) || []).length === 1,
    'E: the run-name reader is defined exactly once')
  ok((model.match(/export function gateApprovalSuffix\b/g) || []).length === 1,
    'E: the status-line suffix is defined exactly once')

  const engine = readRepo('server/engine/dev_lane.py')
  ok((engine.match(/^def gate_row_verdict\b/mg) || []).length === 1,
    'E: the engine row-verdict rule is defined exactly once')
  ok((engine.match(/^def gate_row_reds\b/mg) || []).length === 1,
    'E: the engine red-set rule is defined exactly once')
  ok((engine.match(/^def gate_row_name\b/mg) || []).length === 1,
    'E: the engine row-name rule is defined exactly once')
  // No merge_check red_count left on the private predicate (both lane faces).
  ok(!engine.includes('len([c for c in mc.checks if not c.get("green")])'),
    'E: neither merge_check face computes its red_count by the retired predicate')
  ok((engine.match(/"red_count": len\(gate_row_reds\(mc\.checks\)\)/g) || []).length === 2,
    'E: both merge_check faces count through the shared rule (dev lane + quickmanual lane)')
  ok(engine.includes('reds = [c for c in gate_row_reds(checks) if isinstance(c, dict)]'),
    'E: the quiet-baseline coverage predicate uses the same red set')
  ok(!engine.includes('for c in mc.checks if not c.get("green")'),
    'E: the merge_check red texts come from the shared red set too')
  ok(!engine.includes('isinstance(c, dict) and c.get("green") is False'),
    'E: the blocked_detail face judges rows through the shared verdict')

  // Shipped bundles carry the shared suffix (plumbing guard: a source-only fix
  // renders nothing on the console the host opens).
  for (const out of ['lib/client.js', 'lib/client.cjs']) {
    const p = join(wbDir, out)
    if (!existsSync(p)) { ok(false, `E: shipped bundle present (${out})`); continue }
    const bundle = readFileSync(p, 'utf8')
    ok(bundle.includes('gateApprovalSuffix') && bundle.includes('readGateRunVerdict'),
      `E: ${out} carries the shared run readers (bundle rebuilt)`)
    ok(!bundle.includes('(merge_check green)'), `E: ${out} no longer carries the hardcoded stage literal`)
  }
}

/* ── F. Malformed / absent faces ── */
{
  for (const bad of [undefined, null, 42, 'x', [], {}, { gate_runs: 'no' }, { gate_runs: [null, 7, 'x', {}] },
    { gate_runs: [{ stage: 's', level: 'weird', checks: [null, undefined, true, 'x', 3] }] }]) {
    let threw = false
    try {
      gateApprovalSuffix(bad && typeof bad === 'object' ? bad : undefined)
      buildStatusCard(bad)
      buildChecksDetail(bad)
    } catch (e) { threw = true; console.error(e) }
    ok(!threw, `F: malformed input does not throw on the fixed faces (${JSON.stringify(bad)})`)
  }
  ok(buildStatusCard(undefined) === null, 'F: absent detail renders no card')
  ok(gateApprovalSuffix(undefined) === '' && gateRunStage({}) === '',
    'F: absent run announces nothing and names nothing')
  // Engine side, same discipline.
  let engineBad = null
  try {
    engineBad = pythonJson(join(repo, 'server/engine'),
      [{ level: 'weird' }, {}, 'x', 3, null, [], { green: true }, { green: 'red' }, { done: true }])
  } catch (e) {
    ok(false, `F: the engine side tolerated malformed rows at all (${e.message})`)
  }
  if (engineBad) {
    ok(engineBad.reds === 6,
      `F: engine — no-signal/junk/scalar rows count red, green rows do not (reds=${engineBad.reds})`)
    ok(engineBad.verdicts[0] === null && engineBad.verdicts[0] !== false,
      'F: engine — an unknown verdict word stays unknown (never an invented verdict)')
  }
}

console.log(`\nt261028-56-verdict-readers: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
