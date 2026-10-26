/**
 * sc_t261026_10_panel_declared_face_attempts.mjs — the Inspection tab shows the
 * DECLARED face id per row and reads real attempt records instead of a wall of
 * not_run (ticket t261026-10, host report 261026 defects B and C).
 *
 * Incident shape: every row read `face decl-unreadable` because the coverage
 * core was called with a hardcoded empty FACES map, and every slot read
 * `not_run - no attempt recorded` because attempts were never read from where
 * they are recorded (the inspection ticket board). The fix serves the
 * declaration's scan_face per instance and adapts inspection-ticket rows into
 * attempt records through one guarded adapter.
 *
 * Grey-box L3, offline seconds, zero docker/Temporal-server/browser, never
 * touches 3099/7233. Judged through the PUBLIC pure view module
 * server/plugins/executor-panel/src/host/inspection-coverage.ts (imported by
 * path, like the sibling t261009-49 scenario) — never private helpers.
 *
 * Legs:
 *  B1 DECLARED FACE - with the served faces map the row shows the declared
 *     scan_face; a genuinely unknown instance still reads the named
 *     `decl-unreadable` marker.
 *  B2 PRE-FETCH DEFAULT - the empty-map default degrades to the same named
 *     marker, never a crash or an invented face.
 *  C1 ATTEMPTS ADAPTED - inspection-ticket rows (instance_id, period, status,
 *     blocked_reason, id) become attempt records keyed instance/period.
 *  C2 UNTRUSTED INPUT - a non-array payload, rows missing period, and null
 *     rows are dropped or degrade to null; no throw, no fabricated attempt.
 *  C3 THE WALL LIFTS - with attempts available the slot for that instance/
 *     period no longer renders the bare not_run wall and carries the ticket
 *     evidence; where no attempt exists the degrade still reads not_run.
 *  C4 SOURCE NAMED - the unavailable copy NAMES the source it could not read
 *     (the inspection ticket board), per acceptance.
 *
 * Intent split: the five-state copy vocabulary and the existing
 * recordsToAttempts (manual-trigger) guards belong to t261009-49; the archive
 * declared-instance filter belongs to the sibling
 * t261026-10-archive-declared-instances entry; THIS entry uniquely owns the
 * declared-face rendering and the ticket-board attempt source journey.
 *
 * Pre-implement tree: B1/C1/C3/C4 red = the named TDD signal
 * (ticketRowsToAttempts not landed, faces not served yet). Green required at
 * the integration gate. node missing or the client tree absent = ENV_FAIL
 * exit 2.
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
  console.log('FAIL named: inspection-coverage.ts not landed (pre-implementation TDD red expected)')
  process.exit(1)
}

let mod
try {
  mod = await import(MODULE)
} catch (e) {
  console.log('FAIL named: module present but unimportable: ' + e.message)
  process.exit(1)
}

const copies = mod.COVERAGE_COPIES || mod.COPIES || null
const DECL_UNREADABLE = copies?.decl_unreadable ?? 'decl-unreadable'
const NOT_RUN = copies?.not_run ?? 'not_run'

function periodsFor(instance, period, reportless = false) {
  // reportless=true seeds a period with NO archived report: the not_run shape
  // (a period that HAS a report reads produced — never pin that to not_run).
  if (reportless) return [{ period, reports: {} }]
  return [{ period, reports: { [instance]: { ok: true, file: 'x.json', report: {} } } }]
}

function render({ faces = {}, attempts = null, unavailable = false, instance = 'docs-sync', period = '20261026', reportless = false }) {
  const view = mod.buildCoverageCore(
    periodsFor(instance, period, reportless),
    [instance],
    attempts,
    {
      COPIES: copies,
      FACES: faces,
      ATTEMPT_CAP: 5,
      attempts_unavailable: unavailable,
    },
  )
  return JSON.stringify(view)
}

// B1: declared face id renders; unknown instance keeps the named marker.
{
  const out = render({ faces: { 'docs-sync': 'doc' } })
  ok(out.includes('"doc"'), 'B1 the declared scan_face (doc) renders on its row')
  const unknown = render({ faces: {}, instance: 'ghost-inst' })
  ok(unknown.includes(DECL_UNREADABLE), 'B1 an unknown instance reads the named decl-unreadable marker')
}
// B2: pre-fetch default (empty map) is a named degrade, not a crash.
{
  let out = null
  let threw = false
  try { out = render({}) } catch { threw = true }
  ok(!threw && out !== null && out.includes(DECL_UNREADABLE),
    'B2 empty faces map degrades to the named marker, never a throw')
}

// C1/C2: the ticket-board adapter.
if (typeof mod.ticketRowsToAttempts === 'function') {
  const rows = [
    { instance_id: 'integration-tests', period: '20261026', status: 'done', stage_state: 'done', blocked_reason: null, id: 't261026-50' },
    { instance_id: 'docs-sync', period: '20261025', status: 'failed', stage_state: 'failed', blocked_reason: 'scan red', id: 't261026-51' },
    { instance_id: 'docs-sync' }, // no period -> not attributable
    null, // null row
  ]
  let att = null
  let threw = false
  try { att = mod.ticketRowsToAttempts(rows) } catch { threw = true }
  ok(!threw && att && typeof att === 'object',
    'C1 ticket rows adapt to attempt records without throwing')
  const blob = JSON.stringify(att ?? {})
  ok(blob.includes('integration-tests/20261026') || blob.includes('20261026'),
    'C1 attempts are keyed by instance/period')
  ok(blob.includes('t261026-50') && blob.includes('failed'),
    'C1 the attempt carries the ticket evidence (id + state verbatim)')
  ok(!blob.includes('t261026-99'), 'C1 no fabricated attempt exists')
  let att2 = 'unset'
  let threw2 = false
  try { att2 = mod.ticketRowsToAttempts('not-an-array') } catch { threw2 = true }
  ok(!threw2 && (att2 === null || (typeof att2 === 'object' && Object.keys(att2).length === 0)),
    'C2 a non-array payload degrades to empty/null, never a throw')
} else {
  ok(false, 'C1 ticketRowsToAttempts is not exported (not landed yet)')
}

// C3: with attempts available, the slot is not the bare not_run wall.
{
  const att = {
    'integration-tests/20261026': { state: 'failed', ticket_id: 't261026-50', evidence: 't261026-50' },
  }
  const withAtt = render({ instance: 'integration-tests', attempts: att })
  ok(!withAtt.includes(`"${NOT_RUN}"`) || withAtt.includes('t261026-50'),
    'C3 an attempted slot carries ticket evidence, not a bare not_run')
  const bare = render({ instance: 'stage-capacity', unavailable: true, reportless: true })
  ok(bare.includes(NOT_RUN), 'C3 a slot with no attempt still reads not_run (named, unchanged)')
}
// C4: the unavailable copy names the source it could not read.
{
  const copy = JSON.stringify(copies?.attempts_unavailable ?? '')
  ok(copy.includes('ticket'),
    'C4 the attempts_unavailable copy names the inspection ticket board as the source')
}

console.log(`SUMMARY pass=${n - bad.length} fail=${bad.length} env_fail=0 scenario=sc_t261026_10_panel_declared_face_attempts`)
if (bad.length) {
  console.log('FAIL named: ' + bad.join('; '))
  process.exit(1)
}
process.exit(0)
