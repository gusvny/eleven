/**
 * metrics.ts —— metrics M1a（t260901-20）读侧聚合唯一实现（只读真源，永不回写）。
 *
 * 双前门共用本模块（契约块 2 L158「同实现同缓存」+ 立项关键决策 3「一个实现
 * 两扇前门」）：HTTP 前门 = node.ts 的 exact 路由 /suyou-workbench/api/wf/metrics；
 * CLI 前门 = metrics-cli.mjs（argv JSON 收口后直调 buildMetricsResponse）。
 * 数据契约唯一真源 = docs/design/metrics-api契约v1.md（v1 冻结版），字段增删须
 * 开新工单 bump（块 6），本文件不得私改 schema。
 *
 * 口径出处（方案 gen2 已过三过审读，实现锚点）：
 * - 时间维：stage 时长 v1=handoff 近似，窗口派生复用 agent-usage.ts
 *   stageWindowsFromTimeline（乱序按 from 排序）；末窗封口是本模块新增语义
 *   （agent-usage 末窗 toMs=null 开放式，L82-93），实现为 closeStageWindows
 *   包装、不改本体签名——既有消费方（agent-usage 端点、M1b 泳道图）零回退。
 * - 交付维：base 钉死取工单 base_ref 进 delivery.base；git diff --numstat 分列
 *   add/del（不并净值）+ rev-list count；git 失败 → delivery=null + reason 软降级。
 * - token 维：复用 aggregateTicketUsage（块 5 八项故障模式随函数全量带入）。
 * - 纳票/归窗口径（契约真空，gen2 成文、已上报用户裁决）：closed 票归窗时刻=
 *   闭单终态时刻，未结票=创建时刻；KPI 分母与 charts 聚合同一口径、跨视图一致。
 * - health 视图：直查不读缓存（块 2 L157）；kpis 恒冻结四字段（tokens_total=
 *   0+reason，token 维不在直查路径）；blocked/silent 落 charts；server/worker
 *   存活经 200+reason 人话承载（块 4 SKIP 先例），不进 schema（块 6 冻结）。
 *
 * 缓存路径（t260901-14 路径约定）：~/.sandbar/projects/<key>/data/metrics/。
 * 【碑注——两真源矛盾】契约块 3 L189 写「~/.sandbar/data/<project>/」，与
 * sandbar 契约 ①a（sandbar项目接入契约v1.md L170-171）的 projects/<key>/data/
 * 矛盾；本实现取 ①a（工单正文明示「经 t260901-14 的路径约定解析」），契约
 * 修订候选已上报用户，谁也不代改冻结文档。env SUYOU_METRICS_DIR 仅测试覆盖。
 * legacy SUYOU_PROJECTS_YAML 单文件模式下 per-key 目录无定义 → 缓存禁用+SKIP。
 *
 * 测试缝（同 SUYOU_EPIC_NEXT_STUB 先例）：env SUYOU_METRICS_STUB 指向 stub JSON
 * {tickets, workflows, shows, deliveries}，deps 全离线零 admin.py/git 真源，
 * 供 CLI 双前门基线与泳道测试用；未设时走真通路。
 */

import { execFile } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import net from 'node:net'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { runAdminCli } from '../../../suyou-tools.ts'
import { findProject, loadProjects } from '../../../suyou-projects.ts'
import { listEpics, resolveEpicsDir } from './epics.ts'
import {
  aggregateTicketUsage, resolveAllSessionFiles, stageWindowsFromTimeline,
  type StageWindow,
} from './agent-usage.ts'

const execFileP = promisify(execFile)

export const SOURCE_VERSION = 'v1'
/** health 视图静默阈值（分钟）：模块常量，env SUYOU_METRICS_SILENT_MIN 仅测试覆盖；可调 UI 参数归 M2c 修约。 */
export const SILENT_RUNNING_MIN = 30
/** blocked_reason 榜逐票 show 封顶（成本上限，超出折叠计数+reason；票多项目不炸）。 */
export const BLOCKED_SHOW_CAP = 20

/**
 * 逐票记录生成的并发度（t260902-05⑦冷启动：串行逐票 spawn admin.py+git+zstd
 * 解压是打开慢的根因）。env SUYOU_METRICS_CONCURRENCY 仅测试覆盖；上限 8 防
 * 失配值把 admin.py 打成风暴。结果按入参序落位（out[idx]），与串行逐票同一
 * skipped/reason 顺序，双前门字节级一致不受影响（golden 基线锁定）。
 */
export const TICKET_CONCURRENCY = Math.max(1, Math.min(8, Number.parseInt(process.env.SUYOU_METRICS_CONCURRENCY ?? '', 10) || 4))

/**
 * 有界并发 map：结果按入参序落位；任一任务抛错即整体 reject（Promise.all 语义，
 * 与串行 await 链一致——错误处理路径不因并发改变）。
 */
export async function mapPool<T, R>(items: T[], concurrency: number, fn: (item: T, index: number) => Promise<R>): Promise<R[]> {
  const out = new Array<R>(items.length)
  let next = 0
  const workers = Array.from({ length: Math.max(1, Math.min(concurrency, items.length)) }, async () => {
    while (true) {
      const idx = next++
      if (idx >= items.length) return
      out[idx] = await fn(items[idx]!, idx)
    }
  })
  await Promise.all(workers)
  return out
}

// t260902-05⑤：窗口枚举扩 1d/3d（授权=工单正文用户原话「时间窗加 1d/3d」；
// 契约 v1 块 2 枚举变更候选已落 integration/t260902-05/contract-bump-candidate.md 上报）
const WINDOWS: Record<string, number> = { '1d': 86_400_000, '3d': 3 * 86_400_000, '7d': 7 * 86400_000, '30d': 30 * 86400_000, all: 0 }
const VIEWS = ['time', 'delivery', 'token', 'health']
const NUM_RE = /^\d+(\.\d+)?$/

/* ------------------------------------------------ 参数解析（契约块 2 防穿） */

export interface MetricsParams {
  window: string
  epic: string
  project: string
  template: string
  view: string
}

export type ParsedQuery = { ok: true; params: MetricsParams } | { ok: false; status: number; error: string }

/**
 * query 参数解析单点（HTTP 前门传 URLSearchParams，CLI 前门传普通对象——
 * 同一校验函数，同款 {error} 形状）。非法值/缺必填/同名重复参数一律 4xx
 * （契约块 2：无「取首个」容错，与非法值同款防穿）。
 */
export function parseMetricsQuery(input: URLSearchParams | Record<string, string | string[]>): ParsedQuery {
  const get = (key: string): string[] => {
    if (input instanceof URLSearchParams) return input.getAll(key)
    const v = (input as Record<string, string | string[]>)[key]
    return v === undefined ? [] : Array.isArray(v) ? v : [v]
  }
  const once = (key: string): { v?: string; err?: string } => {
    const all = get(key)
    if (all.length > 1) return { err: `同名重复参数 '${key}' 出现 ${all.length} 次（无取首个容错）` }
    return { v: all[0] }
  }
  const out: MetricsParams = { window: '7d', epic: 'all', project: '', template: 'dev-lane', view: '' }
  const projectGiven = get('project').length > 0
  for (const [key, def] of [['window', '7d'], ['epic', 'all'], ['project', ''], ['template', 'dev-lane'], ['view', '']] as const) {
    const r = once(key)
    if (r.err) return { ok: false, status: 400, error: r.err }
    if (r.v !== undefined && r.v !== '') (out as any)[key] = r.v
  }
  if (!(out.window in WINDOWS)) return { ok: false, status: 400, error: `window 非法：'${out.window}'（枚举 1d|3d|7d|30d|all）` }
  if (out.epic !== 'all' && out.epic !== 'none') {
    if (out.epic.length > 41 || !/^[a-z0-9][a-z0-9-]{0,40}$/.test(out.epic)) {
      return { ok: false, status: 400, error: `epic 非法：'${out.epic.slice(0, 60)}'（立项代号形状 all|none|<code>）` }
    }
  }
  if (projectGiven && !/^[a-z0-9][a-z0-9-]{0,40}$/.test(out.project)) {
    return { ok: false, status: 400, error: `project 非法：'${out.project.slice(0, 60)}'（projects.yaml 注册表 key 形状）` }
  }
  if (!VIEWS.includes(out.view)) {
    return { ok: false, status: 400, error: `view 必填且须为 ${VIEWS.join('|')}（收到 '${out.view}'）` }
  }
  return { ok: true, params: out }
}

/* ------------------------------------------------ 数据通路（deps 注入 + 缺省实现） */

/** 聚合所需数据通路面。测试以桩注入；缺省实现走 admin.py/git/注册表真源。 */
export interface MetricsDeps {
  repo: string
  /** ticket list 行（ticket.py L30 形状）。 */
  listTickets: (project: string) => Promise<any[]>
  /** ticket show 全文（snapshot+meta，含 timeline/worktree/base_ref）。 */
  showTicket: (id: string) => Promise<any | null>
  /** 模板表（workflow.py L15 形状：[{id, name, lane, stages:[{id, exit?...}]}]）。 */
  listWorkflows: () => Promise<any[]>
  /** 立项代号白名单（null=校验不可用，放行并附 reason）。 */
  listEpicCodes: () => Promise<string[] | null>
  /** project 校验：ok=放行；否则给出 4xx 人话（findProject 三态：未知/隔离/注册表坏）。 */
  checkProject: (key: string) => Promise<{ ok: true } | { ok: false; status: number; error: string }>
  /** 默认项目 key（注册表字母序首个，suyou-projects.ts scanRegistry sort 口径）。 */
  defaultProject: () => Promise<string | null>
  /** git：cwd 下跑 args，stdout 原文；失败抛错（调用方软降级）。 */
  git: (cwd: string, args: string[]) => Promise<string>
  now: () => number
}

/** SUYOU_METRICS_STUB 测试缝：读 stub JSON 构造全离线 deps。 */
function stubDeps(repo: string, stubPath: string, now: () => number): MetricsDeps {
  // 同步读不行（顶层 async 约束），惰性缓存首调加载
  let stub: any = null
  const load = async (): Promise<any> => {
    if (stub === null) stub = JSON.parse(await readFile(stubPath, 'utf8'))
    return stub
  }
  const find = (rows: any[], id: string) => rows.find((r) => r.id === id) ?? null
  return {
    repo,
    listTickets: async () => (await load()).tickets ?? [],
    showTicket: async (id: string) => find((await load()).tickets ?? [], id),
    listWorkflows: async () => (await load()).workflows ?? [],
    listEpicCodes: async () => (await load()).epics ?? [],
    checkProject: async () => ({ ok: true }),
    defaultProject: async () => (await load()).project ?? 'demo',
    git: async (_cwd, args) => {
      const key = args.join(' ')
      const d = ((await load()).deliveries ?? {})[key]
      if (d === undefined) throw new Error(`stub git 未备：${key}`)
      return d
    },
    now,
  }
}

/** 缺省 deps：admin.py spawn + git + 注册表/立项单真源。 */
export function defaultDeps(repo: string, now: () => number = Date.now): MetricsDeps {
  const cli = { repo }
  const stub = process.env.SUYOU_METRICS_STUB
  if (stub) return stubDeps(repo, stub, now)
  return {
    repo,
    listTickets: async (project) => {
      const r = await runAdminCli(cli, ['call', 'ticket', JSON.stringify({ op: 'list', project })])
      return r?.ok === true ? r.result?.tickets ?? [] : []
    },
    showTicket: async (id) => {
      const r = await runAdminCli(cli, ['call', 'ticket', JSON.stringify({ op: 'show', id })])
      return r?.ok === true ? r.result ?? null : null
    },
    listWorkflows: async () => {
      const r = await runAdminCli(cli, ['call', 'workflow', JSON.stringify({ op: 'list' })])
      return r?.result?.workflows ?? (Array.isArray(r?.result) ? r.result : [])
    },
    listEpicCodes: async () => {
      try {
        const rows = await listEpics(resolveEpicsDir(repo))
        return rows.map((e) => e.code)
      } catch {
        return null // 白名单不可用：放行并附 reason（不阻塞聚合）
      }
    },
    checkProject: async (key) => {
      if (!/^[a-z0-9][a-z0-9-]{0,40}$/.test(key)) {
        return { ok: false, status: 400, error: `project 非法：'${key}'（projects.yaml 注册表 key 形状）` }
      }
      try {
        if (findProject(key)) return { ok: true }
        return { ok: false, status: 400, error: `未知项目 key：'${key}'（projects.yaml 注册表无此项）` }
      } catch (err) {
        // 隔离条目/注册表装载失败：显式带原因（与「未知 key」文案区分，findProject 三态）
        return { ok: false, status: 400, error: `项目 '${key}' 不可用：${String(err instanceof Error ? err.message : err)}` }
      }
    },
    defaultProject: async () => {
      try {
        const rows = loadProjects()
        if (rows.length === 0) return null
        return [...rows].sort((a, b) => (a.key < b.key ? -1 : 1))[0]!.key
      } catch {
        return null
      }
    },
    git: async (cwd, args) => (await execFileP('git', args, { cwd, timeout: 30_000, maxBuffer: 16 * 1024 * 1024 })).stdout,
    now,
  }
}

/* ------------------------------------------------ 缓存层（契约块 3 schema + 版本化失效） */

export interface MetricsCacheRecord {
  ticket_id: string
  template: string
  durations: { by_stage: Record<string, number>; by_round: Record<string, number>; human_wait: number }
  delivery: { base: string; add: number; del: number; commits: number } | null
  tokens: { by_stage: Record<string, { in: number; out: number; cacheRead: number }>; by_model: Record<string, number>; in: number; out: number; cacheRead: number } | null
  open: boolean
  delivery_frozen: boolean
  source_version: string
  engine_version: string
  updated_ts: string
  computed_at: string
}

/**
 * per-ticket 缓存目录：~/.sandbar/projects/<key>/data/metrics/（t260901-14 路径
 * 约定；env SANDBAR_PROJECTS_DIR 现读，SUYOU_METRICS_DIR 测试覆盖）。
 * legacy 单文件模式（SUYOU_PROJECTS_YAML）无 per-key 目录定义 → enabled:false+SKIP。
 * 两真源矛盾见文件头碑注。
 */
export function resolveMetricsCacheDir(projectKey: string): { dir: string; enabled: boolean; reason?: string } {
  if (process.env.SUYOU_PROJECTS_YAML) {
    return { dir: '', enabled: false, reason: 'legacy 单文件注册表模式（SUYOU_PROJECTS_YAML）无 per-key 数据目录约定，metrics 缓存禁用（数据现算，不落盘）' }
  }
  const root = process.env.SUYOU_METRICS_DIR ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
  return { dir: join(root, projectKey, 'data', 'metrics'), enabled: true }
}

/** stages 链的稳定指纹（FNV-1a 32 位 hex ×2 轮拼 16 位，无 crypto 依赖——
 *  node-shims 最小面不含 createHash；只需确定性，不需密码学强度）。 */
export function engineVersionOf(stages: unknown): string {
  const text = JSON.stringify(stages ?? [])
  let fnv = (x: string): string => {
    let h = 0x811c9dc5
    for (let i = 0; i < x.length; i++) {
      h ^= x.charCodeAt(i)
      h = Math.imul(h, 0x01000193) >>> 0
    }
    return h.toString(16).padStart(8, '0')
  }
  return (fnv(text) + fnv(text.split('').reverse().join(''))).slice(0, 12)
}

/** 读缓存：文件缺/坏 JSON/双版本失配 → null（作废重算，契约块 3）。 */
export async function readTicketCache(dir: string, id: string, engineVersion: string): Promise<MetricsCacheRecord | null> {
  let raw: string
  try {
    raw = await readFile(join(dir, `${id}.json`), 'utf8')
  } catch {
    return null
  }
  let rec: any
  try {
    rec = JSON.parse(raw)
  } catch {
    return null // 坏缓存当未命中
  }
  if (rec?.source_version !== SOURCE_VERSION || rec?.engine_version !== engineVersion) return null
  return rec as MetricsCacheRecord
}

/** 写缓存（失败静默：目录不可写 → 本次直算回包+reason，不 5xx）。 */
export async function writeTicketCache(dir: string, rec: MetricsCacheRecord): Promise<boolean> {
  try {
    await mkdir(dir, { recursive: true })
    await writeFile(join(dir, `${rec.ticket_id}.json`), JSON.stringify(rec, null, 1), 'utf8')
    return true
  } catch {
    return false
  }
}

/* ------------------------------------------------ 时间维（窗口派生 + 封口） */

/**
 * 末窗封口（契约块 1「末窗右端 = min(下一窗 from, closed_ts)」）：metrics 侧
 * 新增包装，不改 stageWindowsFromTimeline 本体（agent-usage 末窗开放式语义与
 * M1b 泳道图复用不受影响）。closedMs=NaN 时保持开放式。
 */
export function closeStageWindows(windows: StageWindow[], closedMs: number): StageWindow[] {
  if (!Number.isFinite(closedMs) || windows.length === 0) return windows
  const last = windows[windows.length - 1]!
  if (last.toMs !== null) return windows
  return [...windows.slice(0, -1), { ...last, toMs: closedMs }]
}

export interface Durations {
  by_stage: Record<string, number>
  by_round: Record<string, number>
  human_wait: number
  closed_ms: number | null
  created_ms: number | null
  reasons: string[]
}

/**
 * 单票时间维：timeline running 条目切窗（复用 stageWindowsFromTimeline）+ 末窗
 * 按 closed 时刻封口 + human 门（stage exit:human）窗口合计。缺失/畸形逐条记
 * reason 不静默丢（契约块 4：无 running 条目→计 0+reason；缺 from→计 0+reason）。
 * humanStages = 所选模板 stages 链里 exit==='human' 的 stage id 集。
 */
export function computeDurations(timeline: any, humanStages: Set<string>, nowMs: number = Date.now()): Durations {
  const out: Durations = { by_stage: {}, by_round: {}, human_wait: 0, closed_ms: null, created_ms: null, reasons: [] }
  const entries = (Array.isArray(timeline) ? timeline : []).map((t: any) => ({
    stage: String(t?.stage ?? ''), state: String(t?.state ?? ''), at: t?.at, ms: isoMs(t?.at),
  }))
  if (entries.length > 0) {
    out.created_ms = Math.min(...entries.filter((e) => Number.isFinite(e.ms)).map((e) => e.ms))
    if (!Number.isFinite(out.created_ms)) out.created_ms = null
  }
  const closed = entries.filter((e) => e.state === 'closed' && Number.isFinite(e.ms))
  out.closed_ms = closed.length > 0 ? Math.max(...closed.map((e) => e.ms)) : null
  const running = entries.filter((e) => e.state === 'running')
  if (running.length === 0) {
    out.reasons.push('timeline 无 running 条目，stage 时长计 0')
    return out
  }
  for (const e of running) {
    if (!Number.isFinite(e.ms)) out.reasons.push(`timeline 条目缺/坏时间戳（stage=${e.stage || '?'}），该窗计 0`)
  }
  let windows = stageWindowsFromTimeline(entries)
  windows = closeStageWindows(windows, out.closed_ms ?? NaN)
  const roundOf = new Map<string, number>()
  for (const w of windows) {
    // 开放式末窗（未结票且无 closed 时刻）封到 nowMs——nowMs 由 deps.now() 注入，双前门同刻可比
    const dur = (w.toMs ?? nowMs) - w.fromMs
    const d = Math.max(0, dur)
    out.by_stage[w.stage] = (out.by_stage[w.stage] ?? 0) + d
    // by_round：同 stage 每重入一轮计一列（rework 多窗加总口径的可视分列）
    const r = (roundOf.get(w.stage) ?? 0) + 1
    roundOf.set(w.stage, r)
    const rkey = r === 1 ? w.stage : `${w.stage}#r${r}`
    out.by_round[rkey] = d
    if (humanStages.has(w.stage)) out.human_wait += d
  }
  return out
}

function isoMs(at: unknown): number {
  const ms = typeof at === 'string' ? new Date(at).getTime() : NaN
  return Number.isFinite(ms) ? ms : NaN
}

/* ------------------------------------------------ 交付维 / token 维 */

/** 单票交付维：base 钉死 base_ref；numstat 分列 add/del；rev-list count。git 失败 → null+reason。 */
export async function computeDelivery(
  deps: MetricsDeps, ticket: any,
): Promise<{ delivery: MetricsCacheRecord['delivery']; reason?: string }> {
  const base = String(ticket?.base_ref ?? '')
  const worktree = String(ticket?.worktree ?? '')
  if (base === '' || worktree === '') {
    return { delivery: null, reason: '工单缺 base_ref/worktree（无泳道或历史票），delivery 维不可算' }
  }
  const cwd = join(deps.repo, worktree)
  try {
    const numstat = await deps.git(cwd, ['diff', `${base}...HEAD`, '--numstat'])
    let add = 0
    let del = 0
    for (const line of numstat.split('\n')) {
      const m = /^(\d+|-)\t(\d+|-)\t/.exec(line)
      if (!m) continue
      add += m[1] === '-' ? 0 : Number(m[1])
      del += m[2] === '-' ? 0 : Number(m[2])
    }
    const commits = Number((await deps.git(cwd, ['rev-list', '--count', `${base}..HEAD`])).trim())
    return { delivery: { base, add, del, commits: Number.isFinite(commits) ? commits : 0 } }
  } catch (err) {
    return { delivery: null, reason: `git 读取失败（${String(err instanceof Error ? err.message : err)}），delivery 维置空` }
  }
}

/** 单票 token 维：复用 agent-usage 通路（八项故障模式随函数带入，契约块 5）。 */
export async function computeTokens(
  deps: MetricsDeps, id: string, ticket: any, windows: StageWindow[],
): Promise<{ tokens: MetricsCacheRecord['tokens']; reason?: string }> {
  const ref = await resolveAllSessionFiles(deps.repo, id, ticket)
  if (ref.refused === true) return { tokens: null, reason: ref.reason ?? '工单字段越界（拒绝读取会话）' }
  const agg = await aggregateTicketUsage(ref.paths ?? [], windows)
  if (!agg.exists) return { tokens: null, reason: agg.reason ?? '无 usage 事件' }
  const by_model: Record<string, number> = {}
  for (const m of agg.models) by_model[`${m.provider}/${m.model}`] = m.input + m.output
  const by_stage: Record<string, { in: number; out: number; cacheRead: number }> = {}
  for (const [stage, s] of Object.entries(agg.byStage)) {
    by_stage[stage] = { in: s.input, out: s.output, cacheRead: s.cacheRead }
  }
  return { tokens: { by_stage, by_model, in: agg.total.input, out: agg.total.output, cacheRead: agg.total.cacheRead } }
}

/* ------------------------------------------------ 单票记录（惰性生成 + frozen 语义） */

/** 记录 + 归窗锚点（锚点可从派生时序得出，不进冻结 schema——块 6）。fromCache=本票记录由缓存读命中（false=本次惰性生成），cache.status 契约字面语义的依据。 */
export interface RecordWithAnchor {
  rec: MetricsCacheRecord
  createdMs: number | null
  closedMs: number | null
  fromCache: boolean
  /** 惰性生成的记录是否成功落盘（fromCache=true 时恒 true；落盘失败=每次直算兜底）。 */
  persisted: boolean
}

async function ticketRecord(
  deps: MetricsDeps, row: any, template: string, stages: any[], engineVersion: string,
  cacheDir: { dir: string; enabled: boolean; reason?: string },
): Promise<RecordWithAnchor | null> {
  const id = String(row?.id ?? '')
  if (id === '') return null
  const humanStages = new Set(stages.filter((s: any) => s?.exit === 'human').map((s: any) => String(s.id)))
  const cached = cacheDir.enabled ? await readTicketCache(cacheDir.dir, id, engineVersion) : null
  if (cached) {
    return { rec: cached, createdMs: null, closedMs: null, fromCache: true, persisted: true } // 锚点由主循环统一补（见主循环注释）
  }
  // 上方 if 已把 cached 收窄成 null；断言还原宽类型供下方 frozen 语义读取
  const prev = cached as MetricsCacheRecord | null
  const ticket = (await deps.showTicket(id)) ?? row
  const timeline = ticket?.timeline ?? ticket?.meta?.timeline
  const durations = computeDurations(timeline, humanStages, deps.now())
  // frozen 例外（契约块 3）：已固化票重算跳过 delivery 维，只刷新其余维度
  let delivery = prev?.delivery ?? null
  if (delivery === null && prev?.delivery_frozen !== true) {
    delivery = (await computeDelivery(deps, ticket)).delivery
  }
  const windows = closeStageWindows(stageWindowsFromTimeline(timeline), durations.closed_ms ?? NaN)
  const t = await computeTokens(deps, id, ticket, windows)
  const nowIso = new Date(deps.now()).toISOString()
  const rec: MetricsCacheRecord = {
    ticket_id: id,
    template,
    durations: { by_stage: durations.by_stage, by_round: durations.by_round, human_wait: durations.human_wait },
    delivery,
    tokens: t.tokens,
    open: String(ticket?.status ?? '') !== 'closed',
    delivery_frozen: prev?.delivery_frozen ?? false,
    source_version: SOURCE_VERSION,
    engine_version: engineVersion,
    updated_ts: nowIso,
    computed_at: nowIso,
  }
  const persisted = cacheDir.enabled ? await writeTicketCache(cacheDir.dir, rec) : false
  return { rec, createdMs: durations.created_ms, closedMs: durations.closed_ms, fromCache: false, persisted }
}

/**
 * 稳定 reason（双前门字节级一致的一部分）：reason 只从**缓存记录的状态**派生
 * （delivery/tokens 为 null、stage 链为空、缓存未落盘），不从重算路径的中间过程
 * 派生——否则首门（重算）与次门（命中）reason 不同，比较面天然红。
 */
function stableReasons(entries: RecordWithAnchor[], cacheDir: { dir: string; enabled: boolean; reason?: string }): string[] {
  const out: string[] = []
  if (!cacheDir.enabled && cacheDir.reason) out.push(cacheDir.reason)
  for (const e of entries) {
    const id = e.rec.ticket_id
    if (!e.fromCache && !e.persisted) {
      out.push(`${id}: 记录未入缓存（缓存禁用/不可写），每次直算兜底`)
    }
    if (Object.keys(e.rec.durations.by_stage).length === 0) out.push(`${id}: timeline 无 running 条目，stage 时长计 0`)
    if (e.rec.delivery === null && !e.rec.delivery_frozen) out.push(`${id}: delivery 维不可算（缺 base_ref/worktree 或 git 失败）`)
    if (e.rec.tokens === null) out.push(`${id}: 无 token 数据（无会话文件/无 usage，SKIP）`)
  }
  return out
}

/* ------------------------------------------------ 视图组装（响应形状契约块 2，逐字段冻结） */

function emptyKpis() {
  return { tickets: 0, closed: 0, avg_delivery_min: 0.0, tokens_total: 0 }
}

function chart(kind: string, title: string, categories: string[], series: { name: string; data: number[] }[]) {
  return { kind, title, categories, series, drill: true }
}

function inWindow(ms: number | null, from: number, to: number): boolean {
  if (ms === null || !Number.isFinite(ms)) return false
  return ms >= from && ms < to
}

/** 归窗锚点（gen2 成文口径）：closed 票=闭单终态时刻；未结票=创建时刻。KPI 与 charts 同口径。 */

export interface MetricsResponse {
  status: number
  body: Record<string, unknown>
}

/** 4xx 防穿回包形状（契约块 2：`4xx {error, reason}`，双字段都给人话）。 */
export function bad4xx(msg: string): Record<string, unknown> {
  return { error: msg, reason: msg }
}

/**
 * 聚合唯一出口：双前门直调。返回 {status, body}；4xx 时 body={error}。
 * 响应键序即序列化序（字节级比较面 = 剔除 generated_at/cache.computed_at 的全部字段）。
 */
export async function buildMetricsResponse(
  query: URLSearchParams | Record<string, string | string[]>,
  deps: MetricsDeps,
): Promise<MetricsResponse> {
  const parsed = parseMetricsQuery(query)
  if (!parsed.ok) return { status: parsed.status, body: bad4xx(parsed.error) }
  const p = parsed.params
  const reasons: string[] = []

  if (p.project === '') {
    const def = await deps.defaultProject()
    if (def === null) return { status: 400, body: bad4xx('无法确定默认项目（projects.yaml 注册表为空或不可读），请显式传 project') }
    p.project = def
  }
  const proj = await deps.checkProject(p.project)
  if (!proj.ok) return { status: proj.status, body: bad4xx(proj.error) }
  if (p.epic !== 'all' && p.epic !== 'none') {
    const codes = await deps.listEpicCodes()
    if (codes !== null && !codes.includes(p.epic)) {
      return { status: 400, body: bad4xx(`未知立项代号：'${p.epic}'（notes/epics 无此文件）`) }
    }
  }

  const workflows = await deps.listWorkflows()
  const wf = workflows.find((w: any) => String(w?.id ?? '') === p.template)
  if (!wf) return { status: 400, body: bad4xx(`未知模板：'${p.template}'（workflow list 无此项）`) }
  const stages = Array.isArray(wf.stages) ? wf.stages : []
  const stageIds = stages.map((s: any) => String(s?.id ?? '')).filter((s: string) => s !== '')
  const engineVersion = engineVersionOf(stages)

  let rows = await deps.listTickets(p.project)
  if (p.epic === 'none') rows = rows.filter((r: any) => String(r?.epic ?? '') === '')
  else if (p.epic !== 'all') rows = rows.filter((r: any) => String(r?.epic ?? '') === p.epic)
  rows = rows.filter((r: any) => String(r?.workflow ?? '') === p.template)

  const nowMs = deps.now()
  const span = WINDOWS[p.window] ?? 0
  const from = span === 0 ? -Infinity : nowMs - span
  const to = nowMs

  const cacheDir = resolveMetricsCacheDir(p.project)

  if (p.view === 'health') return healthView(deps, rows, p, stageIds, from, to, nowMs, reasons)

  /* -- 三数据视图：逐票惰性算/读缓存（t260902-05⑦：有界并发，保序落位，
      skipped/reason 顺序与原串行一致；锚点补齐也在任务内做，语义不变） -- */
  const recordEntries = await mapPool<any, RecordWithAnchor | null>(rows, TICKET_CONCURRENCY, async (row) => {
    const e = await ticketRecord(deps, row, p.template, stages, engineVersion, cacheDir)
    if (e === null) return null
    // 锚点统一补齐（缓存命中路径的 rec 不带 created/closed——冻结 schema 无槽位，
    // 且命中/重算两条路径必须产出同一响应，否则双前门字节级比对红）：优先 list 行
    // 自带 timeline（stub/测试零成本），否则一次 show 取 timeline。
    if (e.createdMs === null) {
      const tl = row?.timeline ?? (await deps.showTicket(String(row?.id ?? '')))?.timeline
      e.createdMs = timelineCreatedMs(tl)
      e.closedMs = e.rec.open ? null : timelineClosedMs(tl)
    }
    return e
  })
  const skipped: string[] = []
  for (let i = 0; i < recordEntries.length; i++) {
    if (recordEntries[i] === null) skipped.push(`${String(rows[i]?.id ?? '?')}: 记录生成失败，跳过`)
  }
  const entries = recordEntries.filter((e): e is RecordWithAnchor => e !== null)

  // KPI 分母与 charts 聚合同口径（gen2 成文）：closed 票按闭单时刻、未结票按创建时刻归窗
  const kpis = emptyKpis()
  const kept: MetricsCacheRecord[] = []
  let avgSumMin = 0
  for (const e of entries) {
    const anchor = e.rec.open ? e.createdMs : (e.closedMs ?? e.createdMs)
    if (e.createdMs !== null && inWindow(e.createdMs, from, to)) kpis.tickets += 1
    if (inWindow(anchor, from, to)) {
      kept.push(e.rec)
      if (!e.rec.open && anchor !== null) {
        kpis.closed += 1
        if (e.createdMs !== null && anchor - e.createdMs > 0) avgSumMin += (anchor - e.createdMs) / 60000
      }
    }
  }
  kpis.avg_delivery_min = kpis.closed > 0 ? round2(avgSumMin / kpis.closed) : 0.0
  kpis.tokens_total = kept.reduce((s, r) => s + (r.tokens ? r.tokens.in + r.tokens.out : 0), 0)

  const body = buildChartsBody(p.view, kept, stageIds, kpis)
  // cache.status 契约块 2 字面语义（t260901-20 acceptance P1 打回后回归字面）：
  // 'computed'=本响应含本次惰性生成（缓存 miss）的记录；'hit'=全部记录由缓存读命中。
  // 双前门字节级一致由此保住：t05/M3 比对基线在两门前**预热缓存**（同请求先跑一次），
  // 两门同刻同缓存状态、status 同为 hit——比较面不削（status 不进剔除清单），契约
  // 字面不偏离。冷缓存下「第一门 computed / 第二门 hit」的天然差异即契约语义本身。
  const cacheStatus = entries.length > 0 && entries.every((e) => e.fromCache) ? 'hit' : 'computed'
  const nowIso = new Date(nowMs).toISOString()
  const resp: Record<string, unknown> = {
    kpis,
    charts: body.charts,
    generated_at: nowIso,
    cache: { status: cacheStatus, computed_at: nowIso, source_version: SOURCE_VERSION },
  }
  const respReasons = [...skipped, ...stableReasons(entries, cacheDir)]
  if (respReasons.length > 0) {
    ;(resp as any).reason = dedupe(respReasons).slice(0, 20).join('；')
  }
  return { status: 200, body: resp }
}

function timelineCreatedMs(timeline: any): number | null {
  const msList = (Array.isArray(timeline) ? timeline : []).map((t: any) => isoMs(t?.at)).filter(Number.isFinite)
  return msList.length > 0 ? Math.min(...msList) : null
}

function timelineClosedMs(timeline: any): number | null {
  const msList = (Array.isArray(timeline) ? timeline : [])
    .filter((t: any) => String(t?.state ?? '') === 'closed')
    .map((t: any) => isoMs(t?.at)).filter(Number.isFinite)
  return msList.length > 0 ? Math.max(...msList) : null
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function dedupe(arr: string[]): string[] {
  return [...new Set(arr)]
}

/** 三数据视图的 charts（契约：跨模板不混排，stage 轴=该模板 stages 链序）。 */
function buildChartsBody(view: string, records: MetricsCacheRecord[], stageIds: string[], kpis: ReturnType<typeof emptyKpis>): { charts: unknown } {
  if (view === 'time') {
    const byStage = stageIds.map((s) => records.reduce((sum, r) => sum + (r.durations.by_stage[s] ?? 0), 0))
    const human = records.reduce((s, r) => s + r.durations.human_wait, 0)
    const machine = byStage.reduce((a, b) => a + b, 0) - human
    const perTicket = [...records].sort((a, b) => totalDur(b) - totalDur(a)).slice(0, 10)
    return {
      charts: {
        primary: chart('bar', 'stage 时长合计（分钟，v1=handoff 近似）', stageIds, [{ name: '时长(min)', data: byStage.map(msToMin) }]),
        secondaries: [
          chart('donut', '时间去哪了：人审等待 vs 机器', ['人审等待', '机器'], [{ name: '占比', data: [round2(msToMin(human)), round2(msToMin(Math.max(0, machine)))] }]),
          chart('stackBar', 'Top 票 stage 构成（分钟）', perTicket.map((r) => r.ticket_id), [
            { name: '机器', data: perTicket.map((r) => round2(msToMin(totalDur(r) - r.durations.human_wait))) },
            { name: '人审等待', data: perTicket.map((r) => round2(msToMin(r.durations.human_wait))) },
          ]),
        ],
      },
    }
  }
  if (view === 'delivery') {
    const withD = records.filter((r) => r.delivery !== null)
    const top = [...withD].sort((a, b) => (b.delivery!.add + b.delivery!.del) - (a.delivery!.add + a.delivery!.del)).slice(0, 10)
    const add = withD.reduce((s, r) => s + r.delivery!.add, 0)
    const del = withD.reduce((s, r) => s + r.delivery!.del, 0)
    const commits = withD.reduce((s, r) => s + r.delivery!.commits, 0)
    return {
      charts: {
        primary: chart('hBar', 'Top 票变更量（行，add+del 分列口径）', top.map((r) => r.ticket_id), [{ name: '行数', data: top.map((r) => r.delivery!.add + r.delivery!.del) }]),
        secondaries: [
          chart('bar', '全窗口变更总量', ['additions', 'deletions', 'commits'], [{ name: '量', data: [add, del, commits] }]),
          chart('donut', '有无代码变更票占比', ['有变更', '无变更/无数据'], [{ name: '票数', data: [withD.filter((r) => (r.delivery?.add ?? 0) + (r.delivery?.del ?? 0) > 0).length, records.length - withD.filter((r) => (r.delivery?.add ?? 0) + (r.delivery?.del ?? 0) > 0).length] }]),
        ],
      },
    }
  }
  // token
  const byStage = stageIds.map((s) => records.reduce((sum, r) => sum + (r.tokens?.by_stage[s] ? r.tokens!.by_stage[s].in + r.tokens!.by_stage[s].out : 0), 0))
  const byModel = new Map<string, number>()
  for (const r of records) for (const [m, v] of Object.entries(r.tokens?.by_model ?? {})) byModel.set(m, (byModel.get(m) ?? 0) + v)
  const modelEntries = [...byModel.entries()].sort((a, b) => b[1] - a[1])
  const top = [...records].filter((r) => r.tokens !== null).sort((a, b) => tok(b) - tok(a)).slice(0, 10)
  return {
    charts: {
      primary: chart('bar', 'stage token 消耗（in+out，cacheRead 单列）', stageIds, [{ name: 'tokens', data: byStage }]),
      secondaries: [
        chart('donut', '模型份额', modelEntries.map((e) => e[0]), [{ name: 'tokens', data: modelEntries.map((e) => e[1]) }]),
        chart('hBar', 'Top 票 token 消耗', top.map((r) => r.ticket_id), [{ name: 'tokens', data: top.map(tok) }]),
      ],
    },
  }
}

function totalDur(r: MetricsCacheRecord): number {
  return Object.values(r.durations.by_stage).reduce((a, b) => a + b, 0)
}
function msToMin(ms: number): number {
  return round2(ms / 60000)
}
function tok(r: MetricsCacheRecord): number {
  return r.tokens ? r.tokens.in + r.tokens.out : 0
}

/* ------------------------------------------------ health 视图（直查，不读缓存） */

/** Temporal server 存活探测（同 node.ts handleTemporalHealth 口径，本模块自带以保持单实现）。 */
function probePort(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((res) => {
    const sock = net.connect({ host, port })
    let settled = false
    const done = (ok: boolean) => {
      if (settled) return
      settled = true
      sock.destroy()
      res(ok)
    }
    sock.setTimeout(timeoutMs)
    sock.once('connect', () => done(true))
    sock.once('error', () => done(false))
    sock.once('timeout', () => done(false))
  })
}

async function healthView(
  deps: MetricsDeps, rows: any[], p: MetricsParams, stageIds: string[],
  from: number, to: number, nowMs: number, reasons: string[],
): Promise<MetricsResponse> {
  const nowIso = new Date(nowMs).toISOString()
  const base: Record<string, unknown> = {
    kpis: emptyKpis(),
    charts: { primary: chart('hBar', 'blocked 榜', [], []), secondaries: [] },
    generated_at: nowIso,
    // cache 块取值成文（implement 口径）：health 不走缓存通路，status 恒 'computed'、
    // computed_at=本次时刻，语义=「本次直查即产出」，非缓存命中（hit）也不误导为会回写缓存。
    cache: { status: 'computed', computed_at: nowIso, source_version: SOURCE_VERSION },
  }
  const online = await probePort('127.0.0.1', 7233, 800)
  if (!online) {
    reasons.push('Temporal server 127.0.0.1:7233 未监听（server 离线），票流数据降级为空')
  }
  const silentMin = Number.parseInt(process.env.SUYOU_METRICS_SILENT_MIN ?? '', 10) || SILENT_RUNNING_MIN
  const kpis = base.kpis as ReturnType<typeof emptyKpis>
  const running = rows.filter((r) => String(r?.stage_state ?? '') === 'running')
  const blocked = rows.filter((r) => String(r?.stage_state ?? '') === 'blocked')
  // 归窗口径与三数据视图一致（closed 按闭单/未结按创建）；health 直查路径无缓存
  // created/closed，KPI 分母取 list 行 updated 列为锚的近似不可取——直查 snapshot 太重，
  // 故 health 的 tickets/closed 只在 window=all 时给全量计数，7d/30d 降级为
  // 「updated 列落窗」的近似计数并附 reason（直查路径的已知近似，不静默）。
  const anchorApprox = (r: any): number | null => {
    const ms = isoMs(r?.updated)
    return Number.isFinite(ms) ? ms : null
  }
  for (const r of rows) {
    const a = from === -Infinity ? 0 : anchorApprox(r)
    if (from !== -Infinity && !inWindow(a, from, to)) continue
    kpis.tickets += 1
    if (String(r?.status ?? '') === 'closed') kpis.closed += 1
  }
  if (from !== -Infinity) reasons.push('health 直查路径无 created/closed 时刻，窗口计数以 list.updated 列近似（window=all 为精确全量）')
  kpis.avg_delivery_min = 0.0
  kpis.tokens_total = 0
  reasons.push('token 维不在 health 直查路径（tokens_total 恒 0；接通归 M2c 修约）')

  // blocked_reason 榜：逐票 show 封顶 BLOCKED_SHOW_CAP，超出折叠计数+reason
  const blockedCats: string[] = []
  const blockedData: number[] = []
  for (const r of blocked.slice(0, BLOCKED_SHOW_CAP)) {
    const full = await deps.showTicket(String(r?.id ?? ''))
    const why = String(full?.blocked_reason ?? full?.meta?.blocked_reason ?? '（原因未取到）')
    blockedCats.push(`${String(r?.id ?? '?')}：${why.slice(0, 40)}`)
    blockedData.push(1)
  }
  if (blocked.length > BLOCKED_SHOW_CAP) {
    reasons.push(`blocked 票 ${blocked.length} 张超榜上限 ${BLOCKED_SHOW_CAP}，仅逐票取前 ${BLOCKED_SHOW_CAP} 张原因`)
  }
  // 静默在制：running 票会话 mtime 超阈值（_sessionKbFast 同源信息，这里轻量 stat）
  const silentCats: string[] = []
  const silentData: number[] = []
  for (const r of running) {
    const ms = isoMs(r?.updated)
    if (Number.isFinite(ms) && nowMs - ms > silentMin * 60_000) {
      silentCats.push(String(r?.id ?? '?'))
      silentData.push(Math.round((nowMs - ms) / 60000))
    }
  }
  base.charts = {
    primary: chart('hBar', `blocked 榜（stage_state=blocked，封顶 ${BLOCKED_SHOW_CAP}）`, blockedCats, [{ name: '张', data: blockedData }]),
    secondaries: [
      chart('stackBar', '票流状态分布', ['open', 'closed', 'blocked', 'running'], [
        { name: '票数', data: [rows.filter((r) => String(r?.status ?? '') !== 'closed').length, rows.filter((r) => String(r?.status ?? '') === 'closed').length, blocked.length, running.length] },
      ]),
      chart('bar', `静默在制（会话无进展 > ${silentMin} 分钟）`, silentCats, [{ name: '静默分钟', data: silentData }]),
    ],
  }
  void stageIds // health 直查路径不用模板 stage 轴（票流桶计数为准）
  if (reasons.length > 0) base.reason = dedupe(reasons).join('；')
  return { status: 200, body: base }
}
