/**
 * sandbar-workbench · chat 项目 tag 数据索引单态（t260903-07 工单②）。
 *
 * Owner 落明（方案 v3 N2 修正后的规格句）：
 * - 谁写：WorkbenchSidebar.load()（10s 轮询）成功分支调用 publishProjects /
 *   publishProjectEntry；catch 分支**不发**（失败不得顶掉 last-known-good，
 *   KI-018 同族预防）。侧栏窄模式（wide=false）不轮询。
 * - 谁读：chat-project-tag.ts 装饰器（消息文本里的工单 id → 项目归属）。
 * - 变更通知（t260911-06 补缺）：publish* 只在**数据实际变化**时通知订阅者
 *   （onProjectTagIndexChange）——此前外部发布后装饰器不重扫，行是否补装饰
 *   全看「碰巧有无别的 DOM 变动」；新消息行在索引空窗插入即永久裸奔（260911
 *   夜 chat-project-tag 间歇红实证签名：新行无 chip、旧行有）。
 * - 兜底自取：装饰器挂载时若单态为空（侧栏未挂载/窄模式），自行 fetch 一次
 *   /wf/projects + 各项目 /wf/tickets?project=，成功后同样走 publish* 合并语义；
 *   60s 重试直到有数据、或侧栏外部发布（publishProjects 被外部调用即停自取定时器，
 *   绝不出现两条 10s 轮询）。取舍已声明：允许 decorator 侧一条低频（60s）兜底轮询，
 *   换取窄模式下 tag 不死。
 * - 按需强取（t260911-06 补缺，nudge）：scan 发现「带票号引用却未归属」的行时，
 *   兜底 handle 的 nudge() 单次强取一轮（绕过 hasData/外部发布停止条件——那两个
 *   条件防的是**定时轮询双跑**，不防「数据源落后于刚建成的新票」）。有界三闸：
 *   在途去重（同时只一轮）、最小间隔（默认 5s）、按引用去重（同一票号只强取一次）。
 *   取到即 publish → 变更通知 → 装饰器重扫；仍取不到（假票号）不重试。
 * - 失败语义：单态按项目键 last-known-good 合并——新值非空覆盖；新值为空且已有
 *   旧值 → 保留旧值 + warn 一次（「fetch 成功但空列表」与失败在数据上同形，统一
 *   口径不猜服务端；项目工单真清零属低频事件且 tag 缺失不炸，无过期机制的代价
 *   已在方案 v3 声明）。
 * - 纯逻辑（合并/查询）与 IO（fetch）分离：startProjectIndexFallback 接受
 *   fetchImpl 注入，smoke 桩测全路径（含畸形响应不炸）。
 * - 可见性门（t260915-10 gen7 顺手收口，仲裁判别探针终裁的 multi-tab T3 泄漏面）：
 *   兜底自取链与 nudge 强取同受 KI-003 族纪律约束——页签不可见即零请求（schedule
 *   周期照排但取数被门住、nudge 忽略且不耗最小间隔额度），回可见立即补跑一次并恢
 *   复节拍，语义对齐 visibility-poll.ts startVisibleInterval 契约。document 不可用
 *   （node/smoke 裸跑）沿用其故障口径：视为可见，取数照常，不静默改语义。
 */

import { pageVisible } from './visibility-state.ts'

/** 发布的项目注册表条目（/wf/projects 行的最小面）。 */
export interface ProjectIndexEntry {
  key: string
  dirs: string[]
}

/** 只读快照（装饰器消费面）。 */
export interface ProjectTagIndex {
  /** 项目 key → 注册目录（cwd 前缀匹配备用；当前 v1 归属主用 ticket 映射）。 */
  projectDirs: Map<string, string[]>
  /** 工单 id → 项目 key。 */
  projectByTicket: Map<string, string>
  /** 是否已有任何成功发布（装饰器兜底自取的停止条件之一）。 */
  hasData: boolean
}

const state = {
  projectDirs: new Map<string, string[]>(),
  projectByTicket: new Map<string, string>(),
  /** 被外部（侧栏）发布过至少一次 → decorator 兜底自取停止。 */
  externallyPublished: false,
  /** 已 warn 过的项目键（warn 一次纪律）。 */
  warnedEmpty: new Set<string>(),
}

/** 归一化工单 id 引用（字符串白名单：t\\d{6}-\\d{2} 口径由调用方先行过滤）。 */
function addTicketsOfProject(key: string, ticketIds: readonly string[]): boolean {
  // 该项目旧映射先比对：集合等价（同引用同归属）则零写动（10s 轮询同值重发
  // 不算变更，不惊扰订阅者）；确有变化才整体替换（delete-then-add 原子完成，
  // 项目维度 last-known-good 在调用侧判空）。返回是否有实际变化。
  const fresh = new Set<string>()
  for (const tid of ticketIds) {
    if (typeof tid === 'string' && tid !== '') fresh.add(tid)
  }
  const prev: string[] = []
  for (const [tid, k] of Array.from(state.projectByTicket)) {
    if (k === key) prev.push(tid)
  }
  if (prev.length === fresh.size && prev.every(tid => fresh.has(tid))) return false
  for (const [tid, k] of Array.from(state.projectByTicket)) {
    if (k === key) state.projectByTicket.delete(tid)
  }
  for (const tid of fresh) state.projectByTicket.set(tid, key)
  return true
}

/* ── 变更通知（t260911-06）：数据实际变化时广播；监听器异常不炸发布方 ── */
type IndexChangeListener = () => void
const changeListeners = new Set<IndexChangeListener>()

/** 订阅索引变更（仅实际变化触发）。返回退订函数（幂等）。 */
export function onProjectTagIndexChange(listener: IndexChangeListener): () => void {
  changeListeners.add(listener)
  return () => { changeListeners.delete(listener) }
}

function notifyIndexChange(): void {
  for (const l of Array.from(changeListeners)) {
    try { l() } catch { /* 单个监听器异常不炸发布路径（侧栏轮询必须恒可达） */ }
  }
}

/**
 * 发布项目注册表（/wf/projects 整体一个请求，成功才调；失败不发）。
 * 外部发布即关停 decorator 兜底自取。畸形条目跳过，不 throw。
 * 数据实际变化才通知订阅者（同值重发=10s 轮询常态，不惊扰）。
 */
export function publishProjects(entries: readonly ProjectIndexEntry[] | unknown): void {
  if (!Array.isArray(entries)) return
  state.externallyPublished = true
  const next = new Map<string, string[]>()
  for (const e of entries) {
    const key = (e as ProjectIndexEntry)?.key
    const dirs = (e as ProjectIndexEntry)?.dirs
    if (typeof key !== 'string' || key === '' || !Array.isArray(dirs)) continue
    next.set(key, dirs.filter(d => typeof d === 'string' && d !== ''))
  }
  let changed = next.size !== state.projectDirs.size
  if (!changed) {
    for (const [k, v] of next) {
      const cur = state.projectDirs.get(k)
      if (cur === undefined || cur.length !== v.length || v.some((d, i) => cur[i] !== d)) { changed = true; break }
    }
  }
  state.projectDirs = next
  if (changed) notifyIndexChange()
}

/**
 * 逐项目发布工单 id → 项目映射（仅在该项目 fetch 成功分支调用）。
 * last-known-good 合并：tickets 空 且 该项目已有旧映射 → 保留旧值 + warn 一次。
 * 数据实际变化才通知订阅者。
 */
export function publishProjectEntry(projectKey: string, ticketIds: readonly string[]): void {
  if (typeof projectKey !== 'string' || projectKey === '') return
  if (!Array.isArray(ticketIds)) return
  const clean = ticketIds.filter(t => typeof t === 'string' && /^t\d{6}-\d{2}$/.test(t))
  const hadOld = clean.length === 0 && [...state.projectByTicket.values()].includes(projectKey)
  if (hadOld) {
    if (!state.warnedEmpty.has(projectKey)) {
      state.warnedEmpty.add(projectKey)
      console.warn('[workbench] 项目 %s 工单列表为空（可能拉取失败或真清零）：tag 映射保留 last-known-good', projectKey)
    }
    return
  }
  if (addTicketsOfProject(projectKey, clean)) notifyIndexChange()
}

/** 只读快照（复制 Map 引用不计成本：装饰器每次扫描只读一次）。 */
export function readProjectTagIndex(): ProjectTagIndex {
  return {
    projectDirs: new Map(state.projectDirs),
    projectByTicket: new Map(state.projectByTicket),
    hasData: state.projectDirs.size > 0 || state.projectByTicket.size > 0,
  }
}

/** 测试隔离口（生产勿调）：清空单态。 */
export function _resetProjectTagIndex(): void {
  state.projectDirs.clear()
  state.projectByTicket.clear()
  state.externallyPublished = false
  state.warnedEmpty.clear()
}

export interface FallbackOptions {
  fetchImpl: typeof fetch
  /** 首次尝试前延迟 ms（默认 0：挂载即试一次）。 */
  initialDelayMs?: number
  /** 重试间隔 ms（默认 60_000，方案声明的低频兜底）。 */
  retryIntervalMs?: number
  /** 最多尝试次数（防永久后台轮询；默认 60 次 ≈1 小时）。 */
  maxAttempts?: number
  /** 拉到数据后的回调（装饰器据此刷 CSS/重扫；成功路径恰好一次调用）。 */
  onData?: () => void
  /** nudge 最小间隔 ms（默认 5_000；smoke/UT 传小值或大值做有界断言）。 */
  nudgeMinIntervalMs?: number
}

/** 兜底自取句柄：stop=全终态回收；nudge=按需单次强取（t260911-06）。 */
export interface FallbackHandle {
  stop(): void
  nudge(): void
}

/**
 * 装饰器兜底自取：单态为空时拉 /wf/projects + 各项目 /wf/tickets?project=，
 * 60s 重试直至有数据或侧栏外部发布。返回句柄：stop() 清定时器全终态回收；
 * nudge() 绕过 hasData/外部发布停止条件单次强取（那两个条件防的是**定时轮询
 * 双跑**，不防「数据源落后于刚建成的新票」），受三闸约束：在途去重、最小间隔
 * （nudgeMinIntervalMs，默认 5s）、（引用级去重在装饰器侧做——它看得到行）。
 * 所有失败路径静默降级（console.warn 一次），不 throw、不影响装饰器主循环。
 */
export function startProjectIndexFallback(opts: FallbackOptions): FallbackHandle {
  const { fetchImpl } = opts
  const initialDelayMs = typeof opts.initialDelayMs === 'number' ? opts.initialDelayMs : 0
  const retryIntervalMs = typeof opts.retryIntervalMs === 'number' ? opts.retryIntervalMs : 60_000
  const maxAttempts = typeof opts.maxAttempts === 'number' ? opts.maxAttempts : 60
  const nudgeMinIntervalMs = typeof opts.nudgeMinIntervalMs === 'number' ? opts.nudgeMinIntervalMs : 5_000
  let timer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  let warned = false
  let attempts = 0
  let inFlight = false
  let lastNudgeAt = 0

  async function tryOnce(force = false): Promise<void> {
    if (stopped || inFlight) return
    // 可见性门（纵深防御一道；t260915-10 gen7）：页签不可见即零请求——nudge/补跑
    // 共用入口，隐藏时在此统一拦下。document 未定义（node/smoke）pageVisible=true 不改语义。
    if (!pageVisible()) return
    if (!force && (state.externallyPublished || readProjectTagIndex().hasData)) return
    inFlight = true
    if (!force) attempts++
    try {
      const pr = await fetchImpl('/sandbar-workbench/api/wf/projects').then(r => r.json())
      const list: ProjectIndexEntry[] = pr?.result?.projects ?? []
      if (!Array.isArray(list) || list.length === 0) throw new Error('projects 列表为空/畸形')
      publishProjects(list.map(p => ({ key: p.key, dirs: Array.isArray(p?.dirs) ? p.dirs : [] })))
      for (const p of list) {
        if (typeof p?.key !== 'string') continue
        try {
          const tr = await fetchImpl(`/sandbar-workbench/api/wf/tickets?project=${encodeURIComponent(p.key)}`).then(r => r.json())
          const tickets = tr?.result?.tickets
          const ids = Array.isArray(tickets) ? tickets.map((t: { id?: unknown }) => t?.id).filter((x): x is string => typeof x === 'string') : []
          publishProjectEntry(p.key, ids)
        } catch { /* 单项目失败：不发该条目，其他项目照常 */ }
      }
      opts.onData?.()
    } catch (err) {
      if (!warned) {
        warned = true
        console.warn('[workbench] chat 项目 tag 索引兜底拉取失败（将持续低频重试）：', String(err instanceof Error ? err.message : err))
      }
    } finally {
      inFlight = false
    }
  }

  function schedule(): void {
    if (stopped) return
    if (state.externallyPublished || readProjectTagIndex().hasData) return
    if (attempts >= maxAttempts) {
      console.warn('[workbench] chat 项目 tag 索引兜底拉取达上限，停止重试（映射缺失 → tag 不渲染）')
      return
    }
    timer = setTimeout(() => {
      // tick 内重读门（对齐 startVisibleInterval 双重门语义）：隐藏时本次不取数，
      // 链照常重排（回可见由 onVisChange 补跑并重排，这里不重复补）。
      if (!pageVisible()) { schedule(); return }
      void tryOnce().then(schedule)
    }, attempts === 0 ? initialDelayMs : retryIntervalMs)
  }

  // 可见性监听（t260915-10 gen7）：回可见=补跑一次+恢复节拍（对齐 startVisibleInterval
  // 的 onVis 语义）；隐藏=停表（清当前定时器，防到点取数）。句柄留档供 stop 移除。
  let visHandler: (() => void) | null = null
  if (typeof document !== 'undefined') {
    visHandler = () => {
      if (stopped) return
      if (pageVisible()) {
        void tryOnce().then(schedule)
      } else if (timer !== null) {
        clearTimeout(timer)
        timer = null
      }
    }
    document.addEventListener('visibilitychange', visHandler)
  }

  schedule()
  return {
    stop() {
      stopped = true
      if (timer !== null) clearTimeout(timer)
      timer = null
      if (visHandler !== null) {
        document.removeEventListener('visibilitychange', visHandler)
        visHandler = null
      }
    },
    nudge() {
      if (stopped || inFlight) return
      if (!pageVisible()) return // 隐藏即忽略强取（不耗最小间隔额度——回可见后真需求仍可立即触发）
      const now = Date.now()
      if (now - lastNudgeAt < nudgeMinIntervalMs) return
      lastNudgeAt = now
      void tryOnce(true)
    },
  }
}
