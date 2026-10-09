/**
 * sc_face_coverage_panel_face.mjs — the panel Inspection face NAMES a period x
 * face gap instead of making the reader count rows (t261009-49,
 * KI-01M4GGFXPAHDGSQ9767VMB5NGM).
 *
 * Grey-box L3, offline seconds, zero docker/Temporal/browser, never touches
 * 3099/7233. Judged through the PUBLIC pure view module
 * server/plugins/executor-panel/src/host/inspection-coverage.ts (imported by
 * path, like the sibling panel scenarios) — never private helpers.
 *
 * Legs:
 *  P1 the five states each carry their own copy; 'ran but produced nothing'
 *     and 'there was nothing to report' never share a word.
 *  P2 a `failed` row renders a named block: period, face id, last-ok period or
 *     the explicit word never, and the attempt evidence when one exists.
 *  P3 a blocked-shell payload never renders as produced.
 *  P4 an unknown terminal state on the payload renders 'state unknown' — the
 *     client never re-derives a ticket terminal state (spec item 5).
 *  P5 the archive payload is untrusted external input: malformed/missing
 *     fields degrade to named copy, no throw, no fabrication.
 *
 * Module not landed = FAIL named (pre-implementation TDD red expected);
 * node missing or the client tree absent = ENV_FAIL exit 2.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const MODULE = path.join(here, '..', '..', 'server', 'plugins', 'executor-panel',
  'src', 'host', 'inspection-coverage.ts')

let n = 0
const bad = []
const ok = (cond, name) => { n += 1; console.log((cond ? 'ok   ' : 'FAIL ') + name); if (!cond) bad.push(name) }

if (!process.versions?.node) { console.log('ENV_FAIL node missing'); process.exit(2) }
if (!fs.existsSync(path.join(here, '..', '..', 'server', 'plugins', 'executor-panel', 'src', 'host'))) {
  console.log('ENV_FAIL client tree missing')
  process.exit(2)
}
if (!fs.existsSync(MODULE)) {
  console.log('FAIL named: inspection-coverage.ts not landed yet ' +
    '(pre-implementation TDD red is expected at design stage)')
  process.exit(1)
}

let mod
try {
  mod = await import(MODULE)
} catch (e) {
  console.log('FAIL named: module present but unimportable: ' + e.message)
  process.exit(1)
}

const states = ['produced', 'blocked', 'failed', 'not_run', 'unreadable']
const copies = mod.COVERAGE_COPIES || mod.COPIES || null
if (copies) {
  const words = states.map((s) => JSON.stringify(copies[s] ?? copies[s.replace('_', '-')] ?? ''))
  ok(new Set(words).size === states.length,
    'P1 each of the five states has its own copy')
  const nothing = JSON.stringify(copies).toLowerCase()
  ok(!((copies.produced || '').match(/nothing|no report|never ran/i)),
    'P1 produced copy never borrows the nothing/never vocabulary')
  ok((copies.not_run || '').toLowerCase().includes('no attempt') ||
     (copies.not_run || '').toLowerCase().includes('never ran') ||
     (copies.not_run || '').toLowerCase().includes('nothing'),
    'P1 not_run copy says there was nothing to report')
  ok((copies.failed || '').match(/nothing|no result|failed/i) &&
     JSON.stringify(copies.failed) !== JSON.stringify(copies.not_run),
    'P1 failed copy says attempted but produced nothing, distinct from not_run')
}

// P2/P3/P4 through the public render face (discovered by contract name, so a
// keeping refactor stays green).
const render = mod.buildCoverage || mod.buildCoverageCore || null
if (typeof render !== 'function') {
  ok(false, 'P2 no public coverage build face exported (buildCoverage-family)')
} else {
  const core = render === mod.buildCoverageCore
    ? (p, i, a) => mod.buildCoverageCore(p, i, a, mod.COVERAGE_COPIES
        ? { COPIES: mod.COVERAGE_COPIES, FACES: {}, ATTEMPT_CAP: 5 } : mod.COVERAGE_COPIES)
    : render
  const periods = [
    { period: '20260918', reports: {} },
    { period: '20261002', reports: {} },
    { period: '20261008', reports: {} },
    { period: '20261009', reports: { 'integration-tests': { ok: true, report: { findings: [{ id: 'f1' }] } } } },
  ]
  const attempts = {
    'integration-tests/20260918': [{ ticket_id: 't260918-01', state: 'FAILED', blocked_reason: '' }],
    'integration-tests/20261008': [{ ticket_id: 't261008-09', state: '', blocked_reason: '' }],
  }
  const view = core(periods, ['integration-tests'], attempts)
  const byPeriod = {}
  for (const r of view.rows) byPeriod[r.period] = r
  const f = byPeriod['20260918'] || {}
  ok(f.result === 'failed' && /never/i.test(f.copy || '') &&
     /t260918-01/.test(JSON.stringify(f.attempts || [])),
    'P2 failed row names period, never, and the attempt ticket')
  ok((view.block?.lines || []).some((l) => l.includes('20260918') &&
     l.includes('integration-tests') && l.includes('t260918-01')),
    'P2 the produced-nothing block carries a NAMED line (period, face, evidence) — no counting')
  periods[1].reports['integration-tests'] = { ok: true,
    report: { ticket_id: 't261002-12', blocked_reason: 'inspect parse refused', findings: [] } }
  const view2 = core(periods, ['integration-tests'], attempts)
  const b2 = (view2.rows || []).find((r) => r.period === '20261002') || {}
  const b2txt = JSON.stringify(b2) + JSON.stringify(view2.block || {})
  ok(b2.result === 'blocked' && b2.result !== 'produced' &&
     /parse refused/.test(b2txt),
    'P3 blocked shell renders as blocked with its reason (evidence/named line), never produced')
  const viewU = core(periods, ['integration-tests'], attempts)
  const u = (viewU.rows || []).find((r) => r.period === '20261008') || {}
  const uTxt = JSON.stringify(u) + JSON.stringify(viewU.block || {})
  ok(/unknown/i.test(uTxt),
    'P4 unknown terminal state renders as unknown (named line), never re-derived')
}

// P5 malformed payloads degrade, no throw, no fabrication.
const renderP5 = mod.buildCoverage || null
if (typeof renderP5 === 'function') {
  for (const junk of [null, 'x', [{ period: 7 }], [{ period: '20261009', reports: null }],
    [{ period: '20261009', reports: { p: { ok: 'yes' } } }]]) {
    try {
      const out = renderP5(/** @type {any} */ (junk), ['integration-tests'], null)
      ok(true, 'P5 malformed payload degrades without throw: ' + JSON.stringify(junk))
      ok(!JSON.stringify(out ?? '').includes('undefined'),
        'P5 no fabricated output for ' + JSON.stringify(junk))
    } catch (e) {
      ok(false, 'P5 threw on ' + JSON.stringify(junk) + ': ' + e.message)
    }
  }
}

console.log('SCENARIOS t261009-49-face-coverage-panel-face: %d checks, %d failed',
  n, bad.length)
process.exit(bad.length ? 1 : 0)
