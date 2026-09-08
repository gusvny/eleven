/**
 * smoke/sessions.mjs —— sandbar-workbench 会话记账层纯函数冒烟（t260828-02 建，
 * 口径：项目归属 + 只列 UI 主动打开的会话；t260831-02 起消费方=顶部会话入口行，
 * 左栏「会话」区块已移除——记账层语义零改动，本文件口径不变照常全绿）。
 *
 * 直跑：node smoke/sessions.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖 parseLedger / serializeLedger / touchEntry / removeEntry / pickProjectTabs /
 * isGlobalSessionId / labelOf（src/shared/sessions.ts）。
 * 票② R8（t260904-05）：顶部行专属组 E/F/G/H/I/J/N 与 O 段顶部行零回归锚随
 * pickSwitchTargets/SWITCH_LIMIT/renameEntry 退役删除；K/M 渲染代理改
 * pickProjectTabs（项目行=账册唯一渲染消费面）：
 *   A. parseLedger 容错：坏 JSON / 非数组 / 脏条目（缺 id、缺 project、lastOpenedAt
 *      非有限数）剔除；同 id 重复只留首份；空入参 → 空册。
 *   B. touchEntry 登记：新条目入 MRU 头部；同 id upsert（更新 project/cwd/时间并提头）；
 *      ticket- 前缀工单会话与空 project 拒绝入账；不改入参。
 *   C. touchEntry 上限：超 LEDGER_CAP 淘汰最旧（MRU 收敛）。
 *   D. removeEntry：按 id 剔除，不存在的 id 无害。
 *   K. 磁盘存量/工单/subagent 口径：账册里没有的 id 再大 updatedAt 也不出现
 *     （列表数据源=账册而非全量枚举——本单的核心口径）。
 *   L. serializeLedger ↔ parseLedger 往返一致。
 *   M. chat- 会话入账回归（t260831-04 缺陷①防线）：chat-<ts>-<rand4> 走通
 *      「入账 → 渲染 ≥1 行」全链；账册往返后行仍在；removeEntry 语义边界。
 *   O. seq/title 字段透传（记账层）：畸形输入剔字段不崩、往返持久化保留
 *      （深度口径在 smoke/project-sessions.mjs；重命名/顶部行渲染锚已退役）。
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

/** 造一条账册条目（lastOpenedAt 直接给序数，越大越新）。 */
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
    { id: '', project: 'suyou' },                    // 空 id
    { id: 'no-proj' },                               // 缺 project
    { id: 'bad-ts', project: 'suyou', lastOpenedAt: 'x' }, // 时间非数 → 0 兜底保留
    ent('good-1', { lastOpenedAt: 9 }),              // 重复 id → 只留首份
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
  // upsert 不占新名额：满册时 touch 已有 id，长度不变
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
  // 磁盘存量/工单/subagent 会话在 ctx.sessions.list 的 byId 里都在，
  // 但没登记进账册 → 一律不出现（本单相对 t260825-02 的口径翻转点）
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
  // 缺陷①的口径锚：global-session/open 铸造的 chat-<ts>-<rand4> 会话必须走通
  // 「touchEntry 入账 → pickProjectTabs 项目行 tab 渲染」全链——任何一环把它
  // 挡在 tab 外（门错杀/过滤错杀）都在这里红。生产注册表现状=单项目 suyou。
  const sid = 'chat-20260831-120000-abcd'
  const ledger = touchEntry([], { id: sid, project: 'suyou', cwd: '/Users/user/Documents/sandbar', lastOpenedAt: 1, seq: 1 })
  ok(ledger.length === 1 && ledger[0].id === sid, 'chat- 会话入账不被 isGlobalSessionId 门错杀')
  const rows = pickProjectTabs(ledger, { project: 'suyou' })
  ok(rows.length >= 1 && rows[0].id === sid, '账册有货 → 项目行 tab 数 ≥1（缺陷①回归锚）')
  // 缺陷③防线锚：超时不再自动 removeEntry——此处仅固化 removeEntry 语义边界，
  // 「打开链超时不动账册」属 UI 层纪律（session-entry.tsx openSession，无自动调用点）。
  const l2 = touchEntry([], { id: sid, project: 'suyou', lastOpenedAt: 2 })
  ok(removeEntry(l2, sid).length === 0 && l2.length === 1, 'removeEntry 仅显式路径可用，纯函数语义不变')
  // 往返再渲染：账册经 localStorage 序列化往返后 chat- 条目仍能渲染出行
  const rows2 = pickProjectTabs(parseLedger(serializeLedger(ledger)), { project: 'suyou' })
  ok(rows2.length === 1 && rows2[0].id === sid, '账册往返后 tab 仍在（持久化不丢入账）')
}

section('O seq/title 字段透传（记账层，第 3 面①：项目内登记序号，关闭不回收）')
{
  // touchEntry 带 seq 入账 + upsert 更新 + 畸形剔字段 + 往返持久化。
  // 深度口径（补号/续号/不回收链）在 smoke/project-sessions.mjs，此处只守
  // 记账层透传不回归。
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
  // 渲染零回归锚（票② R8 后唯一消费面=项目行）：带 seq 条目照常出 tab
  const tabs = pickProjectTabs(l2, { project: 'suyou' })
  ok(tabs.length === 1 && tabs[0].id === 'chat-a' && tabs[0].seq === 4, '带 seq 条目经项目行照常渲染')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
