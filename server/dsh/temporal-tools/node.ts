/**
 * suyou-temporal-tools —— Temporal 编排工具面的 dsh 插件（模型可见工具，宿主半/node）。
 *
 * 机制（对照 suyou-tools.ts 的 spawn-python 薄壳制式）：
 *   ① 每个 dsh 工具 = spawn `<repo>/server/dsh/temporal-poc/.venv/bin/python
 *     <repo>/server/dsh/temporal-poc/client.py <子命令> <argsJSON>`，
 *     stdout 单行 JSON `{ok, result|error}` 原样成为工具返回；
 *   ② client.py 是唯一数据源（信号白名单、workflow 类型、payload 契约全在 python 侧钉死），
 *     本文件不复制业务逻辑，只把五个工具逐字注册成 dsh 裸 JSON Schema 工具。
 *
 * **安全红线（t260821-02，POC 证明点①；t260821-05 加 ticket_sign）**：工具面暴露
 *   start / query / signal / schedule-list / cancel / ticket_sign，
 *   **绝不暴露 set-stage / force_stage / 改状态工具**——一旦有，代码推进的不可变性立刻失效。
 *   client.py 的 signal 子命令只认 sign / retry_qc 两个 signal，force_stage 在 python 侧
 *   根本不存在 CLI 入口（workflow 里的 force_stage signal 仅用于 POC 越权反证，不暴露给模型）。
 *   ticket_sign（M3 新增）= 走 client.py `ticket` 子命令的 op=sign（TicketWorkflow 的
 *   签字白名单），schema 只有 ticket_id/who/gate/decision/note，无 set-stage。
 *
 * 只用 dsh 稳定面：apply(ctx) + ctx.tools.register；不碰 preview 不稳定面。
 *
 * repo 解析顺序：config.repo → SUYOU_REPO → 按本文件位置推导
 * （<repo>/server/dsh/temporal-tools/node.ts 上三级）。python 默认取
 * temporal-poc 目录内的 .venv/bin/python（temporalio SDK 装在仓库内 venv，不碰系统 python）。
 */

import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { closeSync, mkdirSync, openSync, readFileSync, realpathSync, unlinkSync, writeFileSync } from 'node:fs'
import net from 'node:net'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'

const execFileP = promisify(execFile)

export const name = 'suyou-temporal-tools'
export const inject = ['tools']

/** 本文件固定落在 <repo>/server/dsh/temporal-tools/ 下，上三级即仓库根。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/** temporal-poc 目录（client.py / .venv 都在这里面）。 */
const pocDir = (repo: string): string => join(repo, 'server', 'dsh', 'temporal-poc')

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface TemporalToolsConfig {
  /** 溯游仓库根。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器（要带 temporalio SDK）。缺省=temporal-poc/.venv/bin/python。 */
  python?: string
  /** 子进程超时（毫秒）。缺省 120000（start/query/signal 都是秒级返回）。 */
  timeoutMs?: number
  /** 是否启用 supervisor（boot 拉 temporal server+worker + keepalive 守护）。缺省 true。 */
  supervisor?: boolean
  /** supervisor 探测的 temporal gRPC 端口。缺省 7233（单例锁=这个端口只允许一个监听者）。 */
  port?: number
  /** keepalive 探测间隔（毫秒）。缺省 5000。 */
  keepaliveMs?: number
  /** worker pidfile 路径。缺省 <poc>/data/worker.pid（worker.py --daemon 自写）。 */
  pidfile?: string
  /** server 日志路径。缺省 <poc>/data/server.log。 */
  serverLog?: string
  /** worker 日志路径。缺省 <poc>/data/worker.log（worker.py --daemon 自写）。 */
  workerLog?: string
  /** 工单 worker ensure 间隔（毫秒，A 案：console 是工单 worker 唯一生产 spawn 点）。缺省 15000。 */
  ticketEnsureMs?: number
}

/** 一个 dsh 工具的静态 schema + execute（映射到 client.py 子命令）。 */
interface ToolSpec {
  name: string
  description: string
  parameters: Record<string, unknown>
  subcommand: string
  /** 可选：把模型参数重排成 client.py 该子命令要的 args（缺省原样透传）。 */
  mapArgs?: (args: any) => any
}

const TOOLS: ToolSpec[] = [
  {
    name: 'temporal_start',
    subcommand: 'start',
    description:
      '启动一个 Temporal workflow（content-pipeline 七段流水线 或 dispatcher-scan 巡检）。' +
      '返回 workflow_id / run_id；workflow 后续由 worker 执行、由 temporal query 读阶段。' +
      '单例：同一 workflow id 再次 start 会被服务端拒绝（AlreadyStarted）。',
    parameters: {
      type: 'object',
      properties: {
        type: {
          type: 'string',
          enum: ['content-pipeline', 'dispatcher-scan'],
          description: 'workflow 类型：content-pipeline（内容加工七段流水线）或 dispatcher-scan（工单巡检）。',
        },
        proposal: {
          type: 'string',
          description: '仅 content-pipeline：提案/工单 id（会成为 workflow id 的一部分，即单例锁）。',
        },
        title: { type: 'string', description: '仅 content-pipeline：提案标题（进事件历史的人话）。' },
        scope: { type: 'string', description: '仅 content-pipeline：机器校验 qc_run 的期次（默认 260627）。' },
        label: { type: 'string', description: '仅 content-pipeline：机器校验标签（默认 qc_run）。' },
        id: { type: 'string', description: '可选：显式指定 workflow id（缺省 content-pipeline:<proposal> 或 dispatcher-scan）。' },
      },
      required: ['type'],
    },
  },
  {
    name: 'temporal_query',
    subcommand: 'query',
    description:
      '只读查询一个 workflow 的实时快照（stage / stage_state / 门跑了几次 / 签字记录 / 时间线）。' +
      '只读，改不了状态——状态只能由 workflow 代码推进。',
    parameters: {
      type: 'object',
      properties: {
        workflow_id: { type: 'string', description: '要读的 workflow id（start 时返回的 workflow_id）。' },
      },
      required: ['workflow_id'],
    },
  },
  {
    name: 'temporal_signal',
    subcommand: 'signal',
    description:
      '给 workflow 发信号。安全红线：只认 sign（人工审批签字）与 retry_qc（请求重跑机器校验）两个信号；' +
      '不存在 force_stage / set-stage 入口。sign 是「人工审批」的唯一开启方式，who 由调用方注入身份。',
    parameters: {
      type: 'object',
      properties: {
        workflow_id: { type: 'string', description: '目标 workflow id。' },
        signal: {
          type: 'string',
          enum: ['sign', 'retry_qc'],
          description: '信号名：sign=人工审批签字（gate 只认 approve/final-review）；retry_qc=请求重跑机器校验（过不过仍由脚本说）。',
        },
        input: {
          description:
            'signal 载荷。sign 用 JSON 对象 {who, gate: approve|final-review, decision: approve|reject, note}；' +
            'retry_qc 用字符串（请求人 who）。',
        },
      },
      required: ['workflow_id', 'signal'],
    },
  },
  {
    name: 'temporal_schedule_list',
    subcommand: 'schedule-list',
    description:
      '列出 Temporal 上的 Schedule（定时触发巡检等）：id / 是否暂停 / 备注 / 下次触发时间 / 最近触发次数。只读。',
    parameters: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'temporal_cancel',
    subcommand: 'cancel',
    description:
      '停掉一个 workflow（Temporal terminate：强制结束并留历史，清场/撤销用）。不删历史。',
    parameters: {
      type: 'object',
      properties: {
        workflow_id: { type: 'string', description: '要停的 workflow id。' },
        reason: { type: 'string', description: '停掉原因（进历史，可追溯）。' },
      },
      required: ['workflow_id'],
    },
  },
  {
    name: 'ticket_sign',
    subcommand: 'ticket',
    description:
      '工单人工审批签字（TicketWorkflow 的签字；安全红线白名单：只发 sign，无 set-stage / force_stage）。' +
      '人工审批段（exit=human）挂起时唯一开启方式；who 由调用方注入身份（agent 不得自签自己的角色名），' +
      'gate 必须是当前等待的 exit=human 段 id（缺省取当前段），decision=reject 会打回（rework 回上一段）。',
    parameters: {
      type: 'object',
      properties: {
        ticket_id: { type: 'string', description: '工单 id（= workflow id，单例）。' },
        who: { type: 'string', description: '签字人身份（由调用方注入；agent 不得自签自己的角色名）。' },
        gate: { type: 'string', description: '人工审批段 id（exit=human 的 stage id）；空则取当前等待段。' },
        decision: {
          type: 'string',
          enum: ['approve', 'reject'],
          description: 'approve=签字通过推进下一段；reject=打回（rework 回上一段）。',
        },
        note: { type: 'string', description: '签字备注（进不可变事件历史）。' },
      },
      required: ['ticket_id'],
    },
    mapArgs: (args: any) => ({
      op: 'sign',
      ticket_id: args.ticket_id,
      input: { who: args.who, gate: args.gate, decision: args.decision, note: args.note },
    }),
  },
]

// ---- supervisor（t260821-04）：boot 探测端口单例 → spawn server+worker → keepalive 守护 ----

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/** TCP 探测端口：有监听者即「server 在线」。 */
function probePort(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    const sock = net.connect({ host, port })
    let settled = false
    const done = (ok: boolean) => {
      if (settled) return
      settled = true
      sock.destroy()
      resolve(ok)
    }
    sock.setTimeout(timeoutMs)
    sock.once('connect', () => done(true))
    sock.once('error', () => done(false))
    sock.once('timeout', () => done(false))
  })
}

/** 进程存活探测（kill -0）。ESRCH=没了；EPERM=还在只是没权限。 */
function isPidAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (err: any) {
    return err?.code === 'EPERM'
  }
}

/** 读 pidfile（worker.py --daemon 自写），拿不到/脏值返回 null。 */
function readPid(pidfile: string): number | null {
  try {
    const n = Number.parseInt(readFileSync(pidfile, 'utf8').trim(), 10)
    return Number.isInteger(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

// ---- worker 归属指纹（KI-033，t260904-02）----
// worker.py 起跑自写 meta JSON（SUYOU_WORKER_META 指路 / daemon 模式 <pidfile>.meta），
// 内容 {version, pid, repo_root, ts}（repo_root=realpath）。ensure 据此识别
// 异仓 worker 伺服同票。指纹=repo_root 路径而非 git HEAD——同仓先后 commit 不该
// 误判异仓（supervisor 与 worker 常是先后从同一棵树起的）。本节模块级 + export
// （契约=design_integration_tests 场景对齐真源）：readWorkerMeta/judgeTicketWorkerMeta/
// ensureTicketWorkersOnce——集成场景直接真调，断言落真执行路径行为输出（review C1）。

/** worker meta JSON 形状（写入方=worker.py shared.write_worker_meta）。 */
export interface WorkerMeta {
  version?: number
  pid?: number
  repo_root?: string
  ts?: number
}

/** 读 meta 结果：state 四态与 python 侧 shared.read_worker_meta_state 对齐。 */
export interface WorkerMetaRead {
  meta: WorkerMeta | null
  state: 'ok' | 'missing' | 'malformed' | 'read_error'
  detail: string
}

/** 读+校验 meta（对外契约形态）：可读且形状符 → meta；缺/坏/读失败 → null。 */
export function readWorkerMeta(path: string): WorkerMeta | null {
  return readWorkerMetaDetailed(path).meta
}

/** 读 meta 全量四态（内部用：unknown 留痕要 state/detail，review C3）。 */
export function readWorkerMetaDetailed(path: string): WorkerMetaRead {
  let raw: string
  try {
    raw = readFileSync(path, 'utf8')
  } catch (err: any) {
    if (err?.code === 'ENOENT') return { meta: null, state: 'missing', detail: `文件不存在：${path}` }
    return { meta: null, state: 'read_error', detail: `${err?.code ?? ''} ${err?.message ?? err}`.trim() }
  }
  let data: any
  try {
    data = JSON.parse(raw)
  } catch (err: any) {
    return { meta: null, state: 'malformed', detail: `JSON 不可解析：${err?.message ?? err}` }
  }
  if (typeof data !== 'object' || data === null
    || typeof data.repo_root !== 'string' || !data.repo_root
    || !Number.isInteger(data.pid)) {
    return { meta: null, state: 'malformed', detail: '形状不符（需 version/pid:int/repo_root:str）' }
  }
  return { meta: data, state: 'ok', detail: '' }
}

/** 判定在册工单 worker 归属：'same'（本仓，照旧跳过不重复拉）/'foreign'（异仓，
 * 告警+拒接——不杀别人进程，只不重复拉自己的；杀进程归人）/'unknown'（meta 缺失/
 * 畸形/读失败——兼容期按旧行为跳过，但 info 留痕可定位）。ownRepoRoot 应传
 * realpath 规范化后的本仓根。meta=null（缺/坏）直接 unknown。 */
export function judgeTicketWorkerMeta(
  meta: WorkerMeta | null, ownRepoRoot: string): 'same' | 'foreign' | 'unknown' {
  const root = meta?.repo_root
  if (!root) return 'unknown'
  if (root === ownRepoRoot) return 'same'
  // 字串不等再试 realpath 归一（比对双方口径一致，符号链接差异不产生假异仓）；
  // 对方路径已不可解析=确实不是本树，判 foreign（它伺服的就是别处的代码）。
  try {
    if (realpathSync(root) === ownRepoRoot) return 'same'
  } catch { /* 不可解析 → foreign */ }
  return 'foreign'
}

/** ensureTicketWorkersOnce 单轮决策（对外契约形态，可断言的行为记录面）。 */
export interface TicketWorkerDecision {
  tid: string
  action: 'spawned' | 'held-same' | 'held-foreign' | 'held-unknown'
  /** action=held-foreign 时必带：异仓根/pid/tid（告警记录的最小闭环）。 */
  warn?: { repoRoot: string; pid: number; tid: string }
  /** action=held-unknown 时必带：meta 路径/失败原因（兼容跳过不哑巴，review C3）。 */
  reason?: string
}

/** 单轮 ensure 的可注入依赖：running=在册 RUNNING 工单清单（fetch 归调用方）；
 * spawn 可注入（缺省=不拉起只记录——真拉起出口在 apply 闭包侧注入）。 */
export interface EnsureTicketWorkersOnceDeps {
  dataDir: string
  repoRoot: string
  running: { id: string; queue: string }[]
  spawn?: (tid: string, queue: string) => { pid: number } | void
}

/** 一轮工单 worker 归属判定 + 补拉决策（纯决策面，不做日志/网络）：
 * 在册 worker 带指纹 → held-same/held-foreign/held-unknown 三态；无活 worker →
 * spawned（spawn 出口由 deps.spawn 提供）。清 stale pidfile 后再抢注。 */
export async function ensureTicketWorkersOnce(
  deps: EnsureTicketWorkersOnceDeps): Promise<{ decisions: TicketWorkerDecision[] }> {
  const decisions: TicketWorkerDecision[] = []
  for (const r of deps.running) {
    const pf = join(deps.dataDir, `worker-${r.id}.pid`)
    const mf = join(deps.dataDir, `worker-${r.id}.meta`)
    const existing = readPid(pf)
    if (existing !== null && isPidAlive(existing)) {               // 别的 console/手动 worker 在册
      const read = readWorkerMetaDetailed(mf)
      const verdict = judgeTicketWorkerMeta(read.meta, deps.repoRoot)
      if (verdict === 'foreign') {
        decisions.push({
          tid: r.id, action: 'held-foreign',
          warn: { repoRoot: String(read.meta?.repo_root ?? '?'), pid: read.meta?.pid ?? existing, tid: r.id },
        })
        continue
      }
      if (verdict === 'unknown') {
        decisions.push({
          tid: r.id, action: 'held-unknown',
          reason: `meta=${mf} state=${read.state}：${read.detail}（pidfile=${pf} pid=${existing}）`,
        })
        continue
      }
      decisions.push({ tid: r.id, action: 'held-same' })           // 本仓在册，照旧
      continue
    }
    try { unlinkSync(pf) } catch { /* 无 pidfile */ }              // 清 stale 再抢注
    if (deps.spawn) {
      deps.spawn(r.id, r.queue)
      decisions.push({ tid: r.id, action: 'spawned' })
    } else {
      decisions.push({
        tid: r.id, action: 'held-unknown',
        reason: `worker 缺位且未提供 spawn 出口（pidfile=${pf}）——独立调用仅判定不拉起`,
      })
    }
  }
  return { decisions }
}

/** ensureTicketWorkers 的可注入依赖（apply 闭包真跑时全为真件）。 */
export interface EnsureTicketWorkersDeps {
  /** spawn `python client.py <子命令> <argsJSON>` 的真出口（场景可桩）。 */
  cli: (subcommand: string, args: unknown) => Promise<any>
  /** 工单 worker pidfile/meta 所在目录（<dataDir>/worker-<tid>.pid/.meta）。 */
  dataDir: string
  /** 本引擎仓根（realpath；指纹比对基准）。 */
  repoRoot: string
  /** 日志缝：warn=异仓告警，info=unknown 兼容跳过留痕。 */
  log: { info: (...a: unknown[]) => void; warn: (...a: unknown[]) => void }
  /** 本进程已持有的工单 worker 表（tid → ChildProcess）。 */
  ticketChildren: Map<string, ChildProcess>
  /** 本进程的工单 worker spawn 出口（场景可记录调用）。 */
  spawnTicketWorker: (tid: string, queue: string) => void
  /** supervisor 是否已 dispose。 */
  isDisposed: () => boolean
  /** temporal server 在线探测（ensure 前置条件）。 */
  serverAlive: () => Promise<boolean>
}

/** 一轮工单 ensure：server 在线才做；RUNNING 工单缺活 worker 的补拉；
 * 在册 worker 带归属指纹时按 same/foreign/unknown 三态处置（KI-033）。
 * 判定主体=ensureTicketWorkersOnce（真执行路径），本函数只做 fetch/日志/真 spawn。
 * 工单已收口但 worker 还活着的：不主动杀——worker 自己的 watch 30s 内优雅自退
 * （在跑 activity 做完再走），比 host 侧 SIGTERM 更干净。 */
export async function ensureTicketWorkers(deps: EnsureTicketWorkersDeps): Promise<void> {
  if (await deps.isDisposed() || !(await deps.serverAlive())) return
  let list: any
  try {
    list = await deps.cli('running-tickets', {})
  } catch (err: any) {
    deps.log.warn('suyou-temporal-tools supervisor: running-tickets 查询失败（下轮再试）：%s', err?.message ?? err)
    return
  }
  const runningAll: { id: string; queue: string }[] = list?.result?.running ?? []
  if (await deps.isDisposed()) return  // fetch 窗口内 dispose：立即短路不再拉起（acceptance P2）
  const running = runningAll.filter(r => !deps.ticketChildren.has(r.id))  // 本进程已持有的不管
  const { decisions } = await ensureTicketWorkersOnce({
    dataDir: deps.dataDir, repoRoot: deps.repoRoot, running,
    spawn: (tid, queue) => { deps.spawnTicketWorker(tid, queue); return { pid: -1 } },
  })
  for (const d of decisions) {
    if (await deps.isDisposed()) return
    const pf = join(deps.dataDir, `worker-${d.tid}.pid`)
    const mf = join(deps.dataDir, `worker-${d.tid}.meta`)
    if (d.action === 'held-foreign' && d.warn) {
      // 异仓 worker 伺服同票（260904 t260904-01 首开脑裂形态）：告警+拒接。
      // 绝不 kill 别人进程——杀进程归人（doctor --live 可扫异仓进程辅助清点）。
      deps.log.warn(
        'suyou-temporal-tools supervisor: [KI-033] 异仓 worker 伺服同票，拒接（不杀别人进程）：' +
        'tid=%s pid=%d 其引擎仓=%s 本仓=%s meta=%s —— 处置：人工清点该 worker 归属' +
        '（sandbar doctor --live 扫异仓引擎进程），确认后手动停它或迁移注册',
        d.tid, d.warn.pid, d.warn.repoRoot, deps.repoRoot, mf)
    } else if (d.action === 'held-unknown') {
      // meta 缺失/畸形/读失败三态都在 reason 里（review C3：兼容跳过不许哑巴）。
      // 行为不劣于现状（老版 worker 无 meta 照样跳过），但留痕可查。
      deps.log.info(
        'suyou-temporal-tools supervisor: 工单 worker %s 在册但无归属指纹——按兼容期处理不重复拉起；%s' +
        '（旧版 worker 请升级或清场）', d.tid, d.reason ?? `pidfile=${pf}`)
    }
  }
}

export function apply(ctx: Context, config?: TemporalToolsConfig): (() => void) | void {
  const repo = config?.repo ?? process.env.SUYOU_REPO ?? DEFAULT_REPO
  const python = config?.python ?? join(pocDir(repo), '.venv', 'bin', 'python')
  const timeoutMs = config?.timeoutMs ?? 120_000
  const clientPy = join(pocDir(repo), 'client.py')

  /** 唯一出口：spawn `python client.py <子命令> <argsJSON>`，stdout 单行 JSON。 */
  async function cli(subcommand: string, args: unknown): Promise<any> {
    const { stdout } = await execFileP(
      python,
      [clientPy, subcommand, JSON.stringify(args ?? {})],
      { cwd: pocDir(repo), maxBuffer: 16 * 1024 * 1024, timeout: timeoutMs },
    )
    return JSON.parse(stdout)
  }

  for (const t of TOOLS) {
    ctx.tools.register({
      name: t.name,
      description: `${t.description}（Temporal 审计=workflow 事件历史；client.py=${t.subcommand}）`,
      parameters: t.parameters,
      timeoutMs,
      output: {
        schema: {},
        render: (_args: unknown, value: unknown) => [{
          type: 'text' as const,
          text: typeof value === 'string' ? value : JSON.stringify(value, null, 1),
        }],
      },
      async execute(args: unknown, exec: { signal: AbortSignal }) {
        let res: any
        try {
          res = await cli(t.subcommand, t.mapArgs ? t.mapArgs(args) : args)
        } catch (err: any) {
          // 基础设施故障（连不上 temporal server / worker 不在线 / 超时）
          const detail = (err?.stderr ?? err?.message ?? String(err)).slice(0, 500)
          throw new Error(`temporal cli ${t.subcommand} 失败：${detail}`)
        }
        // ok=false 是结构化业务回执（如「未知 signal 名」「workflow 不存在」），抛错走 isError 路径。
        if (!res?.ok) {
          throw new Error(res?.error ?? '未知错误')
        }
        return res
      },
    } as any)
  }

  ctx.logger.info(
    'suyou-temporal-tools: 已注册 %d 个 Temporal 工具（repo=%s，client=%s）。' +
    '工具面只有 start/query/signal/schedule-list/cancel/ticket_sign，无 set-stage / force_stage。',
    TOOLS.length, repo, clientPy,
  )

  // ---- supervisor（t260821-04）：temporal server+worker 的托管守护 ----
  // 设计（详见 temporal-tools/README.md）：
  //   server = 托管子进程（spawn run_server.sh，持有 ChildProcess，dispose 优雅停）；
  //   worker = 走 worker.py --daemon（python 侧 fork+setsid 自守护），supervisor 用 pidfile 追踪、dispose 优雅停；
  //   单例 = 端口探测（7233 只允许一个监听者）+ worker pidfile 存活探测（多个 dsh 会话不重复起）。
  if (config?.supervisor === false) return

  const poc = pocDir(repo)
  const runServerSh = join(poc, 'run_server.sh')
  const workerPy = join(poc, 'worker.py')
  const dataDir = join(poc, 'data')
  const host = '127.0.0.1'
  const port = config?.port ?? 7233
  const keepaliveMs = config?.keepaliveMs ?? 5_000
  const ticketEnsureMs = config?.ticketEnsureMs ?? 15_000
  const pidfile = config?.pidfile ?? join(dataDir, 'worker.pid')
  const serverLog = config?.serverLog ?? join(dataDir, 'server.log')
  const workerLog = config?.workerLog ?? join(dataDir, 'worker.log')

  const PORT_PROBE_TIMEOUT = 1_500
  const SERVER_START_TIMEOUT = 30_000
  const RESTART_COOLDOWN = 5_000
  const GRACE_KILL = 3_000

  const log = ctx.logger

  // 状态：serverChild 非空 = 本会话 spawn（并「拥有」）的 server；workerSpawned = 本会话起过 worker。
  let serverChild: ChildProcess | null = null
  let workerSpawned = false
  let disposed = false
  let ensuring = false
  let lastServerSpawn = 0
  let lastWorkerSpawn = 0
  let serverFailures = 0
  let workerFailures = 0

  const serverAlive = () => probePort(host, port, PORT_PROBE_TIMEOUT)

  function workerAlive(): boolean {
    const pid = readPid(pidfile)
    return pid !== null && isPidAlive(pid)
  }

  function stopWorker() {
    const pid = readPid(pidfile)
    if (pid !== null && isPidAlive(pid)) {
      try {
        process.kill(pid, 'SIGTERM') // worker.py 接 SIGTERM → 优雅停（做完在跑 activity）
        log.info('suyou-temporal-tools supervisor: 已向 worker pid=%d 发 SIGTERM', pid)
      } catch (err: any) {
        log.warn('suyou-temporal-tools supervisor: 停 worker pid=%d 失败：%s', pid, err?.message ?? err)
      }
    }
  }

  function stopServer() {
    if (serverChild && serverChild.exitCode === null) {
      const child = serverChild
      child.kill('SIGTERM')
      log.info('suyou-temporal-tools supervisor: 已向 server pid=%d 发 SIGTERM', child.pid)
      setTimeout(() => {
        if (child.exitCode === null) {
          try { child.kill('SIGKILL') } catch { /* 已退 */ }
        }
      }, GRACE_KILL).unref()
    }
  }

  function spawnServer(): boolean {
    // 已有一个本会话 spawn 的、尚未退出的 server，或冷却期内，不再起。
    if (serverChild && serverChild.exitCode === null) return false
    if (Date.now() - lastServerSpawn < RESTART_COOLDOWN) return false
    lastServerSpawn = Date.now()
    try {
      mkdirSync(dataDir, { recursive: true })
      const fd = openSync(serverLog, 'a')
      const child = spawn(runServerSh, [], {
        cwd: poc,
        stdio: ['ignore', fd, fd], // run_server.sh exec temporal，stdout/stderr 进 data/server.log
        detached: false,
      })
      closeSync(fd)
      serverChild = child
      child.once('error', (err) => {
        log.error('suyou-temporal-tools supervisor: spawn server 失败：%s', err?.message ?? err)
        if (serverChild === child) serverChild = null
      })
      child.once('exit', (code, signal) => {
        if (serverChild === child) serverChild = null
        if (!disposed) {
          log.warn('suyou-temporal-tools supervisor: server 退出（code=%s signal=%s），keepalive 将重启', code, signal)
        }
      })
      log.info('suyou-temporal-tools supervisor: 已 spawn temporal server（pid=%d，port=%d）', child.pid, port)
      return true
    } catch (err: any) {
      log.error('suyou-temporal-tools supervisor: spawn server 异常：%s', err?.message ?? err)
      return false
    }
  }

  function spawnWorker(): boolean {
    if (Date.now() - lastWorkerSpawn < RESTART_COOLDOWN) return false
    lastWorkerSpawn = Date.now()
    try {
      // --daemon：worker.py 自己 fork+setsid，父进程立即退出，真 worker 是孙进程；此后 pidfile 是唯一真相。
      const child = spawn(python, [workerPy, '--daemon', '--pidfile', pidfile, '--logfile', workerLog], {
        cwd: poc,
        stdio: 'ignore',
      })
      child.once('error', (err) => {
        log.error('suyou-temporal-tools supervisor: spawn worker 失败：%s', err?.message ?? err)
      })
      child.once('exit', (code) => {
        if (code !== 0) log.warn('suyou-temporal-tools supervisor: worker daemonize 父进程退出 code=%s', code)
      })
      workerSpawned = true
      log.info('suyou-temporal-tools supervisor: 已 spawn worker（--daemon，pidfile=%s）', pidfile)
      return true
    } catch (err: any) {
      log.error('suyou-temporal-tools supervisor: spawn worker 异常：%s', err?.message ?? err)
      return false
    }
  }

  // ---- 工单 worker ensure（260824 A 案：工单 worker 跟 console 走）----
  // console 是工单 worker 的唯一生产 spawn 点（ticket.py create 不再 spawn）：
  // 每 ticketEnsureMs 查一次 running-tickets（轻量 visibility 查询，无 snapshot），
  // 缺 worker 的以**本进程子进程**拉起（不 daemonize——ppid=本 console，进程树即归属）。
  // dispose 时 SIGTERM 全部本进程 spawn 的工单 worker；console 被 SIGKILL 时
  // worker 靠 SUYOU_WATCH_PPID=1 自守（ppid 变 1 即优雅自退，见 worker.py）。
  // 多 console：pidfile wx 独占写定归属，撞车即杀自己 spawn 的重复进程；
  // 拥有者退出 → 其 worker 被带走/自退 → 存活 console 下一轮 ensure 补拉接管。
  const ticketChildren = new Map<string, ChildProcess>()

  /** 以本进程子进程拉起工单 worker；pidfile 抢注失败（别的 console 抢先）则杀掉重复进程。 */
  function spawnTicketWorker(tid: string, queue: string): void {
    const pf = join(dataDir, `worker-${tid}.pid`)
    const lf = join(dataDir, `worker-${tid}.log`)
    let fd: number
    try {
      mkdirSync(dataDir, { recursive: true })
      fd = openSync(lf, 'a')
    } catch (err: any) {
      log.warn('suyou-temporal-tools supervisor: 开工单 worker 日志失败（%s）：%s', tid, err?.message ?? err)
      return
    }
    let child: ChildProcess
    try {
      child = spawn(python, [workerPy], {
        cwd: poc,
        env: {
          ...process.env,
          SUYOU_TASK_QUEUE: queue,   // queue 名取自 running-tickets（执行本身），零常量复制
          SUYOU_WATCH_WORKFLOW: tid, // workflow 收口自退
          SUYOU_WATCH_PPID: '1',     // 宿主 SIGKILL → ppid=1 自退
          SUYOU_WORKER_META: join(dataDir, `worker-${tid}.meta`), // 归属指纹自报（KI-033，ensure 据此判异仓）
        },
        stdio: ['ignore', fd, fd],
      })
    } catch (err: any) {
      closeSync(fd)
      log.error('suyou-temporal-tools supervisor: spawn 工单 worker %s 异常：%s', tid, err?.message ?? err)
      return
    }
    closeSync(fd)
    child.once('error', (err) => {
      log.error('suyou-temporal-tools supervisor: 工单 worker %s spawn 失败：%s', tid, err?.message ?? err)
    })
    try {
      writeFileSync(pf, String(child.pid), { flag: 'wx' })
    } catch {
      log.info('suyou-temporal-tools supervisor: 工单 worker %s 已被别的实例抢先注册，停掉重复 spawn', tid)
      try { child.kill('SIGTERM') } catch { /* 已退 */ }
      return
    }
    ticketChildren.set(tid, child)
    child.once('exit', (code, sig) => {
      ticketChildren.delete(tid)
      // 只清自己写的 pidfile（内容=child.pid 才删，防误删别人新注册的）。
      if (readPid(pf) === child.pid) try { unlinkSync(pf) } catch { /* 已清 */ }
      // meta 旁车同理：worker 优雅停自清；这里兜底只清自己 child 的（内容=pid 才删）。
      const mf = join(dataDir, `worker-${tid}.meta`)
      try {
        const meta = readWorkerMeta(mf)
        if (meta?.pid === child.pid) unlinkSync(mf)
      } catch { /* 已清 */ }
      if (code !== 0 && sig === null) {
        log.warn('suyou-temporal-tools supervisor: 工单 worker %s 异常退出 code=%s', tid, code)
      } else {
        log.info('suyou-temporal-tools supervisor: 工单 worker %s 已退出（%s）', tid, sig ?? `code=${code}`)
      }
    })
    log.info('suyou-temporal-tools supervisor: 已 spawn 工单 worker（tid=%s pid=%d queue=%s）', tid, child.pid, queue)
  }

  // 工单 ensure 走模块级可注入实现（KI-033 三态判定；review C1：真执行路径可测），
  // 本闭包注入真件。isDisposed 读闭包态而非快照——dispose 后的轮次立即短路。
  const ticketEnsureDeps: EnsureTicketWorkersDeps = {
    cli,
    dataDir,
    repoRoot: realpathSync(repo),
    log,
    ticketChildren,
    spawnTicketWorker,
    isDisposed: () => disposed,
    serverAlive,
  }

  /** 一轮守护：server 没了就重启，server 在线但 worker 没了就重启 worker。 */
  async function ensureOnce(): Promise<void> {
    if (disposed || ensuring) return
    ensuring = true
    try {
      const up = await serverAlive()
      if (!up) {
        // 端口不通 = server 不在服务：先把本会话起的 stale worker 停掉（它连不上 server 干不了活）。
        if (workerSpawned) stopWorker()
        // 还持有一个 live child 但端口不通且已超启动超时 → 判挂死，强杀后重来（正常崩溃走 exit 钩子已置空）。
        if (serverChild && serverChild.exitCode === null && Date.now() - lastServerSpawn > SERVER_START_TIMEOUT) {
          try { serverChild.kill('SIGKILL') } catch { /* ignore */ }
          serverChild = null
        }
        if (!spawnServer()) return // 冷却期 / 还持有一个正在起的 child，本轮不动
        const deadline = Date.now() + SERVER_START_TIMEOUT
        let ok = false
        while (Date.now() < deadline && !disposed) {
          await sleep(500)
          if (await serverAlive()) { ok = true; break }
        }
        if (ok) {
          serverFailures = 0
          log.info('suyou-temporal-tools supervisor: temporal server 已就绪（port=%d）', port)
        } else {
          serverFailures += 1
          log.error('suyou-temporal-tools supervisor: temporal server %d 秒内未就绪（连续失败 %d 次）',
            SERVER_START_TIMEOUT / 1000, serverFailures)
          return
        }
      } else {
        serverFailures = 0
      }

      // worker：只在 server 在线时才要求 worker 存活。
      if (disposed || !(await serverAlive())) return
      if (!workerAlive()) {
        if (spawnWorker()) {
          // 给 daemonize + Client.connect 一点时间（实测 ~1.2s），短轮询等它出现在 pidfile 且进程存活。
          let alive = false
          for (let i = 0; i < 10; i++) { // 最多 ~5s
            await sleep(500)
            if (workerAlive()) { alive = true; break }
          }
          if (alive) {
            workerFailures = 0
          } else {
            workerFailures += 1
            log.warn('suyou-temporal-tools supervisor: worker 起后 %d 秒内未存活（连续失败 %d 次）', 5, workerFailures)
          }
        }
      } else {
        workerFailures = 0
      }
    } catch (err: any) {
      log.error('suyou-temporal-tools supervisor: 守护轮异常：%s', err?.message ?? err)
    } finally {
      ensuring = false
    }
  }

  // boot：启动即确保 server+worker 在线（端口探测保单例）。
  ensureOnce().catch((err) => log.error('suyou-temporal-tools supervisor: boot 失败：%s', err?.message ?? err))

  // keepalive：周期探测，崩了自动重启。
  const timer = setInterval(() => { void ensureOnce() }, keepaliveMs)

  // 工单 worker ensure（A 案）：独立节奏（15s），server 在线才干活。
  const ticketTimer = setInterval(() => { void ensureTicketWorkers(ticketEnsureDeps) }, ticketEnsureMs)
  void ensureTicketWorkers(ticketEnsureDeps)

  log.info('suyou-temporal-tools supervisor: 已启动（port=%d，keepalive=%dms，ticketEnsure=%dms，serverLog=%s）',
    port, keepaliveMs, ticketEnsureMs, serverLog)

  // dispose：只停「本会话 spawn 的」server/worker/工单 worker——不碰别人（手动/其它会话）已起的实例。
  return () => {
    disposed = true
    clearInterval(timer)
    clearInterval(ticketTimer)
    for (const [tid, child] of ticketChildren) {
      try {
        child.kill('SIGTERM') // 优雅停：在跑 activity 做完再走（worker.py 契约）
        log.info('suyou-temporal-tools supervisor: 已向工单 worker %s pid=%d 发 SIGTERM', tid, child.pid)
      } catch { /* 已退 */ }
    }
    ticketChildren.clear()
    if (workerSpawned) stopWorker()
    stopServer()
    log.info('suyou-temporal-tools supervisor: 已停（keepalive 停止；本会话 spawn 的 server/worker/工单 worker 已发 SIGTERM）')
  }
}
