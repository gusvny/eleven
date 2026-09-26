#!/usr/bin/env node
/**
 * t260915-17-ticket-time-ui.mjs —— 「本票时刻只读查看」客户端模型层单测（t260915-17）。
 *
 * 直跑：node server/plugins/workbench/tests/t260915-17-ticket-time-ui.mjs
 * 契约：exit 0 = 过；末行 SUMMARY pass=<n> skip=<m> fail=<k>。
 *
 * 覆盖（shared/ticket-time-model.ts 纯函数层；组件渲染由 bundle 构建 + 集成场景
 * 源码锁覆盖，本文件不裸跑 react）：
 *   A. mode 词表与判定（合法三态/畸形值）
 *   B. isSafeTicketFilePath 路径白名单（正常/中文/多层/各畸形形态）
 *   C. isInFlightStatus / isSettleCapableStatus（C1/N2 口径：status 五态+畸形）
 *   D. ticketTimeFailReason 人话构表（全 kind 非空、关键短语、detail 拼接）
 *   E. buildTicketTimeBanner 横幅视图模型（settle/base 有横幅、current=null 横幅消失、
 *      refShort 畸形不渲染假版本号）
 *   F. viewer/refs 接线的源码锚（index.tsx 链接化点位、viewer 只读刚性——无编辑控件）
 */
import { readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(import.meta.url), '..')
const MODEL_TS = join(HERE, '..', 'src', 'shared', 'ticket-time-model.ts')
const VIEWER_TSX = join(HERE, '..', 'src', 'client', 'ticket-time-viewer.tsx')
const INDEX_TSX = join(HERE, '..', 'src', 'client', 'index.tsx')
const { isTicketTimeMode, isSafeTicketFilePath, isInFlightStatus, isSettleCapableStatus, ticketTimeFailReason, buildTicketTimeBanner } = await import(MODEL_TS)

let PASS = 0
let FAIL = 0
function ok(cond, label) {
  if (cond) { PASS += 1; console.log(`  ok  ${label}`) }
  else { FAIL += 1; console.error(`  FAIL ${label}`) }
}

/* ── A. mode ── */
ok(isTicketTimeMode('settle') && isTicketTimeMode('base') && isTicketTimeMode('current'), 'A1: 三态合法')
for (const bad of ['Settle', '', null, undefined, 42, {}, 'settle ']) {
  if (isTicketTimeMode(bad)) { ok(false, `A2: 畸形 mode 拒收（${String(bad)}）`) }
}
ok(true, 'A2: 畸形 mode 全拒收')

/* ── B. 路径白名单 ── */
for (const good of ['docs/x.md', 'server/engine/base.py', 'src/client/index.tsx', 'notes/debts/known-issues.md', '知识库/设计文档.md', 'a.b.c/d-e_f.ts', 'app/public/data/x.json']) {
  if (!isSafeTicketFilePath(good)) ok(false, `B1: 合法路径误拒（${good}）`)
}
ok(true, 'B1: 合法路径（含中文/多点/多层）全过')
for (const bad of ['', null, undefined, 42, {}, '/abs/x', '../etc/passwd', 'a/../b', './x', 'a\\b', 'a b.md', 'a%20b.md', '..', 'a/']) {
  if (isSafeTicketFilePath(bad)) ok(false, `B2: 畸形路径误收（${String(bad)}）`)
}
ok(true, 'B2: 畸形路径（穿路径/绝对/反斜杠/空格/URL编码/空）全拒')

/* ── C. 在飞/已收口谓词（C1：以 status 为锚） ── */
ok(isInFlightStatus('dispatched') && isInFlightStatus('rework'), 'C1: 在飞=dispatched|rework')
for (const s of ['settled', 'verified', 'closed']) ok(!isInFlightStatus(s), `C2: ${s} 不算在飞`)
ok(!isInFlightStatus(42) && !isInFlightStatus(undefined) && !isInFlightStatus('DISPATCHED'), 'C3: 畸形/大小写不冒充在飞（由 bad-status 面处理）')
ok(isSettleCapableStatus('settled') && isSettleCapableStatus('verified') && isSettleCapableStatus('closed'), 'C4: 收口可查三态')
ok(!isSettleCapableStatus('dispatched') && !isSettleCapableStatus('rework') && !isSettleCapableStatus(42), 'C5: 其余形态不可查')

/* ── D. reason 构表 ── */
const kinds = ['bad-status', 'in-flight', 'main-lane', 'lane-gone', 'path-not-in-version', 'no-base', 'member-repo-no-base', 'invalid-base', 'binary', 'current-missing', 'repo-error']
const phrases = {
  'in-flight': 'still in flight', 'main-lane': 'main-lane ticket', 'lane-gone': 'lane was torn down',
  'path-not-in-version': 'is not in that version', 'no-base': 'no recorded base ref',
  'member-repo-no-base': 'No base ref is recorded for the member-repo path', 'invalid-base': 'Invalid base ref',
  'binary': 'Binary file', 'current-missing': 'does not exist in the current working tree',
}
for (const k of kinds) {
  const r = ticketTimeFailReason(k, 'DET')
  if (typeof r !== 'string' || r.length < 6) ok(false, `D: ${k} 文案缺失`)
}
ok(true, 'D1: 全 kind 文案非空')
for (const [k, ph] of Object.entries(phrases)) {
  if (!ticketTimeFailReason(k, 'DET').includes(ph)) ok(false, `D: ${k} 缺关键短语「${ph}」`)
}
ok(true, 'D2: 关键短语逐 kind 在场（fail-closed 必答「为什么拿不到」）')
ok(ticketTimeFailReason('lane-gone', 't260915-17').includes('t260915-17'), 'D3: detail 拼接（票号点名）')

/* ── E. 横幅视图模型 ── */
{
  const b1 = buildTicketTimeBanner('settle', 'squash-commit', 'a1b2c3d4e5f6')
  ok(b1 !== null && b1.text === '🕰 Ticket time · read-only' && b1.canJumpCurrent === true
    && b1.version.includes('Settled') && b1.version.includes('a1b2c3d4e5f6') && b1.version.includes('squash settle commit'),
    'E1: settle 横幅=mock D 原话主文案+版本副文案+跳链在场')
  const b2 = buildTicketTimeBanner('base', 'base-ref', '07e36415ff12')
  ok(b2 !== null && b2.version.includes('Baseline') && b2.canJumpCurrent === true, 'E2: base 横幅同构')
  ok(buildTicketTimeBanner('current', 'base-ref', 'a1b2c3d4e5f6') === null, 'E3: current → 横幅消失（切到当前版的可见信号）')
  for (const badRef of [undefined, null, 42, '', '   ']) {
    if (buildTicketTimeBanner('settle', 'merge-commit', badRef) !== null) ok(false, `E4: refShort 畸形应不渲染横幅（${String(badRef)}）`)
  }
  ok(true, 'E4: refShort 畸形 → 横幅整条不渲染（不显假版本号）')
}

/* ── F. 接线源码锚 ── */
{
  const viewer = readFileSync(VIEWER_TSX, 'utf8')
  const index = readFileSync(INDEX_TSX, 'utf8')
  ok(viewer.includes('data-testid={TICKET_TIME_BANNER_TESTID}') && viewer.includes('data-testid={TICKET_TIME_JUMP_TESTID}'), 'F1: viewer 横幅/跳链契约锚在场')
  ok(viewer.includes("setMode('current')"), 'F2: 跳到当前版=内部切 current 口径')
  // 只读刚性：渲染面无编辑元素/保存路径。isEditableTarget 函数体（Esc guard 的
  // editable 判定，C6 声明带）单独剥除后 contentEditable 不应再出现。
  const viewerRender = viewer
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*/g, '')
    .replace(/function isEditableTarget[\s\S]*?\n}\n/, '')
  ok(!/<textarea/i.test(viewerRender) && !/<input/i.test(viewerRender)
    && !/contentEditable/i.test(viewerRender)
    && !/保存/.test(viewerRender),
    'F3: viewer 只读刚性——无编辑控件/保存路径（源码层，Esc guard 判定除外）')
  ok(index.includes("onClick={() => setFileViewer({ ticketId: detail.id, path: f, mode: 'settle' })}")
    && index.includes("onClick={() => setFileViewer({ ticketId: detail.id, path: f, mode: 'base' })}"), 'F4: 状态卡文件行=settle、背景引用行=base（接线锚）')
  ok(index.includes('data-testid="ticket-refs"'), 'F5: 背景引用行组契约锚在场')
  ok(/onOpenFile=\{\(p, m\) => setFileViewer\(\{ ticketId: detail\.id, path: p, mode: m \}\)\}/.test(index), 'F6: ChangesTab 文件行回调接线')
}

console.log(`SUMMARY pass=${PASS} skip=0 fail=${FAIL}`)
process.exit(FAIL > 0 ? 1 : 0)
