/**
 * tests/t261028-48-receipt-shape-faces.mjs — the receipt-row family sweep.
 *
 * Root cause (t261028-48; host methodology 260907 — one reported symptom is a
 * SAMPLE, the same mechanism must be classified on every face): t261028-46
 * taught the Check-details face to read the engine's TWO receipt-row shapes,
 * but three other readers still assumed one:
 *
 *   - problems-model.rowsFromChecks (D2Problems): `co.green === true` +
 *     `item || id` → on a RED script gate it listed EVERY row (green ones
 *     included) as "merge_check red: check #i", naming none of them;
 *   - ticket-detail-column-model.receiptRows (Receipts box): counted only
 *     `green === true` → a fully green script gate read "0 of 3 green";
 *   - lane-map.tsx ChecksDetail: rendered no slot for the `count` / `note`
 *     the view now carries → engine words carried and thrown away.
 *
 * Every one of them now goes through the ONE accessor in lane-map-model
 * (`receiptRowView` / `receiptRowViews` / `readGateRunVerdict`).
 *
 * Run: node server/plugins/workbench/tests/t261028-48-receipt-shape-faces.mjs
 * Covers:
 *   A. ANTI-PROOF: today's two private predicates, re-expressed verbatim,
 *      misread the real script shape (Problems lists a GREEN row and names
 *      nothing; the column says 0 of 3). The shared accessor does not.
 *   B. Problems face: both shapes (green script row never a problem row, red
 *      one named from `check` + detail/count; agent rows unchanged).
 *   C. Receipts column: both shapes count greens through the accessor, and it
 *      agrees with the Check-details rows for the same receipt.
 *   D. Lane map face: count/note are carried by the model AND rendered by the
 *      component (source anchors — no silent drop).
 *   E. ONE accessor: no reader keeps a private copy of the verdict/name rule
 *      (source scan over src/client); run-verdict reading is shared too.
 *   F. Malformed / absent faces: no throw, nothing invented, nothing blank.
 *
 * Pure-function + source/bundle text assertions only: no console, no port
 * 3099, no integration run.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gateProblemRows } from '../src/client/problems-model.ts'
import { receiptRows } from '../src/client/ticket-detail-column-model.ts'
import {
  buildChecksDetail, receiptRowView, receiptRowViews, readGateRunVerdict,
} from '../src/client/lane-map-model.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = (() => {
  let d = here
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('repo root not found')
})()
const clientDir = join(repo, 'server/plugins/workbench/src/client')
const readClient = (f) => readFileSync(join(clientDir, f), 'utf8')

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── Real receipt shapes (verbatim keys, measured on live faces) ── */

// verify_lane code / cs-machine-qc: SCRIPT gate rows {check, level, count[, note, items]}
const SCRIPT_GREEN = {
  stage: 'cs-machine-qc', label: 'cs_machine_qc contract（溯源校验＋契约校验固定项）',
  green: true, red_count: 0, exit_code: 0,
  checks: [
    { check: '溯源校验（checkpoint 可指回内容源位置）', level: 'green', count: 0 },
    { check: '契约校验（四件套/定位符）', level: 'green', count: 0 },
    { check: '契约校验（类型分布合理）', level: 'green', count: 0 },
  ],
}
const SCRIPT_RED = {
  stage: 'cs-machine-qc', label: 'cs_machine_qc contract（溯源校验＋契约校验固定项）',
  green: false, red_count: 2, exit_code: 1,
  checks: [
    { check: '输入形状', level: 'red', count: 2, note: 'units 缺失或非列表' },
    { check: '溯源校验（checkpoint 可指回内容源位置）', level: 'green', count: 0 },
    { check: '契约校验（四件套/定位符）', level: 'green', count: 0 },
  ],
}
// A script gate whose RUN row writes `level` instead of `green` (same family).
const SCRIPT_RUN_LEVEL_RED = {
  stage: 'verify_lane', label: 'verify_lane code',
  level: 'red', red_count: 1, exit_code: 1,
  checks: [
    { check: '写集白名单', level: 'red', count: 1 },
    { check: 'lint', level: 'green', count: 0 },
  ],
}
// merge_check: AGENT gate rows {item, green, id, detail, reason_code, files, next_action}
const AGENT_RED = {
  stage: 'merge_check', label: 'merge_check（程序化检查）', green: false, red_count: 1, exit_code: 0,
  checks: [
    { item: 'Lane branch has commits', green: true, id: 'lane_commits', detail: '3 commits' },
    { item: 'In-lane verify_lane code is green', green: false, id: 'verify_lane_code',
      detail: 'exit=1 red=1', reason_code: 'verify_red', files: ['server/z.py'],
      next_action: 'fix the red item then retry_qc' },
  ],
}
const detailOf = (...runs) => ({ status: 'running', stage_state: 'blocked', gate_runs: runs })

/* ── A. ANTI-PROOF: today's private predicates on the real script shape ── */

// The Problems predicate exactly as it stood (problems-model.ts:47-50 before
// this ticket): green only when `green === true`, name only from item/id.
const oldProblems = (checks) => checks
  .map((co, i) => {
    if (co === null || typeof co !== 'object') return null
    if (co.green === true) return null
    const item = co.item || co.id || `check #${i}`
    return { text: `merge_check red: ${item}`, dim: co.detail }
  })
  .filter(Boolean)

// The Receipts predicate exactly as it stood (ticket-detail-column-model.ts:118).
const oldReceiptCount = (checks) =>
  checks.filter((c) => c !== null && typeof c === 'object' && c.green === true).length

{
  const oldRows = oldProblems(SCRIPT_RED.checks)
  ok(oldRows.length === 3,
    'A: anti-proof — the old Problems predicate lists ALL 3 script rows on a red script gate (the 2 green ones included)')
  ok(oldRows.every(r => /^merge_check red: check #\d$/.test(r.text)),
    'A: anti-proof — and names none of them (no `item`, no `check`, only "check #i")')
  ok(oldRows.every(r => r.dim === undefined),
    'A: anti-proof — and carries no detail (script rows have `note`/`count`, not `detail`)')
  ok(oldRows.every(r => r.text.includes('merge_check') && !r.text.includes('cs-machine-qc')),
    'A: anti-proof — and mislabels a cs-machine-qc gate as merge_check')

  const newRows = gateProblemRows(detailOf(SCRIPT_RED))
  ok(newRows.length === 1, 'A: fixed — the same red script gate yields exactly ONE problem row')
  ok(newRows[0].text === 'cs-machine-qc red: 输入形状',
    'A: fixed — the red row is named from `check` and prefixed by its own stage id')
  ok(newRows[0].dim === 'units 缺失或非列表', 'A: fixed — the row carries the engine note (data untranslated)')
  const blob = newRows.map(r => r.text + ' ' + (r.dim ?? '')).join(' | ')
  ok(!blob.includes('溯源校验') && !blob.includes('契约校验'),
    'A: fixed — the GREEN script rows are NOT listed in the Problems area')

  const oldGreen = oldReceiptCount(SCRIPT_GREEN.checks)
  ok(oldGreen === 0, 'A: anti-proof — the old Receipts predicate counts 0 green on a fully green script gate')
  ok(`${oldGreen} of ${SCRIPT_GREEN.checks.length} green` === '0 of 3 green',
    'A: anti-proof — so the column reads "0 of 3 green" today')
  const newCol = receiptRows([SCRIPT_GREEN])
  ok(newCol[0].v === '3 of 3 green', 'A: fixed — the same receipt reads "3 of 3 green"')
}

/* ── B. Problems face: both shapes, and the run verdict through the reader ── */
{
  // Red script gate.
  const rows = gateProblemRows(detailOf(SCRIPT_RED))
  ok(rows.length === 1 && rows[0].key === 'check-0-输入形状',
    'B: script shape — one row, keyed by the red row only')
  ok(rows[0].text === 'cs-machine-qc red: 输入形状', 'B: script shape — text names the failing check')
  // Green script gate: no problems at all (not even a fallback row).
  ok(gateProblemRows(detailOf(SCRIPT_GREEN)).length === 0, 'B: script shape — a green script gate yields no rows')

  // A red script row without a note carries its `count` instead of nothing.
  const countOnly = gateProblemRows(detailOf({
    stage: 'verify_lane', label: 'verify_lane code', green: false, red_count: 1,
    checks: [{ check: '写集白名单', level: 'red', count: 2 }, { check: 'lint', level: 'green', count: 0 }],
  }))
  ok(countOnly.length === 1 && countOnly[0].dim === 'count 2',
    'B: script shape — a red row with no note carries `count N` (engine field name, no invented wording)')

  // Run verdict written as `level` (script-gate run row): shared reader sees it.
  const lv = gateProblemRows(detailOf(SCRIPT_RUN_LEVEL_RED))
  ok(lv.length === 1 && lv[0].text === 'verify_lane red: 写集白名单',
    'B: run verdict from `level` is read through the shared reader (no private `green === false` test)')
  // No written verdict: the row evidence decides.
  const rowsDecide = gateProblemRows(detailOf({
    stage: 's', label: 'gate S', checks: [{ check: 'c1', level: 'red', count: 1 }],
  }))
  ok(rowsDecide.length === 1 && rowsDecide[0].text === 's red: c1',
    'B: no written run verdict → the red row decides (still named)')
  ok(gateProblemRows(detailOf({ stage: 's', label: 'gate S', checks: [{ check: 'c1', level: 'green', count: 0 }] })).length === 0,
    'B: no written run verdict + all-green rows → no problem row')

  // Agent/human shape: unchanged rendering (item, detail).
  const agent = gateProblemRows(detailOf(AGENT_RED))
  ok(agent.length === 1 && agent[0].text === 'merge_check red: In-lane verify_lane code is green',
    'B: agent shape — one row, named by `item`, prefixed by the gate stage')
  ok(agent[0].dim === 'exit=1 red=1', 'B: agent shape — detail in the dim half (unchanged)')

  // Light gate (no checks array): unchanged field-based rows.
  const light = gateProblemRows(detailOf({ stage: 'run_integration_tests', label: 'machine gate',
    green: false, red_count: 2, exit_code: 1, counts: { ran: 12, failed: 2 }, error: 'boom' }))
  ok(light.some(r => r.text === 'gate error: boom') && light.some(r => r.text.includes('ran=12'))
    && light.some(r => r.text.includes('2 red item(s)')),
    'B: light gate (no checks key) keeps its field rows')

  // Scalar-only checks under a red gate: fallback names the gate, never blank.
  const scalars = gateProblemRows(detailOf({ stage: 's', label: 'gate S', green: false, checks: ['x', 7, null] }))
  ok(scalars.length === 1 && scalars[0].key === 'no-detail' && scalars[0].text.includes('gate S'),
    'B: scalar-only checks → the no-detail fallback names the gate (nothing silently blank)')
  // Red gate whose rows are all green: the disagreement is not hidden here either.
  const allGreenRed = gateProblemRows(detailOf({ stage: 's', label: 'gate S', green: false,
    checks: [{ check: 'c1', level: 'green', count: 0 }] }))
  ok(allGreenRed.length === 1 && allGreenRed[0].key === 'no-detail',
    'B: red verdict + all-green rows → named fallback (no invented red row)')
}

/* ── C. Receipts column: both shapes, and it agrees with Check details ── */
{
  ok(receiptRows([SCRIPT_GREEN])[0].v === '3 of 3 green', 'C: script shape — fully green gate reads "3 of 3 green"')
  ok(receiptRows([SCRIPT_RED])[0].v === '2 of 3 green', 'C: script shape — 2 of 3 green (one red row)')
  ok(receiptRows([SCRIPT_RUN_LEVEL_RED])[0].v === '1 of 2 green', 'C: script shape — run-level wording does not change row counting')
  ok(receiptRows([AGENT_RED])[0].v === '1 of 2 green', 'C: agent shape — unchanged (1 of 2 green)')
  ok(receiptRows([SCRIPT_GREEN])[0].k === 'cs_machine_qc contract（溯源校验＋契约校验固定项）',
    'C: the row label is the engine label verbatim (untranslated)')

  // Every script row is green → no "env red" row invented.
  ok(receiptRows([SCRIPT_GREEN]).length === 1, 'C: green script gate → no extra rows')
  // Red count still rides along when the face carries it.
  const red = receiptRows([SCRIPT_RED])
  ok(red.some(r => r.k === 'env red' && r.v === '2'), 'C: env red row kept from the face')

  // Cross-face agreement: the column total is the Check-details row count, and
  // the green counts agree for every shape above.
  for (const [name, run] of [['green script', SCRIPT_GREEN], ['red script', SCRIPT_RED],
    ['level-red script', SCRIPT_RUN_LEVEL_RED], ['agent', AGENT_RED]]) {
    const col = receiptRows([run])[0].v
    const views = buildChecksDetail({ gate_runs: [run] })[0].rows
    const expect = `${views.filter(v => v.green).length} of ${views.length} green`
    ok(col === expect, `C: column and Check details agree on the same receipt (${name}: ${col})`)
  }
  ok(receiptRows([{ stage: 'gate', checks: [] }])[0].v === 'no checks recorded',
    'C: no rows → "no checks recorded" (unchanged)')
  ok(receiptRows([{ stage: 'gate', checks: [{ green: true }] }])[0].v === 'no checks recorded',
    'C: a nameless green row is not noise on EITHER face (accessor drops it, column agrees)')
  ok(receiptRows(undefined) === null && receiptRows('nope') === null, 'C: absent/malformed face → null')
}

/* ── D. Lane map face: count / note carried AND rendered ── */
{
  const run = buildChecksDetail(detailOf(SCRIPT_RED))[0]
  const redRow = run.rows[0]
  ok(redRow.count === 2 && redRow.note === 'units 缺失或非列表',
    'D: model — the script row carries count + note (engine words verbatim)')
  ok(redRow.item === '输入形状' && redRow.green === false, 'D: model — the row is named and red')
  const greenRun = buildChecksDetail(detailOf(SCRIPT_GREEN))[0]
  ok(greenRun.rows.every(r => r.count === 0), 'D: model — count 0 is carried, not dropped as falsy')

  const tsx = readClient('lane-map.tsx')
  ok(tsx.includes('wb-ck-count') && tsx.includes('count ${row.count}'),
    'D: component — the count is rendered in the row summary (engine field name)')
  ok(tsx.includes('wb-ck-note') && tsx.includes('row.note'),
    'D: component — the note is rendered (not carried and dropped)')
  ok(tsx.includes('note: {row.note}') && tsx.includes('count: {row.count}'),
    'D: component — the expanded fold repeats the full note/count (a truncated summary is not the only copy)')
  const css = readClient('index.tsx')
  ok(css.includes('.wb-ck-count{') && css.includes('.wb-ck-note{'),
    'D: the two new row slots have declared styles (no unstyled text spill)')
}

/* ── E. ONE accessor: no private copy of the verdict/name rule anywhere ── */
{
  const model = readClient('lane-map-model.ts')
  ok(model.includes('export function receiptRowView'), 'E: the accessor is exported from the model')
  ok(model.includes('export function receiptRowViews'), 'E: the array form is exported (readers share the relevance rule)')
  ok(model.includes('export function readGateRunVerdict'), 'E: the run-verdict reading is exported too')
  ok((model.match(/function receiptRowView\b/g) || []).length === 1,
    'E: the accessor is DEFINED exactly once (no second implementation in the model)')
  ok(model.includes('const rows: CheckRowView[] = receiptRowViews(o.checks)')
    && model.includes('const verdict = readGateRunVerdict(o)'),
    'E: buildChecksDetail itself consumes the accessor (no third copy)')

  const problems = readClient('problems-model.ts')
  ok(problems.includes('./lane-map-model.ts') && problems.includes('receiptRowView(raw)'),
    'E: the Problems reader goes through the shared accessor')
  ok(problems.includes('readGateRunVerdict(g)'),
    'E: the Problems reader judges the gate through the shared run-verdict reader')
  const column = readClient('ticket-detail-column-model.ts')
  ok(column.includes('./lane-map-model.ts') && column.includes('receiptRowViews(last.checks)'),
    'E: the Receipts column goes through the shared accessor')

  // No reader keeps its own verdict/name predicate. The scan judges CODE:
  // the files' prose is allowed to quote the retired predicate (that is how a
  // reader learns what was wrong), comments are stripped first.
  const stripComments = (src) =>
    src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/[^\n]*/g, '')
  for (const f of ['problems-model.ts', 'ticket-detail-column-model.ts', 'lane-map.tsx']) {
    const src = stripComments(readClient(f))
    ok(!src.includes('green === true') && !src.includes("=== 'green'") && !src.includes('=== "green"'),
      `E: ${f} keeps no private green predicate`)
    ok(!src.includes('co.level') && !src.includes('co.item') && !src.includes('co.check'),
      `E: ${f} keeps no private row-name/level copy`)
  }
  // Files that read the verdict field set at all: the model, and nothing else.
  const offenders = readdirSync(clientDir)
    .filter(f => f.endsWith('.ts') || f.endsWith('.tsx'))
    .filter(f => {
      const src = readClient(f)
      return /rowVerdict\(|receiptBool\(|co\.level|\.level === '(green|red)'/.test(src)
    })
    .filter(f => f !== 'lane-map-model.ts')
  ok(offenders.length === 0, `E: no other client file re-implements the receipt-row predicate (${offenders.join(',') || 'none'})`)

  // The retired literals are gone from the code.
  ok(!stripComments(problems).includes('merge_check red:'),
    'E: the hardcoded `merge_check red:` prefix is retired (the gate names itself)')
  ok(!stripComments(column).includes('(c as Record<string, unknown>).green === true'),
    'E: the retired Receipts filter (`.green === true` inline) is gone')

  // Shipped bundles carry the accessor (plumbing guard: a source-only fix
  // renders nothing on the console the host opens).
  for (const out of ['lib/client.js', 'lib/client.cjs']) {
    const p = join(repo, 'server/plugins/workbench', out)
    if (!existsSync(p)) { ok(false, `E: shipped bundle present (${out})`); continue }
    const bundle = readFileSync(p, 'utf8')
    ok(bundle.includes('receiptRowView') && bundle.includes('readGateRunVerdict'),
      `E: ${out} carries the shared accessor (bundle rebuilt)`)
    ok(bundle.includes('wb-ck-note') && bundle.includes('wb-ck-count'),
      `E: ${out} carries the count/note slots (bundle rebuilt)`)
  }
}

/* ── F. Malformed / absent faces ── */
{
  const bad = [undefined, null, 42, 'x', [], {}, { gate_runs: 'no' }, { gate_runs: [] },
    { gate_runs: [null, 7, 'x', {}] }, { gate_runs: [{ stage: 's', checks: 'no' }] },
    { gate_runs: [{ stage: 's', green: false, checks: [null, undefined, true, 'x', 3] }] }]
  for (const b of bad) {
    let threw = false
    try {
      gateProblemRows(b)
      receiptRows(b?.gate_runs)
      buildChecksDetail(b)
    } catch (e) { threw = true; console.error(e) }
    ok(!threw, `F: malformed input does not throw on any of the three faces (${JSON.stringify(b)})`)
  }
  ok(gateProblemRows(undefined).length === 0 && receiptRows(undefined) === null,
    'F: absent faces render nothing')
  ok(receiptRowView(null) === null && receiptRowView(undefined) === null && receiptRowView('') === null,
    'F: the accessor returns null (not a half row) for empty input')
  ok(receiptRowView('plain text').item === 'plain text',
    'F: a scalar row still names something on the accessor')
  ok(receiptRowViews('no').length === 0, 'F: a non-array checks face yields no rows')
  ok(readGateRunVerdict({}).green === undefined && readGateRunVerdict({}).source === 'rows',
    'F: no written verdict → undefined (never an invented green)')
  ok(readGateRunVerdict({ level: 'green' }).source === 'level'
    && readGateRunVerdict({ verdict: 'red' }).green === false
    && readGateRunVerdict({ green: false }).source === 'green',
    'F: run-verdict source is named per field (green → level → verdict → rows)')
  ok(readGateRunVerdict({ green: 'maybe' }).green === undefined,
    'F: an unknown verdict word invents nothing')
}

console.log(`\nt261028-48-receipt-shape-faces: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
