/**
 * smoke/sessions.mjs — smoke for the session ledger pure functions of sandbar-workbench
 * (created t260828-02; criterion: project attribution + only sessions the UI actively opened;
 * since t260831-02 the consumer is the top session-entry row and the left-rail "sessions"
 * block has been removed — the ledger semantics are unchanged, this file's criterion is
 * unchanged and stays fully green).
 *
 * Run: node smoke/sessions.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * Covers parseLedger / serializeLedger / touchEntry / removeEntry / pickProjectTabs /
 * isGlobalSessionId / labelOf (src/shared/sessions.ts).
 * Ticket 2 R8 (t260904-05): the top-row-specific groups E/F/G/H/I/J/N and the section-O
 * top-row zero-regression anchors were deleted with pickSwitchTargets/SWITCH_LIMIT/renameEntry;
 * K/M render proxies changed to pickProjectTabs (the project row = the ledger's only render
 * consumer surface):
 *   A. parseLedger tolerance: bad JSON / non-array / dirty entries (missing id, missing
 *      project, non-finite lastOpenedAt) dropped; duplicate ids keep only the first; empty
 *      input -> empty ledger.
 *   B. touchEntry registration: a new entry goes to the MRU head; same-id upsert (updates
 *      project/cwd/time and moves to the head); ticket- prefixed ticket sessions and empty
 *      project are refused; input not mutated.
 *   C. touchEntry cap: over LEDGER_CAP the oldest is evicted (MRU convergence).
 *   D. removeEntry: removes by id, a missing id is harmless.
 *   K. Disk-existing/ticket/subagent criterion: an id not in the ledger never appears no
 *      matter how large its updatedAt (the list data source is the ledger, not full
 *      enumeration — the core criterion of this ticket).
 *   L. serializeLedger <-> parseLedger round-trip consistency.
 *   M. chat- session registration regression (defense line for defect 1 of t260831-04):
 *      a chat-<ts>-<rand4> session passes the full chain "touchEntry -> pickProjectTabs
 *      project-row tab render"; the row survives a ledger round-trip; removeEntry semantics
 *      boundary.
 *   O. seq/title field pass-through (ledger layer): malformed input drops the field without
 *      crashing, the round-trip keeps it (the deep criterion lives in smoke/project-sessions.mjs;
 *      the rename/top-row render anchors are retired).
 */

import {
  isGlobalSessionId,
  labelOf,
  parseLedger,
  serializeLedger,
  touchEntry,
  removeEntry,
  pickProjectTabs,
  LEDGER_CAP,
} from '../src/shared/sessions.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }

/** Build one ledger entry (lastOpenedAt given directly as an ordinal, larger = newer). */
function ent(id, extra = {}) {
  return { id, project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 0, ...extra }
}

section('A parseLedger 容错')
{
  ok(parseLedger(null).length === 0 && parseLedger(undefined).length === 0 && parseLedger('').length === 0, '空入参 → 空册')
  ok(parseLedger('not json{').length === 0, '坏 JSON → 空册')
  ok(parseLedger('{"a":1}').length === 0, '非数组 → 空册')
  ok(parseLedger('[1,"x",null]').length === 0, '非对象条目全脏 → 空册')
  const mixed = parseLedger(JSON.stringify([
    ent('good-1', { lastOpenedAt: 5 }),
    { id: '', project: 'suyou' },                    // empty id
    { id: 'no-proj' },                               // missing project
    { id: 'bad-ts', project: 'suyou', lastOpenedAt: 'x' }, // non-numeric time → kept with 0 fallback
    ent('good-1', { lastOpenedAt: 9 }),              // duplicate id → keep only the first
  ]))
  ok(mixed.length === 2, '脏条目剔除、重复 id 去重')
  ok(mixed[0].id === 'good-1' && mixed[0].lastOpenedAt === 5, '重复 id 留最靠前一份')
  ok(mixed[1].id === 'bad-ts' && mixed[1].lastOpenedAt === 0 && mixed[1].cwd === '', '缺字段兜底（ts→0、cwd→空串）')
}

section('B touchEntry 登记')
{
  let l = []
  l = touchEntry(l, { id: 'chat-a', project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 1 })
  l = touchEntry(l, { id: 'chat-b', project: 'suyou', lastOpenedAt: 2 })
  ok(l.length === 2 && l[0].id === 'chat-b', '新条目入 MRU 头部')
  l = touchEntry(l, { id: 'chat-a', project: 'suyou', cwd: '/repo/suyou', lastOpenedAt: 3 })
  ok(l.length === 2 && l[0].id === 'chat-a' && l[0].lastOpenedAt === 3, '同 id upsert 并提头')
  const before = l
  const after = touchEntry(l, { id: 'ticket-t1', project: 'suyou', lastOpenedAt: 4 })
  ok(after.length === 2 && after.every(e => !e.id.startsWith('ticket-')), 'ticket- 工单会话拒绝入账')
  ok(after !== before && before.length === 2, '不改入参（返回新数组）')
  ok(touchEntry(l, { id: 'chat-x', project: '', lastOpenedAt: 5 }).length === 2, '空 project 拒绝入账')
  ok(touchEntry(null, { id: 'chat-a', project: 'suyou' }).length === 1, 'entries 非数组容错')
  ok(isGlobalSessionId('chat-a') && !isGlobalSessionId('ticket-t1'), 'isGlobalSessionId 判定')
  ok(!isGlobalSessionId('') && !isGlobalSessionId(undefined), 'isGlobalSessionId 空值安全')
}

section('C touchEntry 上限（MRU 收敛）')
{
  let l = []
  for (let i = 0; i < LEDGER_CAP + 3; i++) {
    l = touchEntry(l, { id: `chat-${i}`, project: 'suyou', lastOpenedAt: i + 1 })
  }
  ok(l.length === LEDGER_CAP && LEDGER_CAP === 20, '账册上限 20')
  ok(l[0].id === `chat-${LEDGER_CAP + 2}` && !l.some(e => e.id === 'chat-0'), '最旧的被淘汰、最新的在头部')
  // upsert does not take a new slot: touching an existing id in a full ledger leaves the length unchanged
  l = touchEntry(l, { id: `chat-${LEDGER_CAP + 2}`, project: 'suyou', lastOpenedAt: 999 })
  ok(l.length === LEDGER_CAP && l[0].lastOpenedAt === 999, '满册 upsert 长度不变')
}

section('D removeEntry')
{
  const l = [ent('a', { lastOpenedAt: 1 }), ent('b', { lastOpenedAt: 2 })]
  const r = removeEntry(l, 'a')
  ok(r.length === 1 && r[0].id === 'b' && l.length === 2, '按 id 剔除、不改入参')
  ok(removeEntry(l, 'ghost').length === 2, '不存在的 id 无害')
  ok(removeEntry(null, 'a').length === 0, 'entries 非数组容错')
}

section('K 核心口径：列表=账册，不是全量枚举')
{
  // Disk-existing/ticket/subagent sessions are all in the byId map of ctx.sessions.list,
  // but not registered in the ledger -> they never appear (the criterion flip of this
  // ticket relative to t260825-02).
  const l = [ent('chat-mine', { lastOpenedAt: 1, seq: 1 })]
  const byId = {
    'chat-mine': { displayTitle: '我打开过的' },
    'chat-disk-stale': { displayTitle: '磁盘存量' },
    'ticket-t260828-02': { displayTitle: '工单会话' },
    'sub-1': { displayTitle: 'subagent 会话' },
  }
  const tabs = pickProjectTabs(l, { project: 'suyou', byId, current: 'chat-mine' })
  ok(tabs.length === 1 && tabs[0].id === 'chat-mine' && tabs[0].active,
    '未登记的磁盘存量/工单/subagent 会话不出现（项目行 tab 口径）')
}

section('L serializeLedger ↔ parseLedger 往返')
{
  const l = [ent('a', { lastOpenedAt: 2 }), ent('b', { project: 'other', cwd: '/x', lastOpenedAt: 1 })]
  const back = parseLedger(serializeLedger(l))
  ok(back.length === 2 && back[0].id === 'a' && back[1].project === 'other' && back[1].cwd === '/x', '往返一致')
  ok(serializeLedger(undefined) === '[]', 'serialize 非数组容错')
}

section('M chat- 会话入账回归（t260831-04 缺陷①防线）')
{
  // The criterion anchor of defect 1: a chat-<ts>-<rand4> session cast by global-session/open
  // must pass the full chain "touchEntry registration -> pickProjectTabs project-row tab
  // render" — any link that keeps it out of the tab (gate false-kill / filter false-kill)
  // goes red here. The production registration surface is currently the single project suyou.
  const sid = 'chat-20260831-120000-abcd'
  const ledger = touchEntry([], { id: sid, project: 'suyou', cwd: '/Users/xingu/Documents/sandbar', lastOpenedAt: 1, seq: 1 })
  ok(ledger.length === 1 && ledger[0].id === sid, 'chat- 会话入账不被 isGlobalSessionId 门错杀')
  const rows = pickProjectTabs(ledger, { project: 'suyou' })
  ok(rows.length >= 1 && rows[0].id === sid, '账册有货 → 项目行 tab 数 ≥1（缺陷①回归锚）')
  // Defect-3 defense anchor: timeout no longer auto-removes entries — this only locks the
  // removeEntry semantics boundary; "the open chain does not touch the ledger on timeout" is
  // a UI-layer discipline (session-entry.tsx openSession, no automatic call site).
  const l2 = touchEntry([], { id: sid, project: 'suyou', lastOpenedAt: 2 })
  ok(removeEntry(l2, sid).length === 0 && l2.length === 1, 'removeEntry 仅显式路径可用，纯函数语义不变')
  // Round-trip then render again: a chat- entry still renders a row after the ledger goes through localStorage serialization
  const rows2 = pickProjectTabs(parseLedger(serializeLedger(ledger)), { project: 'suyou' })
  ok(rows2.length === 1 && rows2[0].id === sid, '账册往返后 tab 仍在（持久化不丢入账）')
}

section('O seq/title 字段透传（记账层，第 3 面①：项目内登记序号，关闭不回收）')
{
  // touchEntry carrying seq + upsert updates + malformed field dropping + round-trip persistence.
  // The deep criterion (backfill/continuation/no-recycling chain) lives in smoke/project-sessions.mjs;
  // here we only guard the ledger pass-through against regression.
  const l1 = touchEntry([], { id: 'chat-a', project: 'suyou', lastOpenedAt: 1, seq: 3 })
  ok(l1.length === 1 && l1[0].seq === 3, 'touchEntry 采纳有限数 seq')
  const l2 = touchEntry(l1, { id: 'chat-a', project: 'suyou', lastOpenedAt: 2, seq: 4 })
  ok(l2.length === 1 && l2[0].seq === 4 && l2[0].lastOpenedAt === 2, '同 id upsert 更新 seq')
  const bad = touchEntry([], { id: 'chat-b', project: 'suyou', seq: Number.NaN })
  ok(bad.length === 1 && bad[0].seq === undefined, '畸形 seq（NaN）剔字段不崩')
  const bad2 = parseLedger(JSON.stringify([{ id: 'chat-c', project: 'suyou', lastOpenedAt: 1, seq: 'x' }]))
  ok(bad2.length === 1 && bad2[0].seq === undefined, 'parseLedger 非数字 seq 剔字段')
  const back = parseLedger(serializeLedger(l2))
  ok(back.length === 1 && back[0].seq === 4, 'seq 往返持久化保留')
  // Zero-render-regression anchor (after ticket 2 R8 the only consumer surface is the project row): an entry with seq still produces a tab
  const tabs = pickProjectTabs(l2, { project: 'suyou' })
  ok(tabs.length === 1 && tabs[0].id === 'chat-a' && tabs[0].seq === 4, '带 seq 条目经项目行照常渲染')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
