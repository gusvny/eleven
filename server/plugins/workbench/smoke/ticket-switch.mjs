/**
 * smoke/ticket-switch.mjs — smoke for t260831-08 ticket-row session-restore chain + screenshot
 * evidence visualization.
 *
 * Run: node smoke/ticket-switch.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 *
 * Coverage (item by item):
 *   A. ticketContext contract: created=true first message = ticket snapshot (id / title /
 *      stage / pending approvals / acceptance / body truncated at 600 chars / closing
 *      instruction); malformed tk (missing fields / null / object-typed vs number-typed
 *      pending, acceptance) does not crash.
 *   B. listEvidenceFiles + traversal guard: normal listing (archive + worklane candidates,
 *      deduped and sorted), whitelist filtering (oddly named files stay out of the list),
 *      missing directory soft-falls back to [], `../` and illegal ticket ids.
 *   C. evidenceImgSrc contract (exercised through the built artifact lib/client.cjs — real
 *      code, not a copy).
 *   D. (removed by t260903-07) the session-restore chain openTicketSessionFlow — the
 *      per-ticket session linkage was retired and the flow body deleted; the server route
 *      stays under the ③ data-retention ruling (a trace comment in node.ts).
 */

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ticketContext, listEvidenceFiles } from '../node.ts'
import { isEvidenceFileName } from '../src/host/epics.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/* ---------------------------------------------------------------- A ticketContext contract */

section('A ticketContext：created=true 首条消息=工单快照')
{
  const tk = {
    id: 't260831-08', title: '工单行会话恢复', workflow: 'dev-lane', role: 'developer',
    stage: 'implement', stage_state: 'running', blocked_reason: '',
    pending: [{ gate: 'merge', reason: '预演冲突' }, { gate: 'sign', reason: '等签字' },
      { gate: 'a', reason: '' }, { gate: 'b', reason: '' }, { gate: 'c', reason: '' }, { gate: 'd', reason: '只取前5' }],
    acceptance: ['探针场景入 smoke', '详情抽屉可见截图'],
    body: '正文一二三',
  }
  const ctx = ticketContext(tk)
  ok(ctx.includes('【工单上下文】t260831-08《工单行会话恢复》'), '含 id 与标题')
  ok(ctx.includes('工作流：dev-lane · 角色：developer · 当前阶段：implement（running）'), '含工作流/角色/阶段行')
  ok(ctx.includes('待审批：merge — 预演冲突'), '含待审批条目')
  ok(!ctx.includes('只取前5'), '待审批截断前 5 条')
  ok(ctx.includes('1. 探针场景入 smoke') && ctx.includes('2. 详情抽屉可见截图'), '含验收标准编号列表')
  ok(ctx.includes('工单正文：\n正文一二三'), '含工单正文')
  ok(ctx.endsWith('——以上是这张工单的快照。接下来的对话都围绕它：先回我一段你对现状的理解和下一步建议。'), '收尾指令原样')
  // body truncated at 600 chars
  const long = ticketContext({ id: 'x', body: '啊'.repeat(700) })
  ok(long.includes('啊'.repeat(600) + '…') && !long.includes('啊'.repeat(601)), '正文超 600 截断加省略号（600 字保留）')
  // closing edge: a null blocked_reason emits no 「阻塞原因」 line
  ok(!ticketContext(tk).includes('阻塞原因'), '无阻塞不出现阻塞行')
  ok(ticketContext({ ...tk, blocked_reason: '等人' }).includes('阻塞原因：等人'), '有阻塞出现阻塞行')
}
section('A2 ticketContext 畸形输入不崩（取舍清单 #5：Array.isArray 防线）')
{
  ok(typeof ticketContext({ id: 'x', pending: { gate: '对象型' }, acceptance: 42 }) === 'string', '对象型 pending / 数字型 acceptance 不抛（原实现 .slice 会 TypeError）')
  ok(ticketContext({}) .includes('【工单上下文】undefined《》'), '空 tk 兜底不崩')
  ok(ticketContext(null).length > 0, 'null tk 不崩')
  ok(ticketContext({ id: 'x', pending: '字符串也行', acceptance: [null, '文字验收'] }).includes('2. 文字验收'), '脏条目容错')
}

/* ---------------------------------------------------------------- B listEvidenceFiles + traversal guard */

const TMP_ROOT = mkdtempSync(join(tmpdir(), 't260831-08-smoke-'))
const ARCHIVE = join(TMP_ROOT, 'archive')
const REPO = join(TMP_ROOT, 'repo')
const T1 = 'tk-a'
const T2 = 'tk-b'
mkdirSync(join(ARCHIVE, T1), { recursive: true })
mkdirSync(join(REPO, '.worktrees', T1, '.suyou', 'screenshots'), { recursive: true })
mkdirSync(join(REPO, '.worktrees', T2, '.suyou', 'screenshots'), { recursive: true })
writeFileSync(join(ARCHIVE, T1, 'b.png'), 'x')
writeFileSync(join(ARCHIVE, T1, 'a.png'), 'x')
writeFileSync(join(ARCHIVE, T1, 'evil.txt'), 'x')            // not a png → stays out of the list
writeFileSync(join(ARCHIVE, T1, 'we ird.png'), 'x')          // outside the shape whitelist (has a space) → left out
writeFileSync(join(REPO, '.worktrees', T1, '.suyou', 'screenshots', 'c.png'), 'x')
writeFileSync(join(REPO, '.worktrees', T1, '.suyou', 'screenshots', 'nope.jpeg'), 'x')
process.env.SANDBAR_EVIDENCE_DIR = ARCHIVE

section('B listEvidenceFiles：读序=归档→泳道，白名单过滤，去重排序')
{
  const files = await listEvidenceFiles(T1, REPO)
  ok(JSON.stringify(files) === JSON.stringify(['a.png', 'b.png', 'c.png']), `归档+泳道合并去重排序（got ${JSON.stringify(files)}）`)
  ok(!files.includes('evil.txt') && !files.includes('nope.jpeg') && !files.includes('we ird.png'), '白名单外文件不入列表')
  // note: '..png' is a whitelisted literal file name (the RE allows runs of dots and
  // endsWith(.png)) — it is not path traversal, and the existing endpoint admits it too;
  // the traversal defense lives at the id layer (TICKET_ID_RE has no / or .) plus directory
  // containment.
  ok(isEvidenceFileName('a.png') && isEvidenceFileName('..png') && !isEvidenceFileName('x.txt') && !isEvidenceFileName('a.PNG') && !isEvidenceFileName('we ird.png'), 'isEvidenceFileName 口径（小写 .png、白名单字符集）')
}
section('B2 软降级与防穿')
{
  ok((await listEvidenceFiles('tk-none', REPO)).length === 0, '无归档无泳道 → []（已合并工单口径）')
  ok((await listEvidenceFiles(T2, REPO)).length === 0, '泳道在但无图 → []')
  ok((await listEvidenceFiles('../etc', REPO)).length === 0, '../ 穿越被拒 → []')
  ok((await listEvidenceFiles('a/b', REPO)).length === 0, '含 / 的 id 被拒 → []')
  ok((await listEvidenceFiles('', REPO)).length === 0, '空 id 被拒 → []')
  ok((await listEvidenceFiles('x'.repeat(200), REPO)).length === 0, '超长 id（RE 上限外）被拒 → []')
}
process.env.SANDBAR_EVIDENCE_DIR = join(TMP_ROOT, 'does-not-exist')
section('B3 归档基目录不存在（env 指空处）仍走泳道候选')
{
  const files = await listEvidenceFiles(T1, REPO)
  ok(JSON.stringify(files) === JSON.stringify(['c.png']), `归档缺失只余泳道（got ${JSON.stringify(files)}）`)
}
rmSync(TMP_ROOT, { recursive: true, force: true })

/* ------------------------------------------------- C/D real code via the built artifact (lib/client.cjs) */

// dsh client module contract: window.__ModuleLoader__.load({id, factory}), factory(require) → exports.
// react and @deepseek-ai/* are fully externalized through the module table, so a stub require
// handing back an all-purpose callable proxy is enough (the module top level only defines
// things and never renders; hooks/jsx are only touched when a component renders).
function makeStubRequire() {
  const stub = new Proxy(function () {}, {
    get: (_t, p) => (p === Symbol.toPrimitive ? () => '' : stub),
    apply: () => stub,
    construct: () => stub,
  })
  return () => stub
}
function loadClientBundle() {
  const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', 'lib', 'client.cjs'))
  let factory = null
  globalThis.window = { __ModuleLoader__: { load: (m) => { factory = m.factory } } }
  new Function(src)()
  globalThis.window = undefined
  if (typeof factory !== 'function') throw new Error('lib/client.cjs 未按 __ModuleLoader__.load 契约暴露 factory（先跑 tsdown 构建）')
  return factory(makeStubRequire())
}
const client = loadClientBundle()
const { evidenceImgSrc } = client
if (typeof evidenceImgSrc !== 'function') {
  console.error('  FAIL 构建产物未导出 evidenceImgSrc（检查 tsdown 构建）')
  process.exit(1)
}
// t260903-07: the former group D (openTicketSessionFlow session-restore sequencing D1/D2/D3)
// was deleted along with the flow body — the per-ticket session linkage is retired, clicking a
// ticket only opens the middle-column details (the right-column chat is always the global session).
// Group A (ticketContext contract + malformed tk cases) stays: ticketContext is live code (the
// server keeps /api/ticket-session/open under the ③ data-retention ruling, with a trace comment
// in node.ts). B/C have nothing to do with the removed chain and are untouched.

section('C evidenceImgSrc 契约')
{
  ok(evidenceImgSrc('t1', 'a.png') === '/sandbar-workbench/api/wf/tickets/t1/evidence/a.png', '相对路径端点契约（safeUrl 放行）')
  ok(!evidenceImgSrc('t1', 'a.png').startsWith('data:'), '不走 data: 内联（取舍清单 #4：防穿收口 host）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
