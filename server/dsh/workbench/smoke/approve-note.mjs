/**
 * smoke/approve-note.mjs —— KI-004（t260901-22）：人审 approve 弹层自由备注 冒烟。
 *
 * 直跑：node smoke/approve-note.mjs（node ≥22.18 原生 type-stripping）。
 * 覆盖：
 *   A. approve-note.ts 纯函数 buildApproveNote 的畸形输入矩阵
 *      （remark 空串/纯空白/前后空白/含换行多段/超长 5k/summary 空回落/双空）；
 *   B. 源码锁（桥路两层 + 产物同步，模式同 allow-empty-create.mjs 源码锁惯例）：
 *      index.tsx approve 路径模态化（不再 window.confirm）、buildApproveNote 接通、
 *      opBusy 防连点、四路径复位、maxLength 软防呆；
 *      lib/client.js 与 lib/client.cjs 同一组断言（防 tsdown 未重建交付陈旧包）。
 */

import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { buildApproveNote } from '../src/client/approve-note.ts'

let pass = 0
let fail = 0
function ok(cond, label) {
  if (cond) { pass++; console.log(`  ✓ ${label}`) }
  else { fail++; console.error(`  ✗ ${label}`) }
}

/* ---------------- A. 纯函数：畸形输入矩阵 ---------------- */
console.log('A. buildApproveNote 纯函数')
const SUM = '审批意见第2轮：conclude=approved，块 approve 3/reject 0/带注释 1（落盘 server/dsh/reviews/t1.json，reviewer 用户）'

// 1. remark 空串 → 摘要原样（trim 后）
ok(buildApproveNote(SUM, '') === SUM, 'remark 空串 → 摘要原样')
// 2. remark 纯空白（空格 / 换行制表）→ 视同空
ok(buildApproveNote(SUM, '   ') === SUM, 'remark 纯空格 → 摘要原样')
ok(buildApproveNote(SUM, ' \n\t\n ') === SUM, 'remark 换行制表混排 → 摘要原样')
// 3. remark 前后空白 → trim 后拼接
ok(buildApproveNote(SUM, '  可以发布  ') === `${SUM}\n\n可以发布`, 'remark 前后空白 → trim 后拼接')
// 4. remark 含换行多段 → 摘要与备注间恰好一个 \\n\\n，备注内部换行原样保留
const multi = buildApproveNote(SUM, '第一段\n第二段\n\n第三段')
ok(multi === `${SUM}\n\n第一段\n第二段\n\n第三段`, 'remark 多段 → 摘要后恰好一个空行分隔')
ok(multi.split('\n\n').length === 3, '拼接结果按 \\n\\n 分 3 段（摘要/备注前段/备注后段），无歧义')
// 5. remark 超长 5k → 不抛错，长度恒等式成立
const big = '长'.repeat(5000)
const bigOut = buildApproveNote(SUM, big)
ok(bigOut.length === SUM.length + 2 + 5000, 'remark 5000 字 → 不抛错且长度 = 摘要+2+5000')
ok(bigOut.startsWith(`${SUM}\n\n`), '超长 remark → 前缀摘要 + 空行不变')
// 6. summary 空 + remark 非空（fetch 失败回落路径）→ 只返回 remark
ok(buildApproveNote('', '  人工确认无误  ') === '人工确认无误', 'summary 空 + remark 非空 → 只落 remark')
// 7. 两者皆空 → ''
ok(buildApproveNote('', '') === '', '双空 → 空串（不 sign 出空行污染历史）')
ok(buildApproveNote('  ', ' \n ') === '', '双纯空白 → 空串')
// 8. summary 自带前后空白 → trim
ok(buildApproveNote(` ${SUM} `, '') === SUM, 'summary 前后空白 → trim')

/* ---------------- B. 源码锁 ---------------- */
console.log('B. 源码锁（src + 产物同步）')
const here = path.dirname(fileURLToPath(import.meta.url))
const wbDir = path.join(here, '..')

function lockClient(src, label) {
  ok(!src.includes('window.confirm(`审批通过并推进'),
    `${label}：approve 路径不再是原生 confirm（已模态化）`)
  ok(src.includes('buildApproveNote'),
    `${label}：buildApproveNote 已接通`)
  // 复位断言兼容两种形态：TSX `setApproveRemark('')` / 编译产物 setApproveRemark("")
  ok(/setApproveBox\(null\)[\s\S]{0,400}setApproveRemark\(('|")\1\)/.test(src) || /setApproveRemark\(('|")\1\)[\s\S]{0,400}setApproveBox\(null\)/.test(src),
    `${label}：确认/取消路径复位 approveBox 与 approveRemark`)
  // 防连点断言兼容：TSX `disabled={opBusy} onClick={doApprove}` / 产物 `disabled: opBusy ... onClick: doApprove`
  ok(/disabled=\{opBusy\} onClick=\{doApprove\}/.test(src) || /disabled:\s*opBusy[\s\S]{0,120}onClick:\s*doApprove/.test(src),
    `${label}：确认按钮 opBusy 防连点`)
  // maxLength 断言兼容：TSX `maxLength={2000}` / 产物 `maxLength: 2e3`（tsdown 数字压缩）
  ok(/maxLength=\{2000\}/.test(src) || /maxLength:\s*(2000|2e3)/.test(src),
    `${label}：textarea maxLength=2000 软防呆`)
  ok(src.includes('approveSeqRef'),
    `${label}：fetch 迟到回调有请求序号守卫`)
  ok(src.includes('确认通过并推进'),
    `${label}：approve 弹层确认文案在位`)
}

const indexSrc = await readFile(path.join(wbDir, 'src', 'client', 'index.tsx'), 'utf8')
lockClient(indexSrc, 'src/client/index.tsx')

const libSrc = await readFile(path.join(wbDir, 'lib', 'client.js'), 'utf8')
lockClient(libSrc, 'lib/client.js')
const libCjs = await readFile(path.join(wbDir, 'lib', 'client.cjs'), 'utf8')
lockClient(libCjs, 'lib/client.cjs')
ok(libSrc.length === libCjs.length && libSrc === libCjs, 'lib/client.js 与 client.cjs 逐字节一致（tsdown 产物对）')

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail > 0 ? 1 : 0)
