/**
 * sc_t261026_10_archive_declared_instances.mjs — the inspection archive lists
 * DECLARED instances, and the historical doc-scan shard files are excluded BY
 * NAME, never silently (ticket t261026-10, host report 261026 defect A).
 *
 * Incident shape: the archive whitelist `inspection-<instance>-<YYYYMMDD>.json`
 * also matches the retired doc scanner's per-shard files
 * `inspection-doc-face-<hash>-<period>.json`, so 40+ shard pseudo-instances
 * occupied the tab while the real producer (today's periods, real findings)
 * was fine all along. The fix lands on the READ side: the archive keeps only
 * DECLARED instances (declaration = inspection.yaml, five instances) and names
 * what it excluded (excluded_files: count + names).
 *
 * Grey-box L3, offline seconds, zero docker/Temporal-server/browser, never
 * touches 3099/7233. Judged through the PUBLIC reader
 * server/plugins/workbench/src/host/inspection-archive.ts (imported by path,
 * like the sibling inspection scenarios) — no private helpers, no route
 * internals.
 *
 * Legs:
 *  A1 THE INCIDENT, FIXED FACE - a directory holding one real-instance report
 *     plus shard-shaped files yields instances = the DECLARED set exactly; no
 *     doc-face id appears as an instance.
 *  A2 NAMED, NOT SILENT - the excluded shard files are counted AND named
 *     (count exact, at least the file names visible on the payload).
 *  A3 DECLARED BUT UNARCHIVED - a declared instance with zero files still
 *     renders as an instance (acceptance: "lists exactly the five declared
 *     instances").
 *  A4 HONEST DEGRADE - with the declaration unreadable (decl = null) the
 *     archive degrades NAMED (a declaration_state ok:false with a reason) and
 *     falls back to the filename-derived instance set - never a silent guess.
 *  A5 PRODUCED STILL REACHABLE - a declared instance's parseable period report
 *     still reads out ok (the producer's real findings stay visible once the
 *     shards stop occupying slots).
 *
 * Intent split: the filename whitelist / over-cap / parse-failure truth table
 * belongs to t261006-15 (archive reader contract, landed); the panel-side
 * face id rendering and attempt adaptation belong to the sibling
 * t261026-10-panel-declared-face-attempts entry; THIS entry uniquely owns
 * "declared instances only, exclusions named" on the archive read face.
 *
 * Pre-implement tree: A1/A2/A3/A4 red = the named TDD signal (the reader has
 * no declaration parameter yet). Green required at the integration gate.
 * node missing or the workbench tree absent = ENV_FAIL exit 2.
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const MODULE = path.join(here, '..', '..', 'server', 'plugins', 'workbench',
  'src', 'host', 'inspection-archive.ts')

let n = 0
const bad = []
const ok = (cond, name) => { n += 1; console.log((cond ? 'ok   ' : 'FAIL ') + name); if (!cond) bad.push(name) }

if (!process.versions?.node) { console.log('ENV_FAIL node missing'); process.exit(2) }
if (!fs.existsSync(path.join(here, '..', '..', 'server', 'plugins', 'workbench', 'src', 'host'))) {
  console.log('ENV_FAIL workbench tree missing')
  process.exit(2)
}
if (!fs.existsSync(MODULE)) {
  console.log('FAIL named: inspection-archive.ts not landed (pre-implementation TDD red expected)')
  process.exit(1)
}

let mod
try {
  mod = await import(MODULE)
} catch (e) {
  console.log('FAIL named: module present but unimportable: ' + e.message)
  process.exit(1)
}

if (typeof mod.readInspectionArchive !== 'function') {
  console.log('FAIL named: readInspectionArchive is not exported')
  process.exit(1)
}

const DECL = {
  instances: ['integration-tests', 'docs-sync', 'mechanism-face', 'simplify-face', 'stage-capacity'],
  faces: {
    'integration-tests': 'test',
    'docs-sync': 'doc',
    'simplify-face': 'simplify',
    'stage-capacity': 'stage',
  },
}

const REPORT = { schema: 'v1', heartbeat: { state: 'ok' }, findings: [] }

function makeArchiveDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sandbar-sc-t261026-10-'))
  const write = (name, body) => fs.writeFileSync(path.join(dir, name), body)
  write('inspection-integration-tests-20261026.json', JSON.stringify(REPORT))
  write('inspection-doc-face-00591-20260908.json', JSON.stringify({ shard: true }))
  write('inspection-doc-face-01205-20260908.json', JSON.stringify({ shard: true }))
  write('inspection-doc-face-00abc-20261023.json', JSON.stringify({ shard: true }))
  // whitelist-external shape (never was an instance): stays outside both sets
  write('unrelated.txt', 'hello')
  return dir
}

// A1 + A2 + A3: declared table filters the incident shape.
{
  const dir = makeArchiveDir()
  try {
    const res = await mod.readInspectionArchive(dir, DECL)
    if (!res?.ok) {
      ok(false, 'A1 archive read ok over fixture dir')
    } else {
      const insts = res.instances ?? []
      ok(DECL.instances.every((i) => insts.includes(i)),
        'A1 every declared instance is listed')
      ok(!insts.some((i) => /^doc-face-/.test(i)),
        'A1 no doc-face shard id appears as an instance')
      ok(insts.length === DECL.instances.length,
        'A3 the instance set is EXACTLY the declared set (no shard noise)')
      const ex = res.excluded_files
      ok(ex && typeof ex.count === 'number' && ex.count === 3,
        'A2 excluded count names all three shard files (count=3)')
      const names = JSON.stringify(ex?.names ?? ex?.files ?? ex ?? null)
      ok(names.includes('doc-face-00591-20260908.json'),
        'A2 the excluded shard files are NAMED, not silently dropped')
      // A5: the real report is still reachable on its declared instance.
      const periods = res.periods ?? []
      const p = periods.find((x) => x.period === '20261026')
      const slot = p?.reports?.['integration-tests']
      ok(!!(slot?.ok), 'A5 a declared instance with a real report still reads ok (produced)')
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

// A4: declaration unreadable -> named degrade, filename fallback.
{
  const dir = makeArchiveDir()
  try {
    const res = await mod.readInspectionArchive(dir, null)
    if (!res?.ok) {
      ok(false, 'A4 archive read still ok when the declaration is unreadable')
    } else {
      const state = res.declaration_state
      ok(!!(state && state.ok === false && (state.reason ?? '').length > 0),
        'A4 unreadable declaration degrades NAMED (declaration_state ok:false + reason)')
      const insts = res.instances ?? []
      ok(insts.includes('doc-face-00591'),
        'A4 fallback is the filename-derived set (the marker stays truthful when blind)')
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

console.log(`SUMMARY pass=${n - bad.length} fail=${bad.length} env_fail=0 scenario=sc_t261026_10_archive_declared_instances`)
if (bad.length) {
  console.log('FAIL named: ' + bad.join('; '))
  process.exit(1)
}
process.exit(0)
