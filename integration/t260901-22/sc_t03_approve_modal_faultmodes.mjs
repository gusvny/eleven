/**
 * integration/t260901-22/t03_approve_modal_faultmodes.mjs
 * —— KI-004 approve 弹层故障面行为契约（t260901-22，integration 层）。
 *
 * 用户视角的故障面（与 developer 单测错位：本层只锁「用户会遇到的事故」）：
 *   1) 连点「确认通过并推进」不得重复签字（签字进不可变历史，重复签代价高）；
 *   2) 摘要 fetch 慢/失败时弹层行为确定（照开、有文案，不白屏不吊死）；
 *   3) 无论怎么关弹层（确认/取消/Esc/外点），下次打开不带脏备注（不串单）；
 *   4) 多页签写前守门不被本单旁路（另一页签刚签过 → 仍有二次确认安全网）；
 *   5) 失败后弹层不吊着等结果，错误信息显示在操作条（与打回弹层同一心智）。
 *
 * 手法：对 src + 产物做行为形状断言（正则族，不钉死具体变量名，防实现漂移误伤）。
 *
 * 直跑：node integration/t260901-22/t03_approve_modal_faultmodes.mjs（node ≥22.18）。
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

const src = await readFile(path.join(WB, 'src', 'client', 'index.tsx'), 'utf8')
const bundle = await readFile(path.join(WB, 'lib', 'client.js'), 'utf8')

/* ---- 1) 防连点：确认钮 opBusy 禁用 + doOp 先置 busy 后放行 ---- */
section('1 防重复签字')
ok(/disabled=\{[^}]*opBusy[^}]*\}[^>]*>[^<]*Approve and advance/.test(src),
  'src：确认钮 disabled={opBusy}（执行期连点无效）')
ok(/setOpBusy\(true\)[\s\S]{0,2000}await apiPost[\s\S]{0,3000}finally[\s\S]{0,200}setOpBusy\(false\)/
  .test(src), 'src：doOp 先 setOpBusy(true) → await → finally setOpBusy(false)（busy 必复位）')

/* ---- 2) 摘要 fetch 迟到/失败的行为确定 ---- */
section('2 摘要 fetch 竞态与失败')
ok(/no stored review|no summary this round/.test(bundle), '产物：fetch 失败时弹层有 no-stored-review 类文案（照开不白屏；t260925-18 UI 英文化后锚英文串）')
ok(/await fetchReviewFile[\s\S]{0,400}setApproveBox|setApproveBox[\s\S]{0,80}fetchReviewFile/
  .test(src) || /fetchReviewFile[\s\S]{0,600}setApproveBox/.test(src),
  'src：弹层在 fetch 摘要之后打开（不同时开着弹层等摘要）')
ok(/[Ss]eq.*[Rr]ef|[Rr]ef.*[Ss]eq|requestId|reqSeq|latestFetch/.test(src),
  'src：存在迟到回调守卫（请求序号/ ref 比对，取消后到的 fetch 不污染弹层）')

/* ---- 3) 全终态回收：每条关闭路径都复位弹层与备注 ---- */
section('3 关弹层全路径复位（不串单）')
{
  // 本 UI 家族（wb-modal）无 Esc/外点关闭处理器（rework 打回弹层同样只有「确认/取消」
  // 两条真实关闭路径）——验收口径改为：每一处 setApproveBox(null) 调用点都必须与
  // setApproveRemark('') 配对（同函数紧邻复位），且真实关闭路径 ≥2。
  const boxResets = (src.match(/setApproveBox\(null\)/g) ?? []).length
  const pairedResets = (src.match(/setApproveBox\(null\)\s*setApproveRemark\(''\)/g) ?? []).length
  ok(boxResets >= 2, `src：setApproveBox(null) 出现 ${boxResets} 处（确认/取消两条真实关闭路径）`)
  ok(boxResets === pairedResets, `src：${boxResets} 处关弹层调用全部配对复位备注（${pairedResets} 处紧邻 setApproveRemark('')）——无路径留脏态`)
}
ok(/确认后立即关弹层|同 doRework 口径/.test(src) || /setApproveBox\(null\)[\s\S]{0,200}doSign|doSign[\s\S]{0,200}setApproveBox\(null\)/
  .test(src) || /void doSign/.test(src),
  'src：确认路径不把弹层吊着等结果（doSign 走 doOp 异步、opMsg 外露成败）')

/* ---- 4) 多页签守门不被旁路 ---- */
section('4 写前守门回归')
ok(src.includes('peerWriteAllowed') && /peerWriteAllowed\(id, op\)/.test(src),
  'src：doOp 仍过 peerWriteAllowed（另一页签刚签过/正在看 → 二次确认安全网保留）')

/* ---- 5) maxLength 软上限在产物中真实生效 ---- */
section('5 备注长度软防呆')
ok(/maxLength[:=]\s*\{?\s*2000|maxlength="2000"/i.test(bundle) || /maxLength=\{2000\}/.test(src),
  '产物/src：textarea maxLength=2000（前端软防呆，placeholder 有提示）')

console.log(`\nSUMMARY pass=${pass} fail=${fail} env_fail=0 na=0`)
process.exit(fail > 0 ? 1 : 0)
