/**
 * tests/t261008-23-timeline-collapse.mjs —— 时间轴 reason 折叠 + Changes 紧凑面 UT
 * （t261008-23 缺陷 2/3 的模型半）。
 *
 * 直跑：node server/plugins/workbench/tests/t261008-23-timeline-collapse.mjs
 * 覆盖：
 *   A. collapseReason：短 reason 原样（collapsed=false）；长 reason 出短式+
 *      collapsed=true，full 恒等于原文（展开不丢字）；空白归一；空串安全。
 *   B. timelineRows × collapseReason 组合：条目数不因折叠减少（option b：
 *      keep every entry——逐条对表输入长度）。
 *   C. changeRows：紧凑面=总量行 + 逐文件行（path → status · +a −d），超封顶出
 *      「more files」点名行；full diff 不在紧凑面（无 unified 文本行）——与折叠块
 *      不重叠（缺陷 3 方向）。
 *   D. 畸形输入逐条跳过不抛。
 * 全程纯函数直跑，不碰 3099。
 */
import assert from 'node:assert/strict'
import { collapseReason, TIMELINE_REASON_MAX, timelineRows, changeRows } from '../src/client/ticket-detail-column-model.ts'

let passed = 0, failed = 0
function ok(cond, name) {
  if (cond) { passed += 1; console.log(`ok   ${name}`) }
  else { failed += 1; console.error(`FAIL ${name}`) }
}

/* A collapseReason */
const short = collapseReason('done: three files changed')
ok(short.collapsed === false && short.short === 'done: three files changed' && short.full === 'done: three files changed', 'short reason passes through, collapsed=false')
const longText = 'handoff from implement: root cause was the read face resolving the old dot-directory name; fix candidates ordered newest first and the probed path is reported back to the face'
const long = collapseReason(longText)
ok(long.collapsed === true, `reason over ${TIMELINE_REASON_MAX} chars → collapsed`)
ok(long.short.length <= TIMELINE_REASON_MAX + 1 && long.short.endsWith('…'), 'collapsed short form is capped and marked')
ok(long.full === longText, 'expansion keeps the FULL text (nothing lost)')
const spaced = collapseReason('line one\n\nline two   with spaces and ' + 'x'.repeat(120))
ok(spaced.collapsed === true && !spaced.short.includes('\n'), 'whitespace normalized in the short form')
ok(collapseReason('').short === '' && collapseReason('').collapsed === false, 'empty reason safe')

/* B 条目保全 */
const tl = [
  { at: '2026-10-08T10:00:00Z', stage: 'create_plan', state: 'running', reason: 'adopt dev-lane' },
  { at: '2026-10-08T10:05:00Z', stage: 'create_plan', state: 'done', reason: longText },
  { at: '2026-10-08T10:06:00Z', stage: 'review_plan', state: 'running', reason: '' },
  null, 42, { stage: 7 }, 'junk',
]
const rows = timelineRows(tl)
ok(rows !== null && rows.length === 3, `malformed entries skipped, real entries kept (${rows?.length})`)
const collapsedCount = rows.filter(r => collapseReason(r.reason).collapsed).length
ok(rows.every(r => collapseReason(r.reason).full === r.reason), 'every row still carries its full reason (no entry dropped to look tidy)')
ok(collapsedCount === 1, `exactly the long reason collapses (${collapsedCount})`)

/* C changeRows 紧凑面 */
const diff = {
  files: [
    { path: 'server/a.ts', status: 'modified', unified: '+x\n-y\n+z\n' },
    { path: 'docs/b.md', status: 'modified', kind: 'doc', blocks: [] },
    { path: 'lib/c.js', status: 'added', unified: '+a\n+b\n' },
    { path: '', status: 'modified', unified: '+ghost\n' },
  ],
}
const cr = changeRows(diff, { worktree: 'wt-x', branch: 'lane/t-1' })
ok(cr !== null, 'changeRows builds')
ok(cr[0].k === 'files' && cr[0].v.includes('4') && cr[0].v.includes('+5') && cr[0].v.includes('−1'), `totals row first (got ${cr[0].k}: ${cr[0].v})`)
const fileRows = cr.filter(r => r.k.includes('.'))
ok(fileRows.length === 3, `one compact row per file, pathless entries skipped (${fileRows.length})`)
ok(fileRows[0].v.startsWith('modified · +2 −1'), `file row carries status and size (got ${fileRows[0].v})`)
ok(!cr.some(r => typeof r.v === 'string' && r.v.includes('+x')), 'no diff body in the compact panel (full diff lives only in the fold)')

/* C2 封顶点名 */
const many = { files: Array.from({ length: 12 }, (_, i) => ({ path: `f${i}.ts`, status: 'modified', unified: '+a\n' })) }
const cr2 = changeRows(many, {})
const more = cr2.find(r => r.k === '…')
ok(more !== undefined && more.v.startsWith('4 more files'), `over-cap files named by a pointer row (got ${more?.v})`)

/* D 畸形 */
ok(changeRows(null, {}) === null && changeRows({}, {}) === null && changeRows({ files: 'x' }, {}) === null, 'malformed diff face → null (no scaffolding)')

console.log(`\nTIMELINE_COLLAPSE ran=${passed + failed} pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
