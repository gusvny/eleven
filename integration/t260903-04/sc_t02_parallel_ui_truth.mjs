/**
 * integration/t260903-04/sc_t02_parallel_ui_truth.mjs
 * —— 工单台并行双显的真源优先契约（KI-024① UI 半，t260903-04）。
 *
 * 用户场景（KI-024 实案 t260903-01）：并行分叉期工单台详情只能看到一边（后写者赢），
 * 值守把 arbitrate∥acceptance_walkthrough 正在办案的票误读成停滞。t260901-05 的
 * timeline 启发式双显属推导非真源（相邻边等场景有误判面）；本票引擎在并行期往快照
 * meta 写 parallel_stages 列表（工单钦定契约字段），UI 消费该列表双显。
 *
 * 跨组件契约（本场景守的接缝）：引擎快照 meta.parallel_stages（组件 A 产物形态）
 * → 工单台推导消费（组件 B 用户可感知口径）。锚用户可感知行为：
 *   T1 真源纠偏：启发式误判面场景（timeline 只有单边 running）下，真源列表非空
 *      → 活跃恰为真源两边（fallback=false——「并行分叉中：A ∥ B」文案依赖它）。
 *   T2 真源与启发式一致场景不回归（implement∥design 双 running → 双显）。
 *   T3 真实收口窗：列表边的显式终态（done/blocked）不被真源重亮 ▶——引擎「先完成
 *      边已收口、汇合未到」与「失败边摘除」窗口的用户可感知正确性（完成边 ✓、失败边 ✗）。
 *   T4/T5 字段缺失/空列表 → 回落现口径（F4 语义：timeline 双 running → 双显）。
 *   T6 畸形条目清洗：词表外/非字符串跳过；全畸形视同空 → 回落。
 *   T7 旧票回归：无 meta 无 timeline → 单值指针口径逐字节不变（fallback=true）。
 *   W  场景自身词表防漂移：与 workflows/dev-lane.yaml 的 stage id 序对拍。
 *
 * 直跑：node integration/t260903-04/sc_t02_parallel_ui_truth.mjs（node ≥22.18）。
 * 末行 SUMMARY pass=<n> fail=<k> env_fail=<e> na=<w>（三态 §7.3）；fail>0 或全 na→exit 1。
 */

import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO = resolve(HERE, '..', '..')
const { deriveStageStates } = await import(resolve(REPO, 'server/dsh/workbench/src/client/lane-states.ts'))

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t} ==`) }

/* ------------------------------------------------- W. 场景词表防漂移 */
section('W 词表与 dev-lane.yaml 同构')
const ORDER = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge', 'suggest_next']
{
  const yaml = readFileSync(resolve(REPO, 'server/dsh/workflows/dev-lane.yaml'), 'utf8')
  const ids = [...yaml.matchAll(/^\s*- id:\s*(\S+)\s*$/gm)].map(m => m[1])
  ok(JSON.stringify(ids) === JSON.stringify(ORDER),
    `场景 ORDER 与 yaml stage 序一致（${ids.length} 步）`)
}

/* fixture 工厂：与快照 detail 同构（lane-states.ts LaneDetailLike + 本票 meta 契约字段）。 */
function makeDetail({ stage, parallel = undefined, timeline = [], results = {}, checks = {} } = {}) {
  const d = {
    status: 'running', stage, stage_state: 'running',
    timeline, results, checks,
  }
  if (parallel !== undefined) d.meta = { parallel_stages: parallel }
  return d
}
const running = (stage) => ({ stage, state: 'running' })

/* ------------------------------------------------- T1. 真源纠偏（启发式误判面） */
section('T1 真源纠偏：timeline 单边 running，真源非空 → 双显')
{
  // 启发式误判面：arbitrate 已落 running 条目、acceptance_walkthrough 尚无（gather 窗内
  // 两边 _enter 交错），单看 timeline 推导只亮一边——正是 KI-024 实案误读形态。
  const d = makeDetail({
    stage: 'arbitrate',
    parallel: ['arbitrate', 'acceptance_walkthrough'],
    timeline: [running('arbitrate')],
  })
  const r = deriveStageStates(d, ORDER)
  ok(r.active.includes('arbitrate') && r.active.includes('acceptance_walkthrough'),
    `活跃恰为真源两边（actual active=${JSON.stringify(r.active)}）`)
  ok(r.states['acceptance_walkthrough'] === 'running',
    '真源边状态=running（步骤条 ▶，用户可见双亮）')
  ok(r.fallback === false,
    'fallback=false（d2StatusLine「并行分叉中：A ∥ B」文案依赖非回退路径）')
}

/* --------------------------------------------- T2. 真源与启发式一致（回归） */
section('T2 一致场景不回归：implement∥design 双 running')
{
  const d = makeDetail({
    stage: 'design_integration_tests',
    parallel: ['implement', 'design_integration_tests'],
    timeline: [running('implement'), running('design_integration_tests')],
  })
  const r = deriveStageStates(d, ORDER)
  ok(r.active.includes('implement') && r.active.includes('design_integration_tests'),
    '两边同显（启发式本就对，真源路径不劣化）')
}

/* ------------------------------------- T3. 真实收口窗：显式终态钉住优先于真源列表 */
section('T3 收口窗语义：列表边的显式终态不被真源重亮')
{
  // 引擎时序：gather 前写入的列表要等两边齐活才清键——「先完成边已 done、汇合未到」
  // 的窗口里列表仍含完成边；「失败边摘除」的窗口里 blocked 边可能仍在列表。用户可
  // 感知契约：完成边保持 ✓ 不假亮 ▶、失败边保持 ✗，活跃只剩真在跑的边。
  // （实现口径=真源强制 running 但被 timeline 显式终态钉住；比「列表即真值」多修了
  //  假亮窗，场景按用户可感知窗口语义锚定，不锚列表/时间线谁覆盖谁的实现细节。）
  const d = makeDetail({
    stage: 'arbitrate',
    parallel: ['arbitrate', 'acceptance_walkthrough'],
    timeline: [running('acceptance_walkthrough'), { stage: 'acceptance_walkthrough', state: 'done' },
      running('arbitrate')],
  })
  const r = deriveStageStates(d, ORDER)
  ok(r.states['acceptance_walkthrough'] === 'done',
    '先完成边保持 done（不被列表重亮 ▶——假并行误导值守）')
  ok(JSON.stringify(r.active) === JSON.stringify(['arbitrate']),
    `活跃只剩真在跑的边（actual=${JSON.stringify(r.active)}）`)

  const d2 = makeDetail({
    stage: 'arbitrate',
    parallel: ['arbitrate'],
    timeline: [running('acceptance_walkthrough'), { stage: 'acceptance_walkthrough', state: 'blocked' },
      running('arbitrate')],
  })
  const r2 = deriveStageStates(d2, ORDER)
  ok(r2.states['acceptance_walkthrough'] === 'blocked'
    && JSON.stringify(r2.active) === JSON.stringify(['arbitrate']),
    '失败边保持 ✗ 不入活跃（列表单边摘除窗：不假亮失败边）')
}

/* ------------------------------------------------- T4/T5. 缺失与空列表回落 */
section('T4/T5 字段缺失/空列表 → 回落现口径（F4 语义）')
{
  const d = makeDetail({
    stage: 'design_integration_tests',
    timeline: [running('implement'), running('design_integration_tests')],
  })
  const r = deriveStageStates(d, ORDER)
  ok(r.active.includes('implement') && r.active.includes('design_integration_tests'),
    '无 meta 字段（旧票/旧引擎快照）→ 启发式双显照旧')

  const d2 = makeDetail({
    stage: 'design_integration_tests',
    parallel: [],
    timeline: [running('implement'), running('design_integration_tests')],
  })
  const r2 = deriveStageStates(d2, ORDER)
  ok(r2.active.includes('implement') && r2.active.includes('design_integration_tests'),
    '空列表（汇合清空后形态）→ 与无字段同回落，不残留假并行')
}

/* ------------------------------------------------------- T6. 畸形条目清洗 */
section('T6 畸形条目：词表外/非字符串跳过，全畸形视同空')
{
  const d = makeDetail({
    stage: 'arbitrate',
    parallel: ['arbitrate', 'bogus_stage', 123, null],
    timeline: [running('arbitrate')],
  })
  const r = deriveStageStates(d, ORDER)
  ok(JSON.stringify(r.active) === JSON.stringify(['arbitrate']),
    `词表外与非字符串条目跳过（actual=${JSON.stringify(r.active)}，不泄漏不建状态）`)

  const d2 = makeDetail({
    stage: 'arbitrate',
    parallel: ['bogus_stage'],
    timeline: [running('arbitrate'), running('acceptance_walkthrough')],
  })
  const r2 = deriveStageStates(d2, ORDER)
  ok(r2.active.includes('arbitrate') && r2.active.includes('acceptance_walkthrough'),
    '全畸形视同空 → 回落现口径（不因坏数据丢双显）')
}

/* --------------------------------------------------------- T7. 旧票零回归 */
section('T7 旧票回归：无 meta 无 timeline → 单值指针口径不变')
{
  const d = makeDetail({ stage: 'implement' })
  const r = deriveStageStates(d, ORDER)
  ok(r.fallback === true, 'fallback=true（单值指针回退路径仍在）')
  ok(r.states['implement'] === 'running' && r.states['review_plan'] === 'done'
    && r.states['ui_evidence'] === 'todo',
    '指针口径逐字节：当前步 running、前步 done、后步 todo')
  ok(r.active.length === 0, '回退路径 active 空（不伪造并行）')
}

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail > 0 ? 1 : 0)
