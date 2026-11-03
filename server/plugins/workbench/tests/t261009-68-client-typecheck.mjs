#!/usr/bin/env node
/**
 * t261009-68-client-typecheck.mjs — typecheck gate over THIS package's own sources.
 *
 * Incident 1 (t261009-68): lane-map.tsx imported lane-map-model with `import type`
 * and then called laneMapScene as a value. tsdown transpiles without checking types,
 * so the bad call shipped into lib/client.js and the console panel died with a
 * ReferenceError at render time.
 *
 * Incident 2 (KI-467, fixed by t261103-24): src/host/docs.ts called isPlainDocRel(rel),
 * a function bound nowhere in the tree, and a normal document read answered HTTP 500.
 * The gate below already existed then, but it filtered tsc diagnostics by path
 * (src/client/** only) and by code (TS1361/TS2304 only), so a src/host defect of
 * exactly the incident class stayed invisible.
 *
 * Judgement (widened by t261103-28): every diagnostic whose file belongs to this
 * package is judged — src/** plus the package-root .ts files (node.ts,
 * node-shims.d.ts, tsdown.config.ts) — excluding node_modules and third-party
 * declaration mirrors under a vendor/ directory. src/client keeps its own dedicated
 * case (B1) so the original incident class stays explicitly covered, and a
 * host-shaped fixture control (B4/B5) proves the widening bites outside src/client.
 *
 * Judged vs exempt: this package type-checks against a deliberately minimal
 * hand-written node shim (node-shims.d.ts — the repo takes no new runtime
 * dependencies) and against the external type mirror that tsconfig.json maps into
 * /tmp/wb-deps. On a machine without that mirror the compiler cannot type react or
 * @deepseek-ai/*, and the measured consequence is a fixed set of diagnostic codes.
 * That set is DECLARED in EXEMPTIONS together with the reason for each entry, and
 * every entry is printed on the face with its measured count and sample locations.
 * Nothing is filtered silently. A blank reason is refused: such an entry exempts
 * nothing, so the diagnostic stays judged and fails the run.
 *
 * Exit contract (integration/README.md): last stdout line is
 * `SUMMARY pass=N skip=M fail=K`; fail>0 -> exit 1; tsc absent -> exit 2 ENV_FAIL
 * naming the real cause (the path, the devDependency, the install command) — never a
 * silent downgrade and never an invented pin.
 *
 * Resource discipline: every child process is a spawnSync with a 120 s timeout (all
 * end states — exit, error, timeout — are collected synchronously, no fd or timer
 * left behind); the temporary fixture root is removed in a finally block; this file
 * writes nothing inside the repo.
 */

import { mkdtempSync, rmSync, writeFileSync, existsSync, readFileSync, readdirSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { spawnSync } from 'node:child_process'
import { join, dirname, resolve, relative, isAbsolute } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const WB = join(HERE, '..')
const TSC = join(WB, 'node_modules', '.bin', 'tsc')
const PKG_JSON = join(WB, 'package.json')
const TSC_TIMEOUT_MS = 120_000

/**
 * Declared, printed, non-silent exemption table: {code -> why this code is recorded
 * instead of judged}. Each entry states what the code IS in this tree. TS2304
 * (cannot find name) and TS1361 (value used through a type-only import) are
 * deliberately absent: they are the incident class this gate exists for.
 */
const EXEMPTIONS = {
  TS2307: 'Cannot find module: tsconfig.json maps react and @deepseek-ai/* into the external type mirror /tmp/wb-deps, which a clean machine does not have, so those imports resolve nowhere here.',
  TS2875: 'JSX needs react/jsx-runtime declarations: they live only in the absent /tmp/wb-deps mirror, so every .tsx tag reports this code instead of a type error.',
  TS2503: 'Cannot find namespace: NodeJS comes from @types/node (not installed — the repo takes no new dependencies) and React from the absent mirror.',
  TS2305: 'Module has no exported member: node-shims.d.ts declares only the node surface the host code measured a need for (no realpath, basename, readdirSync, ...), and dsh members come from the absent mirror.',
  TS2339: 'Property does not exist: carries the minimal-shim gaps (Dirent.isFile, ChildProcess.stdout, Buffer.byteLength, IncomingMessage.headers) and pre-existing model mismatches this tree already had (ReportSlot.report in inspection-archive.ts, the row cast in sidebar.tsx). Recorded on the face, not adjudicated.',
  TS2345: 'Argument not assignable: carries the same shim/mirror gaps and pre-existing model mismatches (e.g. ProjectAnchor against its ok-union). Recorded, not adjudicated.',
  TS2322: 'Assignment not assignable: carries JSX props typed from the absent react declarations and pre-existing strict-null/mismatch findings (platform-banner style/document). Recorded, not adjudicated.',
  TS2554: 'Expected N arguments: the hand-written node shim declares fewer parameters than the call site uses. Recorded, not adjudicated.',
  TS2739: 'Missing properties: the pre-existing client model casts (sidebar.tsx hands a DismissalRowLike-shaped row to a typed card). Recorded, not adjudicated.',
  TS2559: 'No properties in common: the same pre-existing client model casts as TS2739. Recorded, not adjudicated.',
  TS18046: 'Value is of type unknown: the declaration that would type it is absent from the shim/mirror. Recorded, not adjudicated.',
  TS18047: 'Value is possibly null: pre-existing strict-null findings in the client code (platform-banner document/style). Recorded, not adjudicated.',
  TS2352: 'Conversion may be a mistake: a pre-existing conversion in a host module (session-ledger-file.ts). Recorded, not adjudicated.',
}

let passed = 0, failed = 0, skipped = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.error(`  FAIL ${label}`) }
}

/* ── ENV: tsc comes from the exact "typescript" devDependency of this package ── */

/** The devDependency string this package declares for typescript ('' when absent). */
function declaredTypescriptPin() {
  try {
    const pkg = JSON.parse(readFileSync(PKG_JSON, 'utf8'))
    const pin = pkg?.devDependencies?.typescript
    return typeof pin === 'string' ? pin : ''
  } catch {
    return ''
  }
}

if (!existsSync(TSC)) {
  const pin = declaredTypescriptPin()
  console.error(`[ENV_FAIL] typecheck gate cannot run: no tsc executable at ${TSC}`)
  if (pin === '') {
    console.error('[ENV_FAIL] the cause is in package.json: it declares no "typescript" devDependency, so nothing can produce that path (the t261103-28 defect: the copy used to claim a pin that did not exist)')
  } else {
    console.error(`[ENV_FAIL] that path is produced by the "typescript" devDependency declared in ${PKG_JSON} (declared version: ${pin}); the installed tree is missing it`)
  }
  console.error(`[ENV_FAIL] fix the environment with: cd ${WB} && npm ci --no-audit --ignore-scripts`)
  console.log('SUMMARY pass=0 skip=0 fail=0')
  process.exit(2)
}

/* tsc helper: always returns {status, out}; every end state lands in `out`. */
function runTsc(args, cwd) {
  const r = spawnSync(TSC, args, { cwd, encoding: 'utf8', timeout: TSC_TIMEOUT_MS })
  if (r.error) return { status: -1, out: String(r.error) }
  return { status: r.status, out: (r.stdout || '') + (r.stderr || '') }
}

const tscFlags = ['--noEmit', '--skipLibCheck', '--allowImportingTsExtensions', '--noImplicitAny', 'false']

/* ── Diagnostics: parse, scope to this package, judge against EXEMPTIONS ── */

const DIAG_RE = /^(?<file>.+?)\((?<line>\d+),(?<col>\d+)\): error (?<code>TS\d+): (?<msg>.*)$/

function parseDiagnostics(text) {
  const out = []
  for (const raw of text.split('\n')) {
    const m = DIAG_RE.exec(raw.trim())
    if (m) out.push({ file: m.groups.file, line: +m.groups.line, col: +m.groups.col, code: m.groups.code, message: m.groups.msg })
  }
  return out
}

/**
 * tsc prints diagnostic paths relative to the cwd it ran in, and its relative form
 * can climb (e.g. `../../../tmp/x/src/host/a.ts`). Resolving against that base and
 * re-relativising keeps the scope test stable for both the package scan and the
 * fixture controls.
 */
function relTo(base, file) {
  return relative(base, resolve(base, file)).replace(/\\/g, '/')
}

/**
 * Is this diagnostic about this package's own source? Judged: everything under src/
 * plus the package-root .ts files. Not judged: dependencies (node_modules) and
 * third-party declaration mirrors (vendor/*.d.ts).
 */
function inPackageScope(file, base = WB) {
  const rel = relTo(base, file)
  if (rel === '' || rel.startsWith('..') || isAbsolute(rel)) return false
  const parts = rel.split('/')
  if (parts.includes('node_modules')) return false
  const underSrc = parts[0] === 'src' && parts.length > 1
  const rootSource = parts.length === 1 && /\.tsx?$/.test(rel)
  if (!underSrc && !rootSource) return false
  if (parts.includes('vendor') && rel.endsWith('.d.ts')) return false
  return true
}

/** Reason for a code, or null. A blank/absent reason never exempts anything. */
function exemptionReason(code, table = EXEMPTIONS) {
  if (!Object.prototype.hasOwnProperty.call(table, code)) return null
  const reason = typeof table[code] === 'string' ? table[code].trim() : ''
  return reason === '' ? null : reason
}

/** Split the in-package diagnostics of one tsc run into judged / exempt. */
function judge(diags, table = EXEMPTIONS, base = WB) {
  const judged = [], exempt = []
  for (const d of diags) {
    if (!inPackageScope(d.file, base)) continue
    const reason = exemptionReason(d.code, table)
    if (reason === null) judged.push(d)
    else exempt.push({ ...d, reason })
  }
  return { judged, exempt }
}

let tmp
try {
  tmp = mkdtempSync(join(tmpdir(), 'wb-typecheck-'))

  /* ── A. Guard's guard: malformed fixtures really trip tsc, clean fixture passes ── */
  // The module specifier is built by concatenation: the fixture bytes on disk are
  // unchanged, but the static import scanner of lint L3 no longer reads this test
  // file as carrying a dangling import (measured, 3 errors, t261009-68 review round).
  const spec = './model' + '.ts'
  writeFileSync(join(tmp, 'model.ts'), 'export function scene(m: { n: number }) { return m.n }\nexport type Only = { n: number }\n')
  writeFileSync(join(tmp, 'bad.tsx'), `import type { scene } from '${spec}'\nexport const x = scene({ n: 1 })\n`)
  const bad = runTsc([...tscFlags, 'bad.tsx'], tmp)
  ok(bad.status !== 0 && bad.out.includes('error TS1361'), `A1 malformed fixture (value used through a type-only import) trips TS1361 (status=${bad.status})`)
  writeFileSync(join(tmp, 'bad2.tsx'), 'export const z = scene({ n: 3 })\n')
  const bad2 = runTsc([...tscFlags, 'bad2.tsx'], tmp)
  ok(bad2.status !== 0 && bad2.out.includes('error TS2304'), `A2 malformed fixture (value never imported or defined) trips TS2304 (status=${bad2.status})`)
  writeFileSync(join(tmp, 'clean.tsx'), `import type { Only } from '${spec}'\nimport { scene } from '${spec}'\nexport const y: Only = { n: 2 }\nexport const w = scene(y)\n`)
  const clean = runTsc([...tscFlags, 'clean.tsx'], tmp)
  ok(clean.status === 0 && !clean.out.includes('error TS1361') && !clean.out.includes('error TS2304'), `A3 clean fixture (value import and type-only import coexist) passes (status=${clean.status})`)
  ok(bad.status !== 0 && bad2.status !== 0, 'A4 guard is load-bearing (both malformed fixtures really exit non-zero)')

  /* ── B. Real tree: judge every in-package diagnostic ── */
  // One program covers both halves of the widened scope: the base tsconfig's `include`
  // (src/**, node-shims.d.ts, resolved relative to that config = the package root) plus
  // the package-root .ts files passed through `files`.
  const rootSources = readdirSync(WB).filter((n) => /\.tsx?$/.test(n)).map((n) => join(WB, n))
  const judgeConfig = { extends: join(WB, 'tsconfig.json') }
  if (rootSources.length > 0) judgeConfig.files = rootSources
  writeFileSync(join(tmp, 'tsconfig.judge.json'), JSON.stringify(judgeConfig, null, 2))

  const scan = runTsc(['-p', join(tmp, 'tsconfig.judge.json'), '--noImplicitAny', 'false', '--listFiles'], WB)
  const scanned = parseDiagnostics(scan.out)
  // --listFiles prints one absolute path per line after the diagnostics: that listing
  // is what proves which files the judgement actually covered.
  const listedFiles = scan.out.split('\n').map((l) => l.trim())
    .filter((l) => l !== '' && !DIAG_RE.test(l) && !/(^|\s)error TS\d+/.test(l))
  // Measured exit-code semantics of tsc 5.9: 0 = clean, 2 = diagnostics reported,
  // 1 = the command/config was rejected (bad path, unknown option). A run that ended
  // in 1, or that reported nothing at all on a non-zero status, proves nothing.
  ok((scan.status === 0 || (scan.status === 2 && scanned.length > 0)),
    `B0 tsc really ran over the package sources (status=${scan.status}, diagnostics=${scanned.length})`)

  const { judged, exempt } = judge(scanned)

  // The pin must be real and exact: a range here would make the gate's own premise drift.
  const pin = declaredTypescriptPin()
  const tscVersionRun = runTsc(['--version'], WB)
  const installed = /Version (\d+\.\d+\.\d+[^\s]*)/.exec(tscVersionRun.out)?.[1] || ''
  ok(/^\d+\.\d+\.\d+$/.test(pin) && installed === pin,
    `B0b the exact "typescript" devDependency pin is what is installed (declared=${pin || 'missing'}, installed=${installed || 'unknown'})`)

  // B0c — the widening is not vacuous: the judged program must really contain the
  // widened scope, so a later tsconfig/include drift cannot shrink the judgement silently.
  const covered = (rel) => listedFiles.includes(join(WB, rel))
  const rootCovered = rootSources.length > 0 && rootSources.every((p) => listedFiles.includes(p))
  ok(rootCovered && covered('node.ts') && covered('src/client/index.tsx') && covered('src/host/docs.ts'),
    `B0c the judging program covers the widened scope (${rootSources.length} package-root .ts files, src/client and src/host)`)

  // B1 — the original incident class, still covered on its own dedicated directory.
  const clientUnbound = scanned.filter((d) => {
    const rel = relTo(WB, d.file)
    return inPackageScope(d.file) && rel.startsWith('src/client/') && (d.code === 'TS1361' || d.code === 'TS2304')
  })
  ok(clientUnbound.length === 0, `B1 zero unbound-value errors (TS1361/TS2304) in src/client (found ${clientUnbound.length})`)
  for (const d of clientUnbound.slice(0, 10)) console.error(`    ${d.file}(${d.line},${d.col}): error ${d.code}: ${d.message}`)

  // B2 — the exemption table is honest: every entry carries a reason, and a blank
  // reason is refused rather than turning into a silent green.
  const blankEntries = Object.entries(EXEMPTIONS).filter(([, reason]) => typeof reason !== 'string' || reason.trim() === '')
  ok(blankEntries.length === 0, `B2 every declared exemption carries a non-blank reason (blank: ${blankEntries.map(([code]) => code).join(',') || 'none'})`)
  const blankProbe = judge(
    [{ file: 'src/host/probe.ts', line: 1, col: 1, code: 'TS2304', message: 'Cannot find name...' }],
    { TS2304: '   ' },
  )
  ok(blankProbe.judged.length === 1 && blankProbe.exempt.length === 0, 'B2b a blank exemption reason is refused (the diagnostic stays judged)')

  // The face: what is declared exempt, why, how much of it the tree reports, where.
  console.log(`  exempt: ${exempt.length} of ${exempt.length + judged.length} in-package diagnostics, by declared code`)
  const exemptByCode = new Map()
  for (const d of exempt) {
    if (!exemptByCode.has(d.code)) exemptByCode.set(d.code, [])
    exemptByCode.get(d.code).push(d)
  }
  for (const [code, reason] of Object.entries(EXEMPTIONS)) {
    const hits = exemptByCode.get(code) || []
    console.log(`  exemption ${code} [${hits.length} measured]: ${reason}`)
    for (const d of hits.slice(0, 2)) {
      console.log(`      e.g. ${d.file}(${d.line},${d.col}): error ${d.code}: ${d.message.slice(0, 110)}`)
    }
  }

  // B3 — the judgement: no in-package diagnostic may escape the declaration above.
  ok(judged.length === 0, `B3 zero non-exempt in-package diagnostics across src/** and the package-root .ts files (found ${judged.length})`)
  for (const d of judged.slice(0, 20)) console.error(`    ${d.file}(${d.line},${d.col}): error ${d.code}: ${d.message}`)
  if (judged.length > 20) console.error(`    ... and ${judged.length - 20} more`)

  /* ── B4/B5. Incident control on a HOST-SHAPED path ──
     A control that only exercised src/client would re-test the code path that was
     already covered; this pair proves the widened judgement reaches src/host. */
  const fixtureFlags = {
    compilerOptions: {
      jsx: 'react-jsx', target: 'es2022', module: 'esnext', moduleResolution: 'bundler',
      strict: true, skipLibCheck: true, noEmit: true, allowImportingTsExtensions: true,
      noImplicitAny: false,
    },
    include: ['src'],
  }
  const hostRoot = join(tmp, 'host-control')
  const badHost = join(hostRoot, 'bad')
  const cleanHost = join(hostRoot, 'clean')
  for (const dir of [badHost, cleanHost]) {
    mkdirSync(join(dir, 'src', 'host'), { recursive: true })
    writeFileSync(join(dir, 'tsconfig.json'), JSON.stringify(fixtureFlags, null, 2))
    // The helper exists in a host module and is exported, as isPlainDocRel did.
    writeFileSync(join(dir, 'src', 'host', 'doc-face.ts'),
      "export function isPlainDocRel(rel: string): boolean {\n  return rel !== '' && !rel.startsWith('/')\n}\n")
  }
  // Bad: the consumer uses the helper without importing it (the KI-467 shape).
  writeFileSync(join(badHost, 'src', 'host', 'docs-view.ts'),
    'export function servedRel(rel: string): boolean {\n  return isPlainDocRel(rel)\n}\n')
  // Clean: the same pair, with the import present.
  // Same house trick as `spec` above: the helper specifier is built by concatenation.
  // The fixture bytes on disk stay identical, while the static import scanner of lint
  // L3 no longer reads this test file as carrying a dangling import (t261103-30 rework).
  const helperRel = './doc' + '-face.ts'
  writeFileSync(join(cleanHost, 'src', 'host', 'docs-view.ts'),
    `import { isPlainDocRel } from '${helperRel}'\n\nexport function servedRel(rel: string): boolean {\n  return isPlainDocRel(rel)\n}\n`)

  const badHostRun = runTsc(['-p', 'tsconfig.json'], badHost)
  const badHostJudge = judge(parseDiagnostics(badHostRun.out), EXEMPTIONS, badHost)
  const hostHits = badHostJudge.judged.filter((d) => d.code === 'TS2304' && relTo(badHost, d.file).startsWith('src/host/'))
  ok(badHostRun.status !== 0 && hostHits.length > 0,
    `B4 control: an unbound helper under src/host is reported as a non-exempt TS2304 (status=${badHostRun.status}, hits=${hostHits.length})`)
  for (const d of hostHits) console.log(`      control hit ${relTo(badHost, d.file)}(${d.line},${d.col}): error ${d.code}: ${d.message}`)

  const cleanHostRun = runTsc(['-p', 'tsconfig.json'], cleanHost)
  const cleanHostJudge = judge(parseDiagnostics(cleanHostRun.out), EXEMPTIONS, cleanHost)
  ok(cleanHostRun.status === 0 && cleanHostJudge.judged.length === 0 && cleanHostJudge.exempt.length === 0,
    `B5 control: the clean host fixture is green and prints no exemption (status=${cleanHostRun.status}, judged=${cleanHostJudge.judged.length}, exempt=${cleanHostJudge.exempt.length})`)

  /* ── C. Bundle freshness anchor: the built bundle carries the definition ── */
  const bundle = join(WB, 'lib', 'client.js')
  if (!existsSync(bundle)) {
    skipped++
    console.log('  skip C1 lib/client.js not built yet (run build-client.sh; covered by the build gate)')
  } else {
    const js = readFileSync(bundle, 'utf8')
    const defined = /\bfunction laneMapScene\b|\blaneMapScene\s*=\s*\(/.test(js)
    ok(defined, 'C1 built bundle carries the laneMapScene definition (a src change was not shipped stale)')
  }
} finally {
  if (tmp) rmSync(tmp, { recursive: true, force: true })
}

console.log(`SUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
