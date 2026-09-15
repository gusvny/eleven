/**
 * lanediagram-removed — the t260901-05 "delete the dead LaneDiagram code"
 * assertions (resource reclamation).
 *
 * Run directly: node integration/baselines/lanediagram-removed.mjs (cwd =
 * lane root, zero dependencies).
 *
 * Background (review_plan round 1, P2): LaneDiagram (index.tsx) has zero
 * callers across src; the detail page really renders D2Stepper/d2StatusLine.
 * This ticket also deletes the component and its .wb-lane* dedicated CSS and
 * rebuilds the lib artifacts — omit the build and the injected bundle is
 * still the old one carrying the dead code.
 *
 * Coverage:
 *   1. src/client/ has no LaneDiagram definition and no leftover .wb-lane
 *      references;
 *   2. lib/client.js and lib/client.cjs were rebuilt (no LaneDiagram /
 *      wb-lane-step strings);
 *   3. the actually-rendered components survive (guarding against
 *      over-deletion): D2Stepper/d2StatusLine/deriveStageStates consumers are
 *      in place.
 * Safety line: reads local files only.
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
    // t260915-05 仲裁收紧：/wb-lane/ 会误伤新真泳道图的合法前缀 wb-lanemap（子串
    // 撞车）——本守卫的意图是「t260901-05 删掉的死组件 CSS 家族（wb-lane-step 等）
    // 不复活」，带尾连字符才锚得住那个家族；wb-lanemap / wb-lm-* 是拓扑渲染器新家族。
    if (/wb-lane-/.test(t)) { laneRefs++; console.log(`    残留 wb-lane-* @ ${f}`) }
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

// t260915-05 加宽段（仲裁段被拒的基线增强转 implement 落，受保护路径授权在案：
// scope=integration/baselines/lanediagram-removed.mjs）——只加不削，上方 10 条
// 原有断言逐字保留。意图：真泳道图家族（wb-lanemap/wb-lm-*）是「删除死组件」
// 守卫的新邻居，把「新家族真在 src+lib 双产物、守卫仍咬旧家族」也钉进本基线，
// 防两向漂移（新家族被误删 / 守卫被放松到不再咬 wb-lane-step 家族）。
section('新 lane-map 家族在场（t260915-05 加宽；src 与 lib 双产物）')
{
  const laneMapSrc = join(CLIENT_SRC, 'lane-map.tsx')
  const laneMapModelSrc = join(CLIENT_SRC, 'lane-map-model.ts')
  ok(existsSync(laneMapSrc) && existsSync(laneMapModelSrc),
    'src/client 新家族模块在盘（lane-map.tsx + lane-map-model.ts）')
  const srcMap = existsSync(laneMapSrc) ? readFileSync(laneMapSrc, 'utf8') : ''
  const srcModel = existsSync(laneMapModelSrc) ? readFileSync(laneMapModelSrc, 'utf8') : ''
  ok(/wb-lm-parallel/.test(srcMap) && /wb-lm-round/.test(srcMap) && /wb-lm-node/.test(srcMap),
    'src 泳道图组件带 wb-lm-* 家族（并行框/轮次格/节点）')
  ok(/wb-ck-row/.test(srcMap) || /wb-ck-row/.test(srcModel), 'src 检查明细区 wb-ck-* 家族在案')
  ok(/buildLaneMap/.test(srcModel) && /parseTopology/.test(srcModel),
    'src 纯模型导出 buildLaneMap/parseTopology 在案')
  const idx = readFileSync(join(CLIENT_SRC, 'index.tsx'), 'utf8')
  ok(/wb-lanemap/.test(idx) && /LaneMap/.test(idx) && /ChecksDetail/.test(idx),
    'index.tsx 接线新家族（wb-lanemap CSS/LaneMap/ChecksDetail 消费）')
  for (const [label, p] of [['lib/client.js', LIB_JS], ['lib/client.cjs', LIB_CJS]]) {
    if (!existsSync(p)) continue // 产物缺失已由上方原断言报 FAIL，不重复计
    const t = readFileSync(p, 'utf8')
    ok(/wb-lanemap/.test(t) && /wb-lm-node/.test(t), `${label} 新家族已入 bundle（wb-lanemap/wb-lm-node）`)
  }
}

section('守卫仍咬旧家族（加宽不放松）')
{
  // 守卫正则自检：收紧后的 /wb-lane-/（带尾连字符）必须仍咬住旧死组件家族
  // （wb-lane-step 形态），且不误咬新真泳道图家族（wb-lanemap/wb-lm-*）——
  // 「旧家族仍被咬」=守卫语义未因加宽而松弛的机械证明。
  const guard = /wb-lane-/
  ok(guard.test('wb-lane-step') && guard.test('wb-lane-wrap'),
    '守卫仍咬旧家族（wb-lane-step/wb-lane-wrap 命中）')
  ok(!guard.test('wb-lanemap') && !guard.test('wb-lm-node'),
    '守卫不误咬新家族（wb-lanemap/wb-lm-* 放行）')
}

console.log(`\n${passed} passed, ${failed} failed, env_fail=${envFailed}, na=${naCount}`)
console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=${naCount}`)
const allNa = naCount > 0 && passed + failed + envFailed === 0
process.exit(failed > 0 || allNa ? 1 : envFailed > 0 ? 2 : 0)
