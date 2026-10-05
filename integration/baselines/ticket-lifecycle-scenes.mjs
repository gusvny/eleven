/**
 * Scenario library for the ticket-lifecycle E2E baseline (group 5).
 *
 * What is real: the Docker test Temporal (17233 / namespace suyou-test), a  (naming-compat)
 * real per-ticket worker (worker.py on a dedicated queue, WATCH self-exit),
 * the real engine chain (prepare_workspace -> create_plan <-> review_plan ->
 * implement || design_integration_tests -> run_integration_tests -> arbitrate
 * -> acceptance_walkthrough -> merge_check -> merge [human gate] ->
 * suggest_next inline -> status=closed), real settle/merge/lane cleanup, and
 * human-review signals via real client.py.
 *
 * What is stubbed: only the agent brain (SANDBAR_AGENT_STUB=1 self-completes
 * on a timer, SANDBAR_SUGGEST_STUB=ok, zero model calls).
 *
 * Isolation (merge lands on the worker-side REPO_ROOT current branch, ignoring
 * base_ref — see agent_activities.py merge()): every scenario runs against a
 * throwaway fixture repo — a --depth 1 clone of the local checkout. The
 * worker starts from the fixture repo's own engine with REPO_ROOT=fixture:
 * lanes, settle, merge, and lane cleanup all happen inside the fixture repo;
 * the real repo is never touched.
 *
 * Determinism levers: the agent stage returns a cached result when the result
 * file already exists (agent_activities.py idempotent cache path). Scenarios
 * pre-seed `.suyou/stage_arbitrate_gen<N>.json` (summary carries verdict=pass)  (naming-compat)
 * while the ticket is mechanically busy in run_integration_tests — the stub
 * brain never produces verdict= on its own, and that is exactly scene D's
 * round-limit trigger.
 *
 * Safety: same write-guard trio as ticket-validate.mjs (target env unset ->
 * env_fail; explicit production default -> FAIL; otherwise pinned to
 * 17233/suyou-test).  (naming-compat)
 *
 * Fixture reclamation (260926 disk-leak fix, 1086 dirs / 391G): the fixture
 * temp dir is reclaimed on every terminal state — callers await dispose() in a
 * finally, buildFixture arms process-level fallbacks (exit / SIGINT / SIGTERM /
 * uncaughtException / unhandledRejection), and every run first sweeps stale
 * `integ-e2e-fixture-*` dirs (see reapStaleFixtures). SIGKILL cannot be caught
 * in-process, so the entry sweep is the net for it.
 */

import { spawn, spawnSync } from 'node:child_process'
import { connect } from 'node:net'
import { existsSync, readdirSync, rmSync, statSync } from 'node:fs'
import { mkdtemp, mkdir, writeFile, readFile, readdir, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const POC = join(REPO, 'server', 'engine')
const COMPOSE = join(REPO, 'server', 'docker-compose.test.yml')
export const PROD_ADDR = '127.0.0.1:7233'
export const TEST_ADDR = '127.0.0.1:17233'
export const TEST_NS = 'sandbar-test'
const EPIC_CODE = 'integ-e2e'

/* ------------------------------------------------------------------ assertions */

export function makeTally() {
  const t = { pass: 0, fail: 0, envFail: 0, failures: [] }
  t.ok = (cond, label) => {
    if (cond) { t.pass++; console.log(`  ok ${label}`) } else {
      t.fail++; t.failures.push(label); console.error(`  FAIL ${label}`)
    }
  }
  t.envFailNote = (label) => { t.envFail++; console.log(`  ENV_FAIL ${label}`) }
  t.section = (s) => console.log(`\n== ${s}`)
  return t
}

/* ------------------------------------------------------------------ processes */

/** Run one command via spawnSync; returns {status, stdout, stderr} as strings. */
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', timeout: opts.timeoutMs ?? 60_000, ...opts })
  return { status: r.status, stdout: r.stdout || '', stderr: r.stderr || '' }
}

/** Own a long-lived child process with a reaper that always collects it (KILL if TERM does not work). */
export function own(child) {
  const o = { child, done: false, reaped: false }
  child.once('exit', () => { o.done = true })
  o.kill = async (sig = 'SIGTERM') => {
    if (o.done) return
    try { child.kill(sig) } catch { /* already dead */ }
    for (let i = 0; i < 50 && !o.done; i++) await new Promise(r => setTimeout(r, 100))
    if (!o.done) { try { child.kill('SIGKILL') } catch { /* already dead */ } }
    await new Promise(r => {
      if (o.done) return r()
      child.once('exit', r)
      setTimeout(r, 5000).unref?.()
    })
    o.reaped = !child.pid || (() => { try { process.kill(child.pid, 0); return false } catch { return true } })()
  }
  return o
}

/* ------------------------------------------------------------------ environment */

export async function portOpen(host, port, ms = 1500) {
  return new Promise((resolve) => {
    const s = connect({ host, port })
    const fin = (v) => { s.destroy(); resolve(v) }
    s.setTimeout(ms, () => fin(false))
    s.once('connect', () => fin(true))
    s.once('error', () => fin(false))
  })
}

/**
 * Find a python that can import temporalio (the engine SDK needs it).
 * Priority: this tree's venv -> the main checkout's venv (worktrees share
 * .git; prepare_workspace links same-source dirs into the lane) -> bare
 * python3. Returns null when none works.
 */
export function findSdkPython(t) {
  const mainVenv = run('git', ['-C', REPO, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
  const mainCheckout = mainVenv.status === 0 ? dirname(mainVenv.stdout.trim()) : ''
  const candidates = [
    join(POC, '.venv', 'bin', 'python'),
    ...(mainCheckout ? [join(mainCheckout, 'server', 'engine', '.venv', 'bin', 'python')] : []),
    'python3',
  ]
  for (const py of candidates) {
    const r = run(py, ['-c', 'import temporalio'], { timeoutMs: 30_000 })
    if (r.status === 0) return py
  }
  t?.envFailNote?.('temporalio SDK not importable (no server/engine/.venv here or in the main checkout, system python3 lacks it): env halves cannot drive real client.py/worker')
  return null
}

/**
 * Make sure the Docker test Temporal (17233) is usable: reachable AND ready to
 * serve RPCs AND the custom search attributes exist. Probe first, idempotent
 * `docker compose up -d` when down, then a readiness/registration loop.
 * Returns true/false.
 *
 * Why "port open" is not enough (flakes observed 261002): a freshly composed
 * server opens the gRPC port before it serves RPCs — ticket-start then dies on
 * a transient transport error ("broken pipe"), and a cold namespace has no
 * ProjectKey/EpicCode search attribute mapping (docs/testing-guide.md test-env
 * steps), so `ticket-start --epic` fails loudly ("立项 epic 打标失败"). Both
 * were env-state-coupled false reds: warm runs passed, cold runs failed.
 * `operator search-attribute create` is idempotent on the test server and its
 * success doubles as the readiness proof.
 */
export async function ensureTestTemporal(t) {
  if (!(await portOpen('127.0.0.1', 17233))) {
    const docker = run('docker', ['--version'], { timeoutMs: 10_000 })
    if (docker.status !== 0) {
      t?.envFailNote?.(`docker CLI unavailable (test Temporal 17233 down and cannot be pulled up): ${docker.stderr.trim().slice(0, 120) || 'command not found'}`)
      return false
    }
    console.log('  test Temporal 17233 down -> docker compose up -d (idempotent) ...')
    run('docker', ['compose', '-f', COMPOSE, 'up', '-d'], { timeoutMs: 300_000 })
    let opened = false
    for (let i = 0; i < 60; i++) {
      if (await portOpen('127.0.0.1', 17233)) { opened = true; break }
      await new Promise(r => setTimeout(r, 2000))
    }
    if (!opened) {
      t?.envFailNote?.('docker compose up ran but test Temporal 17233 never opened: test env unavailable')
      return false
    }
  }
  // Readiness + search-attribute registration (docs/testing-guide.md steps):
  // retry on transport errors (server up but not serving yet), stop early on
  // success. Idempotent on an already-warm server.
  const cli = join(POC, 'bin', 'temporal')
  const deadline = Date.now() + 90_000
  for (const name of ['ProjectKey', 'EpicCode']) {
    let done = false, lastErr = ''
    while (Date.now() < deadline) {
      const r = run(cli, ['operator', 'search-attribute', 'create',
        '--name', name, '--type', 'Keyword', '--namespace', TEST_NS, '--address', TEST_ADDR],
        { timeoutMs: 30_000 })
      const out = `${r.stdout || ''}\n${r.stderr || ''}`
      if (r.status === 0 || /already exists/i.test(out)) { done = true; break }
      lastErr = out.trim().slice(-200) || `exit=${r.status}`
      await new Promise(r2 => setTimeout(r2, 2000))
    }
    if (!done) {
      t?.envFailNote?.(`test Temporal search attribute ${name} could not be registered (ticket-start --epic fails loudly without it; steps in docs/testing-guide.md): ${lastErr}`)
      return false
    }
  }
  return true
}

/**
 * Write-guard three states (same contract as ticket-validate.mjs): returns
 * 'run' | 'env_fail' | 'fail'. Target env unset = env_fail (ticket t260904-12
 * three-state contract: a missing environment uses the env red word, never a
 * "skipped" outcome word); explicitly pointing at production = fail; any other unclear
 * target = fail. Never start when the target is unclear.
 */
export function writeGuard() {
  const target = process.env.SANDBAR_TARGET_HOST
  if (target === PROD_ADDR) {
    console.error(`  FAIL write-guard: SANDBAR_TARGET_HOST explicitly points at production default ${PROD_ADDR} -- ticket-creating tests refuse to run (red line: production 7233 is read-only)`)
    return 'fail'
  }
  if (target === undefined || target === '') return 'env_fail'
  if (target !== TEST_ADDR) {
    console.error(`  FAIL write-guard: SANDBAR_TARGET_HOST=${target} is neither the pinned test env ${TEST_ADDR} nor production -- refusing an unclear write target`)
    return 'fail'
  }
  return 'run'
}

/** Shared env for every client.py/worker call (pinned to the test environment). */
export function targetEnv(extra = {}) {
  return {
    ...process.env,
    SANDBAR_TARGET_HOST: TEST_ADDR,
    SANDBAR_NAMESPACE: TEST_NS,
    ...extra,
  }
}

/* ------------------------------------------------------------------ fixture repo */

/** Fixture dir prefix: shared by the single creation point and the entry sweep. */
export const FIXTURE_PREFIX = 'integ-e2e-fixture-'

/** Reaper guardrail defaults (env knobs: see reapStaleFixtures). */
export const FIXTURE_REAPER_DEFAULTS = {
  maxAgeSec: 6 * 3600,   // SANDBAR_FIXTURE_MAX_AGE_SEC
  maxCount: 50,          // SANDBAR_FIXTURE_MAX_COUNT
  maxTotalMb: 8192,      // SANDBAR_FIXTURE_MAX_TOTAL_MB (0 = size guardrail off)
  minLiveSec: 60,        // live floor for the count/size guardrails: never touch anything younger
}

/** Fixture root: the system temp dir by default; env-injectable so tests stay hermetic. */
function fixtureRoot() {
  return process.env.SANDBAR_FIXTURE_TMPDIR || tmpdir()
}

/** Read a non-negative integer env knob; missing/malformed falls back (a bad knob warns, never crashes a suite). */
export function fixtureKnob(name, fallback) {
  const raw = process.env[name]
  if (raw === undefined || raw === '') return fallback
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0) {
    console.error(`fixture reaper: malformed ${name}=${JSON.stringify(raw)} -> default ${fallback}`)
    return fallback
  }
  return Math.floor(n)
}

/* ---- Process-level fallbacks: every in-process terminal state reclaims the fixture ----
   Terminal-state matrix (each one checked):
   - normal completion / assertion failure / throw / process.exit() / uncaughtException /
     unhandledRejection -> the 'exit' event (node fires it for crashes and explicit exits alike);
   - SIGINT / SIGTERM -> explicit handlers (the default signal disposition does NOT fire 'exit'),
     reclaim synchronously, then exit 130 / 143;
   - SIGKILL (the executor's 900s timeout cap, or a plain kill -9) -> physically impossible to
     catch in-process; the entry sweep (reapStaleFixtures) is the net that reclaims it. */
const LIVE_FIXTURES = new Set()
let fallbacksArmed = false

/** Remove one fixture dir synchronously; a fallback path warns instead of throwing. */
function dropSync(p) {
  try { rmSync(p, { recursive: true, force: true, maxRetries: 3 }) }
  catch (e) { console.error(`fixture cleanup: sync rm failed for ${p}: ${e?.message || e}`) }
}

/** Reclaim every fixture registered by this process (synchronous); idempotent, safe next to dispose. */
export function reapLiveFixturesSync() {
  for (const p of [...LIVE_FIXTURES]) { LIVE_FIXTURES.delete(p); dropSync(p) }
}

/** Arm the process-level fallbacks (idempotent; registered when the first fixture is created). */
function armFixtureFallbacks() {
  if (fallbacksArmed) return
  fallbacksArmed = true
  process.on('exit', () => reapLiveFixturesSync())
  process.on('SIGINT', () => {
    console.error('fixture cleanup: SIGINT -> reaping live fixtures')
    reapLiveFixturesSync(); process.exit(130)
  })
  process.on('SIGTERM', () => {
    console.error('fixture cleanup: SIGTERM -> reaping live fixtures')
    reapLiveFixturesSync(); process.exit(143)
  })
  // Crash paths still exit non-zero: cleanup must never swallow a crash into green.
  process.on('uncaughtException', (e) => {
    console.error('FATAL uncaughtException:', e?.stack || e)
    reapLiveFixturesSync(); process.exit(1)
  })
  process.on('unhandledRejection', (e) => {
    console.error('FATAL unhandledRejection:', e?.stack || e)
    reapLiveFixturesSync(); process.exit(1)
  })
}

/** Bounded directory size: never follows symlinks (the fixture links node_modules/.venv), stops at the budget. */
function boundedDirSize(dir, budget = { entries: 20000, deadlineMs: 3000 }) {
  const deadline = Date.now() + budget.deadlineMs
  let bytes = 0, walked = 0, truncated = false
  const stack = [dir]
  while (stack.length) {
    if (Date.now() > deadline) { truncated = true; break }
    const cur = stack.pop()
    let ents
    try { ents = readdirSync(cur, { withFileTypes: true }) } catch { continue }
    for (const ent of ents) {
      if (walked++ >= budget.entries) { truncated = true; stack.length = 0; break }
      try {
        if (ent.isSymbolicLink()) continue
        const p = join(cur, ent.name)
        if (ent.isDirectory()) stack.push(p)
        else if (ent.isFile()) bytes += statSync(p).size
      } catch { /* race: the entry vanished or is unreadable — treat as gone */ }
    }
  }
  return { bytes, truncated }
}

/**
 * Entry sweep (stale reaper): before a fixture is created, clean same-prefix leftovers.
 * Criteria (mtime only — no implementation detail is anchored):
 *  1. age >= maxAgeSec -> always removed (default 6h; SANDBAR_FIXTURE_MAX_AGE_SEC);
 *  2. count guardrail: more than maxCount dirs (default 50; SANDBAR_FIXTURE_MAX_COUNT)
 *     -> oldest first until maxCount;
 *  3. size guardrail: total above maxTotalMb (default 8192; SANDBAR_FIXTURE_MAX_TOTAL_MB,
 *     0 disables) -> oldest first until inside the cap.
 * (2)/(3) never touch a dir younger than minLiveSec (60s): a parallel suite may be using it.
 * Scan/remove failures only warn — the sweep must never take a suite down.
 * Returns { root, removed, kept, removedByCount, removedBySize, totalBytes, truncated, error }.
 */
export async function reapStaleFixtures(opts = {}) {
  const root = opts.dir || fixtureRoot()
  const maxAgeSec = opts.maxAgeSec ?? fixtureKnob('SANDBAR_FIXTURE_MAX_AGE_SEC', FIXTURE_REAPER_DEFAULTS.maxAgeSec)
  const maxCount = opts.maxCount ?? fixtureKnob('SANDBAR_FIXTURE_MAX_COUNT', FIXTURE_REAPER_DEFAULTS.maxCount)
  const maxTotalMb = opts.maxTotalMb ?? fixtureKnob('SANDBAR_FIXTURE_MAX_TOTAL_MB', FIXTURE_REAPER_DEFAULTS.maxTotalMb)
  const minLiveSec = opts.minLiveSec ?? FIXTURE_REAPER_DEFAULTS.minLiveSec
  const log = opts.log ?? ((m) => console.log(m))
  const warn = opts.warn ?? ((m) => console.error(m))
  const now = opts.now ?? Date.now()
  const out = {
    root, removed: 0, kept: 0, removedByCount: 0, removedBySize: 0,
    totalBytes: 0, truncated: false, error: '',
  }
  let entries
  try {
    entries = readdirSync(root, { withFileTypes: true })
      .filter((e) => e.name.startsWith(FIXTURE_PREFIX) && e.isDirectory())
      .map((e) => {
        const p = join(root, e.name)
        return { name: e.name, path: p, ageSec: Math.max(0, Math.round((now - statSync(p).mtimeMs) / 1000)) }
      })
  } catch (e) {
    out.error = String(e?.message || e)
    warn(`fixture reaper: scan failed for ${root}: ${out.error}`)   // warn only, never block
    return out
  }
  if (maxAgeSec < minLiveSec) {
    warn(`fixture reaper: SANDBAR_FIXTURE_MAX_AGE_SEC=${maxAgeSec}s is aggressive (<${minLiveSec}s): live parallel suites can be reclaimed`)
  }

  const del = async (item, why) => {
    try { await rm(item.path, { recursive: true, force: true, maxRetries: 3 }); item.gone = true; return true }
    catch (e) { warn(`fixture reaper: ${why} failed for ${item.path}: ${e?.message || e}`); return false }
  }

  // 1) anything at or above the age threshold goes
  const stale = entries.filter((e) => e.ageSec >= maxAgeSec)
  const live = entries.filter((e) => e.ageSec < maxAgeSec)
  for (const s of stale) if (await del(s, 'stale removal')) out.removed++

  // 2)/3) guardrails: oldest first, protected by the live floor
  const pool = live.filter((e) => e.ageSec >= minLiveSec).sort((a, b) => b.ageSec - a.ageSec)
  let liveCount = live.length
  if (liveCount > maxCount) {
    const named = []
    for (const item of pool) {
      if (liveCount <= maxCount) break
      if (await del(item, 'count-cap removal')) { liveCount--; out.removedByCount++; named.push(`${item.name}(${item.ageSec}s)`) }
    }
    log(`fixture reaper: count cap ${maxCount} exceeded (live=${live.length}) -> removed ${out.removedByCount} oldest (>=${minLiveSec}s floor)${named.length ? ': ' + named.join(', ') : ''}`)
  }
  if (maxTotalMb > 0 && live.some((e) => !e.gone)) {
    for (const item of live.filter((e) => !e.gone)) {
      const measured = boundedDirSize(item.path)
      item.bytes = measured.bytes
      out.truncated = out.truncated || measured.truncated
      out.totalBytes += measured.bytes
    }
    const capBytes = maxTotalMb * 1024 * 1024
    if (out.totalBytes > capBytes) {
      const named = []
      let total = out.totalBytes
      for (const item of pool) {          // pool = oldest first, live floor already applied
        if (total <= capBytes) break
        if (item.bytes === undefined || item.gone) continue
        if (await del(item, 'size-cap removal')) {
          total -= item.bytes; out.removedBySize++
          named.push(`${item.name}(${Math.round(item.bytes / 1048576)}MB,${item.ageSec}s)`)
        }
      }
      out.totalBytes = total
      log(`fixture reaper: total size cap ${maxTotalMb}MB exceeded -> removed ${out.removedBySize} oldest (>=${minLiveSec}s floor)${named.length ? ': ' + named.join(', ') : ''}`
        + (out.truncated ? ' [measurement truncated: the size cap is best-effort, the count cap is the primary net]' : ''))
    }
  }
  out.kept = entries.length - out.removed - out.removedByCount - out.removedBySize
  log(`fixture reaper: removed ${out.removed} stale dirs (>=${maxAgeSec}s) | kept ${out.kept} live`)
  return out
}

/**
 * Build a throwaway fixture repo (the stub worker's home): sweep stale fixtures,
 * clone the local checkout (--depth 1), symlink gitignored dependency dirs (node_modules /
 * engine/.venv — verify_lane needs them inside the lane), and drop the epic
 * file suggest_next needs. Returns { fixture, mainCheckout, tmp, dispose, disposeSync };
 * returns null when impossible (with an ENV_FAIL note; the fixture dir is reclaimed either way).
 * opts (all optional, injection points for the L1 regression): repo / mainCheckout /
 * tmpBase / reap=false.
 */
export async function buildFixture(t, opts = {}) {
  const root = opts.tmpBase || fixtureRoot()
  if (opts.reap !== false) {
    try { await reapStaleFixtures({ dir: root, ...(opts.reapOpts || {}) }) }
    catch (e) { console.error(`fixture reaper: unexpected failure (not blocking): ${e?.message || e}`) }
  }
  const tmp = await mkdtemp(join(root, FIXTURE_PREFIX))
  armFixtureFallbacks()
  LIVE_FIXTURES.add(tmp)
  let disposed = false
  /** Reclaim the fixture dir; idempotent (safe twice, safe next to the process fallbacks). */
  const dispose = async () => {
    if (disposed) return
    disposed = true
    LIVE_FIXTURES.delete(tmp)
    try { await rm(tmp, { recursive: true, force: true, maxRetries: 3 }) }
    catch (e) { console.error(`fixture cleanup: dispose failed for ${tmp}: ${e?.message || e}`) }
  }
  const disposeSync = () => { if (disposed) return; disposed = true; LIVE_FIXTURES.delete(tmp); dropSync(tmp) }
  const srcRepo = opts.repo || REPO
  const common = opts.mainCheckout
    ? { status: 0, stdout: opts.mainCheckout, stderr: '' }
    : run('git', ['-C', srcRepo, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
  const mainCheckout = opts.mainCheckout || (common.status === 0 ? dirname(common.stdout.trim()) : '')
  if (!mainCheckout || !existsSync(mainCheckout)) {
    t?.envFailNote?.(`cannot locate the local main checkout (${common.stderr.trim().slice(0, 120)}): fixture clone source unavailable`)
    await dispose()
    return null
  }
  const fixture = join(tmp, 'fixture')
  // The fixture follows the current checkout HEAD, not a pinned main: while
  // engine contracts evolve, pinning main creates a new/old split-brain
  // (ticket t260907-04 proven: the lane client starts workflows under the new
  // queue name, but a fixture worker on the old engine waits forever on the
  // old env=workflow). After merge lane==main and behavior is unchanged.
  const clone = run('git', ['clone', '--depth', '1', srcRepo, fixture], { timeoutMs: 300_000 })
  if (clone.status !== 0) {
    t?.envFailNote?.(`git clone main failed: ${(clone.stderr || clone.stdout).trim().slice(0, 200)}`)
    await dispose()
    return null
  }
  run('git', ['-C', fixture, 'config', 'user.email', 'e2e@suyou.test'])
  run('git', ['-C', fixture, 'config', 'user.name', 'integ-e2e'])
  // Everything below runs inside the post-mkdtemp guard: any throw here reclaims the
  // fixture dir before the error leaves buildFixture (no "fixture made, then failed" window).
  try {
    // Fixture-ize the project registry (ticket t260907-04): the machine-level
    // registry's suyou key points at the retired repo (auto-migration residue,
    // dirs are dead paths), so lane derivation would always blow up on a dead
    // project root (symptom: prepare_workspace reports missing git identity).
    // The scenario pins the registry into the fixture: the key stays the same
    // (the engine must keep serving existing keys), dirs point at the fixture
    // itself, and the whole chain stays hermetic off machine state.
    const projectsDir = join(fixture, '.e2e-projects', 'suyou')
    await mkdir(projectsDir, { recursive: true })
    // .migrated marker: the fixture table and the migration source (the
    // projects.yaml seed cloned inside the fixture) share keys but differ in
    // content, so the consistency check would judge a "mixed scene" fail-closed
    // — the fixture table is a self-contained manual registry, so add the
    // marker to pass the "already migrated" criterion.
    await writeFile(join(fixture, '.e2e-projects', '.migrated'), 'fixture-local hermetic registry (t260907-04)\n')
    await writeFile(join(projectsDir, 'project.yaml'),
      `# fixture-local registry (t260907-04): hermetic project entry, dirs -> fixture itself\n`
      + 'schema: v1\n'
      + 'project:\n'
      + '  - key: suyou\n'
      + '    name: integ-e2e-fixture\n'
      + '    dirs:\n'
      + `      - ${fixture}\n`)
    // Dependency symlinks: prepare_workspace symlinks gitignored dirs from the
    // worker REPO_ROOT (=fixture) into the lane; prepare the link targets in
    // the fixture first.
    for (const [link, target] of [
      [join(fixture, 'app', 'node_modules'), join(mainCheckout, 'app', 'node_modules')],
      [join(fixture, 'server', 'engine', '.venv'), join(mainCheckout, 'server', 'engine', '.venv')],
    ]) {
      if (existsSync(target)) {
        await mkdir(dirname(link), { recursive: true })
        await symlink(target, link).catch(() => {})
      }
    }
    // The epic archive file suggest_next needs (worker-side EPICS_DIR=fixture).
    await mkdir(join(fixture, 'notes', 'epics'), { recursive: true })
    await writeFile(join(fixture, 'notes', 'epics', `${EPIC_CODE}.md`),
      '# 立项单：integ-e2e\n\n| 字段 | 值 |\n| --- | --- |\n| 代号 | `integ-e2e` |\n| 状态 | 已立项（执行中） |\n', 'utf8')
  } catch (e) {
    await dispose()
    throw e
  }
  return { fixture, mainCheckout, tmp, dispose, disposeSync }
}

/* ------------------------------------------------------------------ client.py bridge */

function client(sdkPython, op, args, extraEnv = {}) {
  const env = targetEnv()
  if (extraEnv.epicsDir) env.SANDBAR_EPICS_DIR = extraEnv.epicsDir
  if (extraEnv.projectsDir) env.SANDBAR_PROJECTS_DIR = extraEnv.projectsDir
  // 261001 修（与 lib_stage_console.mjs 的同款口径）：跨项目闸（t260915-12 族）要求
  // **调用方项目身份显式声明**且与目标票所属项目一致，否则 ticket-start / ticket op 一律
  // fail-closed 拒收（实案：`跨项目写操作拒收：调用方项目身份未声明…目标票属项目 suyou`
  // ⇒ 票根本没建起来 ⇒ 场景报「workflow disappeared」）。夹具票都建在 suyou 项目下，
  // 故此处按夹具项目声明调用方身份（缺省不设=保持其它调用方原行为）。
  if (extraEnv.callerProject) env.SANDBAR_CALLER_PROJECT = extraEnv.callerProject
  const r = run(sdkPython, [join(POC, 'client.py'), op, JSON.stringify(args)],
    { env, timeoutMs: extraEnv.timeoutMs ?? 120_000 })
  let body = null
  try { body = JSON.parse(r.stdout) } catch { /* surfaced below */ }
  return { ...r, body }
}

export function makeApi(sdkPython, fixture) {
  const epicsDir = join(fixture, 'notes', 'epics')
  // 夹具票一律建在 suyou 项目下（见 start() 的 project 字段）⇒ 调用方身份跟它对齐
  const env = { epicsDir, projectsDir: join(fixture, '.e2e-projects'), callerProject: 'suyou' }
  return {
    async start(ticketId, writeSet) {
      return client(sdkPython, 'ticket-start', {
        ticket_id: ticketId, template_id: 'dev-lane', project: 'suyou',
        title: `[e2e] 工单全链 ${ticketId}`, epic: EPIC_CODE,
        user_request: 'integration baseline: stub-brain full-chain ticket lifecycle',
        write_set: writeSet,
      }, env)
    },
    query: (tid) => client(sdkPython, 'ticket-query', { ticket_id: tid }, env),
    sign: (tid, who, decision, note, gate = 'merge') =>
      client(sdkPython, 'ticket', { op: 'sign', ticket_id: tid, input: { who, gate, decision, note } }, env),
    rework: (tid, toStage, note, who = 'e2e') =>
      client(sdkPython, 'ticket', { op: 'rework', ticket_id: tid, to_stage: toStage, note, who }, env),
    cancel: (tid) => client(sdkPython, 'cancel', { workflow_id: tid }, env),
  }
}

/* ------------------------------------------------------------------ worker */

/**
 * Start a per-ticket stub worker from the fixture repo's own engine
 * (REPO_ROOT=fixture). WATCH mode self-exits after the workflow leaves
 * RUNNING; blocked steady-state and failure paths are reaped by own().
 */
export function startStubWorker(fixture, sdkPython, ticketId) {
  const child = spawn(sdkPython, [join(fixture, 'server', 'engine', 'worker.py')], {
    env: targetEnv({
      SANDBAR_TASK_QUEUES: `sandbar-ticket-${ticketId},suyou-ticket-${ticketId}`,  // naming-compat（新旧双前缀 CSV=ticket_worker.spawn 同款契约，t260907-04）
      SANDBAR_PROJECTS_DIR: join(fixture, '.e2e-projects'),  // registry fixture-ized (ticket t260907-04: the machine seed key points at the retired repo)
      SANDBAR_WATCH_WORKFLOW: ticketId,
      // Watch fast mode (ticket t260905-02 knob): after the scenario's
      // cancel, worker self-exit shrank from slow mode 30s per round to ~4s
      // — cleanupTicket's 90s wait-for-exit window was previously always
      // eaten up by slow mode (260909 timing proven).
      SANDBAR_WATCH_INTERVAL_SEC: '4',
      SANDBAR_AGENT_STUB: '1',
      SANDBAR_SUGGEST_STUB: 'ok',
      SANDBAR_UI_CAPTURE_STUB: '1',
    }),
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  child.stderr.on('data', () => {}) // drained; keep the pipe from backing up
  child.stdout.on('data', () => {})
  return own(child)
}

/* ------------------------------------------------------------------ driving helpers */

const sleep = (ms) => new Promise(r => setTimeout(r, ms))

/** Poll ticket-query until pred(snapshot) holds. Returns the last snapshot or null. */
export async function waitFor(api, tid, pred, label, deadlineMs, t) {
  const end = Date.now() + deadlineMs
  let snap = null
  while (Date.now() < end) {
    const r = api.query(tid)
    snap = r.body?.ok ? r.body.result.snapshot : null
    if (snap && pred(snap)) return snap
    if (!snap && r.body && r.body.ok === false && /不存在|not found/i.test(r.body.error || '')) {
      t?.ok?.(false, `${label}: workflow disappeared (${r.body.error})`)
      return null
    }
    await sleep(2000)
  }
  t?.ok?.(false, `${label}: timed out after ${Math.round(deadlineMs / 1000)}s (last stage=${snap?.stage}/${snap?.stage_state})`)
  return null
}

/** Derive the absolute lane worktree path inside the fixture from a snapshot. */
export function lanePath(fixture, snap) {
  const p = snap?.meta?.workspace?.path || snap?.meta?.worktree || ''
  if (!p) return ''
  return p.startsWith('/') ? p : join(fixture, p)
}

/**
 * Pre-seed the next arbitrate result file (max existing gen + 1) with a
 * summary carrying verdict=pass. Call it while the ticket is busy in
 * run_integration_tests: the idempotent cache then returns it
 * deterministically.
 */
export async function seedArbitratePass(lane) {
  const dir = join(lane, '.suyou')  // naming-compat
  let maxGen = -1
  if (existsSync(dir)) {
    for (const f of await readdir(dir)) {
      const m = /^stage_arbitrate_gen(\d+)\.json$/.exec(f)
      if (m) maxGen = Math.max(maxGen, Number(m[1]))
    }
  }
  const gen = maxGen + 1
  await mkdir(dir, { recursive: true })
  await writeFile(join(dir, `stage_arbitrate_gen${gen}.json`), JSON.stringify({
    status: 'ok',
    summary: '集成测试三态判定：verdict=pass（全部机械测试通过；E2E 预置结果文件，走引擎幂等缓存路径）',
    report: '[e2e seeded] verdict=pass',
    deliverables: [], files_changed: [],
    evidence: 'seeded by integration/baselines ticket-lifecycle (stub-brain determinism lever)',
    prompt: '(seeded; real prompt patched by _patch_result_prompt on cache hit)',
  }, null, 1) + '\n', 'utf8')
  return gen
}

/** Drop a probe file into the lane (integration/ is on the write-set exemption list). */
export async function writeProbe(lane, name) {
  const p = join(lane, 'integration', name)
  await mkdir(dirname(p), { recursive: true })
  await writeFile(p, `probe written by ticket-lifecycle e2e at ${new Date().toISOString()}\n`, 'utf8')
  return p
}

/* ------------------------------------------------------------------ scenes */

const SCENE_DEADLINE_MS = 10 * 60 * 1000 // ticket contract: <=10 min per scene

async function driveToMergeGate(t, api, sdkPython, fixture, tid, seed = true) {
  // 1) workspace ready -> write the probe (must dirty the lane before the join settle)
  const ready = await waitFor(api, tid, (s) => !!s?.meta?.workspace_prep?.ok,
    'workspace ready', 120_000, t)
  if (!ready) return null
  const lane = lanePath(fixture, ready)
  if (!lane) { t.ok(false, 'snapshot.meta.workspace.path missing'); return null }
  const probeName = `e2e-probe-${tid}.txt`
  await writeProbe(lane, probeName)
  // 2) pre-seed arbitrate verdict=pass during the mechanical run_integration_tests busy window
  if (seed) {
    const s = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'run_integration_tests reached', SCENE_DEADLINE_MS, t)
    if (!s) return null
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 0, `arbitrate verdict=pass pre-seeded (gen${gen})`)
  }
  // 3) wait for the human gate
  const snap = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
    'merge human gate', SCENE_DEADLINE_MS, t)
  return snap ? { snap, lane, probeName } : null
}

/** Scene A: full-chain happy path -> approve -> closed + lane cleanup + suggest_next. */
export async function sceneA(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-a-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid,[`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || r.stderr).slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    lane = gate.lane
    const s = gate.snap
    const expected = ['workspace', 'create_plan', 'review_plan', 'implement',
      'design_integration_tests', 'run_integration_tests', 'arbitrate',
      'acceptance_walkthrough', 'merge_check', 'merge']
    const tl = (s.timeline || []).map(e => e.stage)
    const idx = expected.map(st => tl.indexOf(st))
    const seenAll = idx.every(i => i >= 0)
    const inOrder = seenAll && idx.every((v, k) => k === 0 || v > idx[k - 1])
    t.ok(seenAll && inOrder, `timeline covers the full stage chain in STAGES order (got: ${tl.join('>')})`)
    for (const st of ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
      'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check']) {
      t.ok(!!s.results?.[st], `checks ledger has ${st} entry`)
    }
    const mc = (s.gate_runs || []).filter(g => g.stage === 'merge_check').pop()
    t.ok(mc?.green === true, `merge_check four checks green (detail: ${JSON.stringify(mc?.checks?.map(c => [c.item, c.green])) || 'none'})`)
    t.ok(s.signatures?.merge === undefined, 'merge gate is awaiting signature (not yet signed)')
    // write-set exemption evidence: integration/ is exempt, but the probe still gets committed
    const log = run('git', ['-C', lane, 'log', '--name-only', '--pretty=format:', '-5'])
    t.ok(log.stdout.includes(gate.probeName), 'integration/ probe file landed in a lane commit (write-set exemption)')
    // approve -> real merge + lane cleanup + suggest_next + closed
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 A 放行').body?.ok === true, 'sign approve delivered')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    if (!fin) return
    t.ok(fin.status === 'closed', `terminal status is closed (not legacy settled): ${fin.status}`)
    t.ok(!existsSync(lane), 'lane worktree removed after merge (fixture cleanup)')
    const br = run('git', ['-C', fixture, 'branch', '--list', fin.meta?.branch || 'lane/*'])
    t.ok(!br.stdout.trim(), 'lane branch deleted after merge')
    t.ok(existsSync(join(fixture, '.suyou', 'epic-next', EPIC_CODE, 'pre.json')),  // naming-compat
      'suggest_next pre-ran: fixture .suyou/epic-next/<code>/pre.json exists')  // naming-compat
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene B: merge human-gate reject -> back to implement with a note -> approve again -> closed. */
export async function sceneB(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-b-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const note = 'E2E reject 意见：探针自测不足，请补充'
    const r = await api.start(tid,['integration/README.md'])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    t.ok(api.sign(tid, 'e2e-human', 'reject', note).body?.ok === true, 'sign reject (with note) delivered')
    const atImpl = await waitFor(api, tid, (x) => x?.stage === 'implement',
      'reject routed back to implement', SCENE_DEADLINE_MS, t)
    if (!atImpl) return
    t.ok(String(atImpl.meta?.log?.map(l => l.note).join('｜')).includes('人在 merge 打回'),
      'reject logged as human merge rework')
    // Redo re-enters arbitrate at gen1: seed the next generation again when
    // the manifest re-runs, otherwise the stub brain has no verdict= and hits
    // the format round limit
    const busy2 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'manifest re-running after reject', SCENE_DEADLINE_MS, t)
    if (!busy2) return
    const gen = await seedArbitratePass(lanePath(fixture, busy2))
    t.ok(gen >= 1, `arbitrate pass re-seeded for the redo (gen${gen})`)
    const back = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'back at merge gate after redo', SCENE_DEADLINE_MS, t)
    if (!back) return
    // prev_ctx assertion: read the lane result file directly (snapshot results don't carry prompt)
    const impl1 = join(lanePath(fixture, back), '.suyou', 'stage_implement_gen1.json')  // naming-compat
    let prompt = ''
    try { prompt = JSON.parse(await readFile(impl1, 'utf8')).prompt || '' } catch { /* below */ }
    t.ok(prompt.includes(`人在 merge 打回：${note}`), 'redo prompt injects the reject note (prev_ctx via lane result file)')
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 B 复核通过').body?.ok === true, 'second visit: sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'reject->redo->approve chain ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene C: manual rework (real routing + context inheritance + gen bump) + malformed signals. */
export async function sceneC(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-c-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const r = await api.start(tid,['integration/manifest.json'])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // malformed #1: sign while the ticket is not awaiting (still in create_plan)
    const running = await waitFor(api, tid, (x) => x?.stage === 'create_plan', 'create_plan running', 120_000, t)
    if (!running) return
    const refusedBefore = (running.refused || []).length
    api.sign(tid, 'e2e-human', 'approve', ' premature sign (should be refused) ')
    const after = await waitFor(api, tid, (x) => (x?.refused || []).length > refusedBefore,
      'premature sign lands in refused', 60_000, t)
    t.ok(!!after && (after.refused || []).length > refusedBefore,
      'malformed sign (non-awaiting state) -> refused entry, stage untouched')
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    // malformed #2/#3: rework to a nonexistent stage, rework to an inline stage
    const refusedAtGate = (gate.snap.refused || []).length
    api.rework(tid, 'no_such_stage_xyz', 'E2E malformed rework: nonexistent target')
    const m2 = await waitFor(api, tid, (x) => (x?.refused || []).length > refusedAtGate,
      'rework(nosuch) refused', 60_000, t)
    t.ok(!!m2 && m2.stage === 'merge' && m2.stage_state === 'awaiting-human',
      'malformed rework (nonexistent stage) -> refused, ticket stays at the merge gate')
    api.rework(tid, 'suggest_next', 'E2E malformed rework: inline stage')
    const m3 = await waitFor(api, tid, (x) => (x?.refused || []).length > (m2?.refused || []).length,
      'rework(suggest_next) refused', 60_000, t)
    t.ok(!!m3 && m3.stage === 'merge' && m3.stage_state === 'awaiting-human',
      'malformed rework (inline suggest_next) -> refused, ticket stays at the merge gate')
    // legal rework: back to acceptance_walkthrough (a real STAGES id)
    const note = 'E2E rework 意见：走查报告需补充边界场景'
    t.ok(api.rework(tid, 'acceptance_walkthrough', note).body?.ok === true, 'rework -> acceptance_walkthrough delivered')
    const atAcc = await waitFor(api, tid, (x) => x?.stage === 'acceptance_walkthrough',
      'routed back to acceptance_walkthrough', SCENE_DEADLINE_MS, t)
    if (!atAcc) return
    const back = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'back at merge gate after rework loop', SCENE_DEADLINE_MS, t)
    if (!back) return
    const acc1 = join(lanePath(fixture, back), '.suyou', 'stage_acceptance_walkthrough_gen1.json')  // naming-compat
    let prompt = ''
    try { prompt = JSON.parse(await readFile(acc1, 'utf8')).prompt || '' } catch { /* below */ }
    t.ok(prompt.includes(note), 'rework prompt inherits the note (context inheritance, lane result file)')
    t.ok(String(back.meta?.last_rework_note || '') === note, 'meta.last_rework_note recorded (round accounting)')
    const gens = (back.timeline || []).filter(e => e.stage === 'acceptance_walkthrough').length
    t.ok(gens >= 2, `acceptance_walkthrough re-entered (gen bump, timeline entries=${gens})`)
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 C 收口').body?.ok === true, 'sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'rework loop ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene D: no verdict seeded -> real round limit (arbitrate format rounds) -> blocked -> revive. */
export async function sceneD(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-d-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid,[`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    // Deviation note (scene D originally said "merge repeatedly rejected hits
    // the round limit"; the engine has no reject counter — this scene takes
    // the real limit: the stub brain's arbitrate summary lacks verdict=, so
    // 3 format-correction rounds -> blocked).
    // The probe must dirty the lane before the parallel join's settle: that
    // meet commit is what satisfies run_integration_tests's 0-commit precheck
    // ("implementation not persisted"). Waiting for the mechanical step is too
    // late — the precheck fires first and blocks for the wrong reason. So:
    // write the probe as soon as the workspace is ready, then wait.
    const ready = await waitFor(api, tid, (x) => !!x?.meta?.workspace_prep?.ok,
      'workspace ready', 120_000, t)
    if (!ready) return
    lane = lanePath(fixture, ready)
    await writeProbe(lane, probeName)
    const blocked = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'arbitrate round-limit -> blocked', SCENE_DEADLINE_MS, t)
    if (!blocked) return
    const logs = (blocked.meta?.log || []).map(l => l.note).join('｜')
    t.ok(blocked.stage === 'arbitrate', 'blocked at arbitrate (stage preserved)')
    t.ok(logs.includes('times missing verdict= marker'), 'blocked note names the missing verdict= marker')
    t.ok((blocked.timeline || []).filter(e => e.stage === 'arbitrate').length >= 3,
      'three arbitrate format rounds in the timeline (round limit reached)')
    // Revive: rework -> implement; seed the next arbitrate when the manifest re-runs
    t.ok(api.rework(tid, 'implement', 'E2E：补预置后重跑').body?.ok === true, 'rework -> implement (revive)')
    const busy = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'manifest re-running after revive', SCENE_DEADLINE_MS, t)
    if (!busy) return
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 1, `arbitrate pass seeded at polled gen${gen} (not statically guessed)`)
    const gate = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'revived ticket reaches merge gate', SCENE_DEADLINE_MS, t)
    if (!gate) return
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 D 收口').body?.ok === true, 'sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'blocked -> rework -> approve chain ends closed')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/** Scene E: write-set lifecycle assertions on a dedicated ticket (refresh + exemption). */
export async function sceneE(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-e-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const initialWs = [`integration/${probeName}`, 'integration/README.md']
    const r = await api.start(tid,initialWs)
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : (r.body?.error || '').slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const ready = await waitFor(api, tid, (x) => !!x?.meta?.workspace_prep?.ok, 'workspace ready', 120_000, t)
    if (!ready) return
    const lane = lanePath(fixture, ready)
    await writeProbe(lane, probeName)
    // initial write_set booked as-is
    t.ok(JSON.stringify([...(ready.meta?.write_set || [])].sort()) === JSON.stringify([...initialWs].sort()),
      `initial meta.write_set equals ticket-start input (${JSON.stringify(ready.meta?.write_set)})`)
    // write-set refresh after review_plan finalization (union; the stub's
    // files_changed=[] leaves the set alone — a log line makes that explicit)
    const refreshed = await waitFor(api, tid,
      (x) => String((x?.meta?.log || []).map(l => l.note).join('｜')).includes('写集已随方案定稿刷新'),
      'write-set refreshed on plan finalization', SCENE_DEADLINE_MS, t)
    if (!refreshed) return
    t.ok((refreshed.meta?.write_set || []).length >= initialWs.length,
      'meta.write_set after refresh still covers the initial set (union semantics)')
    // authorized-extension pure-function half (deterministic, race-free):
    // refresh_write_set unions plan files into the set and logs new entries
    // as "authorized extension"
    const py = run(sdkPython, ['-c', `
import sys, json
sys.path.insert(0, ${JSON.stringify(POC)})
from shared import refresh_write_set
merged, added, dropped = refresh_write_set(["a.txt"], ["integration/new-probe.txt", "a.txt"])
print(json.dumps({"merged": merged, "added": added, "dropped": dropped}))`], { timeoutMs: 30_000 })
    let ext = null
    try { ext = JSON.parse(py.stdout.trim()) } catch { /* surfaced by the assert below */ }
    t.ok(ext?.merged?.includes('integration/new-probe.txt') && (ext?.added || []).includes('integration/new-probe.txt'),
      'refresh_write_set unions plan files (authorized extension) and integration/ entries survive')
    // exemption half: the integration/ probe (not on the writable-code list
    // at all) is committed by settle_lane, and verify_lane's write-set
    // whitelist stays green
    const gate = await driveToMergeGate(t, api, sdkPython, fixture, tid)
    if (!gate) return
    const log = run('git', ['-C', gate.lane, 'log', '--name-only', '--pretty=format:', '-5'])
    t.ok(log.stdout.includes(probeName), 'integration/ probe committed (exemption holds in the real settle)')
    const mc = (gate.snap.gate_runs || []).filter(g => g.stage === 'merge_check').pop()
    const wsCheck = (mc?.checks || []).find(c => String(c.item).includes('写集白名单'))
    t.ok(mc?.green === true && (wsCheck === undefined || wsCheck.green === true),
      'merge_check green with the probe in the commit (whitelist + exemption)')
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 场景 E 收口').body?.ok === true, 'sign approve')
    await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/* ------------------------------------------------------------------ cleanup */

/**
 * Best-effort close-out: cancel the ticket + reap the worker + handle the
 * fixture repo. Unlike borrowed integration baseline patterns: leftover
 * integ-e2e tickets are our own system under test, so a cancel failure counts
 * as a scenario red (silently polluting the namespace is not allowed).
 */
export async function cleanupTicket(t, api, worker, tid) {
  // Probe the terminal state first; when the probe fails (query times out —
  // during a blocked retry storm queries can starve, 260909 proven) never bypass
  // cancel: the old implementation skipped everything on one query exception,
  // cancel never went out, and the worker could only be SIGKILLed at the 90s
  // deadline.
  let closed = false
  try {
    const q = api.query(tid)
    closed = q.body?.result?.status === 'closed'
  } catch { /* query failure counts as non-terminal: cancel is best-effort close-out, not a fake red */ }
  if (!closed) {
    try {
      const c = api.cancel(tid)
      // client.py cancel keys by workflow_id (dev-lane ticket id = ticket
      // number); benign errors for already-terminal / deregistered are not
      // failures.
      const errTxt = String((c && (c.body?.error || c.stderr)) || '')
      const benign = /not[ -]?found|不存在|already completed|已收口|已终态|closed/i.test(errTxt)
      if (c.body?.ok !== true && !benign) {
        t.ok(false, `cancel ${tid} failed: ${errTxt.slice(0, 120)}`)
      }
    } catch (e) {
      t.ok(false, `cancel ${tid} threw: ${String(e).slice(0, 120)}`)
    }
  }
  if (worker) {
    const deadline = Date.now() + 90_000 // WATCH self-exit for closed/cancelled
    while (!worker.done && Date.now() < deadline) await sleep(1000)
    if (!worker.done) await worker.kill() // blocked steady-state or hung: owner reaps
    t.ok(worker.done || worker.reaped, `worker for ${tid} fully reaped (WATCH exit or owner kill)`)
  }
}

export const SCENE_TIMEOUT_BUDGET_MS = SCENE_DEADLINE_MS
