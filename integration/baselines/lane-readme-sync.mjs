/**
 * lane-readme-sync —— t260901-05「workflows README 同步」断言。
 *
 * 直跑：node integration/baselines/lane-readme-sync.mjs（cwd=泳道根，零依赖）。
 *
 * 覆盖（用户可感知：工单台文档与真实机制脱节）：
 *   1. dev-lane 步链段写全新链（并行分叉/汇合/ui_evidence/机械测试/仲裁/验收走查），
 *      顺序 implement→design_integration_tests→ui_evidence→run_integration_tests；
 *   2. 已退役的 integration_review 打回循环从步链段与执行主体段消失；
 *   3. 执行主体 parts 段含 design_integration_tests。
 * 安全红线：纯本地读文件。
 */

import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const README = join(REPO, 'server', 'workflows', 'README.md')

let passed = 0, failed = 0, envFailed = 0, naCount = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const text = readFileSync(README, 'utf8')

/** 抽取「- **dev-lane ...」到下一个「- **<其它模版」之间的段。 */
function bulletSection(startRe) {
  const m = text.match(startRe)
  if (!m) return null
  const rest = text.slice(m.index)
  const tail = rest.slice(1).search(/\n- \*\*/g)
  return tail < 0 ? rest : rest.slice(0, tail + 1)
}

section('dev-lane 步链段（§4 索引）')
{
  const sec = bulletSection(/- \*\*dev-lane 步链\*\*/)
  ok(sec !== null, '步链段存在')
  if (sec) {
    for (const kw of ['design_integration_tests', 'ui_evidence', 'run_integration_tests',
      'arbitrate', 'acceptance_walkthrough', '∥'])
      ok(sec.includes(kw), `步链段含「${kw}」`)
    ok(!sec.includes('integration_review'), '步链段无退役 integration_review')
    const iImpl = sec.indexOf('implement')
    const iDesign = sec.indexOf('design_integration_tests')
    const iUi = sec.indexOf('ui_evidence')
    const iRit = sec.indexOf('run_integration_tests')
    ok(iImpl >= 0 && iDesign > iImpl && iUi > iDesign && iRit > iUi,
      `链序 implement→design→ui_evidence→run_integration_tests（idx ${iImpl}/${iDesign}/${iUi}/${iRit}）`)
  }
}

section('dev-lane 执行主体 parts 段')
{
  const sec = bulletSection(/- \*\*dev-lane\*\*:/)
  ok(sec !== null, 'parts 段存在')
  if (sec) {
    ok(sec.includes('design_integration_tests'), 'parts 段含 design_integration_tests')
    ok(!sec.includes('integration_review'), 'parts 段无退役 integration_review')
  }
}

section('全文无退役机制残留')
{
  ok(!text.includes('integration_review'), 'README 全文无 integration_review')
}

console.log(`\n${passed} passed, ${failed} failed, env_fail=${envFailed}, na=${naCount}`)
console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=${naCount}`)
const allNa = naCount > 0 && passed + failed + envFailed === 0
process.exit(failed > 0 || allNa ? 1 : envFailed > 0 ? 2 : 0)
