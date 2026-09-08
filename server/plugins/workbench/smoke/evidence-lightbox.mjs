/**
 * smoke/evidence-lightbox.mjs —— t260901-13 截图证据看图灯箱冒烟。
 *
 * 直跑：node smoke/evidence-lightbox.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 *
 * 照搬 ticket-switch.mjs 的 loadClientBundle（经构建产物 lib/client.cjs 测真代码，
 * 不是复制品），故障模式取舍清单（create_plan gen1 过审口径）：
 *   ① factory 未按 __ModuleLoader__.load 契约暴露 → 显式 throw 带「先跑 tsdown
 *     构建」诊断 —— 带过来（依赖构建产物，缺失时必须可读报错）。
 *   ② react / @deepseek-ai/* 外部化 → 万能可调用 Proxy stub require —— 带过来
 *     （前提「模块顶层只定义不渲染」对 index.tsx 成立；本 smoke 只取纯导出，
 *     不 render 组件）。
 *   ③ globalThis.window 装载后清回 undefined —— 带过来（不污染后续断言）。
 *   ④ 入口先断言关键导出，否则 FAIL + exit(1) —— 带过来，断言对象
 *     evidenceNav / evidenceImgSrc / evidenceLightboxKeys。
 *
 * 覆盖（create_plan gen1 验收口径）：
 *   A. evidenceNav 纯函数：正常前进/后退/循环；畸形输入（空列表、越界下标、
 *      负数/非整数/非数字 delta）不抛且落安全下标；open 期间列表变短的越界收敛。
 *   B. evidenceImgSrc 契约回归（相对端点、非 data:）。
 *   C. evidenceLightboxKeys 键位契约（Escape / ArrowLeft / ArrowRight）。
 *   D. keydown 绑定/回收不在本 smoke 覆盖内（桩驱动组件永不 render）——
 *      由实现段代码走查指认行号（方案 gen1 R2 定案），此处不造假覆盖。
 */

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

// dsh 客户端模块契约：window.__ModuleLoader__.load({id, factory})，factory(require) → exports。
function makeStubRequire() {
  const stub = new Proxy(function () {}, {
    get: (_t, p) => (p === Symbol.toPrimitive ? () => '' : stub),
    apply: () => stub,
    construct: () => stub,
  })
  return () => stub
}
function loadClientBundle() {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'lib', 'client.cjs'))
  let factory = null
  globalThis.window = { __ModuleLoader__: { load: (m) => { factory = m.factory } } }
  new Function(src)()
  globalThis.window = undefined
  if (typeof factory !== 'function') throw new Error('lib/client.cjs 未按 __ModuleLoader__.load 契约暴露 factory（先跑 tsdown 构建）')
  return factory(makeStubRequire())
}
const client = loadClientBundle()
const { evidenceNav, evidenceImgSrc, evidenceLightboxKeys } = client
if (typeof evidenceNav !== 'function' || typeof evidenceImgSrc !== 'function' || evidenceLightboxKeys === undefined) {
  console.error('  FAIL 构建产物未导出 evidenceNav / evidenceImgSrc / evidenceLightboxKeys（检查 index.tsx 导出与 tsdown 构建）')
  process.exit(1)
}

section('A evidenceNav：正常前进/后退/循环')
{
  const files = ['a.png', 'b.png', 'c.png']
  ok(evidenceNav(files, 0, 1) === 1, '0 前进 → 1')
  ok(evidenceNav(files, 2, 1) === 0, '末张前进 → 回首张（循环）')
  ok(evidenceNav(files, 0, -1) === 2, '首张后退 → 到末张（循环）')
  ok(evidenceNav(files, 1, -1) === 0, '1 后退 → 0')
  ok(evidenceNav(files, 1, 0) === 1, 'delta 0 → 原地')
  ok(evidenceNav(files, 1, 4) === 2, 'delta 超一圈（1+4 → 5 mod 3 = 2）')
  ok(evidenceNav(files, 1, -4) === 0, '负 delta 超一圈（1-4 → -3 mod 3 = 0）')
}

section('A2 evidenceNav：畸形输入不抛、兜底安全下标')
{
  ok(evidenceNav([], 0, 1) === 0, '空列表 → 0 不抛')
  ok(evidenceNav(['a.png'], 5, 1) === 0, '越界下标收敛到 0')
  ok(evidenceNav(['a.png'], -1, 1) === 0, '负下标收敛到 0')
  ok(evidenceNav(['a.png', 'b.png'], 1.5, 1) === 1, '非整数下标先兜底 0 再前进 → 1（安全下标）')
  ok(evidenceNav(['a.png', 'b.png'], 0, 1.5) === 0, '非整数 delta 视为 0')
  ok(evidenceNav(['a.png', 'b.png'], 0, NaN) === 0, 'NaN delta 视为 0 不抛')
  ok(evidenceNav(['a.png', 'b.png'], 0, undefined) === 0, 'undefined delta 视为 0 不抛')
  ok(evidenceNav(['a.png', 'b.png'], 1, 1) === 0, '列表变短后越界：open=1、n=2，正常循环 1+1=0')
  ok(evidenceNav(['a.png'], 1, 1) === 0, '列表缩到 1 张：越界下标兜底 0（open 期间重拉变短的收敛）')
}

section('B evidenceImgSrc 契约回归')
{
  ok(evidenceImgSrc('t1', 'a.png') === '/sandbar-workbench/api/wf/tickets/t1/evidence/a.png', '相对路径端点契约')
  ok(!evidenceImgSrc('t1', 'a.png').startsWith('data:'), '不走 data: 内联（防穿收口 host）')
}

section('C evidenceLightboxKeys 键位契约')
{
  ok(evidenceLightboxKeys.close === 'Escape', 'close = Escape')
  ok(evidenceLightboxKeys.prev === 'ArrowLeft', 'prev = ArrowLeft')
  ok(evidenceLightboxKeys.next === 'ArrowRight', 'next = ArrowRight')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
