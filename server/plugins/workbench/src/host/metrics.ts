/**
 * metrics.ts —— metrics M1a（t260901-20）读侧聚合唯一实现（只读真源，永不回写）。
 *
 * 双前门共用本模块（契约块 2 L158「同实现同缓存」+ 立项关键决策 3「一个实现
 * 两扇前门」）：HTTP 前门 = node.ts 的 exact 路由 /sandbar-workbench/api/wf/metrics；
 * CLI 前门 = metrics-cli.mjs（argv JSON 收口后直调 buildMetricsResponse）。
 * 数据契约唯一真源 = docs/design/metrics-api-contract-v1.md（v1 冻结版），字段增删须
 * 开新工单 bump（块 6），本文件不得私改 schema。
 *
 * 口径出处（票 t260901-20 方案，实现锚点）：
 * - 时间维：stage 时长 v1=handoff 近似，窗口派生复用 agent-usage.ts
 *   stageWindowsFromTimeline（乱序按 from 排序）；末窗封口是本模块新增语义
 *   （agent-usage 末窗 toMs=null 开放式，L82-93），实现为 closeStageWindows
 *   包装、不改本体签名——既有消费方（agent-usage 端点、M1b 泳道图）零回退。
 * - 交付维（t260903-09 KI-017①② 重写）：泳道在=泳道三点 diff（活口径）；泳道
 *   拆了/字段缺失/直并票=主仓归档口径（票 id grep 提交集，frozen=true），
 *   reason 显式标注口径，两口径不静默混用；git 双路失败 → null+reason。
 * - token 维：复用 aggregateTicketUsage（块 5 八项故障模式随函数全量带入）；
 *   泳道会话陪葬后回落项目级 usage 账本（SANDBAR_USAGE_LEDGER_DIR 前向契约），
 *   缓存存量降维保留（engine_version 失配不再整条作废）。
 * - 纳票/归窗口径（原契约未覆盖，票 t260901-20 成文、已上报用户裁决）：closed 票归窗时刻=
 *   闭单终态时刻，未结票=创建时刻；KPI 分母与 charts 聚合同一口径、跨视图一致。
 * - health 视图：直查不读缓存（块 2 L157）；kpis 恒冻结四字段（tokens_total=
 *   0+reason，token 维不在直查路径）；blocked/silent 落 charts；server/worker
 *   存活经 200+reason 人话承载（块 4 SKIP 先例），不进 schema（块 6 冻结）。
 *
 * 缓存路径（t260901-14 路径约定）：~/.sandbar/projects/<key>/data/metrics/。
 * 【碑注——两真源矛盾】契约块 3 L189 写「~/.sandbar/data/<project>/」，与
 * sandbar 契约 ①a（sandbar-project-onboarding-contract-v1.md L170-171）的 projects/<key>/data/
 * 矛盾；本实现取 ①a（工单正文明示「经 t260901-14 的路径约定解析」），契约
 * 修订候选已上报用户，谁也不代改冻结文档。env SANDBAR_METRICS_DIR 仅测试覆盖。
 * legacy SANDBAR_PROJECTS_YAML 单文件模式下 per-key 目录无定义 → 缓存禁用+SKIP。
 *
 * 测试缝（同既有测试桩 env 先例）：env SANDBAR_METRICS_STUB 指向 stub JSON
 * {tickets, workflows, shows, deliveries}，deps 全离线零 admin.py/git 真源，
 * 供 CLI 双前门基线与泳道测试用；未设时走真通路。
 */

import { execFile } from 'node:child_process'
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises'
import net from 'node:net'
import { homedir } from 'node:os'
import { isAbsolute, join } from 'node:path'
import { promisify } from 'node:util'
import { runAdminCli } from '../../../../sandbar-tools.ts'
import { findProject, loadProjects, primaryDir } from '../../../../project-registry.ts'
import { listEpics, resolveEpicsDir } from './epics.ts'
import {
  aggregateTicketUsage, resolveAllSessionFiles, resolveLedgerSessionFiles, stageWindowsFromTimeline,
  type StageWindow,
} from './agent-usage.ts'

const execFileP = promisify(execFile)

/** v1→v2（t260904-09）：settle 出仓快照语义 + 归档口径收窄（票号前缀）。bump 后
 *  全量 per-ticket 缓存整条作废重算（契约成文「缓存整体可弃置重建」）——存量
 *  non-null frozen 记录（如 t260904-05 归档 5783）由此获得唯一重算入口，收窄后
 *  重算=5658。副作用面：collectArchivedRows 记忆行按 source_version 过滤，
 *  bump 后旧记忆行缺席（聚合宇宙暂缩，重算入口=既有 list/全量门；在-list 票不受影响）。 */
export const SOURCE_VERSION = 'v2'
/** health 视图静默阈值（分钟）：模块常量，env SANDBAR_METRICS_SILENT_MIN 仅测试覆盖；可调 UI 参数归 M2c 修约。 */
export const SILENT_RUNNING_MIN = 30
/** blocked_reason 榜逐票 show 封顶（成本上限，超出折叠计数+reason；票多项目不炸）。 */
export const BLOCKED_SHOW_CAP = 20

/**
 * 逐票记录生成的并发度（t260902-05⑦冷启动：串行逐票 spawn admin.py+git+zstd
 * 解压是打开慢的根因）。env SANDBAR_METRICS_CONCURRENCY 仅测试覆盖；上限 8 防
 * 失配值把 admin.py 打成风暴。结果按入参序落位（out[idx]），与串行逐票同一
 * skipped/reason 顺序，双前门字节级一致不受影响（golden 基线锁定）。
 */
export const TICKET_CONCURRENCY = Math.max(1, Math.min(8, Number.parseInt(process.env.SANDBAR_METRICS_CONCURRENCY ?? '', 10) || 4))

/**
 * KI-040 null 重探节流门（分钟，t260904-04）：缓存记录 delivery===null 时距
 * updated_ts 超 TTL 才重探（每票每周期最多一轮 showTicket+git，防「真不可算」票
 * 每请求重复付费）。env SANDBAR_METRICS_REPROBE_TTL_MIN：缺省 60；0=每次必探（仅
 * 测试用）；负值按 0；非法/缺失按缺省。逐调读取（非模块常量）保测试可注入。
 */
function reprobeTtlMin(): number {
  const v = Number.parseInt(process.env.SANDBAR_METRICS_REPROBE_TTL_MIN ?? '', 10)
  return Number.isFinite(v) ? Math.max(0, v) : 60
}

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
/** 取数模式（t260903-09 cache-first）：full=全量惰性计算（缺省）；fast=只读缓存聚合（缺票不现算，cache.status='stale'）。 */
const MODES = ['full', 'fast']
const NUM_RE = /^\d+(\.\d+)?$/

/* ------------------------------------------------ 参数解析（契约块 2 防穿） */

export interface MetricsParams {
  window: string
  epic: string
  project: string
  template: string
  view: string
  mode: string
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
  const out: MetricsParams = { window: '7d', epic: 'all', project: '', template: 'dev-lane', view: '', mode: 'full' }
  const projectGiven = get('project').length > 0
  for (const [key, def] of [['window', '7d'], ['epic', 'all'], ['project', ''], ['template', 'dev-lane'], ['view', ''], ['mode', 'full']] as const) {
    const r = once(key)
    if (r.err) return { ok: false, status: 400, error: r.err }
    if (r.v !== undefined && r.v !== '') (out as any)[key] = r.v
  }
  if (!(out.window in WINDOWS)) return { ok: false, status: 400, error: `window 非法：'${out.window}'（枚举 1d|3d|7d|30d|all）` }
  if (!MODES.includes(out.mode)) {
    return { ok: false, status: 400, error: `mode 非法：'${out.mode}'（枚举 full|fast）` }
  }
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
  /** 默认项目 key（注册表字母序首个，project-registry.ts scanRegistry sort 口径）。 */
  defaultProject: () => Promise<string | null>
  /**
   * per-project 主目录解析（t260904-04，KI-043①）：project key → 注册表主目录。
   * 缺省实现（defaultDeps）对任何注册表合法 key（含默认项目）返回 primaryDir(key)，
   * buildMetricsResponse 据此换根 deps.repo（git/主仓回落/会话解析随之指向项目主
   * 目录）——双前门（node.ts/metrics-cli.mjs 同吃 defaultDeps）同修，前门零逻辑。
   * 未知 key/注册表异常返回 null（回退传入 repo；checkProject 4xx 先拦，仅兜底）。
   * stubDeps 不带 → 既有测试/golden 零破坏；单测可显式注桩。
   */
  repoForProject?: (key: string) => string | null
  /** git：cwd 下跑 args，stdout 原文；失败抛错（调用方软降级）。 */
  git: (cwd: string, args: string[]) => Promise<string>
  now: () => number
}

/** SANDBAR_METRICS_STUB 测试缝：读 stub JSON 构造全离线 deps。 */
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
  const stub = process.env.SANDBAR_METRICS_STUB
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
    repoForProject: (key) => {
      try {
        const p = findProject(key)
        return p ? primaryDir(p) : null
      } catch {
        return null // 注册表不可读/隔离条目：回退传入 repo（checkProject 4xx 先拦）
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
  /* 归窗锚点（t260903-09 契约 bump：派生字段入缓存、不入响应）——fast 路径与
   * 缓存命中路径据此免 showTicket spawn 补锚点；旧版记录无此两键 → null → 走
   * 既有「list 行 timeline / show 取 timeline」补齐路径，读侧向后兼容。 */
  created_ms?: number | null
  closed_ms?: number | null
}

/**
 * per-ticket 缓存目录：~/.sandbar/projects/<key>/data/metrics/（t260901-14 路径
 * 约定；env SANDBAR_PROJECTS_DIR 现读，SANDBAR_METRICS_DIR 测试覆盖）。
 * legacy 单文件模式（SANDBAR_PROJECTS_YAML）无 per-key 目录定义 → enabled:false+SKIP。
 * 两真源矛盾见文件头碑注。
 */
export function resolveMetricsCacheDir(projectKey: string): { dir: string; settleDir: string; enabled: boolean; reason?: string } {
  // settle 出仓快照目录（t260904-09）：根链与引擎 _settle_snapshot_dir 同序互指
  // （SANDBAR_SETTLE_SNAPSHOT_DIR ?? SANDBAR_METRICS_DIR ?? SANDBAR_PROJECTS_DIR ?? home
  // ——SETTLE env 替换项目根整体，只在链头）——缺 SETTLE 头会造成写读分叉、快照
  // 永不可见（integration R6 实证，已修）。读取独立于缓存 enabled：legacy 单文件
  // 注册表模式只影响「host 侧缓存落盘」，引擎照常把快照写进根链目录，读侧照读
  // （契约增补段成文）。
  const settleDirOf = () => {
    const root = process.env.SANDBAR_SETTLE_SNAPSHOT_DIR ?? process.env.SANDBAR_METRICS_DIR
      ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
    return join(root, projectKey, 'data', 'settle')
  }
  if (process.env.SANDBAR_PROJECTS_YAML) {
    const root = process.env.SANDBAR_METRICS_DIR ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
    return { dir: '', settleDir: settleDirOf(), enabled: false, reason: 'legacy 单文件注册表模式（SANDBAR_PROJECTS_YAML）无 per-key 数据目录约定，metrics 缓存禁用（数据现算，不落盘）' }
  }
  const root = process.env.SANDBAR_METRICS_DIR ?? process.env.SANDBAR_PROJECTS_DIR ?? join(homedir(), '.sandbar', 'projects')
  return { dir: join(root, projectKey, 'data', 'metrics'), settleDir: settleDirOf(), enabled: true }
}

/** settle 出仓快照（t260904-09，KI-017 引擎侧收口）：读 <root>/<key>/data/settle/
 *  <票号>.json，引擎在 merge 落定后冻结。畸形 JSON / 缺字段 / 数值非有限 → null+
 *  reason（不抛、不做假 0）。 */
export interface SettleSnapshot {
  tokens: NonNullable<MetricsCacheRecord['tokens']>
  delivery: NonNullable<MetricsCacheRecord['delivery']> & { squash_commit?: string; zero_change?: boolean }
  squash_commit: string
}

function finiteNum(x: unknown): x is number {
  return typeof x === 'number' && Number.isFinite(x)
}

export async function readSettleSnapshot(settleDir: string, ticketId: string): Promise<{ snap?: SettleSnapshot; reason?: string }> {
  let raw: string
  try {
    raw = await readFile(join(settleDir, `${ticketId}.json`), 'utf8')
  } catch {
    return { reason: `无 settle 快照: ${join(settleDir, ticketId + '.json')}` }
  }
  let obj: any
  try {
    obj = JSON.parse(raw)
  } catch {
    return { reason: `settle 快照不可解析（跳过）: ${ticketId}` }
  }
  const d = obj?.delivery
  const t = obj?.tokens
  if (!d || !t || !finiteNum(d.add) || !finiteNum(d.del) || !finiteNum(d.commits)
    || !finiteNum(t.in) || !finiteNum(t.out) || !finiteNum(t.cacheRead)) {
    return { reason: `settle 快照字段缺失/非法（跳过）: ${ticketId}` }
  }
  const tokens = {
    by_stage: (t.by_stage && typeof t.by_stage === 'object') ? t.by_stage : {},
    by_model: (t.by_model && typeof t.by_model === 'object') ? t.by_model : {},
    in: t.in, out: t.out, cacheRead: t.cacheRead,
  }
  const delivery: SettleSnapshot['delivery'] = { base: String(d.base ?? ''), add: d.add, del: d.del, commits: d.commits }
  // 引擎侧注记键透传：zero_change=true=「收口零变更」（squash_commit 是 main 尾提交
  // 非本票交付）；squash_commit 供 reason 点名真身 hash。
  if (typeof d.squash_commit === 'string' && d.squash_commit !== '') delivery.squash_commit = d.squash_commit
  if (d.zero_change === true) delivery.zero_change = true
  if (typeof d.squash_commit !== 'string' && typeof obj.squash_commit === 'string') delivery.squash_commit = obj.squash_commit
  return { snap: { tokens, delivery, squash_commit: String(delivery.squash_commit ?? obj.squash_commit ?? '') } }
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

/** 读缓存返回：rec=记录本体；engineStale=stages 链指纹失配（时间维须按现行链重算，
 *  delivery/tokens 两维与 stage 链无关 → 降维保留不陪葬，t260903-09 KI-017②③）。 */
export interface CachedTicket {
  rec: MetricsCacheRecord
  engineStale: boolean
}

/** 读缓存：文件缺/坏 JSON/source_version 失配 → null（schema 失配整条作废，形状不可信）；
 *  engine_version 失配 → 返回记录+engineStale=true（只作废时间维，见 CachedTicket 注）。 */
export async function readTicketCache(dir: string, id: string, engineVersion: string): Promise<CachedTicket | null> {
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
  if (rec?.source_version !== SOURCE_VERSION) return null
  return { rec: rec as MetricsCacheRecord, engineStale: rec.engine_version !== engineVersion }
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

/** 单票交付维结果：frozen=true=归档口径（主仓回落成功或缓存存量降维保留），
 *  落 rec.delivery_frozen——读侧 reason 据此标注「冻结快照」，KI-017② 收口。 */
export interface DeliveryResult {
  delivery: MetricsCacheRecord['delivery']
  reason?: string
  frozen?: boolean
}

function parseNumstatTotal(numstat: string): { add: number; del: number } {
  let add = 0
  let del = 0
  for (const line of numstat.split('\n')) {
    const m = /^(\d+|-)\t(\d+|-)\t/.exec(line)
    if (!m) continue
    add += m[1] === '-' ? 0 : Number(m[1])
    del += m[2] === '-' ? 0 : Number(m[2])
  }
  return { add, del }
}

/**
 * 单票交付维（t260903-09 KI-017①② 收口重写）：
 * - 泳道在且 git 可读：泳道三点 diff（活口径，frozen=false）。已知病灶=区间 diff
 *   会吸收中途并 main 的进度（t260902-02 实证显示 8 万 vs squash 实测 +2,557），
 *   活口径语义不变，主仓回落口径见下——两口径差异在 reason 显式标注，不静默混用。
 * - 泳道拆了 / base_ref·worktree 缺失（直并收口票）/ 泳道 git 失败：回落**主仓
 *   归档口径**——`git log --grep <票id>` 取引用本票的提交集（merge/squash commit
 *   message 均带票 id）+ numstat 合计。票 id grep 为主键，不依赖 base_ref/worktree
 *   （绕开旧实现的字段早退——直并票恰无这两字段又最需要补账）；提交集口径天然不含
 *   main 无关进度，正面收口 KI-017①。frozen=true，主仓历史不随泳道拆除蒸发。
 * - 两路全失败：delivery=null + reason（人话，含两路失败原因），不做静默 0。
 * 已知边界：一 commit 引用多票 id 时同一行变更会计入两票提交集（双算面）；
 * 实证与标注义务见 tests/delivery-recovery.mjs，反例票 reason 不静默。
 */
export async function computeDelivery(deps: MetricsDeps, ticket: any): Promise<DeliveryResult> {
  const base = String(ticket?.base_ref ?? '')
  const worktree = String(ticket?.worktree ?? '')
  const id = String(ticket?.id ?? '')
  let laneFail = ''
  if (base !== '' && worktree !== '') {
    try {
      // t260904-04（KI-041）：KI-032 后 worktree 恒为绝对路径（锚项目根），join
      // 第二参不重置基址会拼出 /…/sandbar/Users/... 毒路径杀死全部活口径——绝对
      // 路径直接用；相对路径旧值兜底 join（向后兼容）。
      const cwd = isAbsolute(worktree) ? worktree : join(deps.repo, worktree)
      const numstat = await deps.git(cwd, ['diff', `${base}...HEAD`, '--numstat'])
      const { add, del } = parseNumstatTotal(numstat)
      const commits = Number((await deps.git(cwd, ['rev-list', '--count', `${base}..HEAD`])).trim())
      return { delivery: { base, add, del, commits: Number.isFinite(commits) ? commits : 0 }, frozen: false }
    } catch (err) {
      laneFail = String(err instanceof Error ? err.message : err)
    }
  } else {
    laneFail = '工单缺 base_ref/worktree（无泳道或历史/直并票）'
  }
  if (id === '') {
    return { delivery: null, reason: `delivery 维不可算（${laneFail}，且无票 id 可回落主仓）` }
  }
  try {
    // 归档口径收窄（t260904-09，工单条 6）：只认 message 首行以票号开头的 squash
    // 收口提交（squash 模板保证首 token=票号），他账剔除——引用性提及（教训引用
    // 「t260904-05 教训」等）票号不居首，天然被前缀挡掉（取代 t260904-04 增补段 3
    // 「收窄议后不落」结论：子串启发式误判面在「不居首」，前缀锚定无此面）。
    // 实证锚=t260904-05：grep 命中 5 提交、前缀命中仅 1（真身 455320d=5658，
    // grep 合计 5783 含他账 125）。
    const headList = await deps.git(deps.repo, ['log', '--format=%H %s', '--grep', id])
    const lines = headList.split('\n').filter((l) => l.trim() !== '')
    const squashLines = lines.filter((l) => l.slice(41).startsWith(id))
    if (lines.length === 0) {
      return { delivery: null, reason: `主仓无引用本票（${id}）的提交（泳道${laneFail === '' ? '不可用' : `：${laneFail}`}），delivery 维不可算`, frozen: false }
    }
    if (squashLines.length === 0) {
      return { delivery: null, reason: `主仓仅他账引用本票（${id}，${lines.length} 条无票号前缀，已剔），delivery 维不可算（泳道${laneFail}）`, frozen: false }
    }
    let add = 0
    let del = 0
    for (const line of squashLines) {
      const numstat = await deps.git(deps.repo, ['show', '--numstat', '--format=', line.slice(0, 40)])
      const s = parseNumstatTotal(numstat)
      add += s.add
      del += s.del
    }
    return {
      delivery: { base, add, del, commits: squashLines.length },
      reason: `delivery 为主仓归档口径（票号前缀 squash 提交 ${squashLines.length} 个，grep 命中 ${lines.length} 条已剔他账；泳道${laneFail}）`,
      frozen: true,
    }
  } catch (err) {
    return { delivery: null, reason: `git 读取失败（泳道：${laneFail}；主仓回落也失败：${String(err instanceof Error ? err.message : err)}），delivery 维置空` }
  }
}

/** 单票 token 维：复用 agent-usage 通路（八项故障模式随函数带入，契约块 5）。
 *  t260903-09 KI-017③ 补账缝：泳道会话不存在（已拆）→ 探测项目级 usage 账本
 *  （SANDBAR_USAGE_LEDGER_DIR，引擎侧出仓前向契约）；两处皆无 → null+人话 reason。 */
export async function computeTokens(
  deps: MetricsDeps, id: string, ticket: any, windows: StageWindow[],
): Promise<{ tokens: MetricsCacheRecord['tokens']; reason?: string }> {
  const ref = await resolveAllSessionFiles(deps.repo, id, ticket)
  if (ref.refused === true) return { tokens: null, reason: ref.reason ?? '工单字段越界（拒绝读取会话）' }
  let paths = ref.paths ?? []
  let srcReason = ref.reason
  if (paths.length === 0) {
    const led = await resolveLedgerSessionFiles(id)
    if (led.paths.length > 0) {
      paths = led.paths
      srcReason = undefined
    } else if (led.reason) {
      srcReason = led.reason
    }
  }
  const agg = await aggregateTicketUsage(paths, windows)
  if (!agg.exists) return { tokens: null, reason: paths.length === 0 ? (srcReason ?? agg.reason ?? '无 usage 事件') : (agg.reason ?? '无 usage 事件') }
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
  /** 锚点为近似值（旧版缓存记录无锚点，按 rec.computed_at 近似归窗；t260903-09 F3）。
   *  近似锚点只进响应、绝不回写缓存（防近似值永久化成「闭单时刻」）。 */
  anchorApproximated?: boolean
  /** 近似锚点基线（t260904-04 F1 修复）：本请求内重算的记录，取**重算前**存量记录的
   *  computed_at——归档票无 timeline 可补真锚点，若用重算后的 computed_at（=本次请求
   *  时刻 > 窗口上界 to）近似归窗，被治愈的票会在首拍被 inWindow 静默丢弃（人口塌缩
   *  一拍）。锚点基线钉在首次计算时刻，跨多次重探单调不漂。 */
  anchorApproxBaseMs?: number
  /** open 标志无外部真源（F2，t260904-04）：show 回退合成行且 open=true——归档票
   *  收口终态不可达，closed 计数可能低计，进 notices 显式计数（不静默）。 */
  openUnverified?: boolean
}

async function ticketRecord(
  deps: MetricsDeps, row: any, template: string, stages: any[], engineVersion: string,
  cacheDir: { dir: string; settleDir: string; enabled: boolean; reason?: string },
): Promise<RecordWithAnchor | null> {
  const id = String(row?.id ?? '')
  if (id === '') return null
  const humanStages = new Set(stages.filter((s: any) => s?.exit === 'human').map((s: any) => String(s.id)))
  const cached = cacheDir.enabled ? await readTicketCache(cacheDir.dir, id, engineVersion) : null
  if (cached && !cached.engineStale) {
    // 新版记录自带归窗锚点（created_ms/closed_ms，t260903-09 bump）→ 纯命中路径零
    // showTicket spawn。t260904-04（KI-040）缓存命中不再无条件早退——两类陈旧记录
    // 放行走下方重算路径（prev=cached.rec 降维保留在位）：
    //   条件 A（失败维固化，TTL 节流）：delivery===null 且 updated_ts 距今超 TTL
    //     （SANDBAR_METRICS_REPROBE_TTL_MIN，缺省 60 分钟；0=每次必探仅测试）。缺失/
    //     坏值 updated_ts（isoMs→NaN）视为过期必探——不给脏记录留永久静默。重探
    //     写回恒刷 updated_ts=「上次尝试时刻」，节流锚点自洽、风暴有界（每票每
    //     TTL 周期最多一轮 showTicket+git）。
    //   条件 B（open 陈旧）：rec.open 与 list 行 status 比对不一致 → 刷新。比对
    //     是零 spawn 纯内存且不受 TTL 门；刷新走既有全量重算路径（closed_ms/
    //     timeline 从 show 来——不可内存改 flag 了事，否则闭单票归窗锚点退化为
    //     created_ms 污染 KPI 归窗）。
    const expectedOpen = String(row?.status ?? '') !== 'closed'
    const ts = isoMs(cached.rec.updated_ts)
    const ttlMs = reprobeTtlMin() * 60_000
    // TTL=0（必探语义）或 updated_ts 缺失/坏值（isoMs→NaN）→ 恒过期必探
    const expired = ttlMs === 0 || !(Number.isFinite(ts) && deps.now() - ts <= ttlMs)
    const needsReprobe = cached.rec.delivery === null && expired
    const openStale = cached.rec.open !== expectedOpen
    if (!needsReprobe && !openStale) {
      return {
        rec: cached.rec,
        createdMs: cached.rec.created_ms ?? null,
        closedMs: cached.rec.closed_ms ?? null,
        fromCache: true,
        persisted: true,
      }
    }
  }
  // engineStale（stages 链演化）：时间维必须按现行链重算（stage 键可能改名），
  // delivery/tokens 两维与 stage 链无关 → 从 prev 降维保留，不因版本失配陪葬
  // （t260903-09 KI-017②③：蒸发真实路径=此处旧实现整条作废后重算失败写 null）。
  const prev = cached?.rec ?? null
  const shown = await deps.showTicket(id)
  const ticket = shown ?? row
  // F2 修复（t260904-04）：show 不可达（返回 null，归档票列表/show 双不可达的结构面）
  // 时，open 无外部真源——沿用存量 flag（自确认循环不漂白也不误翻），归档票 open=true
  // 另由主循环标记 openUnverified 进 notices 显式计数（registry 根修=KI-031 家族）。
  const showFellBackToRow = shown === null || shown === undefined
  const timeline = ticket?.timeline ?? ticket?.meta?.timeline
  const durations = computeDurations(timeline, humanStages, deps.now())
  // settle 出仓快照优先（t260904-09，KI-017 收口）：快照 > 现算（泳道活/会话聚合）
  // > 归档 grep。快照命中 → delivery/tokens 直取快照值、delivery_frozen=true，
  // 跳过 computeDelivery/computeTokens（归档 grep 收窄口径只服务无快照存量票）。
  const snapRef = await readSettleSnapshot(cacheDir.settleDir, id)
  let delivery = prev?.delivery ?? null
  let deliveryFrozen = prev?.delivery_frozen ?? false
  let tokens: MetricsCacheRecord['tokens'] = null
  if (snapRef.snap) {
    delivery = snapRef.snap.delivery
    deliveryFrozen = true
    tokens = snapRef.snap.tokens
  } else {
    // 重算 delivery 门（t260904-04 条1）：只看 delivery===null，不再看 frozen 位——
    // null+frozen 脏态（命中路径条件 A 放行进来）若保留 frozen 门会跳过 computeDelivery、
    // 写回仍 null+frozen，下个 TTL 周期白烧 spawn 永不自愈。其余状态零影响：prev.delivery
    // 非 null 首条件短路跳过（frozen 快照不重算语义不变）；engineStale 降维保留路径不受影响。
    if (delivery === null) {
      const d = await computeDelivery(deps, ticket)
      delivery = d.delivery
      if (d.frozen === true) deliveryFrozen = true // 主仓归档口径成功 → 冻结
    }
    if (delivery !== null && prev !== null && cached?.engineStale === true) {
      deliveryFrozen = true // 降维保留的存量=冻结快照（归档口径）
    }
    const windows = closeStageWindows(stageWindowsFromTimeline(timeline), durations.closed_ms ?? NaN)
    const t = await computeTokens(deps, id, ticket, windows)
    // token 现算失败（泳道会话已拆）→ 存量保留；同序 reason 由 stableReasons 只看 rec 状态保证双前门一致
    tokens = t.tokens ?? prev?.tokens ?? null
  }
  const nowIso = new Date(deps.now()).toISOString()
  // F1 修复姊妹面：无真锚点（timeline 不可得）时 computed_at 保留基线值（首次计算
  // 时刻），不随重探覆写为 now——否则下一拍纯命中近似归窗 approx=now>to 再次塌缩。
  // updated_ts 仍恒刷（TTL 节流锚点不受影响）；语义细化已落契约增补段 1。
  const prevComputedMs = isoMs(prev?.computed_at)
  const anchorBaseIso = Number.isFinite(prevComputedMs) && durations.created_ms === null
    ? new Date(prevComputedMs).toISOString()
    : nowIso
  const rec: MetricsCacheRecord = {
    ticket_id: id,
    template,
    durations: { by_stage: durations.by_stage, by_round: durations.by_round, human_wait: durations.human_wait },
    delivery,
    tokens,
    open: showFellBackToRow ? (prev?.open ?? String(ticket?.status ?? '') !== 'closed') : String(ticket?.status ?? '') !== 'closed',
    delivery_frozen: deliveryFrozen,
    source_version: SOURCE_VERSION,
    engine_version: engineVersion,
    updated_ts: nowIso,
    computed_at: anchorBaseIso,
    created_ms: durations.created_ms,
    closed_ms: durations.closed_ms,
  }
  const persisted = cacheDir.enabled ? await writeTicketCache(cacheDir.dir, rec) : false
  // F1 修复：近似锚点基线=重算前存量 computed_at——治愈票首拍归窗用它，不被
  // 重算时刻（=now>to）挤出人口。
  return { rec, createdMs: durations.created_ms, closedMs: durations.closed_ms, fromCache: false, persisted, ...(Number.isFinite(prevComputedMs) ? { anchorApproxBaseMs: prevComputedMs } : {}) }
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
    if (e.rec.delivery === null && !e.rec.delivery_frozen) out.push(`${id}: delivery 维不可算（泳道不可用且主仓无引用本票的提交）`)
    // settle 出仓快照（t260904-09）：squash_commit 注记键在场即快照口径——
    // zero_change=true 时 squash_commit 是 main 尾提交（非本票交付），文案显式点名防误导
    if (e.rec.delivery !== null && e.rec.delivery_frozen && (e.rec.delivery as any).squash_commit) {
      const d = e.rec.delivery as any
      out.push(d.zero_change === true
        ? `${id}: delivery=settle 快照·收口零变更（${d.squash_commit} 为 main 尾提交，非本票交付）；token=settle 快照`
        : `${id}: delivery=settle 快照（squash ${d.squash_commit}，真身口径）；token=settle 快照`)
    }
    // 归档口径（收窄后）：只计票号前缀 squash 提交（t260904-09），多提交面随收窄收敛
    if (e.rec.delivery !== null && e.rec.delivery_frozen && !(e.rec.delivery as any).squash_commit) out.push(`${id}: delivery 为主仓归档口径（票号前缀提交 ${e.rec.delivery.commits} 个，他账已剔；冻结快照 KI-017②）`)
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

/** 归窗锚点（票 t260901-20 口径）：closed 票=闭单终态时刻；未结票=创建时刻。KPI 与 charts 同口径。 */

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
  // per-project 换根（t260904-04，KI-043①）：本请求局部生效——git/主仓回落/会话
  // 解析随 deps.repo 指向该项目注册表主目录；admin CLI 通路面（listTickets/showTicket
  // 等闭包）不触碰（本就按 project 传参分流）。缺省实现含默认项目也换根（语义见
  // MetricsDeps.repoForProject 注）；未知/异常回退传入 repo，不换根不报错。
  deps = { ...deps, repo: deps.repoForProject?.(p.project) ?? deps.repo }
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
  // 去重名单取「未过滤」全量列表（t260903-09 修复）：若在 epic 筛选后取名单，
  // 「在列表但被筛掉」的票会被宇宙补全二次并入（epic=none 下冒充无代号票）。
  const listedIds = new Set(rows.map((r: any) => String(r?.id ?? '')))
  if (p.epic === 'none') rows = rows.filter((r: any) => String(r?.epic ?? '') === '' && (r?.__archived !== true))
  else if (p.epic !== 'all') rows = rows.filter((r: any) => String(r?.epic ?? '') === p.epic)
  // 模板过滤（t260904-04，KI-043②）：被过滤的票不再静默缩宇宙——计数进 notices，
  // 用户可在 reason 看到「list 有 N 票因 workflow 为空/不匹配被排除」。
  const beforeTemplateFilter = rows.length
  rows = rows.filter((r: any) => String(r?.workflow ?? '') === p.template)
  const templateDropped = beforeTemplateFilter - rows.length

  const nowMs = deps.now()
  const span = WINDOWS[p.window] ?? 0
  const from = span === 0 ? -Infinity : nowMs - span
  const to = nowMs

  const cacheDir = resolveMetricsCacheDir(p.project)

  // 宇宙补全（t260903-09 S5，audit 洞）：直并/收口终态票可能已从工单列表消失，
  // 但度量缓存仍有其存量记录——从缓存目录并入（epic 不入缓存=存量票 epic 未知，
  // 仅在 all 与对应窗口可见；template 筛选仍尊重，跨模板不混排契约不破）。
  // W3 红线：只并入度量聚合，绝不回写 ticket list API（dispatch 流不被污染）。
  const archivedRows = cacheDir.enabled ? await collectArchivedRows(cacheDir.dir, p.template, listedIds) : []
  const allRows: any[] = archivedRows.length > 0 ? [...rows, ...archivedRows] : rows

  if (p.view === 'health') return healthView(deps, rows, p, stageIds, from, to, nowMs, reasons)

  /* -- 三数据视图：逐票惰性算/读缓存（t260902-05⑦：有界并发，保序落位，
      skipped/reason 顺序与原串行一致；锚点补齐也在任务内做，语义不变）。
      mode=fast（t260903-09 cache-first）：只读缓存聚合，缺票不现算——
      先吐缓存快照（cache.status='stale'），全量由客户端随后台请求补。 -- */
  let recordEntries: (RecordWithAnchor | null)[]
  const fastSkips: string[] = []
  if (p.mode === 'fast') {
    recordEntries = await mapPool<any, RecordWithAnchor | null>(allRows, TICKET_CONCURRENCY, async (row) => {
      const e = await fastCacheRecord(cacheDir, row, engineVersion)
      if (e === null) { fastSkips.push(`${String(row?.id ?? '?')}: fast 无可用缓存（未算过或引擎版本失配），跳过现算`); return e }
      if (row.__archived === true && e.rec.open === true) e.openUnverified = true
      return e
    })
  } else {
    recordEntries = await mapPool<any, RecordWithAnchor | null>(allRows, TICKET_CONCURRENCY, async (row) => {
      const e = await ticketRecord(deps, row, p.template, stages, engineVersion, cacheDir)
      if (e === null) return null
      // F2 显式化（t260904-04）：归档票 open=true 恒无外部真源（列表/show 双不可达），
      // 命中与重算两拍一致标记 → notices 计数（不静默缩 closed 人口）。
      if (row.__archived === true && e.rec.open === true) e.openUnverified = true
      // 锚点统一补齐：新版缓存记录自带 created_ms/closed_ms（零 spawn）；旧版记录
      // 或重算路径缺锚点时，优先 list 行自带 timeline（stub/测试零成本），否则一次
      // show 取 timeline。命中/重算两条路径产出同一响应，双前门字节级比对不红。
      if (e.createdMs === null) {
        const id = String(row?.id ?? '')
        const tl = row?.timeline ?? (row.__archived === true ? undefined : (await deps.showTicket(id))?.timeline)
        const realCreated = timelineCreatedMs(tl)
        if (realCreated !== null) {
          e.createdMs = realCreated
          e.closedMs = e.rec.open ? null : timelineClosedMs(tl)
          // F2 迁移回写：旧版缓存记录命中后补齐了真实锚点 → 落盘升级为带锚点新版，
          // 下次 fast 直接受益（存量数据逐步收敛，不再永久跳过）。近似锚点不回写。
          if (e.fromCache && cacheDir.enabled &&
            (e.rec.created_ms === undefined || (!e.rec.open && e.rec.closed_ms === undefined))) {
            e.rec.created_ms = e.createdMs
            if (!e.rec.open && e.closedMs !== null) e.rec.closed_ms = e.closedMs
            e.persisted = await writeTicketCache(cacheDir.dir, e.rec)
          }
        } else if (row.__archived === true) {
          // F3 存量票近似归窗：列表外票无 timeline 可补，按 rec.computed_at 近似——
          // 只进内存不回写（防近似值被永久化成真实闭单时刻），reason 显式声明。
          // F1 修复（t260904-04）：本请求内重算的记录用重算前存量 computed_at 作基线
          // （anchorApproxBaseMs），否则 approx=now>to，治愈票首拍被 inWindow 丢弃。
          const approx = Number.isFinite(e.anchorApproxBaseMs) ? e.anchorApproxBaseMs! : isoMs(e.rec.computed_at)
          if (Number.isFinite(approx)) {
            e.createdMs = approx
            if (!e.rec.open && e.closedMs === null) e.closedMs = approx
            e.anchorApproximated = true
          }
        }
      }
      return e
    })
  }
  const skipped: string[] = []
  for (let i = 0; i < recordEntries.length; i++) {
    if (recordEntries[i] === null) skipped.push(`${String(allRows[i]?.id ?? '?')}: 记录生成失败，跳过`)
  }
  const entries = recordEntries.filter((e): e is RecordWithAnchor => e !== null)

  // KPI 单一口径（票 t260903-09 收口）：四指标同一 anchor——
  // closed 票按闭单时刻、未结票按创建时刻归窗。原实现 tickets 按创建归窗、closed
  // 按闭单归窗，出现「关闭数(10) > 工单数(8)」悖论，此处收口为单一人口。
  const kpis = emptyKpis()
  const kept: MetricsCacheRecord[] = []
  let avgSumMin = 0
  let approxInWindow = 0
  for (const e of entries) {
    const anchor = e.rec.open ? e.createdMs : (e.closedMs ?? e.createdMs)
    if (anchor === null || !inWindow(anchor, from, to)) continue
    kpis.tickets += 1
    kept.push(e.rec)
    // 近似 notice 计数口径=「通过归窗的近似条目数」：与 KPI
    // 人口严格一致，响应中途重算导致的边界排除票不再被 notice 多报。
    if (e.anchorApproximated === true) approxInWindow += 1
    if (!e.rec.open) {
      kpis.closed += 1
      if (e.createdMs !== null && anchor - e.createdMs > 0) avgSumMin += (anchor - e.createdMs) / 60000
    }
  }
  kpis.avg_delivery_min = kpis.closed > 0 ? round2(avgSumMin / kpis.closed) : 0.0
  kpis.tokens_total = kept.reduce((s, r) => s + (r.tokens ? r.tokens.in + r.tokens.out : 0), 0)

  const body = buildChartsBody(p.view, kept, stageIds, kpis)
  // cache.status 契约字面语义（t260901-20 回归字面；t260903-09
  // bump 增 'stale'）：'computed'=本响应含本次惰性生成（缓存 miss）的记录；'hit'=
  // 全部记录由缓存读命中；'stale'=fast 模式缓存快照（可能缺票，客户端随后台全量替换）。
  // 双前门字节级一致由此保住：t05/M3 比对基线在两门前**预热缓存**（同请求先跑一次），
  // 两门同刻同缓存状态、status 同为 hit——比较面不削（status 不进剔除清单），契约
  // 字面不偏离。冷缓存下「第一门 computed / 第二门 hit」的天然差异即契约语义本身。
  const cacheStatus = p.mode === 'fast' ? 'stale' : (entries.length > 0 && entries.every((e) => e.fromCache) ? 'hit' : 'computed')
  const nowIso = new Date(nowMs).toISOString()
  const resp: Record<string, unknown> = {
    kpis,
    charts: body.charts,
    generated_at: nowIso,
    cache: { status: cacheStatus, computed_at: nowIso, source_version: SOURCE_VERSION },
  }
  const respReasons = [...fastSkips, ...skipped, ...stableReasons(entries, cacheDir)]
  // 近似归窗计数（F3）：旧版缓存无锚点的票按缓存计算时刻近似归窗，显式计数让用户
  // 可分辨近似与精确；与宇宙补全 notice 一起排在 reason 首、不受 20 条 cap 截断
  // （真实项目规模下 reason 常满，notice 沉尾=用户不可见，验收 F3 实锤）。
  const approxCount = approxInWindow
  const notices: string[] = []
  if (archivedRows.length > 0) {
    notices.push(`度量宇宙补全：${archivedRows.length} 票仅存于度量缓存（工单列表已不可见，直并/收口终态）`)
  }
  if (approxCount > 0) {
    notices.push(`其中 ${approxCount} 票旧版缓存无归窗锚点，按缓存计算时刻近似归窗（全量重算后自动转精确）`)
  }
  if (templateDropped > 0) {
    notices.push(`${templateDropped} 票模板不匹配（workflow 为空或非 ${p.template}）被过滤出聚合宇宙`)
  }
  // F2 显式化（t260904-04）：归档票 open 无外部真源（registry 不暴露收口终态）——
  // 不静默缩 closed 人口，计数进 notices（registry 根修=KI-031 家族，写集外）。
  const openUnverifiedCount = entries.filter((e) => e.openUnverified === true).length
  if (openUnverifiedCount > 0) {
    notices.push(`${openUnverifiedCount} 张归档票 open 标志无外部真源（工单列表与 show 均不可达），closed 计数可能低计`)
  }
  if (notices.length > 0 || respReasons.length > 0) {
    const rest = dedupe(respReasons).slice(0, Math.max(0, 20 - notices.length))
    ;(resp as any).reason = [...notices, ...rest].join('；')
  }
  return { status: 200, body: resp }
}

/** S5 宇宙补全：缓存目录里「不在工单列表」的票 → 合成聚合行。只读缓存文件，不 spawn、
 *  不回写任何 API；坏 JSON 跳过（不崩）；存量票 epic 不入缓存=未知（仅 all 可见，none 桶排除），template 尊重。 */
async function collectArchivedRows(dir: string, template: string, listedIds: Set<string>): Promise<any[]> {
  let files: string[] = []
  try {
    files = (await readdir(dir)).filter((f) => f.endsWith('.json'))
  } catch {
    return [] // 缓存目录不存在=冷项目，无补全面
  }
  const out: any[] = []
  for (const f of files) {
    const id = f.slice(0, -'.json'.length)
    if (listedIds.has(id)) continue
    let rec: any
    try {
      rec = JSON.parse(await readFile(join(dir, f), 'utf8'))
    } catch {
      continue // 坏缓存跳过，不崩不静默混入
    }
    if (rec?.source_version !== SOURCE_VERSION) continue
    if (String(rec?.template ?? '') !== template) continue
    out.push({
      id,
      workflow: String(rec.template),
      epic: '',
      status: rec.open === true ? 'running' : 'closed',
      archived: true, // 派生标记（内存行，不进冻结 schema）：reason 计数 + epic=none 桶排除（存量票 epic 未知，不得冒充无代号）
      __archived: true,
    })
  }
  return out
}

/** fast 模式单票记录：只读缓存。engineStale 一律不入（快照宁可缺票不可错数）；
 *  旧版记录（无锚点）按 rec.computed_at 近似归窗——存量数据不再被 fast 永久跳过
 *  （t260903-09 F2/F3），近似票在 reason 显式计数，全量门到达后被真实锚点取代。 */
async function fastCacheRecord(
  cacheDir: { dir: string; enabled: boolean; reason?: string },
  row: any, engineVersion: string,
): Promise<RecordWithAnchor | null> {
  if (!cacheDir.enabled) return null
  const id = String(row?.id ?? '')
  if (id === '') return null
  const c = await readTicketCache(cacheDir.dir, id, engineVersion)
  if (!c || c.engineStale) return null
  let createdMs = c.rec.created_ms ?? null
  let closedMs = c.rec.closed_ms ?? null
  let anchorApproximated: boolean | undefined
  if (createdMs === null && closedMs === null) {
    const approx = isoMs(c.rec.computed_at)
    if (Number.isFinite(approx)) {
      createdMs = approx
      if (c.rec.open !== true) closedMs = approx
      anchorApproximated = true
    }
  }
  if (createdMs === null && closedMs === null) return null
  return { rec: c.rec, createdMs, closedMs, fromCache: true, persisted: true, anchorApproximated }
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
    // 有无代码变更票占比（t260904-09 工单条 7 四桶拆分，互斥且 Σ=票数）：
    // 有变更（add+del>0）/ 已收口·零变更（delivery 非空且全零）/ 未交付（在制，
    // delivery=null 且 open）/ 不可算（数据缺失，delivery=null 且 closed）——
    // 零变更已闭票不再与「不可算」混装。已知边界：归档票 open 无外部真源
    // （openUnverified，KI-031 家族），在制桶可能混入实际已闭的归档票，契约增补段成文。
    const withChange = records.filter((r) => r.delivery !== null && (r.delivery!.add + r.delivery!.del) > 0).length
    const zeroChange = records.filter((r) => r.delivery !== null && (r.delivery!.add + r.delivery!.del) === 0).length
    const noDOpen = records.filter((r) => r.delivery === null && r.open).length
    const noDClosed = records.filter((r) => r.delivery === null && !r.open).length
    return {
      charts: {
        primary: chart('hBar', 'Top 票变更量（行，add+del 分列口径）', top.map((r) => r.ticket_id), [{ name: '行数', data: top.map((r) => r.delivery!.add + r.delivery!.del) }]),
        secondaries: [
          chart('bar', '全窗口变更总量', ['additions', 'deletions', 'commits'], [{ name: '量', data: [add, del, commits] }]),
          chart('donut', '有无代码变更票占比', ['有变更', '已收口·零变更', '未交付（在制）', '不可算（数据缺失）'], [{ name: '票数', data: [withChange, zeroChange, noDOpen, noDClosed] }]),
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
  const silentMin = Number.parseInt(process.env.SANDBAR_METRICS_SILENT_MIN ?? '', 10) || SILENT_RUNNING_MIN
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
