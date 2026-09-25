/**
 * smoke/approve-note.mjs — smoke for the free-text remark on the human-approve modal (KI-004, t260901-22).
 *
 * Run: node smoke/approve-note.mjs (node >= 22.18 native type-stripping).
 * Covers:
 *   A. Malformed-input matrix for buildApproveNote from approve-note.ts (remark empty string /
 *      whitespace-only / leading-trailing whitespace / multi-line / oversized 5k / empty
 *      summary fallback / both empty);
 *   B. Source-text locks (two bridge layers + artifact sync, same pattern as allow-empty-create.mjs):
 *      index.tsx approve path modalized (no more window.confirm), buildApproveNote wired,
 *      opBusy double-click guard, four-path reset, maxLength soft guard;
 *      the same assertions against both lib/client.js and lib/client.cjs (guards against
 *      shipping a stale bundle when tsdown was not rebuilt).
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

/* ---------------- A. Pure functions: malformed-input matrix ---------------- */
console.log('A. buildApproveNote 纯函数')
const SUM = '审批意见第2轮：conclude=approved，块 approve 3/reject 0/带注释 1（落盘 server/reviews/t1.json，reviewer 用户）'

// 1. empty remark -> summary kept as-is (after trim)
ok(buildApproveNote(SUM, '') === SUM, 'remark 空串 → 摘要原样')
// 2. whitespace-only remark (spaces / newlines / tabs) -> treated as empty
ok(buildApproveNote(SUM, '   ') === SUM, 'remark 纯空格 → 摘要原样')
ok(buildApproveNote(SUM, ' \n\t\n ') === SUM, 'remark 换行制表混排 → 摘要原样')
// 3. leading/trailing whitespace in remark -> trimmed, then joined
ok(buildApproveNote(SUM, '  可以发布  ') === `${SUM}\n\n可以发布`, 'remark 前后空白 → trim 后拼接')
// 4. multi-line remark -> exactly one \n\n between summary and remark; line breaks inside the remark kept as-is
const multi = buildApproveNote(SUM, '第一段\n第二段\n\n第三段')
ok(multi === `${SUM}\n\n第一段\n第二段\n\n第三段`, 'remark 多段 → 摘要后恰好一个空行分隔')
ok(multi.split('\n\n').length === 3, '拼接结果按 \\n\\n 分 3 段（摘要/备注前段/备注后段），无歧义')
// 5. oversized 5k remark -> no throw, length identity holds
const big = '长'.repeat(5000)
const bigOut = buildApproveNote(SUM, big)
ok(bigOut.length === SUM.length + 2 + 5000, 'remark 5000 字 → 不抛错且长度 = 摘要+2+5000')
ok(bigOut.startsWith(`${SUM}\n\n`), '超长 remark → 前缀摘要 + 空行不变')
// 6. empty summary + non-empty remark (fetch-failure fallback path) -> only the remark returned
ok(buildApproveNote('', '  人工确认无误  ') === '人工确认无误', 'summary 空 + remark 非空 → 只落 remark')
// 7. both empty -> ''
ok(buildApproveNote('', '') === '', '双空 → 空串（不 sign 出空行污染历史）')
ok(buildApproveNote('  ', ' \n ') === '', '双纯空白 → 空串')
// 8. summary with its own leading/trailing whitespace -> trimmed
ok(buildApproveNote(` ${SUM} `, '') === SUM, 'summary 前后空白 → trim')

/* ---------------- B. Source-text locks ---------------- */
console.log('B. 源码锁（src + 产物同步）')
const here = path.dirname(fileURLToPath(import.meta.url))
const wbDir = path.join(here, '..')

function lockClient(src, label) {
  ok(!src.includes('window.confirm(`审批通过并推进'),
    `${label}：approve 路径不再是原生 confirm（已模态化）`)
  ok(src.includes('buildApproveNote'),
    `${label}：buildApproveNote 已接通`)
  // Reset assertions accept both shapes: TSX `setApproveRemark('')` / compiled `setApproveRemark("")`
  ok(/setApproveBox\(null\)[\s\S]{0,400}setApproveRemark\(('|")\1\)/.test(src) || /setApproveRemark\(('|")\1\)[\s\S]{0,400}setApproveBox\(null\)/.test(src),
    `${label}：确认/取消路径复位 approveBox 与 approveRemark`)
  // Double-click guard accepts both shapes: TSX `disabled={opBusy} onClick={doApprove}` / compiled `disabled: opBusy ... onClick: doApprove`
  ok(/disabled=\{opBusy\} onClick=\{doApprove\}/.test(src) || /disabled:\s*opBusy[\s\S]{0,120}onClick:\s*doApprove/.test(src),
    `${label}：确认按钮 opBusy 防连点`)
  // maxLength accepts both shapes: TSX `maxLength={2000}` / compiled `maxLength: 2e3` (tsdown compresses the number)
  ok(/maxLength=\{2000\}/.test(src) || /maxLength:\s*(2000|2e3)/.test(src),
    `${label}：textarea maxLength=2000 软防呆`)
  ok(src.includes('approveSeqRef'),
    `${label}：fetch 迟到回调有请求序号守卫`)
  ok(src.includes('Approve and advance'), // t260925-18：approve 弹层主按钮英文化
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
