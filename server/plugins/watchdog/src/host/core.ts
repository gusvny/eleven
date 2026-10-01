/**
 * Watchdog core（t260928-28）——把 config/tail/reconcile/liveness/self-lock/exits
 * 拼成一个项目一个实例的状态机。一进程看多项目（按项目分账，不搞每项目一进程）。
 *
 * 生命周期（全终态纪律）：start() 起单一定时器；dispose() 清定时器、停对账（在飞
 * 对账以 aborted 标记收尾），正常/报错/超时/取消四条路都走到清理。
 *
 * 启动即全量（工单 scope 2）：start() 从账本第 0 行重放重建（不信任任何内存水位），
 * alerts.jsonl 重放重建去重集——重启不重播过去 12 小时；缺行/去重重建计数全部显式。
 *
 * 注入面（测试桩全走这里）：io（fs）、boardReader（看板真源）、wakeIo（投递面）、
 * pendingProvider（自锁证据源）、now（时钟）。
 */

import { appendFile, mkdir, readFile, writeFile, stat, readdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'

import { loadWatchdogConfig, watchdogDataDir, eventLedgerFile, projectsRoot, type ResolvedConfig } from './config.ts'
import { LedgerTailer, deriveTicketStates, type LedgerRow, type TailIo } from './ledger-tail.ts'
import { compareStates, countMissingRows, degradedResult, makeMissingRowsSpec, type BoardRow, type ReconcileResult } from './reconcile.ts'
import { judgeExecutor, type ExecutorLiveness } from './liveness.ts'
import { detectSelfLock, type PendingInteraction, type SelfLockVerdict } from './self-lock.ts'
import { applyDedupe, judgeAlert, makeKey, replayDedupe, type AlertSpec, type DedupeState } from './alert-rules.ts'
import { alertRecord, freshWakeMemory, wakeExecutor, type WakeIo, type WakeMemory, type WakeOutcome } from './exits.ts'

export interface BoardReader {
  (): Promise<{ ok: boolean; rows: BoardRow[]; error?: string }>
}

/** 引擎存活探针（独立于对账：board 桩故障 ≠ 引擎死；缺省回落 board 读结果）。 */
export interface EngineProbe {
  (): Promise<{ online: boolean; detail: string }>
}

export interface PendingProvider {
  (): Promise<{ available: boolean; pending: PendingInteraction[] | null; reason?: string }>
}

export interface SessionStatFn {
  /** executor 会话文件的 (size,mtime) 前进探测；null = 会话文件不可读。 */
  (sessionId: string, sinceMs: number): Promise<{ advanced: boolean | null; mtimeMs: number | null }>
}

export interface CoreIo {
  tail: TailIo
  heartbeat: {
    write(path: string, data: string): Promise<void>
    read(path: string): Promise<string>
    mtimeMs(path: string): Promise<number | null>
  }
  appendAlerts(path: string, line: string): Promise<void>
  listAlerts(path: string): Promise<string[]>
}

export const defaultIo: CoreIo = {
  tail: {
    stat: async (p) => { const s = await stat(p); return { size: s.size, ino: s.ino } },
    read: async (p, a, b) => {
      const { open } = await import('node:fs/promises')
      const fh = await open(p, 'r')
      try {
        const len = Math.min(b, Number.MAX_SAFE_INTEGER) - a
        const buf = Buffer.alloc(len)
        const { bytesRead } = await fh.read(buf, 0, len, a)
        return buf.toString('utf8', 0, bytesRead)
      } finally { await fh.close() }
    },
    listArchives: async (activePath) => {
      const dir = dirname(activePath)
      const base = activePath.slice(dir.length + 1).replace(/\.jsonl$/, '')
      const names = await readdir(dir)
      return names.filter(n => n.startsWith(`${base}.`) || (n.startsWith(base) && n !== `${base}.jsonl` && n.endsWith('.jsonl')))
    },
  },
  heartbeat: {
    write: async (p, d) => { await mkdir(dirname(p), { recursive: true }); await writeFile(p, d) },
    read: async (p) => readFile(p, 'utf8'),
    mtimeMs: async (p) => { try { return (await stat(p)).mtimeMs } catch { return null } },
  },
  appendAlerts: async (p, line) => { await mkdir(dirname(p), { recursive: true }); await appendFile(p, line + '\n') },
  listAlerts: async (p) => {
    let raw = ''
    try { raw = await readFile(p, 'utf8') } catch { return [] }
    return raw.split('\n').filter(l => l !== '')
  },
}

/** deps：除 io 外全部可桩。 */
export interface WatchdogDeps {
  configDirEnv?: NodeJS.ProcessEnv
  /** 配置装载注入（默认 loadWatchdogConfig；UT 用内存桩——沙箱 vfs 对真实 fs 的读可见性不稳，见 tests/lib.mjs 注）。 */
  configLoader?: (key: string, env: NodeJS.ProcessEnv | undefined) => ResolvedConfig
  io?: CoreIo
  boardReader?: BoardReader
  engineProbe?: EngineProbe
  wakeIo?: WakeIo | null
  pendingProvider?: PendingProvider
  sessionStat?: SessionStatFn
  now?: () => number
  /** 数据根（heartbeat/alerts 落此根；测试缝）。 */
  dataDir?: string
  /** 账本目录（缺省 env SANDBAR_EVENT_LEDGER_DIR 或 <repo>/server/ledger；测试缝）。 */
  ledgerDir?: string
  /** 按需代建 executor 会话（t260930-09；未注入=不代建，行为与旧语义一致）。 */
  sessionEnsure?: SessionEnsureFn
}

/** 会话代建回调形状（node.ts 注入 ensureExecutorSession 的闭包；UT 注入桩）。 */
export type SessionEnsureFn = (args: { declaredSessionId: string; hasWork: boolean }) => Promise<SessionEnsureOutcome>
export type SessionEnsureOutcome = import('./session-create.ts').EnsureOutcome

/** 代建失败重试节流（同进程内拒绝后至少隔这么久再试一次；成功后不再试）。 */
export const SESSION_ENSURE_RETRY_MS = 5 * 60_000

export type CorePhase = 'idle' | 'full_reconcile' | 'running' | 'stopped' | 'config_error'

export interface WatchdogStatus {
  project: string
  declared: boolean
  enabled: boolean
  phase: CorePhase
  config_error: string | null
  config_provenance: ResolvedConfig['provenance'] & { keys: Record<string, string> }
  heartbeat: { last_beat: number | null; age_seconds: number | null; alive: boolean; reason: string | null }
  ledger: { path: string; watermark_offset: number; rows_seen: number; dupes_skipped: number; malformed_rows: number; gaps_seen: number; last_row_at: number | null; unreadable: string | null }
  liveness: { engine: { online: boolean | null; detail: string; checked_at: number | null }; executor: ExecutorLiveness | null }
  self_lock: SelfLockVerdict | null
  reconcile: ReconcileResult | null
  startup: { missing_rows: number | null; replayed_rows: number | null; dedupe_keys: number }
  /** t260929-04 additive：自醒排除的响亮计数与最近证据（review C1 的审计面）。 */
  presumed_self_rows: number
  presumed_self_detail: string | null
  /** t260929-04 additive：队列镜像/投递通路状态串（null = 镜像面未注入）。 */
  queue_mirror: string | null
  /** t260930-09 additive：按需代建面最近一次结果（null = 未注入代建面）。 */
  executor_session: { session_id: string | null; last_action: string | null; reason: string | null; declared_written: boolean } | null
  wakes: Array<{ at: number; ticket: string; dedupe_key: string; mode: string | null; accepted: boolean | null }>
  alerts: Array<Record<string, unknown>>
  notify: { beep: boolean; unseen_redline: number }
  last_error: string | null
}

const HEARTBEAT_STALE_MS = 3 * 60_000

export class Watchdog {
  readonly project: string
  private cfg: ResolvedConfig
  private tailer: LedgerTailer
  private io: CoreIo
  private boardReader: BoardReader
  private engineProbe: EngineProbe | null
  private wakeIo: WakeIo | null
  private pendingProvider: PendingProvider
  private sessionStat: SessionStatFn
  private sessionEnsure: SessionEnsureFn | null
  private now: () => number
  private dataDir: string
  private timer: ReturnType<typeof setInterval> | null = null
  private disposed = false
  private inFlight = false
  private aborted = false

  private dedupe: DedupeState = new Map()
  private ledgerRows: LedgerRow[] = []
  private lastProgressAt: number | null = null
  private lastSessionStatMs = 0
  private lastSessionAdvanced: boolean | null = null
  private engineOnline: { online: boolean | null; detail: string; checked_at: number | null } = { online: null, detail: '尚未探测', checked_at: null }
  private reconcileState: ReconcileResult | null = null
  private selfLock: SelfLockVerdict | null = null
  private liveness: ExecutorLiveness | null = null
  private startup: { missing_rows: number | null; replayed_rows: number | null; dedupe_keys: number } = { missing_rows: null, replayed_rows: null, dedupe_keys: 0 }
  private wakes: WatchdogStatus['wakes'] = []
  /** 自醒排除记忆（t260929-04）：随实例存活；dispose 即随进程终态。 */
  private wakeMem: WakeMemory = freshWakeMemory()
  private alerts: Array<Record<string, unknown>> = []
  private unseenRedline = new Set<string>()
  private lastError: string | null = null
  // 代建面（t260930-09）：收养每进程只记一次；失败重试节流；最近结果进状态面。
  private ensureAdoptLogged = false
  private lastEnsureFailAt = Number.NEGATIVE_INFINITY
  private ensureState: WatchdogStatus['executor_session'] = null
  phase: CorePhase = 'idle'

  constructor(project: string, deps: WatchdogDeps = {}) {
    this.project = project
    this.io = deps.io ?? defaultIo
    this.now = deps.now ?? Date.now
    this.boardReader = deps.boardReader ?? (async () => ({ ok: false, rows: [], error: 'boardReader 未注入（实现期由 node.ts 提供 engine client.py spawn）' }))
    this.engineProbe = deps.engineProbe ?? null
    this.wakeIo = deps.wakeIo ?? null
    this.pendingProvider = deps.pendingProvider ?? (async () => ({ available: false, pending: null, reason: '宿主侧待办交互面未接入（S1-probe 后续票落地）——显式 unknown' }))
    this.sessionStat = deps.sessionStat ?? (async () => ({ advanced: null, mtimeMs: null }))
    this.sessionEnsure = deps.sessionEnsure ?? null
    // 260930 直修：数据根走 config.watchdogDataDir **单一真源**（与 node.ts 的执行器会话账 /
    // 状态读侧同一个表达式）。旧写法读 `deps.configDirEnv`，而该 deps 生产恒不传 ⇒ HOME 取空
    // ⇒ 退化成相对路径 `.sandbar/watchdog`（写进仓根），读侧看 ~/.sandbar/watchdog ⇒ 永不相见。
    this.dataDir = deps.dataDir ?? watchdogDataDir(deps.configDirEnv ?? process.env)
    this.ledgerDirOpt = deps.ledgerDir
    this.cfg = (deps.configLoader ?? ((k, env) => loadWatchdogConfig(k, env)))(project, deps.configDirEnv)
    this.tailer = new LedgerTailer(this.ledgerDir(), project, this.io.tail, 4096, this.tailerOpts())
  }

  private ledgerDir(): string {
    // 引擎账本目录（t261001-12 与 event_ledger.py 同源：注入 > env 平铺缝 >
    // <projects_root>/<project>/ledger —— 活动文件名由事件账本文件路径给出，
    // 缺省 events.jsonl、平铺缝 <project>.jsonl，两种形状见 config.eventLedgerFile）。
    if (this.ledgerDirOpt) return this.ledgerDirOpt
    const env = process.env
    return env.SANDBAR_EVENT_LEDGER_DIR || join(projectsRoot(env), this.project, 'ledger')
  }
  private ledgerDirOpt: string | undefined

  /** 活动文件名形状（t261001-12，与 event_ledger.ledger_path 两种形状对齐）：
   *  注入目录 / env 平铺缝 = `<project>.jsonl`（返回空 opts）；缺省逐项目目录
   *  = 固定 events.jsonl。 */
  private tailerOpts(): { activeFile?: string } {
    if (this.ledgerDirOpt || process.env.SANDBAR_EVENT_LEDGER_DIR) return {}
    return { activeFile: 'events.jsonl' }
  }

  private get cfgEnabled(): boolean {
    return this.cfg.declared && this.cfg.enabled && this.cfg.config_error === null
  }

  private alertsPath(): string {
    return join(this.dataDir, `${this.project}.alerts.jsonl`)
  }

  private heartbeatPath(): string {
    return join(this.dataDir, `${this.project}.heartbeat.json`)
  }

  /** 启动即全量：不信任内存水位；账本从 0 重放；alerts.jsonl 重建去重集。 */
  async start(): Promise<void> {
    if (this.disposed) return
    if (!this.cfgEnabled) { this.phase = this.cfg.config_error ? 'config_error' : 'stopped'; return }
    this.phase = 'full_reconcile'
    // 账本全量重放（水位从零开始——不信任内存）。
    this.tailer = new LedgerTailer(this.ledgerDir(), this.project, this.io.tail, 4096, this.tailerOpts())
    const replay: LedgerRow[] = []
    for (;;) {
      const out = await this.tailer.poll()
      if (out.unreadable) { this.lastError = out.unreadable; break }
      replay.push(...out.rows)
      if (out.rows.length === 0 && !out.rotated) break
    }
    this.ledgerRows = replay
    this.startup.replayed_rows = replay.length
    // 启动重放本身就是推进证据（历史有事件 ≠ 死寂）：把基准点定在启动时刻，
    // 否则第一拍会把「刚全量读过的账」误判成 no_signal。
    if (replay.length > 0) this.lastProgressAt = this.now()
    // alerts.jsonl 重放 → 去重集（重启不重播：已报过的事从账里读回来）。
    const alertLines = await this.io.listAlerts(this.alertsPath())
    const rows = alertLines.map(l => { try { return JSON.parse(l) as Record<string, unknown> } catch { return null } }).filter((r): r is Record<string, unknown> => r !== null)
    this.dedupe = replayDedupe(rows, this.cfg.config.alerts.keep_days, this.now())
    this.startup.dedupe_keys = this.dedupe.size
    this.alerts = rows.slice(-200)
    await this.beat()
    await this.tickOnce()
    if (this.disposed || !this.cfgEnabled) return
    this.phase = 'running'
    this.timer = setInterval(() => { void this.onTimer() }, this.cfg.config.reconcile_seconds * 1000)
    // 定时器不挂进程退出（守望者随宿主进程走，timer 不阻止 dispose/unref 场景退出）。
    ;(this.timer as unknown as { unref?: () => void }).unref?.()
  }

  private async onTimer(): Promise<void> {
    if (this.disposed || this.inFlight) return // 单飞：上一拍没完不并发，节拍只丢不堆
    try { await this.tickOnce() } catch (e) { this.lastError = String(e instanceof Error ? e.message : e) }
  }

  private async beat(): Promise<void> {
    try {
      await this.io.heartbeat.write(this.heartbeatPath(), JSON.stringify({ last_beat: this.now() }))
    } catch (e) {
      // fail-open 且 LOUD（照 event_ledger 先例）：心跳写不进必须点名，绝不静默。
      this.lastError = `心跳写入失败（守望者将不可自证存活）：${e instanceof Error ? e.message : String(e)}`
    }
  }

  /** 落一条 alert（去重判定 → 落账 → 更新去重状态；夜间只影响发声不影响落账）。 */
  private async raise(spec: AlertSpec): Promise<void> {
    const nowMs = this.now()
    const judged = judgeAlert(this.cfg.config, spec, this.dedupe, nowMs)
    if (!judged.record) return
    const rec = alertRecord(spec, judged.key, nowMs, judged.night_muted)
    try {
      await this.io.appendAlerts(this.alertsPath(), JSON.stringify(rec))
    } catch (e) {
      this.lastError = `alerts 落账失败（不阻断主循环）：${e instanceof Error ? e.message : String(e)}`
    }
    applyDedupe(this.dedupe, judged.key, nowMs)
    this.alerts.push(rec)
    if (this.alerts.length > 200) this.alerts.splice(0, this.alerts.length - 200)
    this.unseenRedline.add(judged.key)
  }

  /**
   * 会话 id 确保面（t260930-09）：语义 =「未声明 = 按需创建；已声明 = 收养」。
   *  - 项目「有活」= 账本有事件行 或 看板有票——冻结遗留项目（无账本、无票）不建会话；
   *  - 已声明：只收养，进程生命周期内至多落一条 adopt 事件，绝不创建/绝不覆盖人的声明；
   *  - 未声明且有活：交注入的 sessionEnsure（node.ts=宿主 Session API create）；
   *    成功 = 会话 id 回写声明 + 记忆面就地生效；失败 = 显式 refused，节流重试；
   *  - 代建面未注入 = 维持旧行为（用声明 id，绝不猜）。
   */
  private async ensureSession(board: { ok: boolean; rows: BoardRow[] }, ledgerAdvanced: boolean, nowMs: number): Promise<string> {
    let sid = this.cfg.config.executor_session
    if (this.sessionEnsure === null) return sid
    const hasWork = this.ledgerRows.length > 0 || (board.ok && board.rows.length > 0)
    if (sid !== '') {
      if (this.ensureAdoptLogged) return sid
      this.ensureAdoptLogged = true
      const out = await this.sessionEnsure({ declaredSessionId: sid, hasWork })
      this.ensureState = { session_id: out.sessionId, last_action: out.action, reason: out.reason, declared_written: out.declaredWritten }
      return sid // 收养/重建判定不改本拍使用的 id（重建成功后声明已落盘，下一拍自然采用）
    }
    if (!hasWork) { this.ensureState = null; return sid }
    if (nowMs - this.lastEnsureFailAt < SESSION_ENSURE_RETRY_MS) return sid
    const out = await this.sessionEnsure({ declaredSessionId: '', hasWork })
    if (out.sessionId) {
      // 声明已回写（writeExecutorSession 过装载器校验）——内存面同步，本拍即可唤醒/观测。
      this.cfg = { ...this.cfg, config: { ...this.cfg.config, executor_session: out.sessionId } }
      sid = out.sessionId
      this.ensureAdoptLogged = true
      this.lastEnsureFailAt = Number.NEGATIVE_INFINITY
    } else if (out.action.startsWith('refused')) {
      this.lastEnsureFailAt = nowMs
    }
    this.ensureState = { session_id: out.sessionId, last_action: out.action, reason: out.reason, declared_written: out.declaredWritten }
    return sid
  }

  /** 一拍：beat → tail → reconcile → liveness → self-lock → exits。 */
  async tickOnce(): Promise<void> {
    if (this.disposed || !this.cfgEnabled) return
    this.inFlight = true
    this.aborted = false
    const nowMs = this.now()
    try {
      await this.beat()
      const out = await this.tailer.poll()
      if (out.unreadable) {
        this.lastError = out.unreadable
        await this.raise({ rule: 'ledger_unreadable', target: this.project, level: 'redline', title: `账本不可读（project ${this.project}）`, detail: out.unreadable })
      } else {
        this.lastError = null
        if (out.archive_gap > 0) {
          await this.raise({ rule: 'ledger_archive_gap', target: this.project, level: 'warn', title: `账本归档名序缺口 ${out.archive_gap}（project ${this.project}）`, detail: '轮转归档名序回跳——需要人看一眼归档是否被动过' })
        }
        if (this.tailer.state.unresolvedRotateTail) {
          await this.raise({ rule: 'ledger_rotate_tail', target: this.project, level: 'warn', title: `轮转残余未收全（project ${this.project}）`, detail: '轮转夹缝里的行没能从归档收齐——以对账面为准' })
          this.tailer.state.unresolvedRotateTail = false
        }
      }
      const newRows = out.rows
      this.ledgerRows.push(...newRows)
      if (this.ledgerRows.length > 20000) this.ledgerRows.splice(0, this.ledgerRows.length - 20000)
      const ledgerAdvanced = newRows.length > 0

      // 对账（心跳）：board 读不到 = degraded 显式，绝不是 ok。
      const board = await this.boardReader()
      if (this.aborted) return
      if (!board.ok) {
        this.reconcileState = degradedResult(board.error ?? 'board reader 失败', nowMs)
        await this.raise({ rule: 'reconcile_degraded', target: this.project, level: 'redline', title: `对账降级（project ${this.project}）`, detail: this.reconcileState.reason ?? '' })
      } else {
        const mism = compareStates(deriveTicketStates(this.ledgerRows), board.rows)
        const missing = countMissingRows(board.rows, this.ledgerRows)
        this.startup.missing_rows = missing
        if (mism.length > 0) {
          this.reconcileState = { state: 'mismatch', reason: `${mism.length} 票账本推演与看板不一致（以看板为准）`, since: nowMs, mismatches: mism.slice(0, 50) }
          await this.raise({ rule: 'reconcile_mismatch', target: this.project, level: 'redline', title: `对账不一致 ${mism.length} 票（project ${this.project}）`, detail: mism.slice(0, 5).map(m => `${m.ticket}: board=${m.board_state} ledger=${m.ledger_state}`).join('；') })
        } else {
          this.reconcileState = { state: 'ok', reason: null, since: nowMs, mismatches: [] }
        }
        if (missing > 0) await this.raise(makeMissingRowsSpec(this.project, missing))
      }

      // liveness：引擎存活（独立探针优先；无探针时板面读成功本身是在线的强证据）。
      if (this.engineProbe) {
        const eng = await this.engineProbe()
        if (this.aborted) return
        this.engineOnline = { online: eng.online, detail: eng.detail, checked_at: nowMs }
        if (!eng.online) await this.raise({ rule: 'engine_down', target: this.project, level: 'redline', title: `引擎不可达（project ${this.project}）`, detail: eng.detail })
      } else {
        this.engineOnline = { online: board.ok ? true : null, detail: board.ok ? 'ticket-list 可读（引擎在线）' : (board.error ?? '引擎不可达'), checked_at: nowMs }
        if (!board.ok) await this.raise({ rule: 'engine_down', target: this.project, level: 'redline', title: `引擎不可达（project ${this.project}）`, detail: board.error ?? '' })
      }
      // executor 会话推进探测（会话文件每拍查一次；失败=null 显式）。
      const sid = await this.ensureSession(board, ledgerAdvanced, nowMs)
      const sstat = await this.sessionStat(sid, this.lastSessionStatMs)
      if (this.aborted) return
      this.lastSessionStatMs = nowMs
      this.lastSessionAdvanced = sstat.advanced
      this.liveness = judgeExecutor(
        { sessionKnown: sid !== '', ledgerAdvanced, sessionProgress: sstat.advanced, lastWakeAt: this.wakes.length > 0 ? this.wakes[this.wakes.length - 1].at : null },
        nowMs, this.cfg.config.stall_minutes, this.lastProgressAt,
      )
      if (this.liveness.state === 'advancing') this.lastProgressAt = nowMs
      if (this.liveness.state === 'stalled') {
        await this.raise({ rule: 'stall', target: sid, level: 'redline', title: `executor 停摆（${sid}）`, detail: this.liveness.evidence })
      }

      // 自锁：provider 不可用 = unknown 显式（绝不冒充 none）。
      const pend = await this.pendingProvider()
      if (this.aborted) return
      this.selfLock = detectSelfLock(pend.pending, sid, nowMs, pend.reason)
      if (this.selfLock.state === 'waiting_on_itself') {
        await this.raise({ rule: 'self_lock', target: sid, level: 'redline', title: `executor 在等自己（${sid}）`, detail: this.selfLock.reason })
      }

      // 出口 (a) wake：值得醒才醒；我们自己的未消化简报不重发；自喂循环排除（WakeMemory）。
      if (newRows.length > 0 && this.wakeIo) {
        const level = this.selfLock.state === 'waiting_on_itself' || this.liveness.state === 'stalled' ? 'redline' : 'info'
        const r: WakeOutcome = await wakeExecutor(this.wakeIo, this.project, sid, newRows, this.selfLock.target, level, this.wakeMem)
        if (this.aborted) return
        if (r.woke) {
          this.wakes.push({ at: nowMs, ticket: newRows[newRows.length - 1].ticket, dedupe_key: makeKey('wake', sid), mode: r.mode, accepted: r.accepted })
          if (this.wakes.length > 100) this.wakes.splice(0, this.wakes.length - 100)
          this.lastProgressAt = nowMs
        } else if (r.accepted === false) {
          await this.raise({ rule: 'wake_failed', target: sid, level: 'warn', title: `唤醒投递失败（${sid}）`, detail: r.reason })
        }
      }
    } finally {
      this.inFlight = false
    }
  }

  /** dispose：全终态（定时器清、在飞拍标记 abort、投递面后台循环收口、心跳停）。 */
  dispose(): void {
    this.disposed = true
    this.aborted = true
    if (this.timer !== null) { clearInterval(this.timer); this.timer = null }
    void this.wakeIo?.dispose?.()
    this.phase = 'stopped'
  }

  /** 状态面（下一票面板消费的唯一形状；见 integration/t260928-28/panel-contract.md）。 */
  status(): WatchdogStatus {
    const nowMs = this.now()
    const beepKeys = [...this.unseenRedline].filter(k => {
      const rec = [...this.alerts].reverse().find(a => a.key === k)
      return rec ? rec.night_muted !== true : false
    })
    return {
      project: this.project,
      declared: this.cfg.declared,
      enabled: this.cfgEnabled,
      phase: this.phase,
      config_error: this.cfg.config_error,
      config_provenance: this.cfg.provenance,
      heartbeat: { last_beat: null, age_seconds: null, alive: false, reason: 'status() 不读盘（心跳由 readHeartbeat 在 node.ts 路由面读）' },
      ledger: {
        path: eventLedgerFile(this.project, process.env),
        watermark_offset: this.tailer.state.offset,
        rows_seen: this.tailer.state.rowsSeen,
        dupes_skipped: this.tailer.state.dupesSkipped,
        malformed_rows: this.tailer.state.malformedRows,
        gaps_seen: this.tailer.state.archiveGap,
        last_row_at: this.tailer.state.lastRowAt,
        unreadable: this.phase === 'running' ? null : (this.lastError ?? (this.phase === 'idle' ? '守望者尚未 start()——数据缺失，不是一切正常' : null)),
      },
      liveness: { engine: this.engineOnline, executor: this.liveness },
      self_lock: this.selfLock,
      reconcile: this.reconcileState,
      startup: this.startup,
      presumed_self_rows: this.wakeMem.presumedSelfRows,
      presumed_self_detail: this.wakeMem.presumedSelfDetail,
      queue_mirror: this.wakeIo?.transportState?.() ?? null,
      executor_session: this.ensureState,
      wakes: this.wakes.slice(-20),
      alerts: this.alerts.slice(-50),
      notify: { beep: this.cfg.config.alerts.enabled && this.cfg.config.alerts.sound && beepKeys.length > 0, unseen_redline: beepKeys.length },
      last_error: this.lastError,
    }
  }
}

/** 状态面补充：读盘心跳（node.ts 路由面组装用；core.status() 的 heartbeat 占位由它覆盖）。 */
export async function readHeartbeatFile(io: CoreIo, path: string, nowMs: number): Promise<WatchdogStatus['heartbeat']> {
  const { readHeartbeat } = await import('./liveness.ts')
  return readHeartbeat({ write: io.heartbeat.write, read: io.heartbeat.read, mtimeMs: io.heartbeat.mtimeMs }, path, nowMs, HEARTBEAT_STALE_MS)
}
