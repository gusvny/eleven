// t260915-19 左栏收录巡检票 UT：host/inspection-face.ts 新增纯函数真值表 + 源级锚。
// 独立可执行（node ≥22 type-stripping，cwd=仓库根；exit 0 = 过）。
//
// KI 对齐（review gen2 落实项）：KI-018①（错误文案进横幅不进数据字段）、
// KI-008 + t260910-04 R3（失败保快照+原文透传，绝不吞成空列表）、
// KI-051（源级锚用 data-testid 语义锚；降级文案场景断「原文子串」不锚整句）、
// KI-055（bundle 锚归场景 S0，真机计算样式归场景 S1——本 UT 只锁源面）。
//
// review gen2 C1 口径：dev-lane 行自带 engine="template-as-code-v2"（非缺席）——
// data-engine 黄调作用域是「在场-异值」等值判定；本 UT 禁止断言「项目行无
// data-engine 属性」，只锁 `.wb-sb .wb-card[data-engine=inspection][data-state=waiting]`
// 等值选择器在源（场景再做真机对照行不黄的反断言）。
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  INSPECTION_TICKETS_URL, inspectionSidebarRows, inspectionSplitByProject,
  inspectionDegradedNote, isInspectionRow,
} from '../src/host/inspection-face.ts'

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

// ---- 端点串单源：与 node.ts 注册路径逐字一致（防两处字面量漂移）
ok(INSPECTION_TICKETS_URL === '/sandbar-workbench/api/wf/inspection/tickets', '端点串=注册路径')
const nodeTs = readFileSync(join(repo, 'server/plugins/workbench/node.ts'), 'utf8')
ok(nodeTs.includes(`path: '${INSPECTION_TICKETS_URL}'`)
  || nodeTs.includes(`path: "${INSPECTION_TICKETS_URL}"`), 'node.ts 注册同一端点串')

// ---- inspectionSidebarRows（防御过滤，保序）
const inspRow = (id, over = {}) => ({ id, kind: 'inspection', engine: 'inspection', ...over })
const rows = [
  inspRow('inspection-b-20260916', { project: 'sandbar' }),
  { id: 't-dev-lane', project: 'sandbar' }, // dev-lane 行（无巡检标记）须剔除
  inspRow('inspection-a-20260916', { project: '' }), // 老票（SA 空）
]
const filtered = inspectionSidebarRows(rows)
ok(filtered.length === 2 && filtered[0].id === 'inspection-b-20260916' && filtered[1].id === 'inspection-a-20260916',
  '非巡检行剔除且保序')
ok(JSON.stringify(inspectionSidebarRows(null)) === '[]'
  && JSON.stringify(inspectionSidebarRows(undefined)) === '[]'
  && JSON.stringify(inspectionSidebarRows({ tickets: [] })) === '[]'
  && JSON.stringify(inspectionSidebarRows('x')) === '[]', '非数组输入→空数组不抛')
ok(JSON.stringify(inspectionSidebarRows([null, 'x', 123, inspRow('k')])) === JSON.stringify([inspRow('k')]),
  '元素非对象剔除不抛')

// ---- inspectionSplitByProject（分拣：有身份进组，空/非串/不在册→unowned）
const reg = ['sandbar', 'dengzhufpv']
const split = inspectionSplitByProject(rows, reg)
ok(split.byProject.sandbar?.length === 1 && split.byProject.sandbar[0].id === 'inspection-b-20260916',
  '在册 key 归组')
ok(split.byProject.dengzhufpv === undefined, '无行项目不产空组键')
ok(split.unowned.length === 1 && split.unowned[0].id === 'inspection-a-20260916', '空 project（老票）→ unowned')
const split2 = inspectionSplitByProject([
  inspRow('i1', { project: 'quarantined-key' }), // 注册表隔离 key：不在 projects → 不进不存在的组
  inspRow('i2', { project: 123 }),               // 非串 project → unowned
  inspRow('i3'),                                  // 缺键 → unowned
  inspRow('i4', { project: 'sandbar' }),
], reg)
ok(split2.byProject.sandbar?.length === 1 && split2.byProject.sandbar[0].id === 'i4', '正常行归组不受畸形行影响')
ok(split2.unowned.map(r => r.id).join(',') === 'i1,i2,i3', '隔离 key/非串/缺键→unowned（不静默丢失）')
ok(JSON.stringify(inspectionSplitByProject(rows, null)) === JSON.stringify({ byProject: {}, unowned: filtered })
  && JSON.stringify(inspectionSplitByProject(rows, 'sandbar')) === JSON.stringify({ byProject: {}, unowned: filtered }),
  'registeredKeys 畸形按空集处理不抛')
ok(JSON.stringify(inspectionSplitByProject('x', reg)) === JSON.stringify({ byProject: {}, unowned: [] }),
  'rows 畸形→空分拣不抛')
const allOwned = inspectionSplitByProject([inspRow('i1', { project: 'sandbar' })], reg)
ok(allOwned.unowned.length === 0, '全归属→unowned 空（兜底组整组不渲染的判定源）')

// ---- inspectionDegradedNote（原文透传，不吞空列表）
const note = inspectionDegradedNote('ticket-list(inspection) 失败: 连接超时')
ok(note.includes('ticket-list(inspection) 失败: 连接超时'), '错误原文透传在文案')
ok(note.includes('显示上次快照'), '保快照语义显式（不静默）')
ok(note.includes('自动重试中'), '重试语义与中列词表同源')
ok(inspectionDegradedNote(123).includes('123')
  && inspectionDegradedNote({ code: 'ECONNREFUSED' }).includes('[object Object]')
  && inspectionDegradedNote(undefined).endsWith('：')
  && inspectionDegradedNote(null).endsWith('：')
  && inspectionDegradedNote('').endsWith('：'), '畸形 err 不抛；无原文不编造（尾巴可空，主体文案恒在）')

// ---- 源级锚（KI-051：语义锚；实现漂移在此点名）
const sbSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/sidebar.tsx'), 'utf8')
ok(sbSrc.includes('data-testid="sidebar-inspection-head"'), '兜底组头语义锚在源')
ok(sbSrc.includes('data-testid="sidebar-inspection-degraded"'), '降级横幅语义锚在源')
ok(sbSrc.includes('.wb-sb .wb-card[data-engine=inspection][data-state=waiting]'),
  '等你黄调=等值选择器作用域（review C1 口径：项目行 data-engine 在场-异值，非属性缺席）')
ok(sbSrc.includes('inspection_filter'), 'inspection_filter.degraded 左栏不带横幅的取舍声明在源（review gen0 意见②）')
ok(sbSrc.includes('驻留窗分工'), '巡检行不经 inSandbar 窗的两窗分工声明在源（review gen2 意见2）')
ok(sbSrc.includes('chat 项目 tag') && sbSrc.includes('不进 chat 项目 tag'), '巡检行不进 publishProjectEntry 的取舍声明在源')
ok(sbSrc.includes('INSPECTION_TICKETS_URL'), '端点串从单点 import（不写字面量）')
ok(!/const INSPECTION_TICKETS_URL\s*=/.test(sbSrc), '侧栏不再本地定义端点串')

const idxSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/index.tsx'), 'utf8')
ok(!/const INSPECTION_TICKETS_URL\s*=/.test(idxSrc), '中列不再本地定义端点串（迁移到单点）')
ok(idxSrc.includes('INSPECTION_TICKETS_URL'), '中列改走单点 import（URL 串仍在 bundle，08 S0 锚不丢）')

const cardSrc = readFileSync(join(repo, 'server/plugins/workbench/src/client/ticket-row-card.tsx'), 'utf8')
ok(/data-engine=\{t\.engine\}/.test(cardSrc), '行卡发射 data-engine（等值判定数据源）')
ok(cardSrc.includes('engine?: string'), 'CardTicket 类型面带 engine')

console.log(`PASS t260915-19-sidebar-inspection ok=${n}`)
