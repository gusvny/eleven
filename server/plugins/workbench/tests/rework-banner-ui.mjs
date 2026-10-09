/**
 * 基线：rework 横幅的 UI 消费契约（票 t260901-04）。
 *
 * 意图：
 *   票 t260901-04 的修复让引擎为机器打回发 state='rework' 的 timeline 记录；
 *   工单台横幅（D2Reworks）负责把它变成用户可见的「我的票为什么被打回」。
 *   本基线锁定两侧之间的契约，让修复不能静默地从界面上消失：
 *     - 横幅过滤条件确实是 `t.state === 'rework'`，三个在发的 bundle 全查
 *       （src + lib/client.js + lib/client.cjs）——防经典事故「src 改了但
 *       bundle 没重建，用户照样什么都看不见」；
 *     - 引擎写的记录形状（{at, stage, state, reason}）与横幅渲染的字段
 *       （t.at / t.stage / t.reason）对齐——不缺键；
 *     - 健壮性：timeline 缺失、reason 为空、未知 stage id 都不得弄坏渲染。
 *   只测纯 node 半——无 server、无 Temporal，随处可跑（包括引擎机械
 *   integration 步内）。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client', 'index.tsx')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')
const DEV_LANE = join(REPO, 'server', 'engine', 'dev_lane.py')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const src = readFileSync(SRC, 'utf8')
const libJs = readFileSync(LIB_JS, 'utf8')
const libCjs = readFileSync(LIB_CJS, 'utf8')
const lane = readFileSync(DEV_LANE, 'utf8')

/* ---- 1. 三件套过滤口径一致：src 与两个编译产物都吃 state==='rework' ---- */
section('banner filter present in all three shipped bundles')
const FILTER_RE = /t\.state\s*===\s*['"]rework['"]/
ok(FILTER_RE.test(src), 'src/client/index.tsx 含 t.state===\'rework\' 过滤')
ok(FILTER_RE.test(libJs), 'lib/client.js 含同款过滤（编译产物未回退）')
ok(FILTER_RE.test(libCjs), 'lib/client.cjs 含同款过滤（编译产物未回退）')

/* ---- 2. 提取 src 真过滤式执行：自动打回记录必被横幅看见 ---- */
section('engine record shape -> banner visibility (real filter exec)')
const m = /\(\s*detail\.timeline\s*\?\?\s*\[\]\s*\)\.filter\(\s*((?:\(\s*)?t\s*=>\s*t\.state\s*===\s*'rework'\s*\)?)\s*\)/.exec(src)
ok(m !== null, 'D2Reworks 的 (detail.timeline ?? []).filter(...) 表达式可整体抽出')
let filterFn = null
if (m) {
  try { filterFn = eval(`(${m[1]})`) } catch { filterFn = null }
  ok(typeof filterFn === 'function', '抽出的过滤箭头函数可 eval 执行（真代码，非复刻）')
}
// fixture：_mark 真实产出的记录形状（at/stage/state/reason 四键）
const autoRecord = { at: '2026-09-01T10:06:54', stage: 'implement', state: 'rework', reason: '验收走查打回（第 2 轮）（workflow）' }
const mixedTimeline = [
  { at: '2026-09-01T09:00:00', stage: 'create_plan', state: 'running', reason: 'Entered step (attempt 1)' },
  autoRecord,
  { at: '2026-09-01T10:07:00', stage: 'implement', state: 'running', reason: 'Entered step (attempt 2)' },
]
if (filterFn) {
  ok(filterFn.length === 1, '过滤函数单参数（t）')
  ok(filterFn(autoRecord) === true, '自动打回记录（state=rework）被过滤保留 → 横幅可见')
  const kept = mixedTimeline.filter(filterFn)
  ok(kept.length === 1 && kept[0] === autoRecord, '混合时间线只保留 rework 记录（其它 state 不进横幅）')
  const withBlocked = [...mixedTimeline, { at: '2026-09-01T10:08:00', stage: 'merge_check', state: 'blocked', reason: '检查红' }]
  ok(withBlocked.filter(filterFn).length === 1, 'blocked 记录不进横幅（卡单≠打回，用户视角区分）')
  ok([].filter(filterFn).length === 0, '空时间线 → 0 条（横幅隐藏，不崩）')
}

/* ---- 3. 跨层字段契约：workflow 写的键 ↔ UI 读的键 一一对齐 ---- */
section('record keys vs rendered fields')
const dm = /function D2Reworks\([\s\S]*?\n\}/.exec(src)
ok(dm !== null, 'D2Reworks 组件体可抽出')
const body = dm ? dm[0] : ''
ok(/\bt\.at\b/.test(body), '组件渲染 t.at（时间列）')
ok(/\bt\.stage\b/.test(body), '组件渲染 t.stage（打回到哪步）')
ok(/\bt\.reason\b/.test(body), '组件渲染 t.reason（打回原因）')
ok(/\{"at":\s*self\._now_iso\(\),\s*"stage":\s*step,\s*"state":\s*state,\s*"reason":\s*reason\}/.test(lane),
  'engine _mark 记录恰为 {at, stage, state, reason} 四键——与渲染字段完全对齐，不多缺')

/* ---- 4. 健壮性：空 reason / 未知步 id / 缺 timeline 不回退 ---- */
section('rendering robustness')
ok(/\{\s*t\.reason\s*\?/.test(body), '空 reason 有三元守卫（不渲染 undefined/null）')
ok(/wf\?\.stages\.find\(\s*\(?s\)?\s*=>/.test(body) && /\?\.name\s*\?\?\s*id/.test(body),
  '未知 stage id 回显原 id（wf 缺失/步不在模版也不崩）')
ok(/detail\.timeline\s*\?\?\s*\[\]/.test(body), 'timeline 缺失时按空数组处理（?? [] 不回退）')
ok(/reworks\.length === 0\s*\)\s*return null/.test(body), '无 rework 记录时横幅整体不渲染')

console.log(`\nSUMMARY pass=${pass} skip=0 fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
