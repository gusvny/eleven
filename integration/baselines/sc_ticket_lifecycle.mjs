/**
 * Baseline: full ticket lifecycle E2E (group 5) -- real state machine, stub brains.
 *
 * Intent:
 *   Lock the CURRENT dev-lane engine chain end to end: real Docker test Temporal
 *   (17233 / suyou-test) + real per-ticket worker + real settle / merge / lane  // naming-compat
 *   cleanup / human gates. The only stubs are the agent brains (SANDBAR_AGENT_STUB=1
 *   stages self-complete, zero model calls). Terminal status is `closed` (the
 *   legacy `settled` name is gone), the only human gate is merge (exit=human), and
 *   implement || design_integration_tests really forks in parallel.
 *
 * Scenes (one shared fixture repo per run, one ticket per scene, prefix integ-e2e-):
 *   A. happy path full chain -> approve -> closed + lane cleanup + suggest_next.
 *   B. merge-gate reject (with note) -> back to implement (note injected) -> redo -> approve -> closed.
 *   C. manual rework (route + context inheritance + gen bump) + malformed-signal refused contract.
 *   D. round limit (the real one: stub arbitrate lacks verdict=, 3 format rounds -> blocked) -> revive -> closed.
 *      Ticket-body deviation, on record: the original ask "round limit via repeated
 *      merge rejects" is unreachable -- the engine counts no merge-reject rounds
 *      (dev_lane.py merge gate). Engine finding, separate ticket.
 *   E. write-set lifecycle: refresh on plan finalization (union + authorized
 *      extension) + integration/ exemption in the real settle.
 *
 * Two run modes, decided by env:
 *   - Top-level (human/maintenance run): neither SANDBAR_TASK_QUEUE nor
 *     SANDBAR_WATCH_WORKFLOW is set -> scenes execute.
 *   - Inside a lane's mechanical integration step: the worker env carries
 *     SANDBAR_TASK_QUEUE / SANDBAR_WATCH_WORKFLOW, and _run_manifest inherits it -> the
 *     nested guard records ENV_FAIL loudly (exit 2) instead of recursing (each nested run would clone a
 *     fixture, start a worker and spawn integ-e2e- tickets: unbounded recursion).
 *     Consequence, on record: this manifest entry always records env_fail inside the engine's
 *     mechanical step. That is the nested-safety guard working as designed, not a
 *     dead entry -- real coverage happens in top-level runs (ticket body requires
 *     the manifest registration; the t260831-03 shell avoided registering for the
 *     same reason; the conflict is resolved in favor of registering, per ticket).
 *
 * Pure halves (always run when not nested): write-guard triad + nested-guard matrix.
 * Env halves (SDK + test Temporal + fixture clone required, otherwise ENV_FAIL, exit 2):
 *     scenes A-E, each with its own worker lifecycle (WATCH self-exit + owner kill).
 *
 * Write-guard (this test creates tickets; it refuses an unclear target):
 *   SANDBAR_TARGET_HOST unset -> ENV_FAIL loudly (exit 2); == production default 127.0.0.1:7233
 *   -> FAIL; anything else must equal the pinned test env 127.0.0.1:17233.
 */

import {
  makeTally, writeGuard, findSdkPython, ensureTestTemporal, buildFixture, makeApi,
  sceneA, sceneB, sceneC, sceneD, sceneE,
} from './ticket-lifecycle-scenes.mjs'

let pass = 0, fail = 0, envFail = 0
const tally = makeTally()

/** The nested-run guard: any dedicated-worker env marker means "inside a lane". */
export function nestedGuard(env = process.env) {
  return (env.SANDBAR_TASK_QUEUE || env.SANDBAR_TASK_QUEUES || env.SANDBAR_WATCH_WORKFLOW) ? 'nested' : 'top'
}

/** Fold the shared tally's counters (env_fail notes from env-chain helpers) into the module totals. */
function foldTally() {
  pass += tally.pass; fail += tally.fail; envFail += tally.envFail
  tally.pass = 0; tally.fail = 0; tally.envFail = 0
}

function summarize(label, t) {
  pass += t.pass; fail += t.fail; envFail += t.envFail
  if (t.envFail) console.log(`  (${label}: ${t.envFail} env_fail note(s) above)`)
}

async function main() {
  console.log('== full ticket lifecycle (stub-brain E2E: real test Temporal + real worker + real engine chain)')

  /* ---- pure half 1: nested guard (must come first; recursion breaks the budget) */
  if (nestedGuard() === 'nested') {
    envFail++
    console.log('  ENV_FAIL nested inside a lane integration step (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present): recursive guard, top-level runs carry the coverage')
    foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
    process.exit(2)
  }

  /* ---- pure half 2: write-guard triad (env simulated, then restored) */
  {
    const t = makeTally()
    t.section('P1 write-guard triad (simulated targets, env restored after)')
    const saved = process.env.SANDBAR_TARGET_HOST
    const withEnv = async (v, fn) => {
      if (v === undefined) delete process.env.SANDBAR_TARGET_HOST
      else process.env.SANDBAR_TARGET_HOST = v
      try { return await fn() } finally {
        if (saved === undefined) delete process.env.SANDBAR_TARGET_HOST
        else process.env.SANDBAR_TARGET_HOST = saved
      }
    }
    t.ok(await withEnv(undefined, writeGuard) === 'env_fail', 'unset SANDBAR_TARGET_HOST -> env_fail (client.py would default to production)')
    t.ok(await withEnv('127.0.0.1:7233', writeGuard) === 'fail', 'explicit production default -> fail (red line)')
    t.ok(await withEnv('127.0.0.1:9999', writeGuard) === 'fail', 'unclear target -> fail')
    t.ok(await withEnv('127.0.0.1:17233', writeGuard) === 'run', 'pinned test env -> run')
    // The env half itself follows the triad verdict of the real (saved) env value.
    const guard = writeGuard()
    summarize('write-guard', t)
    if (guard === 'fail') {
      foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
      process.exit(1)
    }
    if (guard === 'env_fail') {
      envFail++
      console.log('  ENV_FAIL write-guard: SANDBAR_TARGET_HOST not set explicitly -- refusing to create tickets on an unclear target (set SANDBAR_TARGET_HOST=127.0.0.1:17233)')
      foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
      process.exit(2)
    }
  }

  /* ---- env chain: SDK -> test Temporal -> fixture */
  const sdkPython = findSdkPython(tally)
  if (!sdkPython || !(await ensureTestTemporal(tally))) {
    foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
    process.exit(2)
  }
  const fixtureBuilt = await buildFixture(tally)
  if (!fixtureBuilt) {
    foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
    process.exit(2)
  }
  const { fixture, dispose } = fixtureBuilt
  const api = makeApi(sdkPython, fixture)

  /* ---- scenes A-E (independent tickets, sequential, shared fixture) */
  const scenes = [
    ['A happy path full chain', sceneA],
    ['B merge-gate reject loop', sceneB],
    ['C manual rework + malformed signals', sceneC],
    ['D round limit -> blocked -> revive', sceneD],
    ['E write-set lifecycle', sceneE],
  ]
  // 夹具回收放 finally（260926 磁盘泄漏修）：正常/断言失败/抛异常/超时早退一律走 dispose，
  // 进程内兜底（exit/SIGINT/SIGTERM）在 ticket-lifecycle-scenes.mjs 里另行武装。
  try {
    for (const [label, fn] of scenes) {
      const t = makeTally()
      t.section(label)
      try {
        await fn(t, api, sdkPython, fixture)
      } catch (e) {
        t.ok(false, `scene crashed: ${e?.stack || e}`)
      }
      summarize(label, t)
    }
  } finally {
    await dispose()
  }

  foldTally()
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
  process.exit(fail > 0 ? 1 : envFail > 0 ? 2 : 0)
}

await main()
