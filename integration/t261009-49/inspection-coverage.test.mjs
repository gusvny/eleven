/**
 * inspection-coverage.test.mjs — period-x-face coverage view tests (t261009-49,
 * KI-01M4GGFXPAHDGSQ9767VMB5NGM). Lives inside the ticket's write set
 * (integration/t261009-49/); imports the pure module from the panel src.
 *
 * Pins:
 *  - the five states (produced / blocked / failed / not_run / unreadable), each with
 *    its own copy — 'ran but produced nothing' and 'there was nothing to report'
 *    never share a word;
 *  - the blocked shell (readable ledger + non-empty blocked_reason) never reads
 *    produced (R2 regression pin, t261002-12 shape);
 *  - last successful period or the explicit 'never';
 *  - zero-attempt vs three-failed-attempts read differently;
 *  - attempts unavailable = the named degraded reading, never a silent fact;
 *  - the payload is untrusted external input: malformed fields degrade, no throw,
 *    no fabrication (malformed-input stubs included).
 * Zero DOM, zero io, zero network.
 */
import assert from 'node:assert/strict'
import {
  buildCoverage, buildCoverageCore, COVERAGE_COPIES, recordsToAttempts,
} from '../../server/plugins/executor-panel/src/host/inspection-coverage.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

const slotOk = (report) => ({ ok: true, report })
const slotFail = (reason) => ({ ok: false, reason })
const periodEntry = (period, reports) => ({ period, reports })

const INSTANCES = ['integration-tests', 'simplify']

// ---- five states over a two-instance, three-period window ----
const periods = [
  periodEntry('20261006', {
    'integration-tests': slotOk({ findings: { high: 0, med: 0, low: 0 }, named: [] }),
    'simplify': slotOk({ findings: [], blocked_reason: 'inspect stage refused the report', ticket_id: 't261002-12' }),
  }),
  periodEntry('20261008', {
    'integration-tests': slotFail('report file unreadable or not JSON: Unexpected token'),
    'simplify': slotOk({ findings: [], blocked_reason: 'refused again', ticket_id: 't261008-17' }),
  }),
]
const attempts = {
  'integration-tests/20261008': [
    { ticket_id: 't261008-09', state: 'FAILED', blocked_reason: '' },
  ],
}
const v = buildCoverage(periods, INSTANCES, attempts)

ok(v.attempts_available === true, 'attempts available when a map is given')
const by = (inst, p) => v.rows.find((r) => r.instance === inst && r.period === p)
ok(by('integration-tests', '20261006').result === 'produced', 'served all-green ledger = produced')
ok(by('integration-tests', '20261006').copy === COVERAGE_COPIES.produced, 'produced copy is the contract copy')
ok(by('simplify', '20261006').result === 'blocked', 'blocked shell is blocked, NEVER produced')
ok(/blocked shell/.test(by('simplify', '20261006').copy), 'blocked copy names the blocked shell')
ok(by('simplify', '20261006').attempts[0].ticket_id === 't261002-12', 'blocked row carries the ledger ticket evidence')
ok(by('integration-tests', '20261008').result === 'unreadable', 'unreadable slot = unreadable (never fine, never missing)')
ok(by('simplify', '20261008').result === 'blocked', 'second blocked shell still blocked')

// last successful period / never
ok(by('simplify', '20261006').last_ok_period === 'never', 'no prior success = the explicit never')
ok(by('simplify', '20261008').last_ok_period === 'never', 'blocked never inherits a success it did not have')
ok(by('integration-tests', '20261008').last_ok_period === '20261006',
  'unreadable row still names the face\'s last success')

// ---- failed vs not_run (different facts) ----
const failRun = buildCoverage(
  [periodEntry('20260918', { 'integration-tests': { ok: false } })],
  ['integration-tests'],
  { 'integration-tests/20260918': [
    { ticket_id: 't260918-01', state: 'FAILED' },
    { ticket_id: 't260919-01', state: 'FAILED' },
    { ticket_id: 't261008-09', state: 'TIMED_OUT' },
  ] })
ok(failRun.rows[0].result === 'failed', 'attempts without a served ledger = failed')
ok(failRun.rows[0].attempts.length === 3, 'all attempt evidence carried on the row')
ok(['t260918-01', 't260919-01', 't261008-09'].every((t) => failRun.block.lines[0].includes(t)),
  'the named line carries every failed ticket id (with its state)')

const notRun = buildCoverage(
  [periodEntry('20260918', { 'integration-tests': { ok: false } })],
  ['integration-tests'], { 'integration-tests/20260918': [] })
ok(notRun.rows[0].result === 'not_run', 'zero attempts = not_run')
ok(/No attempt recorded/.test(notRun.rows[0].copy), 'not_run copy is its own wording')
ok(failRun.rows[0].copy !== notRun.rows[0].copy, 'three failed attempts and zero attempts never read the same')
ok(notRun.rows[0].attempts_unavailable === false, 'an empty attempts list is a known absence, not an unavailable surface')
ok(/never/.test(notRun.block.lines[0]), 'the not_run line names the last success or never')

// ---- attempts unavailable (named degradation, never a silent fact) ----
const noRecords = buildCoverage(
  [periodEntry('20260918', { 'integration-tests': { ok: false } })],
  ['integration-tests'], null)
ok(noRecords.attempts_available === false, 'null map = attempts unavailable')
ok(noRecords.rows[0].result === 'not_run' && noRecords.rows[0].attempts_unavailable === true,
  'a missing slot with no attempt records degrades to the flagged not_run')
ok(noRecords.rows[0].copy.includes(COVERAGE_COPIES.attempts_unavailable.slice(0, 30)),
  'the row says the surface could not check attempts')

// ---- block: produced-nothing lines are visible without counting rows ----
ok(v.block.visible === true, 'the block is visible when something produced nothing')
ok(v.block.lines.length === 3, 'one named line per non-produced period x face (2 blocked + 1 unreadable)')
ok(v.block.lines[0].includes('(face decl-unreadable)'),
  'a missing declared-face entry reads the named decl-unreadable marker, never an invented face id')
const allGreen = buildCoverage(
  [periodEntry('20261006', { 'integration-tests': slotOk({ findings: [] }) })],
  ['integration-tests'], {})
ok(allGreen.block.visible === false, 'an all-produced window shows no block')

// ---- attempt cap ----
const many = buildCoverage(
  [periodEntry('20260918', { i: { ok: false } })], ['i'],
  { 'i/20260918': Array.from({ length: 7 }, (_, k) => ({ ticket_id: `t${k}`, state: 'FAILED' })) },
)
ok(many.block.lines[0].includes('and 2 more attempt(s) not shown'), 'the overflow is counted, not hidden')

// ---- recordsToAttempts (untrusted input) ----
ok(recordsToAttempts(null) === null, 'null rows = no records')
ok(recordsToAttempts('garbage') === null, 'non-array rows = no records')
ok(recordsToAttempts([]) === null, 'empty rows = no records')
ok(recordsToAttempts([{ instance: 'i' }, { period: '20261008' }]) === null,
  'rows without both instance and period are not attributable -> null')
const m = recordsToAttempts([
  { instance: 'integration-tests', period: '20261008', ticket_id: 't261008-09', reason: 'human rerun',
    spawn: { ok: false, error: 'workflow FAILED' } },
  { instance_id: 'simplify', period: '20261008', spawn: { ok: true } },
  'garbage',
  { instance: 'x' },
])
ok(m['integration-tests/20261008'][0].ticket_id === 't261008-09', 'ticket id carried')
ok(m['integration-tests/20261008'][0].state === 'spawn failed', 'a spawn error is the attempt state, verbatim from the record')
ok(m['simplify/20261008'][0].state === COVERAGE_COPIES.unknown_state,
  'no state in the record = the named unknown-state copy (never re-derived)')
ok(m['simplify/20261008'][0].ticket_id === '', 'a record without a ticket id stays empty, never invented')

// ---- malformed payload drill (the view never throws, never fabricates) ----
const weird = buildCoverage(
  [periodEntry('20261008', { 'integration-tests': slotOk('not-an-object') })],
  ['integration-tests'], { 'integration-tests/20261008': 'not-an-array' })
ok(weird.rows[0].result === 'produced', 'a non-object report body still reads produced from the ok slot (no throw)')
const nullSlot = buildCoverage(
  [periodEntry('20261008', { 'integration-tests': null })], ['integration-tests'], null)
ok(nullSlot.rows[0].result === 'not_run' && nullSlot.rows[0].attempts_unavailable === true,
  'a null slot degrades to the flagged not_run')
const badAttempts = buildCoverage(
  [periodEntry('20261008', {})], ['i'],
  { 'i/20261008': ['garbage', null, 42, { ticket_id: 't1', state: 'FAILED' }] })
ok(badAttempts.rows[0].result === 'failed' && badAttempts.rows[0].attempts.length === 1,
  'non-dict attempt entries are dropped, the dict one is kept')

// ---- face id table (declared scan_face; missing = decl-unreadable) ----
const faced = buildCoverageCore(
  [periodEntry('20261008', { i: { ok: false } })], ['i'], null,
  { COPIES: COVERAGE_COPIES, FACES: { i: 'test' }, ATTEMPT_CAP: 5 })
ok(faced.rows[0].face === 'test', 'the declared face id is carried on the row and the line')
ok(faced.block.lines[0].includes('(face test)'), 'the named line names the face id')

// ---- table-parameterised core === module convenience ----
const conv = buildCoverage(periods, INSTANCES, attempts)
ok(JSON.stringify(conv) === JSON.stringify(buildCoverageCore(periods, INSTANCES, attempts,
  { COPIES: COVERAGE_COPIES, FACES: {}, ATTEMPT_CAP: 5 })), 'the convenience wrapper is the core with the real tables')

// ---- run-scoped coverage (t261009-49 rework, gate round 1 Red 1): the merged
// no-report-run face passes ONLY the run's own periods to the core — the far
// period must not leak into the block (t261006-15 §7 adjacency ruling). ----
const runScoped = buildCoverage(
  [periodEntry('20260928', { i: { ok: true, report: {} } })],   // far period, produced
  ['i'], null)
ok(runScoped.block.visible === false,
  'run-scoped window with all-produced periods shows no block (far period never leaks)')
// The page passes ONLY the run's own periods, so the far produced period (20260928)
// is not in the window at all: no line carries it, not even as a last-success cite.
const scoped = buildCoverage(
  [periodEntry('20260929', { i: { ok: false } })],   // the run's own periods only
  ['i'], null)
ok(scoped.block.lines.length === 1 && scoped.block.lines[0].includes('20260929')
   && !JSON.stringify(scoped).includes('20260928'),
  'a scoped block names only the run\'s periods — the far period never leaks, not even as a last-success cite')
ok(/never/.test(scoped.block.lines[0]),
  'with the far period out of scope, the last success reads the explicit never')

console.log(`inspection-coverage.test.mjs: ${n} assertions ok`)
