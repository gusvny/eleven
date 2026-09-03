/**
 * lane-done-terminal-states —— t260901-08 追加范围回归基线：
 * 「终态留痕（引擎 _finish 落 done timeline 条目）优先于 inRun 计数启发式」。
 *
 * intent: t260901-07 实锤——merge 失败→rework→重验→再签字循环后，工单详情泳道图
 * 把 run_integration_tests 与 merge_check 误亮「进行中」。根因：
 *   ① 引擎 _finish 只翻 checks 不落 timeline（完成步最新态停 running）；
 *   ② lane-states done 判定靠 inRun 计数（running 条数 > attempts），盖不住
 *      a) 仲裁触发的内部重跑复用结果文件不增 gen；b) merge_check 等脚本门
 *      重复进段只落 checks 不落 results。
 * 修复（本票，双端闭环）：
 *   引擎侧 dev_lane.py `_finish` 补 _mark(step_id,'done') 终态条目；
 *   UI 侧 lane-states.ts 规则 2 显式终态集合加入 done，直采优先于计数启发式。
 *
 * high-level steps（07 真实时间线形态 = merge-conflict-loop 作案底）：
 *   T1 新形态（带 done 条目）：重验循环后 run_integration_tests/merge_check 判
 *      done 不误亮，活跃数组只含当前真实 running 步；
 *   T2 存量 closed 票全 done 短路不破；
 *   T3 旧形态（无 done 条目，07 原始快照）：回落现有 inRun 启发式，行为与
 *      lane-parallel-states 既有断言一致（存量数据不追改，靠新票留痕根治）；
 *   T4 重跑语义：done 条目后追加 running（rework 重进）→ 该步回 running 入活跃；
 *   T5 畸形输入：done 条目缺字段跳过、模板外 id 忽略。
 *
 * 被测契约：server/dsh/workbench/src/client/lane-states.ts 纯模块 deriveStageStates
 * （黑盒直跑 import，同 lane-parallel-states.mjs 形态；node>=22 type-stripping）。
 * 全 hermetic：纯本地 fixture，零 Docker 零网络，3099/Temporal 零接触。
 */

import { readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..', '..', '..')
const CLIENT_SRC = join(REPO, 'server', 'dsh', 'workbench', 'src', 'client')

let passed = 0, failed = 0, skipped = 0
const ok = (cond, label) => {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
const section = (t) => console.log(`\n== ${t}`)

section('resolve deriveStageStates module')
let derive = null, deriveFrom = ''
for (const f of readdirSync(CLIENT_SRC).filter(f => f.endsWith('.ts') && !f.endsWith('.d.ts'))) {
  try {
    const mod = await import(pathToFileURL(join(CLIENT_SRC, f)).href + '?t=' + Date.now())
    if (typeof mod.deriveStageStates === 'function') { derive = mod.deriveStageStates; deriveFrom = f; break }
  } catch { /* 平台依赖文件跳过 */ }
}
if (!derive) {
  console.log('  FAIL src/client/ 下找不到导出 deriveStageStates 的纯 .ts 模块')
  console.log(`\nSUMMARY pass=0 skip=0 fail=1`)
  process.exit(1)
}
console.log(`  ok resolve deriveStageStates @ src/client/${deriveFrom}`)

const ORDER = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge', 'suggest_next']
const DONE = 'done', RUN = 'running', TODO = 'todo'
const okRes = (gen = 0) => ({ status: 'ok', gen })
const doneChecks = (...items) => items.map(item => ({ item, done: true, by: 'x' }))
const tle = (stage, state, reason = '') => ({ at: '2026-09-01T00:00:00', stage, state, reason })
const statesOf = (r) => r.states

/**
 * 07 真实形态构造器（merge-conflict-loop）：merge 预演冲突 → 自动打回 implement
 * 消解 → 重验 → 再冲突 → 再消解 → 重验绿 → 签字合并。
 * noDone=true 复刻存量旧票（引擎尚无终态留痕）；默认产出新引擎留痕形态。
 */
function conflictLoopDetail({ noDone = false, closed = false } = {}) {
  const results = {}, checks = {}, timeline = []
  const enter = (s, i) => timeline.push(tle(s, RUN, `进入本步（第 ${i} 次）`))
  const finish = (s, by) => {
    if (s === 'merge_check' || s === 'merge') checks[s] = doneChecks('泳道有 commit', '工作区干净', 'verify_lane code 绿', 'merge-tree 无冲突')
    else results[s] = okRes(results[s] ? results[s].gen : 0)
    if (!noDone) timeline.push(tle(s, DONE, `${by}：完成`))
  }
  // 正常前段
  for (const s of ['create_plan', 'review_plan']) { enter(s, 1); finish(s, `${s}-agent`) }
  // implement ∥ design_integration_tests 并行分叉
  enter('implement', 1); enter('design_integration_tests', 1)
  finish('implement', 'developer-agent')
  finish('design_integration_tests', 'integration-agent')
  // run_integration_tests 第 1 次跑（仲裁内部重跑：复用结果文件，gen 不变）
  enter('run_integration_tests', 1); finish('run_integration_tests', 'run_integration_tests')
  enter('arbitrate', 1); finish('arbitrate', 'integration-agent')
  enter('run_integration_tests', 1) // 内部重跑：timeline 再进段，results.gen 不增
  finish('run_integration_tests', 'run_integration_tests')
  enter('acceptance_walkthrough', 1); finish('acceptance_walkthrough', 'integration-agent')
  // merge_check 三进段（冲突×2 + 全绿×1）：只落 checks，无 results
  for (let i = 1; i <= 3; i++) { enter('merge_check', i); if (i === 3) finish('merge_check', 'merge_check') }
  // merge 签字
  timeline.push(tle('merge', 'awaiting-human', '等人签字：sign(gate=merge)'))
  enter('merge', 1)
  finish('merge', 'user')
  return {
    status: closed ? 'closed' : 'dispatched',
    stage: 'suggest_next', stage_state: RUN,
    timeline, results, checks,
  }
}

section('T1 新形态（引擎落 done 终态条目）：重验循环不误亮')
{
  const d = conflictLoopDetail()
  // merge_check 三进段 running、零 results——修复前 inRun 计数必误亮；now 显式 done 直采
  const s = statesOf(derive(d, ORDER))
  ok(s.merge_check === DONE, 'T1.1 merge_check 三进段（无 results）判 done 不误亮')
  ok(s.run_integration_tests === DONE, 'T1.2 run_integration_tests 内部重跑不增 gen 判 done 不误亮')
  ok(s.merge === DONE, 'T1.3 merge（签字完成）判 done')
  ok(s.implement === DONE && s.design_integration_tests === DONE, 'T1.4 并行分叉两步均 done')
  // 活跃数组只含当前真实步：suggest_next 排除后应为空（活跃空集触发回退属合法口径）
  const r = derive(d, ORDER)
  ok(!r.active.includes('run_integration_tests') && !r.active.includes('merge_check'),
    'T1.5 活跃数组不含已终态步')
}

section('T2 存量 closed 票：全 done 短路不破')
{
  const d = conflictLoopDetail({ closed: true, noDone: true }) // 旧票 + 已 closed
  const r = derive(d, ORDER)
  ok(r.fallback === false && Object.values(r.states).every(v => v === DONE), 'T2.1 closed 全 done 短路')
}

section('T3 旧形态（无 done 条目，07 原始快照）：回落现有启发式')
{
  const d = conflictLoopDetail({ noDone: true })
  const s = statesOf(derive(d, ORDER))
  // merge_check 三进段 running、无 results、checks 全 done → attempts=1 < 3 → 误亮 running
  // （07 bug 形态在旧数据上按拍板口径保持原行为，不追改存量；此断言锁定「回落」而非「修复」）
  ok(s.merge_check === RUN, 'T3.1 旧票 merge_check 维持 inRun 启发式原行为（running）')
  ok(s.run_integration_tests === RUN, 'T3.2 旧票内部重跑步维持原行为（running）')
  ok(s.create_plan === DONE && s.review_plan === DONE, 'T3.3 旧票有 results 的完成步仍 done')
}

section('T4 重跑语义：done 条目后 rework 重进 → 回 running 入活跃')
{
  const d = conflictLoopDetail()
  // acceptance 打回 implement 重做：_enter 追加 running 在 done 之后
  d.timeline.push(tle('implement', RUN, '进入本步（第 2 次）'))
  d.stage = 'implement'
  const s = statesOf(derive(d, ORDER))
  const r = derive(d, ORDER)
  ok(s.implement === RUN && r.active.includes('implement'), 'T4.1 rework 重进步回 running 且入活跃数组')
  ok(s.run_integration_tests === DONE, 'T4.2 其余终态步不受重跑影响')
}

section('T5 畸形输入：done 条目缺字段跳过、模板外 id 忽略')
{
  const d = conflictLoopDetail()
  d.timeline.push(tle('implement', ''))          // 空 state → 跳过
  d.timeline.push({ at: 'x', stage: 'ghost', state: DONE }) // 模板外 id → 忽略
  d.timeline.push({ at: 'x', state: DONE })      // 缺 stage → 跳过
  const s = statesOf(derive(d, ORDER))
  ok(s.implement === DONE && !('ghost' in s), 'T5.1 畸形/外条目不影响推导且不泄漏进返回键')
  ok(s.create_plan === DONE, 'T5.2 其余推导不受污染')
}

console.log(`\nSUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed > 0 ? 1 : 0)
