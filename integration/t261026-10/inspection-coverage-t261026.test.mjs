/**
 * inspection-coverage-t261026.test.mjs — t261026-10 additions to the coverage view
 * (host report 261026 defects B and C). Imports the pure module from the panel src;
 * zero DOM, zero io, zero network.
 *
 * Pins:
 *  - ticketRowsToAttempts (defect C): the inspection TICKET BOARD rows become the
 *    per (instance/period) attempts map — ticket id, engine status/stage words
 *    verbatim, blocked_reason; malformed input degrades (null / rows dropped, no
 *    throw); a row from ANOTHER project is dropped (review C1) while a row without a
 *    project field (pre-t260915-20 historical shape) is kept;
 *  - the attempts degrade copy names the source it could not read (the ticket board
 *    route), and rendering with attempts present flips a not_run slot to failed with
 *    ticket evidence instead of 'no attempt recorded';
 *  - defect B: a declared FACES map drives the row's face id; an unknown instance
 *    still reads the named 'decl-unreadable' marker.
 */
import assert from 'node:assert/strict'
import {
  buildCoverageCore, COVERAGE_COPIES, recordsToAttempts, ticketRowsToAttempts,
} from '../../server/plugins/executor-panel/src/host/inspection-coverage.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

const T = (faces) => ({ COPIES: COVERAGE_COPIES, FACES: faces, ATTEMPT_CAP: 5 })
const slotOk = (report) => ({ ok: true, report })
const periodEntry = (period, reports) => ({ period, reports })

// ---- ticketRowsToAttempts: happy path ----
const rows = [
  { id: 't1', instance: 'integration-tests', period: '20261026', status: 'closed', stage_state: 'close', project: 'sandbar' },
  { id: 't2', instance: 'integration-tests', period: '20261025', status: 'running', stage_state: 'inspect', blocked_reason: 'inspect stage refused the report', project: 'sandbar' },
]
const m1 = ticketRowsToAttempts(rows, 'sandbar')
ok(m1 !== null, 'board rows: attributable rows build a map')
const a1 = m1['integration-tests/20261026']
ok(Array.isArray(a1) && a1.length === 1, 'board rows: one attempt per (instance/period)')
ok(a1[0].ticket_id === 't1', 'board rows: ticket id from the row id')
ok(a1[0].state === 'close', 'board rows: engine stage words verbatim (stage_state wins)')
ok(a1[0].blocked_reason === '', 'board rows: no invented blocked reason')
ok(m1['integration-tests/20261025'][0].blocked_reason === 'inspect stage refused the report',
  'board rows: blocked reason carried verbatim')

// ---- ticketRowsToAttempts: project scope (review C1) ----
const m2 = ticketRowsToAttempts([
  { id: 'x1', instance: 'integration-tests', period: '20261026', project: 'other-project' },
  { id: 'x2', instance: 'integration-tests', period: '20261026', project: 'sandbar' },
], 'sandbar')
ok(m2['integration-tests/20261026'].length === 1 && m2['integration-tests/20261026'][0].ticket_id === 'x2',
  'board rows: another project\'s same-named instance is dropped')
const m3 = ticketRowsToAttempts([
  { id: 'x3', instance: 'docs-sync', period: '20260908', status: 'closed' },
], 'sandbar')
ok(m3 !== null && m3['docs-sync/20260908'][0].ticket_id === 'x3',
  'board rows: a row without a project field (historical shape) is kept')

// ---- ticketRowsToAttempts: malformed inputs (untrusted payload) ----
ok(ticketRowsToAttempts(null, 'sandbar') === null, 'malformed: null rows -> null')
ok(ticketRowsToAttempts('nope', 'sandbar') === null, 'malformed: non-array -> null')
ok(ticketRowsToAttempts([], 'sandbar') === null, 'malformed: empty array -> null')
ok(ticketRowsToAttempts([null, 42, { instance: 'i' }, { period: '20261026' }, {}], 'sandbar') === null,
  'malformed: junk rows are not attributable -> null (no fabricated cell)')
const m4 = ticketRowsToAttempts([
  { instance: 'docs-sync', period: '20260908' },
  'junk',
  { id: '', instance_id: 'docs-sync', period: '20260909' },
], 'sandbar')
ok(m4 !== null && m4['docs-sync/20260908'][0].ticket_id === '' && m4['docs-sync/20260908'][0].state === '',
  'malformed: a row without an id still counts, empty strings never invented words')

// ---- recordsToAttempts untouched (regression guard) ----
ok(recordsToAttempts([{ instance: 'i', period: '20261026', reason: 'r', spawn: { ticket_id: 't9' } }]) !== null,
  'regression: trigger-record adapter still builds its map')

// ---- defect B: declared faces drive the row face id ----
const periods = [
  periodEntry('20261026', { 'docs-sync': slotOk({ findings: [] }) }),
]
const cov1 = buildCoverageCore(periods, ['docs-sync', 'stage-capacity'], null, T({ 'docs-sync': 'doc', 'stage-capacity': 'stage' }))
const rowDoc = cov1.rows.find((r) => r.instance === 'docs-sync')
ok(rowDoc.face === 'doc', 'defect B: the declared scan_face is the row face id')
ok(!cov1.block.lines.some((l) => l.includes('decl-unreadable')), 'defect B: no decl-unreadable when the declaration is served')
ok(rowDoc.result === 'produced' && rowDoc.copy === COVERAGE_COPIES.produced, 'a real report reads produced')
const rowStage = cov1.rows.find((r) => r.instance === 'stage-capacity')
ok(rowStage.face === 'stage' && rowStage.result === 'not_run', 'declared instance with zero reports still lists its declared face')

// ---- defect B: unknown instance still reads the named marker ----
const cov2 = buildCoverageCore(periods, ['ghost'], null, T({ 'docs-sync': 'doc' }))
ok(cov2.rows[0].face === 'decl-unreadable', 'defect B: unknown instance reads the named decl-unreadable marker')

// ---- defect C: board attempts flip not_run to failed with evidence ----
const emptyPeriods = [periodEntry('20261025', {}), periodEntry('20261026', {})]
const attempts = ticketRowsToAttempts([rows[1]], 'sandbar') // only 20261025 has a ticket
const cov3 = buildCoverageCore(emptyPeriods, ['integration-tests'], attempts, T({}))
const failed = cov3.rows.find((r) => r.period === '20261025')
ok(failed.result === 'failed' && failed.attempts[0].ticket_id === 't2',
  'defect C: a period with a real ticket reads failed with ticket evidence')
ok(cov3.block.lines.some((l) => l.includes('t2 (inspect: inspect stage refused the report)')),
  'defect C: the named line carries the ticket id, state and blocked reason')
const notRun = cov3.rows.find((r) => r.period === '20261026')
ok(notRun.result === 'not_run' && !notRun.copy.includes('unavailable'),
  'defect C: with the board readable, a genuinely empty period is plain not_run (no unavailable copy)')
ok(!cov3.attempts_available === false, 'defect C: attempts_available true when the board rows arrived')

// ---- defect C: the degrade copy names the source ----
const cov4 = buildCoverageCore(emptyPeriods, ['integration-tests'], null, T({}))
ok(cov4.attempts_available === false, 'both sources unavailable -> the named degrade')
ok(cov4.rows.every((r) => r.attempts_unavailable === true), 'degrade: every missing slot is attempts_unavailable')
ok(/inspection\/tickets/.test(COVERAGE_COPIES.attempts_unavailable),
  'degrade: the unavailable copy names the ticket-board source it could not read')
ok(cov4.block.lines.some((l) => l.includes('no attempt recorded')),
  'degrade: the line still names that no attempt was recorded')

console.log(`inspection-coverage-t261026: ${n} assertions ok`)
