// tests/t260916-05-inspection-topology-lock.mjs —— 巡检短名映射 ↔ 引擎阶段声明 同步锁。
//
// 背景（t260916-05 方案 §3，review gen1 认可的「保留+同步锁」收敛形态）：
//   - 段词表编码真源=引擎 inspection_flow.py `InspectionPeriodicWorkflow.STAGES`
//     （机器可读阶段声明）；展示面拓扑=引擎 template_topology 导出（快照 topology
//     键 → 泳道图通用渲染器）。
//   - workbench 侧 INSPECTION_TOPOLOGY（host/inspection-face.ts）收窄为「短名排版
//     映射」宿主职责——它与引擎 STAGES 的一致性由本锁源级锚钉死：
//     「STAGES 改了（增段/删段/改名/换序）不改本表，此处必红」。
//
// 锁的实现（源级锚，非编译产物）：
//   - 读引擎 inspection_flow.py 源码，**只在 InspectionPeriodicWorkflow 类块内**截取
//     STAGES 声明（review 意见 1 同款作用域纪律：同文件还有 watcher 类，不限定类块
//     会把 poll/trigger 混入），解析 InspectionStage(id=…, name=…) 声明序。
//   - 变异自证腿：锁体=纯函数，喂变异副本（改名/插段/换序）必出问题清单——证明锁
//     有牙齿，不靠真改文件。
//
// 仓库根解析（KI-075 族卫生，review 意见 2）：爬根找 CLAUDE.md（t260915-08 同款
// helper），禁宿主绝对路径、禁裸信 process.cwd()。
// 直跑：node server/plugins/workbench/tests/t260916-05-inspection-topology-lock.mjs
// （cwd=仓库根由 run_tests.mjs 保证；独立直跑也过——爬根自锚）。
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { INSPECTION_TOPOLOGY } from '../src/host/inspection-face.ts'

const repo = (() => {
  let d = dirname(fileURLToPath(import.meta.url))
  for (let i = 0; i < 6; i++) {
    try { readFileSync(join(d, 'CLAUDE.md')); return d } catch { d = join(d, '..') }
  }
  throw new Error('找不到仓库根（爬根 6 层无 CLAUDE.md）')
})()

let n = 0
function ok(cond, msg) {
  n++
  if (!cond) { console.error(`FAIL ${msg}`); process.exit(1) }
}

// ---- 引擎 STAGES 源级提取（类块作用域 + STAGES 元组边界） ----

function workflowClassBlock(src) {
  const starts = [...src.matchAll(/^class \w+/gm)].map(m => m.index)
  const start = src.search(/^class InspectionPeriodicWorkflow\b/m)
  if (start < 0) throw new Error('引擎源码缺 InspectionPeriodicWorkflow 类定义')
  const later = starts.filter(i => i > start)
  return src.slice(start, later.length > 0 ? later[0] : src.length)
}

function parseEngineStages(src) {
  const block = workflowClassBlock(src)
  const tupleStart = block.indexOf('STAGES = (')
  if (tupleStart < 0) throw new Error('类块内找不到 STAGES 声明（声明被移出类块？）')
  // 元组边界：到首个「行首 4 空格 + )」的闭括号（声明条目全部 ≥4 空格缩进）
  const rest = block.slice(tupleStart)
  const close = rest.search(/^    \)/m)
  if (close < 0) throw new Error('STAGES 元组闭括号解析失败')
  const body = rest.slice(0, close)
  const stages = [...body.matchAll(/InspectionStage\(\s*id="([a-z_]+)"\s*,\s*name="([^"]+)"/g)]
  if (stages.length === 0) throw new Error('STAGES 声明解析出零条目（改了声明样式？同步改本锁）')
  return stages.map(m => ({ id: m[1], name: m[2] }))
}

// ---- 锁体（纯函数，变异腿的载体） ----

export function lockStagesToTopology(engineStages, hostTopology) {
  const problems = []
  if (engineStages.length !== hostTopology.length) {
    problems.push(`段数漂移：引擎 ${engineStages.length} 段 vs 宿主 ${hostTopology.length} 段`)
  }
  const hostIds = hostTopology.map(s => s.id)
  for (let i = 0; i < Math.min(engineStages.length, hostTopology.length); i++) {
    const e = engineStages[i]
    const h = hostTopology[i]
    if (e.id !== h.id) problems.push(`第 ${i + 1} 段 id 漂移：引擎 ${e.id} vs 宿主 ${h.id}`)
    if (e.name !== h.name) problems.push(`段 ${h.id} name 漂移：引擎 ${e.name} vs 宿主 ${h.name}`)
  }
  for (const id of engineStages.map(s => s.id)) {
    if (!hostIds.includes(id)) problems.push(`引擎段 ${id} 在宿主短名表缺席`)
  }
  for (const h of hostTopology) {
    if (!engineStages.some(e => e.id === h.id)) problems.push(`宿主段 ${h.id} 引擎已删（幽灵段）`)
  }
  return problems
}

// ---- 主锁：引擎 STAGES（源级） ↔ INSPECTION_TOPOLOGY（宿主常量） ----

const src = readFileSync(join(repo, 'server', 'engine', 'inspection_flow.py'), 'utf-8')
const engineStages = parseEngineStages(src)

ok(engineStages.length === 5 && engineStages[0].id === 'setup' && engineStages[4].id === 'close',
  '引擎声明形状自检（5 段、setup 起 close 收）')
ok(INSPECTION_TOPOLOGY.every(s => typeof s.short === 'string' && s.short !== ''),
  '宿主每段带非空短名（排版职责在位）')
{
  const problems = lockStagesToTopology(engineStages, INSPECTION_TOPOLOGY)
  ok(problems.length === 0,
    `真实对零漂移（误报即锁坏）${problems.length ? '：' + problems.join('；') : ''}`)
}

// ---- 变异自证腿：改声明不改宿主表 → 锁必红 ----

{
  const renamed = engineStages.map(s => (s.id === 'inspect' ? { ...s, name: '改过的审查' } : s))
  ok(lockStagesToTopology(renamed, INSPECTION_TOPOLOGY).length > 0, '变异：改引擎 name → 红')
  const inserted = [...engineStages.slice(0, 1),
    { id: 'ghost', name: '幽灵段' }, ...engineStages.slice(1)]
  ok(lockStagesToTopology(inserted, INSPECTION_TOPOLOGY).length > 0, '变异：引擎插段 → 红')
  const swapped = [engineStages[1], ...engineStages.slice(0, 1), ...engineStages.slice(2)]
  ok(lockStagesToTopology(swapped, INSPECTION_TOPOLOGY).length > 0, '变异：换序 → 红')
  const dropped = engineStages.filter(s => s.id !== 'suite')
  ok(lockStagesToTopology(dropped, INSPECTION_TOPOLOGY).length > 0, '变异：引擎删段 → 红')
}

console.log(`ok ${n} 项断言（t260916-05 同步锁：引擎 STAGES ↔ 宿主短名表，含变异自证）`)
