/**
 * lane-yaml-chain — artifact-consistency assertions for the t260901-05
 * "STAGES chain-order fix".
 *
 * Run directly: node integration/baselines/lane-yaml-chain.mjs (cwd = lane
 * root, zero dependencies).
 *
 * Background (review_plan round 1, P1): the workbench template order is read
 * from the workflows/dev-lane.yaml snapshot (server/tools/workflow.py
 * load_all globs *.yaml), not from the live class. Changing the class without
 * re-running gen_workflows_doc.py = source-of-truth divergence plus a red
 * ordered stage-parts comparison.
 *
 * Assertion policy (revised by arbitrate t260901-05 gen0):
 *   - class STAGES order == expected: hard FAIL, never downgraded
 *     (class-side drift is always red);
 *   - yaml order == class order: match → pass; mismatch → FAIL with a loud
 *     paper trail (a narrowed-branch partial delivery and a forgotten
 *     generator run are indistinguishable, so the trail lands in output_tail
 *     for the human review gate to judge; where a venv is present,
 *     stage-parts-chain still enforces the yaml↔class ordered comparison).
 *     The check returns to green on its own once the generator is re-run.
 *     (Three-state contract finalization §7.3: source-of-truth divergence is
 *     a deliverable defect = a product red; it is not conditioned on the
 *     environment and must not be waved through.)
 * Safety line: reads local files only.
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
  'merge_check', 'merge']
// t260910-14：suggest_next 段整链退役（宿主拍板），金链随退役收口更新——
// 老金链含 suggest_next 属过期基准（arbitrate 段 tests-fault 迭代）。

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
  // Narrowed branch (the write set does not include dev-lane.yaml; accepted by
  // review_plan C3): regenerating the yaml is handed to the next ticket. This
  // test then cannot tell a "compliant partial delivery" from a forgotten
  // generator run — so FAIL with a loud paper trail (into output_tail for
  // arbitrate/the human review gate to judge) instead of silently going green
  // (the three-state contract has no pass-through inside the gate); lanes with
  // a venv keep the yaml↔class ordered comparison enforced by
  // stage-parts-chain. Once the next ticket re-runs gen_workflows_doc.py,
  // this check returns to its hard assertion (match → pass).
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
  ok(!/suggest_next/.test(yamlText), 'yaml 无 suggest_next（t260910-14 退役步同族归档）')
  const readme = readFileSync(join(REPO, 'server', 'workflows', 'README.md'), 'utf8')
  ok(!/integration_review/.test(readme), 'README 无 integration_review')
}

console.log(`\n${passed} passed, ${failed} failed, env_fail=${envFailed}, na=${naCount}`)
console.log(`SUMMARY pass=${passed} fail=${failed} env_fail=${envFailed} na=${naCount}`)
const allNa = naCount > 0 && passed + failed + envFailed === 0
process.exit(failed > 0 || allNa ? 1 : envFailed > 0 ? 2 : 0)
