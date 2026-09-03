/**
 * suyou-workbench —— 工单工作流台的 dsh UI 插件（宿主半 / node）。
 *
 * 职责：在 dsh 自己的 webServer 上挂 /suyou-workbench/api/wf/*（工单工作流台设计
 * v0.3 §5/§9），供本插件的浏览器半（lib/client.js，设置面板「工单台」分区）同源
 * fetch 使用。独立命名，不寄生 suyou-admin-ui 壳：
 *
 *   GET  /suyou-workbench/api/wf/projects       → 项目注册表（server/dsh/projects.yaml，260823 多项目化）：
 *                                                 project 是逻辑概念，1:N 对应目录；返回 key/name/dirs/primary
 *   GET  /suyou-workbench/api/wf/tickets?project=<key>
 *                                               → ticket list（按 ProjectKey SA 过滤；project 必传、无默认值；
 *                                                 台面行，awaiting-human 工单附 pending 审批理由）+ workflow list（全局模板表）
 *   GET  /suyou-workbench/api/wf/tickets/<id>   → ticket show（详情全文）
 *   POST /suyou-workbench/api/wf/tickets/<id>/accept|advance|dispatch-next|rework|update
 *                                               → 写操作，走 admin.py call ticket（run-id 审计）
 *   GET  /suyou-workbench/api/wf/workflows      → workflow list（模板链，泳道图用）
 *   GET  /suyou-workbench/api/wf/book?path=books/hanshu/jizhuan.json&limit=5
 *                                               → 内容预览（审批前过目）：只读 app/public/data/<path>，
 *                                                 返回 meta + 前 limit 章（标题+段落）；path 白名单防穿路径
 *   GET  /suyou-workbench/api/wf/temporal-health → Temporal 健康（只读，t260821-06）：真实探测
 *                                                 127.0.0.1:7233 端口是否监听（=server 在线）+ worker
 *                                                 pidfile pid 是否存活（=worker 在线），不写死结果
 *   GET  /suyou-workbench/api/wf/workers        → worker 清单（260824 每工单专属 worker）：
 *                                                 扫 data/worker*.pid 逐个探测存活（共享 suyou-poc +
 *                                                 专属 suyou-ticket-<id>），状态条「N workers」数据源
 *   GET  /suyou-workbench/api/wf/scan-report    → 巡检报告（只读，M6 t260821-m6-scan-expand）：
 *                                                 读 temporal-poc/out/scan/ 文件名序最新的
 *                                                 <YYYY-MM-DD>.json（DispatcherScanWorkflow 落盘）；
 *                                                 无报告走 reason 人话降级，不抛错
 *   POST /suyou-workbench/api/global-session/open {project}
 *                                               → 新建全局会话（session-entry t260825-02，侧栏「会话」区
 *                                                 新建按钮）：仿工单会话开/找，但 id 不带 ticket- 前缀、
 *                                                 不注入工单上下文、always-create（全局会话每次新建一个；
 *                                                 cwd=该项目注册表主目录）
 *   GET  /suyou-workbench/api/wf/tickets/<id>/agent-logs
 *                                               → 工单 agent 日志（只读，M12 t260822-m12）：
 *                                                 定泳道/隔离目录 .suyou/，列 agent_<stage>_gen<n>.log
 *                                                 （子 agent stdout/stderr 流）+ stage_<stage>_gen<n>.json
 *                                                 （段结算结果），带尾部内容/解析结果；无目录走
 *                                                 reason 人话降级，不抛错
 *   GET  /suyou-workbench/api/wf/tickets/<id>/agent-live?n=30
 *                                               → agent 实时动态（只读，t260825-03）：泳道
 *                                                 .dsh/sessions/<cwd-slug>/<工单id>-<角色>/
 *                                                 session.jsonl.zstd 整解（zstd -dc，多帧拼接
 *                                                 直接解）取尾部 n 条事件摘要（assistant 文本截断 /
 *                                                 工具调用名+目标路径）；无会话文件/解压失败走
 *                                                 {exists:false,reason} 降级；工单字段 ../ 逃逸 → 400
 *
 * 立项单只读 API（epic-linkage Tier 2，t260825-04；真源=notes/epics/*.md + Temporal
 * 查询，UI 不存状态——立项单关键决策 5；代号存在性=文件存在性强校验——决策 2）：
 *   GET  /suyou-workbench/api/epics            → 列 notes/epics/*.md：代号（文件名主名）/
 *                                                 标题（首个 # 行）/状态（字段表格「状态」行）/
 *                                                 立项日期；目录不存在/无文件 → 空数组不报错
 *   GET  /suyou-workbench/api/epics/<code>     → 单份立项单 Markdown 全文；代号形状白名单
 *                                                 （shared.EPIC_CODE_RE 同款）+ 路径防穿双保险，
 *                                                 非法 400 / 不存在 404 人话
 *   GET  /suyou-workbench/api/epics/<code>/tickets
 *                                               → 该立项全部工单实时状态聚合（复用 ticket list
 *                                                 --epic 通路）：按 status 分桶计数 + 工单行
 *                                                 （id/title/status/stage/stage_state）；Temporal
 *                                                 不可达 → {degraded:true, reason} 降级不 502
 *   POST /suyou-workbench/api/epics/<code>/suggest-next
 *                                               → 「继续执行」建议 job 启动（t260827-02）：spawn 一次性
 *                                                 headless integration agent 分析立项现状，产出下一步
 *                                                 工单建议（模板/标题/正文）；同 code 进行中 job 复用
 *                                                 不重复起。agent 只产建议，不直接创建工单
 *   GET  /suyou-workbench/api/epics/<code>/suggest-next/<jobId>
 *                                               → 建议 job 轮询：{state:running|done|failed,
 *                                                 suggestion?|reason?}；宿主重启丢注册表 → 404
 *                                                 （前端重新点击即可）
 *   归档快照 POST /epics/<code>/archive 本工单不做（无调用方，留给归档动作真正发生时的工单）。
 *
 * PR 式审批台（M9，t260821-m9-pr-approval）：
 *   GET  /suyou-workbench/api/wf/tickets/<id>/diff
 *                                               → 工单变更集（只读）：泳道道=worktree 工作树 vs base_ref
 *                                                 文件级 diff（文档=渲染态 block diff 复用 knowledge
 *                                                 blocks.ts / 代码=unified diff / 数据=前后值对账）；
 *                                                 主树道=write_set+git log，给不出显「无变更记录」。
 *   GET  /suyou-workbench/api/wf/tickets/<id>/review
 *                                               → 读审批意见（server/dsh/reviews/<工单id>.json，无则空 rounds）
 *   POST /suyou-workbench/api/wf/tickets/<id>/review {base, conclude, blocks[], reviewer?}
 *                                               → 追加一轮审批意见落盘（工单 id 白名单防穿路径、
 *                                                 admin.log 同形 JSONL 审计+run-id；块 key 含内容哈希，
 *                                                 内容变→旧意见客户端标「已过期」，支持多轮迭代）
 *
 * 数据源=server/tools/ticket.py（M1 已落地）：读写统一走 runAdminCli spawn
 * admin.py（读列也走，不直读 json）——与模型通道 suyou-tools 共用同一函数，
 * run-id 审计唯一数据源始终在 python server/admin.log（面板写操作不另开审计通道）。
 * M11 v2（t260822-m11 模版即代码）+ 260823 多项目化：**工单状态只在 Temporal
 * workflow**（旧 tickets/ JSON 投影目录已删）——ticket.py 薄壳内部全走 client.py
 * ticket-start/ticket-list/ticket-query/ticket，本插件路由按 project 传参即完成分流；
 * v2 行带 engine 标记，前端操作矩阵走 v2 分支
 * （无 dispatch-next/逐项 accept；blocked 的「解除阻塞」=retry-qc → Temporal retry_qc
 * signal，与 sign 同款直发）。
 * 待审批（awaiting-human）的审批/打回走签字（v2 base 的 sign signal，
 * decision=approve/reject），由本插件 spawn temporal-poc client.py 直发。
 * book 预览为纯只读文件服务（app/public/data/ 下，白名单 books/ 前缀）。
 *
 * headless profile 没有 webServer 服务：apply 静默待命（internal/service 事件
 * 等不到就什么都不挂），不报错不阻塞。
 *
 * repo 解析顺序：config.repo → SUYOU_REPO → 按本文件位置推导
 * （<repo>/server/dsh/workbench/node.ts 上三级）。无任何机器绝对路径写死。
 */

import { execFile } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { appendFile, readFile, readdir, stat } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import net from 'node:net'
import { dirname, join, resolve, sep } from 'node:path'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'
import { runAdminCli } from '../suyou-tools.ts'
import { findProject, loadProjects, primaryDir, type ProjectEntry } from '../suyou-projects.ts'
import { computeTicketDiff, type TicketForDiff } from './src/host/changes.ts'
import { readLatestScanReport } from './src/host/scan-report.ts'
import { listAgentLogs, resolveSuyouBaseDir, _sessionKbFast } from './src/host/agent-logs.ts'
import { readAgentLiveTail, resolveSessionFile } from './src/host/agent-live.ts'
import { aggregateTicketUsage, resolveAllSessionFiles, stageWindowsFromTimeline } from './src/host/agent-usage.ts'
import { buildMetricsResponse, defaultDeps } from './src/host/metrics.ts'
import { computeHostFingerprint, type HostFingerprint } from './src/host/build-info.ts'
import { closeEpic, isEvidenceFileName, listEpics, readEpicMarkdown, resolveEpicsDir, setEpicStatus } from './src/host/epics.ts'
import {
  dismissPrecache, findRunningJob, pollSuggestJob, precacheExists, readPrecache,
  readPrecacheHint, resolvePrecacheDir, startEpicNextJanitor, startSuggestJob, stateKeyFromRows,
  type EpicNextJob,
} from './src/host/epic-next.ts'
import {
  CONCLUDES, appendReviewRound, loadReview,
  type ReviewBlockEntry, type ReviewConclude, type ReviewRound,
} from '../knowledge/src/shared/review-store.ts'

const execFileP = promisify(execFile)

export const name = 'suyou-workbench'
// webServer 只存在于 web profile；headless 下本插件待机即可，故不走 inject 硬依赖。
export const inject: string[] = []

/** 本文件固定落在 <repo>/server/dsh/workbench/ 下，上三级即仓库根。 */
const DEFAULT_REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')

/**
 * host 启动指纹（t260902-03 陈旧看守）：仅首次解析固化——apply 可能被宿主重放/
 * 多次调用，每次刷新会把新磁盘指纹误记为 boot 指纹，stale 永假（一日三咬照样咬）。
 * 不变量：进程内只算一次（Promise 单例），之后 apply 重放不覆盖。导出供 smoke await。
 */
let bootFingerprintP: Promise<HostFingerprint> | undefined
export function resolveBootFingerprint(repo: string): Promise<HostFingerprint> {
  bootFingerprintP ??= computeHostFingerprint(repo)
  return bootFingerprintP
}

/** 插件配置（cordis.patch.yml 里 config: 字段；全部可缺省）。 */
interface SuyouWorkbenchConfig {
  /** 溯游仓库根。缺省按本文件位置推导。 */
  repo?: string
  /** python 解释器，默认 python3。 */
  python?: string
  /** 子进程超时（毫秒），默认 300000。 */
  timeoutMs?: number
}

/** 详情路由前缀（prefix kind 挂在它下面；注册 path 不带尾斜杠——
 * webserver 的 prefix 匹配按 `${prefix}/` 判定，带尾斜杠会拼出双斜杠永不命中）。 */
const TICKETS_PREFIX = '/suyou-workbench/api/wf/tickets'
/** 立项单路由前缀（epic-linkage Tier 2）：exact 挂列表，prefix 挂 <code>[ /tickets]。 */
const EPICS_PREFIX = '/suyou-workbench/api/epics'
/** POST 操作白名单（admin.py 引擎的 op 子集 + sign=审批签字走 Temporal signal；
 *  M11 v2 加 retry-qc=blocked 重跑走 Temporal retry_qc signal）。
 *  create 不进此表：它没有工单 id，落 exact 路由 /wf/tickets 的 POST 分支
 *  （handleTicketCreate，epic-linkage Tier 3 / t260826-02），与 <id>/<op> 路径正交。
 *  review（审批意见落盘）不进此表——它不经过 admin.py，在路由里按 method 单独分支。 */
const OPS = new Set(['accept', 'advance', 'dispatch-next', 'rework', 'update', 'sign', 'retry-qc'])

/** 工单 id 白名单：review 落盘文件名由它拼出，必须防穿路径（同 knowledge DOC_PATH_RE 的角色）。
 *  放行 Han 字（真实工单 id 含中文，54 张全量体检零误伤）；/ \ . % 与控制字符全在表外，穿路径无门。 */
const TICKET_ID_RE = /^[A-Za-z0-9\p{Script=Han}][A-Za-z0-9_\-\p{Script=Han}]{2,80}$/u

/**
 * 工单快照 → 首条上下文消息（t260831-08 从 handleTicketSessionOpen 的闭包抽出，
 * 逻辑主体逐字迁移；smoke 直测同口径防实现漂移）。唯一偏离（t260831-08 方案取舍
 * 清单 #5）：pending/acceptance 加 Array.isArray 防线——工单数据来自 Temporal 投影，
 * 字段类型漂移是现实输入，原 `?? []` 写法对对象型 pending 会在 .slice 抛 TypeError。
 */
export function ticketContext(input: any): string {
  const tk = (input && typeof input === 'object') ? input : {}
  const lines: string[] = [
    `【工单上下文】${tk.id}《${tk.title ?? ''}》`,
    `工作流：${tk.workflow ?? '—'} · 角色：${tk.role ?? '—'} · 当前阶段：${tk.stage ?? '—'}（${tk.stage_state ?? '—'}）`,
  ]
  if (tk.blocked_reason) lines.push(`阻塞原因：${tk.blocked_reason}`)
  const pend = Array.isArray(tk.pending) ? tk.pending as any[] : []
  for (const p of pend.slice(0, 5)) lines.push(`待审批：${p?.gate ?? ''} — ${p?.reason ?? ''}`)
  const acc = Array.isArray(tk.acceptance) ? tk.acceptance as any[] : []
  if (acc.length > 0) lines.push(`验收标准：\n${acc.slice(0, 8).map((a, i) => `${i + 1}. ${a}`).join('\n')}`)
  const bodyText = String(tk.body ?? '').trim()
  if (bodyText) lines.push(`工单正文：\n${bodyText.slice(0, 600)}${bodyText.length > 600 ? '…' : ''}`)
  lines.push('——以上是这张工单的快照。接下来的对话都围绕它：先回我一段你对现状的理解和下一步建议。')
  return lines.join('\n')
}

/**
 * 工单截图证据文件列表（t260831-08）：GET /wf/tickets/<id>/evidence 的数据源。
 * 读序与既有取图端点（handleTicketEvidence，t260829-02）一致：①主树归档
 * <base>/<id>/（base=SUYOU_EVIDENCE_DIR env 或 <repo>/.suyou/evidence）；②泳道
 * <repo>/.worktrees/<id>/.suyou/screenshots/。取舍清单（t260831-08 方案 gen1
 * #1b/#1c/#1d）：目录级 containment（resolve 后 startsWith 各自数据根——词法纵深
 * 防御，配合 TICKET_ID_RE 不含 / 和 . 双保险）；枚举结果逐名过 isEvidenceFileName
 * （泳道目录可能被手塞怪名文件，不进列表即不渲染）；目录不存在→该候选空（软降级
 * 不报错，枚举语义没有 404，files=[] 即人话）。symlink 防线不带：截图目录内容来自
 * 自家 QA agent 工具产物，非外部输入，与既有取图端点同洞（不单侧加防线造伪安全）。
 */
export async function listEvidenceFiles(id: string, repo: string): Promise<string[]> {
  if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) return []
  const base = process.env.SUYOU_EVIDENCE_DIR ?? join(repo, '.suyou', 'evidence')
  const roots = [resolve(base), resolve(repo, '.worktrees')]
  const dirs = [
    resolve(roots[0], id),
    resolve(roots[1], id, '.suyou', 'screenshots'),
  ]
  const seen = new Set<string>()
  for (let i = 0; i < dirs.length; i++) {
    const dir = dirs[i]
    if (!dir.startsWith(roots[i] + sep)) continue // containment：越界基目录直接跳过
    let names: string[]
    try {
      names = await readdir(dir)
    } catch {
      continue // 目录不存在（已合并工单/无截图）→ 该候选空
    }
    for (const n of names) {
      if (isEvidenceFileName(n)) seen.add(n)
    }
  }
  return [...seen].sort()
}

/** Temporal 状态探测（t260821-06）：真实探测，不写死结果。 */
const TEMPORAL_HOST = '127.0.0.1'
const TEMPORAL_PORT = 7233
const PORT_PROBE_TIMEOUT_MS = 800

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
async function readPid(pidfile: string): Promise<number | null> {
  try {
    const n = Number.parseInt((await readFile(pidfile, 'utf8')).trim(), 10)
    return Number.isInteger(n) && n > 0 ? n : null
  } catch {
    return null
  }
}

/** 读 POST JSON body（64KB 封顶），非法 JSON 抛错。 */
async function readJsonBody(req: IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []
  let size = 0
  for await (const chunk of req) {
    size += (chunk as Buffer).length
    if (size > 64 * 1024) throw new Error('body 超过 64KB')
    chunks.push(chunk as Buffer)
  }
  const text = Buffer.concat(chunks).toString('utf8')
  return text === '' ? {} : JSON.parse(text)
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(JSON.stringify(body))
}

export function apply(ctx: Context, config?: SuyouWorkbenchConfig): void {
  const repo = config?.repo ?? process.env.SUYOU_REPO ?? DEFAULT_REPO
  // host 陈旧看守（t260902-03）：boot 指纹只在首次 apply 固化（见模块级注释的不变量）。
  void resolveBootFingerprint(repo)
  const cli = { repo, python: config?.python, timeoutMs: config?.timeoutMs }
  /** 审批意见落盘锚点：reviewsAnchor=<repo>/server/dsh，loadReview 再拼 reviews/<工单id>.json。 */
  const reviewsAnchor = join(repo, 'server', 'dsh')
  /** 立项单目录：SUYOU_EPICS_DIR env 优先（shared.py EPICS_DIR 同款先例），缺省 <repo>/notes/epics。 */
  const epicsDir = resolveEpicsDir(repo)

  // t260829-07 epic-next 泄漏修复：宿主侧 janitor 定时扫 JOBS 补 poll（前端停 poll
  // 后 running job 的 agent 进程不再无人回收）。unref，不拖宿主退出。
  startEpicNextJanitor()

  /** 调 admin.py call <tool> <args>，成功/结构化失败都原样透传（含 run_id）。 */
  async function callTool(tool: string, args: unknown): Promise<any> {
    return runAdminCli(cli, ['call', tool, JSON.stringify(args ?? {})])
  }

  /** 调 temporal-poc client.py（Temporal TicketWorkflow：sign 审批签字走这里）。 */
  async function runPocCli(_cli: { repo: string }, args: string[]): Promise<any> {
    const poc = join(repo, 'server', 'dsh', 'temporal-poc')
    const python = join(poc, '.venv', 'bin', 'python')
    const { stdout } = await execFileP(python, [join(poc, 'client.py'), ...args], {
      cwd: repo,
      timeout: 120_000,
    })
    return JSON.parse(stdout)
  }

  /** 台面：ticket list + workflow list 并行；awaiting-human 工单再 show 取 pending（审批理由显性化）。
   *  多项目化（260823）：?project=<key> 必传（projects.yaml 注册表，无默认值）——
   *  工单按 ProjectKey search attribute 过滤（Temporal 侧）；workflow 模板表是全局的，不过滤。 */
  /** 新建工单（epic-linkage Tier 3，t260826-02）：立项单详情页「新建工单」入口的落点——
   *  代号由界面传值（UI 无手输框），本层只透传不重复校验：epic 强校验单点在
   *  client.py validate_epic_code（notes/epics/<代号>.md 存在性），拒收错误经 admin.py
   *  ok:false 原样透传给 UI。审计=admin.py run-id 机制（与面板其他写操作同口径）。
   *  注意：本改动属 host 半，需重启 dsh 才生效。 */
  async function handleTicketCreate(req: IncomingMessage, res: ServerResponse, projectKey: string): Promise<void> {
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const workflow = String(body?.workflow ?? '')
    const title = String(body?.title ?? '').trim()
    if (!workflow) {
      sendJson(res, 400, { ok: false, error: 'create 需要 workflow（模板 id）' })
      return
    }
    if (!title) {
      sendJson(res, 400, { ok: false, error: 'create 需要 title（工单标题）' })
      return
    }
    const epic = String(body?.epic ?? '')
    try {
      const args: Record<string, unknown> = {
        op: 'create',
        project: projectKey,
        workflow,
        title,
        body: String(body?.body ?? ''),
        epic,
      }
      // t260829-07 写集生命周期：弹层写集编辑栏随票透传（数组逐项 String；空数组
      // 不带——「无文件改动」票走客户端显式 allow_empty_write_set，host 不代办）。
      if (Array.isArray(body?.write_set) && body.write_set.length > 0) {
        args.write_set = body.write_set.map((w: unknown) => String(w))
      }
      // t260901-01「无文件改动」显式声明透传：仅客户端显式 true 才带（host 不代办、
      // 不默认）。引擎口（client.py ticket-start）空写集+声明才放行，meta 记 no_file_changes。
      if (body?.allow_empty_write_set === true) {
        args.allow_empty_write_set = true
      }
      const r = await callTool('ticket', args)
      // t260829-06 追加：建票成功即失效该立项的「下一步已备」预跑缓存——新票一出现，
      // 缓存里的建议就是过期的（state_key 失配），挂着只会让列表徽标说谎。
      // best-effort：删失败不影响建票结果。
      if (r?.ok === true && epic) {
        try {
          await dismissPrecache(resolvePrecacheDir(repo), epic)
        } catch { /* 缓存删除失败不阻塞建票 */ }
      }
      sendJson(res, 200, r)
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  async function handleTickets(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const projectKey = String(url.searchParams.get('project') ?? '')
    if (!projectKey) {
      sendJson(res, 400, { ok: false, error: '缺 project 参数（projects.yaml 注册表 key，无默认值）' })
      return
    }
    try {
      // 白名单校验（注册表损坏抛错在这把住）；未知 key/形状非法 findProject 回 undefined 不抛——
      // 必须显式判空，否则白名单形同虚设（t260826-02 顺手修复：原代码只 try/catch 不判空）。
      if (!findProject(projectKey)) {
        sendJson(res, 400, { ok: false, error: `未知项目 key：'${projectKey}'（projects.yaml 注册表无此项）` })
        return
      }
    } catch (err) {
      sendJson(res, 400, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    // method 分支（t260826-02）：GET=list（下）、POST=create（上）、其余 405。
    if (req.method === 'POST') {
      await handleTicketCreate(req, res, projectKey)
      return
    }
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '工单列表只支持 GET（列表）/ POST（新建）' })
      return
    }
    try {
      const [t, w] = await Promise.all([
        callTool('ticket', { op: 'list', project: projectKey }),
        callTool('workflow', { op: 'list' }),
      ])
      const tickets = t?.result?.tickets ?? []
      // workflow list 返回 {workflows:[...]}（M1 引擎结构），兼容裸数组。
      const workflows = w?.result?.workflows ?? (Array.isArray(w?.result) ? w.result : [])
      // 审批理由：awaiting-human 工单（list 不含 pending 内容）并行 show 补上，供行内「审批：…」显示。
      const pendingOnes = tickets.filter((tk: any) => tk.stage_state === 'awaiting-human' && tk.status !== 'closed')
      if (pendingOnes.length > 0) {
        const shows = await Promise.all(pendingOnes.map((tk: any) => callTool('ticket', { op: 'show', id: tk.id })))
        shows.forEach((s, i) => {
          const pend = (s?.result?.pending ?? []) as any[]
          if (pend.length > 0) tickets.find((tk: any) => tk.id === pendingOnes[i].id)!.pending = pend
        })
      }
      // 补充运行中工单的 agent 进度（轻量 stat，不解压）
      const running = tickets.filter((tk: any) => tk.stage_state === 'running' && tk.worktree)
      await Promise.all(running.map(async (tk: any) => {
        try {
          const sessDir = join(repo, tk.worktree, '.dsh', 'sessions')
          const info = await _sessionKbFast(sessDir)
          if (info.kb > 0) {
            tk.session_kb = info.kb
            tk.agent_alive = info.alive
          }
        } catch { /* 静默 */ }
      }))
      sendJson(res, 200, { ok: true, result: { count: tickets.length, tickets }, workflows })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 内容预览（审批前过目）：只读 app/public/data/<path>，path 白名单 books/ 前缀 + 防穿路径。 */
  async function handleBook(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    const p = url.searchParams.get('path') ?? ''
    if (!/^books\/(?:[A-Za-z0-9_\-\u4e00-\u9fff]+\/)?[A-Za-z0-9_\-\u4e00-\u9fff]+\.json$/.test(p)) {
      sendJson(res, 404, { ok: false, error: 'path 不合法（books/<文件>.json 或 books/<册>/<文件>.json）' })
      return
    }
    const root = resolve(repo, 'app', 'public', 'data')
    const abs = resolve(root, p)
    if (abs !== root && !abs.startsWith(root + sep)) {
      sendJson(res, 404, { ok: false, error: 'path 越界（穿路径拒绝）' })
      return
    }
    const limit = Math.max(1, Math.min(20, Number(url.searchParams.get('limit')) || 5))
    try {
      const text = await readFile(abs, 'utf8')
      const data = JSON.parse(text)
      const chapters = (Array.isArray(data.章节) ? data.章节 : []).slice(0, limit).map((c: any) => ({
        id: String(c?.id ?? ''),
        标题: String(c?.标题 ?? ''),
        paras: Array.isArray(c?.正文) ? (c.正文 as unknown[]).map(String) : [],
      }))
      sendJson(res, 200, {
        ok: true,
        result: {
          preview: true,
          meta: {
            主题: String(data.主题 ?? ''),
            类型: String(data.类型 ?? ''),
            期次: String(data.期次 ?? ''),
            total_chapters: (Array.isArray(data.章节) ? data.章节 : []).length,
            size_kb: Math.round(text.length / 1024),
          },
          chapters,
        },
      })
    } catch (err: any) {
      if (err?.code === 'ENOENT') {
        sendJson(res, 404, { ok: false, error: `书文件不存在: ${p}` })
        return
      }
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /** 模板列表（泳道图/筛选用，台面接口已附带，独立路由供单独刷新）。 */
  async function handleWorkflows(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const w = await callTool('workflow', { op: 'list' })
      const workflows = w?.result?.workflows ?? (Array.isArray(w?.result) ? w.result : [])
      sendJson(res, 200, { ok: true, result: workflows })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** Temporal 健康（只读）：server=7233 端口监听，worker=pidfile pid 存活，真实探测。
   *  worker pidfile 缺省 <repo>/server/dsh/temporal-poc/data/worker.pid（worker.py --daemon 自写，
   *  与 suyou-temporal-tools supervisor 的 pidfile 同一真相源）。 */
  async function handleTemporalHealth(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const workerPidfile = join(repo, 'server', 'dsh', 'temporal-poc', 'data', 'worker.pid')
    const serverOnline = await probePort(TEMPORAL_HOST, TEMPORAL_PORT, PORT_PROBE_TIMEOUT_MS)
    const pid = await readPid(workerPidfile)
    const workerOnline = pid !== null && isPidAlive(pid)
    sendJson(res, 200, {
      ok: true,
      result: {
        ts: Math.floor(Date.now() / 1000),
        server: {
          online: serverOnline,
          host: TEMPORAL_HOST,
          port: TEMPORAL_PORT,
          detail: serverOnline
            ? `${TEMPORAL_HOST}:${TEMPORAL_PORT} 端口监听中`
            : `${TEMPORAL_HOST}:${TEMPORAL_PORT} 未监听（server 离线）`,
        },
        worker: {
          online: workerOnline,
          pid,
          pidfile: workerPidfile,
          detail: workerOnline
            ? `pid ${pid} 存活（${workerPidfile}）`
            : (pid !== null
              ? `pid ${pid} 已退出（pidfile ${workerPidfile}）`
              : `无 pidfile（${workerPidfile}）`),
        },
        restart_hint: {
          server: 'cd server/dsh/temporal-poc && ./run_server.sh（或重启控制台，supervisor 会自动拉起）',
          worker: 'cd server/dsh/temporal-poc && .venv/bin/python worker.py --daemon（或重启控制台，supervisor 会自动拉起）',
        },
      },
    })
  }

  /** Worker 清单（260824 每工单专属 worker）：扫 data/worker*.pid 逐个探测存活。
   *  worker.pid=共享队列 suyou-poc；worker-<工单id>.pid=专属队列 suyou-ticket-<id>。
   *  工单台状态条「N workers」点开即是本接口的清单。 */
  async function handleWorkers(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const dataDir = join(repo, 'server', 'dsh', 'temporal-poc', 'data')
    const workers: unknown[] = []
    try {
      const files = await readdir(dataDir)
      for (const f of files.sort()) {
        const m = /^worker(?:-(.+))?\.pid$/.exec(f)
        if (!m) continue
        const tid = m[1] ?? ''
        const pid = await readPid(join(dataDir, f))
        const online = pid !== null && isPidAlive(pid)
        let logMtime: number | null = null
        try {
          logMtime = Math.floor((await stat(join(dataDir, `worker${tid ? `-${tid}` : ''}.log`))).mtimeMs / 1000)
        } catch { /* 无日志文件（前台 worker 直打 stdout） */ }
        workers.push({
          ticket: tid || null,
          queue: tid ? `suyou-ticket-${tid}` : 'suyou-poc',
          pid,
          online,
          log_mtime: logMtime,
        })
      }
    } catch { /* data 目录不存在 → 空清单 */ }
    sendJson(res, 200, {
      ok: true,
      result: {
        count: workers.length,
        count_alive: (workers as { online: boolean }[]).filter(w => w.online).length,
        workers,
      },
    })
  }

  /* ------------------------------------------------ M9 PR 式审批台：diff + review */

  /** 变更集（只读）：worktree/base_ref/write_set 读工单 JSON 字段，计算在 src/host/changes.ts。 */
  async function handleTicketDiff(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendJson(res, 404, { ok: false, error: `工单不存在或读取失败：${String(s?.error ?? id)}` })
        return
      }
      const t = s.result as TicketForDiff
      const result = await computeTicketDiff(repo, {
        id, worktree: t.worktree, base_ref: t.base_ref, write_set: t.write_set,
      })
      sendJson(res, 200, { ok: true, result })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 读审批意见：server/dsh/reviews/<工单id>.json（复用 knowledge review-store 的读改写与文件形制）。 */
  async function handleTicketReviewGet(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      sendJson(res, 200, { ok: true, result: await loadReview(reviewsAnchor, id) })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /** 追加一轮审批意见（制式照 knowledge /review/save：白名单防穿+admin.log 同形审计+run-id）。 */
  async function handleTicketReviewSave(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    const runId = randomUUID().replace(/-/g, '').slice(0, 12)
    if (!TICKET_ID_RE.test(id)) {
      await audit(runId, 'review.save', { ticket: id }, false, '工单 id 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: '工单 id 不合法' })
      return
    }
    let body: any
    try {
      body = await readJsonBody(req)
    } catch (err) {
      await audit(runId, 'review.save', { ticket: id }, false, '请求体非法 JSON')
      sendJson(res, 400, { ok: false, run_id: runId, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const base = typeof body?.base === 'string' ? body.base : ''
    if (!/^[A-Za-z0-9._~^/-]*$/.test(base)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'base 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'base 不合法' })
      return
    }
    const conclude = body?.conclude as ReviewConclude
    if (!CONCLUDES.includes(conclude)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'conclude 不合法')
      sendJson(res, 400, { ok: false, run_id: runId, error: `conclude 必须是 ${CONCLUDES.join(' | ')}` })
      return
    }
    if (!Array.isArray(body?.blocks)) {
      await audit(runId, 'review.save', { ticket: id }, false, 'blocks 缺/非数组')
      sendJson(res, 400, { ok: false, run_id: runId, error: 'blocks 必须是数组' })
      return
    }
    const blocks: ReviewBlockEntry[] = []
    for (const b of body.blocks as any[]) {
      if (typeof b?.block_key !== 'string' || b.block_key === '') {
        await audit(runId, 'review.save', { ticket: id }, false, 'block 缺 block_key')
        sendJson(res, 400, { ok: false, run_id: runId, error: '每个 block 必须带 block_key' })
        return
      }
      const decision = b.decision === 'approve' || b.decision === 'reject' ? b.decision : undefined
      blocks.push({
        block_key: b.block_key.slice(0, 300),
        summary: typeof b.summary === 'string' ? b.summary.slice(0, 120) : '',
        type: typeof b.type === 'string' ? b.type : '',
        status: typeof b.status === 'string' ? b.status : '',
        decision,
        comment: typeof b.comment === 'string' && b.comment !== '' ? b.comment.slice(0, 2000) : undefined,
      })
    }
    const reviewer = typeof body?.reviewer === 'string' && body.reviewer.trim() !== ''
      ? body.reviewer.trim().slice(0, 40) : 'user'
    const round: ReviewRound = { base, ts: Math.floor(Date.now() / 1000), reviewer, conclude, blocks }
    try {
      const saved = await appendReviewRound(reviewsAnchor, id, round)
      const summary = `${id} 第 ${saved.rounds.length} 轮 conclude=${conclude} 块 ${blocks.length}`
      await audit(runId, 'review.save', { ticket: id, base, conclude, blocks: blocks.length }, true, summary)
      ctx.logger.info('suyou-workbench: review.save %s（run-id %s）', summary, runId)
      sendJson(res, 200, { ok: true, run_id: runId, result: { ticket: id, rounds: saved.rounds.length, round } })
    } catch (err: any) {
      await audit(runId, 'review.save', { ticket: id }, false, String(err?.message ?? err))
      sendJson(res, 500, { ok: false, run_id: runId, error: String(err?.message ?? err) })
    }
  }

  /**
   * admin.log 同款审计（同 knowledge 插件的取舍：为一条文件写入不 spawn python，
   * 直接按同一 JSONL schema 追加 server/admin.log，审计单一真源保持一致）。
   */
  async function audit(runId: string, name: string, args: unknown, ok: boolean, summary: string): Promise<void> {
    const rec = JSON.stringify({
      run_id: runId, ts: Math.floor(Date.now() / 1000), actor: 'suyou-workbench',
      name, args, ok, summary: summary.length > 800 ? summary.slice(0, 800) + '…' : summary,
    })
    try {
      await appendFile(join(repo, 'server', 'admin.log'), rec + '\n', 'utf8')
    } catch (err: any) {
      ctx.logger.warn('suyou-workbench: admin.log 审计写入失败（不影响主流程）：%s', String(err?.message ?? err))
    }
  }

  /**
   * 工单截图证据只读端点（t260829-02）：GET /wf/tickets/<id>/evidence/<file>。
   * 读序：①主树归档 <repo>/.suyou/evidence/<id>/<file>（泳道拆树后 report 引图不死链）；
   * ②泳道在时 <repo>/.worktrees/<id>/.suyou/screenshots/<file>（命名约定 lane/t<id>，
   * merge 拆树后自然落空，归档处兜底）。防穿三层：TICKET_ID_RE 白名单 + 文件名白名单
   * （^[A-Za-z0-9._-]+$ 且 .png 结尾）+ resolve 落点断言。归档基目录 SUYOU_EVIDENCE_DIR
   * env 可覆盖（python 侧 _archive_shots 同名 env 互指，自测指向临时目录）。
   */
  async function handleTicketEvidence(res: ServerResponse, id: string, file: string): Promise<void> {
    if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) {
      sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
      return
    }
    if (!isEvidenceFileName(file)) {
      sendJson(res, 400, { ok: false, error: `证据文件名不合法：'${file.slice(0, 60)}'（要求 ^[A-Za-z0-9._-]+$ 且 .png 结尾）` })
      return
    }
    const base = process.env.SUYOU_EVIDENCE_DIR ?? join(repo, '.suyou', 'evidence')
    const candidates = [
      resolve(base, id, file),
      resolve(repo, '.lane', id, '.suyou', 'screenshots', file),
      resolve(repo, '.worktrees', id, '.suyou', 'screenshots', file),
    ]
    for (const abs of candidates) {
      const root = resolve(abs, '..', '..')
      if (!abs.startsWith(root + sep)) continue // 落点越界（.. 穿越等），直接跳过
      try {
        const png = await readFile(abs)
        res.writeHead(200, { 'content-type': 'image/png', 'cache-control': 'no-store' })
        res.end(png)
        return
      } catch (err: any) {
        if (err?.code === 'ENOENT') continue // 下一候选
        sendJson(res, 500, { ok: false, error: `证据读取失败：${String(err?.message ?? err)}` })
        return
      }
    }
    sendJson(res, 404, { ok: false, error: `证据不存在：${file}（归档处与泳道 screenshots 均无）` })
  }

  /**
   * 工单截图证据列表端点（t260831-08）：GET /wf/tickets/<id>/evidence（无 file 段）。
   * 数据源=listEvidenceFiles（归档+泳道两候选枚举，防穿/降级口径见其注释）。
   * 空列表=200 files:[]（枚举语义无 404；「证据不存在」的人话由取图端点承担）。
   */
  async function handleTicketEvidenceList(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id) || /[./]/.test(id)) {
      sendJson(res, 400, { ok: false, error: `工单 id 不合法：'${id.slice(0, 40)}'` })
      return
    }
    try {
      sendJson(res, 200, { ok: true, result: { files: await listEvidenceFiles(id, repo) } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: `证据列表读取失败：${String(err instanceof Error ? err.message : err)}` })
    }
  }

  /** 详情 + 操作：prefix 路由，<id> 或 <id>/<op>。 */
  async function handleTicketRoute(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    let rest: string
    try {
      rest = decodeURIComponent(url.pathname.slice(TICKETS_PREFIX.length)).replace(/^\/+/, '')
    } catch {
      sendJson(res, 400, { ok: false, error: '路径含非法百分号编码' })
      return
    }
    const parts = rest.split('/').filter(Boolean)
    if (parts.length === 1) {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: '详情只支持 GET' })
        return
      }
      try {
        const r = await callTool('ticket', { op: 'show', id: parts[0] })
        // 补充 agent 进度（轻量 stat）
        const tk = r?.result
        if (tk && tk.stage_state === 'running' && tk.worktree) {
          try {
            const info = await _sessionKbFast(join(repo, tk.worktree, '.dsh', 'sessions'))
            if (info.kb > 0) { tk.session_kb = info.kb; tk.agent_alive = info.alive }
          } catch { /* 静默 */ }
        }
        sendJson(res, 200, r)
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    if (parts.length === 3 && parts[1] === 'evidence') {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'evidence 只支持 GET（只读图片）' })
        return
      }
      await handleTicketEvidence(res, parts[0], parts[2])
      return
    }
    if (parts.length === 2) {
      const [id, op] = parts
      // t260831-08：evidence 列表只读 GET（详情抽屉「截图证据」区数据源；
      // 带文件段的取图在同前缀 3 段路由，见上方 handleTicketEvidence）。
      if (op === 'evidence' && req.method === 'GET') {
        await handleTicketEvidenceList(res, id)
        return
      }
      // M9：diff / review 是只读 GET；review 的 POST 是审批意见落盘（不走 admin.py）。
      if (op === 'diff' && req.method === 'GET') {
        await handleTicketDiff(res, id)
        return
      }
      // M12：agent-logs 只读 GET（工单 agent 日志，见 handleAgentLogs）。
      if (op === 'agent-logs' && req.method === 'GET') {
        await handleAgentLogs(res, id)
        return
      }
      // t260825-03：agent-live 只读 GET（泳道会话事件流尾部，「实时动态」面板数据源）。
      if (op === 'agent-live' && req.method === 'GET') {
        await handleAgentLive(req, res, id)
        return
      }
      // t260828-07：agent-usage 只读 GET（token 消耗聚合，同一解析通路的第二个端点）。
      if (op === 'agent-usage' && req.method === 'GET') {
        await handleAgentUsage(res, id)
        return
      }
      if (op === 'review') {
        if (req.method === 'GET') {
          await handleTicketReviewGet(res, id)
          return
        }
        if (req.method === 'POST') {
          await handleTicketReviewSave(req, res, id)
          return
        }
        sendJson(res, 405, { ok: false, error: 'review 只支持 GET（读）/ POST（落盘一轮）' })
        return
      }
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '操作只支持 POST' })
        return
      }
      if (!OPS.has(op)) {
        sendJson(res, 404, { ok: false, error: `未知操作 ${op}（可用：${[...OPS].join('/')}）` })
        return
      }
      let body: any
      try {
        body = await readJsonBody(req)
      } catch (err) {
        sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
        return
      }
      try {
        // sign = 审批签字（awaiting-human 人工审批段）：走 Temporal TicketWorkflow 的签字
        // （decision=approve 放行推进 / reject 打回），不经 admin.py（引擎对 human 门只认 sign）。
        if (op === 'sign') {
          const decision = body.decision === 'reject' ? 'reject' : 'approve'
          const note = String(body.note ?? '')
          const who = String(body.who ?? 'op-local')
          const pocArgs = {
            op: 'sign',
            ticket_id: id,
            input: { who, gate: '', decision, note },
          }
          const r = await runPocCli(cli, ['ticket', JSON.stringify(pocArgs)])
          sendJson(res, 200, r)
          return
        }
        // M11 v2：retry-qc = blocked 工单请求重跑本段（Temporal retry_qc signal，新旧类同名）。
        if (op === 'retry-qc') {
          const who = String(body.who ?? 'op-local')
          const r = await runPocCli(cli, ['signal', JSON.stringify({
            workflow_id: id, signal: 'retry_qc', input: who,
          })])
          sendJson(res, 200, r)
          return
        }
        // 面板通道写操作直接执行（总管操作本身即意图）；审计由 admin.py run-id 机制承担。
        const args: Record<string, unknown> = { op, id }
        if (op === 'accept') {
          for (const k of ['item', 'done', 'by', 'evidence', 'agent']) {
            if (body[k] !== undefined) args[k] = body[k]
          }
        } else if (op === 'advance') {
          if (body.note !== undefined) args.note = body.note
        } else if (op === 'dispatch-next') {
          if (body.mark_running !== undefined) args.mark_running = body.mark_running
        } else if (op === 'rework') {
          if (!body.note) {
            sendJson(res, 400, { ok: false, error: 'rework 需要 note（返工原因）' })
            return
          }
          args.note = body.note
          if (body.to_stage !== undefined) args.to_stage = body.to_stage
        } else if (op === 'update') {
          for (const k of ['status', 'stage_state', 'note', 'pending_add']) {
            if (body[k] !== undefined) args[k] = body[k]
          }
        }
        const r = await callTool('ticket', args)
        sendJson(res, 200, r)
      } catch (err) {
        sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
      }
      return
    }
    sendJson(res, 404, { ok: false, error: '路径不合法：/suyou-workbench/api/wf/tickets/<id>[/op | /evidence/<file>]' })
  }

  /** 巡检报告（M6，只读）：最新一份 out/scan/<YYYY-MM-DD>.json；无报告走 reason 降级。 */
  async function handleScanReport(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const scanDir = join(repo, 'server', 'dsh', 'temporal-poc', 'out', 'scan')
      sendJson(res, 200, { ok: true, result: await readLatestScanReport(scanDir) })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * host 陈旧看守读侧（t260902-03，只读）：GET /suyou-workbench/api/build-info。
   * 现算磁盘指纹与启动指纹比对，stale=true 即「磁盘 host 半已更新、console 进程
   * 还在跑旧码」，客户端据此渲染全局「重启 console 生效」横幅。指纹全缺（部署
   * 形态异常）→ stale:false + error 人话，客户端见 error 有意降级不显横幅
   * （不属于陈旧提醒范畴，不静默绕过——响应里带 error 字段显性化）。
   */
  async function handleBuildInfo(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'build-info 只支持 GET（只读看守）' })
      return
    }
    try {
      const disk = await computeHostFingerprint(repo)
      if (disk.error !== undefined) {
        sendJson(res, 200, {
          ok: true,
          result: { stale: false, error: disk.error, missing: disk.missing },
        })
        return
      }
      const boot = bootFingerprintP === undefined ? undefined : await bootFingerprintP
      sendJson(res, 200, {
        ok: true,
        result: {
          stale: boot?.hash !== undefined && disk.hash !== boot.hash,
          bootFingerprint: boot?.hash,
          diskFingerprint: disk.hash,
          missing: disk.missing,
        },
      })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /**
   * metrics 读侧聚合（t260901-20，只读，M1a）：GET /suyou-workbench/api/wf/metrics。
   * 聚合唯一实现在 src/host/metrics.ts（与 metrics-cli.mjs CLI 前门同函数同缓存，
   * 契约块 2「同实现同缓存」）；本 handler 只做 query 透传（同名重复参数由
   * parseMetricsQuery 防穿）与 sendJson 回包，4xx {error,reason} / 200 响应形状
   * 单点在 metrics.ts。零逻辑前门——改动聚合口径请改 metrics.ts，勿在此堆逻辑。
   */
  async function handleMetrics(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: 'metrics 只支持 GET（只读聚合）' })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    try {
      const r = await buildMetricsResponse(url.searchParams, defaultDeps(repo))
      // 回包即契约块 2 冻结响应本体（不再包 {ok,result} 外壳）：CLI 前门 stdout
      // 是同一份 body，双前门字节级一致才成立（M3 基线比较面）。
      sendJson(res, r.status, r.body)
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }


  /* ---------------------------------- 立项单只读 API（epic-linkage Tier 2） */

  /** 立项单列表：列 notes/epics/*.md（目录不存在/无文件 → 空数组不报错）。 */
  async function handleEpics(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '立项单列表只支持 GET' })
      return
    }
    try {
      const epics = await listEpics(epicsDir)
      // t260829-02：轻量带上「下一步已备」缓存命中标记（只 stat pre.json 存在性，
      // 不逐个算 state_key；准态由详情响应 nextHint 承担），前端列表行直接消费。
      const cacheDir = resolvePrecacheDir(repo)
      const withHint = await Promise.all(epics.map(async (e) => ({
        ...e,
        nextHintCached: await precacheExists(cacheDir, e.code),
      })))
      sendJson(res, 200, { ok: true, result: { count: withHint.length, epics: withHint } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 立项单工单聚合（只读）：复用 ticket list --epic 通路（handleTickets 同款 callTool）。
   *  前置与详情路由同口径：形状 400 / 不存在 404（拦住后 ticket.py 侧强校验不会再以
   *  引擎错误冒出）；其后 callTool 抛错或回 ok:false 一律降级 {degraded:true, reason}
   *  （reason 透传底层 error 原文，不吞成空泛「不可用」），不 502。 */
  async function handleEpicTickets(res: ServerResponse, code: string): Promise<void> {
    const chk = await readEpicMarkdown(epicsDir, code)
    if (!chk.ok) {
      sendJson(res, chk.status, { ok: false, error: chk.error })
      return
    }
    let r: any
    try {
      r = await callTool('ticket', { op: 'list', epic: code })
    } catch (err) {
      const detail = String(err instanceof Error ? err.message : err)
      sendJson(res, 200, { ok: true, result: { code, degraded: true, reason: `工单状态查询降级：admin.py 调用失败——${detail}` } })
      return
    }
    if (r?.ok !== true) {
      const detail = String(r?.error ?? '返回缺 error 字段')
      sendJson(res, 200, { ok: true, result: { code, degraded: true, reason: `工单状态查询降级：ticket list 失败——${detail}` } })
      return
    }
    const rows = ((r.result?.tickets ?? []) as any[]).map((t) => ({
      id: String(t?.id ?? ''),
      title: String(t?.title ?? ''),
      status: String(t?.status ?? ''),
      stage: String(t?.stage ?? ''),
      stage_state: String(t?.stage_state ?? ''),
    }))
    const buckets: Record<string, number> = {}
    for (const row of rows) buckets[row.status || 'unknown'] = (buckets[row.status || 'unknown'] ?? 0) + 1
    sendJson(res, 200, { ok: true, result: { code, count: rows.length, buckets, tickets: rows } })
  }

  /** 「继续执行」建议 job 启动（t260827-02，host 半，需重启 dsh 生效）：
   *  code 校验复用 readEpicMarkdown 口径（形状 400/不存在 404）；同 code 有进行中
   *  job 直接复用（不重复 spawn agent）；模板清单（验证建议合法性的白名单基准）
   *  拿不到 → 502 可重试（不放行无校验的建议）；工单状态汇总失败降级为说明文字
   *  内联进 prompt（不阻塞建议链路）。 */
  async function handleSuggestNextStart(res: ServerResponse, code: string): Promise<void> {
    const chk = await readEpicMarkdown(epicsDir, code)
    if (!chk.ok) {
      sendJson(res, chk.status, { ok: false, error: chk.error })
      return
    }
    const existing = findRunningJob(code)
    if (existing) {
      sendJson(res, 200, { ok: true, result: { job_id: existing.jobId, state: existing.state, reused: true } })
      return
    }
    let workflows: { id: string; name: string }[]
    try {
      const w = await callTool('workflow', { op: 'list' })
      if (w?.ok !== true) {
        sendJson(res, 502, { ok: false, error: `模板清单查询失败：${String(w?.error ?? '返回缺 error 字段')}（可重试）` })
        return
      }
      workflows = ((w.result?.workflows ?? []) as any[])
        .map((x) => ({ id: String(x?.id ?? ''), name: String(x?.name ?? '') }))
        .filter((x) => x.id !== '')
    } catch (err) {
      sendJson(res, 502, { ok: false, error: `模板清单查询失败：${String(err instanceof Error ? err.message : err)}（可重试）` })
      return
    }
    let ticketsSummary: string
    let ticketRows: { id: string; closed: boolean }[] = []
    try {
      const t = await callTool('ticket', { op: 'list', epic: code })
      if (t?.ok === true) {
        const rows = ((t.result?.tickets ?? []) as any[]).map((x) => ({
          id: String(x?.id ?? ''), title: String(x?.title ?? ''), status: String(x?.status ?? ''),
          stage: String(x?.stage ?? ''), stage_state: String(x?.stage_state ?? ''),
        }))
        ticketRows = rows.map((r) => ({ id: r.id, closed: r.status === 'closed' }))
        ticketsSummary = rows.length === 0 ? '（本立项暂无关联工单）' : JSON.stringify(rows, null, 1)
      } else {
        ticketsSummary = `（工单状态查询失败：${String(t?.error ?? '未知错误')}，请基于立项单全文判断）`
      }
    } catch (err) {
      ticketsSummary = `（工单状态查询失败：${String(err instanceof Error ? err.message : err)}，请基于立项单全文判断）`
    }
    // 预跑缓存命中（t260828-08）→ 秒回，不再 spawn agent 冷启动（1~5 分钟 → 毫秒级）。
    // state_key 口径：点击时本票已 closed（ticketRows 里就是 closed），与 python 预跑侧
    // 「当前票强制 closed」口径对齐（shared.py epic_state_key / stateKeyFromRows 互指）。
    // 坏缓存 readPrecache 一律当未命中 → 落回下方原冷起路径。
    if (ticketRows.length > 0) {
      const cached = await readPrecache(
        resolvePrecacheDir(repo), code,
        stateKeyFromRows(ticketRows, ''), workflows.map((w) => w.id))
      if (cached) {
        sendJson(res, 200, { ok: true, result: { state: 'done', suggestion: cached, cached: true } })
        return
      }
    }
    try {
      const job: EpicNextJob = await startSuggestJob({
        repo, code, epicTitle: chk.title, epicMarkdown: chk.markdown, ticketsSummary, workflows,
      })
      sendJson(res, 200, { ok: true, result: { job_id: job.jobId, state: job.state, reused: false } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: `建议任务启动失败：${String(err instanceof Error ? err.message : err)}` })
    }
  }

  /** 建议 job 轮询：done 带 suggestion / failed 带人话 reason（200 透传，前端黄条降级）。 */
  async function handleSuggestNextPoll(res: ServerResponse, code: string, jobId: string): Promise<void> {
    if (!/^[a-z0-9-]{6,80}$/.test(jobId)) {
      sendJson(res, 400, { ok: false, error: `job id 形状不合法：'${jobId}'` })
      return
    }
    const job = await pollSuggestJob(jobId)
    if (!job || job.code !== code) {
      sendJson(res, 404, { ok: false, error: '无此建议任务（宿主可能已重启，回到立项单重新点击「继续执行」即可）' })
      return
    }
    const result: Record<string, unknown> = { job_id: job.jobId, state: job.state }
    if (job.state === 'done') result.suggestion = job.suggestion
    if (job.state === 'failed') result.reason = job.reason ?? '未知原因'
    sendJson(res, 200, { ok: true, result })
  }

  /** 立项详情的「下一步建议」准态（t260829-02）：工单集合现算 state_key（本票已
   *  closed 口径，currentTicketId 传 '' 与 suggest-next 缓存命中路径同款）+
   *  readPrecacheHint 全量校验。任一查询失败 → null（详情不被建议链路拖垮）。 */
  async function epicNextHintFor(code: string): Promise<unknown> {
    try {
      const [w, t] = await Promise.all([
        callTool('workflow', { op: 'list' }),
        callTool('ticket', { op: 'list', epic: code }),
      ])
      if (w?.ok !== true || t?.ok !== true) return null
      const workflowIds = ((w.result?.workflows ?? []) as any[])
        .map((x) => String(x?.id ?? '')).filter((x) => x !== '')
      const rows = ((t.result?.tickets ?? []) as any[]).map((x) => ({
        id: String(x?.id ?? ''), closed: String(x?.status ?? '') === 'closed',
      }))
      return await readPrecacheHint(
        resolvePrecacheDir(repo), code, stateKeyFromRows(rows, ''), workflowIds)
    } catch {
      return null
    }
  }

  /** 立项单详情/工单聚合/继续执行建议：prefix 路由，<code> 或 <code>/tickets
   *  （只读 GET）或 <code>/suggest-next[/<jobId>]（t260827-02：POST 启动 + GET 轮询）。 */
  async function handleEpicRoute(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', 'http://x')
    let rest: string
    try {
      rest = decodeURIComponent(url.pathname.slice(EPICS_PREFIX.length)).replace(/^\/+/, '')
    } catch {
      sendJson(res, 400, { ok: false, error: '路径含非法百分号编码' })
      return
    }
    const parts = rest.split('/').filter(Boolean)
    // suggest-next 两支（t260827-02）须在下面的 GET-only 405 之前分支。
    if (parts.length === 2 && parts[1] === 'suggest-next') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: 'suggest-next 启动只支持 POST' })
        return
      }
      await handleSuggestNextStart(res, parts[0])
      return
    }
    if (parts.length === 3 && parts[1] === 'suggest-next') {
      if (req.method !== 'GET') {
        sendJson(res, 405, { ok: false, error: 'suggest-next 轮询只支持 GET' })
        return
      }
      await handleSuggestNextPoll(res, parts[0], parts[2])
      return
    }
    // 结项动作（t260828-08）：POST /epics/<code>/close——立项目标达成后人审确认，
    // 外科改写 notes/epics/<code>.md 状态表行为「已完结」（写前备份 /tmp）。须在
    // 下面的 GET-only 405 之前分支。
    if (parts.length === 2 && parts[1] === 'close') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '结项动作只支持 POST（人审确认语义）' })
        return
      }
      const r = await closeEpic(epicsDir, parts[0])
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: r.code, status: r.status } })
      return
    }
    // 状态编辑动作（t260831-05）：POST /epics/<code>/status {status, note?}——枚举白名单
    // 校验 + 外科改写状态行 + 可选更新备注列 + 写前 /tmp 备份（setEpicStatus 与 close
    // 单点共用骨架）。须在下面的 GET-only 405 之前分支。note 语义：缺省/null=不动备注，
    // ''=清空，非空=写入（形状校验在 setEpicStatus/validateEpicNote 单口径）。
    if (parts.length === 2 && parts[1] === 'status') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '状态编辑只支持 POST（写动作语义）' })
        return
      }
      let body: any
      try {
        body = await readJsonBody(req)
      } catch {
        sendJson(res, 400, { ok: false, error: '请求体必须是合法 JSON（readJsonBody 64KB 封顶）' })
        return
      }
      if (body === null || typeof body !== 'object' || typeof body.status !== 'string') {
        sendJson(res, 400, { ok: false, error: '请求体必须是 {"status": "<四值枚举>", "note"?: <单行字符串>}，status 必填字符串' })
        return
      }
      const r = await setEpicStatus(epicsDir, parts[0], body.status, body.note)
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: r.code, status: r.status, note: r.note } })
      return
    }
    if (req.method !== 'GET') {
      sendJson(res, 405, { ok: false, error: '立项单路由只支持 GET（只读）' })
      return
    }
    if (parts.length === 1) {
      const r = await readEpicMarkdown(epicsDir, parts[0])
      if (!r.ok) {
        sendJson(res, r.status, { ok: false, error: r.error })
        return
      }
      // t260829-02：详情准态「下一步建议」——state_key 现算 + readPrecacheHint 全量
      // 校验（命中才带 nextHint；工单/模板清单查询失败一律静默 null，不拖垮详情）。
      const nextHint = await epicNextHintFor(parts[0])
      sendJson(res, 200, {
        ok: true,
        result: {
          code: r.code,
          path: `notes/epics/${r.code}.md`,
          title: r.title,
          status: r.status,
          note: r.note,
          created: r.created,
          markdown: r.markdown,
          nextHint,
        },
      })
      return
    }
    // [忽略] 动作（t260829-02）：POST /epics/<code>/next-hint/dismiss——删预跑缓存
    // pre.json（幂等；删除前备份 /tmp）。须在 GET-only 405 之前分支。
    if (parts.length === 3 && parts[1] === 'next-hint' && parts[2] === 'dismiss') {
      if (req.method !== 'POST') {
        sendJson(res, 405, { ok: false, error: '忽略建议只支持 POST（写动作语义）' })
        return
      }
      const chk = await readEpicMarkdown(epicsDir, parts[0])
      if (!chk.ok) {
        sendJson(res, chk.status, { ok: false, error: chk.error })
        return
      }
      const dr = await dismissPrecache(resolvePrecacheDir(repo), parts[0])
      if (!dr.ok) {
        sendJson(res, dr.status, { ok: false, error: dr.error })
        return
      }
      sendJson(res, 200, { ok: true, result: { code: dr.code, dismissed: true } })
      return
    }
    if (parts.length === 2 && parts[1] === 'tickets') {
      await handleEpicTickets(res, parts[0])
      return
    }
    sendJson(res, 404, { ok: false, error: '路径不合法：/suyou-workbench/api/epics/<代号>[/tickets | /suggest-next[/<jobId>] | /next-hint/dismiss | /close | /status]' })
  }

  /** 工单 agent 日志（M12，只读）：show 工单 → 定 .suyou 目录 → 列 agent_*.log / stage_*.json。
   *  无目录/无文件走 reason 人话降级（不抛错）；id 白名单在进 show 前拦（防穿）。 */
  async function handleAgentLogs(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendJson(res, 404, { ok: false, error: `工单不存在或读取失败：${String(s?.error ?? id)}` })
        return
      }
      const t = s.result ?? {}
      const { base, reason } = resolveSuyouBaseDir(repo, id, t)
      const result = await listAgentLogs(base)
      if (reason !== undefined && result.reason === undefined) result.reason = reason
      sendJson(res, 200, { ok: true, result })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** agent 实时动态（t260825-03，只读）：show 工单 → 定泳道会话文件 → 整解取尾 n 条事件摘要。
   *  降级契约仿 agent-logs：无会话/解压失败 → 200 {exists:false,reason} 不抛错；
   *  防穿比 agent-logs 更严（验收硬性要求）：id 非法或工单字段（worktree/workspace）越界 → 400。 */
  async function handleAgentLive(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    const url = new URL(req.url ?? '/', 'http://x')
    const n = Math.max(1, Math.min(200, Number.parseInt(url.searchParams.get('n') ?? '', 10) || 30))
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendJson(res, 404, { ok: false, error: `工单不存在或读取失败：${String(s?.error ?? id)}` })
        return
      }
      const t = s.result ?? {}
      const ref = await resolveSessionFile(repo, id, t)
      if (ref.refused === true) {
        sendJson(res, 400, { ok: false, error: ref.reason ?? '工单字段越界（拒绝读取）' })
        return
      }
      if (ref.path === undefined) {
        sendJson(res, 200, {
          ok: true,
          result: { exists: false, events: [], truncated: false, ws_root: ref.wsRoot ?? '', reason: ref.reason ?? '会话文件未定位' },
        })
        return
      }
      const result = await readAgentLiveTail(ref.path, n)
      sendJson(res, 200, { ok: true, result: { ...result, ws_root: ref.wsRoot ?? '' } })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** token 消耗聚合（t260828-07，只读）：show 工单 → 定全部会话文件（多角色加总）→
   *  按 timeline running 条目切阶段时间窗 → 整解聚合。与 agent-live 同一解析通路
   *  （decompressSession 复用）。降级契约同 handleAgentLive：无会话/无 usage →
   *  200 {exists:false,reason}；id 非法/字段越界 → 4xx 防穿。 */
  async function handleAgentUsage(res: ServerResponse, id: string): Promise<void> {
    if (!TICKET_ID_RE.test(id)) {
      sendJson(res, 400, { ok: false, error: '工单 id 不合法' })
      return
    }
    try {
      const s = await callTool('ticket', { op: 'show', id })
      if (s?.ok !== true) {
        sendJson(res, 404, { ok: false, error: `工单不存在或读取失败：${String(s?.error ?? id)}` })
        return
      }
      const t = s.result ?? {}
      const ref = await resolveAllSessionFiles(repo, id, t)
      if (ref.refused === true) {
        sendJson(res, 400, { ok: false, error: ref.reason ?? '工单字段越界（拒绝读取）' })
        return
      }
      if ((ref.paths ?? []).length === 0) {
        sendJson(res, 200, {
          ok: true,
          result: {
            exists: false, files: 0, total: { input: 0, output: 0, cacheRead: 0 },
            byStage: {}, models: [], ws_root: ref.wsRoot ?? '', reason: ref.reason ?? '会话文件未定位',
          },
        })
        return
      }
      const windows = stageWindowsFromTimeline(t.timeline)
      const result = await aggregateTicketUsage(ref.paths, windows)
      sendJson(res, 200, { ok: true, result: { ...result, ws_root: ref.wsRoot ?? '' } })
    } catch (err) {
      sendJson(res, 502, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 工单↔session 绑定：点工单→验存在→找/建 session，新建时附工单快照（client 作首条消息注入）。 */
  async function handleTicketSessionOpen(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let body: any
    try { body = await readJsonBody(req) } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    const ticketId = body?.ticket_id
    if (!ticketId || !TICKET_ID_RE.test(ticketId)) {
      sendJson(res, 400, { ok: false, error: 'ticket_id 不合法' })
      return
    }
    // 多项目化（260823）：project 必传（projects.yaml 注册表 key，无默认值）——
    // 会话工作区按该项目的注册目录判定。
    const projectKey = typeof body?.project === 'string' ? body.project : ''
    let proj: ProjectEntry | undefined
    try {
      proj = projectKey ? findProject(projectKey) : undefined
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    if (!proj) {
      sendJson(res, 400, { ok: false, error: projectKey ? `未知项目：${projectKey}（projects.yaml 未注册）` : '缺 project 字段（projects.yaml 注册表 key，无默认值）' })
      return
    }
    const primary = primaryDir(proj)
    // 存在性校验 + 快照素材：bogus id 不许建空 session（原路只验格式， bogus 也会建出孤儿会话）
    let tk: any
    try {
      const r = await callTool('ticket', { op: 'show', id: ticketId })
      tk = r?.result
    } catch { tk = null }
    if (!tk || tk.id !== ticketId) {
      sendJson(res, 404, { ok: false, error: `工单不存在：${ticketId}` })
      return
    }
    const sessionId = `ticket-${ticketId}`
    const sessions = ctx.get('sessions')
    if (!sessions) {
      sendJson(res, 500, { ok: false, error: 'sessions 服务不可用（headless 无此路由）' })
      return
    }
    // 工单快照→首条上下文消息：契约抽成模块级纯函数 ticketContext（t260831-08，
    // smoke 直测同口径；本处语义不变）
    // 检查 live store
    if (sessions.get(sessionId)) {
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: false } })
      return
    }
    // 工作区随工单走（用户拍板 260823）：泳道工单 cwd=泳道目录，主树工单 cwd=项目主目录。
    // 优先级同 workspaceInfoOf：workspace{type,path} > 旧 worktree 字段 > 主目录；
    // 相对路径对项目主目录解，绝对路径须落在该项目注册目录之一。
    const wsPath = (tk.workspace && typeof tk.workspace.path === 'string' && tk.workspace.path) || tk.worktree || ''
    let cwd = primary
    if (wsPath) {
      const abs = resolve(primary, wsPath)
      const inProject = proj.dirs.some(d => abs === d || abs.startsWith(d.replace(/\/+$/, '') + sep))
      if (inProject && existsSync(abs)) cwd = abs
      else ctx.logger.warn('suyou-workbench: 工单 %s 的工作区 %s 不在项目 %s 注册目录内或不存在，会话落主目录', ticketId, wsPath, proj.key)
    }
    try {
      sessions.create(sessionId, { meta: { cwd } })
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: true, cwd, context: ticketContext(tk) } })
    } catch (err: any) {
      const msg = String(err?.message ?? err)
      // 可能在持久层存在（上次进程创建的）：给 client open 自己加载
      if (msg.includes('already') || msg.includes('exist') || msg.includes('duplicate')) {
        sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: false } })
      } else {
        sendJson(res, 500, { ok: false, error: msg })
      }
    }
  }

  /**
   * 新建全局会话（session-entry t260825-02 建端点、t260828-02 口径调整，侧栏
   * 「会话」区新建按钮）。
   * 仿 handleTicketSessionOpen 的开/找形制，但语义边界三条：
   *   ① id 不带 ticket- 前缀（chat-<yyyymmdd-hhmmss>-<rand4>，可读有序防撞）；
   *   ② 不注入工单上下文（自由聊天，无首条快照消息）；
   *   ③ always-create 不 find（全局会话每次新建一个——连点会在服务端累积空会话
   *     尸体，但 t260828-02 起客户端列表数据源=插件记账层（只登记 UI 主动打开/
   *     新建的会话），存量不进列表，设计文档 §4 已授权此取舍，本期不做清理 UI）。
   * cwd 取该项目注册表主目录（「落在当前项目主目录」）。
   */
  async function handleGlobalSessionOpen(req: IncomingMessage, res: ServerResponse): Promise<void> {
    let body: any
    try { body = await readJsonBody(req) } catch (err) {
      sendJson(res, 400, { ok: false, error: `请求体不是合法 JSON：${String(err instanceof Error ? err.message : err)}` })
      return
    }
    // project 必传（projects.yaml 注册表 key，无默认值）——cwd 取该项目主目录。
    const projectKey = typeof body?.project === 'string' ? body.project : ''
    let proj: ProjectEntry | undefined
    try {
      proj = projectKey ? findProject(projectKey) : undefined
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
      return
    }
    if (!proj) {
      sendJson(res, 400, { ok: false, error: projectKey ? `未知项目：${projectKey}（projects.yaml 未注册）` : '缺 project 字段（projects.yaml 注册表 key，无默认值）' })
      return
    }
    const sessions = ctx.get('sessions')
    if (!sessions) {
      sendJson(res, 500, { ok: false, error: 'sessions 服务不可用（headless 无此路由）' })
      return
    }
    const cwd = primaryDir(proj)
    const d = new Date()
    const pad = (n: number): string => String(n).padStart(2, '0')
    const ts = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
    const sessionId = `chat-${ts}-${randomUUID().replace(/-/g, '').slice(0, 4)}`
    try {
      sessions.create(sessionId, { meta: { cwd } })
      ctx.logger.info('suyou-workbench: 新建全局会话 %s（项目 %s，cwd %s）', sessionId, proj.key, cwd)
      sendJson(res, 200, { ok: true, result: { session_id: sessionId, created: true, cwd } })
    } catch (err: any) {
      sendJson(res, 500, { ok: false, error: String(err?.message ?? err) })
    }
  }

  /** 项目注册表（projects.yaml）：侧栏分组数据源。project 是逻辑概念，1:N 对应目录。 */
  async function handleProjects(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const projects = loadProjects().map((p: ProjectEntry) => ({
        key: p.key,
        name: p.name,
        dirs: p.dirs,
        primary: primaryDir(p),
      }))
      sendJson(res, 200, { ok: true, result: { projects } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 工作区列表（项目切换器数据源）。 */
  async function handleWorkspaceList(_req: IncomingMessage, res: ServerResponse): Promise<void> {
    const wr = ctx.get('workspaceRegistry')
    if (!wr) {
      sendJson(res, 500, { ok: false, error: 'workspaceRegistry 不可用' })
      return
    }
    try {
      const list = wr.list()
      // repo 一并下发：工单台侧栏按它把「相对 worktree / 无 worktree」的工单归属到本仓库项目组。
      sendJson(res, 200, { ok: true, result: { repo, list: list.map((w: any) => {
        const ids = w.sessionIds
        return {
          id: w.id,
          title: w.title,
          path: w.path,
          sessionCount: typeof ids?.length === 'number' ? ids.length : 0,
        }
      }) } })
    } catch (err) {
      sendJson(res, 500, { ok: false, error: String(err instanceof Error ? err.message : err) })
    }
  }

  /** 把路由挂到 webServer（同一 effect，卸载随插件生命周期）。 */
  const attach = (ws: any): void => {
    ctx.effect(() => {
      const disposers = [
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/tickets', handler: handleTickets }),
        ws.register({ kind: 'prefix', path: TICKETS_PREFIX, handler: handleTicketRoute }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/workflows', handler: handleWorkflows }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/book', handler: handleBook }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/temporal-health', handler: handleTemporalHealth }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/workers', handler: handleWorkers }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/scan-report', handler: handleScanReport }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/build-info', handler: handleBuildInfo }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/metrics', handler: handleMetrics }),
        ws.register({ kind: 'exact', path: EPICS_PREFIX, handler: handleEpics }),
        ws.register({ kind: 'prefix', path: EPICS_PREFIX, handler: handleEpicRoute }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/workspaces', handler: handleWorkspaceList }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/wf/projects', handler: handleProjects }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/ticket-session/open', handler: handleTicketSessionOpen }),
        ws.register({ kind: 'exact', path: '/suyou-workbench/api/global-session/open', handler: handleGlobalSessionOpen }),
      ]
      return () => { for (const dispose of disposers) dispose() }
    }, 'suyou-workbench: wf api routes')
    ctx.logger.info('suyou-workbench: 工单工作流台 API 已挂载 /suyou-workbench/api/wf/*（repo=%s）', repo)
  }

  // webServer 可能先已提供（直接取），也可能后到（等 internal/service 事件）；
  // headless 永远等不到——待机即正确行为。
  const existing = ctx.get('webServer')
  if (existing !== undefined) {
    attach(existing)
    return
  }
  const dispose = ctx.on('internal/service', (serviceName: string, value: any) => {
    if (serviceName !== 'webServer') return
    dispose()
    attach(value)
  })
}
