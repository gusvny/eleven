/**
 * tests/lane-map-model.mjs —— 真泳道图视图模型 UT（t260915-05，mock ③④）。
 *
 * 直跑：node server/plugins/workbench/tests/lane-map-model.mjs
 * 覆盖：
 *   A. parseTopology 清洗：合法契约通过；畸形（非对象/无节点/kind 越词表/重复 id/
 *      悬空边/组员越表/组员<2）逐条降级——null=渲染器回落线性步骤条。
 *   B. buildLaneMap：主道渲染序（组折叠）、并行组 active（meta.parallel_stages 真源）、
 *      轮次带 gen 分组 + ×N 徽章 + rework 轮格、老票（无 gen）回退 running 计数切轮、
 *      handoff 按序消费、closed 终态全 done、人门到站 humanGateActive、畸形 detail 不抛。
 *   B2. 受阻史接线（t260916-04）。
 *   B3/B4/B5. 认领行（adopt/awaiting）不成轮（实报 t260930-09：首段凭空多一格 + ×N
 *      徽章撒谎）、真重入照旧逐轮、无认领行的段逐字节不变、形状不认识不静默丢行。
 *   C. buildChecksDetail（检查明细区模型）：逐行 ✓/✗/item/detail/checkId/reasonCode/
 *      files/nextAction、绿项 id-only 可读、最新轮在前、畸形条目跳过。
 *   D. 渲染器通用性（模型半）：fixture-two-step 线性拓扑同组件建模——无组、
 *      标签来自拓扑、模型面零 dev-lane 词。
 * 全程纯函数直跑，不碰 3099、不起 console。
 */
import assert from 'node:assert/strict'
import {
  parseTopology, buildLaneMap, buildChecksDetail, deriveRounds,
} from '../src/client/lane-map-model.ts'

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* dev-lane 拓扑夹具（与引擎 template_topology 导出同构；改契约须同步） */
const DEV_LANE_TOPOLOGY = {
  version: 'topology-v1',
  template: 'dev-lane',
  name: '开发泳道',
  nodes: [
    { id: 'create_plan', label: '做方案', role: 'developer', kind: 'agent', parts: ['agent'] },
    { id: 'review_plan', label: '审方案', role: 'integration', kind: 'agent', parts: ['agent'] },
    { id: 'implement', label: '实现', role: 'developer', kind: 'agent', parts: ['agent', 'script'] },
    { id: 'design_integration_tests', label: '设计集成测试', role: 'integration', kind: 'agent', parts: ['agent'] },
    { id: 'ui_evidence', label: 'UI截图证据', role: 'developer', kind: 'agent', parts: ['script'], optional: '仅 UI 票' },
    { id: 'run_integration_tests', label: '跑集成测试', role: 'integration', kind: 'gate', parts: ['script'] },
    { id: 'arbitrate', label: '仲裁', role: 'integration', kind: 'agent', parts: ['agent', 'script'] },
    { id: 'acceptance_walkthrough', label: '验收走查', role: 'integration', kind: 'agent', parts: ['agent', 'script'] },
    { id: 'merge_check', label: '合并检查', role: 'integration', kind: 'gate', parts: ['script'] },
    { id: 'merge', label: '合并（人审）', role: 'integration', kind: 'human', parts: ['human', 'script'] },
  ],
  edges: [
    ['create_plan', 'review_plan'],
    ['review_plan', 'implement'], ['review_plan', 'design_integration_tests'],
    ['implement', 'ui_evidence'], ['design_integration_tests', 'ui_evidence'],
    ['ui_evidence', 'run_integration_tests'],
    ['run_integration_tests', 'arbitrate'], ['run_integration_tests', 'acceptance_walkthrough'],
    ['arbitrate', 'merge_check'], ['acceptance_walkthrough', 'merge_check'],
    ['merge_check', 'merge'],
  ],
  groups: [
    { id: 'parallel_impl_design', members: ['implement', 'design_integration_tests'], phase: 'parallel_impl_design' },
    { id: 'arb_acc_parallel', members: ['arbitrate', 'acceptance_walkthrough'], phase: 'arb_acc_parallel' },
  ],
}

const FIXTURE_TOPOLOGY = {
  template: 'fixture-two-step',
  nodes: [
    { id: 'fx_step_one', label: '夹具段一', role: 'developer', kind: 'agent', parts: [] },
    { id: 'fx_step_two', label: '夹具段二', role: 'integration', kind: 'agent', parts: [] },
  ],
  edges: [['fx_step_one', 'fx_step_two']],
  groups: [],
}

/* ── A. parseTopology 清洗 ── */
ok(parseTopology(DEV_LANE_TOPOLOGY) !== null, 'A: 合法契约通过')
ok(parseTopology(null) === null && parseTopology('x') === null && parseTopology(42) === null, 'A: 非对象 → null')
ok(parseTopology({}) === null && parseTopology({ nodes: [] }) === null, 'A: 无节点 → null（回落线性）')
ok(parseTopology({ nodes: [{ id: 'a', label: '甲', kind: 'magic' }] }) === null, 'A: kind 越词表逐条丢弃 → 无节点 null')
ok(parseTopology({ nodes: [{ id: 'a', label: '', kind: 'agent' }] }) === null, 'A: 缺 label 丢弃 → null')
{
  const t = parseTopology({
    nodes: [
      { id: 'a', label: '甲', kind: 'agent' }, { id: 'a', label: '重复', kind: 'agent' },
      { id: 'b', label: '乙', kind: 'gate' },
    ],
    edges: [['a', 'b'], ['a', 'ghost'], 'junk', ['a']],
    groups: [{ id: 'g', members: ['a', 'ghost'] }, { id: 'h', members: ['a'] }],
  })
  ok(t !== null && t.nodes.length === 2, 'A: 重复 id 去重保留首个')
  ok(t.edges.length === 1 && t.edges[0][1] === 'b', 'A: 悬空边/畸形边逐条过滤')
  ok(t.groups.length === 0, 'A: 组员越表/单成员组过滤')
}

/* ── B. buildLaneMap ── */
{
  const detail = {
    status: 'running', stage: 'implement', stage_state: 'running',
    meta: { parallel_stages: ['implement', 'design_integration_tests'], parallel_phase: 'parallel_impl_design' },
    gens: { create_plan: 3, implement: 1 },
    timeline: [
      { at: 'T1', stage: 'create_plan', state: 'running', reason: '第 1 次', gen: 1 },
      { at: 'T2', stage: 'create_plan', state: 'rework', reason: '审读打回：写集补列', gen: 1 },
      { at: 'T3', stage: 'create_plan', state: 'running', reason: '第 2 次', gen: 2 },
      { at: 'T4', stage: 'create_plan', state: 'blocked', reason: '闸拒绝', gen: 2 },
      { at: 'T5', stage: 'create_plan', state: 'running', reason: '第 3 次', gen: 3 },
      { at: 'T6', stage: 'create_plan', state: 'done', reason: '定稿', gen: 3 },
      { at: 'T7', stage: 'implement', state: 'running', gen: 1, phase: 'parallel_impl_design' },
      { at: 'T7', stage: 'design_integration_tests', state: 'running', gen: 1, phase: 'parallel_impl_design' },
    ],
    handoffs: [
      { stage: 'create_plan', summary: '方案 v3', ts: 1, gen: 3 },
    ],
  }
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, detail)
  ok(m !== null, 'B: 模型构建成功')
  ok(m.items.map(i => i.kind === 'group' ? `g:${i.id}` : i.id).join(',') ===
    'create_plan,review_plan,g:parallel_impl_design,ui_evidence,run_integration_tests,g:arb_acc_parallel,merge_check,merge',
    'B: 主道渲染序=组折叠单向流')
  const cp = m.nodes['create_plan']
  ok(cp.rounds.length === 3 && cp.badge === '×3', 'B: 轮次带 3 轮 + ×N 徽章')
  ok(cp.rounds[0].state === 'rework' && cp.rounds[0].reason === '审读打回：写集补列', 'B: 第 1 轮结局=rework+打回原因')
  ok(cp.rounds[1].state === 'blocked', 'B: 第 2 轮结局=blocked')
  ok(cp.rounds[2].state === 'done' && cp.rounds[2].handoffSummary === '方案 v3', 'B: 第 3 轮 done+同 gen handoff 摘要')
  ok(m.nodes['ui_evidence'].node.optional === '仅 UI 票', 'B: 条件段注记透传')
  ok(m.groups['parallel_impl_design'].active === true, 'B: 并行组 active（parallel_stages 真源+双 running）')
  ok(m.nodes['implement'].vis === 'running' && m.nodes['design_integration_tests'].vis === 'running', 'B: 双道同亮')
  ok(m.humanGateActive === null, 'B: 人门未到站')
  ok(m.topology.edges.length === 11 && m.topology.nodes.length === 10, 'B: 契约边/节点数保持')
}
{
  // closed 终态：全 done（KI-027 关单同图）+ 人门到站
  const closed = {
    status: 'closed', stage: 'merge', stage_state: 'awaiting-human',
    gens: { merge: 1 },
    timeline: [{ at: 'T1', stage: 'merge', state: 'awaiting-human', reason: '等人签字', gen: 1 }],
  }
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, closed)
  ok(m.closed === true, 'B: closed 旗标')
  ok(Object.values(m.nodes).every(n => n.vis === 'done'), 'B: closed 终态全 done（轮次带仍在）')
  const m2 = buildLaneMap(DEV_LANE_TOPOLOGY, {
    status: 'running', stage: 'merge', stage_state: 'awaiting-human',
    timeline: [{ at: 'T1', stage: 'merge', state: 'awaiting-human', reason: '等人签字' }],
  })
  ok(m2.humanGateActive === 'merge', 'B: 人门到站 humanGateActive=merge')
}
{
  // 老票回退：无 gens、timeline 无 gen → running 计数切轮；handoff 按序消费
  const legacy = {
    status: 'running', stage: 'review_plan', stage_state: 'running',
    timeline: [
      { at: 'L1', stage: 'review_plan', state: 'running', reason: '进审' },
      { at: 'L2', stage: 'review_plan', state: 'rework', reason: '打回意见 1' },
      { at: 'L3', stage: 'review_plan', state: 'running', reason: '再审' },
      { at: 'L4', stage: 'review_plan', state: 'done', reason: '过' },
    ],
    handoffs: [
      { stage: 'acceptance', summary: '走查报告 1', ts: 1 },
      { stage: 'acceptance', summary: '走查报告 2', ts: 2 },
    ],
  }
  ok(deriveRounds('review_plan', legacy).length === 2, 'B: 老票 running 计数切轮（2 轮）')
  ok(deriveRounds('acceptance_walkthrough', legacy).length === 0, 'B: 无 mark 无轮（handoff 不凭空造轮，诚实缺省）')
  const accWithMarks = {
    timeline: [
      { at: 'A1', stage: 'acceptance_walkthrough', state: 'running' },
      { at: 'A2', stage: 'acceptance_walkthrough', state: 'done' },
      { at: 'A3', stage: 'acceptance_walkthrough', state: 'running' },
      { at: 'A4', stage: 'acceptance_walkthrough', state: 'done' },
    ],
    handoffs: [
      { stage: 'acceptance', summary: '走查报告 1', ts: 1 },
      { stage: 'acceptance', summary: '走查报告 2', ts: 2 },
    ],
  }
  const accRounds = deriveRounds('acceptance_walkthrough', accWithMarks)
  ok(accRounds.length === 2 && accRounds[0].handoffSummary === '走查报告 1' && accRounds[1].handoffSummary === '走查报告 2',
    'B: handoff 别名（acceptance→acceptance_walkthrough）按序逐轮消费')
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, legacy)
  ok(m.nodes['review_plan'].rounds[0].handoffSummary === undefined, 'B: 无同段 handoff 时轮格缺省（不串段）')
}
{
  // 畸形 detail：junk timeline / 非对象 meta / 空对象——全程不抛、视图可建
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, { status: 42, timeline: [null, 'x', { stage: 1 }, { stage: 'merge', state: '' }], meta: 'junk' })
  ok(m !== null && Object.values(m.nodes).every(n => n.rounds.length === 0), 'B: 畸形 detail 不抛，轮次带为空')
  ok(buildLaneMap(DEV_LANE_TOPOLOGY, null) !== null, 'B: detail=null 软降级（拓扑半仍可画）')
}

/* ── B2. 受阻史接线（t260916-04）：groups 透传解除判定，节点视图携史 ── */
{
  // 复现子用例形态：implement 同刻 done+blocked，解除证据记在相邻后段（run_integration_tests）
  const detail = {
    status: 'running', stage: 'run_integration_tests', stage_state: 'running',
    results: { create_plan: { status: 'ok', gen: 1 }, review_plan: { status: 'ok', gen: 1 } },
    gens: { create_plan: 1, review_plan: 1, implement: 1, run_integration_tests: 1 },
    timeline: [
      { at: 'T1', stage: 'create_plan', state: 'running', reason: '', gen: 1 },
      { at: 'T2', stage: 'create_plan', state: 'done', reason: '', gen: 1 },
      { at: 'T3', stage: 'review_plan', state: 'running', reason: '', gen: 1 },
      { at: 'T4', stage: 'review_plan', state: 'done', reason: '', gen: 1 },
      { at: 'T5', stage: 'implement', state: 'running', reason: '', gen: 1, phase: 'parallel_impl_design' },
      { at: 'T6', stage: 'implement', state: 'done', reason: '活干完', gen: 1, phase: 'parallel_impl_design' },
      { at: 'T7', stage: 'implement', state: 'blocked', reason: '受保护路径闸拒绝落盘', gen: 1, phase: 'parallel_impl_design' },
      { at: 'T8', stage: 'run_integration_tests', state: 'running', reason: '', gen: 1 },
    ],
  }
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, detail)
  ok(m !== null && m.nodes['implement'].vis === 'done', 'B2: implement 显完成色（不钉红）')
  const bh = m.nodes['implement'].blockedHistory
  ok(!!bh && bh.resolved === true && bh.resolvedBy === 'advanced', 'B2: 节点视图携解除史（advanced）')
  ok(bh.last.reason === '受保护路径闸拒绝落盘' && bh.passes.length === 1, 'B2: hover 经过数据源（最近受阻+计数）')
  ok(m.nodes['create_plan'].blockedHistory === undefined, 'B2: 无受阻史的段不带键')
  // 真当前受阻：无后续证据 → vis=blocked 且史标未解除（渲染层据此不出角标）
  const m2 = buildLaneMap(DEV_LANE_TOPOLOGY, {
    status: 'running', stage: 'merge_check', stage_state: 'blocked',
    timeline: [
      { at: 'T1', stage: 'create_plan', state: 'done', reason: '', gen: 1 },
      { at: 'T2', stage: 'merge_check', state: 'running', reason: '', gen: 1 },
      { at: 'T3', stage: 'merge_check', state: 'blocked', reason: 'verify_red', gen: 1 },
    ],
  })
  ok(m2.nodes['merge_check'].vis === 'blocked', 'B2: 真当前受阻仍红')
  ok(m2.nodes['merge_check'].blockedHistory.resolved === false, 'B2: 未解除史在场（角标渲染闸）')
  // closed：历史受阻段随收口解除（工单④）
  const m3 = buildLaneMap(DEV_LANE_TOPOLOGY, {
    status: 'closed', stage: 'merge', stage_state: 'done',
    timeline: [{ at: 'T1', stage: 'create_plan', state: 'blocked', reason: '越界', gen: 1 }],
  })
  ok(m3.nodes['create_plan'].vis === 'done' && m3.nodes['create_plan'].blockedHistory.resolvedBy === 'closed',
    'B2: closed 历史受阻=完成色+closed 解除史')
}

/* ── B3. 认领行（adopt）不成轮：实报 t260930-09 回归（轻道首段被画成两轮） ── */
{
  // 真票据形态＝server/ledger/sandbar.jsonl 里 t260930-09 的 seq1-4 逐字（gen 键原样）
  const lightTicket = {
    status: 'running', stage: 'implement', stage_state: 'running',
    timeline: [
      { at: '2026-09-30T08:09:09+00:00', stage: 'implement', state: 'awaiting',
        reason: "adopt light-lane（步=['implement', 'ui_evidence', 'run_integration_tests', "
                + "'merge_check', 'merge']）", gen: 0 },
      { at: '2026-09-30T08:09:09+00:00', stage: 'workspace', state: 'ready',
        reason: 'prepare_workspace: worktree/created+deps:server/engine/.venv', gen: 0 },
      { at: '2026-09-30T08:09:09+00:00', stage: 'implement', state: 'running',
        reason: '进入本步（第 1 次）', gen: 1 },
      { at: '2026-09-30T08:26:25+00:00', stage: 'implement', state: 'done',
        reason: '交接报告落盘', gen: 1 },
    ],
  }
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, lightTicket)
  const iv = m.nodes['implement']
  ok(m !== null && iv.rounds.length === 1 && iv.rounds[0].gen === 1 && iv.rounds[0].state === 'done',
    'B3: 认领行不成轮——首段只余真入场那一轮（gen=1）')
  ok(iv.badge === '', 'B3: 认领行不再把首段撑成 ×2 徽章（渲染层少一格）')
  ok(!iv.rounds.some(r => r.gen === 0), 'B3: 无 gen=0 幽灵轮')
  ok(deriveRounds('implement', lightTicket).length === 1, 'B3: deriveRounds 直调同口径')
  // 老票同形（无 gen）：认领行过去被「running mark 切轮」口径当成首轮
  const legacyAdopt = {
    status: 'running', stage: 'implement', stage_state: 'running',
    timeline: [
      { at: 'T0', stage: 'implement', state: 'awaiting', reason: 'adopt v2（模版=dev-lane，stages=[...]）' },
      { at: 'T1', stage: 'implement', state: 'running', reason: '进入' },
      { at: 'T2', stage: 'implement', state: 'done', reason: '完事' },
    ],
  }
  const lr = deriveRounds('implement', legacyAdopt)
  ok(lr.length === 1 && lr[0].gen === 1 && lr[0].at === 'T1', 'B3: 无 gen 老票同形——认领行不占轮，真入场仍是第 1 轮')
}

/* ── B4. 真重入照旧逐轮（修不吞返工：只剔认领行，不剔「首次出现」） ── */
{
  const rework = {
    status: 'running', stage: 'implement', stage_state: 'running',
    timeline: [
      { at: 'T0', stage: 'implement', state: 'awaiting', reason: 'adopt light-lane（步=[...]）', gen: 0 },
      { at: 'T1', stage: 'implement', state: 'running', reason: '进入本步（第 1 次）', gen: 1 },
      { at: 'T2', stage: 'implement', state: 'rework', reason: '验收打回：证据缺', gen: 1 },
      { at: 'T3', stage: 'implement', state: 'running', reason: '进入本步（第 2 次）', gen: 2 },
      { at: 'T4', stage: 'implement', state: 'done', reason: '第 2 次完成', gen: 2 },
    ],
  }
  const rounds = deriveRounds('implement', rework)
  ok(rounds.length === 2 && rounds[0].gen === 1 && rounds[1].gen === 2,
    'B4: 真重入两轮仍在（认领行剔除不吃返工）')
  ok(rounds[0].state === 'rework' && rounds[0].reason === '验收打回：证据缺', 'B4: 第 1 轮结局=rework+打回原因')
  const m = buildLaneMap(DEV_LANE_TOPOLOGY, rework)
  ok(m.nodes['implement'].badge === '×2', 'B4: 徽章=真轮数 ×2（不是含认领行的 ×3）')
  const legacyRework = {
    timeline: [
      { at: 'T0', stage: 'implement', state: 'awaiting', reason: 'adopt dev-lane（步=[...]）' },
      { at: 'T1', stage: 'implement', state: 'running' },
      { at: 'T2', stage: 'implement', state: 'rework' },
      { at: 'T3', stage: 'implement', state: 'running' },
    ],
  }
  ok(deriveRounds('implement', legacyRework).length === 2, 'B4: 无 gen 老票重入仍两轮')
}

/* ── B5. 窄修锚：无认领行的段逐字节不变 + 形状不认识时保留现行口径 ── */
{
  const plain = {
    status: 'running', stage: 'merge_check', stage_state: 'running',
    timeline: [
      { at: 'T1', stage: 'merge_check', state: 'running', reason: '进入', gen: 1 },
      { at: 'T2', stage: 'merge_check', state: 'done', reason: '四项全绿', gen: 1 },
    ],
  }
  const r = deriveRounds('merge_check', plain)
  ok(r.length === 1 && r[0].gen === 1 && r[0].state === 'done' && r[0].at === 'T1'
    && r[0].reason === '四项全绿' && r[0].handoffSummary === undefined,
    'B5: 无认领行的段轮次带逐字节不变')
  const unknownAwaiting = {
    timeline: [
      { at: 'T0', stage: 'merge_check', state: 'awaiting', reason: '等人放行（非 adopt 起头）' },
      { at: 'T1', stage: 'merge_check', state: 'running', reason: '进入' },
    ],
  }
  ok(deriveRounds('merge_check', unknownAwaiting).length === 2,
    'B5: 非 adopt 形状的 awaiting 保留现行口径（形状不认识=如实成轮，不静默丢行）')
  const adoptReasonRunning = {
    timeline: [{ at: 'T0', stage: 'merge_check', state: 'running', reason: 'adopt 之后的真入场' }],
  }
  ok(deriveRounds('merge_check', adoptReasonRunning).length === 1,
    'B5: state≠awaiting 不参与剔除（形状判据负锁）')
}

/* ── C. buildChecksDetail ── */
{
  const detail = {
    gate_runs: [
      { stage: 'merge_check', label: 'merge_check（第 1 轮）', green: true, red_count: 0,
        checks: [{ id: 'worktree_clean', green: true }] },
      { stage: 'merge_check', label: 'merge_check（程序化检查·第 2 轮）', green: false, red_count: 1,
        checks: [
          { id: 'worktree_clean', item: '工作区干净', green: true },
          { id: 'verify_lane_code', item: '泳道自检', green: false, detail: 'red=3',
            reason_code: 'verify_red', files: ['integration/x.mjs'], next_action: '修复后 retry_qc' },
        ] },
      'junk', null,
    ],
  }
  const runs = buildChecksDetail(detail)
  ok(runs.length === 2, 'C: 畸形 gate_run 条目跳过')
  ok(runs[0].redCount === 1 && runs[0].green === false, 'C: 最新轮在前')
  ok(runs[0].rows.length === 2, 'C: 红轮两行（绿 id-only 行也在场）')
  const redRow = runs[0].rows.find(r => !r.green)
  ok(redRow.checkId === 'verify_lane_code' && redRow.reasonCode === 'verify_red', 'C: 红行带 check_id/reason_code')
  ok(redRow.files[0] === 'integration/x.mjs' && redRow.nextAction === '修复后 retry_qc', 'C: 红行带文件点名/下一步（与状态卡同源联动）')
  ok(runs[1].rows[0].item === 'worktree_clean', 'C: 绿项 id-only → id 即可读锚')
  ok(buildChecksDetail(null).length === 0 && buildChecksDetail({}).length === 0
    && buildChecksDetail({ gate_runs: 'x' }).length === 0, 'C: 畸形输入 → 空数组不抛')
}

/* ── D. 通用性对拍（模型半）：fixture-two-step 同组件 ── */
{
  const m = buildLaneMap(FIXTURE_TOPOLOGY, {
    status: 'running', stage: 'fx_step_two', stage_state: 'running',
    timeline: [{ at: 'F1', stage: 'fx_step_one', state: 'running' }, { at: 'F2', stage: 'fx_step_one', state: 'done' }],
  })
  ok(m !== null && m.items.length === 2 && m.items.every(i => i.kind === 'node'), 'D: 线性拓扑无组')
  ok(m.topology.nodes[0].label === '夹具段一', 'D: 标签来自拓扑（零业务词）')
  const surface = JSON.stringify(m)
  ok(!surface.includes('dev_lane') && !surface.includes('implement'), 'D: 模型面零 dev-lane 业务词泄漏')
  ok(m.nodes['fx_step_one'].vis === 'done' && m.nodes['fx_step_two'].vis === 'running', 'D: 同组件线性链状态推导')
}

console.log(`\nLANE_MAP_MODEL_TESTS pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
