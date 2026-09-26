/**
 * t260917-01: arbitrate settle gate-refusal is NOT "missing verdict=" format rounds.
 *
 * Ticket (user words preserved in the ticket body): t260916-19/-21 both blocked as
 * "仲裁结论 3 次缺 verdict= 标记" while the true cause was a settle path-gate refusal
 * (path_gate_reason=unauthorized_path … integration/baselines/ticket-lifecycle-scenes.mjs).
 * The refusal note swallowed the arbitration summary, the format counter read
 * "conclusion missing" instead of "landing refused", and the count never went down
 * across human intervention (-21 reached a phantom "4th time") — the ticket could not
 * self-recover via rework/retry.
 *
 * Legs (one shared fixture repo, one ticket per leg, stub brains):
 *   L1 gate-refusal honest face + real-way-out revival:
 *      a rogue out-of-face test asset (integration/baselines/e2e-gate-probe-<tid>.txt:
 *      not sc_*, not test_face, not this ticket's receipt) lands in the lane before the
 *      join settle -> the arbitrate settle is refused -> blocked. Assertions on the
 *      public ticket face only (snapshot notes / timeline / blocked_detail):
 *      the note keeps the machine-readable path_gate_reason= key and the sanctioned
 *      way-out text, does NOT claim "缺 verdict= 标记", the timeline holds exactly one
 *      arbitrate blocked entry (format rounds untouched), blocked_detail carries
 *      reason_code=unauthorized_path and a non-empty next_action (detail-face gate is
 *      live for new instances). Then the documented way out actually works: remove the
 *      rogue file, rework, re-enter (no refusal anywhere -> "缺 verdict= 标记" stays the
 *      stated cause for a pure format round limit: zero regression of the existing
 *      chain), seed verdict=pass, merge human gate, sign -> closed. A ticket stuck at
 *      this state must be recoverable by following its own ticket face — the mirror of
 *      the reported "cannot self-recover" symptom.
 *   L2 format-counter reset across rework (t260916-21 "4th time" mirror):
 *      first round-limit blocked reads exactly "仲裁结论 3 次缺 verdict= 标记"; rework and
 *      re-enter without seeding anything: the second limit must read "3 次" again —
 *      never an accumulated "4+ 次". (The counter resets at the run_integration_tests
 *      entry; before the fix the face reads "4 次缺".) Leg ends at the second blocked
 *      assertion; the revival chain itself is proven by L1.
 *
 * Design anchors (grey-box: deep understanding, shallow binding):
 *   - assertions sit on public surfaces only (snapshot notes, timeline entries,
 *     meta.blocked_detail) — a contract-preserving refactor must not break this file;
 *   - acceptance mapping: ticket acceptance ③ (gate refusal -> face + next_action),
 *     ④ (existing arbitrate/KI-061 chain zero regression, L1 second blocked leg);
 *     ①② live in developer UTs, mirrored here only at whole-chain level;
 *   - KI lineage: KI-061 wake-rerun semantics (blocked -> rework -> edges really re-run,
 *     seeded verdicts are consumed) is exercised by both revival chains;
 *   - intent differs from baselines sc_ticket_lifecycle scene D (pure format round
 *     limit, no refusal): this file guards the refusal-vs-format decoupling and the
 *     counter reset; scene D remains the no-refusal regression anchor.
 *
 * Run modes (same contract as baselines/sc_ticket_lifecycle.mjs):
 *   - top-level runs carry the coverage; inside a lane's mechanical integration step the
 *     nested guard records ENV_FAIL loudly (exit 2) instead of recursing;
 *   - env halves need SDK + docker test Temporal (17233) + fixture clone, otherwise
 *     ENV_FAIL (exit 2); write-guard refuses unclear targets (production default = FAIL).
 */

import { writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'

import {
  makeTally, writeGuard, findSdkPython, ensureTestTemporal, buildFixture, makeApi,
  startStubWorker, waitFor, lanePath, seedArbitratePass, writeProbe, cleanupTicket,
} from '../baselines/ticket-lifecycle-scenes.mjs'

let pass = 0, fail = 0, envFail = 0
const tally = makeTally()

const SCENE_DEADLINE_MS = 10 * 60 * 1000 // ticket contract: <=10 min per wait leg

/** Fold the shared tally's counters into the module totals. */
function foldTally() {
  pass += tally.pass; fail += tally.fail; envFail += tally.envFail
  tally.pass = 0; tally.fail = 0; tally.envFail = 0
}

function printSummaryAndExit(code) {
  console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=${envFail}`)
  process.exit(code)
}

/** The nested-run guard: any dedicated-worker env marker means "inside a lane". */
function nestedGuard(env = process.env) {
  return (env.SANDBAR_TASK_QUEUE || env.SANDBAR_TASK_QUEUES || env.SANDBAR_WATCH_WORKFLOW) ? 'nested' : 'top'
}

/** Join all worker-side log notes of a snapshot into one searchable string. */
function allNotes(snap) {
  return (snap?.meta?.log || []).map(l => String(l?.note || '')).join('｜')
}

/**
 * L1 — gate refusal: honest face, format rounds untouched, way out actually works.
 */
async function legGateRefusal(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-gate-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid, [`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : String(r.body?.error || r.stderr).slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const ready = await waitFor(api, tid, (s) => !!s?.meta?.workspace_prep?.ok,
      'workspace ready', 120_000, t)
    if (!ready) return
    lane = lanePath(fixture, ready)
    if (!lane) { t.ok(false, 'snapshot.meta.workspace.path missing'); return }
    await writeProbe(lane, probeName)
    // Rogue out-of-face test asset: baselines/ is protected-shared AND not test_face —
    // the same two-gate refusal face t260916-21 hit on ticket-lifecycle-scenes.mjs.
    const rogueRel = `integration/baselines/e2e-gate-probe-${tid}.txt`
    await writeFile(join(lane, rogueRel), `rogue probe written by ${tid} (out-of-face test asset)\n`, 'utf8')

    const blocked1 = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'arbitrate settle gate refusal -> blocked', SCENE_DEADLINE_MS, t)
    if (!blocked1) return
    // Fork display caveat (KI-061 scene, 260908 empirical): during arb_acc_parallel the
    // snapshot's single stage field reports the last-entered edge, so a join-window
    // block may surface as acceptance_walkthrough. The timeline blocked entry carries
    // the true stage — asserted below via arbBlocked1.
    t.ok(['arbitrate', 'arb_acc_parallel', 'acceptance_walkthrough'].includes(blocked1.stage),
      `blocked inside the arbitrate join window (stage=${blocked1.stage}, fork display caveat)`)
    const notes1 = allNotes(blocked1)
    t.ok(notes1.includes('path_gate_reason=unauthorized_path'),
      'face keeps the machine-readable path_gate_reason= key')
    t.ok(notes1.includes('合法出路'), 'face carries the sanctioned way-out text')
    t.ok(!notes1.includes('缺 verdict= 标记'),
      'gate refusal is NOT misreported as "missing verdict= marker" (main cause honest)')
    const arbBlocked1 = (blocked1.timeline || []).filter(e => e.stage === 'arbitrate' && e.state === 'blocked')
    t.ok(arbBlocked1.length === 1,
      `exactly one arbitrate blocked entry — format rounds untouched (got ${arbBlocked1.length})`)
    const d = blocked1.meta?.blocked_detail
    t.ok(d?.reason_code === 'unauthorized_path',
      `blocked_detail.reason_code=unauthorized_path (got ${JSON.stringify(d?.reason_code)})`)
    t.ok(typeof d?.next_action === 'string' && d.next_action.trim().length > 0,
      'blocked_detail.next_action names a real way out (non-empty)')

    // Follow the documented way out: remove the rogue asset, rework. The re-entry has
    // NO refusal anywhere, so the existing pure-format chain must state its own cause.
    await rm(join(lane, rogueRel), { force: true })
    t.ok(api.rework(tid, 'implement', 'E2E：已按出路还原越界文件，打回重跑').body?.ok === true,
      'rework -> implement (revive after removing the rogue asset)')
    const busy1 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      're-entering run_integration_tests', SCENE_DEADLINE_MS, t)
    if (!busy1) return
    const blocked2 = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'second blocked = pure format round limit (no refusal on this path)', SCENE_DEADLINE_MS, t)
    if (!blocked2) return
    t.ok(blocked2.stage === 'arbitrate', 'second blocked still at arbitrate')
    // Face assertions anchor on the LAST blocked timeline entry (the blocked why itself),
    // not the accumulated meta.log — round 1's refusal note stays in the log forever and
    // would poison any negative assertion on the joined notes.
    const lastBlocked2 = (blocked2.timeline || []).filter(e => e.state === 'blocked').pop()
    t.ok(!!lastBlocked2, 'a blocked timeline entry exists for the second block')
    const why2 = String(lastBlocked2?.reason || '')
    const notes2 = allNotes(blocked2)
    t.ok(why2.includes('缺 verdict= 标记') && notes2.includes('缺 verdict= 标记'),
      'with no refusal anywhere, "missing verdict= marker" stays the stated cause (zero regression)')
    t.ok(!why2.includes('path_gate_reason='),
      'refusal-free re-entry shows no gate language on the current blocked face')

    // Final revival: seed verdict=pass in the busy window -> merge human gate -> closed.
    t.ok(api.rework(tid, 'implement', 'E2E：预置仲裁 pass 后收口').body?.ok === true,
      'rework -> implement (final revive)')
    const busy2 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      'final re-run', SCENE_DEADLINE_MS, t)
    if (!busy2) return
    const gen = await seedArbitratePass(lane)
    t.ok(gen >= 0, `verdict=pass seeded at gen${gen} (not statically guessed)`)
    const gate = await waitFor(api, tid, (x) => x?.stage === 'merge' && x?.stage_state === 'awaiting-human',
      'revived ticket reaches merge gate', SCENE_DEADLINE_MS, t)
    if (!gate) return
    t.ok(api.sign(tid, 'e2e-human', 'approve', 'E2E 闸拒子用例收口').body?.ok === true, 'sign approve')
    const fin = await waitFor(api, tid, (x) => x?.status === 'closed', 'ticket closed', SCENE_DEADLINE_MS, t)
    t.ok(fin?.status === 'closed', 'following the ticket-face way out ends closed (ticket self-recovers)')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

/**
 * L2 — format counter resets across rework: the "4th time" phantom never appears.
 * Ends at the second blocked assertion (the revival chain is proven by L1).
 */
async function legCounterReset(t, api, sdkPython, fixture) {
  const tid = `integ-e2e-frst-${Date.now().toString(36)}`
  const worker = startStubWorker(fixture, sdkPython, tid)
  let lane = ''
  try {
    const probeName = `e2e-probe-${tid}.txt`
    const r = await api.start(tid, [`integration/${probeName}`])
    t.ok(r.body?.ok === true, `ticket-start ok (${r.body?.ok ? tid : String(r.body?.error || r.stderr).slice(0, 120)})`)
    if (r.body?.ok !== true) return
    const ready = await waitFor(api, tid, (s) => !!s?.meta?.workspace_prep?.ok,
      'workspace ready', 120_000, t)
    if (!ready) return
    lane = lanePath(fixture, ready)
    await writeProbe(lane, probeName)

    const blocked1 = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'first pure format round-limit blocked', SCENE_DEADLINE_MS, t)
    if (!blocked1) return
    const notes1 = allNotes(blocked1)
    t.ok(/仲裁结论 3 次缺 verdict= 标记/.test(notes1),
      'first limit reads exactly "仲裁结论 3 次缺 verdict= 标记" (fresh counter)')
    t.ok(api.rework(tid, 'implement', 'E2E：一轮超限已 blocked，原样重进验证计数复位').body?.ok === true,
      'rework -> implement (re-enter without seeding anything)')
    const busy1 = await waitFor(api, tid, (x) => x?.stage === 'run_integration_tests',
      're-entering run_integration_tests', SCENE_DEADLINE_MS, t)
    if (!busy1) return
    const blocked2 = await waitFor(api, tid, (x) => x?.stage_state === 'blocked',
      'second pure format round-limit blocked', SCENE_DEADLINE_MS, t)
    if (!blocked2) return
    const notes2 = allNotes(blocked2)
    t.ok(/仲裁结论 3 次缺 verdict= 标记/.test(notes2),
      'counter reset on re-entry: face reads "3 次" again (t260916-21 "4th time" mirror)')
    t.ok(!/仲裁结论 [4-9] 次缺/.test(notes2) && !/仲裁结论 \d{2,} 次缺/.test(notes2),
      'no accumulated count ("4+ 次") ever reaches the ticket face')
  } finally {
    await cleanupTicket(t, api, worker, tid)
  }
}

async function main() {
  console.log('== t260917-01 arbitrate gate-refusal vs format-counter decoupling (stub-brain E2E)')

  /* ---- nested guard (must come first; recursion breaks the budget) */
  if (nestedGuard() === 'nested') {
    envFail++
    console.log('  ENV_FAIL nested inside a lane integration step (SANDBAR_TASK_QUEUE/SANDBAR_WATCH_WORKFLOW present): recursive guard, top-level runs carry the coverage')
    printSummaryAndExit(2)
  }

  /* ---- write-guard triad (env simulated, then restored; same contract as the baseline) */
  {
    const g = makeTally()
    g.section('P1 write-guard triad (simulated targets, env restored after)')
    const saved = process.env.SANDBAR_TARGET_HOST
    const withEnv = async (v, fn) => {
      if (v === undefined) delete process.env.SANDBAR_TARGET_HOST
      else process.env.SANDBAR_TARGET_HOST = v
      try { return await fn() } finally {
        if (saved === undefined) delete process.env.SANDBAR_TARGET_HOST
        else process.env.SANDBAR_TARGET_HOST = saved
      }
    }
    g.ok(await withEnv(undefined, writeGuard) === 'env_fail', 'unset SANDBAR_TARGET_HOST -> env_fail')
    g.ok(await withEnv('127.0.0.1:7233', writeGuard) === 'fail', 'explicit production default -> fail (red line)')
    g.ok(await withEnv('127.0.0.1:9999', writeGuard) === 'fail', 'unclear target -> fail')
    g.ok(await withEnv('127.0.0.1:17233', writeGuard) === 'run', 'pinned test env -> run')
    pass += g.pass; fail += g.fail; envFail += g.envFail
    const guard = writeGuard()
    if (guard === 'fail') {
      console.log('  FAIL write-guard: SANDBAR_TARGET_HOST explicitly points at the production default')
      printSummaryAndExit(1)
    }
    if (guard === 'env_fail') {
      envFail++
      console.log('  ENV_FAIL write-guard: SANDBAR_TARGET_HOST not set explicitly (set SANDBAR_TARGET_HOST=127.0.0.1:17233)')
      printSummaryAndExit(2)
    }
  }

  /* ---- env chain: SDK -> test Temporal -> fixture */
  const sdkPython = findSdkPython(tally)
  if (!sdkPython || !(await ensureTestTemporal(tally))) {
    foldTally()
    printSummaryAndExit(2)
  }
  const fixtureBuilt = await buildFixture(tally)
  if (!fixtureBuilt) {
    foldTally()
    printSummaryAndExit(2)
  }
  const { fixture, dispose } = fixtureBuilt
  const api = makeApi(sdkPython, fixture)

  /* ---- legs (independent tickets, sequential, shared fixture) */
  const legs = [
    ['L1 gate refusal honest face + way-out revival', legGateRefusal],
    ['L2 format counter reset across rework', legCounterReset],
  ]
  // 夹具回收放 finally（260926 磁盘泄漏修）：正常/断言失败/抛异常/超时早退一律走 dispose，
  // 进程内兜底（exit/SIGINT/SIGTERM）在 ticket-lifecycle-scenes.mjs 里另行武装。
  try {
    for (const [label, fn] of legs) {
      const g = makeTally()
      g.section(label)
      try {
        await fn(g, api, sdkPython, fixture)
      } catch (e) {
        g.ok(false, `leg crashed: ${e?.stack || e}`)
      }
      pass += g.pass; fail += g.fail; envFail += g.envFail
      if (g.envFail) console.log(`  (${label}: ${g.envFail} env_fail note(s) above)`)
    }
  } finally {
    await dispose()
  }

  printSummaryAndExit(fail > 0 ? 1 : envFail > 0 ? 2 : 0)
}

await main()
