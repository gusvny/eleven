/**
 * sandbar-watchdog —— 守望者（epic project-executor 第三片，t260928-28）宿主半插件。
 *
 * 是什么：住在本控制台宿主进程里的**非 agent、非 workflow** 组件——读事件账、判活、
 * 对账看板、唤醒 executor、叫人（全部可配置）。一进程看多项目，按项目分账。
 * 绝不重启/停止/占用控制台（3099 是用户面）；测试不碰生产 Temporal。
 *
 * 设计基准：notes/discussions/260927-项目执行器-设计稿.md（守望者框；决策 1/4/6/9；
 * 重启与孤儿协议）+ 本票过审方案 .sandbar/plan_watchdog.md（gen1）。
 *
 * 挂载与降级（头注自述纪律，KI-079 族）：
 *  - web profile：宿主半在 dsh webServer 上挂 GET /sandbar-watchdog/api/status（只读）。
 *  - headless profile：无 webServer，本插件待机（定时器面照常起——守望者本体不依赖
 *    webServer；只有状态读面缺席，且 headless 形态本来没有面板）。
 *  - 未声明项目（无 watchdog.json）：守望者本体不自动起（无配置=无节拍参数），
 *    但**有活的未声明项目会被按需代建 executor 会话**（t260930-09 宿主决策：
 *    「未声明 = 按需创建；已声明 = 收养」——人不供 id）。preset 缺失/注册表缺席
 *    = 显式拒绝并点名，绝不猜、绝不拿默认会话充数；每次 create/recreate/adopt
 *    落一条溯源事件（谁、何时、哪个 preset），面板可答「这会话谁建的」。
 *  - wake 投递通路（t260929-04）：真宿主 Session API——ctx.sessionController.prompt
 *    （queue 模式不丢）+ control() 队列镜像（已消化判定）；宿主服务缺席 = 显式不可用
 *    （wake: 原因进 status），绝不静默降级为「不醒 = 没事」。
 *
 * 全终态：每个项目的定时器收在 Watchdog 实例里，dispose() 全清；本插件 apply 里
 * 注册 ctx.on('dispose') 统一收口。
 */

import { execFile } from 'node:child_process'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { existsSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import * as net from 'node:net'
import { randomUUID } from 'node:crypto'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

import { loadWatchdogConfig, isValidProjectKey } from './src/host/config.ts'
import { Watchdog, defaultIo, readHeartbeatFile, type WatchdogStatus, type PendingProvider, type SessionStatFn } from './src/host/core.ts'
import type { PendingInteraction } from './src/host/self-lock.ts'
import { QueueMirror } from './src/host/queue-mirror.ts'
import type { WakeIo, WakeOutcome } from './src/host/exits.ts'
import {
  ensureExecutorSession, sessionEventPath, readSessionEvents,
  type SessionCreateIo, type SessionProvenanceEvent,
} from './src/host/session-create.ts'
import { readRequests, fsLedgerIo } from '../executor-panel/src/host/requests.ts'

const execFileP = promisify(execFile)

export const name = 'sandbar-watchdog'
// webServer 只在 web profile 存在；headless 下守望者本体照常，只待机状态读面。
export const inject: string[] = []

/** 引擎端口（t260929-08 探针面）：镜像部署引擎的 Temporal 监听口——workbench
 *  metrics.ts 是另一处硬编码点（本仓暂无跨插件共享配置缝）；换口部署用
 *  SANDBAR_ENGINE_PORT 覆盖，勿另散落第二处裸字面量。 */
const ENGINE_PORT = Number.parseInt(process.env.SANDBAR_ENGINE_PORT ?? '', 10) || 7233

/** 本文件固定落在 <repo>/server/plugins/watchdog/ 下，上三级即仓库根。 */
function defaultRepo(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
}

export interface WatchdogPluginConfig {
  repo?: string
  /** python 解释器（引擎 client.py 用），缺省依次试 server/engine/.venv/bin/python → python3。 */
  python?: string
}

export type TicketListParse =
  | { ok: true; tickets: Array<Record<string, unknown>> }
  | { ok: false; error: string }

/**
 * ticket-list 回执解析（纯面；reader 与真实 stdout 锁共用本实现——测试绝不另抄
 * 一份解析，避免自证桩家族 KI-148/150，t260929-07）：
 *  - 兼容两种形状：引擎信封 {ok,result:{tickets}} 与真入口实证形状
 *    {ok:true,result:{count,tickets}}（t260929-07：result 内层无 ok 键——旧代码
 *    `res.ok !== true` 因此永不通过，reconcile 永久 degraded）。
 *  - result 键在但非对象（如 null）= 形状不符的结构化失败，不走异常分支
 *    （review 条件 1：否则会落进 catch 被误标「引擎离线/超时」）。
 *  - JSON.parse 失败 = 点名「不是合法 JSON」的结构化错误；只有 spawn/超时才允许
 *    用「不可达」措辞（review 条件 2：报错必须点中真检查）。
 */
export function parseTicketListDoc(raw: string): TicketListParse {
  let doc: unknown
  try {
    doc = JSON.parse(raw)
  } catch {
    return { ok: false, error: `ticket-list 回执不是合法 JSON：${raw.slice(0, 200)}` }
  }
  if (typeof doc !== 'object' || doc === null || Array.isArray(doc)) {
    return { ok: false, error: `ticket-list 回执形状异常：${String(raw).slice(0, 200)}` }
  }
  const outer = doc as { result?: unknown }
  // 信封优先；result 键缺席才按裸结果收（present-but-null 不算缺席）。
  const res = 'result' in outer ? outer.result : doc
  if (typeof res !== 'object' || res === null) {
    return { ok: false, error: `ticket-list 回执形状异常（result 非对象）：${JSON.stringify(doc).slice(0, 200)}` }
  }
  const inner = res as { ok?: unknown; tickets?: unknown; error?: unknown }
  // 真入口实证（t260929-07）：信封 result 内层没有 ok 键（{count,tickets}）——旧代码
  // `res.ok !== true` 因此永不通过。信封只在内层显式 ok:false 时拒绝；ok 缺席 +
  // tickets 数组 = 接受（显式宽容，真形锁看住这条契约）。
  if ('result' in outer && inner.ok === false) {
    return { ok: false, error: `ticket-list 回执异常：${inner.error != null ? String(inner.error) : JSON.stringify(inner).slice(0, 200)}` }
  }
  if (!Array.isArray(inner.tickets)) {
    return { ok: false, error: `ticket-list 回执异常（tickets 非数组）：${JSON.stringify(doc).slice(0, 200)}` }
  }
  return { ok: true, tickets: inner.tickets as Array<Record<string, unknown>> }
}

/** 看板真源读面：spawn 引擎 client.py ticket-list（visibility list，不依赖单票 worker）。
 *  结构化失败透传（不抛裸栈）；超时由 execFile timeout 收尸。 */
export function makeBoardReader(repo: string, python?: string) {
  return async (): Promise<{ ok: boolean; rows: Array<Record<string, unknown>>; error?: string }> => {
    const engineDir = join(repo, 'server', 'engine')
    const py = python ?? (existsSync(join(engineDir, '.venv', 'bin', 'python')) ? join(engineDir, '.venv', 'bin', 'python') : 'python3')
    try {
      const { stdout } = await execFileP(py, ['client.py', 'ticket-list', JSON.stringify({})], {
        cwd: engineDir, timeout: 30_000, maxBuffer: 32 * 1024 * 1024,
      })
      const parsed = parseTicketListDoc(stdout)
      if (!parsed.ok) return { ok: false, rows: [], error: parsed.error }
      return { ok: true, rows: parsed.tickets }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      return { ok: false, rows: [], error: `ticket-list 不可达（引擎离线/超时）：${msg.slice(0, 300)}` }
    }
  }
}

/** wake 投递面：真宿主 Session API（t260929-04，取代 t260928-28 的 S1-probe 探针缝）。
 *
 * 已核实形状（~/.sandbar/dsh-015/lib/node_modules/@deepseek-ai/dsh/node_modules/
 * @deepseek-ai/dsh-api-session-controller/lib/types/）：
 *  - ctx.sessionController 注入服务（index.d.ts: interface Context { sessionController }）；
 *  - prompt({requestId, sessionId, mode:'queue'|'steer', content:[{type:'text',text}]},
 *    signal) -> {accepted:true}（index.d.ts L138；types.d.ts L291-305）——排队模式
 *    不丢消息（agent 忙时入 inbox）；
 *  - control(signal): AsyncIterable<SessionControlFrame>（index.d.ts L177）——
 *    baseline + 每会话 queue 帧，是已消化判定的权威镜像（src/host/queue-mirror.ts）。
 * 会话身份：认 watchdog.json 的 executor_session 声明；空 id 时 wake 出口显式不可用
 * （投递面不代建——代建是 session-create.ts 的 ensureSession 面的职责，t260930-09）。
 */
export function makeWakeIo(ctx: Context): WakeIo {
  type ControllerLike = {
    prompt?: (req: unknown, signal: AbortSignal) => Promise<{ accepted: true }>
    control?: (signal: AbortSignal) => AsyncIterable<unknown>
  }
  const getController = (): ControllerLike | undefined =>
    (ctx.get('sessionController') as unknown as ControllerLike | undefined) ?? undefined
  let mirror: QueueMirror | null = null
  // 镜像曾终态不可读的留痕（重建恢复后 status 仍点名历史——显式可审计，绝不冒充一路 live）。
  let lastMirrorFailure: string | null = null
  // 宿主面缺席 = 镜像数据无主（陈认领不可信）：显式拆镜像 + no-signal（绝不拿
  // 上一任宿主的队列残影冒充「未消化」把门错关）。
  const hostGone = (): boolean => {
    if (getController() === undefined && mirror !== null) {
      lastMirrorFailure = mirror.describe()
      void mirror.dispose()
      mirror = null
      return true
    }
    return getController() === undefined
  }
  const ensureMirror = (): QueueMirror => {
    if (mirror !== null && mirror.stateInfo === 'unreadable') {
      // 终态镜像允许重建：每次唤醒决策至多一次重订阅（不是每拍轮询）——控制流可能
      // 恢复（瞬时故障/宿主侧重整），显式重订阅好过永久 no-signal 盲发。
      lastMirrorFailure = mirror.describe()
      void mirror.dispose()
      mirror = null
    }
    if (mirror !== null) return mirror
    mirror = new QueueMirror({
      frames: () => {
        const c = getController()
        if (!c || typeof c.control !== 'function') return null
        return c.control(new AbortController().signal) as AsyncIterable<never>
      },
    })
    mirror.start()
    return mirror
  }
  return {
    async prompt(sessionId, text, mode): Promise<{ accepted: boolean; error?: string; requestId?: string }> {
      const c = getController()
      if (!c || typeof c.prompt !== 'function') {
        return { accepted: false, error: '宿主 sessionController 不可达（headless 或服务未注入）——wake 出口显式不可用' }
      }
      const requestId = `watchdog-${randomUUID()}`
      try {
        // 宿主面超时自断（10s）：投递挂死不拖住守望者节拍；失败路径显式回执。
        await c.prompt({ requestId, sessionId, mode, content: [{ type: 'text', text }] }, AbortSignal.timeout(10_000))
        return { accepted: true, requestId }
      } catch (e) {
        return { accepted: false, error: String(e instanceof Error ? e.message : e) }
      }
    },
    async queueDepth(sessionId): Promise<number | null> {
      if (hostGone()) return null
      return ensureMirror().depthOf(sessionId)
    },
    async ourBriefPending(sessionId, requestId): Promise<boolean | null> {
      if (hostGone()) return null
      return ensureMirror().ourBriefPending(sessionId, requestId)
    },
    async ourPendingItemId(sessionId, requestId): Promise<string | null> {
      if (hostGone()) return null
      return ensureMirror().itemIdOfRpc(sessionId, requestId)
    },
    transportState(): string | null {
      const cur = ensureMirror().describe()
      if (lastMirrorFailure !== null && mirror !== null && mirror.stateInfo === 'live') {
        return `live（曾 unreadable：${lastMirrorFailure}——已重订阅恢复）`
      }
      return cur
    },
    async dispose(): Promise<void> {
      if (mirror !== null) { await mirror.dispose(); mirror = null }
    },
  }
}

/**
 * 代建通路（t260930-09，scope 7 定案）：宿主 Session API。
 *  - create：ctx.sessionController.create({cwd, agentPreset})——0.1.5 实装类型原文
 *    "Create or idempotently adopt one ordinary Session"（幂等收养语义）；preset 缺失
 *    由宿主端显式点名（agent-preset/not-found：preset 名 + available 清单）；
 *  - list：sessionController.list({})——重建判定（声明的 id 还在不在宿主清单）。
 * 两个面缺席（headless/服务未注入）= 显式不可用（refused 事件点名原因），绝不静默。
 */
export function makeSessionCreateIo(ctx: Context): SessionCreateIo {
  type ControllerLike = {
    list?: (request: unknown, signal: AbortSignal) => Promise<{ items?: Array<{ sessionId?: string }> }>
    create?: (request: { cwd?: string; agentPreset?: string }) => Promise<{ sessionId?: string; agentPreset?: string }>
  }
  const getController = (): ControllerLike | undefined =>
    (ctx.get('sessionController') as unknown as ControllerLike | undefined) ?? undefined
  return {
    async create(input) {
      const c = getController()
      if (!c || typeof c.create !== 'function') {
        return { ok: false, error: '宿主 sessionController.create 不可达（headless 或服务未注入）——代建显式不可用' }
      }
      try {
        const res = await c.create({ cwd: input.cwd, agentPreset: input.agentPreset })
        if (typeof res?.sessionId !== 'string' || res.sessionId === '') {
          return { ok: false, error: `宿主 create 回执无 sessionId：${JSON.stringify(res).slice(0, 200)}` }
        }
        return { ok: true, sessionId: res.sessionId, agentPreset: res.agentPreset }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        // 宿主的显式错误族（agent-preset/not-found 等）原样透传——点名 preset 的拒绝面。
        return { ok: false, error: msg.slice(0, 300) }
      }
    },
    async listSessionIds() {
      const c = getController()
      if (!c || typeof c.list !== 'function') return null
      try {
        const res = await c.list({}, AbortSignal.timeout(10_000))
        if (!Array.isArray(res?.items)) return null
        return res.items.map((it) => it.sessionId ?? '').filter((s) => s !== '')
      } catch {
        return null
      }
    },
  }
}

/** 组一次「确保会话」调用的闭包（core 的 sessionEnsure 注入件；事件账=dataDir 下
 *  <project>.executor-session.jsonl，面板经 status 的 session_provenance 消费）。 */
export function makeSessionEnsure(ctx: Context, project: string) {
  const createIo = makeSessionCreateIo(ctx)
  const eventIo = {
    append: (p: string, line: string) => defaultIo.appendAlerts(p, line),
    read: async (p: string) => (await defaultIo.listAlerts(p)).join('\n'),
  }
  return async (args: { declaredSessionId: string; hasWork: boolean }) => {
    return ensureExecutorSession({
      project,
      declaredSessionId: args.declaredSessionId,
      hasWork: args.hasWork,
      env: process.env,
      io: createIo,
      eventIo,
      dataDir: process.env.SANDBAR_WATCHDOG_DATA || join(process.env.HOME || '', '.sandbar', 'watchdog'),
      nowMs: Date.now(),
    })
  }
}
// 「确保会话」的 project 绑定在 ensureWatchdog 处按项目闭包（见下方 deps 组装）。

/** executor 会话快照（t260929-08）：sessionStat 每拍刷新，pendingProvider 复用
 *  running 位（避免一拍两次 list()）；读不到 = 显式缺席，绝不冒充「没在跑」。 */
export interface SessionSnapshot {
  /** 声明会话本拍是否在跑；null = 本拍没读到该会话（list 缺席/调用失败/会话不存在）。 */
  runningOf(sessionId: string): boolean | null
}

type ControllerLike = {
  list?: (request: unknown, signal: AbortSignal) => Promise<{ items?: Array<{ sessionId?: string; updatedAt?: number; running?: boolean }> }>
  prompt?: (req: unknown, signal: AbortSignal) => Promise<{ accepted: true }>
  control?: (signal: AbortSignal) => AsyncIterable<unknown>
}

/** executor 推进真源（t260929-08）：真宿主 Session API list()——只认 watchdog.json
 *  声明的 executor_session，绝不猜路径。返回 {advanced,mtimeMs}：
 *  - 会话在列：advanced = updatedAt > sinceMs（宿主 durable message 时间，一有任何落盘
 *    消息即前进），mtimeMs = updatedAt；
 *  - 宿主服务缺席 / list 失败 / 会话不在列：advanced=null（显式 no_signal，绝不冒充
 *  「有信号但没推进」，也不冒充「一切正常」）。
 *  同拍把 running 位写进快照（自锁判定的 sessionRunning 证据）。 */
export function makeSessionStat(ctx: Context): { stat: SessionStatFn; snapshot: SessionSnapshot } {
  type SummaryLike = { sessionId?: string; updatedAt?: number; running?: boolean }
  const getController = (): ControllerLike | undefined =>
    (ctx.get('sessionController') as unknown as ControllerLike | undefined) ?? undefined
  // 本拍缓存（同一拍内 stat 与 pendingProvider 共用一次 list 的结果）。
  let cacheAt = -1
  let cache: SummaryLike[] = []
  const fetchList = async (): Promise<SummaryLike[] | null> => {
    const c = getController()
    if (!c || typeof c.list !== 'function') return null
    try {
      const res = await c.list({}, AbortSignal.timeout(10_000))
      return Array.isArray(res?.items) ? res.items as SummaryLike[] : null
    } catch {
      return null
    }
  }
  return {
    snapshot: {
      runningOf(sessionId) {
        const hit = cache.find(s => s.sessionId === sessionId)
        return hit ? hit.running === true : null
      },
    },
    stat: async (sessionId, sinceMs) => {
      const nowMs = Date.now()
      if (nowMs - cacheAt > 5_000 || cacheAt < 0) {
        const fresh = await fetchList()
        if (fresh !== null) { cache = fresh; cacheAt = nowMs }
      }
      if (sessionId === '') return { advanced: null, mtimeMs: null }
      const hit = cache.find(s => s.sessionId === sessionId)
      if (!hit || typeof hit.updatedAt !== 'number' || !Number.isFinite(hit.updatedAt)) {
        return { advanced: null, mtimeMs: null }
      }
      return { advanced: hit.updatedAt > sinceMs, mtimeMs: hit.updatedAt }
    },
  }
}

/** 自锁 pending 真源（t260929-08）：面板请求账（requests.jsonl，追加式、未答复永不删）
 *  ——设计稿 260927 的「Requests＝等你答复」面。waiting 行逐条映射 PendingInteraction：
 *  raisedBy = 行内 raised_by（'' = 未归属——自锁判定不认空归属并显式点名），target = 请求 id，
 *  sessionRunning = 发起方会话的 list running 位（读不到 = false，快照缺席显式在 reason 面）。
 *  文件不存在 = 真读过、确实没有挂起请求（available:true, pending:[]），不是 unknown；
 *  读失败（io 异常）= available:false + reason → 显式 unknown。
 */
export function makePendingProvider(projectKey: string, runningLookup?: (sessionId: string) => boolean | null): PendingProvider {
  const env = process.env
  return async (): Promise<{ available: boolean; pending: PendingInteraction[] | null; reason?: string }> => {
    if (!isValidProjectKey(projectKey)) {
      return { available: false, pending: null, reason: `project 形状不合法：${projectKey}——请求账不读` }
    }
    let rows: Awaited<ReturnType<typeof readRequests>>['rows']
    try {
      rows = readRequests(fsLedgerIo, env, projectKey).rows.filter(r => r.status === 'waiting')
    } catch (e) {
      return { available: false, pending: null, reason: `请求账读失败：${String(e instanceof Error ? e.message : e)}` }
    }
    return {
      available: true,
      pending: rows.map(r => ({
        raisedBy: r.raised_by ?? '',
        kind: r.kind,
        target: r.id,
        // 发起方会话 running 位：真源是同拍的 list 快照；发起方未知/未读到 = false
        // （证据面靠 raisedBy 归属说话，running 只是辅助位，缺席不冒充）。
        sessionRunning: r.raised_by ? runningLookup?.(r.raised_by) === true : false,
      })),
    }
  }
}

/** 引擎存活真探针（t260929-08，workbench probePort 同口径）：TCP 连 127.0.0.1:ENGINE_PORT。
 *  连上 = online；拒绝/超时/错误 = offline（单机部署，refused 与 filtered 同义=不可达）。
 *  单次尝试不重试（继承 workbench 语义——探针每拍都跑，重试留给节拍）；socket 必 destroy。 */
export function makeEngineProbe(port: number = ENGINE_PORT): () => Promise<{ online: boolean; detail: string }> {
  return () => new Promise((res) => {
    const sock = net.connect({ host: '127.0.0.1', port })
    let settled = false
    const done = (online: boolean, detail: string) => {
      if (settled) return
      settled = true
      sock.destroy()
      res({ online, detail })
    }
    sock.setTimeout(800)
    sock.once('connect', () => done(true, `127.0.0.1:${port} 可连（引擎在线）`))
    sock.once('error', (e) => done(false, `127.0.0.1:${port} 连接失败（${e.code ?? e.message}）——引擎离线`))
    sock.once('timeout', () => done(false, `127.0.0.1:${port} 800ms 超时——引擎离线`))
  })
}

export function apply(ctx: Context, options: WatchdogPluginConfig = {}): void {
  const repo = options.repo ?? process.env.SANDBAR_REPO ?? defaultRepo()
  if (process.env.SANDBAR_REPO === undefined) process.env.SANDBAR_REPO = repo // Watchdog.ledgerDir 缺省推导用

  const watch = new Map<string, Watchdog>()
  const wakeIo = makeWakeIo(ctx)
  const boardReader = makeBoardReader(repo, options.python)
  // 真信号三面（t260929-08）：会话推进（list updatedAt）/ 自锁 pending（面板请求账）/
  // 引擎探针（7233 TCP）。快照由 sessionStat 每拍刷新，pendingProvider 复用 running 位。
  const session = makeSessionStat(ctx)
  const engineProbe = makeEngineProbe()

  /** 起/停一个项目的守望者（配置不存在或被停 = 显式 stopped，非消失）。 */
  async function ensureWatchdog(key: string): Promise<Watchdog> {
    let w = watch.get(key)
    if (w) return w
    w = new Watchdog(key, {
      io: defaultIo,
      boardReader,
      wakeIo,
      engineProbe,
      sessionStat: session.stat,
      pendingProvider: makePendingProvider(key, (sid) => session.snapshot.runningOf(sid)),
      sessionEnsure: makeSessionEnsure(ctx, key),
      now: Date.now,
    })
    watch.set(key, w)
    await w.start()
    return w
  }

  /** 配置目录扫描：watchdog.json 存在的目录 = 已声明项目（存在即声明）。 */
  async function declaredProjects(): Promise<string[]> {
    const { watchdogConfigDir } = await import('./src/host/config.ts')
    const root = watchdogConfigDir()
    let names: string[] = []
    try {
      names = await readdir(root)
    } catch {
      return [] // 无配置根 = 零声明 = 零行为
    }
    return names.filter(k => isValidProjectKey(k) && existsSync(join(root, k, 'watchdog.json'))).sort()
  }

  function sendJson(res: ServerResponse, status: number, body: unknown): void {
    const data = JSON.stringify(body)
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' })
    res.end(data)
  }

  function readQuery(req: IncomingMessage): URLSearchParams {
    return new URL(req.url ?? '/', 'http://x').searchParams
  }

  async function statusFor(key: string): Promise<WatchdogStatus & { heartbeat: Awaited<ReturnType<typeof readHeartbeatFile>>; session_provenance: { file: string; events: SessionProvenanceEvent[]; malformed_rows: number } }> {
    // 溯源事件账独立于声明：未声明项目也能答「有没有代建史」（scope 6/8 检视面）。
    const dataRoot = process.env.SANDBAR_WATCHDOG_DATA || join(process.env.HOME || '', '.sandbar', 'watchdog')
    const evFile = sessionEventPath(dataRoot, key)
    const provenance = await readSessionEvents({ read: async (p) => (await defaultIo.listAlerts(p)).join('\n') }, evFile)
    const session_provenance = { file: evFile, events: provenance.events.slice(-20), malformed_rows: provenance.malformed_rows }
    const cfg = loadWatchdogConfig(key)
    if (!cfg.declared) {
      return {
        project: key, declared: false, enabled: false, phase: 'stopped', config_error: null,
        config_provenance: { file: null, keys: {} },
        executor_session: null,
        heartbeat: { last_beat: null, age_seconds: null, alive: false, reason: '项目未声明（无 watchdog.json）——守望者本体零行为；有活时按需代建（t260930-09）' },
        ledger: { path: '', watermark_offset: 0, rows_seen: 0, dupes_skipped: 0, malformed_rows: 0, gaps_seen: 0, last_row_at: null, unreadable: '项目未声明守望者' },
        liveness: { engine: { online: null, detail: '未探测', checked_at: null }, executor: null },
        self_lock: null, reconcile: null, startup: { missing_rows: null, replayed_rows: null, dedupe_keys: 0 },
        presumed_self_rows: 0, presumed_self_detail: null, queue_mirror: '项目未声明守望者（镜像未起）',
        wakes: [], alerts: [], notify: { beep: false, unseen_redline: 0 }, last_error: null,
        session_provenance,
      } as never
    }
    const w = await ensureWatchdog(key)
    const st = w.status()
    const { join: j2 } = await import('node:path')
    st.heartbeat = await readHeartbeatFile(defaultIo, j2(dataRoot, `${key}.heartbeat.json`), Date.now())
    return { ...(st as object), session_provenance } as never
  }

  /** 只读状态面（下一票面板的唯一消费口；键集=panel-contract.md，写集内交接件）。 */
  async function handleStatus(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '只读面：仅 GET（405 刚性）' })
      return
    }
    const q = readQuery(req)
    const key = q.get('project')
    try {
      if (key !== null && key !== '') {
        if (!isValidProjectKey(key)) {
          sendJson(res, 400, { ok: false, error: `project 形状不合法：${key}` })
          return
        }
        sendJson(res, 200, { ok: true, result: await statusFor(key) })
        return
      }
      // t260930-09 scope 8：清单不再只列已声明项目——注册表根下的每个合法 key 都列
      // （declared=false 的条目走显式未声明状态，绝不空态冒充正常）。面板项目下拉的
      // 数据源就是本清单：项目在「什么都没声明」之前就能被选中检视。
      const { watchdogConfigDir } = await import('./src/host/config.ts')
      const root = watchdogConfigDir()
      let names: string[] = []
      try {
        names = (await readdir(root)).filter(k => isValidProjectKey(k))
      } catch { names = [] } // 无配置根 = 零注册 = 真实空清单
      const projects = (await Promise.all(names.sort().map(k => statusFor(k))))
      sendJson(res, 200, { ok: true, result: { projects, note: 'declared=false 条目 = 尚未入册（可选可看；守望者本体零行为，有活时按需代建）' } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  const attach = (ws: { register: (o: { kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void }): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-watchdog/api/status', handler: handleStatus }),
      ]
      return () => { for (const d of disposers) d() }
    }, 'sandbar-watchdog: status route')
    ctx.logger.info('sandbar-watchdog: 守望者状态面已挂载 /sandbar-watchdog/api/status（repo=%s）', repo)
  }

  // 与 workbench 同款：webServer 可能已在（直接挂）或后到（等 internal/service）；
  // headless 永远等不到——待机即正确行为（守望者本体不依赖 webServer）。
  const existing = ctx.get('webServer') as unknown as Parameters<typeof attach>[0] | undefined
  if (existing !== undefined) {
    attach(existing)
  } else {
    ctx.on('internal/service', (serviceName: string, value: unknown) => {
      if (serviceName !== 'webServer') return
      attach(value as Parameters<typeof attach>[0])
    })
  }

  // 守望者本体：声明了的项目在 apply 时即起（不依赖 webServer；headless 照看账）。
  void (async () => {
    try {
      const keys = await declaredProjects()
      for (const k of keys) {
        const cfg = loadWatchdogConfig(k)
        if (!cfg.declared || !cfg.enabled) continue
        await ensureWatchdog(k)
        ctx.logger.info('sandbar-watchdog: 项目 %s 守望者已起（reconcile %ss / stall %smin）', k, cfg.config.reconcile_seconds, cfg.config.stall_minutes)
      }
    } catch (e) {
      ctx.logger.warn('sandbar-watchdog: 守望者启动面失败（显式点名，不阻断宿主）：%s', String(e instanceof Error ? e.message : e))
    }
  })()

  // 全终态：宿主卸载时停掉一切守望者（定时器/在飞拍/队列镜像消费循环全收）。
  ctx.on('dispose', () => {
    for (const [k, w] of watch) {
      w.dispose()
      watch.delete(k)
    }
    void wakeIo.dispose?.()
  })
}
