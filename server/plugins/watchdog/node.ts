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
 *  - 未声明项目（无 watchdog.json）= 零行为：不起定时器、不读账本、不占路由数据。
 *  - wake 投递通路：S1-probe 前按「显式不可用」交付（wake: 探针结果进 status），
 *    绝不静默降级为「不醒 = 没事」。
 *
 * 全终态：每个项目的定时器收在 Watchdog 实例里，dispose() 全清；本插件 apply 里
 * 注册 ctx.on('dispose') 统一收口。
 */

import { execFile } from 'node:child_process'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { existsSync } from 'node:fs'
import { readdir } from 'node:fs/promises'
import { join, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

import { loadWatchdogConfig, isValidProjectKey } from './src/host/config.ts'
import { Watchdog, defaultIo, readHeartbeatFile, type WatchdogStatus } from './src/host/core.ts'
import type { WakeIo, WakeOutcome } from './src/host/exits.ts'

const execFileP = promisify(execFile)

export const name = 'sandbar-watchdog'
// webServer 只在 web profile 存在；headless 下守望者本体照常，只待机状态读面。
export const inject: string[] = []

/** 本文件固定落在 <repo>/server/plugins/watchdog/ 下，上三级即仓库根。 */
function defaultRepo(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
}

export interface WatchdogPluginConfig {
  repo?: string
  /** python 解释器（引擎 client.py 用），缺省依次试 server/engine/.venv/bin/python → python3。 */
  python?: string
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
      const doc = JSON.parse(stdout) as { result?: { ok?: boolean; tickets?: unknown; error?: string } }
      const res = doc.result ?? {}
      if (res.ok !== true || !Array.isArray(res.tickets)) {
        return { ok: false, rows: [], error: `ticket-list 回执异常：${res.error ?? JSON.stringify(res).slice(0, 200)}` }
      }
      return { ok: true, rows: res.tickets as Array<Record<string, unknown>> }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      return { ok: false, rows: [], error: `ticket-list 不可达（引擎离线/超时）：${msg.slice(0, 300)}` }
    }
  }
}

/** wake 投递面：宿主会话服务探针式接入（S1-probe 落点）。
 *  依次找：sessions.get(id)?.prompt → sessionController 的 prompt 面；都不可达 =
 *  accepted:false + 点名原因（守望者状态面显式 wake: unavailable，绝不静默）。 */
export function makeWakeIo(ctx: Context): WakeIo {
  const probeReason = () => {
    const sessions = ctx.get('sessions') as unknown as { get?: (id: string) => { prompt?: unknown } | undefined } | undefined
    if (sessions && typeof sessions.get === 'function') {
      return 'sessions 服务在，但会话对象缺 prompt 面（S1-probe 未过）'
    }
    return '宿主 sessions 服务不可达（headless 或服务未注入）——wake 出口显式不可用'
  }
  return {
    async prompt(sessionId, text, mode): Promise<{ accepted: boolean; error?: string }> {
      const sessions = ctx.get('sessions') as unknown as { get?: (id: string) => { prompt?: unknown } | undefined } | undefined
      const sess = sessions && typeof sessions.get === 'function' ? sessions.get(sessionId) : undefined
      if (sess && typeof sess.prompt === 'function') {
        try {
          await (sess.prompt as (content: unknown, mode: string) => Promise<unknown>)([{ type: 'text', text }], mode)
          return { accepted: true }
        } catch (e) {
          return { accepted: false, error: String(e instanceof Error ? e.message : e) }
        }
      }
      return { accepted: false, error: probeReason() }
    },
    async queueDepth(_sessionId): Promise<number | null> {
      return null // 队列镜像面未接入（S1-probe）：显式 null，wakeExecutor 按无信号照发并点名
    },
  }
}

export function apply(ctx: Context, options: WatchdogPluginConfig = {}): void {
  const repo = options.repo ?? process.env.SANDBAR_REPO ?? defaultRepo()
  if (process.env.SANDBAR_REPO === undefined) process.env.SANDBAR_REPO = repo // Watchdog.ledgerDir 缺省推导用

  const watch = new Map<string, Watchdog>()
  const wakeIo = makeWakeIo(ctx)
  const boardReader = makeBoardReader(repo, options.python)

  /** 起/停一个项目的守望者（配置不存在或被停 = 显式 stopped，非消失）。 */
  async function ensureWatchdog(key: string): Promise<Watchdog> {
    let w = watch.get(key)
    if (w) return w
    w = new Watchdog(key, {
      io: defaultIo,
      boardReader,
      wakeIo,
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

  async function statusFor(key: string): Promise<WatchdogStatus & { heartbeat: Awaited<ReturnType<typeof readHeartbeatFile>> }> {
    const cfg = loadWatchdogConfig(key)
    if (!cfg.declared) {
      return {
        project: key, declared: false, enabled: false, phase: 'stopped', config_error: null,
        config_provenance: { file: null, keys: {} },
        heartbeat: { last_beat: null, age_seconds: null, alive: false, reason: '项目未声明（无 watchdog.json）——零行为，不是一切正常' },
        ledger: { path: '', watermark_offset: 0, rows_seen: 0, dupes_skipped: 0, malformed_rows: 0, gaps_seen: 0, last_row_at: null, unreadable: '项目未声明守望者' },
        liveness: { engine: { online: null, detail: '未探测', checked_at: null }, executor: null },
        self_lock: null, reconcile: null, startup: { missing_rows: null, replayed_rows: null, dedupe_keys: 0 },
        wakes: [], alerts: [], notify: { beep: false, unseen_redline: 0 }, last_error: null,
      } as never
    }
    const w = await ensureWatchdog(key)
    const st = w.status()
    const { join: j2 } = await import('node:path')
    const dataRoot = process.env.SANDBAR_WATCHDOG_DATA || join(process.env.HOME || '', '.sandbar', 'watchdog')
    st.heartbeat = await readHeartbeatFile(defaultIo, j2(dataRoot, `${key}.heartbeat.json`), Date.now())
    return st as never
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
      const keys = await declaredProjects()
      const projects = await Promise.all(keys.map(k => statusFor(k)))
      sendJson(res, 200, { ok: true, result: { projects, note: '未列出的项目 = 未声明（零行为）' } })
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

  // 全终态：宿主卸载时停掉一切守望者（定时器/在飞拍全收）。
  ctx.on('dispose', () => {
    for (const [k, w] of watch) {
      w.dispose()
      watch.delete(k)
    }
  })
}
