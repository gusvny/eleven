/**
 * t01-fixture-pack —— t260901-24「capture-lane 状态注入」fixture 包语义基线。
 *
 * 直跑：node integration/t260901-24/t01-fixture-pack.mjs（cwd=泳道根，零依赖）。
 *
 * 黑盒视角（用户可感知行为）：ui_evidence 要拍到「改动面实拍级」，前提是随包
 * fixture 数据本身能驱动目标界面。本测试不碰浏览器，只验两件事：
 *   1) 随包 fixture 文件齐、带 _fixture 标记、两票状态形状正确；
 *   2) 交叉验证：把 T-FIX-B/T-FIX-A 的 detail 喂给工单台真推导函数
 *      deriveStageStates（workbench src/client 纯 ts，node 直 import），
 *      必须推出「双 ▶ 并行步」与「✋ 待审批」——这是「实拍能到达目标界面」
 *      的数据侧充分条件。
 *
 * 覆盖故障面：边界（缺文件/缺标记）、异常输入（形状错/并行步计数不足）。
 * 安全红线：纯本地读，不碰 3099/Temporal/网络。
 */

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const FIXTURES = join(REPO, 'server', 'dsh', 'ui-check', 'fixtures')
const CLIENT_SRC = join(REPO, 'server', 'dsh', 'workbench', 'src', 'client')

let passed = 0, failed = 0
const failures = []
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; failures.push(label); console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** 宽容包装差异：票数组可能在顶层或 .tickets 下（严格形状由 loadFixtures 守）。 */
function pickTickets(json) {
  if (Array.isArray(json)) return json
  if (Array.isArray(json?.tickets)) return json.tickets
  return null
}
/** 在对象里深找第一个数组值的键（workflows 模板链 order 用）。 */
function deepArray(obj, key) {
  if (!obj || typeof obj !== 'object') return null
  if (Array.isArray(obj[key])) return obj[key]
  for (const v of Object.values(obj)) {
    const r = deepArray(v, key)
    if (r) return r
  }
  return null
}

section('随包 fixture 目录存在且文件齐')
if (!existsSync(FIXTURES)) {
  console.log('  FAIL server/dsh/ui-check/fixtures 不存在（t260901-24 implement 段应落地该目录）')
  console.log(`\nSUMMARY pass=0 fail=1 env_fail=0 na=0`)
  process.exit(1)
}
const files = readdirSync(FIXTURES).filter((f) => f.endsWith('.json'))
const want = ['tickets-list.json', 'ticket-show-T-FIX-A.json', 'ticket-show-T-FIX-B.json',
  'workflows.json', 'ticket-diff-T-FIX-A.json']
for (const w of want) ok(files.includes(w), `fixture 文件在位：${w}`)

section('全部 fixture 自证 _fixture 标记（非真数据）')
for (const f of files) {
  let json = null
  try { json = JSON.parse(readFileSync(join(FIXTURES, f), 'utf8')) } catch { /* 下一条断言报 */ }
  ok(json !== null, `${f} 可 JSON 解析`)
  ok(json?._fixture === true, `${f} 带 _fixture:true`)
}

section('票清单：两票状态形状（驱动审批弹层与并行泳道的数据前提）')
const list = pickTickets(safeRead(join(FIXTURES, 'tickets-list.json')))
ok(Array.isArray(list) && list.length >= 2, 'tickets-list 至少 2 张票')
const a = (list || []).find((t) => t?.id === 'T-FIX-A')
const b = (list || []).find((t) => t?.id === 'T-FIX-B')
ok(!!a, 'T-FIX-A（awaiting-human 票）在清单')
ok(!!b, 'T-FIX-B（running 票）在清单')
ok(a?.stage_state === 'awaiting-human', 'T-FIX-A stage_state=awaiting-human（审批台前提）')
ok(a?.worktree != null && a.worktree !== '', 'T-FIX-A worktree 非空（详情页不因空 worktree 降级）')
ok(b?.stage_state === 'running', 'T-FIX-B stage_state=running')

section('T-FIX-A detail：timeline 最新条目 awaiting-human（✋ 态驱动）')
const detA = safeRead(join(FIXTURES, 'ticket-show-T-FIX-A.json'))
const tlA = detA?.timeline
ok(Array.isArray(tlA) && tlA.length > 0, 'T-FIX-A timeline 非空')
const lastA = Array.isArray(tlA) ? tlA[tlA.length - 1] : null
ok(lastA?.state === 'awaiting-human', 'T-FIX-A timeline 最新条目 state=awaiting-human')
ok(detA?.id === 'T-FIX-A', 'T-FIX-A detail.id 一致')

section('T-FIX-B detail：implement ∥ design_integration_tests 双 running（并行态驱动）')
const detB = safeRead(join(FIXTURES, 'ticket-show-T-FIX-B.json'))
const tlB = Array.isArray(detB?.timeline) ? detB.timeline : []
const runningStages = new Set(tlB.filter((t) => t?.state === 'running').map((t) => t.stage))
ok(runningStages.has('implement') && runningStages.has('design_integration_tests'),
  'T-FIX-B timeline 含 implement 与 design_integration_tests 双 running')
// attempts 语义（lane-states 规则 4）：results 有记录则该步 attempts ≥ 1——
// 双并行步必须无 results 记录，否则 runningCount>attempts 不成立、推不出活跃步。
const attemptsGt0 = ['implement', 'design_integration_tests']
  .filter((s) => detB?.results?.[s] != null || (detB?.checks?.[s] || []).length > 0)
ok(attemptsGt0.length === 0,
  `双并行步不得已有 results/checks 记录（attempts 须为 0；发现：${attemptsGt0.join(',') || '无'}）`)

section('交叉验证：fixture detail 喂真推导函数 → 双 ▶ / ✋')
const derive = await resolveDerive()
if (!derive) {
  ok(false, 'src/client/ 下找不到可 import 的 deriveStageStates 纯 ts 模块')
} else {
  const order = deepArray(safeRead(join(FIXTURES, 'workflows.json')), 'order')
  ok(Array.isArray(order) && order.length > 0, 'workflows.json 含模板步序 order')
  if (Array.isArray(order)) {
    const outB = norm(derive(detB, order))
    ok(outB.implement === 'running' && outB.design_integration_tests === 'running',
      `T-FIX-B 推导出双 ▶ 并行步（实际 implement=${outB.implement}，dit=${outB.design_integration_tests}）`)
    const outA = norm(derive(detA, order))
    const stageA = lastA?.stage
    ok(stageA && outA[stageA] === 'awaiting-human',
      `T-FIX-A 推导出 ✋（stage=${stageA}，实际=${stageA ? outA[stageA] : '（缺）'}）`)
  }
}

function safeRead(p) {
  try { return JSON.parse(readFileSync(p, 'utf8')) } catch { return null }
}
function norm(out) {
  if (out && typeof out === 'object' && out.states) return out.states
  return out || {}
}
async function resolveDerive() {
  for (const f of readdirSync(CLIENT_SRC).filter((x) => x.endsWith('.ts') && !x.endsWith('.d.ts'))) {
    try {
      const mod = await import(pathToFileURL(join(CLIENT_SRC, f)).href + '?t=' + Date.now())
      if (typeof mod.deriveStageStates === 'function') return mod.deriveStageStates
    } catch { /* 平台依赖文件跳过 */ }
  }
  return null
}

console.log(`\nSUMMARY pass=${passed} fail=${failed} env_fail=0 na=0`)
if (failed > 0) { console.log('FAILURES:\n  - ' + failures.join('\n  - ')); process.exit(1) }
