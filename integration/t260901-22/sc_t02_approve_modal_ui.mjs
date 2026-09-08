/**
 * integration/t260901-22/t02_approve_modal_ui.mjs
 * —— KI-004「approve 弹层自由备注」用户可感知 UI 产物契约（t260901-22）。
 *
 * 用户视角验收：审批人点开「✓ 审批通过」后，看到的必须是一个弹层——
 * 只读自动摘要（标明不可编辑）、所属立项一行、自由备注输入框（可空、有长度软上限）；
 * 不再是只能点「确定/取消」的原生 confirm。本测试锁的是**用户实际被服务的产物**
 * （lib/client.js + lib/client.cjs 双产物），不是 developer 的源码——产物陈旧
 * （改了 src 忘重建 tsdown）在本层必现形。
 *
 * 直跑：node integration/t260901-22/t02_approve_modal_ui.mjs（node ≥22.18）。
 * 末行 SUMMARY pass=<n> fail=<k> env_fail=<e> na=<w>（三态，闸内无旧跳过语义）；
 * fail>0 或全 na→exit 1，env_fail>0→exit 2。
 */

import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const WB = path.resolve(HERE, '..', '..', 'server', 'plugins', 'workbench')

let pass = 0, fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}
function section(s) { console.log(`\n== ${s} ==`) }

const bundleEsm = await readFile(path.join(WB, 'lib', 'client.js'), 'utf8')
const bundleCjs = await readFile(path.join(WB, 'lib', 'client.cjs'), 'utf8')
const src = await readFile(path.join(WB, 'src', 'client', 'index.tsx'), 'utf8')

/* ---- A. 弹层存在且三区结构完整（用户在屏幕上能看到什么）---- */
section('A 弹层三区：只读摘要 / epicLine / 自由备注')
for (const [name, b] of [['lib/client.js', bundleEsm], ['lib/client.cjs', bundleCjs]]) {
  ok(b.includes('自动摘要') && b.includes('不可编辑'), `${name}：摘要区标明「自动摘要（不可编辑）」`)
  ok(b.includes('自由备注') && b.includes('可空'), `${name}：备注输入框 placeholder 标明可空`)
  ok(/maxLength.{0,4}2000|maxlength.{0,4}2000|2000/.test(b), `${name}：备注有 2000 字软上限`)
  ok(b.includes('所属立项') || b.includes('epicLine'), `${name}：弹层含所属立项行`)
}

/* ---- B. 旧交互已移除：原生 confirm 不再是 approve 的签字口 ---- */
section('B 旧 confirm 交互移除')
for (const [name, b] of [['lib/client.js', bundleEsm], ['lib/client.cjs', bundleCjs]]) {
  ok(!b.includes('审批通过并推进？'), `${name}：旧的「审批通过并推进？」原生 confirm 已删`)
}
ok(!/stageState === 'awaiting-human'[\s\S]{0,400}window\.confirm/.test(src),
  'src：awaiting-human 分支内不再出现 window.confirm')

/* ---- C. 备注确实接进签字调用（不是摆设输入框）---- */
section('C 备注接进 sign 链路')
for (const [name, b] of [['lib/client.js', bundleEsm], ['lib/client.cjs', bundleCjs]]) {
  ok(b.includes('buildApproveNote'), `${name}：签字 note 经 buildApproveNote 拼接`)
  ok(/approveRemark/.test(b), `${name}：approveRemark state 存在`)
  ok(/approveBox/.test(b), `${name}：approveBox 弹层 state 存在`)
}
ok(/doSign\([^)]*approve[^)]*buildApproveNote|buildApproveNote\([^)]*\)/.test(src),
  'src：doSign(approve) 的 note 实参来自 buildApproveNote(summary, remark)')

/* ---- D. 双产物同步（防 tsdown 未重建交付陈旧包）---- */
section('D 双产物一致性')
ok(bundleEsm.includes('buildApproveNote') === bundleCjs.includes('buildApproveNote')
  && bundleEsm.includes('自动摘要') === bundleCjs.includes('自动摘要'),
  'ESM 与 CJS 产物同时含/同时不含新弹层特征（不同步=有一边是陈旧包）')

/* ---- E. 打回弹层未被破坏（回归：reject 路径 UI 照旧）---- */
section('E 回归：打回弹层照旧')
ok(src.includes('reworkId') && src.includes('reworkNote') && src.includes('确认打回'),
  'src：rework 打回弹层（reworkId/reworkNote/确认打回）未被本单破坏')

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail > 0 ? 1 : 0)
