/**
 * 队列镜像（t260929-04）——宿主 sessionController.control() 流的内存投影。
 *
 * 是什么：把 dsh 0.1.5 的 SessionControlFrame 流（baseline 一次全量 + 每会话 queue
 * 增量替换，见 ~/.sandbar/dsh-015/.../dsh-api-session-controller/lib/types/types.d.ts
 * L488-536）折成一张「会话 id → 未消化队列项」的内存表。唤醒决策（exits.ts 的
 * 已消化判定）只读这张表，绝不自己轮询宿主（宿主明拒的傻轮询）。
 *
 * 纪律：
 *  - 不可读 = 显式：流没起/流终止/帧解析坏 → 状态置 unreadable 并带原因点名，
 *    depthOf/ourBriefPending 一律返回 null（no-signal 语义，调用方照发并点名），
 *    绝不冒充「已消化」。
 *  - 只认我们自己的项（review C2）：宿主队列里可能有人类/其它来源的输入；消费方
 *    用 ourBriefPending(sessionId, requestId) 按 rpcId（prompt 的 requestId 回显）
 *    精确判断「我们上一份简报是否仍未消化」，不用队列总深度冒充。
 *  - 全终态：dispose() abort 消费循环；流的 error / 提前 return / 正常结束三条路
 *    都落到同一个终态收口（unreadable + 原因），不悬挂、不重复收口。
 */

/** 与宿主类型形状一致的最小结构面（ UT 直接造字面量，不 import 宿主包）。 */
export interface MirrorQueueItem {
  readonly id: string
  readonly placement?: 'queued' | 'steering' | 'context' | string
  readonly rpcId?: string
}

export type ControlFrameLike =
  | { type: 'baseline'; value: { queues?: Record<string, readonly MirrorQueueItem[]> } }
  | { type: 'queue'; sessionId: string; items: readonly MirrorQueueItem[] }
  | { type: 'jobs'; sessionId: string; jobs: readonly unknown[] }
  | { type: 'projection'; sessionId: string; key: string; value: unknown; seq: number }
  | { type: string; [k: string]: unknown }

export interface QueueMirrorDeps {
  /** 帧流工厂（node.ts 传 () => ctx.sessionController.control(signal)）；返回 null/undefined = 宿主服务不可达。 */
  frames?: () => AsyncIterable<ControlFrameLike> | null | undefined
  /** 终态回调（测试观测用；状态翻转本身已足够，缺省空）。 */
  onTerminal?: (state: MirrorState, reason: string) => void
}

export type MirrorState = 'idle' | 'live' | 'unreadable'

const COUNTED_PLACEMENTS = new Set(['queued', 'steering'])

export class QueueMirror {
  private state: MirrorState = 'idle'
  private reason: string | null = null
  private depths = new Map<string, MirrorQueueItem[]>()
  private malformed = 0
  private updates = 0
  private ac: AbortController | null = null
  private abortHook: (() => void) | null = null
  private consume: Promise<void> | null = null
  private disposed = false
  private readonly frames: QueueMirrorDeps['frames']
  private readonly onTerminal: NonNullable<QueueMirrorDeps['onTerminal']>

  constructor(deps: QueueMirrorDeps = {}) {
    this.frames = deps.frames
    this.onTerminal = deps.onTerminal ?? (() => {})
  }

  /** 起消费循环（幂等；只在第一次调用时真正开始）。 */
  start(): void {
    if (this.consume !== null || this.disposed) return
    let iter: AsyncIterable<ControlFrameLike> | null | undefined
    try {
      iter = this.frames?.()
    } catch (e) {
      iter = null
      this.reason = `帧流工厂抛错：${e instanceof Error ? e.message : String(e)}`
    }
    if (iter === null || iter === undefined) {
      this.markUnreadable(this.reason ?? '宿主 sessionController 不可达——队列镜像无源（显式 no-signal）')
      this.consume = Promise.resolve()
      return
    }
    this.ac = new AbortController()
    this.consume = this.drain(iter)
  }

  private async drain(iter: AsyncIterable<ControlFrameLike>): Promise<void> {
    // 手动迭代：next 与「dispose/abort」竞争——不信任外部迭代器会自己结束
    // （宿主流响应 abort；测试/异常实现可能永不返回，收口权必须在自己手里）。
    let aborted: () => void = () => {}
    const abortP = new Promise<null>(r => { aborted = () => r(null) })
    this.abortHook = aborted
    const it = (await Promise.race([iter[Symbol.asyncIterator](), abortP])) as AsyncIterator<ControlFrameLike> | null
    if (it === null) { try { await Promise.race([iter[Symbol.asyncIterator](), new Promise(r => setTimeout(r, 50))]) } catch { /* 尽力 */ } return }
    try {
      for (;;) {
        if (this.disposed || this.ac?.signal.aborted) break
        const nxt = await Promise.race([it.next(), abortP])
        if (nxt === null) break // abort：立即收口
        if (!nxt || nxt.done) {
          if (!this.disposed && !this.ac?.signal.aborted) {
            this.markUnreadable('control 流在未 dispose 的情况下结束（宿主侧关闭）——镜像数据停更，显式 no-signal')
          }
          break
        }
        this.applyFrame(nxt.value)
      }
      try { await Promise.race([it.return?.(), new Promise(r => setTimeout(r, 50))]) } catch { /* 收尾尽力 */ }
    } catch (e) {
      if (!this.disposed) {
        this.markUnreadable(`control 流失败：${e instanceof Error ? e.message : String(e)}`)
      }
    }
  }

  private applyFrame(frame: ControlFrameLike): void {
    if (frame === null || typeof frame !== 'object' || typeof (frame as { type?: unknown }).type !== 'string') {
      this.malformed += 1
      return
    }
    switch (frame.type) {
      case 'baseline': {
        const queues = (frame as Extract<ControlFrameLike, { type: 'baseline' }>).value?.queues
        if (queues === null || typeof queues !== 'object') { this.malformed += 1; return }
        this.depths = new Map(Object.entries(queues).map(([sid, items]) => [sid, Array.isArray(items) ? [...items] : []]))
        this.becomeLive()
        break
      }
      case 'queue': {
        const f = frame as Extract<ControlFrameLike, { type: 'queue' }>
        if (typeof f.sessionId !== 'string' || !Array.isArray(f.items)) { this.malformed += 1; return }
        this.depths.set(f.sessionId, [...f.items])
        this.becomeLive()
        break
      }
      case 'jobs':
      case 'projection':
        break // 与已消化判定无关的帧：不消费也不算坏帧
      default:
        this.malformed += 1 // 未知帧形状：点名计数，不猜
    }
  }

  private becomeLive(): void {
    if (this.state !== 'live') {
      this.state = 'live'
      this.reason = null
      this.updates += 1
    }
  }

  private markUnreadable(reason: string): void {
    this.state = 'unreadable'
    this.reason = reason
    this.onTerminal(this.state, reason)
  }

  /** 该会话未消化项数（只数 queued/steering；unreadable = null 显式）。 */
  depthOf(sessionId: string): number | null {
    if (this.state !== 'live') return null
    const items = this.depths.get(sessionId) ?? []
    return items.filter(i => COUNTED_PLACEMENTS.has(String(i?.placement ?? 'queued'))).length
  }

  /** 我们的上一份简报（按 prompt 的 requestId → 队列项 rpcId 回显）是否仍未消化。
   *  unreadable = null（no-signal，绝不冒充已消化）。 */
  ourBriefPending(sessionId: string, requestId: string): boolean | null {
    if (this.state !== 'live') return null
    const items = this.depths.get(sessionId) ?? []
    return items.some(i => i?.rpcId === requestId)
  }

  /** 我们的未消化项 id（updateQueue 主动消化用；找不到 = null 显式）。 */
  itemIdOfRpc(sessionId: string, rpcId: string): string | null {
    if (this.state !== 'live') return null
    const items = this.depths.get(sessionId) ?? []
    return items.find(i => i?.rpcId === rpcId)?.id ?? null
  }

  /** 状态串（watchdog status 面的 queue_mirror 键）。 */
  describe(): string {
    if (this.state === 'live') return `live（更新 ${this.updates} 次，坏帧 ${this.malformed}）`
    return `${this.state}${this.reason ? `：${this.reason}` : ''}（坏帧 ${this.malformed}）`
  }

  get stateInfo(): MirrorState {
    return this.state
  }

  /** 全终态：abort 消费循环；等 drain 收尾（有界等待——真实宿主流响应 abort，
   *  但不信任任何外部迭代器会自己结束：50ms 不收口即放弃等待，绝不悬挂 dispose）。 */
  async dispose(): Promise<void> {
    this.disposed = true
    this.ac?.abort()
    this.abortHook?.()
    try { await Promise.race([this.consume, new Promise(r => setTimeout(r, 50))]) } catch { /* drain 内部已收口 */ }
    if (this.state !== 'unreadable') this.markUnreadable('disposed（守望者卸载）')
  }
}
