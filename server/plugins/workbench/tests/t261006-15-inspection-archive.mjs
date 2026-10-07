/**
 * t261006-15-inspection-archive.mjs — inspection period archive model tests (workbench side).
 *  - explicit descending numeric sort — includes the numeric-object-key regression;
 *  - which periods exist is decided by the archive (no date arithmetic, no placeholders);
 *  - merge: adjacency over the declared sequence — consecutive no-report periods merge with a span label (per-period data kept);
 *    report-less periods separated by a reported period stay separate; calendar gaps create neither items nor merges;
 *  - fail-closed: absent dir / empty archive / over-cap not parsed / bad JSON / hidden count;
 *  - single period+instance report fetch: double whitelist + the same failure face.
 * Zero network, never touches 3099 (the reader runs on real fs inside this test's tmp dir).
 */
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  sortPeriodsDesc, buildArchiveItems, readInspectionArchive, readPeriodReport,
  ARCHIVE_FILE_RE,
} from '../src/host/inspection-archive.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- sortPeriodsDesc: explicit descending + the numeric-key regression ----
ok(JSON.stringify(sortPeriodsDesc(['20261004', '20260928', '20261001'])) ===
  JSON.stringify(['20261004', '20261001', '20260928']), 'explicit descending numeric sort')
// Regression (mock bug): numeric-looking object keys enumerate ASCENDING in JS.
const keyObj = { '20260928': 1, '20261004': 2, '20261001': 3 }
const enumerated = Object.keys(keyObj) // ['20260928','20261001','20261004'] — oldest first
ok(enumerated[0] === '20260928', 'precondition: JS enumerates numeric keys ascending (the mock bug)')
ok(sortPeriodsDesc(enumerated)[0] === '20261004', 'model sort never inherits enumeration order')

// ---- buildArchiveItems: merge over the declared sequence, adjacency only ----
const P = (period, anyReport) => ({ period, any_report: anyReport, reports: {} })
let items = buildArchiveItems([P('20261004', true), P('20261003', false), P('20261002', false), P('20261001', true)])
ok(items.length === 3, 'consecutive no-report periods merge into one item')
ok(items[1].kind === 'no-report-run' && items[1].count === 2, 'merged run carries its count')
ok(items[1].label === '20261003–20261002 · 2 without a report', 'merged run label names the span')
ok(items[1].periods.length === 2 && items[1].periods[0].period === '20261003', 'merged item keeps per-period data (merge never erases)')

// Non-adjacent no-report periods (separated by a reported period) stay separate.
items = buildArchiveItems([P('20261004', true), P('20261003', false), P('20261002', true), P('20261001', false)])
ok(items.filter(i => i.kind === 'no-report-run').length === 2, 'a reported period between gaps keeps the gaps separate')

// Calendar gaps alone never create items or merges (which periods exist = the archive).
items = buildArchiveItems([P('20261004', true), P('20260928', true)])
ok(items.length === 2 && items.every(i => i.kind === 'period'), 'no date arithmetic: only archived periods exist')

// Single missing period stays its own item with the (no report) label.
items = buildArchiveItems([P('20261004', false)])
ok(items.length === 1 && items[0].kind === 'no-report-run' && items[0].label === '20261004 · (no report)', 'single missing period keeps its own item')

// A no-report period adjacent to nothing at the head still merges backwards into one run.
items = buildArchiveItems([P('20261004', false), P('20261003', false), P('20261002', true)])
ok(items[0].kind === 'no-report-run' && items[0].count === 2, 'head run merges too')

// ---- readInspectionArchive (real fs under a tmp dir) ----
const dir = mkdtempSync(join(tmpdir(), 'insp-archive-'))
try {
  // Directory absent -> ok:false, human reason, not an error.
  let r = await readInspectionArchive(join(dir, 'missing'))
  ok(r.ok === false && /does not exist/.test(r.reason), 'absent archive is a named empty state')

  mkdirSync(join(dir, 'out', 'inspection'), { recursive: true })
  const arc = join(dir, 'out', 'inspection')
  // Empty archive (nothing matching the whitelist) -> ok:false named.
  r = await readInspectionArchive(arc)
  ok(r.ok === false && /matched nothing/.test(r.reason), 'empty archive is a named empty state')

  writeFileSync(join(arc, 'inspection-integration-tests-20261004.json'), JSON.stringify({ findings: { high: 1, med: 2, low: 3 } }))
  writeFileSync(join(arc, 'inspection-integration-tests-20261001.json'), '{broken')
  writeFileSync(join(arc, 'inspection-simplify-20261004.json'), JSON.stringify({ findings: { high: 0, med: 0, low: 1 } }))
  writeFileSync(join(arc, 'inspection-simplify-20261003.json'), 'x'.repeat(300 * 1024)) // over cap
  writeFileSync(join(arc, 'unrelated.txt'), 'noise')
  writeFileSync(join(arc, 'inspection-BAD_INSTANCE-20261002.json'), '{}') // whitelist: instance shape

  r = await readInspectionArchive(arc)
  ok(r.ok === true, 'archive reads ok')
  ok(r.instances.join(',') === 'integration-tests,simplify', 'instances sorted')
  ok(r.periods.map(p => p.period).join(',') === '20261004,20261003,20261001', 'periods explicit descending, archive decides which exist')
  ok(r.periods[0].any_report === true && r.periods[1].any_report === false && r.periods[2].any_report === false, 'any_report per period')
  ok(r.periods[0].reports['integration-tests'].ok === true, 'good report parses')
  ok(r.periods[2].reports['integration-tests'].ok === false && /not JSON/.test(r.periods[2].reports['integration-tests'].reason), 'broken JSON = named slot failure, unreadable counted')
  ok(r.unreadable_files === 2, 'unreadable files counted (broken json + over-cap)')
  ok(r.hidden_files === 2, 'whitelist-external files counted, never read')
  ok(r.items[0].kind === 'period' && r.items[1].kind === 'no-report-run' && r.items[1].count === 2, 'merged view over real archive')
  ok(ARCHIVE_FILE_RE.test('inspection-integration-tests-20261004.json'), 'whitelist accepts well-formed names')
  ok(!ARCHIVE_FILE_RE.test('inspection-BAD_INSTANCE-20261002.json'), 'whitelist rejects bad instance shape')

  // ---- readPeriodReport: double whitelist + fail-closed ----
  let s = await readPeriodReport(arc, 'integration-tests', '20261004')
  ok(s.ok === true && s.report.findings.high === 1, 'single report fetch parses')
  s = await readPeriodReport(arc, 'integration-tests', '20261003')
  ok(s.ok === false && /not available/.test(s.reason), 'absent period report named')
  s = await readPeriodReport(arc, 'integration-tests', '2026103')
  ok(s.ok === false && /invalid/.test(s.reason), 'bad period shape named')
  s = await readPeriodReport(arc, '../etc', '20261004')
  ok(s.ok === false && /invalid/.test(s.reason), 'path escape via instance named and refused')
  s = await readPeriodReport(arc, 'simplify', '20261003')
  ok(s.ok === false && /read cap/.test(s.reason), 'over-cap report not parsed')
} finally {
  rmSync(dir, { recursive: true, force: true })
}

console.log(`t261006-15-inspection-archive: ${n} checks passed`)
