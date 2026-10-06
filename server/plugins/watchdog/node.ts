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
import { appendFile, mkdir, readFile, readdir } from 'node:fs/promises'
import * as net from 'node:net'
import { randomUUID } from 'node:crypto'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

import { loadWatchdogConfig, isValidProjectKey, watchdogDataDir, watchdogConfigDir } from './src/host/config.ts'
import { Watchdog, defaultIo, readHeartbeatFile, type WatchdogStatus, type PendingProvider, type SessionStatFn } from './src/host/core.ts'
import { filterBoardRowsToProject, type BoardRow } from './src/host/reconcile.ts'
import type { PendingInteraction } from './src/host/self-lock.ts'
import { QueueMirror } from './src/host/queue-mirror.ts'
import type { WakeIo, WakeOutcome } from './src/host/exits.ts'
import {
  ensureExecutorSession, sessionEventPath, readSessionEvents,
  type SessionCreateIo, type SessionProvenanceEvent,
} from './src/host/session-create.ts'
import { runOneShotUnit, readConcurrencyLimit, runsPath, type OneShotUnit, type OneShotOutcome } from './src/host/one-shot.ts'
import { spawnApprovedUnit, privilegeAuditPath, privilegeDeclPath, smuggledPrivilegeKeys } from './src/host/one-shot-privilege.ts'
import { instanceProjectsRoot } from './src/host/config.ts'
import { projectMainDir } from './src/host/session-create.ts'
import { readRequests, fsLedgerIo, appendRequest } from '../executor-panel/src/host/requests.ts'
import type { RecentTextResult, ProseBackstopIo } from './src/host/core.ts'

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
 *  **可选按项目过滤**（t261001-22 / KI-180）：账本是 <projects_root>/<key>/ledger/
 *  events.jsonl 本项目文件，守望者对账用的看板必须同 scope——不传 project 时
 *  ticket-list 回全机票，别家票永不可能被本项目账本覆盖，ledger_missing_rows 的 N
 *  恒等于全机票数（永不收敛的结构假警）。opts.project 在场时：服务端 project 过滤
 *  （ProjectKey SA）为主 + 行级 filterBoardRowsToProject 兜底（防御引擎侧过滤被绕过/
 *  回执混行；无 SA 标签的历史票两侧语义一致，保守保留）；缺席时（真形锁/全局视图
 *  调用方，t260929-07 sc C 段契约：makeBoardReader(repo) 必须 rows>0）不做裁剪，
 *  回全机行——scope 是调用方的选择，读器不擅自把全局读面裁空。
 *  结构化失败透传（不抛裸栈）；超时由 execFile timeout 收尸。 */
export function makeBoardReader(repo: string, opts: { python?: string; project?: string } = {}) {
  const project = opts.project
  return async (): Promise<{ ok: boolean; rows: Array<Record<string, unknown>>; error?: string }> => {
    const engineDir = join(repo, 'server', 'engine')
    const py = opts.python ?? (existsSync(join(engineDir, '.venv', 'bin', 'python')) ? join(engineDir, '.venv', 'bin', 'python') : 'python3')
    try {
      const { stdout } = await execFileP(py, ['client.py', 'ticket-list', JSON.stringify(project ? { project } : {})], {
        cwd: engineDir, timeout: 30_000, maxBuffer: 32 * 1024 * 1024,
      })
      const parsed = parseTicketListDoc(stdout)
      if (!parsed.ok) return { ok: false, rows: [], error: parsed.error }
      return { ok: true, rows: project ? filterBoardRowsToProject(parsed.tickets as BoardRow[], project) : parsed.tickets }
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
    // t261005-02 self-heal: cancel one live turn (retains pending inbox work, so the
    // queued wake briefing survives and the session starts a fresh turn). The host
    // cancel is synchronous (SessionCancelValue, no AbortSignal parameter — types.d.ts
    // L326-333), so the bound is a Promise.race timeout, not a signal; the loser
    // timer is always cleared (terminal-state discipline). accepted=null = face
    // absent or unbounded wait (explicit unsupported — the self-heal step holds and
    // never retries); accepted=false = the host named a refusal, error carried.
    async cancelTurn(sessionId): Promise<{ accepted: boolean | null; error?: string }> {
      const c = getController() as (ControllerLike & { cancel?: (request: { sessionId: string }) => unknown }) | undefined
      if (!c || typeof c.cancel !== 'function') {
        return { accepted: null, error: '宿主 sessionController.cancel 不可达（headless 或服务未注入）——self-heal cancel 显式不可用' }
      }
      let timer: ReturnType<typeof setTimeout> | undefined
      try {
        const res = await Promise.race([
          Promise.resolve(c.cancel({ sessionId })).then((v) => ({ ok: true as const, v })),
          new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error('__cancel_bound_timeout__')), 10_000)
            ;(timer as unknown as { unref?: () => void }).unref?.()
          }),
        ])
        if (res.ok && typeof res.v === 'object' && res.v !== null && (res.v as { accepted?: unknown }).accepted === true) {
          return { accepted: true }
        }
        return { accepted: false, error: `宿主 cancel 回执非 accepted：${JSON.stringify(res.ok ? res.v : null).slice(0, 200)}` }
      } catch (e) {
        const msg = String(e instanceof Error ? e.message : e)
        // The 10s bound fired = the answer is unknowable (accepted:null, explicit
        // unsupported — never guessed); any other throw is a host-named refusal
        // (accepted:false, error carried into the receipt).
        if (msg === '__cancel_bound_timeout__') {
          return { accepted: null, error: 'cancel call exceeded the 10s bound — outcome unknowable, explicit unsupported' }
        }
        return { accepted: false, error: `cancel 被宿主点名拒绝：${msg.slice(0, 200)}` }
      } finally {
        if (timer !== undefined) clearTimeout(timer)
      }
    },
    async ourBriefPending(sessionId, requestId): Promise<boolean | null> {
      if (hostGone()) return null
      if (requestId === null) {
        // No brief of ours was ever minted (requestId null): fall back to the queue
        // depth — an undrained queue still evidences the wedge (self-heal guard c).
        const d = await ensureMirror().depthOf(sessionId)
        return d === null ? null : d > 0
      }
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
      dataDir: watchdogDataDir(process.env),   // 260930 直修：数据根单一真源（见 config.watchdogDataDir）
      nowMs: Date.now(),
    })
  }
}
// 「确保会话」的 project 绑定在 ensureWatchdog 处按项目闭包（见下方 deps 组装）。

/** One-shot session path (t261004-30): create reuses the host Session API
 *  (makeSessionCreateIo, create face only -- a one-shot session has no adopt);
 *  runTurn delivers one bounded unit through the host prompt and waits for the
 *  receipt. The receipt proves DELIVERY, not completion -- the real result is
 *  filed by the session itself (engine settle port executor_oneshot.py +
 *  request/action ledgers), so the summary honestly says "delivered" and never
 *  pretends the unit finished. Host service absent = explicit refused. */
export function makeOneShotRunner(ctx: Context, project: string, opts?: {
  /** The declared high-privilege preset (t261006-06): the ONLY elevation
   *  channel the host create call accepts; the default stays the resident
   *  executor preset for callers that do not opt into privilege. */
  presetName?: string
  /** Unit briefing appended to the turn prompt: object, exact action,
   *  privilege scope (composed by one-shot-privilege.ts). */
  briefing?: string
}) {
  const createIo = makeSessionCreateIo(ctx)
  const io = {
    readText: (p: string) => readFile(p, 'utf8'),
    writeText: (p: string, data: string) => { mkdir(dirname(p), { recursive: true }); return writeFileB(p, data) },
    append: (p: string, line: string) => appendFile(p, line, 'utf8'),
  }
  return async function runUnit(input: {
    unit: OneShotUnit
    projectMainDir: string
  }): Promise<OneShotOutcome> {
    const cfg = loadWatchdogConfig(project, process.env)
    const oneShot = cfg.config.one_shot
    const limit = await readConcurrencyLimit(io, join(watchdogConfigDir(process.env), project, 'concurrency.json'))
    return runOneShotUnit({
      project,
      dataDir: watchdogDataDir(process.env),
      cwd: input.projectMainDir,
      unit: input.unit,
      limit: limit.ok ? limit.limit : null,
      lockTimeoutMs: oneShot.lock_timeout_ms,
      presetName: opts?.presetName,
      io,
      sessions: {
        create: (req) => createIo.create({ cwd: req.cwd, agentPreset: req.agentPreset }),
        runTurn: async (sessionId) => {
          type ControllerLike = { prompt?: (req: unknown, signal: AbortSignal) => Promise<{ accepted: true }> }
          const c = (ctx.get('sessionController') as unknown as ControllerLike | undefined) ?? undefined
          if (!c || typeof c.prompt !== 'function') {
            return { ok: false, summary: 'host sessionController.prompt unreachable (headless) — one-shot turn not delivered' }
          }
          const prompt = opts?.briefing ? ONE_SHOT_TURN_PROMPT + ' ' + opts.briefing : ONE_SHOT_TURN_PROMPT
          await c.prompt({ sessionId, message: prompt }, AbortSignal.timeout(10_000))
          return { ok: true, summary: 'bounded unit prompt delivered' }
        },
      },
      nowMs: Date.now(),
    })
  }
}

/** The one-shot turn prompt: wake, read the ledgers, do EXACTLY one bounded
 *  unit, write the result, exit. */
export const ONE_SHOT_TURN_PROMPT =
  'One-shot bounded unit. Read the ledgers first, do EXACTLY the one bounded unit ' +
  'you were woken for, write the result (action row / request row / engine settle ' +
  'note), then stop. Do not start other work. To ask the human anything, file a ' +
  'request row — never wait for a direct reply.'

async function writeFileB(p: string, data: string): Promise<void> {
  const { writeFile } = await import('node:fs/promises')
  await writeFile(p, data, 'utf8')
}


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
      if (sessionId === '') return { advanced: null, mtimeMs: null, running: null }
      const hit = cache.find(s => s.sessionId === sessionId)
      if (!hit || typeof hit.updatedAt !== 'number' || !Number.isFinite(hit.updatedAt)) {
        return { advanced: null, mtimeMs: null, running: null }
      }
      // t261004-12：同一拍顺带把 running 位带回去（同一次 list 缓存，不加第二读）——
      // core 的 stall/long_turn 判定与自锁判定消费同一个位。
      return { advanced: hit.updatedAt > sinceMs, mtimeMs: hit.updatedAt, running: hit.running === true }
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
      return { available: false, pending: null, reason: `invalid project key shape: ${projectKey} — request ledger not read` }
    }
    let rows: Awaited<ReturnType<typeof readRequests>>['rows']
    try {
      rows = readRequests(fsLedgerIo, env, projectKey).rows.filter(r => r.status === 'waiting')
    } catch (e) {
      return { available: false, pending: null, reason: `request ledger read failed: ${String(e instanceof Error ? e.message : e)}` }
    }
    return {
      available: true,
      pending: rows.map(r => ({
        raisedBy: r.raised_by ?? '',
        kind: r.kind,
        target: r.id,
        // t261004-08：发起时刻（账本行 at）——自锁升级阈值的计时真源；畸形行缺 at 时
        // 判定按「刚发起」算（宁可晚报不冒报）。
        raisedAt: typeof r.at === 'number' && Number.isFinite(r.at) ? r.at : undefined,
        // 发起方会话 running 位：真源是同拍的 list 快照；发起方未知/未读到 = false
        // （证据面靠 raisedBy 归属说话，running 只是辅助位，缺席不冒充）。
        sessionRunning: r.raised_by ? runningLookup?.(r.raised_by) === true : false,
        // t261005-02：问行是否声明了可接受的 default（只读观测，进 self-heal 回执）；
        // 空串 = 行未声明 default（hasDefault=false），字段缺席 = 位不可见（null）。
        hasDefault: typeof (r as { default_action?: unknown }).default_action === 'string'
          ? ((r as { default_action: string }).default_action.trim() !== '')
          : null,
      })),
    }
  }
}

/**
 * Recent-round-text reader (t261004-08): the host Session API history page/follow —
 * the authorized path on the real 0.1.5 host (types verified at index.d.ts L163/L171).
 * On-disk transcript files are NOT used: their dirs are keyed by a cwd slug and the
 * payload is zstd jsonl, so resolving a path from a sessionId would be a guess and
 * would need a new dependency; an absent host face = explicitly unavailable
 * (ok:false with the reason) — no file guessing, no silence.
 *
 * Two steps: one follow() opening frame to get the cursor (abort + return() right
 * after — normal/error/timeout/cancel paths all tear the iterator down), then
 * page({address, throughSeq, maxMessages:12}) for the most recent message-aligned
 * page. Text extraction is a shape-agnostic deep walk (all string values inside
 * records[].data concatenated) — no event-type guessing; depth/count caps guard
 * against malformed oversized payloads. Heuristic disclosure: prose-backstop.ts header.
 */
export function makeRecentTextIo(ctx: Context): (sessionId: string) => Promise<RecentTextResult> {
  type RecordLike = { type?: unknown; data?: unknown }
  type ControllerLike = {
    page?: (request: unknown, signal: AbortSignal) => Promise<{ records?: RecordLike[] }>
    follow?: (request: unknown, signal: AbortSignal) => AsyncIterable<unknown>
  }
  const getController = (): ControllerLike | undefined =>
    (ctx.get('sessionController') as unknown as ControllerLike | undefined) ?? undefined
  return async (sessionId: string): Promise<RecentTextResult> => {
    if (sessionId === '') return { ok: false, reason: 'executor session id not declared/adopted — no session to read recent round text from' }
    const c = getController()
    if (!c || typeof c.follow !== 'function' || typeof c.page !== 'function') {
      return { ok: false, reason: 'host sessionController history page/follow face unreachable (headless or service not injected) — recent round text explicitly unavailable' }
    }
    const address = { kind: 'session', sessionId }
    let throughSeq: number | null = null
    const ac = new AbortController()
    try {
      const iter = c.follow({ address, maxMessages: 1 }, ac.signal)[Symbol.asyncIterator]()
      const first = await iter.next()
      const frame = first.value as { cursor?: unknown } | undefined
      if (frame !== null && typeof frame === 'object' && typeof frame.cursor === 'number') throughSeq = frame.cursor
      ac.abort() // window closed as soon as the cursor is in hand; the stream is no longer needed (residual consumer paths are torn down by return())
      try { await iter.return?.(undefined) } catch { /* iterator already terminal = already torn down */ }
    } catch (e) {
      ac.abort()
      return { ok: false, reason: `host follow window failed: ${String(e instanceof Error ? e.message : e).slice(0, 200)} — recent round text explicitly unavailable` }
    }
    if (throughSeq === null) {
      return { ok: false, reason: 'follow opening frame has no cursor (host receipt shape differs from the 0.1.5 types) — recent round text explicitly unavailable' }
    }
    try {
      const page = await c.page({ address, throughSeq, maxMessages: 12 }, AbortSignal.timeout(10_000))
      const records = Array.isArray(page?.records) ? page.records : null
      if (records === null) return { ok: false, reason: 'page receipt lacks the records array (malformed host receipt) — recent round text explicitly unavailable' }
      const parts: string[] = []
      collectStrings(records, parts, 0)
      return { ok: true, text: parts.join('\n') }
    } catch (e) {
      return { ok: false, reason: `host page read failed: ${String(e instanceof Error ? e.message : e).slice(0, 200)} — recent round text explicitly unavailable` }
    }
  }
}

/** Deep string collection (shape-agnostic; depth ≤6, total ≤2000 — malformed deep nesting / oversized receipts never stall the tick). */
function collectStrings(v: unknown, out: string[], depth: number): void {
  if (out.length >= 2000 || depth > 6) return
  if (typeof v === 'string') { if (v !== '') out.push(v); return }
  if (Array.isArray(v)) { for (const item of v) collectStrings(item, out, depth + 1); return }
  if (v !== null && typeof v === 'object') { for (const k of Object.keys(v as Record<string, unknown>)) collectStrings((v as Record<string, unknown>)[k], out, depth + 1) }
}

/**
 * Prose-backstop ledger face (t261004-08): the panel request ledger (read unanswered
 * rows / file a question row) + a journal under the watchdog data root
 * (<project>.prose-backstop.jsonl, the idempotency log). The ledger is the panel's
 * source of truth (readRequests/appendRequest reused as-is, no second copy); a
 * missing journal file = empty set (truly read, truly nothing filed); a read failure
 * is named explicitly by core's startup replay.
 */
export function makeProseBackstopIo(projectKey: string): ProseBackstopIo {
  const env = process.env
  const journalPath = join(watchdogDataDir(env), `${projectKey}.prose-backstop.jsonl`)
  return {
    async readWaiting() {
      if (!isValidProjectKey(projectKey)) return { ok: false as const, reason: `invalid project key shape: ${projectKey} — request ledger not read` }
      try {
        const rows = readRequests(fsLedgerIo, env, projectKey).rows.filter(r => r.status === 'waiting')
        return { ok: true as const, rows: rows.map(r => ({ id: r.id, raisedBy: r.raised_by ?? '' })) }
      } catch (e) {
        return { ok: false as const, reason: `request ledger read failed: ${String(e instanceof Error ? e.message : e).slice(0, 200)}` }
      }
    },
    async append(args) {
      // Row fields (new copy in English STE per the 261004 order): a one-line
      // question + a detail quoting the sentence and naming the session, attributed
      // via raised_by — consumed directly by the panel Requests tab and the
      // self-lock attribution face.
      const out = appendRequest(fsLedgerIo, env, projectKey, {
        kind: 'question',
        question: 'Executor is waiting on the host',
        detail: `Quote: "${args.sentence}" — session ${args.sessionId}`,
        raised_by: args.sessionId,
      }, Date.now())
      return out.ok ? { ok: true as const, requestId: out.row.id } : { ok: false as const, reason: out.error }
    },
    async readJournal() {
      try {
        return (await readFile(journalPath, 'utf8')).split('\n').filter(l => l !== '')
      } catch {
        return [] // missing file = truly nothing filed (the append side always mkdirs first); read failures are named by core's startup replay
      }
    },
    async appendJournal(line) {
      await mkdir(dirname(journalPath), { recursive: true })
      await appendFile(journalPath, line + '\n')
    },
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
  // board reader 按项目实例化（t261001-22 / KI-180）：ticket-list 必须带本项目过滤，
  // 一进程看多项目时各守望者各拿各的 scope，绝不共享一个全机 reader。
  const boardReaderFor = (key: string) => makeBoardReader(repo, { project: key, python: options.python })
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
      boardReader: boardReaderFor(key),
      wakeIo,
      engineProbe,
      sessionStat: session.stat,
      pendingProvider: makePendingProvider(key, (sid) => session.snapshot.runningOf(sid)),
      sessionEnsure: makeSessionEnsure(ctx, key),
      // t261004-08：waiting-on-host 观测面 + prose backstop 落账面（逐项目闭包）。
      waitingRunningLookup: (sid) => session.snapshot.runningOf(sid),
      recentText: makeRecentTextIo(ctx),
      proseBackstopIo: makeProseBackstopIo(key),
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
    const dataRoot = watchdogDataDir(process.env)   // 260930 直修：与写侧同一表达式（单一真源）
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
        self_lock: null,
        waiting_on_host: { state: 'unknown', asks: [], sinceMs: null, reason: '项目未声明守望者——waiting 面零行为（显式 unknown）' },
        prose_backstop: { state: 'off', last_request_id: null, reason: '项目未声明守望者——补落面零行为' },
        reconcile: null, startup: { missing_rows: null, replayed_rows: null, dedupe_keys: 0 },
        presumed_self_rows: 0, presumed_self_detail: null, queue_mirror: '项目未声明守望者（镜像未起）',
        wakes: [], alerts: [], notify: { beep: false, unseen_redline: 0 }, last_error: null,
        wake_receipts: [],
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

  /**
   * t261004-29 wake push face: the host answered a request on the panel → the panel
   * POSTs here → the watchdog wakes the executor through the same wakeExecutor path
   * and returns one receipt (attempted/woke/reason). POST-only; project shape and
   * non-empty request_id are explicit 4xx; an undeclared project returns 404 (the
   * watchdog body stays zero-behavior and no instance is started for it). Headless
   * profile has no webServer → this route does not exist, and its only caller (the
   * panel answer endpoint) does not exist either — the pair degrades together, no
   * dangling caller.
   */
  async function handleWake(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'wake push face is POST-only (write operation, explicit trace)' })
      return
    }
    let raw = ''
    req.on('data', (chunk: Buffer) => { raw += chunk.toString('utf8') })
    req.on('error', () => sendJson(res, 400, { ok: false, error: 'request body read failed' }))
    req.on('end', () => {
      void (async () => {
        let body: Record<string, unknown>
        try { body = JSON.parse(raw) as Record<string, unknown> } catch { sendJson(res, 400, { ok: false, error: 'non-JSON body — explicitly refused' }); return }
        const key = typeof body.project === 'string' ? body.project : ''
        if (!isValidProjectKey(key)) { sendJson(res, 400, { ok: false, error: `project shape is not valid: ${key || '(absent)'}` }); return }
        const requestId = typeof body.request_id === 'string' ? body.request_id : ''
        if (requestId === '') { sendJson(res, 400, { ok: false, error: 'request_id must be a non-empty string' }); return }
        const cfg = loadWatchdogConfig(key)
        if (!cfg.declared) { sendJson(res, 404, { ok: false, error: `project has no watchdog declaration: ${key} — wake push face zero-behavior (explicit)` }); return }
        try {
          const w = await ensureWatchdog(key)
          const receipt = await w.requestWake({
            requestId,
            by: typeof body.by === 'string' ? body.by : 'host',
            detail: typeof body.detail === 'string' ? body.detail : '',
          })
          sendJson(res, 200, { ok: true, wake: receipt })
        } catch (err) {
          sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
        }
      })()
    })
  }


  /**
   * t261006-06 one-shot ignition: the named, approval-gated spawn entry for
   * one high-privilege bounded unit. The human approval IS the gate: the
   * request must exist in the panel request ledger AND be answered by a
   * writer other than its raiser, the request must not be expired, the
   * declared privilege grant must not have aged out, and the approval must
   * not already be consumed (one privileged execution per human approval,
   * checked against the append-only run journal + privilege audit, never the
   * mutable lock). The preset and scope come ONLY from the human-authored
   * one-shot-privilege.json declaration -- preset/scope keys in the body are
   * refused by name (no self-elevation). The audit row is appended BEFORE
   * the session is created; an append failure refuses the spawn (fail
   * closed). Reuses the wake face's HTTP discipline: POST-only, non-JSON
   * 400, bad project 400, undeclared project 404 zero-behavior, handler
   * throw 500 with the message.
   */
  async function handleOneShotRun(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'POST') {
      sendJson(res, 405, { ok: false, error: 'one-shot run face is POST-only (write operation, explicit trace)' })
      return
    }
    let raw = ''
    req.on('data', (chunk: Buffer) => { raw += chunk.toString('utf8') })
    req.on('error', () => sendJson(res, 400, { ok: false, error: 'request body read failed' }))
    req.on('end', () => {
      void (async () => {
        let body: Record<string, unknown>
        try { body = JSON.parse(raw) as Record<string, unknown> } catch { sendJson(res, 400, { ok: false, error: 'non-JSON body — explicitly refused' }); return }
        const smuggled = smuggledPrivilegeKeys(body)
        if (smuggled.length > 0) {
          sendJson(res, 400, { ok: false, error: `body must not carry privilege keys (${smuggled.join(', ')}) — preset and scope come only from one-shot-privilege.json; no self-elevation` })
          return
        }
        const key = typeof body.project === 'string' ? body.project : ''
        if (!isValidProjectKey(key)) { sendJson(res, 400, { ok: false, error: `project shape is not valid: ${key || '(absent)'}` }); return }
        const requestId = typeof body.request_id === 'string' ? body.request_id : ''
        if (requestId === '') { sendJson(res, 400, { ok: false, error: 'request_id must be a non-empty string' }); return }
        const action = typeof body.action === 'string' ? body.action.trim() : ''
        const cfg = loadWatchdogConfig(key)
        if (!cfg.declared) { sendJson(res, 404, { ok: false, error: `project has no watchdog declaration: ${key} — one-shot run face zero-behavior (explicit)` }); return }
        const dataDir = watchdogDataDir(process.env)
        const auditFile = privilegeAuditPath(dataDir, key)
        const readOrNull = (p: string): Promise<string | null> =>
          readFile(p, 'utf8').catch((e: unknown) => ((e as { code?: string }).code === 'ENOENT' ? null : Promise.reject(e)))
        try {
          const result = await spawnApprovedUnit({
            read: readOrNull,
            auditAppend: (row) => mkdir(dirname(auditFile), { recursive: true }).then(() => appendFile(auditFile, JSON.stringify(row) + '\n', 'utf8')),
            runUnit: async (input) => {
              const cwd = projectMainDir(key, process.env)
              if (!cwd.ok) return { action: 'refused', reason: `one-shot unit has no project main dir: ${cwd.error}` }
              const runUnit = makeOneShotRunner(ctx, key, { presetName: input.presetName, briefing: input.briefing })
              return runUnit({ unit: input.unit, projectMainDir: cwd.cwd })
            },
            project: key,
            requestId,
            action,
            declFile: privilegeDeclPath(watchdogConfigDir(process.env), key),
            ledgerFile: join(instanceProjectsRoot(process.env), key, 'requests.jsonl'),
            runsFile: runsPath(dataDir, key),
            auditFile,
            nowMs: Date.now(),
          })
          if (result.ok) sendJson(res, 200, { ok: true, spawn: result.spawn })
          else sendJson(res, result.status, { ok: false, error: result.error })
        } catch (err) {
          sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
        }
      })()
    })
  }

  const attach = (ws: { register: (o: { kind: string; path: string; handler: (req: IncomingMessage, res: ServerResponse) => Promise<void> | void }) => () => void }): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/sandbar-watchdog/api/status', handler: handleStatus }),
        ws.register({ kind: 'exact', path: '/sandbar-watchdog/api/wake', handler: handleWake }),
        ws.register({ kind: 'exact', path: '/sandbar-watchdog/api/one-shot/run', handler: handleOneShotRun }),
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
