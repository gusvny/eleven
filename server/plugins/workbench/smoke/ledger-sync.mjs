/**
 * smoke/ledger-sync.mjs — smoke for same-page sync between two instances of the session ledger (t260830-01).
 *
 * Run: node smoke/ledger-sync.mjs (node >= 22.18 native type-stripping, imports .ts directly).
 * node has no DOM: globalThis.localStorage is stubbed before importing the store module —
 * this works only because session-ledger-store.ts does zero IO at module top level (a hard
 * constraint stated in that file's header; this file is its regression lock).
 *
 * Covers (src/client/session-ledger-store.ts):
 *   0. getItem throwing -> lazy init of an empty ledger without throwing (must be tested
 *      before any snapshot read — once a snapshot is cached it no longer goes through getItem).
 *   A. Same-page two-instance sync: instance A persistLedger creates a session -> instance
 *      B's snapshot view sees it in the same frame; reverse B touch -> A's snapshot syncs
 *      (real behavior assertion, not static wiring); persist writes localStorage (the
 *      refresh-and-find semantics are unchanged).
 *   B. Subscriber notification: all subscribers notified; after unsubscribe no more
 *      notifications (full terminal recovery); one subscriber's throwing callback is isolated,
 *      the others still receive this notification (regression case for the "silent
 *      desync" recurrence path).
 *   C. Malformed input (malformed-input discipline, reproduced with stubs, no real browser):
 *      bad JSON / non-array / dirty entries -> parseLedger's existing tolerance (the store's
 *      lazy init uses the same function on the same path, no loosening); setItem throwing ->
 *      the in-memory snapshot still updates, subscribers still notified, nothing thrown up.
 *   D. LEDGER_KEY value unchanged (ledger-key contract regression).
 */

// ---- stub localStorage first (must happen before importing the store) ----
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

const { LEDGER_KEY, subscribeLedger, getLedgerSnapshot, persistLedger, fetchProjectLedger } =
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
  // "instance A" / "instance B" = two consumer views of the same module: same snapshot + separate subscriptions.
  const seenB = []
  const unsubB = subscribeLedger(() => seenB.push(getLedgerSnapshot().length))
  persistLedger(touchEntry([], { id: 'g-1', project: 'suyou', lastOpenedAt: 100 }))
  ok(getLedgerSnapshot().length === 1, '实例 A persist 后快照含新会话')
  ok(seenB.length === 1 && seenB[0] === 1, '实例 B 同帧收到通知且快照同步（同页同步）')
  // Reverse: B-side touch (switching sessions bumps the MRU) -> A's snapshot syncs.
  persistLedger(touchEntry(getLedgerSnapshot(), { id: 'g-1', project: 'suyou', lastOpenedAt: 200 }))
  ok(getLedgerSnapshot()[0].lastOpenedAt === 200, '反向 touch 后快照 MRU 更新')
  ok(seenB.length === 2, '反向变更实例 B 也收到通知')
  // Persist semantics: persist also writes localStorage (refresh-and-find semantics unchanged).
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
  // setItem throwing: in-memory snapshot still updates, subscribers still notified, nothing thrown up.
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
ok(LEDGER_KEY === 'sandbar-workbench-opened-sessions-v1', 'LEDGER_KEY 值不变（账册 key 口径回归）')

// E. UI-5 file faces (t261005-06): file-wins on a real file, cache-stands on an
// absent/empty face — seeded cache entries must NEVER be wiped by a missing file
// face (round-8 regression: an empty 2xx reply used to win and drop them).
{
  const realFetch = globalThis.fetch
  const seeded = [
    { id: 'session-e3f90001-1', project: 'sandbar', cwd: '/x', lastOpenedAt: 100 },
    { id: 'session-e77a0002-2', project: 'sandbar', cwd: '/x', lastOpenedAt: 200 },
  ]
  const restore = async () => { persistLedger(seeded.map(e => ({ ...e }))) }
  try {
    // E1 file-wins: a real non-empty file face replaces the project's entries
    restore()
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ ok: true, entries: [
      { session_id: 'session-beef0003-3', handle: 'beef', last_opened_at: 300 },
    ] }) })
    let r = await fetchProjectLedger('sandbar')
    ok(Array.isArray(r) && r.length === 1 && r[0].id === 'session-beef0003-3' && r[0].project === 'sandbar',
      'E1 file-wins：非空文件面整组替换本项目条目（handle 随带回）')
    ok(getLedgerSnapshot().some(e => e.id === 'session-beef0003-3'), 'E1b 落缓存并广播')
    // E2 empty 2xx reply = absent file face: cache stands (round-8 regression lock)
    restore()
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ ok: true, entries: [] }) })
    r = await fetchProjectLedger('sandbar')
    ok(r === null, 'E2 空文件面=非真源（返回 null）')
    ok(getLedgerSnapshot().some(e => e.id === 'session-e3f90001-1') && getLedgerSnapshot().some(e => e.id === 'session-e77a0002-2'),
      'E2b 空文件面不清洗缓存条目（display-what-you-have，round-8 回归锁）')
    // E3 non-2xx: cache stands
    restore()
    globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({}) })
    r = await fetchProjectLedger('sandbar')
    ok(r === null && getLedgerSnapshot().some(e => e.id === 'session-e3f90001-1'), 'E3 非 2xx=缓存兜底')
    // E4 malformed reply: cache stands, no throw
    restore()
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ entries: 'not-a-list' }) })
    r = await fetchProjectLedger('sandbar')
    ok(r === null && getLedgerSnapshot().some(e => e.id === 'session-e77a0002-2'), 'E4 畸形回包=缓存兜底不抛')
    // E5 fetch throws: cache stands, no throw
    restore()
    globalThis.fetch = async () => { throw new Error('network down') }
    let threw = false
    try { r = await fetchProjectLedger('sandbar') } catch { threw = true }
    ok(!threw && r === null && getLedgerSnapshot().some(e => e.id === 'session-e3f90001-1'), 'E5 fetch 抛异常=缓存兜底不抛')
    // E6 other projects' entries survive a file-wins replace
    restore()
    persistLedger([...getLedgerSnapshot(), { id: 'session-aaaa0004-4', project: 'suyou', cwd: '/y', lastOpenedAt: 1 }])
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ ok: true, entries: [
      { session_id: 'session-beef0003-3', handle: 'beef', last_opened_at: 300 },
    ] }) })
    await fetchProjectLedger('sandbar')
    ok(getLedgerSnapshot().some(e => e.id === 'session-aaaa0004-4') && !getLedgerSnapshot().some(e => e.id === 'session-e3f90001-1'),
      'E6 file-wins 只替换本项目条目，他项目条目保留')
  } finally {
    globalThis.fetch = realFetch
  }
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed > 0 ? 1 : 0)
