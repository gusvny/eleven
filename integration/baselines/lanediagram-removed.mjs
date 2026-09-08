/**
 * lanediagram-removed —— t260901-05「删死代码 LaneDiagram」断言（资源回收面）。
 *
 * 直跑：node integration/baselines/lanediagram-removed.mjs（cwd=泳道根，零依赖）。
 *
 * 背景（review_plan 第 1 轮 P2）：LaneDiagram（index.tsx）全 src 零调用，详情页实际
 * 渲染 D2Stepper/d2StatusLine。本票顺手删除组件及其 .wb-lane* 专属 CSS，并重建
 * lib 产物——若 build 漏跑，线上注入的仍是含死代码的旧 bundle。
 *
 * 覆盖：
 *   1. src/client/ 无 LaneDiagram 定义、无 .wb-lane 残留引用；
 *   2. lib/client.js 与 lib/client.cjs 已重建（无 LaneDiagram/wb-lane-step 字符串）；
 *   3. 实际渲染组件仍在（防误删过头）：D2Stepper/d2StatusLine/deriveStageStates 消费在案。
 * 安全红线：纯本地读文件。
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const CLIENT_SRC = join(REPO, 'server', 'plugins', 'workbench', 'src', 'client')
const LIB_JS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.js')
const LIB_CJS = join(REPO, 'server', 'plugins', 'workbench', 'lib', 'client.cjs')

let passed = 0, failed = 0, envFailed = 0, naCount = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

section('src/client/ 死代码清除')
{
  let laneRefs = 0, lanediagram = 0, files = 0
  for (const f of readdirSync(CLIENT_SRC)) {
    if (!/\.tsx?$/.test(f)) continue
    files++
    const t = readFileSync(join(CLIENT_SRC, f), 'utf8')
    if (/LaneDiagram/.test(t)) { lanediagram++; console.log(`    残留 LaneDiagram @ ${f}`) }
    if (/wb-lane/.test(t)) { laneRefs++; console.log(`    残留 wb-lane @ ${f}`) }
  }
  ok(files > 0, `扫描 ${files} 个源文件`)
  ok(lanediagram === 0, '无 LaneDiagram 残留')
  ok(laneRefs === 0, '无 .wb-lane* CSS/类名残留')
}

section('lib 产物已随 build 重建')
{
  for (const [label, p] of [['lib/client.js', LIB_JS], ['lib/client.cjs', LIB_CJS]]) {
    if (!existsSync(p)) { failed++; console.log(`  FAIL ${label} 不存在（build 产物缺失）`); continue }
    const t = readFileSync(p, 'utf8')
    ok(!/LaneDiagram/.test(t), `${label} 无 LaneDiagram（已重建）`)
    ok(!/wb-lane-step/.test(t), `${label} 无 wb-lane-step（CSS 已清）`)
  }
}

section('实际渲染路径未被误删')
{
  const idx = readFileSync(join(CLIENT_SRC, 'index.tsx'), 'utf8')
  ok(/D2Stepper/.test(idx), 'D2Stepper 在案')
  ok(/d2StatusLine/.test(idx), 'd2StatusLine 在案')
  ok(/deriveStageStates/.test(idx), 'index.tsx 消费 deriveStageStates')
}

console.log(`\n${passed} passed, ${failed} failed, env_fail=${envFailed}, na=${naCount}`)
console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=${naCount}`)
const allNa = naCount > 0 && passed + failed + envFailed === 0
process.exit(failed > 0 || allNa ? 1 : envFailed > 0 ? 2 : 0)
