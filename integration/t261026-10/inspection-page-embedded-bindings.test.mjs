/**
 * inspection-page-embedded-bindings.test.mjs — t261026-10 rework regression lock
 * (arbitration round 3, code-fault).
 *
 * Incident: inspLoad() inside the SERVED page script referenced the module import
 * `COVERAGE_COPIES` bare (`INSP.coverageTables = { COPIES: COVERAGE_COPIES, ... }`).
 * Module imports do not exist in the served page — the fetch .then threw
 * `ReferenceError: COVERAGE_COPIES is not defined`, the catch wiped INSP.archive, and
 * the whole Inspection period row rendered empty on a payload the page rendered fine
 * before (t261006-15-inspection-tab-journey-layout red, merged tree).
 *
 * Lock (source level, seconds, zero browser): in panel-page.ts the identifier
 * `COVERAGE_COPIES` must appear ONLY in the module half (before the PANEL_PAGE_HTML
 * template) — where it is either the import, or the copy source interpolated into the
 * page as data (INSP_COVERAGE_TABLES / INSP_TABLES / RUN_COPIES). Function cores that
 * ARE embedded into the page via String(fn) (buildCoverageCore, recordsToAttempts,
 * ticketRowsToAttempts, ...) must keep their String(...) join entries — a missing join
 * is the same trap one level down (t261021-07 rework note), so the lock also pins each
 * joined name to a String(fn) line.
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const src = readFileSync(join(repo, 'server/plugins/executor-panel/src/host/panel-page.ts'), 'utf8')

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

const marker = 'export const PANEL_PAGE_HTML'
const cut = src.indexOf(marker)
ok(cut > 0, 'panel-page.ts carries the PANEL_PAGE_HTML template marker')
const moduleHalf = src.slice(0, cut)
const pageHalf = src.slice(cut)

// The module binding never leaks into the served page script.
ok(!pageHalf.includes('COVERAGE_COPIES'),
  'lock: COVERAGE_COPIES (a module import) is never referenced inside the served page template')
ok(moduleHalf.includes('COPIES: COVERAGE_COPIES'),
  'lock: the page copy source is interpolated as DATA (INSP_COVERAGE_TABLES) from the module half')

// The embedded cores keep their String(fn) join entries (t261021-07 transitive closure).
for (const fn of ['buildCoverageCore', 'recordsToAttempts', 'ticketRowsToAttempts']) {
  ok(new RegExp(`String\\(${fn}\\)`).test(moduleHalf),
    `lock: ${fn} is joined into the embedded page via String(fn)`)
}

// The defect-B swap reads COPIES from the already-interpolated tables, never bare.
ok(pageHalf.includes('COPIES: INSP.coverageTables.COPIES'),
  'lock: the faces swap takes COPIES from the interpolated default tables')

console.log(`inspection-page-embedded-bindings: ${n} assertions ok`)
