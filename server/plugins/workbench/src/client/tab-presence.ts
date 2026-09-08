/**
 * tab-presence.ts —— 工单台多页签共存：在看心跳 + 写事件广播（t260901-15）。
 *
 * 背景：用户常开多个工单台页签，互相失明——看不到谁在查看/操作哪张工单，
 * 两页签对同一工单的写操作（推进/签字/打回/完成等）基于过期前端态互踩；
 * 后台页签还照常全速轮询放大查询通道压力。本模块解决前两件（第三件=
 * 不可见页签暂停轮询，由 visibility-poll.ts 的可见性门收口）。
 *
 * 机制（两通道，可独立失效，都不静默）：
 *   1. 主通道 BroadcastChannel('sandbar-workbench-tabs')：presence 3s 心跳
 *      （含当前查看的工单 id，关抽屉/隐藏页签置 null）+ write 写事件 + bye。
 *   2. 兜底通道 localStorage：心跳逐页签写 key（storage 事件跨 document 送达），
 *      write 事件写共享 key；BroadcastChannel 不可用（老内核/被禁）时自动走它，
 *      行为等价，降级在注释里写明，不静默。
 *
 * 故障模式取舍（review_plan 钩子要求自查）：
 *   - 页签崩溃发不出 bye → 靠 10s TTL 过期剔除，viewersOf 永不卡死；
 *   - 入站消息是外部输入 → 五类畸形（非 JSON/缺字段/未知类型/字段类型不对/
 *     超长）一律丢弃不崩；
 *   - 心跳/定时器 → stop() 与 pagehide 双终态回收；
 *   - 本模块是 UI 层软机制（不做服务端在场登记），崩溃/降级时退化为
 *     「无提示」，不影响任何写操作主路径。
 *
 * 模块顶层零 IO（smoke 在 node 裸跑，须先 stub BroadcastChannel/localStorage/
 * document 再 import 后调用 startTabPresence——同 session-ledger-store 先例）。
 */

/** presence 心跳间隔（ms）。 */
export const HEARTBEAT_MS = 3000
/** 心跳 TTL：超过即视为该页签已不在看（ms）。 */
export const PEER_TTL_MS = 10000
/** 写守门窗口：远端页签在此时间内写过该工单 → 本页签写前二次确认（ms）。 */
export const WRITE_WINDOW_MS = 10000
/** 写事件留痕上限（条），防长跑内存涨。 */
const WRITE_LOG_CAP = 50
/** 写事件留痕保留时长（ms），超时随 prune 丢弃。 */
const WRITE_LOG_TTL_MS = 60_000
/** 字符串字段长度上限（入站防呆）。 */
const LEN_TAB = 64
const LEN_WHO = 64
const LEN_TICKET = 128
const LEN_OP = 32

const CHANNEL = 'sandbar-workbench-tabs'
const LS_HEARTBEAT_PREFIX = 'sandbar-wb-tab-'
const LS_WRITE_KEY = 'sandbar-wb-tabwrite'
const PROTO_V = 1

/** 同页签在看者（viewersOf 返回项；ageMs=距今多久的心跳）。 */
export interface PeerViewer { who: string; ageMs: number }
/** 远端写事件（onRemoteWrite 回调载荷）。 */
export interface RemoteWrite { ticket: string; op: string; who: string; ageMs: number }
/** 写守门命中结果（recentRemoteWrite 返回项）。 */
export interface RecentWriteHit { op: string; who: string; ageMs: number }

/** 对外句柄：一个页签一份，startTabPresence 幂等（重复 start 先停旧的）。 */
export interface TabPresence {
  /** 详情抽屉开/关/切换时调用；null=本页签没在看任何工单。 */
  setViewingTicket(ticket: string | null): void
  /** 其它页签中正在看 ticket 的列表（TTL 过期自动剔除；不含自己）。 */
  viewersOf(ticket: string): PeerViewer[]
  /** 本页签刚完成一次写操作 → 广播给其它页签（自身回环已过滤）。 */
  notifyWrite(ticket: string, op: string): void
  /** 远端页签 withinMs 内是否写过 ticket（写前守门依据；最新一条）。 */
  recentRemoteWrite(ticket: string, withinMs?: number): RecentWriteHit | undefined
  /** 订阅远端写事件；返回退订函数。 */
  onRemoteWrite(cb: (w: RemoteWrite) => void): () => void
  /** 全终态回收：定时器/监听移除、bye 广播、本页签心跳 key 清除。 */
  stop(): void
}

/* ------------------------------------------------------------------ 时钟（smoke 注入） */
let clock: () => number = () => Date.now()
/** 测试专用：注入可控时钟。 */
export function __setClockForTests(fn: () => number): void { clock = fn }
/** 测试专用：恢复真实时钟。 */
export function __resetClockForTests(): void { clock = () => Date.now() }

/* --------------------------------------------------------------- 入站消息校验（防畸形） */
interface PresenceMsg { v: number; k: 'presence'; tab: string; who: string; ticket: string | null; ts: number }
interface WriteMsg { v: number; k: 'write'; tab: string; who: string; ticket: string; op: string; ts: number }
interface ByeMsg { v: number; k: 'bye'; tab: string; ts: number }
type Msg = PresenceMsg | WriteMsg | ByeMsg

function str(v: unknown, max: number): string | null {
  return typeof v === 'string' && v.length > 0 && v.length <= max ? v : null
}
function tsNum(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null
}

/** 严格校验入站消息：五类畸形（非对象/缺字段/未知 k/字段类型不对/超长）→ null。 */
export function parseMsg(raw: unknown): Msg | null {
  if (raw === null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (o.v !== PROTO_V) return null
  const tab = str(o.tab, LEN_TAB)
  const ts = tsNum(o.ts)
  if (tab === null || ts === null) return null
  if (o.k === 'presence') {
    const who = str(o.who, LEN_WHO)
    if (who === null) return null
    let ticket: string | null
    if (o.ticket === null || o.ticket === undefined) ticket = null
    else { ticket = str(o.ticket, LEN_TICKET); if (ticket === null) return null }
    return { v: PROTO_V, k: 'presence', tab, who, ticket, ts }
  }
  if (o.k === 'write') {
    const who = str(o.who, LEN_WHO)
    const ticket = str(o.ticket, LEN_TICKET)
    const op = str(o.op, LEN_OP)
    if (who === null || ticket === null || op === null) return null
    return { v: PROTO_V, k: 'write', tab, who, ticket, op, ts }
  }
  if (o.k === 'bye') return { v: PROTO_V, k: 'bye', tab, ts }
  return null
}

/* --------------------------------------------------------------- 运行时状态（单例） */
interface Peer { who: string; ticket: string | null; ts: number }
interface WriteEntry { ticket: string; op: string; who: string; ts: number }

/** 惰性能力探测 + 句柄获取（全部包 try/catch：能力缺失走兜底，不静默——注释明写）。 */
function getLS(): Storage | null {
  try {
    if (typeof localStorage !== 'undefined') return localStorage
  } catch { /* 隐私模式禁 localStorage → 只有 BroadcastChannel 单通道 */ }
  return null
}

function lsSet(ls: Storage | null, key: string, value: string): void {
  try { ls?.setItem(key, value) } catch { /* 写失败丢持久化，心跳仍走 BC */ }
}
function lsRemove(ls: Storage | null, key: string): void {
  try { ls?.removeItem(key) } catch { /* 清理失败无害 */ }
}
function lsSweepHeartbeat(ls: Storage | null, now: number): void {
  if (ls === null) return
  try {
    const stale: string[] = []
    for (let i = 0; i < ls.length; i++) {
      const key = ls.key(i)
      if (key === null || !key.startsWith(LS_HEARTBEAT_PREFIX)) continue
      const m = parseMsg(JSON.parse(ls.getItem(key) ?? 'null'))
      if (m === null || now - m.ts > PEER_TTL_MS) stale.push(key)
    }
    for (const k of stale) lsRemove(ls, k)
  } catch { /* 坏 JSON/遍历异常：跳过本次清扫，TTL 读侧仍兜底 */ }
}

/**
 * 启动本页签的在场广播。调用方负责在卸载时 stop()（React effect 清理）；
 * 重复 start 各自独立（smoke 单模块实例模拟双页签依赖这一点）。
 * @param who 操作者标识（工单台 operator，展示在「另一页签正在查看」提示里）。
 * @param opts.tabId 测试注入：固定本页签 id（smoke 单模块实例模拟双页签）；
 *   生产不传，随机生成。
 */
export function startTabPresence(who: string, opts?: { tabId?: string }): TabPresence {
  const ls = getLS()
  const tab = opts?.tabId ?? `t-${Math.random().toString(36).slice(2, 10)}`
  let ticketNow: string | null = null
  let stopped = false
  const peers = new Map<string, Peer>()
  let writes: WriteEntry[] = []
  const writeListeners = new Set<(w: RemoteWrite) => void>()

  // 主通道：BroadcastChannel 不可用时保持 null，心跳/写事件自动全落 localStorage。
  let bc: BroadcastChannel | null = null
  try {
    if (typeof BroadcastChannel !== 'undefined') bc = new BroadcastChannel(CHANNEL)
  } catch { bc = null /* 构造被拒 → localStorage 兜底通道独走 */ }
  const onBcMessage = (ev: MessageEvent) => { ingest(ev.data) }
  bc?.addEventListener('message', onBcMessage)

  const visible = (): boolean =>
    typeof document === 'undefined' || document.visibilityState !== 'hidden'

  function send(msg: Msg): void {
    try { bc?.postMessage(msg) } catch { /* 通道故障：本跳丢失，心跳下跳补 */ }
    // 兜底通道：presence 逐页签 key，write 共享 key（值含 ts 必变，storage 事件必触发）。
    // 用启动时捕获的 ls（同浏览器里每页签是独立 document、各有一份 localStorage 视图）。
    if (msg.k === 'presence') lsSet(ls, LS_HEARTBEAT_PREFIX + tab, JSON.stringify(msg))
    else if (msg.k === 'write') lsSet(ls, LS_WRITE_KEY, JSON.stringify(msg))
  }

  function ingest(raw: unknown): void {
    const m = parseMsg(raw)
    if (m === null || m.tab === tab) return // 畸形丢弃 / 自身回环过滤
    if (m.k === 'presence') {
      peers.set(m.tab, { who: m.who, ticket: m.ticket, ts: m.ts })
    } else if (m.k === 'write') {
      writes.push({ ticket: m.ticket, op: m.op, who: m.who, ts: m.ts })
      const w: RemoteWrite = { ticket: m.ticket, op: m.op, who: m.who, ageMs: Math.max(0, clock() - m.ts) }
      for (const cb of writeListeners) {
        try { cb(w) } catch { /* 回调异常不拖垮广播循环 */ }
      }
    } else {
      peers.delete(m.tab)
      lsRemove(ls, LS_HEARTBEAT_PREFIX + m.tab)
    }
  }

  function prune(now: number): void {
    for (const [id, p] of peers) if (now - p.ts > PEER_TTL_MS) peers.delete(id)
    if (writes.length > 0) writes = writes.filter(w => now - w.ts <= WRITE_LOG_TTL_MS)
  }

  function heartbeat(): void {
    if (stopped) return
    const now = clock()
    prune(now)
    send({ v: PROTO_V, k: 'presence', tab, who, ticket: visible() ? ticketNow : null, ts: now })
  }

  function onStorage(ev: StorageEvent): void {
    if (ev.key === null) return
    if (ev.key === LS_WRITE_KEY || ev.key.startsWith(LS_HEARTBEAT_PREFIX)) {
      if (ev.newValue !== null) {
        let raw: unknown
        try { raw = JSON.parse(ev.newValue) } catch { return /* 坏 JSON 丢弃 */ }
        ingest(raw)
      }
    }
  }
  ls?.addEventListener?.('storage', onStorage)

  function onVisibility(): void {
    // 隐藏 → 立即广播「不在看」（peers 即时清，不等 3s 心跳）；可见 → 立即补一拍。
    heartbeat()
  }
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onVisibility)
  function onPageHide(): void { self.stop() }
  if (typeof window !== 'undefined') window.addEventListener('pagehide', onPageHide)

  // 启动：清一遍别人留下的过期 key（崩溃页签的残骸），发首拍心跳。
  lsSweepHeartbeat(ls, clock())
  heartbeat()
  const timer = setInterval(heartbeat, HEARTBEAT_MS)

  const self: TabPresence = {
    setViewingTicket(t: string | null) {
      ticketNow = t
      heartbeat() // 即时广播，不等下拍
    },
    viewersOf(t: string): PeerViewer[] {
      const now = clock()
      prune(now)
      const out: PeerViewer[] = []
      for (const p of peers.values()) {
        if (p.ticket === t) out.push({ who: p.who, ageMs: Math.max(0, now - p.ts) })
      }
      return out
    },
    notifyWrite(t: string, op: string) {
      if (stopped) return
      const now = clock()
      prune(now)
      send({ v: PROTO_V, k: 'write', tab, who, ticket: t, op: op.slice(0, LEN_OP), ts: now })
    },
    recentRemoteWrite(t: string, withinMs: number = WRITE_WINDOW_MS): RecentWriteHit | undefined {
      const now = clock()
      prune(now)
      let hit: WriteEntry | undefined
      for (const w of writes) {
        if (w.ticket !== t) continue
        if (now - w.ts > withinMs) continue
        if (hit === undefined || w.ts > hit.ts) hit = w
      }
      return hit === undefined ? undefined : { op: hit.op, who: hit.who, ageMs: Math.max(0, now - hit.ts) }
    },
    onRemoteWrite(cb: (w: RemoteWrite) => void): () => void {
      writeListeners.add(cb)
      return () => { writeListeners.delete(cb) }
    },
    stop() {
      if (stopped) return
      stopped = true
      clearInterval(timer)
      // 正常终态：发 bye 让对端即时剔除；pagehide 时 BC/LS 可能发不出去，TTL 兜底。
      try { bc?.postMessage({ v: PROTO_V, k: 'bye', tab, ts: clock() }) } catch { /* 页面销毁期发送失败无害 */ }
      lsRemove(ls, LS_HEARTBEAT_PREFIX + tab)
      if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility)
      if (typeof window !== 'undefined') window.removeEventListener('pagehide', onPageHide)
      ls?.removeEventListener?.('storage', onStorage)
      bc?.removeEventListener('message', onBcMessage)
      try { bc?.close() } catch { /* close 失败无害 */ }
      bc = null
    },
  }
  return self
}
