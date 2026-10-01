/**
 * tests/t261001-11-gate-shape-tolerance.mjs —— 问题区 gate_runs 双形态容忍 UT。
 *
 * 根因（t261001-11）：D2Problems 旧代码 `g.checks.filter(...)` 假设 gate_runs
 * 末条必带 checks 数组；轻道 run_integration_tests 的闸记录无该键 →
 * TypeError → 槽条目崩 → 整个侧栏退回 dsh 默认 UI。
 *
 * 直跑：node server/plugins/workbench/tests/t261001-11-gate-shape-tolerance.mjs
 * 覆盖：
 *   A. 反证明（anti-proof）：旧读者表达式在轻道真实记录形态上必抛——
 *      用票面引述的逐字键族复现，断言新模型不抛而旧表达式抛。
 *   B. gateProblemRows 双形态：dev-lane merge_check 红（带 checks）与
 *      轻道闸红（无 checks，真实字段集）各出原因行，均不抛。
 *   C. 畸形输入面：非对象 detail / gate_runs 非数组 / 末条非对象 /
 *      checks 元素畸形 / counts 畸形 → 不抛、行为明确。
 *   D. 源级锚：index.tsx 的 D2Problems 消费 gateProblemRows，旧
 *      `g.checks.filter` 字面量已退役；GateRun 类型 checks 已可选。
 * 全程纯函数直跑 + 源文本断言，不碰 3099、不起 console、不跑集成。
 */

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  gateProblemRows, gateStageLabel, lastGateRun, slotFaultMessage,
} from '../src/client/problems-model.ts'

const here = dirname(fileURLToPath(import.meta.url))
const repo = (() => {
  let d = here
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── 真实记录形态（票面引述 + 引擎 light_lane.py 落账键族） ── */

// dev-lane merge_check 形态：带 checks 数组（{item, green, detail}）
const devLaneMergeCheck = {
  status: 'running', stage_state: 'blocked',
  stage: 'merge_check', stage_name: 'merge_check',
  gate_runs: [{ stage: 'merge_check', label: 'merge check', green: false, red_count: 1,
    checks: [
      { item: 'pytest gate', green: true },
      { item: 'lint', green: false, detail: '3 errors' },
    ] }],
  timeline: [{ at: 'x', stage: 'merge_check', state: 'blocked', reason: 'merge_check red' }],
}

// 轻道闸形态：无 checks 键（票面引述的逐字键族；t261001-10 实弹同形）
const lightLaneGate = {
  status: 'running', stage_state: 'blocked',
  stage: 'run_integration_tests', stage_name: 'run_integration_tests',
  gate_runs: [{ stage: 'run_integration_tests', label: 'machine gate (verify_lane integ, round 1)',
    green: false, red_count: 2, exit_code: 1,
    counts: { ran: 12, passed: 10, failed: 2, env_fail: 0 },
    error: '', narrowed: 3, excluded_pools: [], known_red_skipped: 1 }],
  timeline: [{ at: 'x', stage: 'run_integration_tests', state: 'blocked', reason: 'machine gate red' }],
}

/* ── A. 反证明：旧表达式在轻道形态上抛（pre-fix 红的根因） ── */
{
  const g = lightLaneGate.gate_runs[0]
  let oldThrows = false
  try { g.checks.filter(x => !x.green) } catch { oldThrows = true }
  ok(oldThrows, 'A: 旧读者表达式 g.checks.filter 在轻道记录上抛 TypeError（反证明）')
  let newOk = true, rows = []
  try { rows = gateProblemRows(lightLaneGate) } catch (e) { newOk = false; console.error(e) }
  ok(newOk && rows.length > 0, 'A: 新模型同一输入不抛且出原因行')
}

/* ── B. 双形态各出原因行 ── */
{
  const rows = gateProblemRows(devLaneMergeCheck)
  ok(rows.length === 1, 'B: dev-lane merge_check 红 → 只列红项（绿项不占行）')
  ok(rows[0].text === 'merge_check red: lint' && rows[0].dim === '3 errors',
    'B: dev-lane 红项行=merge_check red: lint — 3 errors')

  const lrows = gateProblemRows(lightLaneGate)
  ok(lrows.length >= 1, 'B: 轻道闸红 → 至少一行原因')
  ok(lrows.some(r => r.text.includes('ran=12 / passed=10 / failed=2 / env_fail=0')),
    'B: 轻道 counts 对账行在场')
  ok(lrows.some(r => r.text.includes('2 red item(s)')), 'B: red_count 行在场')
  // error 空串不占行（引擎落 str(ir.error or '')，绿跑同形）
  ok(!lrows.some(r => r.key === 'error'), 'B: 空 error 不占行')

  // 真实 error 非空：点名原文
  const withErr = JSON.parse(JSON.stringify(lightLaneGate))
  withErr.gate_runs[0].error = 'scenario sc_x exited 1'
  const erows = gateProblemRows(withErr)
  ok(erows.some(r => r.key === 'error' && r.text.includes('scenario sc_x exited 1')),
    'B: 非空 error 原文入行')
}

/* ── C. 畸形输入面（消费外部记录的实现必带畸形用例） ── */
{
  for (const bad of [undefined, null, 42, 'x', {}, { gate_runs: 'no' }, { gate_runs: [] },
    { gate_runs: [null, 7, 'x'] }]) {
    let threw = false
    try { gateProblemRows(bad) } catch { threw = true }
    ok(!threw, `C: 畸形 detail 不抛（${JSON.stringify(bad)}）`)
  }
  ok(JSON.stringify(gateProblemRows({ gate_runs: [{ stage: 's', green: false }] })) !== '[]'
    || true, 'C: 无明细红闸→兜底行（见下行精确断言）')
  const bare = gateProblemRows({ gate_runs: [{ stage: 's', label: 'gate L', green: false }] })
  ok(bare.length === 1 && bare[0].text.includes('gate L') && bare[0].text.includes('red'),
    'C: 无明细红闸 → 点名 stage 标签 + red 兜底行（绝不静默空白）')
  ok(gateProblemRows({ gate_runs: [{ stage: 's', green: true }] }).length === 0,
    'C: 绿闸不出行')
  ok(gateProblemRows({ gate_runs: [{ stage: 's' }] }).length === 0,
    'C: green 缺席（awaiting-human 同形）不出行')
  // checks 数组内畸形元素逐条跳过
  const mixed = gateProblemRows({ gate_runs: [{ stage: 'm', green: false,
    checks: [null, 'x', 3, { green: false }, { item: 'ok-row', green: false, detail: 'd' }] }] })
  ok(mixed.length === 2 && mixed[1].text.includes('ok-row'), 'C: checks 畸形元素跳过不抛')
  // counts 畸形：非对象/数值外值逐对跳过
  const badCounts = gateProblemRows({ gate_runs: [{ stage: 'c', green: false, counts: 'no' }] })
  ok(badCounts.length === 1 && badCounts[0].text.includes('red'), 'C: counts 非对象 → 兜底行不抛')
}

/* ── C2. 槽错误边界纯面：崩溃点名故障、其余 UI 存活 ── */
{
  // 模拟槽条目渲染期抛错（fixture：真实异常对象 + 畸形输入）
  const fixtureThrow = () => { throw new TypeError("Cannot read properties of undefined (reading 'filter')") }
  let caught
  try { fixtureThrow() } catch (e) { caught = e }
  const msg = slotFaultMessage(caught)
  ok(msg.includes("reading 'filter'") && msg.includes('crashed') && msg.includes('stays usable'),
    'C2: fallback 文案点名故障并声明其余 UI 存活')
  ok(slotFaultMessage(undefined).includes('unknown fault'), 'C2: 畸形 error → unknown fault 兜底文案')
  ok(slotFaultMessage('boom').includes('boom'), 'C2: 字符串 error → 原文入文案')
  ok(slotFaultMessage({ code: 7 }).includes('unknown fault'), 'C2: 非串非 Error 对象 → 兜底文案不抛')
}

/* ── D. 源级锚（KI-052 家族）：纯函数绿但 UI 没接 = 红 ── */
{
  const src = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
  ok(src.includes('gateProblemRows(detail)'), 'D: D2Problems 消费 gateProblemRows')
  ok(!src.includes('g.checks.filter'), 'D: 旧 g.checks.filter 表达式已退役')
  ok(/checks\?:/.test(src), 'D: GateRun.checks 已改可选')
  ok(src.includes('class SlotErrorBoundary extends Component'), 'D: 错误边界类在场')
  ok(src.includes('getDerivedStateFromError') && src.includes('componentDidCatch'),
    'D: 边界两钩子齐备')
  // 槽条目注册位被边界包住：<SlotErrorBoundary><WorkbenchSidebar … /></SlotErrorBoundary>
  ok(src.includes('<SlotErrorBoundary><WorkbenchSidebar') &&
     src.includes('{...props} /></SlotErrorBoundary>'),
    'D: sidebar.workspaces 槽条目被边界整体包住')
  // 纯面单写者：模型文件真源（行推导不在组件里重写第二份）
  const model = readFileSync(join(repo, 'server/plugins/workbench/src/client/problems-model.ts'), 'utf8')
  ok(model.includes('export function gateProblemRows'), 'D: 行模型单写者在 problems-model.ts')
}

/* ── E. 辅助面真值表 ── */
{
  ok(lastGateRun({ gate_runs: [{ a: 1 }, { b: 2 }] }).b === 2, 'E: lastGateRun 取末条')
  ok(lastGateRun({ gate_runs: [null] }) === undefined, 'E: 末条非对象 → undefined')
  ok(gateStageLabel(undefined) === 'gate', 'E: 无 gate → 兜底标签 gate')
  ok(gateStageLabel({ label: 'L', stage: 's' }) === 'L', 'E: label 优先')
  ok(gateStageLabel({ stage: 's' }) === 's', 'E: label 缺 → stage')
  ok(gateStageLabel({}) === 'gate', 'E: 双缺 → gate')
}

console.log(`\nt261001-11-gate-shape-tolerance: ${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
