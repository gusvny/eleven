/**
 * tests/lane-blocked-history.mjs —— 泳道图受阻着色语义 UT（t260916-04）。
 *
 * 被测契约：src/client/lane-states.ts 的 deriveBlockedHistory（新）+ deriveStageStates
 * 规则 2 的「受阻已解除 → 完成色」换算。直跑：node
 * server/plugins/workbench/tests/lane-blocked-history.mjs（node>=22 type-stripping）。
 *
 * 覆盖（对齐工单四条子用例验收 + review_plan 附条件意见）：
 *   T1 复现子用例：t260916-02 实证形态——implement 同刻 done+blocked（受保护路径闸拒绝落盘），
 *      解除证据记在相邻后段（run_integration_tests running，后段证据任意条目型均可）
 *      → vis=done、resolvedBy=advanced；变体：同段重跑 done → resolvedBy=rerun。
 *   T2 真当前受阻子用例：blocked 后无任何后续 → 仍 blocked、无解除（③保守兜底）。
 *   T3 疑难子用例：
 *     3a 并行兄弟陷阱——兄弟段（同 phase/同 groups）done 不算本段推进证据；
 *     3b authorized/retry-requested 不作同段解除证据（人放了话≠活干成了，review 意见 2）；
 *     3c 老票（无 gen/phase）+ 无 groups（线性步骤条降级面）：后段条目按兄弟保守处理不解除；
 *        同夹具带 groups（泳道图面）→ 解除（advanced）——groups 在场即全语义。
 *   T4 关闭票子用例：closed → 全 done + 历史受阻 resolvedBy=closed（工单④）。
 *   T5 畸形输入子用例：非串字段/模板外 id/空 state/groups 非数组——不抛、不泄漏键。
 *   T6 兼容子用例：两参调用（既有消费方签名）返回形状 .states/.active/.fallback 不变，
 *      .blockedHistory 增键在场；并行双亮夹具行为不变。
 *
 * 全 hermetic：纯本地 fixture，零 Docker 零网络，3099 零接触。
 */
import assert from 'node:assert/strict'
import { deriveStageStates, deriveBlockedHistory } from '../src/client/lane-states.ts'

let passed = 0, failed = 0
const ok = (cond, label) => {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
const section = (t) => console.log(`\n== ${t}`)

const ORDER = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge']
const P = 'parallel_impl_design' // 并行相位名（与引擎 meta.parallel_phase 同词表）
const T = '2026-09-16T23:57:07'  // 工单实证时刻（同刻双记录形态）
let seq = 0
/** timeline 条目工厂：at 逐条自增保追加序可辨（时序=数组序，at 仅展示用）。 */
const tle = (stage, state, reason = '', gen, phase) => ({
  at: `${T.slice(0, -2)}${String(++seq).padStart(2, '0')}`,
  stage, state, reason,
  ...(gen !== undefined ? { gen } : {}),
  ...(phase ? { phase } : {}),
})
const okRes = (gen = 0) => ({ status: 'ok', gen })

section('T1 复现子用例（t260916-02 实证形态：同刻 done+blocked，解除证据在相邻后段）')
{
  const d = {
    status: 'dispatched', stage: 'run_integration_tests', stage_state: 'running',
    results: { create_plan: okRes(1), review_plan: okRes(1) },
    gens: { create_plan: 1, review_plan: 1, implement: 1, run_integration_tests: 1 },
    timeline: [
      tle('create_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('create_plan', 'done', 'developer-agent：方案定稿', 1),
      tle('review_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('review_plan', 'done', 'integration-agent：过', 1),
      tle('implement', 'running', 'Entered step (attempt 1)', 1, P),
      tle('implement', 'done', 'developer-agent：活干完', 1, P),
      tle('design_integration_tests', 'done', 'integration-agent：兄弟早已完成', 1, P),
      tle('implement', 'blocked', '受保护路径闸拒绝落盘：docs/design/契约v1.md', 1, P),
      tle('run_integration_tests', 'running', 'Entered step (attempt 1)', 1), // 推进证据（后段任意条目型）
    ],
  }
  const r = deriveStageStates(d, ORDER, { groups: [['implement', 'design_integration_tests']] })
  ok(r.states.implement === 'done', 'T1.1 implement 不再显当前受阻红（vis=done）')
  const h = r.blockedHistory.implement
  ok(!!h && h.resolved === true, 'T1.2 blockedHistory.implement.resolved=true')
  ok(h.resolvedBy === 'advanced', 'T1.3 解除方式=advanced（工作流已推进至后续段）')
  ok(h.passes.length === 1 && h.last.reason.includes('受保护路径闸拒绝落盘'), 'T1.4 受阻经过留档（次数+原因）')
  ok(typeof h.resolvedAt === 'string' && h.resolvedAt.length > 0, 'T1.5 解除证据时刻在场')
  ok(r.states.design_integration_tests === 'done', 'T1.6 兄弟段完成态不受污染')
  ok(r.active.includes('run_integration_tests'), 'T1.7 推进后的当前段正常入活跃数组')
  // 后段证据「任意条目型均可」：把推进证据换成 awaiting-human 型同样解除
  const d2 = { ...d, timeline: d.timeline.slice(0, -1).concat([tle('run_integration_tests', 'awaiting-human', '等人门', 1)]) }
  ok(deriveStageStates(d2, ORDER, { groups: [] }).blockedHistory.implement.resolvedBy === 'advanced',
    'T1.8 后段证据任意条目型均可（awaiting-human 亦算推进）')
}
section('T1b 同段重跑解除（rerun）')
{
  const d = {
    status: 'dispatched', stage: 'design_integration_tests', stage_state: 'running',
    results: { create_plan: okRes(1), review_plan: okRes(1), implement: okRes(1) },
    timeline: [
      tle('create_plan', 'done', '', 1),
      tle('review_plan', 'done', '', 1),
      tle('implement', 'running', 'Entered step (attempt 1)', 1),
      tle('implement', 'blocked', 'verify_red：泳道内 verify_lane code 红', 1),
      tle('implement', 'running', 'Entered step (attempt 2)', 2),   // retry_qc 重进
      tle('implement', 'done', 'developer-agent：重跑完成', 2),
    ],
  }
  const r = deriveStageStates(d, ORDER)
  ok(r.states.implement === 'done', 'T1b.1 重跑完成后 vis=done')
  ok(r.blockedHistory.implement.resolvedBy === 'rerun', 'T1b.2 解除方式=rerun（本段重跑完成）')
}
section('T2 真当前受阻子用例（blocked 后无任何后续 → 保守红）')
{
  const d = {
    status: 'dispatched', stage: 'merge_check', stage_state: 'blocked',
    results: { create_plan: okRes(1), review_plan: okRes(1) },
    timeline: [
      tle('create_plan', 'done', '', 1),
      tle('review_plan', 'done', '', 1),
      tle('merge_check', 'running', '程序化检查（第 1 轮）', 1),
      tle('merge_check', 'blocked', 'merge_check 红灯：verify_lane code 红', 1),
    ],
  }
  const r = deriveStageStates(d, ORDER, { groups: [] })
  ok(r.states.merge_check === 'blocked', 'T2.1 真当前受阻仍显红')
  ok(r.blockedHistory.merge_check.resolved === false, 'T2.2 无解除（resolved=false）')
  ok(r.blockedHistory.merge_check.resolvedBy === undefined, 'T2.3 无解除方式（角标不渲染的依据）')
}
section('T3 疑难子用例')
{
  // 3a 并行兄弟陷阱：兄弟段 done（同 phase）不是本段推进证据
  const d3a = {
    status: 'dispatched', stage: 'implement', stage_state: 'blocked',
    meta: { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: P },
    timeline: [
      tle('create_plan', 'done', '', 1),
      tle('review_plan', 'done', '', 1),
      tle('implement', 'running', 'Entered step (attempt 1)', 1, P),
      tle('implement', 'blocked', 'agent 报失败：容器故障', 1, P),
      tle('design_integration_tests', 'done', 'integration-agent：兄弟先干完', 1, P), // 同相位兄弟
    ],
  }
  const r3a = deriveStageStates(d3a, ORDER) // 无 groups（降级步骤条）——相位同=兄弟
  ok(r3a.states.implement === 'blocked', 'T3a.1 兄弟段 done 不解除本段（相位判定，无 groups）')
  ok(r3a.blockedHistory.implement.resolved === false, 'T3a.2 resolved=false')
  const r3aG = deriveStageStates(d3a, ORDER, { groups: [['implement', 'design_integration_tests']] })
  ok(r3aG.states.implement === 'blocked', 'T3a.3 兄弟段 done 不解除本段（groups 判定，泳道图面）')
  // 3b authorized/retry-requested 不作同段解除证据（review 意见 2：人放了话≠活干成了）
  const d3b = {
    status: 'dispatched', stage: 'create_plan', stage_state: 'blocked',
    timeline: [
      tle('create_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('create_plan', 'blocked', '受保护路径闸拒绝落盘', 1),
      tle('create_plan', 'authorized', '人审放行（受保护路径）', 1), // t260912-03 授权通道留痕
    ],
  }
  ok(deriveStageStates(d3b, ORDER).states.create_plan === 'blocked', 'T3b.1 authorized 不解除同段受阻')
  const d3b2 = {
    status: 'dispatched', stage: 'review_plan', stage_state: 'blocked',
    timeline: [
      tle('review_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('review_plan', 'blocked', '审读红灯', 1),
      tle('review_plan', 'retry-requested', '已请求重验', 1),
    ],
  }
  ok(deriveStageStates(d3b2, ORDER).states.review_plan === 'blocked', 'T3b.2 retry-requested 不解除同段受阻')
  // 真重跑进段后（retry-requested → running 第 2 次）照常显 ▶，不误红
  const d3b3 = {
    status: 'dispatched', stage: 'review_plan', stage_state: 'running',
    timeline: [
      tle('review_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('review_plan', 'blocked', '审读红灯', 1),
      tle('review_plan', 'retry-requested', '已请求重跑（第 1 次）', 1),
      tle('review_plan', 'running', 'Entered step (attempt 2)', 2),
    ],
  }
  ok(deriveStageStates(d3b3, ORDER).states.review_plan === 'running', 'T3b.3 真重跑进段后显 ▶（受阻期已离开）')
  // 3c 老票（无 gen/phase）+ 无 groups：后段条目按兄弟保守处理不解除；带 groups（泳道图）→ 解除
  const d3c = {
    status: 'dispatched', stage: 'run_integration_tests', stage_state: 'running',
    results: { create_plan: okRes(0) },
    timeline: [
      tle('create_plan', 'running', 'Entered step'),
      tle('create_plan', 'blocked', '越界探针'),
      tle('run_integration_tests', 'running', 'Entered step'), // 无相位标注的后段条目
    ],
  }
  const r3cLegacy = deriveStageStates(d3c, ORDER) // 降级面：无法判兄弟 → 保守红
  ok(r3cLegacy.states.create_plan === 'blocked', 'T3c.1 老票+无 groups：保守不解除（宁红不漏）')
  const r3cMap = deriveStageStates(d3c, ORDER, { groups: [] }) // groups 在场（哪怕空）：非同组即真推进
  ok(r3cMap.states.create_plan === 'done' && r3cMap.blockedHistory.create_plan.resolvedBy === 'advanced',
    'T3c.2 groups 在场 → 非兄弟后段=推进解除（泳道图面全语义）')
}
section('T4 关闭票子用例（closed → 全 done + 历史受阻 resolvedBy=closed）')
{
  const d = {
    status: 'closed', stage: 'merge', stage_state: 'done',
    results: { create_plan: okRes(2), merge: okRes(1) },
    timeline: [
      tle('create_plan', 'running', 'Entered step (attempt 1)', 1),
      tle('create_plan', 'blocked', '越界', 1),
      tle('create_plan', 'done', '重跑完成', 2),
      tle('merge', 'done', 'user：签字', 1),
    ],
  }
  const r = deriveStageStates(d, ORDER)
  ok(Object.values(r.states).every(v => v === 'done'), 'T4.1 closed 全 done 短路不破')
  ok(r.blockedHistory.create_plan.resolved === true && r.blockedHistory.create_plan.resolvedBy === 'closed',
    'T4.2 历史受阻段 resolvedBy=closed（角标渲染依据）')
  // 受阻后无 done 也随收口解除（工单④：历史受阻已随收口解除）
  const d2 = {
    status: 'closed', stage: 'merge', stage_state: 'done',
    timeline: [tle('review_plan', 'running', '', 1), tle('review_plan', 'blocked', '历史红灯', 1)],
  }
  const r2 = deriveStageStates(d2, ORDER)
  ok(r2.blockedHistory.review_plan.resolvedBy === 'closed', 'T4.3 收口解除不依赖同段后续条目')
}
section('T5 畸形输入子用例（外部快照不可信）')
{
  const d = {
    status: 'dispatched', stage: 'create_plan', stage_state: 'blocked',
    timeline: [
      null, 'x', 42,
      { at: T },                                  // 缺 stage/state
      { at: T, stage: 123, state: 'blocked' },    // 非串字段
      { at: T, stage: 'ghost', state: 'blocked' },// 模板外 id
      { at: T, stage: 'create_plan', state: '' }, // 空 state
      tle('create_plan', 'running', '', 1),
      tle('create_plan', 'blocked', '真受阻', 1),
    ],
  }
  const r = deriveStageStates(d, ORDER, { groups: 'junk' }) // groups 非数组 → 按未知处理
  ok(r.states.create_plan === 'blocked', 'T5.1 畸形条目不解除真受阻（不抛）')
  ok(r.blockedHistory.create_plan.resolved === false && r.blockedHistory.create_plan.passes.length === 1,
    'T5.2 只有合法 blocked 条目计入 passes')
  ok(!('ghost' in r.blockedHistory), 'T5.3 模板外 id 不泄漏进返回键')
  ok(deriveBlockedHistory({ timeline: null }, ORDER) !== null
    && Object.keys(deriveBlockedHistory({ timeline: null }, ORDER)).length === 0, 'T5.4 timeline 缺失 → 空史不抛')
  ok(deriveStageStates(d, ORDER).blockedHistory && deriveStageStates(d, ORDER).fallback !== undefined,
    'T5.5 无 opts 调用（既有消费方形状）不抛')
}
section('T6 兼容子用例（返回形状增键不破既有消费）')
{
  const d = {
    status: 'dispatched', stage: 'design_integration_tests', stage_state: 'running',
    meta: { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: P },
    results: { create_plan: okRes(1), review_plan: okRes(1) },
    timeline: [
      tle('create_plan', 'done', '', 1),
      tle('review_plan', 'done', '', 1),
      tle('implement', 'running', '', 1, P),
      tle('design_integration_tests', 'running', '', 1, P),
    ],
  }
  const r = deriveStageStates(d, ORDER)
  ok(r.states.implement === 'running' && r.states.design_integration_tests === 'running'
    && r.active.length === 2, 'T6.1 并行双亮行为不变')
  ok(Array.isArray(r.active) && typeof r.fallback === 'boolean' && typeof r.states === 'object',
    'T6.2 .states/.active/.fallback 形状不变')
  ok(r.blockedHistory && Object.keys(r.blockedHistory).length === 0, 'T6.3 无受阻史 → blockedHistory 空对象（增键在场）')
  const fb = deriveStageStates({ status: 'dispatched', stage: 'implement', stage_state: 'running', timeline: null }, ORDER)
  ok(fb.fallback === true && fb.blockedHistory, 'T6.4 回退口径（无 timeline）同样带 blockedHistory 键')
}

console.log(`\nLANE_BLOCKED_HISTORY_TESTS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
