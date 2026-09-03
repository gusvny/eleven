/**
 * smoke/sessions.mjs —— suyou-workbench 会话记账层纯函数冒烟（t260828-02 建，
 * 口径：项目归属 + 只列 UI 主动打开的会话；t260831-02 起消费方=顶部会话入口行，
 * 左栏「会话」区块已移除——记账层语义零改动，本文件口径不变照常全绿）。
 *
 * 直跑：node smoke/sessions.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * 覆盖 parseLedger / serializeLedger / touchEntry / removeEntry / pickSwitchTargets /
 * isGlobalSessionId / labelOf（src/shared/sessions.ts）：
 *   A. parseLedger 容错：坏 JSON / 非数组 / 脏条目（缺 id、缺 project、lastOpenedAt
 *      非有限数）剔除；同 id 重复只留首份；空入参 → 空册。
 *   B. touchEntry 登记：新条目入 MRU 头部；同 id upsert（更新 project/cwd/时间并提头）；
 *      ticket- 前缀工单会话与空 project 拒绝入账；不改入参。
 *   C. touchEntry 上限：超 LEDGER_CAP 淘汰最旧（MRU 收敛）。
 *   D. removeEntry：按 id 剔除，不存在的 id 无害。
 *   E. pickSwitchTargets 项目过滤：只列当前项目的账册条目，他项目不进。
 *   F. MRU 排序 + 截断：lastOpenedAt 降序，7 个 → 前 5（t260831-06：打开路径
 *      不再更新 lastOpenedAt——见 handleOpen，排序语义本身不变，本段照旧全绿）。
 *   G. active 标记命中 current；无 current 全不亮。
 *   H. current 保底入选：通过过滤但排在 limit 名外 → 替换最末一名；
 *      current 是工单会话/他项目会话（不通过过滤）→ 不保底。
 *   I. 标题兜底：byId 有 displayTitle 用之，账册有 list 无（磁盘已删残留）兜底 id 不崩。
 *   J. 边界：project 空串 / limit<=0 / 账册非数组 → 空数组不抛错。
 *   K. 磁盘存量/工单/subagent 口径：账册里没有的 id 再大 updatedAt 也不出现
 *     （列表数据源=账册而非全量枚举——本单的核心口径）。
 *   L. serializeLedger ↔ parseLedger 往返一致。
 *   M. chat- 会话入账回归（t260831-04 缺陷①防线）：chat-<ts>-<rand4> 走通
 *      「入账 → 渲染 ≥1 行」全链；账册往返后行仍在；removeEntry 语义边界。
 *   N. tab 重命名 + title（t260831-06）：renameEntry 正常/trim/空串清除/未知
 *      id/不改入参；title 畸形输入剔字段不崩；touchEntry 带 title；改名→关闭
 *      →重开全链 title 保留；title 往返持久化。
 */

import {
  isGlobalSessionId,
  labelOf,
  parseLedger,
  serializeLedger,
  touchEntry,
  removeEntry,
  renameEntry,
  pickSwitchTargets,
  SWITCH_LIMIT,
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

section('E pickSwitchTargets 项目过滤')
{
  const l = [
    ent('chat-suyou-1', { lastOpenedAt: 3 }),
    ent('chat-other', { project: 'other', cwd: '/repo/other', lastOpenedAt: 9 }),
    ent('chat-suyou-2', { lastOpenedAt: 1 }),
  ]
  const r = pickSwitchTargets(l, { project: 'suyou' })
  ok(r.length === 2 && r.every(t => t.id !== 'chat-other'), '只列当前项目，他项目（哪怕更新）不进')
  const r2 = pickSwitchTargets(l, { project: 'other' })
  ok(r2.length === 1 && r2[0].id === 'chat-other' && r2[0].cwd === '/repo/other', '切项目列表随项目走')
}

section('F MRU 排序 + 截断')
{
  const l = ['a', 'b', 'c'].map((id, i) => ent(id, { lastOpenedAt: i + 1 }))
  const r = pickSwitchTargets(l, { project: 'suyou' })
  ok(r.map(t => t.id).join(',') === 'c,b,a', 'lastOpenedAt 降序')
  const big = Array.from({ length: 7 }, (_, i) => ent(`s${i}`, { lastOpenedAt: i + 1 }))
  const r2 = pickSwitchTargets(big, { project: 'suyou' })
  ok(r2.length === SWITCH_LIMIT && SWITCH_LIMIT === 5, '上限 5')
  ok(r2.map(t => t.id).join(',') === 's6,s5,s4,s3,s2', '留最新 5 个')
}

section('G active 标记命中 current')
{
  const l = [ent('a', { lastOpenedAt: 2 }), ent('b', { lastOpenedAt: 1 })]
  const r = pickSwitchTargets(l, { project: 'suyou', current: 'b' })
  ok(r.find(t => t.id === 'b')?.active === true && r.find(t => t.id === 'a')?.active === false, 'active 命中')
  ok(pickSwitchTargets(l, { project: 'suyou' }).every(t => t.active === false), '无 current 时全不亮')
}

section('H current 保底入选')
{
  // current 通过过滤但 lastOpenedAt 第 7（在 5 名外）→ 替换最末一名
  const l = Array.from({ length: 6 }, (_, i) => ent(`s${i}`, { lastOpenedAt: 100 + i }))
    .concat([ent('cur', { lastOpenedAt: 1 })])
  const r = pickSwitchTargets(l, { project: 'suyou', current: 'cur' })
  ok(r.length === 5 && r.some(t => t.id === 'cur' && t.active), 'current 掉出前 5 仍保底在列')
  ok(!r.some(t => t.id === 's0'), '被替换的是最末一名（s0）')
  // current 是工单会话/他项目会话（不在账册过滤集内）→ 不保底，正常截断
  const l2 = Array.from({ length: 7 }, (_, i) => ent(`g${i}`, { lastOpenedAt: i + 1 }))
  const r2 = pickSwitchTargets(l2, { project: 'suyou', current: 'ticket-t9' })
  ok(r2.length === 5 && !r2.some(t => t.id === 'ticket-t9'), 'current 是工单会话时不保底')
  const r3 = pickSwitchTargets(l2, { project: 'suyou', current: 'other-proj-cur' })
  ok(r3.length === 5 && r3.every(t => t.id !== 'other-proj-cur'), 'current 是他项目会话时不保底')
}

section('I 标题兜底')
{
  const l = [ent('chat-a', { lastOpenedAt: 2 }), ent('chat-gone', { lastOpenedAt: 1 })]
  const byId = { 'chat-a': { displayTitle: '我的会话' } }
  const r = pickSwitchTargets(l, { project: 'suyou', byId })
  ok(r[0].title === '我的会话', 'displayTitle 优先')
  ok(r[1].title === 'chat-gone', '账册有 list 无（磁盘已删残留）兜底 id 不崩')
  ok(labelOf({ displayTitle: '' }, 'x') === 'x' && labelOf(undefined, 'x') === 'x', 'labelOf 空值兜底')
}

section('J 边界：缺字段 / 非法入参不抛错')
{
  ok(pickSwitchTargets(undefined, { project: 'suyou' }).length === 0, 'entries undefined')
  ok(pickSwitchTargets([ent('a')], { project: '' }).length === 0, 'project 空串（未选项目）→ 空列表')
  ok(pickSwitchTargets([ent('a')], { project: 'suyou', limit: 0 }).length === 0, 'limit=0')
  ok(pickSwitchTargets([ent('a')], { project: 'suyou', limit: -1 }).length === 0, 'limit<0')
  ok(pickSwitchTargets([null, ent('a', { lastOpenedAt: 1 })], { project: 'suyou' }).length === 1, '账册脏条目跳过')
  ok(pickSwitchTargets([ent('a'), ent('b', { lastOpenedAt: 1 })], { project: 'suyou' })
    .map(t => t.id).join(',') === 'b,a', 'lastOpenedAt 缺失按 0 排')
}

section('N tab 重命名 + title 字段（t260831-06）')
{
  // renameEntry：正常改名 / 空串清除 / 未知 id 原样 / 不改入参
  let l = [ent('a', { lastOpenedAt: 2 }), ent('b', { lastOpenedAt: 1 })]
  const before = l
  let r = renameEntry(l, 'a', '  我的项目会话  ')
  ok(r[0].title === '我的项目会话', 'renameEntry trim 后采纳')
  ok(r[1] === l[1] && r !== before && before[0].title === undefined, '不改入参（其余条目同引用）')
  ok(renameEntry(l, 'ghost', 'x').every((e, i) => e === l[i]), '未知 id 原样返回')
  ok(renameEntry(null, 'a', 'x').length === 0, 'entries 非数组容错')
  // 空串/纯空白 = 清除自定义名
  r = renameEntry(renameEntry(l, 'a', '临时名'), 'a', '')
  ok(r[0].title === undefined, '空串清除 title（恢复默认显示）')
  r = renameEntry(l, 'a', '   ')
  ok(r[0].title === undefined, '纯空白同样清除')
  // pickSwitchTargets：title 非空优先，空串/缺失走 displayTitle 兜底链
  const byId = { a: { displayTitle: '自动标题' }, b: { displayTitle: 'B 标题' } }
  l = [ent('a', { title: '自定义名' }), ent('b', { title: '' })]
  const rows = pickSwitchTargets(l, { project: 'suyou', byId })
  ok(rows[0].title === '自定义名', '自定义 title 优先于 displayTitle')
  ok(rows[1].title === 'B 标题', '空串 title 走 displayTitle 兜底')
  // 畸形输入：parseLedger title 非字符串 → 剔字段不崩
  const weird = parseLedger(JSON.stringify([
    ent('w1', { title: 42 }),
    ent('w2', { title: { x: 1 } }),
    ent('w3', { title: null }),
    ent('w4', { title: '合法' }),
  ]))
  ok(weird.length === 4 && weird[0].title === undefined && weird[1].title === undefined
    && weird[2].title === undefined && weird[3].title === '合法', 'title 畸形输入剔字段不崩')
  // touchEntry 带 title：登记与重登（↺ 恢复路径）不丢自定义名
  const t1 = touchEntry([], { id: 'a', project: 'suyou', title: '命名会话' })
  ok(t1[0].title === '命名会话', 'touchEntry 采纳 title')
  ok(touchEntry([], { id: 'a', project: 'suyou', title: 42 })[0].title === undefined, 'touchEntry title 非字符串容错')
  // 重命名 → 关闭（removeEntry）→ ↺ 重登（touchEntry 带 title）全链 title 保留
  const closed = removeEntry(renameEntry(t1, 'a', '新名字'), 'a')
  const restored = touchEntry([], { id: 'a', project: 'suyou', cwd: '/x', title: '新名字', lastOpenedAt: 1 })
  ok(closed.length === 0 && restored[0].title === '新名字', '改名→关闭→重开链 title 保留（↺ 通路）')
  // serializeLedger ↔ parseLedger 带 title 往返
  const back = parseLedger(serializeLedger([ent('a', { title: '持久名' })]))
  ok(back[0].title === '持久名', 'title 往返持久化保留')
}

section('K 核心口径：列表=账册，不是全量枚举')
{
  // 磁盘存量/工单/subagent 会话在 ctx.sessions.list 的 byId 里都在，
  // 但没登记进账册 → 一律不出现（本单相对 t260825-02 的口径翻转点）
  const l = [ent('chat-mine', { lastOpenedAt: 1 })]
  const byId = {
    'chat-mine': { displayTitle: '我打开过的' },
    'chat-disk-stale': { displayTitle: '磁盘存量' },
    'ticket-t260828-02': { displayTitle: '工单会话' },
    'sub-1': { displayTitle: 'subagent 会话' },
  }
  const r = pickSwitchTargets(l, { project: 'suyou', byId, current: 'chat-mine' })
  ok(r.length === 1 && r[0].id === 'chat-mine' && r[0].active, '未登记的磁盘存量/工单/subagent 会话不出现')
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
  // 「touchEntry 入账 → pickSwitchTargets 渲染 ≥1 行」全链——任何一环把它
  // 挡在列表外（门错杀/过滤错杀）都在这里红。生产注册表现状=单项目 suyou。
  const sid = 'chat-20260831-120000-abcd'
  const ledger = touchEntry([], { id: sid, project: 'suyou', cwd: '/Users/user/Documents/suyou', lastOpenedAt: 1 })
  ok(ledger.length === 1 && ledger[0].id === sid, 'chat- 会话入账不被 isGlobalSessionId 门错杀')
  const rows = pickSwitchTargets(ledger, { project: 'suyou' })
  ok(rows.length >= 1 && rows[0].id === sid, '账册有货 + projectKey 命中 → MRU 行数 ≥1（缺陷①回归锚）')
  // 缺陷③防线锚：超时不再自动 removeEntry——此处仅固化 removeEntry 语义边界，
  // 「打开链超时不动账册」属 UI 层纪律（session-entry.tsx openSession，无自动调用点）。
  const l2 = touchEntry([], { id: sid, project: 'suyou', lastOpenedAt: 2 })
  ok(removeEntry(l2, sid).length === 0 && l2.length === 1, 'removeEntry 仅显式路径可用，纯函数语义不变')
  // 往返再渲染：账册经 localStorage 序列化往返后 chat- 条目仍能渲染出行
  const rows2 = pickSwitchTargets(parseLedger(serializeLedger(ledger)), { project: 'suyou' })
  ok(rows2.length === 1 && rows2[0].id === sid, '账册往返后行仍在（持久化不丢入账）')
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
