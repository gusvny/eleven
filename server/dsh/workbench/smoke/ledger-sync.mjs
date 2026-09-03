/**
 * smoke/ledger-sync.mjs —— suyou-workbench 会话账册同页双实例同步冒烟（t260830-01）。
 *
 * 直跑：node smoke/ledger-sync.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
 * node 无 DOM，先 stub globalThis.localStorage 再 import store 模块——可行前提是
 * session-ledger-store.ts 模块顶层零 IO（文件头注释的硬约束，本文件即其回归锁）。
 *
 * 覆盖（src/client/session-ledger-store.ts）：
 *   0. getItem 抛异常 → 惰性初始化空册不抛（必须在任何快照读取前测——
 *      快照一旦缓存就不再走 getItem）。
 *   A. 同页双实例同步：实例 A persistLedger 新建会话 → 实例 B 视角快照同帧可见；
 *      反向 B touch → A 快照同步（真实行为断言，非静态接线）；persist 落盘
 *      localStorage（刷新找回口径不变）。
 *   B. 订阅通知：多订阅者全量通知；unsubscribe 后不再通知（全终态回收）；
 *      单订阅者回调 throw 被隔离，其它订阅者仍收到本次通知（「静默失同步」
 *      复发路径的回归用例）。
 *   C. 畸形输入（消费外部输入纪律，桩复现不靠真浏览器）：坏 JSON / 非数组 /
 *      脏条目 → parseLedger 既有容错（store 惰性初始化同函数同路径，不放宽）；
 *      setItem 抛异常 → 内存快照仍更新、订阅者仍收到通知、不向上抛。
 *   D. LEDGER_KEY 值不变（账册 key 口径回归）。
 */

// ---- 先 stub localStorage（必须在 import store 之前）----
const backing = new Map()
let failSetItem = false
let failGetItem = false
globalThis.localStorage = {
  getItem(k) {
    if (failGetItem) throw new Error('localStorage getItem 桩异常')
    return backing.has(k) ? backing.get(k) : null
  },
  setItem(k, v) {
    if (failSetItem) throw new Error('localStorage setItem 桩异常')
    backing.set(k, String(v))
  },
  removeItem(k) { backing.delete(k) },
  clear() { backing.clear() },
}

const { LEDGER_KEY, subscribeLedger, getLedgerSnapshot, persistLedger } =
  await import('../src/client/session-ledger-store.ts')
const { touchEntry, parseLedger } = await import('../src/shared/sessions.ts')

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok - ${label}`) }
  else { failed++; console.error(`  FAIL - ${label}`) }
}

console.log('0. getItem 抛异常 → 惰性初始化空册（快照缓存前唯一能走到的路径）')
{
  failGetItem = true
  let threw = false
  let snap = null
  try { snap = getLedgerSnapshot() } catch { threw = true }
  failGetItem = false
  ok(!threw, 'getItem 抛异常 getLedgerSnapshot 不向上抛')
  ok(Array.isArray(snap) && snap.length === 0, 'getItem 抛异常 → 空册')
}

console.log('A. 同页双实例同步')
{
  // 「实例 A」「实例 B」= 同一模块的两个消费方视角：同一快照 + 各自订阅。
  const seenB = []
  const unsubB = subscribeLedger(() => seenB.push(getLedgerSnapshot().length))
  persistLedger(touchEntry([], { id: 'g-1', project: 'suyou', lastOpenedAt: 100 }))
  ok(getLedgerSnapshot().length === 1, '实例 A persist 后快照含新会话')
  ok(seenB.length === 1 && seenB[0] === 1, '实例 B 同帧收到通知且快照同步（同页同步）')
  // 反向：B 侧 touch（切换会话提升 MRU）→ A 视角快照同步。
  persistLedger(touchEntry(getLedgerSnapshot(), { id: 'g-1', project: 'suyou', lastOpenedAt: 200 }))
  ok(getLedgerSnapshot()[0].lastOpenedAt === 200, '反向 touch 后快照 MRU 更新')
  ok(seenB.length === 2, '反向变更实例 B 也收到通知')
  // 落盘语义：persist 同时写 localStorage（刷新找回口径不变）。
  ok(backing.has(LEDGER_KEY) && parseLedger(backing.get(LEDGER_KEY)).length === 1, 'persist 落盘 localStorage（key/格式不变）')
  unsubB()
}

console.log('B. 订阅通知与异常隔离')
{
  const events = []
  const unsub1 = subscribeLedger(() => events.push('s1'))
  const unsub2 = subscribeLedger(() => { throw new Error('订阅者 2 桩异常') })
  const unsub3 = subscribeLedger(() => events.push('s3'))
  persistLedger([])
  ok(events.includes('s1') && events.includes('s3'), '订阅者 2 throw 后订阅者 1/3 仍收到通知（异常隔离）')
  unsub1(); unsub2(); unsub3()
  persistLedger([{ id: 'x', project: 'p', cwd: '', lastOpenedAt: 1 }])
  ok(events.length === 2, 'unsubscribe 后不再收到通知（回收；隔离的 s2 从未计入）')
}

console.log('C. 畸形输入容错（桩复现，不放宽）')
{
  const bad = ['not json{', '{"a":1}', '42', '"str"', 'null']
  ok(bad.every(raw => parseLedger(raw).length === 0), '坏 JSON/非数组 payload → 空册（parseLedger，store 惰性初始化同路径）')
  ok(parseLedger(JSON.stringify([
    { id: '', project: 'p' },
    { id: 'a' },
    { id: 'a', project: 'p' },
    { id: 'b', project: 'p', lastOpenedAt: 'x' },
  ])).map(e => e.id).join(',') === 'a,b', '脏条目剔除 + 同 id 只留首份 + lastOpenedAt 非数置 0')
  // setItem 抛异常：内存快照仍更新、订阅者仍收到通知、不向上抛。
  const notified = []
  const un = subscribeLedger(() => notified.push(1))
  failSetItem = true
  let threw = false
  try { persistLedger([{ id: 'g-2', project: 'suyou', cwd: '', lastOpenedAt: 1 }]) } catch { threw = true }
  failSetItem = false
  ok(!threw, 'setItem 抛异常 persist 不向上抛（丢持久化不丢内存态）')
  ok(getLedgerSnapshot().some(e => e.id === 'g-2'), 'setItem 失败后内存快照仍更新（两实例不分叉）')
  ok(notified.length === 1, 'setItem 失败订阅者仍收到通知')
  un()
}

console.log('D. LEDGER_KEY 口径')
ok(LEDGER_KEY === 'suyou-workbench-opened-sessions-v1', 'LEDGER_KEY 值不变（账册 key 口径回归）')

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed > 0 ? 1 : 0)
