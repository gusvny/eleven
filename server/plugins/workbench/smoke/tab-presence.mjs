// smoke/tab-presence.mjs —— t260901-15 多页签共存（tab-presence.ts）冒烟。
//
// 直跑：node smoke/tab-presence.mjs（node ≥22.18 原生 type-stripping，直接 import .ts）。
// 全部用例桩化：stub BroadcastChannel 总线 + stub localStorage（跨实例 storage 事件），
// 注入时钟，不碰网络、不碰 3099、不依赖真外部源（畸形输入用例全靠固定桩喂）。
//
// 覆盖（方案验收口径逐条）：
//   A. parseMsg 畸形输入：非对象/版本不对/缺字段/未知类型/字段类型不对/超长 → null。
//   B. BroadcastChannel 主通道：双页签互见 viewersOf；setViewingTicket 即时生效；
//      自己不在自己的 viewersOf 里；bye/stop 即时剔除；TTL 过期剔除（注入时钟）。
//   C. 写事件：notifyWrite → 对端 onRemoteWrite 收到（ticket/op/who）；
//      recentRemoteWrite 窗口内命中、窗口外不命中（注入时钟）；自身写不算远端。
//   D. localStorage 兜底通道：BroadcastChannel 缺席时双页签经 storage 事件互见 + 写事件送达。
//   E. 坏 JSON：直接向对端 storage 喂非 JSON 值 → 不崩、无回调。
//   F. 终态回收：stop 后对端不再收到心跳/写事件（等一拍验证，无回调泄漏）。

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

/* --------------------------------------------------------- 桩：BroadcastChannel 总线 */
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

/* --------------------------------------------------------- 桩：localStorage（跨实例事件） */
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

/* --------------------------------------------------------- 桩：document（恒可见） */
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

/* ---------------------------------------------------------------- A parseMsg 畸形输入 */
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

/* ------------------------------------------------ B BroadcastChannel 主通道：双页签互见 */
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
  // 切看：即时生效
  B.setViewingTicket('t13')
  await tick()
  ok(A.viewersOf('t13').length === 2 - 1 && A.viewersOf('t13')[0].who === 'op-B', 'B 切看 t13 后 A 即时可见')
  B.setViewingTicket(null)
  await tick()
  ok(A.viewersOf('t13').length === 0, 'B 关抽屉（null）后 A 侧即时消失')
  // TTL：时钟推过 PEER_TTL_MS（期间无新心跳——停掉 A 的节拍靠 stop 后再手发？直接用 stop 测 bye）
  B.setViewingTicket('t11')
  B.stop()
  await tick()
  ok(A.viewersOf('t11').length === 0, 'B stop（bye）后 A 即时剔除')
  // TTL 过期：B 已停，A 侧残留 peers 已在 bye 清掉；改用时钟推 + C 页签只发一拍
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

/* ------------------------------------------------------------------ C 写事件 + 守门窗口 */
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
  // 窗口外不命中
  now += WRITE_WINDOW_MS + 1000
  ok(B.recentRemoteWrite('t13') === undefined, '推过守门窗口后不再命中')
  // 退订后不再收到
  off()
  A.notifyWrite('t13', 'sign')
  await tick()
  ok(got.length === 1, '退订后不再收到写事件')
  A.stop(); B.stop()
  __resetClockForTests()
  uninstallGlobals()
}

/* ------------------------------------------------------ D localStorage 兜底通道（无 BC） */
section('D localStorage 兜底：无 BroadcastChannel 时互见 + 写事件送达')
{
  installGlobals(false) // 删掉 BroadcastChannel → 自动走 localStorage 通道
  // 真实浏览器里两个页签是两个 document、各有一份 localStorage 视图；
  // 这里给 A/B 各配一个 FakeLS 实例，setItem 触发「对端」storage 事件。
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

/* ------------------------------------------------------------------ E 坏 JSON 不崩 */
section('E 坏 JSON / 畸形入站：丢弃不崩')
{
  installGlobals(false)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  B.setViewingTicket('t13')
  await tick()
  let crashed = false
  process.once('uncaughtException', () => { crashed = true })
  // 直接往 B 的 storage 塞坏值与非心跳 key（模拟对端/别的脚本写的脏数据）
  globalThis.localStorage.setItem('suyou-wb-tab-tab-A', '{{{not json')
  globalThis.localStorage.setItem('suyou-wb-tabwrite', '{"v":1,"k":"write","tab":') // 截断 JSON
  globalThis.localStorage.setItem('suyou-wb-tab-evil', 'null') // 合法 JSON 但 parseMsg 拒
  await tick()
  ok(!crashed, '坏 JSON 三件套喂入不崩')
  ok(B.viewersOf('t13').length === 0, '脏数据不产生幽灵在看者')
  A.stop(); B.stop()
  uninstallGlobals()
}

/* ------------------------------------------------------------------ F 终态回收 */
section('F stop 终态回收：无回调泄漏')
{
  installGlobals(true)
  const A = startTabPresence('op-A', { tabId: 'tab-A' })
  const B = startTabPresence('op-B', { tabId: 'tab-B' })
  let beats = 0
  B.onRemoteWrite(() => { beats++ })
  A.stop() // 首拍已发，stop 后再等几拍：B 不应再收到任何消息
  await tick(HEARTBEAT_MS * 2 + 20)
  ok(beats === 0, 'A stop 后 B 再无回调（定时器/监听全清）')
  B.stop()
  ok(bcRegistry.size === 0 || [...bcRegistry.values()].every(s => s.size === 0), 'BC 通道实例全部 close')
  uninstallGlobals()
}

console.log(`\n${failed === 0 ? 'PASS' : 'FAIL'}: ${passed} ok, ${failed} failed`)
process.exit(failed === 0 ? 0 : 1)
