/**
 * lane-yaml-chain —— t260901-05「STAGES 链序修正」生成物一致性断言。
 *
 * 直跑：node integration/baselines/lane-yaml-chain.mjs（cwd=泳道根，零依赖）。
 *
 * 背景（review_plan 第 1 轮 P1）：工单台模板序数据源 = workflows/dev-lane.yaml
 * 快照（server/tools/workflow.py load_all glob *.yaml），不是活类。改类不重跑
 * gen_workflows_doc.py = 真源分叉 + stage-parts 有序比对红。
 *
 * 断言口径（arbitrate t260901-05 gen0 修订）：
 *   - 类 STAGES 序 == 期望：硬 FAIL，不降级（类侧漂移永远红）；
 *   - yaml 序 == 类序：一致 → pass；不一致 → FAIL 并大声留痕（收窄分支半交付
 *     与漏跑生成器不可区分，留痕进 output_tail 供人审门判读；venv 在场时
 *     stage-parts-chain 仍硬保 yaml↔类有序比对）。补跑生成器后本条自动恢复全绿。
 *     （三态契约定稿 §7.3：真源分叉属交付物缺陷=产品红，不以环境为条件，不得放行。）
 * 安全红线：纯本地读文件。
 */

import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const YAML = join(REPO, 'server', 'workflows', 'dev-lane.yaml')
const SRC = join(REPO, 'server', 'engine', 'dev_lane.py')

let passed = 0, failed = 0, envFailed = 0, naCount = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const EXPECT = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge', 'suggest_next']

function classOrderFromSrc() {
  const srcText = readFileSync(SRC, 'utf8')
  const start = srcText.indexOf('STAGES = (')
  const end = srcText.indexOf('\n    )', start)
  return [...srcText.slice(start, end).matchAll(/Stage\(id="([^"]+)"/g)].map(m => m[1])
}

section('dev-lane.yaml 快照序 == 类 STAGES 序')
const yamlText = readFileSync(YAML, 'utf8')
const yamlOrder = [...yamlText.matchAll(/^\s+- id: (\S+)$/gm)].map(m => m[1])
if (JSON.stringify(yamlOrder) === JSON.stringify(classOrderFromSrc())) {
  passed++
  console.log('  ok yaml 序==类序（生成物随源，无漂移）')
} else {
  // 收窄分支（写集未含 dev-lane.yaml，review_plan C3 认可）：yaml 再生成移交下一单。
  // 此时本测试无法区分「合规半交付」与「漏跑生成器」——FAIL 并大声留痕（进 output_tail
  // 供 arbitrate/人审门判读），不静默变绿（三态契约闸内无放行语义）；venv 在场的泳道由
  // stage-parts-chain 继续硬保 yaml↔类有序比对。下一单补跑 gen_workflows_doc.py 后，
  // 本条自动恢复硬断言（一致→pass）。
  failed++
  console.log(`  FAIL 真源分叉在案：dev-lane.yaml 序 [${yamlOrder.join(', ')}] ≠ 类序`)
  console.log('       收窄分支半交付或漏跑生成器，二者本测试不可区分；补跑生成器后自动恢复硬断言')
}

section('类 STAGES 序 == 期望（锚定对比基准，硬断言不降级）')
const classOrder = classOrderFromSrc()
ok(JSON.stringify(classOrder) === JSON.stringify(EXPECT),
  `类序=新链（got [${classOrder.join(', ')}]）`)

section('退役步不残留')
{
  ok(!/integration_review/.test(yamlText), 'yaml 无 integration_review')
  const readme = readFileSync(join(REPO, 'server', 'workflows', 'README.md'), 'utf8')
  ok(!/integration_review/.test(readme), 'README 无 integration_review')
}

console.log(`\n${passed} passed, ${failed} failed, env_fail=${envFailed}, na=${naCount}`)
console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=${naCount}`)
const allNa = naCount > 0 && passed + failed + envFailed === 0
process.exit(failed > 0 || allNa ? 1 : envFailed > 0 ? 2 : 0)
