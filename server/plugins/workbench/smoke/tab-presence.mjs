// smoke/tab-presence.mjs — smoke for t260901-15 multi-tab coexistence (tab-presence.ts).
//
// Run: node smoke/tab-presence.mjs (node >= 22.18 native type-stripping, imports .ts directly).
// Every case is stubbed: stub BroadcastChannel bus + stub localStorage (cross-instance storage
// events), injected clock; no network, no 3099, no real external source (malformed-input cases
// are fed entirely from fixed stubs).
//
// Coverage (item by item per the plan's acceptance criteria):
//   A. parseMsg malformed input: non-object / wrong version / missing field / unknown type /
//      wrong field type / over-long → null.
//   B. BroadcastChannel main channel: two tabs see each other in viewersOf; setViewingTicket
//      takes effect immediately; a tab is not in its own viewersOf; bye/stop removes
//      immediately; TTL expiry removes (injected clock).
//   C. Write events: notifyWrite → the peer's onRemoteWrite receives (ticket/op/who);
//      recentRemoteWrite hits inside the window and misses outside it (injected clock);
//      one's own write does not count as remote.
//   D. localStorage fallback channel: with BroadcastChannel absent, two tabs still see each
//      other via storage events + write events are delivered.
//   E. Bad JSON: feeding a non-JSON value straight into the peer's storage → no crash, no callback.
//   F. Terminal cleanup: after stop the peer no longer receives heartbeats/write events
//      (verified by waiting a beat; no callback leaks).

import {
  startTabPresence, parseMsg,
  __setClockForTests, __resetClockForTests,
  HEARTBEAT_MS, PEER_TTL_MS, WRITE_WINDOW_MS,
} from '../src/client/tab-presence.ts'

let passed = 0
let failed = 0
function ok(cond, label) {
  if (cond) { passed++; console.log(`  ok ${label}`) }
  else { failed++; console.log(`  FAIL ${label}`) }
}
function section(t) { console.log(`\n== ${t}`) }
const tick = (ms = 5) => new Promise(r => setTimeout(r, ms))

/* --------------------------------------------------------- stub: BroadcastChannel bus */
const bcRegistry = new Map()
class FakeBC {
  constructor(name) {
    this.name = name; this.closed = false; this.handlers = new Set()
    if (!bcRegistry.has(name)) bcRegistry.set(name, new Set())
    bcRegistry.get(name).add(this)
  }
  postMessage(msg) {
    if (this.closed) return
    for (const other of [...bcRegistry.get(this.name) ?? []]) {
      if (other === this || other.closed) continue
      queueMicrotask(() => { if (!other.closed) for (const h of other.handlers) h({ data: msg }) })
    }
  }
  addEventListener(_t, h) { this.handlers.add(h) }
  removeEventListener(_t, h) { this.handlers.delete(h) }
  close() { this.closed = true; bcRegistry.get(this.name)?.delete(this) }
}

/* --------------------------------------------------------- stub: localStorage (cross-instance events) */
const lsRegistry = new Set()
class FakeLS {
  constructor() { this.m = new Map(); this.handlers = new Set(); lsRegistry.add(this) }
  get length() { return this.m.size }
  key(i) { return [...this.m.keys()][i] ?? null }
  getItem(k) { return this.m.has(k) ? this.m.get(k) : null }
  setItem(k, v) {
    const key = String(k); this.m.set(key, String(v))
    for (const other of lsRegistry) {
      if (other === this) continue
      for (const h of other.handlers) h({ key, newValue: String(v) })
    }
  }
  removeItem(k) {
    this.m.delete(String(k))
    for (const other of lsRegistry) {
      if (other === this) continue
      for (const h of other.handlers) h({ key: String(k), newValue: null })
    }
  }
  addEventListener(_t, h) { this.handlers.add(h) }
  removeEventListener(_t, h) { this.handlers.delete(h) }
}

/* --------------------------------------------------------- stub: document (always visible) */
const fakeDoc = {
  visibilityState: 'visible',
  addEventListener() {}, removeEventListener() {},
}

function installGlobals(withBC) {
  if (withBC) globalThis.BroadcastChannel = FakeBC
  else delete globalThis.BroadcastChannel
  globalThis.localStorage = new FakeLS()
  globalThis.document = fakeDoc
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
}
function uninstallGlobals() {
  delete globalThis.BroadcastChannel
  delete globalThis.localStorage
  delete globalThis.document
  delete globalThis.window
}

/* ---------------------------------------------------------------- A parseMsg malformed input */
section('A parseMsg：五类畸形一律 null')
{
  ok(parseMsg(null) === null, 'null → null')
  ok(parseMsg('not-object') === null, '字符串 → null')
  ok(parseMsg(42) === null, '数字 → null')
  ok(parseMsg({ v: 2, k: 'bye', tab: 'a', ts: 1 }) === null, '版本不对 → null')
  ok(parseMsg({ v: 1, k: 'nope', tab: 'a', ts: 1 }) === null, '未知类型 → null')
  ok(parseMsg({ v: 1, k: 'bye', ts: 1 }) === null, '缺 tab → null')
  ok(parseMsg({ v: 1, k: 'bye', tab: 'a' }) === null, '缺 ts → null')
  ok(parseMsg({ v: 1, k: 'bye', tab: 'a', ts: 'x' }) === null, 'ts 非数字 → null')
  ok(parseMsg({ v: 1, k: 'bye', tab: 'a', ts: NaN }) === null, 'ts NaN → null')
  ok(parseMsg({ v: 1, k: 'presence', tab: 'a', who: 'op-x', ticket: 3, ts: 1 }) === null, 'ticket 类型不对 → null')
  ok(parseMsg({ v: 1, k: 'presence', tab: 'a', who: '', ticket: null, ts: 1 }) === null, '空 who → null')
  ok(parseMsg({ v: 1, k: 'bye', tab: 'x'.repeat(65), ts: 1 }) === null, 'tab 超长 → null')
  ok(parseMsg({ v: 1, k: 'presence', tab: 'a', who: 'op-x', ticket: null, ts: 100 }) !== null, '合法 presence 通过')
  ok(parseMsg({ v: 1, k: 'write', tab: 'a', who: 'op-x', ticket: 't1', op: 'advance', ts: 100 }) !== null, '合法 write 通过')
  ok(parseMsg({ v: 1, k: 'presence', tab: 'a', who: 'op-x', ticket: undefined, ts: 100 }) !== null, 'ticket=undefined 按 null 通过')
}

/* ------------------------------------------------ B BroadcastChannel main channel: mutual visibility */
section('B BroadcastChannel 主通道：双页签互见 / bye 剔除 / TTL 过期')
{
  installGlobals(true)
  let now = 1_000_000
  __setClockForTests(() => now)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  A.setViewingTicket('t13')
  B.setViewingTicket('t11')
  await tick()
  ok(A.viewersOf('t13').length === 0, 'A 看 t13 时自己不出现（A 视角）')
  ok(A.viewersOf('t11').length === 1 && A.viewersOf('t11')[0].who === 'op-B', 'A 看到 B 在看 t11')
  ok(B.viewersOf('t13').length === 1 && B.viewersOf('t13')[0].who === 'op-A', 'B 看到 A 在看 t13')
  ok(B.viewersOf('t99').length === 0, '无人看的工单为空')
  // switch viewed ticket: takes effect immediately
  B.setViewingTicket('t13')
  await tick()
  ok(A.viewersOf('t13').length === 2 - 1 && A.viewersOf('t13')[0].who === 'op-B', 'B 切看 t13 后 A 即时可见')
  B.setViewingTicket(null)
  await tick()
  ok(A.viewersOf('t13').length === 0, 'B 关抽屉（null）后 A 侧即时消失')
  // TTL: push the clock past PEER_TTL_MS (no fresh heartbeat in between — pausing A's beat
  // would need a hand-rolled send after stop, so bye is exercised via stop instead)
  B.setViewingTicket('t11')
  B.stop()
  await tick()
  ok(A.viewersOf('t11').length === 0, 'B stop（bye）后 A 即时剔除')
  // TTL expiry: B is already stopped and A's leftover peers were cleared by bye; use a clock
  // push instead + a C tab that only emits one beat
  const C = startTabPresence('op-C', { tabId: 'tab-C' })
  C.setViewingTicket('t7')
  await tick()
  ok(A.viewersOf('t7').length === 1, 'C 首拍心跳 A 可见')
  now += PEER_TTL_MS + 1000
  ok(A.viewersOf('t7').length === 0, 'TTL 过期后 A 剔除 C（心跳停摆靠 TTL 兜底）')
  C.stop()
  A.stop()
  __resetClockForTests()
  uninstallGlobals()
}

/* ------------------------------------------------------------------ C write events + gate window */
section('C 写事件：送达 / recentRemoteWrite 窗口 / 自身写不算远端')
{
  installGlobals(true)
  let now = 2_000_000
  __setClockForTests(() => now)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  A.setViewingTicket('t13'); B.setViewingTicket('t13')
  await tick()
  const got = []
  const off = B.onRemoteWrite(w => got.push(w))
  A.notifyWrite('t13', 'advance')
  await tick()
  ok(got.length === 1 && got[0].ticket === 't13' && got[0].op === 'advance' && got[0].who === 'op-A',
    'B 收到 A 的 advance 写事件（ticket/op/who 全对）')
  ok(B.recentRemoteWrite('t13') !== undefined && B.recentRemoteWrite('t13').who === 'op-A',
    'B 守门窗口内命中 A 的写')
  ok(A.recentRemoteWrite('t13') === undefined, 'A 自己的写不算远端（自身回环过滤）')
  ok(B.recentRemoteWrite('t99') === undefined, '其它工单的写不命中')
  // outside the window: no hit
  now += WRITE_WINDOW_MS + 1000
  ok(B.recentRemoteWrite('t13') === undefined, '推过守门窗口后不再命中')
  // no more delivery after unsubscribing
  off()
  A.notifyWrite('t13', 'sign')
  await tick()
  ok(got.length === 1, '退订后不再收到写事件')
  A.stop(); B.stop()
  __resetClockForTests()
  uninstallGlobals()
}

/* ------------------------------------------------------ D localStorage fallback channel (no BC) */
section('D localStorage 兜底：无 BroadcastChannel 时互见 + 写事件送达')
{
  installGlobals(false) // BroadcastChannel removed → the localStorage channel is chosen automatically
  // in a real browser the two tabs are two documents, each with its own localStorage view;
  // here A/B each get a FakeLS instance whose setItem fires the 「peer」 storage event.
  let now = 3_000_000
  __setClockForTests(() => now)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  globalThis.localStorage = new FakeLS()
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  A.setViewingTicket('t13')
  await tick()
  ok(B.viewersOf('t13').length === 1 && B.viewersOf('t13')[0].who === 'op-A',
    '无 BC 时 B 经 storage 事件看到 A 在看 t13')
  const got = []
  B.onRemoteWrite(w => got.push(w))
  A.notifyWrite('t13', 'rework')
  await tick()
  ok(got.length === 1 && got[0].op === 'rework', '无 BC 时写事件经 storage 送达')
  ok(B.recentRemoteWrite('t13')?.who === 'op-A', '无 BC 时守门窗口照常命中')
  B.stop()
  await tick()
  ok(A.viewersOf('t13').length === 0, 'bye 经 storage 通道同样即时剔除')
  A.stop()
  __resetClockForTests()
  uninstallGlobals()
}

/* ------------------------------------------------------------------ E bad JSON does not crash */
section('E 坏 JSON / 畸形入站：丢弃不崩')
{
  installGlobals(false)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  B.setViewingTicket('t13')
  await tick()
  let crashed = false
  process.once('uncaughtException', () => { crashed = true })
  // feed bad values and non-heartbeat keys straight into B's storage (dirt a peer or some
  // other script might have written)
  globalThis.localStorage.setItem('suyou-wb-tab-tab-A', '{{{not json')
  globalThis.localStorage.setItem('suyou-wb-tabwrite', '{"v":1,"k":"write","tab":') // truncated JSON
  globalThis.localStorage.setItem('suyou-wb-tab-evil', 'null') // valid JSON but rejected by parseMsg
  await tick()
  ok(!crashed, '坏 JSON 三件套喂入不崩')
  ok(B.viewersOf('t13').length === 0, '脏数据不产生幽灵在看者')
  A.stop(); B.stop()
  uninstallGlobals()
}

/* ------------------------------------------------------------------ F terminal cleanup */
section('F stop 终态回收：无回调泄漏')
{
  installGlobals(true)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  let beats = 0
  B.onRemoteWrite(() => { beats++ })
  A.stop() // first beat already sent; after stop wait a few more beats: B must receive nothing
  await tick(HEARTBEAT_MS * 2 + 20)
  ok(beats === 0, 'A stop 后 B 再无回调（定时器/监听全清）')
  B.stop()
  ok(bcRegistry.size === 0 || [...bcRegistry.values()].every(s => s.size === 0), 'BC 通道实例全部 close')
  uninstallGlobals()
}

console.log(`\n${failed === 0 ? 'PASS' : 'FAIL'}: ${passed} ok, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
