/**
 * tests/t260917-05-usage-suspect-ui.mjs —— 用量/日志面「零静默降级」UI 提示单测。
 *
 * 直跑：node server/plugins/workbench/tests/t260917-05-usage-suspect-ui.mjs
 * 覆盖：
 *   A. usageSuspectHint（src/client/usage-model.ts）真值表：S1 混合态（exists+suspect）
 *      / S1 全灭（!exists+suspect）/ S3（!exists+suspectFiles）/ 普通缺省 null /
 *      畸形输入（undefined/null/数字/数组）不抛；正常 exists 无 suspect → null 不虚报。
 *   B. usageSuspectTitle：suspectDetail 优先、reason 兜底、畸形 undefined。
 *   C. 源锚（KI-052 家族手法）：index.tsx 消费位在场——纯函数绿但 UI 没接 = 红
 *      （UsageSummaryLine 消费 usageSuspectHint、AgentLogsTab 渲染 sessionNote）。
 *   D. bundle 锚：lib/client.js 存在时断言警示字面量已进产物（字符串字面量过压缩器
 *      存活，函数名不锚）；不存在 → SKIP 点名（「跑 npm run build 后重跑」——
 *      构建产物缺席是环境缺供，与 smoke 的 zstd-skip 同纪律，不是静默放过）。
 * 全程纯函数直跑 + 源文本断言，不碰 3099、不起 console。
 */

import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { usageSuspectHint, usageSuspectTitle } from './../src/client/usage-model.ts'

const here = dirname(fileURLToPath(import.meta.url))
const wbRoot = join(here, '..')

let passed = 0
let failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* ── A. usageSuspectHint 真值表 ─────────────────────────────── */
ok(usageSuspectHint({ exists: true, suspect: true })
    === '⚠ 部分会话记录格式不认识（疑似 dsh 版本不匹配），该部分未计入',
  'A: S1 混合态（totals 来自好文件）→ 混合警示文案')
ok(usageSuspectHint({ exists: true }) === null, 'A: 正常 exists 无 suspect → null（不虚报）')
ok(usageSuspectHint({ exists: false, suspect: true })
    === '⚠ 会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信',
  'A: S1 全灭 → 票面例句警示')
ok(usageSuspectHint({ exists: false, suspectFiles: ['a/b'] })
    === '⚠ 发现未入统计的会话文件（名字/布局与本版本解析面对不上，疑似 dsh 版本不匹配）',
  'A: S3（发现集空但有疑似文件）→ S3 警示文案')
ok(usageSuspectHint({ exists: false, suspectFiles: [] }) === null, 'A: suspectFiles 空数组 → null')
ok(usageSuspectHint({ exists: false }) === null, 'A: 普通无会话 → null（既有 tokens — 不受扰）')
ok(usageSuspectHint({ exists: false, suspect: true, suspectFiles: ['x'] })
    === '⚠ 会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信',
  'A: S1 优先于 S3（两态同现时按更重的 S1 报）')
ok(usageSuspectHint(undefined) === null && usageSuspectHint(null) === null
  && usageSuspectHint(42) === null && usageSuspectHint(['x']) === null
  && usageSuspectHint({}) === null,
  'A: 畸形输入（undefined/null/数字/数组/空对象）→ null 不抛')

/* ── B. usageSuspectTitle ──────────────────────────────────── */
ok(usageSuspectTitle({ suspectDetail: '会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信（文件：a）' })
    === '会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信（文件：a）',
  'B: suspectDetail 优先（逐文件明细）')
ok(usageSuspectTitle({ reason: '无会话文件可聚合' }) === '无会话文件可聚合', 'B: reason 兜底')
ok(usageSuspectTitle(undefined) === undefined && usageSuspectTitle(7) === undefined,
  'B: 畸形输入 → undefined 不抛')

/* ── C. 源锚：纯函数绿但 UI 没接 = 红 ───────────────────────── */
const indexSrc = readFileSync(join(wbRoot, 'src', 'client', 'index.tsx'), 'utf8')
ok(indexSrc.includes('usageSuspectHint(usage)'),
  'C: UsageSummaryLine 消费 usageSuspectHint（源锚）')
ok(indexSrc.includes('usageSuspectTitle(usage)'),
  'C: UsageSummaryLine 悬停明细走 usageSuspectTitle（源锚）')
ok(indexSrc.includes('logs.sessionNote'),
  'C: AgentLogsTab 渲染 sessionNote 警示（源锚）')
ok(indexSrc.includes("'./usage-model.ts'"),
  'C: index.tsx import usage-model（源锚）')

/* ── D. bundle 锚（构建产物缺席=SKIP 点名，非静默）──────────── */
const bundle = join(wbRoot, 'lib', 'client.js')
if (!existsSync(bundle)) {
  console.log('SKIP D: lib/client.js 不在盘（bundle 未构建）——跑 npm run build 后重跑本测试补锚')
} else {
  const libSrc = readFileSync(bundle, 'utf8')
  ok(libSrc.includes('疑似 dsh 版本不匹配'),
    'D: 警示字面量已进 bundle（字符串字面量过压缩器存活；缺失=改了源忘重建，KI-052）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
