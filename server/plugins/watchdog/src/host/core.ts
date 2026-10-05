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

import { loadWatchdogConfig, watchdogDataDir, eventLedgerFile, projectsRoot, dshHome, type ResolvedConfig } from './config.ts'
import { LedgerTailer, deriveTicketStates, type LedgerRow, type TailIo } from './ledger-tail.ts'
import { compareStates, ledgerCoverage, degradedResult, makeMissingRowsSpec, type BoardRow, type ReconcileResult } from './reconcile.ts'
import { judgeExecutor, type ExecutorLiveness } from './liveness.ts'
import { judgeAskMirror, collectDeliverRefusals, type PendingAskLike } from './ask-loud.ts'
import { detectSelfLock, type PendingInteraction, type SelfLockVerdict } from './self-lock.ts'
import { detectWaitingFace, type WaitingFace } from './waiting-face.ts'
import { decideProseBackstop, journalLine, replayJournal } from './prose-backstop.ts'
import { applyDedupe, judgeAlert, makeKey, replayDedupe, type AlertSpec, type DedupeState } from './alert-rules.ts'
import { alertRecord, freshWakeMemory, wakeExecutor, requestAnswerRow, alertClearedRow, type WakeIo, type WakeMemory, type WakeOutcome, type WakeReceipt } from './exits.ts'

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
  /** executor 会话文件的 (size,mtime) 前进探测；null = 会话文件不可读。
   *  running = 会话本拍是否在跑（宿主 running 位，t261004-12）；null = 本拍没读到。 */
  (sessionId: string, sinceMs: number): Promise<{ advanced: boolean | null; mtimeMs: number | null; running: boolean | null }>
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
  /** t261004-08: the executor session's running bit this cycle (session snapshot;
   *  null = snapshot missing — the waiting face goes explicitly unknown, never idle).
   *  Not injected = null (face reads unknown, never fakes normal). */
  waitingRunningLookup?: (sessionId: string) => boolean | null
  /** t261004-08: recent-round-text reader (host page/follow; failure = ok:false with an explicit reason). */
  recentText?: (sessionId: string) => Promise<RecentTextResult>
  /** t261004-08: prose-backstop ledger face (request-ledger read/write + journal; assembled in node.ts). */
  proseBackstopIo?: ProseBackstopIo
}

/** Recent-round-text read result (ok:false = host history face absent / call failed / malformed receipt — named explicitly). */
export type RecentTextResult = { ok: true; text: string } | { ok: false; reason: string }

/** Prose-backstop ledger seam (orchestrated by core, implemented in node.ts over the
 *  panel request ledger + the watchdog data root; UTs inject in-memory stubs). */
export interface ProseBackstopIo {
  /** Attribution projection of all unanswered (waiting) rows; ok:false = ledger read failed (fail loud, never file blind). */
  readWaiting(): Promise<{ ok: true; rows: Array<{ id: string; raisedBy: string }> } | { ok: false; reason: string }>
  /** File one backstop request row attributed to the session (kind=question, detail quotes the sentence and names the session). */
  append(args: { sessionId: string; sentence: string }): Promise<{ ok: true; requestId: string } | { ok: false; reason: string }>
  /** Journal (idempotency log) read/write. */
  readJournal(): Promise<string[]>
  appendJournal(line: string): Promise<void>
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
  /** t261004-08 additive: the "executor waiting on the host" observation face
   *  (observe-only, no alert; alerting goes through the self_lock escalation — one
   *  rule, one key, review C1 ruling). unknown = face absent, never reads as normal. */
  waiting_on_host: WaitingFace
  /** t261004-08 additive: prose backstop (prose-ask filing) latest decision. */
  prose_backstop: { state: string; last_request_id: string | null; reason: string | null }
  reconcile: ReconcileResult | null
  startup: { missing_rows: number | null; replayed_rows: number | null; dedupe_keys: number }
  /** t261004-13 additive：缺行覆盖两桶（在飞缺口进告警；终态缺口只在此可见）。 */
  ledger_coverage: { in_flight_missing: string[]; terminal_missing: string[] } | null
  /** t260929-04 additive：自醒排除的响亮计数与最近证据（review C1 的审计面）。 */
  presumed_self_rows: number
  presumed_self_detail: string | null
  /** t260929-04 additive：队列镜像/投递通路状态串（null = 镜像面未注入）。 */
  queue_mirror: string | null
  /** t260930-09 additive：按需代建面最近一次结果（null = 未注入代建面）。 */
  executor_session: { session_id: string | null; last_action: string | null; reason: string | null; declared_written: boolean } | null
  wakes: Array<{ at: number; ticket: string; dedupe_key: string; mode: string | null; accepted: boolean | null }>
  /** t261003-15 additive：最近一拍的唤醒裁决（醒没醒 / 为什么 / 考虑几行）。
   *  null = 尚未有拍走到唤醒步（守望者未 start 或刚启动）；运行中的拍不留空。 */
  last_wake_verdict: { at: number; woke: boolean; reason: string; considered: number; presumed_self: number } | null
  /** t261004-29 additive: push-path wake receipt ring (last 20). Every
   *  attempted:false carries its reason — "was a wake attempted and why not" stays
   *  answerable from the status face, not only inside the HTTP response. */
  wake_receipts: WakeReceipt[]
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
  private configDirEnv: NodeJS.ProcessEnv | undefined

  private dedupe: DedupeState = new Map()
  private ledgerRows: LedgerRow[] = []
  private lastProgressAt: number | null = null
  private lastSessionStatMs = 0
  private lastSessionAdvanced: boolean | null = null
  private engineOnline: { online: boolean | null; detail: string; checked_at: number | null } = { online: null, detail: '尚未探测', checked_at: null }
  private reconcileState: ReconcileResult | null = null
  private selfLock: SelfLockVerdict | null = null
  /** t261004-08：waiting-on-host 观测面（首拍前 = unknown，绝不冒充正常）。 */
  private waitingOnHost: WaitingFace = { state: 'unknown', asks: [], sinceMs: null, reason: 'not yet evaluated (watchdog not started / first tick pending) — explicitly unknown' }
  /** t261004-08：prose backstop 最近一次评判定语。 */
  private proseBackstop: WatchdogStatus['prose_backstop'] = { state: 'unknown', last_request_id: null, reason: 'not yet evaluated (watchdog not started / first tick pending) — explicitly unknown' }
  private proseJournal: Array<{ key: string; requestId: string }> = []
  private waitingRunningLookup: ((sessionId: string) => boolean | null) | null
  private recentText: (() => Promise<RecentTextResult>) | null
  private proseIo: ProseBackstopIo | null
  private liveness: ExecutorLiveness | null = null
  private startup: { missing_rows: number | null; replayed_rows: number | null; dedupe_keys: number } = { missing_rows: null, replayed_rows: null, dedupe_keys: 0 }
  private ledgerCoverageState: WatchdogStatus['ledger_coverage'] = null
  private wakes: WatchdogStatus['wakes'] = []
  /** 最近一拍唤醒裁决（t261003-15）：每条拍路径都显式落（见 tick 内 wake 步注释）。 */
  private lastWakeVerdict: WatchdogStatus['last_wake_verdict'] = null
  /** 自醒排除记忆（t260929-04）：随实例存活；dispose 即随进程终态。 */
  private wakeMem: WakeMemory = freshWakeMemory()
  /** t261004-29 push-path wake receipt ring (one entry per requestWake / clear tick, keep 20). */
  private wakeReceipts: WakeReceipt[] = []
  /** t261004-29 alert-clear detection: dedupe keys whose alert rule was touched by
   *  raise() this tick (the condition still holds). A cooldown-muted raise still
   *  counts — "condition holds but muted" is not "condition cleared". */
  private condActive = new Set<string>()
  /** Previous tick's condition-active key set; the diff between the two = clears.
   *  Empty before the first tick, so a restart can never emit a phantom clear. */
  private lastCondActive = new Set<string>()
  /** t261004-29 fire-episode id per key: the timestamp of the latest touch (raise
   *  call) while the condition holds. Every touch refreshes it — so a re-fire after
   *  a clear starts a NEW episode even inside the alert cooldown (no ledger record
   *  needed), and its later clear is a fresh ticket that wakes again. */
  private episodeBy = new Map<string, number>()
  private alerts: Array<Record<string, unknown>> = []
  private unseenRedline = new Set<string>()
  private lastError: string | null = null
  // 代建面（t260930-09）：收养每进程只记一次；失败重试节流；最近结果进状态面。
  private ensureAdoptLogged = false
  private lastEnsureFailAt = Number.NEGATIVE_INFINITY
  private ensureState: WatchdogStatus['executor_session'] = null
  /** t261004-44: first sighting per watched pending ask (in-memory = a lower bound
   *  of the ask age; cleared once the mirror row lands). */
  private askMirrorFirstSeen = new Map<string, number>()
  phase: CorePhase = 'idle'

  constructor(project: string, deps: WatchdogDeps = {}) {
    this.project = project
    this.configDirEnv = deps.configDirEnv
    this.io = deps.io ?? defaultIo
    this.now = deps.now ?? Date.now
    this.boardReader = deps.boardReader ?? (async () => ({ ok: false, rows: [], error: 'boardReader 未注入（实现期由 node.ts 提供 engine client.py spawn）' }))
    this.engineProbe = deps.engineProbe ?? null
    this.wakeIo = deps.wakeIo ?? null
    this.pendingProvider = deps.pendingProvider ?? (async () => ({ available: false, pending: null, reason: '宿主侧待办交互面未接入（S1-probe 后续票落地）——显式 unknown' }))
    this.sessionStat = deps.sessionStat ?? (async () => ({ advanced: null, mtimeMs: null, running: null }))
    this.sessionEnsure = deps.sessionEnsure ?? null
    this.waitingRunningLookup = deps.waitingRunningLookup ?? null
    this.recentText = deps.recentText ?? null
    this.proseIo = deps.proseBackstopIo ?? null
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
    // t261004-08: prose-backstop journal replay (a restart does not re-file the same ask — facts are read from the ledger, not memory).
    if (this.proseIo !== null) {
      try {
        const replayed = replayJournal(await this.proseIo.readJournal())
        this.proseJournal = replayed.entries
        if (replayed.malformed > 0) this.lastError = `prose backstop journal has ${replayed.malformed} malformed row(s) (skipped; remaining rows keep muting)`
      } catch (e) {
        // Journal unreadable = idempotency layer (b) missing, only the ledger coverage check remains — named explicitly, never silent.
        this.lastError = `prose backstop journal read failed (the same sentence may file one more row after a restart): ${e instanceof Error ? e.message : String(e)}`
      }
    }
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

  /** 实例隔离域（t261001-19）：dedupe key 必须带 DSH_HOME 派生的 scope——同一台机器上
   *  临时 home 的场景实例与真宿主共享 alerts.jsonl 时，不得互相静音（真机 261001 实证：
   *  临时 home 一次报警把真宿主 18 次 refused 静音 12 小时）。 */
  private instanceScope(): string {
    // t261003-04：与 config.dshHome 同一词表（实例身份只算一份，禁再各算一版）。
    return dshHome(this.configDirEnv ?? process.env)
  }

  /** 落一条 alert（去重判定 → 落账 → 更新去重状态；夜间只影响发声不影响落账）。 */
  private async raise(spec: AlertSpec): Promise<void> {
    const nowMs = this.now()
    // scope：调用方未显式指定时统一按本实例隔离域隔离（口径一处定，全部规则生效）。
    const scoped = spec.scope ?? this.instanceScope()
    const full: AlertSpec = scoped === '' ? spec : { ...spec, scope: scoped }
    const judged = judgeAlert(this.cfg.config, full, this.dedupe, nowMs)
    // t261004-29: register that this key's alert condition was touched this tick
    // (before the cooldown verdict) — a cooldown-muted tick still counts as active;
    // clear detection consumes this holds/does-not-hold fact, not the ledger fact.
    // The touch timestamp is the fire-episode id (see episodeBy / takeAlertClears).
    this.condActive.add(judged.key)
    this.episodeBy.set(judged.key, nowMs)
    if (!judged.record) return
    const rec = alertRecord(full, judged.key, nowMs, judged.night_muted)
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

  /** t261004-29: alert-clear detection + key-set rotation (called exactly once per
   *  tick, before the wake step). Keys active last tick but not this tick = cleared;
   *  the episode id is the key's latest touch timestamp (episodeBy — refreshed on
   *  every raise while the condition holds, cooldown-independent, so a re-fire after
   *  a clear starts a NEW episode and its later clear is a fresh ticket that wakes
   *  again; a second clear of the same episode cannot happen — the condition no
   *  longer holds, raise() never registers it). No episode fact on record = no
   *  synthetic row — an episode is never invented. lastCondActive is empty before
   *  the first tick, so a restart emits no phantom clear. */
  private takeAlertClears(): LedgerRow[] {
    const cleared: LedgerRow[] = []
    for (const key of this.lastCondActive) {
      if (this.condActive.has(key)) continue
      const episode = this.episodeBy.get(key)
      if (typeof episode !== 'number' || !Number.isFinite(episode)) continue
      cleared.push(alertClearedRow(this.project, key, episode))
    }
    this.lastCondActive = this.condActive
    return cleared
  }

  /** t261004-29: session-ensure face for the push path — same semantics as
   *  ensureSession (undeclared = create on demand; declared = use it; the failure
   *  retry shares SESSION_ENSURE_RETRY_MS, so an answer inside the throttle window
   *  gets woke=false with ensureState naming the reason — no second retry discipline
   *  is invented beside it). */
  private async sessionIdForWake(nowMs: number): Promise<string> {
    if (this.cfg.config.executor_session !== '' || this.sessionEnsure === null) return this.cfg.config.executor_session
    if (nowMs - this.lastEnsureFailAt < SESSION_ENSURE_RETRY_MS) return this.cfg.config.executor_session
    const out = await this.sessionEnsure({ declaredSessionId: '', hasWork: true })
    if (out.sessionId) {
      // Declaration written back (writeExecutorSession passed the loader check) —
      // in-memory face synced so this very call can wake.
      this.cfg = { ...this.cfg, config: { ...this.cfg.config, executor_session: out.sessionId } }
      this.lastEnsureFailAt = Number.NEGATIVE_INFINITY
    } else if (out.action.startsWith('refused')) {
      this.lastEnsureFailAt = nowMs
    }
    this.ensureState = { session_id: out.sessionId, last_action: out.action, reason: out.reason, declared_written: out.declaredWritten }
    return this.cfg.config.executor_session
  }

  private rememberReceipt(r: WakeReceipt): WakeReceipt {
    this.wakeReceipts.push(r)
    if (this.wakeReceipts.length > 20) this.wakeReceipts.splice(0, this.wakeReceipts.length - 20)
    return r
  }

  /** t261004-29: push-path wake (the host answered a request). The same wakeExecutor
   *  path — the synthetic row passes the worthWaking gate and the self-feed guard
   *  ①②③ still governs; mode is always queue (an answer is not a redline interrupt;
   *  steer stays redline-only). The receipt's attempted/woke/reason are explicit on
   *  every path: project not declared, transport not injected, session not ensurable
   *  (attempted:false quoting the refusal — nothing was delivered), brief still
   *  undigested, delivery refused / transport failed — each lands a reason, never silence. */
  async requestWake(args: { requestId: string; by?: string; detail?: string }): Promise<WakeReceipt> {
    const nowMs = this.now()
    if (!this.cfgEnabled) {
      return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: args.requestId, attempted: false, woke: false, mode: null, accepted: null,
        reason: this.cfg.config_error !== null ? `config_error: ${this.cfg.config_error}` : 'project not declared/enabled — watchdog body zero-behavior' })
    }
    if (typeof args.requestId !== 'string' || args.requestId === '') {
      return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: null, attempted: false, woke: false, mode: null, accepted: null,
        reason: 'request_id must be a non-empty string — malformed push refused, nothing delivered' })
    }
    if (!this.wakeIo) {
      return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: args.requestId, attempted: false, woke: false, mode: null, accepted: null,
        reason: 'no wake transport injected (wakeIo=null) — explicit no-op' })
    }
    const sid = await this.sessionIdForWake(nowMs)
    if (sid === '') {
      return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: args.requestId, attempted: false, woke: false, mode: null, accepted: null,
        reason: `no executor session to wake (declared id empty and ensure did not produce one)${this.ensureState?.reason ? `: ${this.ensureState.reason}` : ' — wake not attempted'}` })
    }
    // Self-feed guard, mirror-first leg (t261004-29 arbitrate round 1): the push path
    // consults the queue mirror BEFORE deciding, even when no brief id is on record
    // yet — a mirror that says our brief is still pending suppresses the push with a
    // named reason (an answer must not stack on top of an undigested brief; this is
    // rule ③'s source-agnostic face, not a second guard). The production mirror face
    // is requestId-keyed, so with no id on record it answers false/null and the
    // decision falls through to wakeExecutor's own guard unchanged.
    if (typeof this.wakeIo!.ourBriefPending === 'function') {
      let pending: boolean | null = null
      try {
        pending = await this.wakeIo!.ourBriefPending(sid, this.wakeMem.lastRequestId ?? '')
      } catch (e) {
        // Mirror throw = unreadable (explicit no-signal): fall through to wakeExecutor's
        // guard, which re-consults and lands its own no-signal honesty in the reason.
        this.lastError = `wake push queue-mirror probe failed (falling through to the wake gate): ${e instanceof Error ? e.message : String(e)}`
      }
      if (pending === true) {
        return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: args.requestId, attempted: false, woke: false, mode: null, accepted: null,
          reason: `queue mirror reports our brief still undigested (last brief on record: ${this.wakeMem.lastRequestId ?? 'none'}) — not re-delivering on top of it` })
      }
    }
    const row = requestAnswerRow(this.project, args.requestId, args.by ?? 'host', args.detail ?? '')
    const r: WakeOutcome = await wakeExecutor(this.wakeIo, this.project, sid, [row], this.selfLock?.target ?? null, 'info', this.wakeMem)
    if (r.woke) {
      this.wakes.push({ at: nowMs, ticket: row.ticket, dedupe_key: makeKey('wake', sid), mode: r.mode, accepted: r.accepted })
      if (this.wakes.length > 100) this.wakes.splice(0, this.wakes.length - 100)
      this.lastProgressAt = nowMs
    }
    return this.rememberReceipt({ at: nowMs, source: 'request-answer', request_id: args.requestId, attempted: true, woke: r.woke, reason: r.reason, mode: r.mode, accepted: r.accepted })
  }

  /** 一拍：beat → tail → reconcile → liveness → self-lock → exits。 */
  async tickOnce(): Promise<void> {
    if (this.disposed || !this.cfgEnabled) return
    this.inFlight = true
    this.aborted = false
    this.condActive = new Set() // t261004-29: this tick's condition-active set collected from zero (see raise / takeAlertClears)
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
        // 缺行覆盖（t261004-13）：只有账本**零行**覆盖的在飞票进告警；终态缺口只进状态面。
        const coverage = ledgerCoverage(board.rows, this.ledgerRows)
        this.ledgerCoverageState = coverage
        this.startup.missing_rows = coverage.in_flight_missing.length
        if (mism.length > 0) {
          this.reconcileState = { state: 'mismatch', reason: `${mism.length} 票账本推演与看板不一致（以看板为准）`, since: nowMs, mismatches: mism.slice(0, 50) }
          await this.raise({ rule: 'reconcile_mismatch', target: this.project, level: 'redline', title: `对账不一致 ${mism.length} 票（project ${this.project}）`, detail: mism.slice(0, 5).map(m => `${m.ticket}: board=${m.board_state} ledger=${m.ledger_state}`).join('；') })
        } else {
          this.reconcileState = { state: 'ok', reason: null, since: nowMs, mismatches: [] }
        }
        if (coverage.in_flight_missing.length > 0) await this.raise(makeMissingRowsSpec(this.project, coverage.in_flight_missing))
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
        { sessionKnown: sid !== '', ledgerAdvanced, sessionProgress: sstat.advanced, lastWakeAt: this.wakes.length > 0 ? this.wakes[this.wakes.length - 1].at : null, sessionRunning: sstat.running },
        nowMs, this.cfg.config.stall_minutes, this.lastProgressAt, this.cfg.config.long_turn_minutes,
      )
      // t261001-19 缺陷 A 修复：基准点从判活结果的 last_progress_at 回灌——判活只在
      // 真有进展（账本/会话文件/唤醒任一）时才把基准点拨到本拍。旧写法按
      // state==='advancing' 刷新，而「无推进但未达阈值」的宽限拍也是 advancing ⇒
      // 每拍把静默计时清零 ⇒ silentMs 永远从 0 重新起算 ⇒ stall 分支不可达（stall
      // 规则在红线名单里却永远不可能响——挂死/死透的 executor 被永久报成健康）。
      this.lastProgressAt = this.liveness.last_progress_at
      if (this.liveness.state === 'stalled') {
        await this.raise({ rule: 'stall', target: sid, level: 'redline', title: `executor 停摆（${sid}）`, detail: this.liveness.evidence })
      }
      // t261004-12：running=true 的长静默是独立 case（long_turn）——不是停摆，不进
      // 红线名单，但超长回合阈值该让人看一眼：warn 级、同一去重/冷却路径。
      if (this.liveness.state === 'long_turn') {
        await this.raise({
          rule: 'executor_long_turn', target: sid, level: 'warn',
          title: `executor long turn in progress (${sid})`,
          detail: this.liveness.evidence,
        })
      }
      // t261001-13：executor 缺席必须响——「账本有事件/看板有票但 executor 从未起来」
      // 不是正常态，是整个推进环的死寂（真机 261001 实证：18 次 refused 零报警）。
      // liveness.state==='missing' 且项目有活 → executor_missing（redline 名单内）。
      const hasWork = this.ledgerRows.length > 0 || (board.ok && board.rows.length > 0)
      if (this.liveness.state === 'missing' && hasWork) {
        await this.raise({
          rule: 'executor_missing', target: this.project, level: 'redline',
          title: `executor 会话缺失（project ${this.project}）`,
          detail: this.ensureState?.reason ?? this.liveness.evidence,
        })
      }
      // 代建/收养面被点名拒绝（refused-*）→ 独立规则响一次（去重冷却节流），
      // 拒绝原因（如 preset 未安装）进 detail——拒绝不再是只有面板才看得见的静默。
      if (this.ensureState !== null && typeof this.ensureState.last_action === 'string' && this.ensureState.last_action.startsWith('refused')) {
        await this.raise({
          rule: 'executor_session_refused', target: this.project, level: 'redline',
          title: `executor 会话代建被拒（project ${this.project}）`,
          detail: this.ensureState.reason ?? this.ensureState.last_action,
        })
      }

      // Self-lock: provider unavailable = explicit unknown (never fakes none).
      // t261004-08: escalation threshold = config.waiting_minutes (waiting_on_itself
      // fires only past the threshold; inside it `waiting` is status-face only).
      // Alert dedupe target is now the request id — one alert per ask, asks independent.
      const pend = await this.pendingProvider()
      if (this.aborted) return
      // Old config shapes lack waiting_minutes (in-memory stubs / existing declarations) → threshold 0 = immediate escalation (legacy semantics).
      const waitingThresholdMs = (typeof this.cfg.config.waiting_minutes === 'number' ? this.cfg.config.waiting_minutes : 0) * 60_000
      this.selfLock = detectSelfLock(pend.pending, sid, nowMs, pend.reason, { waitingThresholdMs })
      if (this.selfLock.state === 'waiting_on_itself') {
        await this.raise({ rule: 'self_lock', target: this.selfLock.target ?? sid, level: 'redline', title: `executor waiting on itself (${sid})`, detail: this.selfLock.reason })
      }

      // waiting-on-host observation face (t261004-08): always-on status key, no
      // alert, no level raise — a below-threshold wait and a cooldown-muted wait both
      // stay visible here. Snapshot missing = explicit unknown.
      const waitingRunning = this.waitingRunningLookup !== null ? this.waitingRunningLookup(sid) : null
      this.waitingOnHost = detectWaitingFace({ pending: pend.pending, sessionId: sid, running: waitingRunning, nowMs })

      // t261004-44 (KI-196 judgement): ask-mirror watch -- a session sitting on
      // ask_user_question with no question row for it past ask_mirror_deadline_s
      // raises the ask_unmirrored redline (a bridge that does not fire has a voice).
      // First-sighting is tracked in memory (a lower bound of the age: reporting late
      // beats never); the watch clears as soon as the row lands.
      const askPending = (pend.pending ?? []).filter(p => p !== null && typeof p === 'object' && (p as PendingInteraction).kind === 'question')
      for (const p of askPending) {
        const j = judgeAskMirror({
          pending: p as PendingAskLike,
          ledgerRows: this.ledgerRows,
          firstSeenMs: this.askMirrorFirstSeen.get((p as PendingAskLike).raisedBy as string),
          deadlineMs: (typeof this.cfg.config.ask_mirror_deadline_s === 'number' && this.cfg.config.ask_mirror_deadline_s > 0
            ? this.cfg.config.ask_mirror_deadline_s : 120) * 1000,
          nowMs,
        })
        if (j.action === 'raise') {
          await this.raise({
            rule: 'ask_unmirrored', target: j.sessionId, level: 'redline',
            title: `session ${j.sessionId} waits on ask_user_question with no ledger row (ask face)`,
            detail: j.detail,
          })
          this.askMirrorFirstSeen.set(j.sessionId, j.sinceMs) // do not move the baseline up again within the dedupe cooldown
        } else if (j.action === 'watch') {
          if (!this.askMirrorFirstSeen.has(j.sessionId)) this.askMirrorFirstSeen.set(j.sessionId, j.sinceMs)
        } else if (j.action === 'forget') {
          this.askMirrorFirstSeen.delete(j.sessionId)
        }
      }

      // t261004-44 (KI-197 judgement): a deliver_refused row in the event ledger
      // raises the redline with the refusal text intact in the detail -- "this face is
      // dead" must reach the human. Malformed rows are counted into lastError (named
      // skip, never silent).
      {
        const { refusals, malformed } = collectDeliverRefusals(this.ledgerRows)
        for (const r of refusals) {
          await this.raise({
            rule: 'deliver_refused', target: r.sessionId, level: 'redline',
            title: `deliver face refused for session ${r.sessionId} (deliver face)`,
            detail: r.detail,
          })
        }
        if (malformed > 0) {
          this.lastError = `deliver_refused rows: ${malformed} row(s) without a session attribution skipped (named, not silent)`
        }
      }


      // prose backstop (t261004-08): files a prose ask as a request row (decision in
      // the pure core prose-backstop.ts; row write / alerting / journal orchestrated
      // here; every unknown shape raises prose_backstop_unknown, never silence).
      await this.runProseBackstop(sid, sstat.mtimeMs, nowMs)

      // 出口 (a) wake：值得醒才醒；我们自己的未消化简报不重发；自喂循环排除（WakeMemory）。
      // t261004-29: beyond new ledger rows, an alert key active last tick but not
      // this tick = cleared — also a wake-worthy event. Its synthetic row joins the
      // same wake cycle (same wakeIo, same WakeMemory, same verdict face).
      // takeAlertClears also rotates "this tick -> last tick"; lastCondActive is
      // empty on the first tick, so a restart never emits a phantom clear.
      const clearRows = this.takeAlertClears()
      const wakeRows = [...newRows, ...clearRows]
      // t261003-15：本拍唤醒裁决（无论醒不醒）都落 lastWakeVerdict——状态面可答
      // 「为什么没醒」，不再需要翻 executor 会话日志。每条路径（含无新行/无投递面/
      // 无会话 id 的跳过拍）都给显式 reason，运行中的拍绝不留空裁决。
      if (!this.wakeIo) {
        this.lastWakeVerdict = { at: nowMs, woke: false, reason: '本实例未注入投递面（wakeIo=null）——显式不作为', considered: 0, presumed_self: 0 }
      } else if (wakeRows.length === 0) {
        this.lastWakeVerdict = { at: nowMs, woke: false, reason: '本拍无新账本行', considered: 0, presumed_self: this.wakeMem.presumedSelfRows }
      } else {
        const level = this.selfLock.state === 'waiting_on_itself' || this.liveness.state === 'stalled' ? 'redline' : 'info'
        const r: WakeOutcome = await wakeExecutor(this.wakeIo, this.project, sid, wakeRows, this.selfLock.target, level, this.wakeMem)
        if (this.aborted) return
        this.lastWakeVerdict = { at: nowMs, woke: r.woke, reason: r.reason, considered: r.considered ?? 0, presumed_self: r.presumedSelf ?? this.wakeMem.presumedSelfRows }
        if (r.woke) {
          this.wakes.push({ at: nowMs, ticket: wakeRows[wakeRows.length - 1].ticket, dedupe_key: makeKey('wake', sid), mode: r.mode, accepted: r.accepted })
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

  /** prose-backstop orchestration (t261004-08): the decision lives in the pure core;
   *  this only reads the ledger, writes the row, appends the journal, raises alerts.
   *  Fail loud: unreadable text / ledger read failure / row-write failure → status
   *  key unknown + one prose_backstop_unknown (dedupe-throttled), never "nothing to
   *  report". */
  private async runProseBackstop(sid: string, mtimeMs: number | null, nowMs: number): Promise<void> {
    // Old config shapes lack the prose_backstop key (in-memory stubs / existing
    // declarations) → the backstop face is explicitly off (not silently broken).
    const cfg = this.cfg.config.prose_backstop ?? { enabled: false, idle_minutes: 10 }
    if (!cfg.enabled) {
      this.proseBackstop = { state: 'off', last_request_id: null, reason: 'prose_backstop.enabled=false — backstop explicitly off' }
      return
    }
    if (this.proseIo === null || this.recentText === null) {
      this.proseBackstop = { state: 'off', last_request_id: null, reason: 'backstop face not injected (headless or not wired) — explicitly off, not "no prose asks"' }
      return
    }
    let text: string | null = null
    let faceFailure: string | null = null
    try {
      const r = await this.recentText(sid)
      if (r.ok) text = r.text
      else faceFailure = r.reason
    } catch (e) {
      faceFailure = `recent-round-text reader threw: ${e instanceof Error ? e.message : String(e)}`
    }
    const idleMinutes = mtimeMs !== null && Number.isFinite(mtimeMs) ? (nowMs - mtimeMs) / 60_000 : null
    const waiting = await this.proseIo.readWaiting().catch((e: unknown) => ({ ok: false as const, reason: `request ledger read failed: ${e instanceof Error ? e.message : String(e)}` }))
    if (!waiting.ok) {
      this.proseBackstop = { state: 'unknown', last_request_id: null, reason: waiting.reason }
      await this.raise({ rule: 'prose_backstop_unknown', target: this.project, level: 'warn', title: `prose backstop: request ledger unreadable (project ${this.project})`, detail: waiting.reason })
      return
    }
    const decision = decideProseBackstop({
      cfg: { enabled: cfg.enabled, idleMinutes: cfg.idle_minutes },
      sessionId: sid,
      text,
      idleMinutes,
      waitingRows: waiting.rows,
      journal: this.proseJournal,
    })
    if (decision.action === 'filed') {
      const appended = await this.proseIo.append({ sessionId: sid, sentence: decision.sentence })
      if (!appended.ok) {
        this.proseBackstop = { state: 'unknown', last_request_id: null, reason: `failed to file the request row: ${appended.reason}` }
        await this.raise({ rule: 'prose_backstop_unknown', target: this.project, level: 'warn', title: `prose backstop: failed to file the request row (project ${this.project})`, detail: appended.reason })
        return
      }
      try {
        await this.proseIo.appendJournal(journalLine(decision.key, appended.requestId, nowMs))
      } catch (e) {
        // Journal write failure = the same ask may file one more row after a restart (idempotency layer b missing) — named, the ledger row is not rolled back.
        this.lastError = `prose backstop journal write failed: ${e instanceof Error ? e.message : String(e)}`
      }
      this.proseJournal.push({ key: decision.key, requestId: appended.requestId })
      this.proseBackstop = { state: 'filed', last_request_id: appended.requestId, reason: `prose ask filed (quote: ${decision.sentence.slice(0, 80)})` }
      await this.raise({
        rule: 'prose_ask_filed', target: appended.requestId, level: 'warn',
        title: `executor prose ask filed as a request (${sid})`,
        detail: `Quote: "${decision.sentence}" (session ${sid}) — prose backstop heuristic hit (marker list in prose-backstop.ts)`,
      })
      return
    }
    if (decision.action === 'no-marker' && faceFailure !== null) {
      const reason = `${faceFailure}${idleMinutes === null ? '; idle duration unreadable (snapshot missing)' : ''} — explicitly unknown, never "nothing to report"`
      this.proseBackstop = { state: 'unknown', last_request_id: null, reason }
      await this.raise({ rule: 'prose_backstop_unknown', target: this.project, level: 'warn', title: `prose backstop: host face unreadable (project ${this.project})`, detail: reason })
      return
    }
    if (decision.action === 'no-marker' && idleMinutes === null) {
      const reason = 'recent round text readable but idle duration unreadable (snapshot missing) — explicitly unknown, never fakes "not waiting"'
      this.proseBackstop = { state: 'unknown', last_request_id: null, reason }
      await this.raise({ rule: 'prose_backstop_unknown', target: this.project, level: 'warn', title: `prose backstop: session snapshot missing (project ${this.project})`, detail: reason })
      return
    }
    const stateMap: Record<string, string> = {
      'not-idle': 'idle', 'no-marker': 'clear', 'skipped-covered-by-ledger': 'covered',
      'already-filed': 'covered', 'no-session': 'off', off: 'off',
    }
    this.proseBackstop = { state: stateMap[decision.action] ?? 'unknown', last_request_id: null, reason: decision.reason }
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
      heartbeat: { last_beat: null, age_seconds: null, alive: false, reason: 'status() does not touch disk (the heartbeat is read by readHeartbeat in the node.ts routing face)' },
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
      waiting_on_host: this.waitingOnHost,
      prose_backstop: this.proseBackstop,
      reconcile: this.reconcileState,
      startup: this.startup,
      ledger_coverage: this.ledgerCoverageState,
      presumed_self_rows: this.wakeMem.presumedSelfRows,
      presumed_self_detail: this.wakeMem.presumedSelfDetail,
      queue_mirror: this.wakeIo?.transportState?.() ?? null,
      executor_session: this.ensureState,
      wakes: this.wakes.slice(-20),
      last_wake_verdict: this.lastWakeVerdict,
      wake_receipts: this.wakeReceipts.slice(-20),
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



