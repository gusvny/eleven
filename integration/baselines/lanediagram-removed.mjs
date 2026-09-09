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
 * rebuilds the lib artifacts — skip the build and the injected bundle is
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
