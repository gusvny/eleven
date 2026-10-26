/**
 * t261026-10-inspection-decl.mjs — the inspection declaration reader + the archive's
 * declared-instance filter (t261026-10, host report 261026 defects A/B).
 *
 * Pins:
 *  - reader: engine-spawn seam returns the declared instance set (ids + scan_face +
 *    enabled); malformed/empty id rows are dropped, a failed read carries its named
 *    reason; successes cache for the TTL, failures never cache; the engine test
 *    overlay env SANDBAR_INSPECTION_DECL is honored with a relative value refused;
 *  - archive: with a readable declaration the instance set IS the declaration (a
 *    declared instance with zero archived reports still lists), faces ride on the
 *    payload, non-declared whitelist matches are excluded with an EXACT count and a
 *    capped name list (count > names.length names the truncation, review C3), and a
 *    failed declaration read degrades named (filename-derived fallback, faces empty);
 *  - declaration lock (source level, no second YAML parser): the shipped repo-root
 *    inspection.yaml names exactly the five declared instances.
 * Zero network, real fs only inside this test's tmp dir; the engine spawn is injected.
 */
import assert from 'node:assert/strict'
import { mkdtempSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import {
  readInspectionArchive, EXCLUDED_NAMES_CAP, ARCHIVE_FILE_RE,
} from '../src/host/inspection-archive.ts'
import {
  readInspectionDeclaration, resetInspectionDeclCacheForTests,
} from '../src/host/inspection-decl.ts'

let n = 0
const ok = (cond, msg) => { n += 1; assert.ok(cond, msg) }

// ---- reader: happy path through the injected engine seam ----
const DECL = {
  ok: true, file: '/repo/inspection.yaml',
  instances: [
    { id: 'integration-tests', scan_face: '', enabled: true },
    { id: 'docs-sync', scan_face: 'doc', enabled: true },
    { id: 'mechanism-face', scan_face: '', enabled: false },
    { id: 'simplify-face', scan_face: 'simplify', enabled: true },
    { id: 'stage-capacity', scan_face: 'stage', enabled: false },
  ],
}
let spawnCalls = 0
resetInspectionDeclCacheForTests()
const r1 = await readInspectionDeclaration('/repo', 'sandbar', {
  spawn: async () => { spawnCalls += 1; return DECL },
})
ok(r1.ok === true, 'decl reader: engine seam ok')
ok(r1.instances.length === 5, 'decl reader: five declared instances')
ok(r1.instances.find((i) => i.id === 'docs-sync').scan_face === 'doc', 'decl reader: scan_face carried')
// Second call inside the TTL hits the cache (one spawn total).
await readInspectionDeclaration('/repo', 'sandbar', { spawn: async () => { spawnCalls += 1; return DECL } })
ok(spawnCalls === 1, 'decl reader: successful read is cached (single spawn)')

// ---- reader: failed read is never cached ----
let failCalls = 0
const r2 = await readInspectionDeclaration('/repo2', null, {
  spawn: async () => { failCalls += 1; return { ok: false, file: '', reason: 'engine load failed: yaml parse' } },
})
ok(r2.ok === false && /yaml parse/.test(r2.reason), 'decl reader: failed read carries the named reason')
await readInspectionDeclaration('/repo2', null, {
  spawn: async () => { failCalls += 1; return { ok: false, file: '', reason: 'still failing' } },
})
ok(failCalls === 2, 'decl reader: a failed resolution is never cached (re-spawn next call)')

// ---- reader: overlay env ----
resetInspectionDeclCacheForTests()
const r3 = await readInspectionDeclaration('/repo', null, {
  env: { SANDBAR_INSPECTION_DECL: 'relative/path.yaml' },
  spawn: async () => { throw new Error('must not spawn') },
})
ok(r3.ok === false && /relative/.test(r3.reason), 'decl reader: relative overlay env refused, named')

// ---- archive: declared filter excludes shard files, keeps declared with zero files ----
const dir = mkdtempSync(join(tmpdir(), 'insp-arch-'))
const mk = (name, body) => writeFileSync(join(dir, name), body ?? JSON.stringify({ findings: [] }))
mk('inspection-integration-tests-20261026.json', JSON.stringify({ findings: [{ id: 'f1' }] }))
mk('inspection-docs-sync-20261026.json', JSON.stringify({ findings: [] }))
for (let i = 0; i < 12; i++) {
  mk(`inspection-doc-face-${String(1000 + i).padStart(5, '0')}-20260908.json`)
}
mk('not-a-report.txt')

const declRead = { ok: true, file: '/repo/inspection.yaml', instances: DECL.instances }
const a1 = await readInspectionArchive(dir, declRead)
ok(a1.ok === true, 'archive: declared read ok')
ok(JSON.stringify(a1.instances) === JSON.stringify([
  'docs-sync', 'integration-tests', 'mechanism-face', 'simplify-face', 'stage-capacity',
]), 'archive: instances = the DECLARATION, sorted (declared instances with zero files still list)')
ok(a1.faces['docs-sync'] === 'doc' && a1.faces['integration-tests'] === '', 'archive: faces = declared scan_face (empty face stays empty, consumer renders the marker)')
ok(a1.excluded_files.count === 12, 'archive: excluded count is EXACT (12 shard files)')
ok(a1.excluded_files.names.length === EXCLUDED_NAMES_CAP, `archive: excluded names capped at ${EXCLUDED_NAMES_CAP}`)
ok(a1.excluded_files.count > a1.excluded_files.names.length, 'archive: count > names length names the truncation (review C3)')
ok(a1.excluded_files.names.every((x) => ARCHIVE_FILE_RE.test(x) && x.startsWith('inspection-doc-face-')),
  'archive: excluded names are the shard files themselves (named, not silent)')
ok(a1.declaration_state.ok === true && a1.declaration_state.file === '/repo/inspection.yaml', 'archive: declaration state carried')
const p = a1.periods.find((x) => x.period === '20261026')
ok(p && p.reports['integration-tests'] && p.reports['integration-tests'].ok === true, 'archive: declared real report still parsed')
ok(p && !p.reports['doc-face-01000'], 'archive: shard files occupy no period slot')

// ---- archive: failed declaration degrades named, legacy fallback intact ----
const a2 = await readInspectionArchive(dir, { ok: false, file: '/repo/inspection.yaml', reason: 'DeclError: bad schema' })
ok(a2.ok === true, 'archive: declaration-failure fallback still reads the ledger')
ok(a2.instances.includes('doc-face-01000'), 'archive: fallback is filename-derived (named degrade, not a guess)')
ok(a2.faces && Object.keys(a2.faces).length === 0, 'archive: fallback faces empty (every face reads decl-unreadable)')
ok(a2.declaration_state.ok === false && /bad schema/.test(a2.declaration_state.reason), 'archive: the declaration failure reason rides the payload')
ok(a2.excluded_files.count === 0, 'archive: nothing excluded without a declaration')

// ---- archive: legacy call (no decl argument) keeps the old shape ----
const a3 = await readInspectionArchive(dir)
ok(a3.ok === true && a3.instances.includes('doc-face-01000'), 'archive: legacy no-arg call unchanged')
ok(a3.declaration_state.reason.includes('legacy'), 'archive: legacy call names that no declaration was supplied')

// ---- archive: the plain scenario table shape (integration contract) works too ----
const a4 = await readInspectionArchive(dir, {
  instances: ['integration-tests', 'docs-sync', 'mechanism-face', 'simplify-face', 'stage-capacity'],
  faces: { 'docs-sync': 'doc' },
})
ok(a4.ok === true && a4.instances.length === 5 && a4.excluded_files.count === 12,
  'archive: the plain {instances, faces} table filters identically')
ok(a4.faces['docs-sync'] === 'doc' && !('integration-tests' in a4.faces),
  'archive: plain table faces carried verbatim (undeclared faces absent)')
ok(a4.declaration_state.ok === true, 'archive: plain table reads as an ok declaration')

// ---- declaration lock (source level — the engine parser stays the truth) ----
const DECL_FILE = new URL('../../../../inspection.yaml', import.meta.url).pathname
ok(existsSync(DECL_FILE), 'lock: repo-root inspection.yaml exists')
const text = await (await import('node:fs/promises')).readFile(DECL_FILE, 'utf8')
const ids = [...text.matchAll(/^\s*-\s+id:\s*(\S+)\s*$/gm)].map((m) => m[1])
ok(JSON.stringify(ids) === JSON.stringify([
  'integration-tests', 'docs-sync', 'mechanism-face', 'simplify-face', 'stage-capacity',
]), `lock: the shipped declaration names exactly the five instances (got ${JSON.stringify(ids)})`)
for (const want of ['docs-sync: doc', 'simplify-face: simplify', 'stage-capacity: stage']) {
  const [inst, face] = want.split(': ')
  const block = text.split(/-\s+id:/).find((s) => s.trimStart().startsWith(inst)) || ''
  ok(new RegExp(`scan_face:\\s*${face}`).test(block), `lock: ${inst} declares scan_face=${face}`)
}

rmSync(dir, { recursive: true, force: true })
console.log(`t261026-10-inspection-decl: ${n} assertions ok`)
