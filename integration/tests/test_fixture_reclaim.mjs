#!/usr/bin/env node
/**
 * L1 regression for the fixture temp-dir disk leak (260926: `integ-e2e-fixture-*`
 * accumulated 1086 dirs / 391G because the fixture was not reclaimed on every
 * terminal state).
 *
 * What this pins — anchors are the helpers' public behaviour, never private
 * structure or accidental ordering:
 *   1. entry sweep deletes only dirs at/over the age threshold; fresh dirs and
 *      non-matching dirs survive (a parallel suite may own them);
 *   2. count guardrail: oldest first, and never a dir younger than the live floor;
 *   3. size guardrail and its off switch behave the same way;
 *   4. malformed env knobs fall back instead of crashing; a failing scan only warns;
 *   5. dispose() is idempotent and really deletes;
 *   6. terminal-state matrix — normal, throw, process.exit(), SIGTERM all reclaim;
 *      SIGKILL is uncatchable in-process, so the next entry sweep reclaims it
 *      (that two-layer split is the whole point of the fix);
 *   7. buildFixture actually runs the sweep at its entry (wiring, not just a
 *      callable function).
 *
 * Hermetic: every fixture lands under one temp root (SANDBAR_FIXTURE_TMPDIR) and
 * buildFixture is injected with a throwaway one-commit git repo — no real
 * checkout is cloned and the real $TMPDIR is never swept.
 *
 * 跑法：node integration/tests/test_fixture_reclaim.mjs（英文输出，秒级，无 docker 依赖）
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, utimesSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const MOD = join(HERE, '..', 'baselines', 'ticket-lifecycle-scenes.mjs')
const MOD_URL = pathToFileURL(MOD).href
const { FIXTURE_PREFIX, reapStaleFixtures, fixtureKnob, buildFixture } = await import(MOD_URL)

let pass = 0, fail = 0
const failures = []
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; failures.push(label); console.error(`  FAIL ${label}`) }
}
const section = (s) => console.log(`\n== ${s}`)

const BASE = mkdtempSync(join(tmpdir(), 'integ-e2e-reclaim-it-'))
const FROOT = join(BASE, 'fixtures')          // styled as $TMPDIR for every case
const TINY = join(BASE, 'tiny-src')           // clone source (one commit, ~0 bytes)
mkdirSync(FROOT, { recursive: true })

let caseSeq = 0
function caseRoot(name) { const d = join(FROOT, `${name}-${++caseSeq}`); mkdirSync(d, { recursive: true }); return d }
const fixturePath = (root, name) => join(root, name)
function mkFixtureDir(root, suffix, ageSec, payloadBytes = 0) {
  const p = fixturePath(root, FIXTURE_PREFIX + suffix)
  mkdirSync(p, { recursive: true })
  if (payloadBytes) writeFileSync(join(p, 'payload.bin'), Buffer.alloc(payloadBytes))
  const when = (Date.now() - ageSec * 1000) / 1000
  utimesSync(p, when, when)                   // mtime injection: the sweep's only criterion
  return p
}
const leftovers = (root) => readdirSync(root).filter((n) => n.startsWith(FIXTURE_PREFIX))
function captureLog(fn) {
  const lines = []
  const orig = console.log
  console.log = (...a) => lines.push(a.join(' '))
  try { return { value: fn(), lines } } finally { console.log = orig }
}
async function captureLogAsync(fn) {
  const lines = []
  const orig = console.log
  console.log = (...a) => lines.push(a.join(' '))
  try { return { value: await fn(), lines } } finally { console.log = orig }
}

function initTinyRepo() {
  mkdirSync(TINY, { recursive: true })
  const git = (...a) => spawnSync('git', a, { cwd: TINY, encoding: 'utf8' })
  git('init', '-q')
  git('config', 'user.email', 'reclaim-it@sandbar.test')
  git('config', 'user.name', 'reclaim-it')
  writeFileSync(join(TINY, 'README.md'), 'tiny clone source for the fixture reclamation test\n')
  git('add', '-A')
  git('commit', '-qm', 'init')
  return git('rev-parse', 'HEAD').status === 0
}
const gitOk = initTinyRepo()

/* ---- child processes: real terminal states, real process boundaries -------- */

const childEnv = () => ({ ...process.env, SANDBAR_FIXTURE_TMPDIR: FROOT })
function childScript(tail) {
  // No tmpBase here on purpose: the child resolves its fixture root from
  // SANDBAR_FIXTURE_TMPDIR (childEnv), so this exercise also covers the env path.
  return `
const M = await import(${JSON.stringify(MOD_URL)})
const fx = await M.buildFixture(null, {
  repo: ${JSON.stringify(TINY)},
  mainCheckout: ${JSON.stringify(BASE)},
})
console.log('FIXTURE_TMP=' + fx.tmp)
${tail}
`
}
function runChildSync(tail, env = childEnv()) {
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', childScript(tail)],
    { encoding: 'utf8', env, timeout: 60_000 })
  const m = /FIXTURE_TMP=(.+)/.exec(r.stdout || '')
  return { status: r.status, signal: r.signal, stdout: r.stdout || '', stderr: r.stderr || '', tmp: m ? m[1].trim() : '' }
}
function spawnChild(tail, env = childEnv()) {
  const child = spawn(process.execPath, ['--input-type=module', '-e', childScript(tail)],
    { env, stdio: ['ignore', 'pipe', 'pipe'] })
  const out = { stdout: '', stderr: '', tmp: '', done: false, code: null, signal: null }
  child.stdout.on('data', (d) => {
    out.stdout += d
    const m = /FIXTURE_TMP=(.+)/.exec(out.stdout)
    if (m && !out.tmp) out.tmp = m[1].trim()
  })
  child.stderr.on('data', (d) => { out.stderr += d })
  out.child = child
  out.exited = new Promise((res) => child.once('exit', (code, signal) => {
    out.done = true; out.code = code; out.signal = signal; res(out)
  }))
  return out
}
async function waitForTmp(out, ms = 30_000) {
  const end = Date.now() + ms
  while (!out.tmp && Date.now() < end) await new Promise((r) => setTimeout(r, 50))
  return out.tmp
}

try {
  ok(gitOk, 'harness: throwaway one-commit git repo built (clone source for injected fixtures)')

  /* ---- 1. entry sweep: threshold is the only criterion -------------------- */
  section('reaper: stale removed, fresh and decoys untouched')
  {
    const root = caseRoot('basic')
    const stale = mkFixtureDir(root, 'stale-a', 8 * 3600)
    const fresh = mkFixtureDir(root, 'fresh-b', 5)
    const decoy = join(root, 'integ-e2e-other-suite')      // same family, different prefix
    mkdirSync(decoy, { recursive: true })
    const { value: r, lines } = await captureLogAsync(() => reapStaleFixtures({ dir: root }))
    ok(!existsSync(stale), 'dir older than the threshold (8h >= 6h) is removed')
    ok(existsSync(fresh), 'fresh dir (5s) is kept — a parallel suite may own it')
    ok(existsSync(decoy), 'dir outside the fixture prefix is never touched')
    ok(r.removed === 1 && r.kept === 1, `report counts match reality (removed=${r.removed} kept=${r.kept})`)
    ok(lines.includes('fixture reaper: removed 1 stale dirs (>=21600s) | kept 1 live'),
      `one-line English summary printed verbatim (got: ${JSON.stringify(lines)})`)
  }

  /* ---- 2. threshold boundary -------------------------------------------- */
  section('reaper: threshold boundary + strict non-removal below it')
  {
    const root = caseRoot('boundary')
    const justUnder = mkFixtureDir(root, 'under', 21600 - 120)
    const justOver = mkFixtureDir(root, 'over', 21600 + 120)
    const { value: r } = await captureLogAsync(() => reapStaleFixtures({ dir: root }))
    ok(existsSync(justUnder), 'age just below the threshold (21480s) survives')
    ok(!existsSync(justOver), 'age just above the threshold (21720s) is reclaimed')
    ok(r.kept === 1 && r.removed === 1, `boundary counted honestly (kept=${r.kept} removed=${r.removed})`)
  }

  /* ---- 3. count guardrail: oldest first, live floor respected ------------ */
  section('reaper: count guardrail')
  {
    const root = caseRoot('countcap')
    const oldest = mkFixtureDir(root, 'age100', 100)
    const second = mkFixtureDir(root, 'age090', 90)
    const third = mkFixtureDir(root, 'age080', 80)
    const newest = mkFixtureDir(root, 'age070', 70)
    const { value: r, lines } = await captureLogAsync(() =>
      reapStaleFixtures({ dir: root, maxCount: 2, maxTotalMb: 0 }))
    ok(!existsSync(oldest) && !existsSync(second), 'count cap removes the two oldest first')
    ok(existsSync(third) && existsSync(newest), 'count cap keeps the newest dirs')
    ok(r.removedByCount === 2 && r.kept === 2, `cap report counted (removedByCount=${r.removedByCount} kept=${r.kept})`)
    ok(lines.some((l) => l.startsWith('fixture reaper: count cap 2 exceeded (live=4) -> removed 2 oldest')
      && l.includes('age100')), `count cap names the reclaimed dirs in English (got: ${JSON.stringify(lines)})`)
  }
  {
    const root = caseRoot('livefloor')
    const dirs = ['a', 'b', 'c', 'd'].map((s) => mkFixtureDir(root, s, 5))
    const { value: r } = await captureLogAsync(() =>
      reapStaleFixtures({ dir: root, maxCount: 1, maxTotalMb: 0 }))
    ok(dirs.every((d) => existsSync(d)), 'count cap never touches dirs younger than the live floor (60s)')
    ok(r.removedByCount === 0 && r.kept === 4, `live floor held (removedByCount=${r.removedByCount} kept=${r.kept})`)
  }

  /* ---- 4. size guardrail + off switch ----------------------------------- */
  section('reaper: size guardrail')
  {
    const root = caseRoot('sizecap')
    const big = mkFixtureDir(root, 'big-old', 200, 1_500_000)
    const small = mkFixtureDir(root, 'small-new', 100, 1_500_000)
    const off = await captureLogAsync(() => reapStaleFixtures({ dir: root, maxCount: 99, maxTotalMb: 0 }))
    ok(existsSync(big) && existsSync(small), 'maxTotalMb=0 disables the size guardrail (nothing removed)')
    ok(off.value.removedBySize === 0 && off.value.totalBytes === 0, 'size measurement is skipped when the guardrail is off')
    const { value: r, lines } = await captureLogAsync(() =>
      reapStaleFixtures({ dir: root, maxCount: 99, maxTotalMb: 2 }))
    ok(!existsSync(big) && existsSync(small), 'size cap removes the oldest dir first (~3MB total > 2MB cap)')
    ok(r.removedBySize === 1 && r.totalBytes <= 2 * 1024 * 1024,
      `size cap report honest (removedBySize=${r.removedBySize} totalBytes=${r.totalBytes})`)
    ok(lines.some((l) => l.startsWith('fixture reaper: total size cap 2MB exceeded')), 'size cap prints an English naming line')
  }

  /* ---- 5. knobs & failure tolerance ------------------------------------- */
  section('reaper: malformed knobs and scan failure')
  {
    process.env.SANDBAR_TEST_KNOB = 'abc'
    const warnings = []
    const origErr = console.error
    console.error = (...a) => warnings.push(a.join(' '))
    let v
    try { v = fixtureKnob('SANDBAR_TEST_KNOB', 7) } finally { console.error = origErr }
    ok(v === 7, 'malformed knob falls back to the default instead of crashing')
    ok(warnings.some((w) => w.includes('SANDBAR_TEST_KNOB') && w.includes('malformed')),
      `malformed knob names itself in the warning (got: ${JSON.stringify(warnings)})`)
    process.env.SANDBAR_TEST_KNOB = '5'
    ok(fixtureKnob('SANDBAR_TEST_KNOB', 7) === 5, 'valid knob value is honoured')
    delete process.env.SANDBAR_TEST_KNOB
    ok(fixtureKnob('SANDBAR_TEST_KNOB', 7) === 7, 'unset knob falls back to the default')
    const missing = join(FROOT, 'nope-not-a-dir')
    const { value: r } = await captureLogAsync(() => reapStaleFixtures({ dir: missing }))
    ok(r.removed === 0 && r.error !== '' && !existsSync(missing), 'scan failure only warns (no throw, empty report with error named)')
    const aggRoot = caseRoot('aggressive')
    const d = mkFixtureDir(aggRoot, 'fresh-under-floor', 1)
    const { value: r2 } = await captureLogAsync(() => reapStaleFixtures({ dir: aggRoot, maxAgeSec: 0, minLiveSec: 0 }))
    ok(!existsSync(d) && r2.removed === 1, 'maxAgeSec=0 is the explicit aggressive mode (used by the SIGKILL case below)')
  }

  /* ---- 6. dispose: idempotent and really deletes ------------------------- */
  section('buildFixture: dispose is idempotent and really deletes')
  {
    const root = caseRoot('dispose')
    const fx = await buildFixture(null, { repo: TINY, mainCheckout: BASE, tmpBase: root, reap: false })
    ok(!!fx && existsSync(fx.tmp), 'injected fixture built (tiny clone source, no real checkout touched)')
    ok(fx.fixture.startsWith(fx.tmp) && existsSync(fx.fixture), 'fixture repo path sits inside the temp dir')
    await fx.dispose()
    ok(!existsSync(fx.tmp), 'dispose() really deletes the fixture dir')
    let threw = ''
    try { await fx.dispose() } catch (e) { threw = String(e) }
    try { fx.disposeSync() } catch (e) { threw += String(e) }
    ok(threw === '' && !existsSync(fx.tmp), 'dispose() called twice (and disposeSync after) is idempotent, no throw')
    ok(leftovers(root).length === 0, 'no fixture dir left under the fixture root after dispose')
  }

  /* ---- 7. buildFixture runs the sweep at its entry ----------------------- */
  section('buildFixture: entry sweep is wired')
  {
    const root = caseRoot('entrysweep')
    const stale = mkFixtureDir(root, 'left-by-previous-run', 9 * 3600)
    const { value: fx, lines } = await captureLogAsync(() =>
      buildFixture(null, { repo: TINY, mainCheckout: BASE, tmpBase: root }))
    ok(!existsSync(stale), 'a leftover from a previous run is swept when the next fixture is built')
    ok(lines.some((l) => l.startsWith('fixture reaper: removed 1 stale dirs')), 'the sweep reports its work at fixture entry')
    await fx.dispose()
    ok(leftovers(root).length === 0, 'entry sweep + dispose leave nothing behind')
  }

  /* ---- 8. terminal-state matrix across real process boundaries ----------- */
  section('terminal states: throw / process.exit / SIGTERM / SIGKILL+entry sweep')
  {
    const root = caseRoot('terminal')
    const env = { ...childEnv(), SANDBAR_FIXTURE_TMPDIR: root }

    const thrown = runChildSync(`throw new Error('boom-after-fixture')`, env)
    ok(thrown.tmp !== '' && thrown.status !== 0, `crash path exited non-zero (rc=${thrown.status})`)
    ok(!existsSync(thrown.tmp), 'throw after buildFixture: fixture dir reclaimed by the process fallback')
    ok(thrown.stderr.includes('boom-after-fixture'), 'the original crash is still reported (cleanup never swallows it into green)')

    const exited = runChildSync(`process.exit(3)`, env)
    ok(exited.status === 3 && !existsSync(exited.tmp), `explicit process.exit(3): rc preserved and fixture dir reclaimed (rc=${exited.status})`)

    const term = spawnChild(`setInterval(() => {}, 1000)`, env)
    await waitForTmp(term)
    term.child.kill('SIGTERM')
    await term.exited
    ok(term.code === 143, `SIGTERM exits 143 (conventional code, got ${term.code})`)
    ok(term.tmp !== '' && !existsSync(term.tmp), 'SIGTERM: fixture dir reclaimed by the signal handler')
    ok(term.stderr.includes('SIGTERM'), 'SIGTERM reclaim is announced on stderr')

    const killed = spawnChild(`setInterval(() => {}, 1000)`, env)
    await waitForTmp(killed)
    killed.child.kill('SIGKILL')
    await killed.exited
    ok(killed.tmp !== '' && existsSync(killed.tmp), 'SIGKILL: in-process cleanup is impossible, the dir survives (documented limit)')
    const { value: swept } = await captureLogAsync(() =>
      reapStaleFixtures({ dir: root, maxAgeSec: 0, minLiveSec: 0 }))
    ok(swept.removed === 1 && !existsSync(killed.tmp), 'the next entry sweep reclaims what SIGKILL orphaned')

    const normal = runChildSync(`await fx.dispose()\nprocess.exit(0)`, env)
    ok(normal.status === 0 && !existsSync(normal.tmp), 'normal run + awaited dispose: exit 0 and no residue')
    ok(leftovers(root).length === 0, 'end to end: the fixture root holds zero `integ-e2e-fixture-*` dirs after every terminal state')
  }
} finally {
  try { rmSync(BASE, { recursive: true, force: true }) } catch { /* scratch is best-effort */ }
}

console.log(`\n== fixture reclamation regression: pass=${pass} fail=${fail} ==`)
if (failures.length) for (const f of failures) console.error(`  FAIL ${f}`)
console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
