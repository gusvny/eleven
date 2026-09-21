// t260915-08 巡检板面纯函数层 UT（src/host/inspection-face.ts 真值表 + review 执行项1 UI 子用例）。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  INSPECTION_TOPOLOGY, isInspectionRow, findingsCountOf, inspectionStageShort,
  inspectionProgressOf, inspectionTitleOf, inspectionSummaryOf,
} from '../src/host/inspection-face.ts'
import { deriveTicketState } from '../src/client/ticket-list-model.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根')
})()

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

// ---- 拓扑声明面：段 id 与引擎 _enter 的 stage 值同源（t260916-22 起=inspect/suite/report/close + setup）
ok(INSPECTION_TOPOLOGY.some(s => s.id === 'inspect') && INSPECTION_TOPOLOGY.some(s => s.id === 'close')
  && INSPECTION_TOPOLOGY.some(s => s.id === 'suite') && INSPECTION_TOPOLOGY.some(s => s.id === 'report')
  && INSPECTION_TOPOLOGY.some(s => s.id === 'setup'), '拓扑覆盖引擎全部 stage 值')
ok(INSPECTION_TOPOLOGY.every(s => typeof s.short === 'string' && s.short !== ''), '每段带短名')

// ---- isInspectionRow
ok(isInspectionRow({ kind: 'inspection' }) === true, 'kind 标记命中')
ok(isInspectionRow({ engine: 'inspection' }) === true, 'engine 标记命中')
ok(isInspectionRow({ kind: 'dev-lane' }) === false, '非巡检行不命中')
ok(isInspectionRow(null) === false && isInspectionRow('x') === false, '畸形输入不命中不抛')

// ---- findingsCountOf
ok(JSON.stringify(findingsCountOf({ findings: { high: 1, med: 2, low: 3, total: 6 } }))
  === JSON.stringify({ high: 1, med: 2, low: 3, total: 6 }), '计数正常读')
ok(JSON.stringify(findingsCountOf({})) === JSON.stringify({ high: 0, med: 0, low: 0, total: 0 }), '缺 findings 全 0')
ok(JSON.stringify(findingsCountOf({ findings: 'garbage' })) === JSON.stringify({ high: 0, med: 0, low: 0, total: 0 }), '畸形 findings 全 0')
ok(findingsCountOf({ findings: { high: 'x', med: NaN } }).high === 0, '非数值降 0 不抛')

// ---- inspectionStageShort（拓扑短名 + 未命中截断 + 畸形）
ok(inspectionStageShort('inspect') === '审查', '拓扑短名命中')
ok(inspectionStageShort('close') === '收口', 'close 短名')
ok(inspectionStageShort('mystery') === 'myst…', '未命中阶段截断')
ok(inspectionStageShort('') === '' && inspectionStageShort(null) === '' && inspectionStageShort(7) === '', '畸形→空串')

// ---- inspectionProgressOf（待签判定只读 stage_state/awaiting_gate，不读 human_gate）
const awaiting = inspectionProgressOf({
  stage: 'close', stage_state: 'awaiting-human', status: 'running',
  findings: { high: 1, med: 2, low: 0, total: 3 },
})
ok(awaiting && awaiting.state === 'awaiting-human' && awaiting.text.includes('等你签字')
  && awaiting.text.includes('高1/中2/低0'), '等你签字行文（含发现数）')
ok(inspectionProgressOf({ stage_state: 'running', awaiting_gate: true, findings: { total: 0 } })?.state
  === 'awaiting-human', 'awaiting_gate 推导等效（human_gate 缺键常态）')
const closed = inspectionProgressOf({ stage_state: 'done', status: 'closed', findings: { high: 0, med: 0, low: 1, total: 1 } })
ok(closed && closed.state === 'done' && closed.text.includes('已收口'), '闭合→done')
const blocked = inspectionProgressOf({ stage_state: 'blocked', blocked_reason: '声明决议失败', findings: {} })
ok(blocked && blocked.state === 'blocked' && blocked.text.includes('声明决议失败'), '受阻带原因')
const running = inspectionProgressOf({ stage: 'suite', stage_state: 'running', findings: { high: 0, med: 0, low: 0, total: 0 } })
ok(running && running.state === 'running' && running.text.includes('套件'), '运行中带阶段短名')
ok(inspectionProgressOf(null) === undefined && inspectionProgressOf('x') === undefined, '畸形行→undefined（行卡降级）')

// ---- inspectionSummaryOf（详情面形状：summary 字典优先，findings 清单重计兜底）
ok(JSON.stringify(inspectionSummaryOf({ summary: { high: 1, med: 2, low: 0 } }))
  === JSON.stringify({ high: 1, med: 2, low: 0, total: 3 }), 'summary 字典优先（total=和）')
ok(JSON.stringify(inspectionSummaryOf({
  summary: { high: 1, med: 2, low: 0, total: 9 },
})) === JSON.stringify({ high: 1, med: 2, low: 0, total: 9 }), 'summary 带 total 时用引擎真值')
ok(JSON.stringify(inspectionSummaryOf({
  findings: [{ severity: 'high' }, { severity: 'low' }, { severity: 'med' }, { severity: 'weird' }],
})) === JSON.stringify({ high: 1, med: 1, low: 1, total: 3 }), 'summary 缺失→清单按 severity 重计')
ok(JSON.stringify(inspectionSummaryOf({ summary: 'garbage', findings: 'garbage' }))
  === JSON.stringify({ high: 0, med: 0, low: 0, total: 0 }), '畸形→全 0 不抛')
ok(JSON.stringify(inspectionSummaryOf(null)) === JSON.stringify({ high: 0, med: 0, low: 0, total: 0 }), 'null 输入不抛')

// ---- inspectionTitleOf
ok(inspectionTitleOf({ title: '巡检 a · 期 b', id: 'x' }) === '巡检 a · 期 b', '标题优先')
ok(inspectionTitleOf({ id: 'inspection-x-20260915' }) === 'inspection-x-20260915', '标题缺失兜底 id（宁显编号不显空）')
ok(inspectionTitleOf({}) === '', '全空→空串不抛')

// ---- review 执行项1 UI 子用例：降级闭合行（引擎钉 status='running'）四态≠done，保持可见
ok(deriveTicketState('running', 'running') !== 'done', '降级闭合行（status=running，exec 断链旧行）不得被收口折叠吃掉')
// t260921-03 有意扩展：降级闭合行带 exec_status=COMPLETED（现引擎行形状）时终态
// 对账判 done——可见性承接方从「running 词面」改为「异常收口段不折叠」（引擎行带
// close_health=unreadable，board 拆桶承接），「已完成却显在跑」的谎言面随之消灭。
ok(deriveTicketState('running', 'running', 'COMPLETED') === 'done',
  '降级闭合行 exec=COMPLETED → done（终态对账优先于可见性词面；可见性由异常收口段承接）')
ok(deriveTicketState('closed', 'done') === 'done', '真闭合行仍是 done（收口折叠正常面）')
ok(deriveTicketState('running', 'awaiting-human') === 'waiting', '人门行=waiting（黄调行数据源）')

// ---- 通用性守卫：行卡组件不得内置巡检专属词（业务词表住 host 拓扑声明面）
const cardSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
ok(!cardSrc.includes('inspection') && !cardSrc.includes('inspection-close'),
  'ticket-row-card 零 inspection 专属词（行卡保持通用）')

console.log(`t260915-08-inspection-face: ${n} assertions passed`)
