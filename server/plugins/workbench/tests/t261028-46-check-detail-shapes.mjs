/**
 * tests/t261028-46-check-detail-shapes.mjs — Check details reads BOTH gate
 * receipt shapes with one implementation.
 *
 * Root cause (t261028-46, host report 261028): `buildChecksDetail` accepted
 * only `co.green === true` and `co.item`. The engine writes two shapes into
 * `gate_runs[*].checks[*]`:
 *   - SCRIPT gates (cs-machine-qc / verify_lane code / release ledger):
 *     `{check: "溯源校验…", level: "green"|"red", count: N}` (measured on
 *     t261028-09 / t261028-37 live faces);
 *   - AGENT and HUMAN gates: `{item, by, done, green, id, detail, …}`.
 * So every script row rendered RED and UNNAMED under an "all green" header.
 *
 * Run: node server/plugins/workbench/tests/t261028-46-check-detail-shapes.mjs
 * Covers:
 *   A. ANTI-PROOF: today's reader predicate (re-expressed verbatim) turns the
 *      real script shape red + unnamed; the new reader makes the same input
 *      green + named.
 *   B. Both shapes through the real buildChecksDetail (script rows named/green
 *      with `count` carried; agent/human rows byte-identical to today).
 *   C. Stage-level honesty: the run verdict is read from whatever the engine
 *      wrote (green → level → verdict → rows); a genuine verdict/rows
 *      disagreement is reported, never reconciled.
 *   D. Malformed and mixed shapes degrade to a NAMED row, never throw, never
 *      drop a row that carries information.
 *   E. Source anchors: `co.green === true` is no longer the only green signal;
 *      the disagreement is rendered on the detail face; the shipped bundle
 *      carries the new reader.
 *
 * Pure-function + source/bundle text assertions only: no console, no port
 * 3099, no integration run.
 */

import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { buildChecksDetail } from '../src/client/lane-map-model.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = (() => {
  let d = here
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── Real receipt shapes (verbatim keys from live ticket faces) ── */

// t261028-09 gate_runs: script gates only (cs-machine-qc / cs-tooling).
const SCRIPT_GATE_DETAIL = {
  gate_runs: [
    { stage: 'cs-machine-qc', label: 'cs_machine_qc contract（溯源校验＋契约校验固定项）',
      green: true, red_count: 0, exit_code: 0,
      checks: [
        { check: '溯源校验（checkpoint 可指回内容源位置）', level: 'green', count: 0 },
        { check: '契约校验（四件套/定位符）', level: 'green', count: 0 },
        { check: '契约校验（类型分布合理）', level: 'green', count: 0 },
      ] },
    { stage: 'cs-tooling', label: 'verify_lane code（代码道 QC）',
      green: true, red_count: 0, exit_code: 0,
      checks: [{ check: '写集白名单', level: 'green', count: null }] },
  ],
}

// t261028-37 gate_runs: agent / human gates (merge_check shape).
const AGENT_GATE_DETAIL = {
  gate_runs: [
    { stage: 'merge_check', label: 'merge_check (programmatic checks)', green: false, red_count: 1, exit_code: 0,
      checks: [
        { id: 'lane_commits', item: '[clientapp] Lane branch has commits', green: true, detail: '1 commit(s)' },
        { id: 'worktree_clean', item: '[clientapp] Worktree is clean (no uncommitted changes)', green: true, detail: '干净' },
        { id: 'verify_lane_code', item: '[clientapp] In-lane verify_lane code is green', green: false,
          detail: 'exit=1 red=1；改动文件不在本票写集: server/zz_probe.py', reason_code: 'verify_red',
          files: ['server/zz_probe.py'], next_action: 'fix the red item then retry_qc' },
      ] },
  ],
}

// A red script gate: level:'red' + count>0 (script-gate red path).
const SCRIPT_RED_DETAIL = {
  gate_runs: [
    { stage: 'cs-machine-qc', label: 'cs_machine_qc contract（溯源校验＋契约校验固定项）',
      green: false, red_count: 1, exit_code: 1,
      checks: [
        { check: '溯源校验（checkpoint 可指回内容源位置）', level: 'red', count: 3 },
        { check: '契约校验（四件套/定位符）', level: 'green', count: 0 },
      ] },
  ],
}

/* ── A. Anti-proof: today's reader on the real script shape ── */
{
  // Today's reader predicate, re-expressed verbatim (model line ~1016-1024
  // before the fix): only `co.item` names a row, only `co.green === true`
  // makes it green.
  const oldReaderRow = (co) => {
    const item = typeof co.item === 'string' ? co.item : ''
    const green = co.green === true
    const checkId = typeof co.id === 'string' ? co.id : ''
    return { green, item: item || checkId || '' }
  }
  const scriptRow = SCRIPT_GATE_DETAIL.gate_runs[0].checks[0]
  const oldRow = oldReaderRow(scriptRow)
  ok(oldRow.green === false && oldRow.item === '',
    'A: anti-proof — today\'s reader renders the real script row RED and UNNAMED ({check,level,count})')

  const newRun = buildChecksDetail(SCRIPT_GATE_DETAIL).find(r => r.stage === 'cs-machine-qc')
  const newRow = newRun.rows[0]
  ok(newRow.green === true && newRow.item === '溯源校验（checkpoint 可指回内容源位置）',
    'A: new reader — same input row is GREEN and NAMED')
  ok(newRun.green === true && newRun.rowsGreen === true && newRun.disagreement === false,
    'A: new reader — stage header and rows agree (green / all rows green)')
  // The anti-proof must fail on the agent shape too if the reader ignored
  // `item`: the fix must not have traded one shape for the other.
  const agentRow = AGENT_GATE_DETAIL.gate_runs[0].checks[0]
  ok(oldReaderRow(agentRow).item === agentRow.item && oldReaderRow(agentRow).green === true,
    'A: anti-proof — the old reader did read the agent/human shape (regression lock)')
}

/* ── B. Both shapes through the real buildChecksDetail ── */
{
  const runs = buildChecksDetail(SCRIPT_GATE_DETAIL)
  ok(runs.length === 2, 'B: script detail → two runs')
  ok(runs[0].stage === 'cs-tooling', 'B: newest run first')
  ok(runs[0].rows.length === 1 && runs[0].rows[0].item === '写集白名单', 'B: script row named from `check`')
  ok(runs[0].rows[0].green === true, 'B: script row green from `level: green`')
  ok(runs[0].rows[0].count === undefined, 'B: `count: null` → no count (never NaN/0 invented)')
  ok(runs[0].verdictSource === 'green' && runs[0].green === true, 'B: script run verdict read from `green`')
  ok(runs[1].rows.length === 3 && runs[1].rows.every(r => r.green && r.item.length > 0),
    'B: every script row named and green (the host-reported face)')
  ok(runs[1].rows[0].count === 0, 'B: `count: 0` carried')
  ok(runs[1].rows.every(r => r.detail === undefined && r.files.length === 0), 'B: no invented detail/files on script rows')

  const redRuns = buildChecksDetail(SCRIPT_RED_DETAIL)
  ok(redRuns[0].green === false && redRuns[0].redCount === 1, 'B: red script run verdict/red_count read')
  ok(redRuns[0].rows[0].green === false && redRuns[0].rows[0].count === 3,
    'B: red script row red with count carried')
  ok(redRuns[0].rows[1].green === true, 'B: green script row under a red run stays green')
  ok(redRuns[0].disagreement === false, 'B: red run + a red row = agreement (no false alarm)')

  // Agent/human shape: keep today's rendering exactly.
  const agent = buildChecksDetail(AGENT_GATE_DETAIL)[0]
  ok(agent.stage === 'merge_check' && agent.green === false && agent.redCount === 1, 'B: agent run verdict kept')
  ok(agent.rows.length === 3, 'B: agent rows all present')
  ok(agent.rows[0].item === '[clientapp] Lane branch has commits' && agent.rows[0].green === true
    && agent.rows[0].detail === '1 commit(s)' && agent.rows[0].checkId === 'lane_commits',
    'B: agent green row (item/detail/id) rendered as today')
  const red = agent.rows[2]
  ok(red.green === false && red.reasonCode === 'verify_red' && red.files[0] === 'server/zz_probe.py'
    && red.nextAction === 'fix the red item then retry_qc',
    'B: agent red row keeps reason_code/files/next_action')
  ok(agent.disagreement === false && agent.rowsGreen === false, 'B: agent red run agrees with its red row')

  // id-only green row (agent_activities D4 shape) still gets the id as name.
  const idOnly = buildChecksDetail({ gate_runs: [{ stage: 's', green: true, red_count: 0,
    checks: [{ id: 'worktree_clean', green: true }] }] })[0]
  ok(idOnly.rows.length === 1 && idOnly.rows[0].item === 'worktree_clean', 'B: id-only green row named by `id`')
}

/* ── C. Stage/row honesty: verdict source + disagreement ── */
{
  // Run-level `level` (script-gate run row that carries it) is read.
  const lv = buildChecksDetail({ gate_runs: [{ stage: 's', level: 'green', red_count: 0,
    checks: [{ check: 'c1', level: 'green', count: 0 }] }] })[0]
  ok(lv.verdictSource === 'level' && lv.green === true && lv.disagreement === false,
    'C: run verdict from `level` when `green` is absent')

  const vd = buildChecksDetail({ gate_runs: [{ stage: 's', verdict: 'red', red_count: 1,
    checks: [{ check: 'c1', level: 'red', count: 1 }] }] })[0]
  ok(vd.verdictSource === 'verdict' && vd.green === false && vd.disagreement === false,
    'C: run verdict from `verdict` when green/level are absent')

  // No written verdict: the rows decide — a "0 red" header is never invented.
  const rowsOnly = buildChecksDetail({ gate_runs: [{ stage: 's',
    checks: [{ check: 'c1', level: 'green', count: 0 }] }] })[0]
  ok(rowsOnly.verdictSource === 'rows' && rowsOnly.green === true && rowsOnly.disagreement === false,
    'C: no written verdict → rows decide (all-green rows are not branded red)')

  // Genuine disagreement #1: written green, a red row underneath.
  const lie = { gate_runs: [{ stage: 's', label: 'gate L', green: true, red_count: 0,
    checks: [{ check: 'c1', level: 'green', count: 0 }, { check: 'c2', level: 'red', count: 2 }] }] }
  const lieRun = buildChecksDetail(lie)[0]
  ok(lieRun.green === true && lieRun.rowsGreen === false && lieRun.disagreement === true,
    'C: green header + red row → disagreement surfaced')
  ok(lieRun.green === true, 'C: the reader does not overwrite the engine\'s written verdict')
  ok(lieRun.rows[1].green === false && lieRun.rows[1].item === 'c2', 'C: the red row stays red and named')

  // Genuine disagreement #2: written red, every row green.
  const lie2 = { gate_runs: [{ stage: 's', green: false, red_count: 0,
    checks: [{ check: 'c1', level: 'green', count: 0 }] }] }
  const lie2Run = buildChecksDetail(lie2)[0]
  ok(lie2Run.green === false && lie2Run.rowsGreen === true && lie2Run.disagreement === true,
    'C: red header + all-green rows → disagreement surfaced')

  // Genuine disagreement #3: green verdict with a non-zero red count.
  const lie3 = buildChecksDetail({ gate_runs: [{ stage: 's', green: true, red_count: 2,
    checks: [{ check: 'c1', level: 'green', count: 0 }] }] })[0]
  ok(lie3.disagreement === true, 'C: green verdict + red_count>0 → disagreement surfaced')

  // No rows = nothing to disagree with (a red gate without detail is not a lie).
  const bare = buildChecksDetail({ gate_runs: [{ stage: 's', green: false, red_count: 2 }] })[0]
  ok(bare.disagreement === false && bare.verdictSource === 'green' && bare.rows.length === 0,
    'C: red gate with no rows → no invented disagreement')
}

/* ── D. Malformed / mixed shapes: named row, no throw, no silent drop ── */
{
  const bad = [
    undefined, null, 42, 'x', [], {}, { gate_runs: 'no' }, { gate_runs: [] },
    { gate_runs: [null, 7, 'x', {}] }, { gate_runs: [{ stage: 's', checks: 'no' }] },
    { gate_runs: [{ stage: 's', checks: [null, undefined, true] }] },
  ]
  for (const b of bad) {
    let threw = false
    try { buildChecksDetail(b) } catch (e) { threw = true; console.error(e) }
    ok(!threw, `D: malformed detail does not throw (${JSON.stringify(b)})`)
  }
  ok(buildChecksDetail(null).length === 0 && buildChecksDetail({}).length === 0,
    'D: no gate_runs → empty model')

  // Mixed row: item wins the name, conflicting green/level resolves red.
  const mixed = buildChecksDetail({ gate_runs: [{ stage: 's', green: false,
    checks: [{ item: 'agent name', check: 'script name', id: 'rid', green: false, level: 'green' }] }] })[0]
  ok(mixed.rows[0].item === 'agent name', 'D: mixed row — `item` wins the name')
  ok(mixed.rows[0].green === false, 'D: mixed row — conflicting green/level resolves red (never upgraded)')

  // A row with information but no name field: named, not dropped.
  const nameless = buildChecksDetail({ gate_runs: [{ stage: 's', green: false,
    checks: [{ level: 'green', count: 2 }, { detail: 'boom' }, { id: 'xid' }] }] })[0]
  ok(nameless.rows.length === 3, 'D: nameless but informative rows are kept')
  ok(nameless.rows.every(r => typeof r.item === 'string' && r.item.length > 0),
    'D: every kept row degrades to a NAMED row')
  ok(nameless.rows[1].item === 'unnamed check' && nameless.rows[1].green === false,
    'D: detail-only row named "unnamed check" and shown red')

  // Bare string / number rows carry a name: kept, never dropped.
  const scalars = buildChecksDetail({ gate_runs: [{ stage: 's', green: false,
    checks: ['plain check text', 7, ''] }] })[0]
  ok(scalars.rows.length === 2 && scalars.rows[0].item === 'plain check text' && scalars.rows[1].item === '7',
    'D: scalar rows become named rows (empty string skipped)')

  // Truly empty green row adds nothing (today's contract kept).
  const emptyGreen = buildChecksDetail({ gate_runs: [{ stage: 's', green: true,
    checks: [{ green: true }] }] })[0]
  ok(emptyGreen.rows.length === 0, 'D: green row with no name and no payload is not noise')

  // Weird verdict values degrade: no invented green, row still shown.
  const weird = buildChecksDetail({ gate_runs: [{ stage: 's', green: 'maybe',
    checks: [{ check: 'c1', level: 'yellow' }] }] })[0]
  ok(weird.rows.length === 1 && weird.rows[0].green === false && weird.rows[0].item === 'c1',
    'D: unknown level word → row kept, shown red, named')
  ok(weird.verdictSource === 'rows' && weird.green === false,
    'D: unknown run verdict word → rows decide (no invented green)')
}

/* ── E. Source and bundle anchors ── */
{
  const model = readFileSync(join(repo, 'server/plugins/workbench/src/client/lane-map-model.ts'), 'utf8')
  ok(!model.includes('co.green === true'), 'E: model no longer uses `co.green === true` as the only green signal')
  ok(model.includes('co.level') && model.includes('co.verdict') && model.includes('co.done'),
    'E: model reads level/verdict/done alongside green')
  ok(model.includes('asString(co.check)'), 'E: model reads the script shape name from `check`')
  ok(model.includes('verdictSource') && model.includes('rowsGreen') && model.includes('disagreement'),
    'E: model exposes verdict source / rows verdict / disagreement')
  ok(/name = asString\(co\.item\) \|\| asString\(co\.check\) \|\| checkId/.test(model),
    'E: single name rule item || check || id')

  const ui = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  ok(ui.includes('buildChecksDetail(detail)'), 'E: detail face consumes the model')
  ok(ui.includes('checks-verdict-disagreement') && ui.includes('r.disagreement'),
    'E: disagreement is rendered on the detail face (not a silent model field)')
  ok(!ui.includes('co.green === true'), 'E: the old predicate is gone from the UI too')

  // Shipped bundle carries the new reader (plumbing guard: a source-only fix
  // renders nothing on the console the host opens).
  for (const out of ['lib/client.js', 'lib/client.cjs']) {
    const p = join(repo, 'server/plugins/workbench', out)
    if (!existsSync(p)) { ok(false, `E: shipped bundle present (${out})`); continue }
    const bundle = readFileSync(p, 'utf8')
    ok(bundle.includes('unnamed check') && bundle.includes('checks-verdict-disagreement'),
      `E: ${out} carries the new reader + disagreement notice (bundle rebuilt)`)
  }
}

console.log(`\nt261028-46-check-detail-shapes: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
