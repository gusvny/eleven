/**
 * grants.test.mjs —— 授予派生 UT（决定 10/15）：固定操作清单×模板事实、人门过滤、
 * 巡检无暂停面过滤、一键收回全隐、未声明显式降级、workbench 形状漂移不猜。
 */
import { assert, done } from './lib.mjs'
import { deriveGrants, extractTemplateFacts, grantsUnavailable, FIXED_OPS } from '../src/host/grants.ts'

let n = 0

const devLane = { name: 'dev-lane', kind: 'dev', has_human_gate: true }
const inspection = { name: 'inspection', kind: 'inspection', has_human_gate: false }

// 决定 10 事实一：有人门的模板才有「签」；无人门 → sign 行隐藏且点名原因。
// 派生=只出显示行；被过滤的项以计数+note 点名（payload 不携带被过滤项的字样）。
const r1 = deriveGrants([inspection], true, true)
assert(r1.ok === true && r1.rows.length === FIXED_OPS.length - 2, 'inspection template: sign+capability-filtered ops hidden, rest shown')
assert(r1.filtered === 2 && /decision 10\/15/.test(r1.filtered_note), 'filtered count + decision-referencing note (explicit, not an empty table)')

// 决定 10 事实一：无人门的模板不显「签」——有门模板才出 sign 行。
const r2 = deriveGrants([devLane], true, true)
assert(r2.rows.find(r => r.op === 'sign') !== undefined, 'human-gate template shows sign')
assert(r2.rows.find(r => r.op === 'sign') === undefined || r1.rows.find(r => r.op === 'sign') === undefined, 'sign only for templates with a human gate (decision 10 fact 1)')
assert(r2.rows.find(r => r.op === 'pause-resume') !== undefined, 'non-inspection template shows the pause-surface op')

// 未声明 / 已收回：显式对象，绝不渲染成「无授权」空表。
assert(deriveGrants([devLane], false, true).ok === false, 'undeclared project = explicit degraded, not an empty list')
const r3 = deriveGrants([devLane], true, false)
assert(r3.ok === true && r3.rows.length === 0 && r3.filtered_note.includes('revoked'), 'enabled:false = all-revoked note (derived, nothing hand-maintained)')

// 形状提取：容 result/workflows/顶层三种数组位 + nodes/topology 人门标记。
assert(extractTemplateFacts({ result: { workflows: [{ id: 'a', kind: 'dev', nodes: [{ exit: 'human' }] }] } }).facts[0].has_human_gate === true, 'human gate via nodes[].exit=human')
assert(extractTemplateFacts({ workflows: [{ name: 'b', kind: 'dev', topology: 'exit=human at gate merge' }] }).facts[0].has_human_gate === true, 'human gate via topology text')
assert(extractTemplateFacts([{ name: 'c', kind: 'dev', has_human_gate: true }]).facts[0].has_human_gate === true, 'human gate via explicit flag')
assert(extractTemplateFacts({ workflows: [{ name: 'd', kind: 'inspection' }] }).facts[0].has_human_gate === false, 'no gate marker = false (no guessing)')
assert(extractTemplateFacts({ workflows: [{ id: 'inspection', name: 'Inspect' }] }).facts[0].kind === 'inspection', 'inspection family recognized by template id when kind absent (decision 15 filter input)')
assert(extractTemplateFacts({ workflows: [{ id: 'dev-lane', name: 'Dev' }] }).facts[0].kind === 'unknown', 'unrecognized family stays unknown (no finer guessing)')

// 真端点形状（仲裁 gen1 打回点）：stages[].exit==='human' 与 topology.nodes[].kind==='human'。
{
  const real = { id: 'dev-lane', name: 'Dev',
    stages: [{ id: 's1', role: 'agent' }, { id: 's2', role: 'human', exit: 'human' }],
    topology: { nodes: [{ id: 's1', kind: 'agent' }, { id: 's2', kind: 'human' }], edges: [['s1', 's2']] } }
  const f = extractTemplateFacts({ workflows: [real] }).facts[0]
  assert(f.has_human_gate === true, 'real endpoint shape: gate via stages[].exit=human')
  assert(extractTemplateFacts({ workflows: [{ ...real, stages: undefined }] }).facts[0].has_human_gate === true, 'real endpoint shape: gate via topology.nodes[].kind=human')
  const insp = extractTemplateFacts({ workflows: [{ id: 'inspection-lite', name: 'Inspect',
    stages: [{ id: 'i1', role: 'agent' }], topology: { nodes: [{ id: 'i1', kind: 'agent' }], edges: [] } }] }).facts[0]
  assert(insp.has_human_gate === false && insp.kind === 'inspection', 'agent-only stages/topology = no gate; inspection family by id')
  // 派生联动：真形状模板必须出 sign 行（决定 10 的头条）。
  assert(deriveGrants([extractTemplateFacts({ workflows: [real] }).facts[0]], true, true).rows.some(r => r.op === 'sign'), 'derived grants include sign for the real-shape human-gate template')
}

// 形状漂移：数组缺席 / 项缺 name / 非对象项 → 显式降级，不猜。
assert(extractTemplateFacts({ foo: 1 }).ok === false, 'unrecognizable shape = explicit degrade')
assert(extractTemplateFacts({ workflows: [{ kind: 'x' }] }).ok === false, 'item missing name/id = explicit degrade')
assert(extractTemplateFacts({ workflows: ['nope'] }).ok === false, 'non-object item = explicit degrade')

// 不可达降级对象原样透传。
const un = grantsUnavailable('workbench unreachable: boom')
assert(un.ok === false && un.reason.includes('boom'), 'unavailable reason carried for explicit rendering')

n += 16
done(n)
