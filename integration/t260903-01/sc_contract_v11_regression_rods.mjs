/**
 * Baseline: t260903-01 erratum regression rods (repo-read-only).
 *
 * Intent:
 *   KI-020① 的故障模式是「真源文件自身漂移」：本票在勘误契约文档的同时修正
 *   verify_lane.py 六处失真文案（含两处幻影关闭路径报错）。本基线钉死勘误不回归：
 *   - 幻影/退役旧措辞在 verify_lane.py 零残留（「道关闭请显式留空并知会」「无声明
 *     即关闭」许诺了引擎不存在的关闭路径；「五项仅在声明在位时跑」「跳过
 *     tsc/smoke/test」是 v2 退役前的失真自述）；
 *   - 契约文档明文 integration 道无关闭态、关闭惯用法=零场景绿（F1 闭环语义）；
 *   - 契约文档明文 SCENARIOS 汇总行双向净判据（v1.8 起 F2「参考性不校验」退役——
 *     t260904-12 三态化反转：谎报=产品红；引擎侧新语义断言随乙段落地，文案锚先行）；
 *   - verify.yaml 头注指向契约 ②a~②e（commit ④ 的落点锁定）。
 *
 * High-level steps (offline, read-only): read three files, assert absence/presence.
 *
 * Note: FAILS LOUDLY until t260903-01 implement lands — the errata do not exist yet.
 * That is the intended pre-implementation state (precedent: sc_sandbar_contract_v1.mjs).
 *
 * Coverage note (anti-duplication): sc_sandbar_contract_v1.mjs 扩段（已核准方案 commit③）
 * 断言新章锚点在位与 ②a 键名；本基线只拥有「旧失真措辞零残留」与 F1/F2 语义锚、
 * verify.yaml 头注指向三面，不重复锚点存在性断言。
 *
 * Reference: notes/debts/known-issues.md KI-020①；review_plan gen1 F1/F2、gen2 通过结论。
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ok ${label}`) }
  else { fail++; console.error(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

const REPO = process.cwd()
let lane = '', contract = '', vy = ''
try { lane = readFileSync(join(REPO, 'server', 'tools', 'verify_lane.py'), 'utf8') } catch { lane = null }
try { contract = readFileSync(join(REPO, 'docs', 'design', 'sandbar-project-onboarding-contract-v1.md'), 'utf8') } catch { contract = null }
try { vy = readFileSync(join(REPO, 'verify.yaml'), 'utf8') } catch { vy = null }

section('A. verify_lane.py 幻影/退役措辞零残留（commit② 勘误回归棒）')
if (lane === null) {
  ok(false, 'A0 server/tools/verify_lane.py 可读')
} else {
  ok(!lane.includes('道关闭请显式留空'), 'A1 幻影文案「道关闭请显式留空并知会」零残留')
  ok(!lane.includes('无声明即关闭'), 'A2 自相矛盾文案「无声明即关闭…fail-closed」零残留')
  ok(!lane.includes('五项仅在声明在位时跑'), 'A3 模块 docstring 五类型段零残留')
  ok(!lane.includes('跳过 tsc/smoke/test'), 'A4 skip_slow 旧描述（跳过 tsc/smoke/test）零残留')
}

section('B. 契约文档 F1/F2 语义明文（integration 道无关闭态 + 汇总行参考性）')
if (contract === null) {
  ok(false, 'B0 契约文档可读')
} else {
  ok(/零场景绿/.test(contract), 'B1 关闭惯用法=零场景绿 已明文（F1）')
  ok(/关闭惯用法|无声明级关闭态|没有[^。\n]{0,16}关闭态/.test(contract),
    'B2 integration 道无声明级关闭态 已明文（F1，与 code 道缺失=关闭 相区分）')
  ok(contract.split('\n').some(l => l.includes('SCENARIOS ran=N') && /env_fail=N na=N/.test(l)),
    'B3 汇总行五计数形状逐字入约（v1.8，t260904-12）')
  ok(contract.split('\n').some(l => l.includes('双向净') && /谎报|不一致/.test(l)),
    'B4 汇总与明细双向净判据已明文（F2 参考性语义 v1.8 退役）')
  ok(contract.split('\n').some(l => /ENV_FAIL \[场景名\] exit=2/.test(l)),
    'B5 ENV_FAIL 行字符级格式已入约（三态协议）')
  ok(contract.split('\n').some(l => /全部子用例 N\/A/.test(l) && /产品红/.test(l)),
    'B6 全部子用例 N/A=产品红已明文（N/A 仅系统状态条件子用例）')
}

section('C. verify.yaml 头注指向契约 ②a~②e（commit④ 落点锁定）')
if (vy === null) {
  ok(false, 'C0 verify.yaml 可读')
} else {
  const header = vy.split('\n').filter(l => l.trim().startsWith('#')).join('\n')
  ok(/②a/.test(header) && /②e/.test(header), 'C1 头注指向 ②a~②e')
}

console.log(`\nSUMMARY pass=${pass} fail=${fail}`)
process.exit(fail > 0 ? 1 : 0)
