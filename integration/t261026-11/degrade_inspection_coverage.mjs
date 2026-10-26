/**
 * degrade_inspection_coverage.mjs — the degrade matrix on the panel
 * inspection-coverage table (t261026-11). Face under judgement:
 * buildCoverageCore over the real archive payload chain.
 *
 * The real payload is the archive's own reading: real record rows through the
 * REAL recordsToAttempts producer function, and real period reports in the
 * reader's own ok/fail slot shape (the t261009-49 archive contract). The
 * checked-in fixture rows carry their capture source; regen_coverage_rows.mjs
 * re-captures them from a live project store when one is reachable.
 *
 * The template's first live run (host report 261026) scored this face 10/10;
 * registration in run_scenarios.py keeps that pin on every line round.
 *
 * Run: node integration/t261026-11/degrade_inspection_coverage.mjs
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { runDegradeMatrix } from '../lib_degrade_matrix.mjs'

const here = new URL('.', import.meta.url).pathname
const COV = new URL('../../server/plugins/executor-panel/src/host/inspection-coverage.ts', import.meta.url).pathname
const cov = await import(COV)

const TABLES = { COPIES: cov.COVERAGE_COPIES, FACES: {}, ATTEMPT_CAP: 5 }

// The real payload: fixture rows (archive capture, provenance in
// fixtures/README.md) through the REAL recordsToAttempts, plus period
// reports in the reader's own slot shape. Not a hand-written view model.
const fixture = JSON.parse(readFileSync(here + 'fixtures/coverage-real.json', 'utf8'))
const real = {
  periods: fixture.periods,
  instances: fixture.instances,
  rows: fixture.rows,
}

const r = runDegradeMatrix({
  face: 'inspection-coverage',
  // Faithful adapter: exactly the arguments buildCoverage itself passes.
  call: (payload) => cov.buildCoverageCore(
    payload === null || payload === undefined || payload === 'UNREADABLE' ? payload : payload.periods,
    payload && typeof payload === 'object' ? payload.instances : payload,
    cov.recordsToAttempts(payload && typeof payload === 'object' ? payload.rows : payload),
    TABLES,
  ),
  real,
  copiesKey: 'copy',
  expect: (out) => ({
    // The face's promise on the real archive payload: period x instance rows,
    // each row speaking its state in its own copy word.
    rows_read: Array.isArray(out?.rows) && out.rows.length >= 4,
    produced_named: (out?.rows ?? []).some((r) => r?.result === 'produced' && typeof r?.copy === 'string' && r.copy.length > 12),
    unreadable_named: (out?.rows ?? []).some((r) => r?.result === 'unreadable' && typeof r?.copy === 'string' && r.copy.length > 12),
  }),
})

process.exit(r.ok ? 0 : 1)
