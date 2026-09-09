/**
 * smoke/evidence-lightbox.mjs — smoke for the screenshot-evidence lightbox (t260901-13).
 *
 * Run: node smoke/evidence-lightbox.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 *
 * Reuses loadClientBundle from ticket-switch.mjs (tests the real code through the built
 * artifact lib/client.cjs, not a copy). Failure-mode tradeoff list:
 *   1. Factory not exposing per the __ModuleLoader__.load contract -> explicit throw with a
 *      "run the tsdown build first" diagnosis — kept (depends on the build artifact; when
 *      missing the error must be readable).
 *   2. react / @deepseek-ai/* externalized -> a callable Proxy stub for require — kept
 *      (the premise "module top level only defines, never renders" holds for index.tsx;
 *      this smoke only takes pure exports, never renders components).
 *   3. globalThis.window cleared back to undefined after loading — kept (no pollution of
 *      later assertions).
 *   4. Entry asserts the key exports first, else FAIL + exit(1) — kept; the asserted
 *      objects are evidenceNav / evidenceImgSrc / evidenceLightboxKeys.
 *
 * Covers:
 *   A. evidenceNav pure function: normal next/prev/wrap; malformed input (empty list,
 *      out-of-range index, negative/non-integer/non-number delta) does not throw and lands
 *      on a safe index; out-of-range convergence when the list shrinks while open.
 *   B. evidenceImgSrc contract regression (relative endpoint, not data:).
 *   C. evidenceLightboxKeys key contract (Escape / ArrowLeft / ArrowRight).
 *   D. keydown binding/recovery is not covered by this smoke (the stub-driven component
 *      never renders) — pointed at by line number in the implementation walkthrough; no
 *      fake coverage is claimed here.
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

// dsh client module contract: window.__ModuleLoader__.load({id, factory}), factory(require) -> exports.
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
