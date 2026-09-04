/**
 * lane-stages-chain —— t260901-05「STAGES 链序修正」引擎侧断言。
 *
 * 直跑：node integration/baselines/lane-stages-chain.mjs（cwd=泳道根，零依赖）。
 *
 * 覆盖（全部文本级断言，不依赖 temporalio；import 级复核无 venv 时干净 SKIP）：
 *   1. dev_lane.py STAGES 元数据序 = 新链（implement→design_integration_tests→ui_evidence
 *      →run_integration_tests，并行分叉语义在展示序上线性化）；
 *   2. next 指针同步（implement→design_integration_tests→ui_evidence→run_integration_tests）；
 *   3. design_integration_tests desc 注明并行；全步 parts 非空（文本级）；
 *   4. 附带修复：`_finish("acceptance"` 孤儿键消失、`_finish("acceptance_walkthrough"` 在案。
 * 安全红线：纯本地读文件，不碰 3099/Temporal/网络。
 */

import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync } from 'node:child_process'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const REPO = resolve(HERE, '..', '..')
const SRC = join(REPO, 'server', 'dsh', 'temporal-poc', 'dev_lane.py')

let passed = 0, failed = 0, skipped = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const EXPECT = ['create_plan', 'review_plan', 'implement', 'design_integration_tests',
  'ui_evidence', 'run_integration_tests', 'arbitrate', 'acceptance_walkthrough',
  'merge_check', 'merge', 'suggest_next']

const text = readFileSync(SRC, 'utf8')

/* ------------------------------------------------------------ 1. STAGES 顺序 */
section('STAGES 元数据序（文本级，真源=类）')
const start = text.indexOf('STAGES = (')
const end = text.indexOf('\n    )', start)
const region = text.slice(start, end)
const order = [...region.matchAll(/Stage\(id="([^"]+)"/g)].map(m => m[1])
ok(order.length === EXPECT.length && order.every((s, i) => s === EXPECT[i]),
  `STAGES 序=新链（got [${order.join(', ')}]）`)

/* ------------------------------------------------------------ 2. next 指针 */
section('next 指针同步')
for (const [from, to] of [['implement', 'design_integration_tests'],
  ['design_integration_tests', 'ui_evidence'], ['ui_evidence', 'run_integration_tests']]) {
  const re = new RegExp(`Stage\\(id="${from}"[\\s\\S]*?next="([^"]*)"`)
  const m = region.match(re)
  ok(m && m[1] === to, `${from}.next=${to}（got ${m && m[1]}）`)
}

/* ------------------------------------------------------------ 3. desc/parts */
section('desc 并行注明 + parts 非空（文本级）')
{
  const blk = region.match(/Stage\(id="design_integration_tests"[\s\S]*?(?=Stage\(id=|\n    \))/)
  ok(blk && /并行/.test(blk[0]), 'design_integration_tests desc 注明并行')
  const noParts = [...region.matchAll(/Stage\(id="([^"]+)"[\s\S]*?parts=\(\)/g)].map(m => m[1])
  ok(noParts.length === 0, `无空 parts 步（${noParts.join(',') || '无'}）`)
}

/* ------------------------------------------------------------ 4. acceptance 键修复 */
section('acceptance 键对齐附带修复')
{
  ok(!/_finish\("acceptance"[,)]/.test(text), '无 _finish("acceptance" 孤儿键调用')
  ok(/_finish\("acceptance_walkthrough"[,)]/.test(text), '_finish("acceptance_walkthrough") 在案')
}

/* ------------------------------------------------------------ 5. import 级复核（SKIP-gated） */
section('import 级复核：活类 STAGES 与文本一致、parts 枚举合法（需 temporalio，缺失则 SKIP）')
{
  const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(join(REPO, 'server', 'dsh', 'temporal-poc'))})
from workflows_v2 import TEMPLATE_CLASSES
c = TEMPLATE_CLASSES['dev-lane']
print(json.dumps({"order": [s.id for s in c.STAGES], "parts": {s.id: list(s.parts) for s in c.STAGES}}))
`
  const venvPy = join(REPO, 'server', 'dsh', 'temporal-poc', '.venv', 'bin', 'python')
  let out = null, used = ''
  for (const cand of [venvPy, 'python3']) {
    try { out = execFileSync(cand, ['-c', py], { encoding: 'utf8' }); used = cand; break }
    catch { /* try next */ }
  }
  if (!out) { skipped++; console.log('  SKIP 无可用 python+temporalio（worktree 无 .venv 的已知限制）') }
  else {
    const info = JSON.parse(out)
    ok(JSON.stringify(info.order) === JSON.stringify(EXPECT),
      `活类 STAGES 序=新链（via ${used.split('/').pop()}）`)
    const LEGAL = ['agent', 'script', 'human']
    const bad = Object.entries(info.parts).filter(([, p]) => !p.length || p.some(x => !LEGAL.includes(x)))
    ok(bad.length === 0, `活类 parts 全非空且枚举合法（${bad.map(b => b[0]).join(',') || '全合法'}）`)
  }
}

console.log(`\n${passed} passed, ${failed} failed, ${skipped} skipped`)
console.log(`SUMMARY pass=${passed} skip=${skipped} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
