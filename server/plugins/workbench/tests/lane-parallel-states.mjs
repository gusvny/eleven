/**
 * lane-parallel-states —— t260901-05「泳道图并行分叉渲染（单值指针 → 活跃步数组）」
 * 推导函数行为测试（黑盒：消费 detail 快照 fixture，只验语义不验实现细节）。
 *
 * 直跑：node integration/baselines/lane-parallel-states.mjs（cwd=泳道根，零依赖）。
 *
 * 被测契约（integration 侧约定，票 t260901-05 方案 v3 推导口径）：
 *   - 推导函数导出 deriveStageStates，住在 server/plugins/workbench/src/client/ 下的
 *     **纯 .ts 模块**（node 无法 import .tsx；index.tsx 只做消费不做推导）。
 *   - 签名 deriveStageStates(detail, order) → Record<stageId, visual>；
 *     visual ∈ done|running|blocked|awaiting-human|todo；若实现返回 {states, active}
 *     包装则自动 unwrap .states。「活跃数组」= states 中值为 'running' 的步
 *     （blocked/awaiting-human 按 review v3 规则 2 永不入活跃数组）。
 *   - 回退（活跃空集 ∨ timeline 缺/空）时 states 必须等于现行单值指针口径。
 *
 * 覆盖（用户可感知行为 × 故障面）：
 *   并发：并行分叉双高亮（F4）、打回重进高亮不误标 done（F5）、merge 执行期单活跃（F2/F7）；
 *   边界：merge 签字期 ✋ 不回归（F1）、blocked 首尝试 ✗ 非活跃（F3）、closed 全 done（F8）、
 *         旧数据无 timeline 软降级（F10/F11）、派发前 awaiting 窗（F12）；
 *   异常输入：模板外 timeline id / 缺字段 / 乱序最新态（F9）；
 *   ui_evidence 软失败（F6/F6b，F6b 按 review C1 双可断言）。
 * 资源回收面无独立条目（本票无 spawn/监听生命周期；死代码清理由 lanediagram-removed 守）。
 *
 * 安全红线：纯本地 fixture，不碰 3099/Temporal/网络。
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')
const CLIENT_SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client')

let passed = 0, failed = 0, skipped = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------------------------------------- 被测模块解析 */
section('resolve deriveStageStates module')
const candidates = readdirSync(CLIENT_SRC).filter(f => f.endsWith('.ts') && !f.endsWith('.d.ts'))
let derive = null, deriveFrom = ''
for (const f of candidates) {
  const p = join(CLIENT_SRC, f)
  try {
    const mod = await import(pathToFileURL(p).href + '?t=' + Date.now())
    if (typeof mod.deriveStageStates === 'function') { derive = mod.deriveStageStates; deriveFrom = f; break }
  } catch { /* 该文件不可 import（含平台依赖等）则继续扫描 */ }
}
if (!derive) {
  console.log('  FAIL src/client/ 下找不到导出 deriveStageStates 的纯 .ts 模块')
  console.log('       （node 无法 import .tsx；推导函数须独立成纯 ts 模块，见本文件头契约）')
  console.log(`\nSUMMARY pass=0 skip=0 fail=1`)
  process.exit(1)
}
console.log(`  ok resolve deriveStageStates @ src/client/${deriveFrom}`)

/* ---------------------------------------------------------------- fixture 构造 */
const ORDER = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge']  // t260910-14：suggest_next 段退役，链中移除
const DONE = 'done', RUN = 'running', BLK = 'blocked', AH = 'awaiting-human', TODO = 'todo'

const okRes = (gen = 0) => ({ status: 'ok', gen })
const doneChecks = (...items) => items.map(item => ({ item, done: true, by: 'x' }))
const tle = (stage, state, reason = '') => ({ at: '2026-09-01T00:00:00', stage, state, reason })

/** 通用 detail：前 N 步完成（results/checks 信号齐），其余无信号。 */
function baseDetail(completed) {
  const results = {}, checks = {}, timeline = []
  for (const s of completed) {
    timeline.push(tle(s, 'running', '进入'))
    if (s === 'merge_check' || s === 'merge') {
      checks[s] = doneChecks('项1')
    } else {
      results[s] = okRes(0)
    }
  }
  return { status: 'dispatched', stage: null, stage_state: RUN, timeline, results, checks }
}

/** 调用并归一：unwrap {states, active}；返回 states map。 */
function run(detail, order = ORDER) {
  let out
  try {
    out = derive(detail, order)
  } catch (e) {
    try { out = derive({ ...detail, stages: order.map(id => ({ id })) }, order) }
    catch { throw e }
  }
  const states = (out && out.states && typeof out.states === 'object') ? out.states : out
  return states
}
const activeOf = states => ORDER.filter(s => states[s] === RUN)

/** 全表断言：states 必须覆盖 order 每步。 */
function expectAll(states, expected, label) {
  let allOk = true
  for (const s of ORDER) {
    const want = expected[s] ?? TODO
    if (states[s] !== want) { allOk = false; console.log(`    ${s}: got=${states[s]} want=${want}`) }
  }
  ok(allOk, label)
}

/* ---------------------------------------------------------------- F1 merge 签字期 */
section('F1 merge 签字期：✋ 且非活跃（review v3 规则 2+7）')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests',
    'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check'])
  d.checks.merge = [{ item: '人审签字', done: false, by: '' }, { item: 'merge 落账', done: false, by: '' }]  // 签字期 checks 未翻
  d.timeline.push(tle('merge', 'running', '进入本步'))
  d.timeline.push(tle('merge', AH, '等人签字'))
  d.stage = 'merge'; d.stage_state = AH
  const st = run(d)
  expectAll(st, {
    create_plan: DONE, review_plan: DONE, implement: DONE, design_integration_tests: DONE,
    ui_evidence: DONE, run_integration_tests: DONE, arbitrate: DONE,
    acceptance_walkthrough: DONE, merge_check: DONE, merge: AH,
  }, 'merge=✋，前序全 done')
  ok(activeOf(st).length === 0, '活跃数组为空（或回退后无 running 步）')
}

/* ---------------------------------------------------------------- F2 merge 执行期 */
section('F2 merge 执行期：恰 merge 单活跃')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests',
    'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check'])
  d.checks.merge = [{ item: '人审签字', done: true, by: 'x' }, { item: 'merge 落账', done: false, by: '' }]
  d.timeline.push(tle('merge', 'running', '进入本步'))
  d.timeline.push(tle('merge', AH, '等人签字'))
  d.timeline.push(tle('merge', 'running', '人审通过，执行 merge'))
  d.stage = 'merge'; d.stage_state = RUN
  const st = run(d)
  ok(st.merge === RUN, 'merge=▶ running')
  ok(JSON.stringify(activeOf(st)) === JSON.stringify(['merge']), `活跃恰={merge}（got ${JSON.stringify(activeOf(st))}）`)
}

/* ---------------------------------------------------------------- F3 merge_check 首尝试 blocked */
section('F3 merge_check 首尝试即 blocked：✗ 非活跃（review v3 规则 2 优先于计数）')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests',
    'run_integration_tests', 'arbitrate', 'acceptance_walkthrough'])
  d.timeline.push(tle('merge_check', 'running', '进入本步'))
  d.timeline.push(tle('merge_check', BLK, '红灯：预演冲突'))
  d.stage = 'merge_check'; d.stage_state = BLK
  const st = run(d)
  ok(st.merge_check === BLK, 'merge_check=✗ blocked')
  ok(!activeOf(st).includes('merge_check'), 'blocked 步不进活跃数组')
  ok(st.merge === TODO, '后续步 todo')
}

/* ---------------------------------------------------------------- F4 并行分叉双高亮 */
section('F4 并行分叉期：implement ∥ design_integration_tests 双高亮（本票核心场景）')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline.push(tle('implement', 'running', '进入本步'))
  d.timeline.push(tle('design_integration_tests', 'running', '进入本步'))
  d.stage = 'design_integration_tests'; d.stage_state = RUN
  const st = run(d)
  ok(st.implement === RUN && st.design_integration_tests === RUN, '两并行步同显 running')
  const act = activeOf(st)
  ok(act.includes('implement') && act.includes('design_integration_tests'),
    `活跃数组含两步（got ${JSON.stringify(act)}）`)
  ok(st.ui_evidence === TODO && st.run_integration_tests === TODO, '汇合后步 todo')
}

/* ---------------------------------------------------------------- F5 打回重进 */
section('F5 implement 完成(gen0)后打回重进 gen1：高亮重跑、不误标 done')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.results.implement = okRes(0)                       // 上一轮已完成
  d.timeline.push(tle('implement', 'running', '进入本步（第 1 次）'))
  d.timeline.push(tle('implement', 'running', '进入本步（第 2 次）'))  // 打回重进
  d.timeline.push(tle('design_integration_tests', 'running', '进入本步'))
  d.stage = 'implement'; d.stage_state = RUN
  const st = run(d)
  ok(st.implement === RUN, 'implement=running（count 2 > attempts 1）')
  ok(activeOf(st).includes('implement'), 'implement 在活跃数组')
}

/* ---------------------------------------------------------------- F6 ui_evidence */
section('F6 ui_evidence：UI 票 ok=done；软失败 C1 双可')
{
  const ok6 = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests'])
  ok6.results.ui_evidence = okRes(0)
  ok6.timeline.push(tle('run_integration_tests', 'running', '进入本步'))
  ok6.stage = 'run_integration_tests'; ok6.stage_state = RUN
  const stOk = run(ok6)
  ok(stOk.ui_evidence === DONE, 'UI 票 ui_evidence ok → done')

  const fl6 = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests'])
  fl6.results.ui_evidence = { status: 'failed', gen: 0 }   // 软失败：计次不计数
  fl6.timeline.push(tle('run_integration_tests', 'running', '进入本步'))
  fl6.stage = 'run_integration_tests'; fl6.stage_state = RUN
  const stFl = run(fl6)
  ok(stFl.ui_evidence === DONE || stFl.ui_evidence === TODO,
    `软失败 ui_evidence done|todo 双可（review C1；got ${stFl.ui_evidence}）`)
  ok(!activeOf(stFl).includes('ui_evidence'), '软失败 ui_evidence 不进活跃数组')
  ok(JSON.stringify(activeOf(stFl)) === JSON.stringify(['run_integration_tests']),
    `活跃恰={run_integration_tests}（got ${JSON.stringify(activeOf(stFl))}）`)
}

// t260910-14 退役注记：原 F7 段（suggest_next 软失败永不点亮）随该段退役删除。

/* ---------------------------------------------------------------- F8 closed */
section('F8 closed 工单：全表 done')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests',
    'run_integration_tests', 'arbitrate', 'acceptance_walkthrough', 'merge_check', 'merge'])
  d.status = 'closed'
  const st = run(d)
  expectAll(st, Object.fromEntries(ORDER.map(s => [s, DONE])), 'closed → 11 步全 done')
}

/* ---------------------------------------------------------------- F9 畸形输入 */
section('F9 畸形 timeline：模板外 id / 缺字段 / 乱序最新态')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline.push(tle('acceptance', 'rework', 'phase 域 id（模板外）'))
  d.timeline.push(tle('workspace', 'ready', '模板外'))
  d.timeline.push(tle('parallel_impl_design', BLK, 'phase 域 id'))
  d.timeline.push({ at: '', stage: '', state: '', reason: '' })   // 缺字段
  d.timeline.push({ at: null, stage: null, state: null })
  d.timeline.push(tle('design_integration_tests', BLK, '早期 blocked'))
  d.timeline.push(tle('design_integration_tests', 'running', '重进后 running（最新）'))
  d.stage = 'design_integration_tests'; d.stage_state = RUN
  let st, threw = null
  try { st = run(d) } catch (e) { threw = e }
  ok(!threw, `不抛错（threw=${threw && threw.message}）`)
  if (!threw) {
    const foreign = Object.keys(st).filter(k => !ORDER.includes(k))
    ok(foreign.length === 0, `states 键不泄漏模板外 id（got ${JSON.stringify(foreign)}）`)
    ok(st.design_integration_tests === RUN, '乱序后取最新态=running')
    ok(activeOf(st).includes('design_integration_tests'), '模板外 blocked 不误伤活跃判定')
  }

  const d2 = baseDetail(['create_plan', 'review_plan'])
  d2.timeline.push(tle('design_integration_tests', 'running', '进入'))
  d2.timeline.push(tle('design_integration_tests', BLK, 'blocked（最新）'))
  d2.stage = 'design_integration_tests'; d2.stage_state = BLK
  const st2 = run(d2)
  ok(st2.design_integration_tests === BLK, '最新态 blocked 优先 → ✗')
}

/* ---------------------------------------------------------------- F10/F11 旧数据软降级 */
section('F10/F11 timeline 缺省/空：回退单值指针口径（软降级不回归）')
{
  const mk = timeline => {
    const d = baseDetail(['create_plan', 'review_plan'])
    d.timeline = timeline
    d.stage = 'implement'; d.stage_state = RUN   // 指针：implement 运行中
    return d
  }
  for (const [label, tl] of [['timeline=undefined', undefined], ['timeline=[]', []]]) {
    const st = run(mk(tl))
    expectAll(st, {
      create_plan: DONE, review_plan: DONE, implement: RUN,
      design_integration_tests: TODO, ui_evidence: TODO, run_integration_tests: TODO,
      arbitrate: TODO, acceptance_walkthrough: TODO, merge_check: TODO, merge: TODO,
    }, `${label} → 指针口径（前 done/指针 running/后 todo）`)
  }
}

/* ---------------------------------------------------------------- F12 派发前 awaiting 窗 */
section('F12 派发前 awaiting 窗：回退口径与现行一致（指针步显 running）')
{
  const d = baseDetail([])
  d.timeline = [tle('create_plan', 'awaiting', 'adopt dev-lane')]
  d.stage = 'create_plan'; d.stage_state = 'awaiting'
  const st = run(d)
  ok(st.create_plan === RUN, '现行单值口径 awaiting 指针步显 running（逐字节保持现行为）')
  ok(st.review_plan === TODO, '后续 todo')
}

/* =================================================================================
 * t260903-04（KI-024）追加：parallel_stages 并行真源（review C1：扩展不覆盖，
 * F1-F12 一字不动全保留；新用例 P1-P6 只增不改签名 deriveStageStates(detail, order)）。
 * 引擎契约（dev_lane.set_parallel_stages）：列表只含 STAGES id、离开并行期删键、
 * 等待期摘失败边。UI 口径：真值优先、显式终态不重亮、畸形清洗、空=无并行。
 * ================================================================================= */

section('P1 并行真源：fork 瞬间 timeline 滞后（启发式漏亮面）→ 列表双亮')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline = d.timeline.filter(t => t.stage !== 'implement' && t.stage !== 'design_integration_tests')
  d.stage = 'implement'; d.stage_state = RUN
  d.parallel_stages = ['implement', 'design_integration_tests']
  const st = run(d)
  ok(st.implement === RUN && st.design_integration_tests === RUN, '列表真值 → 两边同显 ▶')
  const act = activeOf(st)
  ok(act.includes('implement') && act.includes('design_integration_tests'),
    `活跃数组含两步（got ${JSON.stringify(act)}）`)
  const before = run({ ...d, parallel_stages: undefined })
  ok(before.implement === RUN && before.design_integration_tests === TODO,
    '同 fixture 无列表 → 指针口径单显（旧行为逐字节保持，即被修的盲区）')
}

section('P2 真源位置：snapshot 形态 meta.parallel_stages 同样生效')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline = d.timeline.filter(t => t.stage !== 'implement' && t.stage !== 'design_integration_tests')
  d.stage = 'arbitrate'; d.stage_state = RUN
  d.meta = { parallel_stages: ['arbitrate', 'acceptance_walkthrough'] }
  const st = run(d)
  ok(st.arbitrate === RUN && st.acceptance_walkthrough === RUN,
    'arbitrate ∥ acceptance_walkthrough 双亮（meta 嵌套读取）')
  const d2 = { ...d, parallel_stages: ['implement'] }
  const st2 = run(d2)
  ok(st2.arbitrate === RUN && st2.acceptance_walkthrough === RUN && st2.implement !== RUN,
    'meta 优先于顶层（两者同在时取 meta，防双真源分叉）')
}

section('P3 先完成边收口窗：显式终态不被列表重亮（引擎汇合前的真实形态）')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement'])
  d.timeline.push(tle('design_integration_tests', 'running', '进入本步'))
  d.stage = 'design_integration_tests'; d.stage_state = RUN
  d.parallel_stages = ['implement', 'design_integration_tests']
  const st = run(d)
  ok(st.implement === DONE, 'implement 已有 done 留痕 → 保持 ✓（不重亮 ▶）')
  ok(st.design_integration_tests === RUN, 'design 仍跑 → ▶')
  ok(JSON.stringify(activeOf(st)) === JSON.stringify(['design_integration_tests']),
    `活跃只剩未完成边（got ${JSON.stringify(activeOf(st))}）`)
}

section('P4 畸形列表：非字符串/模板外 id/重复清洗；全非法/非数组 → 回落')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline = d.timeline.filter(t => t.stage !== 'implement' && t.stage !== 'design_integration_tests')
  d.stage = 'implement'; d.stage_state = RUN
  d.parallel_stages = ['implement', 42, null, 'parallel_impl_design', 'no_such_stage', 'implement']
  let st = run(d)
  ok(st.implement === RUN && st.design_integration_tests === TODO,
    '畸形条目清洗后只剩合法 implement（phase 值/模板外/重复都丢弃）')
  const d2 = { ...d, parallel_stages: ['parallel_impl_design', 'integ_join'] }
  st = run(d2)
  ok(st.implement === RUN && st.design_integration_tests === TODO,
    '全非法 → 与无列表同口径（指针回退，不崩、不泄漏非法键）')
  const d3 = { ...d, parallel_stages: 'implement' }
  st = run(d3)
  ok(st.implement === RUN && st.design_integration_tests === TODO,
    '非数组（裸字符串）→ 忽略，回落指针口径')
}

section('P5 空数组=无并行：与无字段同口径（引擎删键后的汇合期形态）')
{
  const d = baseDetail(['create_plan', 'review_plan'])
  d.timeline.push(tle('implement', 'running', '进入本步'))
  d.timeline.push(tle('design_integration_tests', 'running', '进入本步'))
  d.stage = 'design_integration_tests'; d.stage_state = RUN
  d.parallel_stages = []
  const st = run(d)
  const ref = run({ ...d, parallel_stages: undefined })
  ok(JSON.stringify(st) === JSON.stringify(ref), '空列表结果与无字段逐字节一致（启发式接管）')
  ok(activeOf(st).length === 2, '启发式仍双亮（既有 F4 口径不回归）')
}

section('P6 等待期摘失败边（review C4 写死口径的 UI 面）：失败边 ✗、剩余边 ▶')
{
  const d = baseDetail(['create_plan', 'review_plan', 'implement', 'design_integration_tests',
    'ui_evidence', 'run_integration_tests'])
  d.timeline.push(tle('arbitrate', 'running', '进入本步'))
  d.timeline.push(tle('arbitrate', BLK, 'agent 活动故障'))
  d.timeline.push(tle('acceptance_walkthrough', 'running', '进入本步'))
  d.stage = 'arbitrate'; d.stage_state = BLK
  d.parallel_stages = ['acceptance_walkthrough']
  const st = run(d)
  ok(st.arbitrate === BLK, '失败边=✗ blocked（timeline 显式终态优先）')
  ok(st.acceptance_walkthrough === RUN, '剩余边=▶（摘边后的列表真值）')
  ok(!activeOf(st).includes('arbitrate') && activeOf(st).includes('acceptance_walkthrough'),
    '活跃数组不含失败边')
}

console.log(`\n${passed} passed, ${failed} failed, ${skipped} skipped`)
console.log(`SUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
