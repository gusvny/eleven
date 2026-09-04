#!/usr/bin/env node
/**
 * sc_project_sessions_ledger_journey.mjs —— t260904-01 面①：项目会话区账册状态旅程（灰盒 L3）。
 *
 * 用户故事：一个多项目用户（sandbar + suyou 两项目注册表）从旧版本插件升级到
 * 面①版本——浏览器 localStorage 里已有顶部行时代的旧账册（无 seq）。升级后：
 * 每个 tab 应获得稳定编号（拍板 1：关闭不回收、新会话续号、只跳不重），项目内
 * 会话行与顶部行（260904 过渡口径）**消费同一账册互不破坏**，账册/计数器被外部
 * 篡改或版本残留时不撞号、不崩、不丢条目。本场景把这条状态旅程连成链：任何
 * 一步的状态转移损坏都会被下一步放大暴露——与 developer 随票 smoke（单点纯函数
 * 断言+源文本锚）步骤级共享前置、intent 级不同（旅程连续转移 × 两消费面交叉 ×
 * 跨键不一致对抗）。
 *
 * 灰盒锚点（理解深、绑定浅）：断言只落在用户可感/可观测面——「项目 X 的 tab
 * 编号集合」「账册 JSON 内容」「active 高亮集合」「缺号不显示」；不锚内部实现
 * 细度（数组内部结构、私有函数、偶然顺序）。
 *
 * 契约依赖（缺任一 = 面①未兑现，S0 红且点名——报错精确说哪个锚缺失）：
 *   - 既有公开面（src/shared/sessions.ts 现导出）：parseLedger / serializeLedger /
 *     touchEntry / removeEntry / pickSwitchTargets / LEDGER_CAP；
 *   - 本票新增公开面：pickProjectTabs / backfillProjectSeqs / nextProjectSeq +
 *     OpenedEntry.seq 字段（tab 数字=seq，渲染编号数据源）。
 *   - 行为契约（本场景真正守护的，函数注释公开承诺）：nextProjectSeq =
 *     max(计数器, 该项目账册现存最大 seq) + 1，只跳不重；计数器非有限数/负数按 0；
 *     gen1 起 max 号域扩展含可选 closed（「最近关闭」内该项目最大——关掉的号
 *     不重发、重开不撞号；缺省=旧口径兼容）；backfill 幂等、不覆写已有 seq、
 *     项目内 seq 互异；缺号/坏号条目不显示 tab。
 *   - 调用签名以 implement 段代码真源为准：nextProjectSeq(entries, project,
 *     counterMax?, closed?)——与 create_plan 方案 evidence 声明的 (counters, entries,
 *     project) 参数序不同（语义等价，分歧已上报本票结果文件）；若后续重构签名，
 *     本场景按行为契约同步调用形态，断言面不变。
 *   - 不锚的未承诺面：计数器 JSON 的非对象形态容错（client 侧 IO 层义务）。
 *
 * 人工走查遗留（node 无 DOM，不可冒烟，见结果文件故障面清单）：确认框
 * 点取消不关、正方形形态、折叠同隐、列表底部弹层不被滚动容器裁剪、切 tab
 * 后高亮随 current 迁移的视觉效果。
 *
 * 直跑：node integration/t260904-01/sc_project_sessions_ledger_journey.mjs
 * （node ≥22.18 原生 type-stripping，直接 import .ts；cwd 无关，相对 import
 * 基于 import.meta.url。纯内存零 IO，不写仓库、零端口、零 3099、零网络。）
 * Exit contract：末行 SUMMARY pass=N fail=M；exit 1 iff fail>0。
 */
import { deepStrictEqual } from 'node:assert/strict'
import * as S from '../../server/dsh/workbench/src/shared/sessions.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
function same(a, b, label) {
  try { deepStrictEqual(a, b); ok(true, label) }
  catch { ok(false, `${label}（期望 ${JSON.stringify(b)}，实得 ${JSON.stringify(a)}）`) }
}

/* ── S0 契约锚自检：面①公开导出全部在场，缺哪个点名哪个 ── */
section('S0 契约锚自检（面①导出面兑现）')
{
  const FUNCS = ['parseLedger', 'serializeLedger', 'touchEntry', 'removeEntry',
    'pickSwitchTargets', 'pickProjectTabs', 'backfillProjectSeqs', 'nextProjectSeq']
  const missing = FUNCS.filter(n => typeof S[n] !== 'function')
  ok(missing.length === 0,
    missing.length === 0 ? '8 个契约函数导出在场'
      : `面①导出面未兑现，缺失锚：${missing.join(', ')}（实现未落地或命名偏离方案 D1/D2 定稿）`)
  ok(typeof S.LEDGER_CAP === 'number' && S.LEDGER_CAP >= 1, `LEDGER_CAP 在场（=${S.LEDGER_CAP}）`)
  if (failed > 0) {
    console.log(`SUMMARY pass=${passed} fail=${failed}（契约锚缺失，后续段无意义，终止）`)
    process.exit(1)
  }
}

/* 造账册条目 helper（lastOpenedAt 用序数，越大越新）。 */
function ent(id, project, ts, extra = {}) {
  return { id, project, cwd: `/repo/${project}`, lastOpenedAt: ts, ...extra }
}
/* 五条基础账册：sandbar 三条（登记序 b→c→a，lastOpenedAt 10/20/30）+ suyou 两条。 */
function baseLedger() {
  return S.backfillProjectSeqs(S.parseLedger(JSON.stringify([
    ent('chat-a', 'sandbar', 30), ent('chat-b', 'sandbar', 10, { title: '我的命名' }),
    ent('chat-c', 'sandbar', 20), ent('chat-d', 'suyou', 5), ent('chat-e', 'suyou', 15),
  ])))
}

/* ── J1 存量升级迁移：顶部行时代旧账册（无 seq）→ 项目内独立编号 ── */
section('J1 存量升级迁移（旧账册 → 稳定编号）')
{
  const raw = JSON.stringify([
    ent('chat-a', 'sandbar', 30), ent('chat-b', 'sandbar', 10, { title: '我的命名' }),
    ent('chat-c', 'sandbar', 20), ent('chat-d', 'suyou', 5), ent('chat-e', 'suyou', 15),
  ])
  const entries = S.parseLedger(raw)
  const before = JSON.stringify(entries)
  const filled = S.backfillProjectSeqs(entries)

  ok(JSON.stringify(entries) === before, 'backfill 不改入参（纯函数契约）')
  const byId = Object.fromEntries(filled.map(e => [e.id, e]))
  ok(byId['chat-b'].seq === 1 && byId['chat-c'].seq === 2 && byId['chat-a'].seq === 3,
    `sandbar 组按登记序（lastOpenedAt 升序）补号 1..3（10→1, 20→2, 30→3）`)
  ok(byId['chat-d'].seq === 1 && byId['chat-e'].seq === 2,
    'suyou 组独立从 1 起号（跨项目不串号）')
  ok(byId['chat-b'].title === '我的命名', 'backfill 不吞既有 title')
  same(S.backfillProjectSeqs(filled), filled, 'backfill 幂等（二跑 no-op）')
  same(S.parseLedger(S.serializeLedger(filled)), filled,
    '编号持久化：serialize→parse 往返 seq 不丢（刷新/重启后编号仍在）')
}

/* ── J2 编号生命周期：新建登记 → 关闭不回收 → 新建续号 → 重开保号 ── */
section('J2 编号生命周期（拍板 1：不回收、续号、重开保号）')
{
  let ledger = baseLedger()

  // 新建分配链（handleNew 语义）：nextProjectSeq → touchEntry 带 seq 落账
  const n1 = S.nextProjectSeq(ledger, 'sandbar')
  ok(n1 === 4, `无计数器时按账册现存最大续号（3+1=4，实得 ${n1}）`)
  ledger = S.touchEntry(ledger, ent('chat-n1', 'sandbar', 99, { seq: n1 }))
  ok(ledger.find(e => e.id === 'chat-n1')?.seq === 4, '新建登记 seq 落账（tab 数字数据源）')

  // 关 2 号（chat-c）：其余保号
  const closed = S.removeEntry(ledger, 'chat-c')
  same(closed.filter(e => e.project === 'sandbar').map(e => e.seq).sort((a, b) => a - b),
    [1, 3, 4], '关 2 号后余 tab 保留原号（不回收、不重排）')

  // 再新建：续 5（不填补空号 2）
  const n2 = S.nextProjectSeq(closed, 'sandbar')
  ok(n2 === 5, `关闭后新会话续号 5 而非回收 2（实得 ${n2}）`)

  // 重开 2 号（touchEntry 带原 seq 重登——方案 D1「同 title 处理，稳定身份」）
  ledger = S.touchEntry(closed, ent('chat-c', 'sandbar', 40, { seq: 2, title: '我的命名' }))
  const again = ledger.find(e => e.id === 'chat-c')
  ok(again?.seq === 2 && again?.title === '我的命名', '重开保号 2 且 title 不丢（肌肉记忆不乱）')

  // 关闭不碰计数器：计数器值（client 侧持有，此处直喂）不被关闭动作回退
  ok(S.nextProjectSeq(ledger, 'sandbar', 5) === 6,
    '计数器=5 时续 6（关闭动作不回退计数器）')
  ok(S.nextProjectSeq(S.removeEntry(ledger, 'chat-c'), 'sandbar') === 5,
    '再关 2 号且不带计数器 → 按账册兜底续 5（仍不回收 2）')
}

/* ── J3 两消费面共存：项目行 × 顶部行同一账册交叉消费 ── */
section('J3 两消费面共存（项目行过滤口径 × 顶部行 260904 混排口径）')
{
  const ledger = baseLedger()
  const byId = { 'chat-a': { displayTitle: '显示名A' } }   // 其余条目 byId 缺失（磁盘清理残留形态）

  // 项目行（pickProjectTabs）：本项目过滤 + seq 升序 + title 三级兜底 + active 唯一
  const tabs = S.pickProjectTabs(ledger, { project: 'sandbar', current: 'chat-a', byId })
  same(tabs.map(t => t.seq), [1, 2, 3], 'sandbar 行 tab 按 seq 升序（1,2,3）')
  same(tabs.map(t => t.id), ['chat-b', 'chat-c', 'chat-a'], '行内 id 序=编号序')
  ok(tabs.filter(t => t.active).length === 1 && tabs.find(t => t.active)?.id === 'chat-a',
    'current 命中本项目 → 恰一 tab 高亮（唯一）')
  const tA = tabs.find(t => t.id === 'chat-a')
  ok(tA?.title === '显示名A', 'title 兜底：byId displayTitle 次于自定义、优于 id')
  ok(!tabs.some(t => t.id.startsWith('ticket-')), '工单会话不进项目行（纵深防御）')
  ok(!tabs.some(t => t.id === 'chat-d' || t.id === 'chat-e'), '他项目条目不进本项目行')

  // 他项目 current / 工单 current：本项目全不亮
  ok(S.pickProjectTabs(ledger, { project: 'sandbar', current: 'chat-d', byId }).every(t => !t.active),
    'current 属他项目 → 本项目 tab 全不亮')
  ok(S.pickProjectTabs(ledger, { project: 'sandbar', current: 'ticket-t9', byId }).every(t => !t.active),
    'current 是工单会话 → 全不亮')

  // 顶部行（pickSwitchTargets）：260904 口径冻结——跨项目混排 ≤5 + current 保底
  const top = S.pickSwitchTargets(ledger, { current: 'chat-a', byId })
  const projs = new Set(top.map(t => ledger.find(e => e.id === t.id)?.project))
  ok(projs.has('sandbar') && projs.has('suyou'),
    '顶部行仍跨项目混排（260904 过渡口径，本票不得改动）')
  ok(top.length <= 5, `顶部行 ≤5（实得 ${top.length}）`)
  ok(top.filter(t => t.active).length === 1, '顶部行 active 恰一')
  // current 保底：chat-e（suyou，MRU 第 3）截断到前 2 之外 → 替换最末一名入选
  const top2 = S.pickSwitchTargets(ledger, { current: 'chat-e', byId, limit: 2 })
  ok(top2.some(t => t.id === 'chat-e'),
    '顶部行 current 保底入选语义不变（截断时替换最末一名）')
}

/* ── J4 对抗注入：计数器/账册跨键不一致、撞号、畸形 seq、CAP 挤压 ── */
section('J4 对抗注入（跨键不一致与污染）')
{
  const base = baseLedger()

  // 计数器孤高（手改/版本残留>现存最大）：跳号不重号（「不回收」推论）
  ok(S.nextProjectSeq(base, 'sandbar', 9) === 10, '计数器孤高 9 → 续 10（跳号，绝不重发 4）')
  // 计数器偏低/丢失/畸形：账册现存最大兜底防撞
  ok(S.nextProjectSeq(base, 'sandbar', 2) === 4, '计数器偏低 2 → 按现存最大兜底续 4（防撞号）')
  ok(S.nextProjectSeq(base, 'sandbar') === 4, '计数器丢失 → 兜底续 4')
  ok(S.nextProjectSeq(base, 'sandbar', -5) === 4, '计数器负数 → 按 0 兜底续 4')
  ok(S.nextProjectSeq(base, 'sandbar', '9') === 4, '计数器字符串 → 非有限数按 0 续 4')
  // 跨项目条目不干扰本项目计算（他项目高号在手改下也不串）
  const polluted = base.map(e => e.project === 'suyou' ? { ...e, seq: 99 } : e)
  ok(S.nextProjectSeq(polluted, 'sandbar') === 4, '他项目条目 seq=99 不干扰本项目（仍 4）')

  // 账册手改注入撞号（两条同 seq）：渲染推导不崩、active 仍唯一
  const collide = baseLedger()
  collide.find(e => e.id === 'chat-c').seq = 1         // 手改制造 1,1,3
  const tabsC = S.pickProjectTabs(collide, { project: 'sandbar', current: 'chat-a', byId: {} })
  ok(Array.isArray(tabsC) && tabsC.length === 3, '撞号账册不崩（3 条照常渲染）')
  ok(tabsC.filter(t => t.active).length <= 1, '撞号下 active 仍至多一')

  // 畸形 seq（手改 localStorage 写字符串/1e999→Infinity）：parseLedger 剔字段不剔条目
  const dirty = S.parseLedger(JSON.stringify([
    ent('chat-b', 'sandbar', 10, { seq: '7' }),        // 字符串
    ent('chat-c', 'sandbar', 20, { seq: 1e999 }),      // JSON.parse 得 Infinity
    ent('chat-a', 'sandbar', 30, { seq: 2 }),
  ]))
  ok(dirty.length === 3, '畸形 seq 不整条剔除（条目仍在）')
  ok(dirty.every(e => e.seq === undefined || (typeof e.seq === 'number' && Number.isFinite(e.seq))),
    'parseLedger 只留有限数 seq（字符串/Infinity 剔字段）')
  ok(S.pickProjectTabs(dirty, { project: 'sandbar', current: 'chat-b', byId: {} }).length === 1,
    '缺号/坏号条目不显示 tab（无数字 tab 无意义，只渲染合法 seq 的 chat-a）')
  // backfill 补号语义不变式：已有 seq 不被覆写 + 项目内互异（不断言具体重排口径）
  const refill = S.backfillProjectSeqs(dirty)
  const rSeqs = refill.map(e => e.seq)
  ok(refill.find(e => e.id === 'chat-a')?.seq === 2, 'backfill 不覆写已有合法 seq（chat-a 保 2）')
  ok(new Set(rSeqs).size === rSeqs.length && rSeqs.every(s => s >= 1),
    `补号后项目内 seq 互异不撞（实得 ${JSON.stringify(rSeqs.sort((a, b) => a - b))}）`)
  ok(S.pickProjectTabs(refill, { project: 'sandbar', current: 'chat-b', byId: {} }).length === 3,
    '补号后 3 条全部可显示')

  // LEDGER_CAP 挤压：淘汰高号侧后续号不回退、不重号
  let ledger = []
  for (let i = 1; i <= 25; i++) ledger = S.touchEntry(ledger, ent(`chat-c${i}`, 'sandbar', i, { seq: i }))
  ok(ledger.length === S.LEDGER_CAP, `超 CAP 淘汰至 ${S.LEDGER_CAP}（实得 ${ledger.length}）`)
  const maxLeft = Math.max(...ledger.map(e => e.seq))
  ok(S.nextProjectSeq(ledger, 'sandbar', 23) === maxLeft + 1,
    `CAP 淘汰后计数器(23)落后于现存最大(${maxLeft}) → 取 max 续 ${maxLeft + 1}（不重号）`)
  ok(S.nextProjectSeq(ledger, 'sandbar') === maxLeft + 1,
    `计数器也丢时按淘汰后现存最大兜底（续 ${maxLeft + 1}）`)

  // BO-1（gen1 契约扩展，验收走查点名随动）：关掉的是最大号且计数器丢失 →
  // closed 号域兜底不重发——重发后重开原号条目=撞号，破坏拍板 1「稳定身份」
  const afterCloseMax = S.removeEntry(base, 'chat-a')       // 关 3 号：账册现存最大=2
  const closedMax = [ent('chat-a', 'sandbar', 30, { seq: 3 })]
  ok(S.nextProjectSeq(afterCloseMax, 'sandbar', undefined, closedMax) === 4,
    '关掉最大号 3 且计数器丢失 → closed 号域兜底续 4（不重发 3）')
  ok(S.nextProjectSeq(afterCloseMax, 'sandbar', undefined, undefined) === 3,
    '不传 closed（缺省旧口径）仍按账册续 3——兼容面：既有断言语义不变')
  ok(S.nextProjectSeq(afterCloseMax, 'sandbar', 1, closedMax) === 4,
    '计数器落后(1) + closed 含最大号(3) → 三域取最大续 4')
  ok(S.nextProjectSeq(afterCloseMax, 'sandbar', 9, closedMax) === 10,
    '计数器孤高(9) 仍主导 → 续 10（closed 域只兜底不封顶）')
  ok(S.nextProjectSeq(afterCloseMax, 'sandbar', undefined,
      [ent('chat-x', 'suyou', 30, { seq: 99 })]) === 3,
    '他项目已关条目(seq 99)不进本项目号域（closed 域按项目过滤）')
  // 旅程闭环：重开已关 3 号保号、号域随之干净——BO-1 修的正是这一步的撞号面
  const reopened = S.touchEntry(afterCloseMax, ent('chat-a', 'sandbar', 40, { seq: 3 }))
  ok(reopened.find(e => e.id === 'chat-a')?.seq === 3,
    '重开已关 3 号保号归位（与域内号不撞）')
  ok(S.nextProjectSeq(reopened, 'sandbar', undefined, closedMax.filter(e => e.id !== 'chat-a')) === 4,
    '重开后（closed 已移除该条）号域干净 → 续 4')
}

console.log(`\nSUMMARY pass=${passed} fail=${failed}`)
process.exit(failed === 0 ? 0 : 1)
