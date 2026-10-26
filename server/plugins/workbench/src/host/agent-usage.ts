/**
 * agent-usage.ts —— 工单 token 消耗聚合的宿主半（只读，t260828-07）。
 *
 * 与 agent-live.ts 是同一套「定位泳道会话文件 + zstd 整解 + 事件提炼」通路的
 * 两个端点（observability 立项关键决策 3）：定位复用 resolveSessionFile 的
 * 防穿/降级契约，解压复用 decompressSession，本文件只做「聚合」这一件事。
 *
 * 聚合口径：
 * - 只加总 `assistant/message` 事件里的 `data.usage{inputTokens,outputTokens,
 *   cacheReadTokens}`。**`assistant/chunk`（data.chunk.type==='usage'）里的
 *   usage 不加总**——它与 message 里的同一份 usage 一一对应（本泳道实测 5↔5），
 *   两处都加会翻倍，这是后来者最容易踩的坑。
 * - 模型归因：usage 事件本身不带 provider/model；顺序扫描维护「当前模型」
 *   （`request/context` 的 data.{provider,model}，`request/header` 的
 *   data.header.config.{provider,model} 兜底），每条 usage 归到当时的模型。
 * - 阶段切分走时间窗：session 按 `<工单id>-<角色>` 复用、同角色跨 stage，
 *   窗口来自 workflow timeline 的 `state==='running'` 条目（base.py _mark 落的
 *   ISO `at`）。第 i 窗 = [from_i, from_{i+1})，最后一窗开放式（到永远）——
 *   toMs 不取事件最大时间，避免晚到事件落空；toMs===null 即开放式。
 *   首窗之前的事件只进 total、不进任何 stage（total ≥ ΣbyStage，口径如此）。
 *
 * 降级：无会话文件/解压失败/0 条 usage → {exists:false, reason 人话}，不抛错；
 * 路径越界 → refused=true，由路由层回 4xx（防穿同 agent-live 验收硬项）。
 * 解析面（t260917-05 零静默降级）：「格式不认识」不再混入普通 0 值——S1 响亮
 * 文案 + suspect/suspectFiles/suspectDetail 独立浮出；发现集空但目录有未入统计
 * 的会话样文件 → reason 按类点名 + suspectFiles（混合态 totals 来自好文件时坏
 * 文件照样浮出，绝不静默）。
 */

import { homedir } from 'node:os'
import { readdir, realpath, stat } from 'node:fs/promises'
import { dirname, join, resolve, sep } from 'node:path'
import {
  SessionError, decompressSession, judgeSessionLines, sessionFaceS1Text,
  scanSuspectSessionFiles, formatSuspectGroups, formatCappedTypes, SESSION_NOTE_CAP,
} from './agent-live.ts'
import { resolveAgentBaseDir } from './agent-logs.ts'
import { existingSessionFilesIn, pickNewestSessionFile } from './session-discovery.ts'

interface Sum { input: number; output: number; cacheRead: number }

function zero(): Sum { return { input: 0, output: 0, cacheRead: 0 } }

function add(a: Sum, u: { inputTokens?: unknown; outputTokens?: unknown; cacheReadTokens?: unknown }): void {
  // 只收有限数值，缺字段/非数值/NaN 一律当 0（畸形输入不炸口径）
  a.input += num(u.inputTokens)
  a.output += num(u.outputTokens)
  a.cacheRead += num(u.cacheReadTokens)
}

function num(x: unknown): number {
  return typeof x === 'number' && Number.isFinite(x) ? x : 0
}

/** 一个阶段时间窗：fromMs 起到 toMs 止（toMs=null 表示开放式，即当前段）。 */
export interface StageWindow {
  stage: string
  fromMs: number
  toMs: number | null
}

export interface ModelSum extends Sum {
  provider: string
  model: string
}

export interface AgentUsageResult {
  exists: boolean
  /** 会话文件数（多角色各一份，全部加总）。 */
  files: number
  total: Sum
  /** 按阶段切分（key=stage id；total ≥ 各 stage 之和，首窗前事件不落段）。 */
  byStage: Record<string, Sum & { models: Record<string, Sum> }>
  /** 各模型的消耗（多模型才在 UI 显示模型名的依据）。 */
  models: ModelSum[]
  /** 人话降级原因，非错误。 */
  reason?: string
  /** 任一会话文件命中 S1「格式不认识」（t260917-05）——结果级置位：混合态下
   *  totals 照常来自好文件，坏文件经 suspect/suspectDetail 浮出，绝不静默。 */
  suspect?: boolean
  /** t260922-02 加性：任一文件存在词表外类型（SESSION_TWO_GEN_TYPES 之外，疑似
   *  更新代 dsh，相关内容可能缺失）——与 engine _aggregate_lane_usage 的
   *  uncovered_types 旗标/note 同构对称（KI-046），绝不静默。 */
  uncovered?: boolean
  /** 词表外类型并集（排序去重，聚合级；显示面走 uncoveredDetail 封顶）。 */
  uncoveredTypes?: string[]
  /** 命中文件的绝对路径清单（同 suspectFiles 先例）。 */
  uncoveredFiles?: string[]
  /** 人话明细（聚合级一句，类型清单 formatCappedTypes 封顶）。 */
  uncoveredDetail?: string
  /** S1 命中文件的绝对路径清单。 */
  suspectFiles?: string[]
  /** S1 逐文件人话明细（封顶 SESSION_NOTE_CAP 条）。 */
  suspectDetail?: string
}

/** timeline 的 `at`（ISO，base.py _now_iso）→ ms epoch；非法值返回 NaN 由调用方过滤。 */
export function isoToMs(at: string): number {
  return new Date(at).getTime()
}

/**
 * 从 workflow timeline（工单详情 API 透出）派生阶段窗口：
 * 取 state==='running' 的条目按时间排序，第 i 窗起点=第 i 条、终点=第 i+1 条起点
 * （不限 stage——两窗边界即阶段迁移时刻），最后一窗开放式。
 * 无 running 条目（历史单/异常数据）→ 空数组，调用方走整单加总不切段。
 */
export function stageWindowsFromTimeline(timeline: { at: string; stage: string; state: string }[] | undefined | null): StageWindow[] {
  const marks = (timeline ?? [])
    .filter(t => t.state === 'running')
    .map(t => ({ stage: t.stage, ms: isoToMs(t.at) }))
    .filter(t => Number.isFinite(t.ms))
    .sort((a, b) => a.ms - b.ms)
  return marks.map((m, i) => ({
    stage: m.stage,
    fromMs: m.ms,
    toMs: i + 1 < marks.length ? marks[i + 1]!.ms : null,
  }))
}

function windowFor(ms: number, windows: StageWindow[]): string | null {
  for (const w of windows) {
    if (ms >= w.fromMs && (w.toMs === null || ms < w.toMs)) return w.stage
  }
  return null
}

/**
 * 按工单定位**全部**候选会话文件（多角色各一份，加总口径）。
 * 与 resolveSessionFile 同一套遍历/防穿（区别：它只取最新一个，这里全取）——
 * 越界双保险 isWithin 与 refused 语义一致，防穿是验收硬项不能省。
 */
export async function resolveAllSessionFiles(
  repo: string,
  ticketId: string,
  ticket: { worktree?: string; workspace?: { type?: string; path?: string } | null; role?: string } | null,
  extraRoots: readonly string[] = [],
): Promise<{ paths?: string[]; wsRoot?: string; reason?: string; refused?: boolean; suspectFiles?: string[] }> {
  const { base, reason } = resolveAgentBaseDir(repo, ticketId, ticket, extraRoots)
  if (base === '') {
    return { refused: true, reason: reason ?? '工单工作区定位失败（拒绝读取）' }
  }
  const wsRoot = dirname(base) // base = <wsRoot>/.suyou
  const sessRoot = join(wsRoot, '.dsh', 'sessions')
  try {
    await stat(sessRoot)
  } catch {
    return { wsRoot, reason: `会话目录不存在: ${sessRoot}（agent 尚未跑过，或非泳道工作空间）` }
  }
  let slugDirs: string[] = []
  try {
    slugDirs = (await readdir(sessRoot, { withFileTypes: true }))
      .filter(e => e.isDirectory()).map(e => e.name)
  } catch (err: any) {
    return { wsRoot, reason: `会话目录读取失败: ${String(err?.message ?? err)}` }
  }
  const paths: string[] = []
  for (const slug of slugDirs) {
    let subs: string[] = []
    try {
      subs = (await readdir(join(sessRoot, slug), { withFileTypes: true }))
        .filter(e => e.isDirectory()).map(e => e.name)
    } catch { continue }
    for (const s of subs) {
      if (s !== ticketId && !s.startsWith(ticketId + '-')) continue
      // 双名发现（t260916-23 session-name-compat）：同一会话目录两代并存取 mtime 最新
      // 一份（防双代并计翻倍）；半径钉死既有两层布局内，不扩（review C2）。
      const picked = await pickNewestSessionFile(await existingSessionFilesIn(join(sessRoot, slug, s)))
      if (picked === null) continue
      // 双保险：最终落点必须在工作空间内（防穿，同 resolveSessionFile 的 isWithin）
      const wr = resolve(wsRoot)
      if (!(resolve(picked) === wr || resolve(picked).startsWith(wr + sep))) {
        return { refused: true, wsRoot, reason: `会话路径越界（拒绝读取）: ${picked}` }
      }
      paths.push(picked)
    }
  }
  if (paths.length === 0) {
    // S3（t260917-05）：发现集空 ≠ 目录空——按类点名（他票会话/旧代布局/名布局
    // 双不识=疑似 dsh 版本不匹配），绝不静默 0；目录真空才维持既有 reason。
    const base = `无本工单会话文件（${sessRoot} 下无 ${ticketId}-*/ 的会话文件 session.jsonl.zstd / session.v3.jsonl.zstd）`
    const suspects = await scanSuspectSessionFiles(sessRoot, ticketId)
    if (suspects.length > 0) {
      return {
        paths: [],
        wsRoot,
        suspectFiles: suspects.map(s => s.rel),
        reason: `${base}；发现未入统计的会话样文件：${formatSuspectGroups(suspects)}`,
      }
    }
    return { paths: [], wsRoot, reason: base }
  }
  return { paths, wsRoot }
}

/**
 * 聚合一个会话文件（只读）。解压失败/文件不存在按「跳过并记原因」处理：
 * 多角色多文件时一份坏不应毁掉整体加总（原因拼进 reason）。
 * 解析面判定（t260917-05）：S1「格式不认识」先响亮（结果级 suspect 置位+文件
 * 入 suspectFiles+返回 S1 文案），金额累加复用判定的解析结果（一次解析两用）。
 */
async function aggregateOneFile(path: string, windows: StageWindow[], out: AgentUsageResult): Promise<string | null> {
  let text: string
  try {
    text = await decompressSession(path)
  } catch (err: any) {
    return String(err instanceof SessionError ? err.message : err)
  }
  const j = judgeSessionLines(text.split('\n'))
  const s1 = sessionFaceS1Text(path, j)
  if (s1 !== null) {
    out.suspect = true
    ;(out.suspectFiles ??= []).push(path)
    return s1
  }
  // t260922-02 禁静默：词表外类型（疑似更新代 dsh）逐文件入聚合 union——
  // 加性注记，totals 照常累加（engine _aggregate_lane_usage 镜像同构，改动必须同步）。
  if (j.uncoveredCount > 0) {
    out.uncovered = true
    ;(out.uncoveredTypes ??= []).push(...j.uncoveredTypes)
    ;(out.uncoveredFiles ??= []).push(path)
  }
  // 当前模型（顺序扫描维护）；provider/model 任一缺失记 '未知'
  let cur = { provider: '', model: '' }
  let sawUsage = false
  for (const obj of j.objs) {
    const t = obj?.type
    const d = obj?.data ?? {}
    if (t === 'request/context' && d.provider !== undefined) {
      cur.provider = typeof d.provider === 'string' ? d.provider : cur.provider
      cur.model = typeof d.model === 'string' ? d.model : cur.model
    } else if (t === 'request/header') {
      const c = d.header?.config ?? {}
      if (cur.model === '' && typeof c.model === 'string') {
        cur.provider = typeof c.provider === 'string' ? c.provider : cur.provider
        cur.model = c.model
      }
    } else if (t === 'assistant/message') {
      // 注意：只加总 message 的 usage；assistant/chunk 里同名 usage 是同一份，加了会翻倍
      const u = d.usage
      if (u === null || typeof u !== 'object') continue
      sawUsage = true
      const timeMs = typeof obj.time === 'number' ? obj.time : 0
      const modelKey = (cur.provider || cur.model) ? `${cur.provider || '?'}/${cur.model || '?'}` : '未知/未知'
      // total 恒加
      add(out.total, u)
      // 模型分账
      let m = out.models.find(x => x.provider === (cur.provider || '?') && x.model === (cur.model || '?'))
      if (!m) {
        m = { provider: cur.provider || '?', model: cur.model || '?', input: 0, output: 0, cacheRead: 0 }
        out.models.push(m)
      }
      add(m, u)
      // 阶段分账（窗口外/无窗口不落段）
      if (windows.length > 0 && timeMs > 0) {
        const st = windowFor(timeMs, windows)
        if (st !== null) {
          const rec = out.byStage[st] ?? (out.byStage[st] = { input: 0, output: 0, cacheRead: 0, models: {} })
          add(rec, u)
          const ms = rec.models[modelKey] ?? (rec.models[modelKey] = { input: 0, output: 0, cacheRead: 0 })
          add(ms, u)
        }
      }
    }
  }
  // S2 兜底文案与 engine _aggregate_lane_usage 镜像同措辞（py:「会话无 usage 事件」），
  // 两侧判据/文案同构纪律（改动必须同步）。
  return sawUsage ? null : '会话无 usage 事件（agent 可能刚启动，尚无完整 assistant 消息）'
}

/**
 * 项目级 usage 账本探测缝（t260903-09 KI-017③ 前向契约）：
 * 泳道拆除后 `.dsh/sessions` 陪葬，token 维唯一存活希望=引擎侧在 merge 时刻把
 * usage 出仓到项目级账本（agent_activities.py，本票写集外——登记
 * notes/debts/known-issues.md KI-017③）。本函数只做探测：
 *   约定路径 = $SANDBAR_USAGE_LEDGER_DIR/<工单id>/*.jsonl.zstd（格式与两代会话文件
 *   session.jsonl.zstd / session.v3.jsonl.zstd 同构，复用同一聚合通路；env 亦为测试缝）。
 * 未配置/无目录/无文件 → paths=[] + 人话 reason（不静默，不做假 0）。
 */
export async function resolveLedgerSessionFiles(ticketId: string): Promise<{ paths: string[]; reason?: string }> {
  const root = process.env.SANDBAR_USAGE_LEDGER_DIR ?? ''
  if (root === '') {
    return { paths: [], reason: '泳道会话不存在，且项目级 usage 账本未配置（SANDBAR_USAGE_LEDGER_DIR 未设；KI-017③ 引擎侧出仓待落地）' }
  }
  const dir = join(root, ticketId)
  let entries: string[] = []
  try {
    entries = (await readdir(dir)).filter((f) => f.endsWith('.jsonl.zstd'))
  } catch {
    return { paths: [], reason: `项目级 usage 账本无本票目录: ${dir}（KI-017③ 出仓未覆盖本票）` }
  }
  const paths = entries.map((f) => join(dir, f))
  if (paths.length === 0) {
    return { paths: [], reason: `项目级 usage 账本无 *.jsonl.zstd: ${dir}` }
  }
  return { paths }
}

/**
 * Archived-session probe seam (t261025-14): before lane teardown, the M1-3
 * archive_ticket activity byte-copies `.dsh/sessions/**` into
 * <projects-root>/<key>/data/tickets/<id>/sessions/ (fail-closed; engine side,
 * agent_activities.py intake path 3) — the only surviving body of a closed
 * ticket's lane sessions. This function only discovers: it collects every
 * *.jsonl.zstd under that directory.
 *
 * Deliberate divergence from the lane-side resolveAllSessionFiles ("newest only
 * per leaf dir"): the archive stores each file exactly once (no dual-generation
 * naming), so taking all of them is what keeps a second role's session counted.
 * If a future refactor "unifies" this back to newest-only, the two-role case in
 * tests/t261025-14-archived-usage.mjs goes red — the divergence is pinned, not
 * accidental.
 *
 * Anti-traversal: project_key/ticket_id pass a shape whitelist first (the same
 * stance as the engine's PROJECT_KEY_RE), then a double guard keeps every final
 * path inside the archive root; any escape refuses the whole set (refused=true,
 * the consumer nulls the block). Missing dir / no files -> paths=[] + a
 * human-readable reason (never a silent zero).
 */
export async function resolveArchivedSessionFiles(
  projectsRoot: string,
  projectKey: string,
  ticketId: string,
): Promise<{ paths: string[]; reason?: string; refused?: boolean }> {
  if (projectKey === '' || !/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(projectKey)) {
    return { paths: [], refused: true, reason: `illegal project key shape (refused to read the archive): ${JSON.stringify(projectKey.slice(0, 60))}` }
  }
  if (ticketId === '' || !/^t\d+-\d+$/.test(ticketId)) {
    return { paths: [], refused: true, reason: `illegal ticket id shape (refused to read the archive): ${JSON.stringify(ticketId.slice(0, 60))}` }
  }
  const root = resolve(projectsRoot)
  const dir = join(root, projectKey, 'data', 'tickets', ticketId, 'sessions')
  try {
    await stat(dir)
  } catch {
    return { paths: [], reason: `archive has no session directory for this ticket: ${dir}` }
  }
  const paths: string[] = []
  // Recursive walk; one unreadable level only records a reason and never destroys
  // the set (good files still enter the totals, never silent).
  const reasons: string[] = []
  const walk = async (d: string): Promise<void> => {
    let entries
    try {
      entries = await readdir(d, { withFileTypes: true })
    } catch (err: any) {
      reasons.push(`dir unreadable: ${d} (${String(err?.message ?? err)})`)
      return
    }
    for (const e of entries) {
      const p = join(d, e.name)
      if (e.isDirectory()) { await walk(p); continue }
      if (e.isFile() && e.name.endsWith('.jsonl.zstd')) paths.push(p)
    }
  }
  await walk(dir)
  if (paths.some((p) => !(resolve(p) === root || resolve(p).startsWith(root + sep)))) {
    return { paths: [], refused: true, reason: `archived session path outside the projects root (refused to read): ${dir}` }
  }
  if (paths.length === 0) {
    return { paths: [], reason: `no *.jsonl.zstd in the archived session directory: ${dir}` + (reasons.length > 0 ? `; ${reasons.join('; ')}` : '') }
  }
  return { paths, ...(reasons.length > 0 ? { reason: reasons.join('; ') } : {}) }
}

/**
 * 工单 usage 聚合入口（只读）。全部会话文件加总 + 按 stage 时间窗切分。
 * 任一文件有内容即 exists:true；全部文件不可读/无 usage → exists:false + 人话 reason。
 */
export async function aggregateTicketUsage(
  paths: string[] | undefined | null,
  windows: StageWindow[],
): Promise<AgentUsageResult> {
  // 入参防呆（t260829-05）：paths 缺参/空数组不裸炸（原实现读 paths.length 会
  // TypeError），与「无会话文件」同一软降级出口（exists:false + 人话 reason）。
  if (paths === undefined || paths === null || paths.length === 0) {
    return {
      exists: false, files: 0, total: zero(), byStage: {}, models: [],
      reason: '无会话文件可聚合（resolveAllSessionFiles 未定位到会话文件 session.jsonl.zstd / session.v3.jsonl.zstd）',
    }
  }
  const out: AgentUsageResult = { exists: false, files: paths.length, total: zero(), byStage: {}, models: [] }
  const reasons: string[] = []
  for (const p of paths) {
    const why = await aggregateOneFile(p, windows, out)
    if (why !== null) reasons.push(why)
  }
  out.exists = out.total.input > 0 || out.total.output > 0 || out.total.cacheRead > 0
  if (!out.exists) {
    out.reason = reasons[0] ?? '无 usage 事件'
  } else if (reasons.length > 0) {
    // t261025-14 (archive seam, proxy-file shape): while the totals come from the
    // good files, the skipped-file reasons (decompress failure / no usage) must
    // still surface on the result — "the file exists but is undecodable" stays
    // distinguishable, never a silently dropped file. Only fills reason when it is
    // still empty (the exists path leaves reason undefined; additive, no flip).
    out.reason = reasons.slice(0, SESSION_NOTE_CAP).join('; ')
  }
  if (out.suspect) {
    // 混合态合成（t260917-05 review 意见2）：totals 可能来自好文件，S1 明细必须
    // 独立浮出——exists:true 也要能看见坏文件清单，绝不静默。
    const s1s = reasons.filter(r => r.startsWith('会话记录格式不认识'))
    out.suspectDetail = s1s.slice(0, SESSION_NOTE_CAP).join('; ')
      + (s1s.length > SESSION_NOTE_CAP ? ` (and ${s1s.length} more in total)` : '')
  }
  if (out.uncovered) {
    // t260922-02：类型并集排序去重 + 人话明细（formatCappedTypes 封顶）——
    // engine 侧 uncovered_types 旗标+note 的 TS 对称面，绝不静默。
    out.uncoveredTypes = [...new Set(out.uncoveredTypes ?? [])].sort()
    out.uncoveredDetail = `会话含本版本未覆盖的记录类型（${formatCappedTypes(out.uncoveredTypes)}）——相关内容可能缺失，疑似更新代 dsh`
  }
  out.models.sort((a, b) => (b.input + b.output) - (a.input + a.output))
  return out
}

/* ------------------------------------------------ project-level sessions (metrics v2, t261021-06) */

/**
 * Discovery result for ticket-free project sessions (metrics contract v2 block
 * `project_sessions`). `buckets` maps the session slug (executor/global/…, kept
 * verbatim) to the discovered session-file paths; `paths` is the flat union.
 */
export interface ProjectSessionRef {
  buckets: Record<string, string[]>
  paths: string[]
  /** The sessions root this discovery searched (t261026-02 shape (b): the face names where it looked). */
  searched?: string
  /** Both declared roots this discovery searched (Rule 5, t261026-05): repo root first, DSH home second. */
  searchedRoots?: string[]
  /** Human-readable degrade reason; present when nothing was found or a slug dir was unreadable. */
  reason?: string
  /** A resolved path escaped the workspace root: refuse the whole block (same discipline as resolveAllSessionFiles). */
  refused?: boolean
}

/**
 * Ticket-shaped session directory names never belong to project sessions:
 * an exact listed ticket id, or the engine ticket-id shape t<digits>-<digits>.
 */
function isTicketSessionName(name: string, listedTicketIds: readonly string[]): boolean {
  if (listedTicketIds.includes(name)) return true
  return /^t\d+-\d+/.test(name)
}

/* ---------------------------------- declared roots (metrics-token-face-delta.md Rule 5, t261026-05) */

/**
 * The DSH session home for one project: `<home>/.dsh/sessions/<repo slug>` where
 * the slug is the repo path munged the way dsh munges it ('/'-separated segments
 * joined by '-' inside '--' guards, e.g. /Users/x/a b -> --Users-x-a-b--). One
 * implementation on purpose: the metrics face's home-candidate line and this
 * reader must never drift apart.
 */
export function dshSessionHomeRoot(repoRoot: string): string {
  const slug = '--' + resolve(repoRoot).split('/').filter(Boolean).join('-') + '--'
  // SANDBAR_DSH_HOME: declared test seam (same discipline as SANDBAR_METRICS_DIR) —
  // hermetic fixtures never touch the real ~/.dsh.
  const home = process.env.SANDBAR_DSH_HOME ?? homedir()
  return join(home, '.dsh', 'sessions', slug)
}

/** One declared root: where the sessions tree sits, what a picked path must
 *  stay inside (the repo root for the repo root; the project slug dir for the
 *  DSH home — tighter than the home, per Rule 5's slug bound), and the real
 *  layout: 'slug-then-dir' = repo root, `sessions/<slug>/<sessionDir>/file`
 *  (two levels); 'dir' = DSH home, the project slug dir IS the sessions root,
 *  session dirs sit DIRECTLY under it (`<slugDir>/<sessionDir>/file`, one
 *  level — the real home layout, gen1 arbitration: one UUID dir per session). */
interface DeclaredRoot { sessRoot: string; bound: string; tag: string; layout: 'slug-then-dir' | 'dir' }

/** The two declared roots, in order: the repository root first, then the DSH
 *  session home for the project. Nothing else is ever read (Rule 5). */
function declaredSessionRoots(repoRoot: string): DeclaredRoot[] {
  const root = resolve(repoRoot)
  const homeSlug = dshSessionHomeRoot(root)
  return [
    { sessRoot: join(root, '.dsh', 'sessions'), bound: root, tag: 'repo', layout: 'slug-then-dir' },
    { sessRoot: homeSlug, bound: homeSlug, tag: 'dsh home', layout: 'dir' },
  ]
}

/** True when a listing entry is a directory — real ones directly, symlinks via a
 *  stat (a symlink to a directory must ENTER the list so the realpath containment
 *  guard can name its refusal; skipping it silently would hide the escape). */
async function isDirEntry(base: string, e: { name: string; isDirectory(): boolean; isSymbolicLink(): boolean }): Promise<boolean> {
  if (e.isDirectory()) return true
  if (!e.isSymbolicLink()) return false
  try {
    return (await stat(join(base, e.name))).isDirectory()
  } catch {
    return false // dangling symlink: nothing to read, nothing to refuse
  }
}

/** Newest session file in one session dir: the dual-name contract first
 *  (t260916-23), then — for trees written by other dsh generations — ANY
 *  `*.jsonl.zstd` file, newest mtime (gen1 arbitration, scenario F: a stale
 *  sibling never double-counts). Null when the dir holds neither. */
async function pickNewestSessionFileLoose(dir: string): Promise<string | null> {
  const canon = await existingSessionFilesIn(dir)
  if (canon.length > 0) return pickNewestSessionFile(canon)
  let best: string | null = null
  let bestMtime = -Infinity
  let entries: Awaited<ReturnType<typeof readdir>> = []
  try { entries = await readdir(dir, { withFileTypes: true }) } catch { return null }
  for (const e of entries) {
    if (!e.isFile() || !/\.jsonl\.zstd$/.test(e.name)) continue
    const fp = join(dir, e.name)
    let mtime: number
    try { mtime = (await stat(fp)).mtimeMs } catch { continue }
    if (mtime > bestMtime) { best = fp; bestMtime = mtime }
  }
  return best
}

/**
 * Walk the declared roots (read-only: readdir/stat only, never create/move/delete)
 * and pick, per kept session directory, the newest session file. One entry per
 * picked file, carrying its root/slug/session-dir so each consumer can bucket its
 * own way. Refusal, traversal and unreadable-dir handling keep the existing
 * vocabulary verbatim; an unreadable or missing root degrades with a named reason
 * and never throws.
 */
async function scanDeclaredRoots(
  roots: readonly DeclaredRoot[],
  keep: (dirName: string) => boolean,
): Promise<{ entries: Array<{ root: DeclaredRoot; slug: string; dir: string; picked: string }>; reasons: string[]; refusedReason?: string }> {
  const entries: Array<{ root: DeclaredRoot; slug: string; dir: string; picked: string }> = []
  const reasons: string[] = []
  for (const r of roots) {
    try {
      await stat(r.sessRoot)
    } catch {
      reasons.push(`${r.tag}: sessions directory does not exist: ${r.sessRoot}`)
      continue
    }
    // C3 (review_plan): containment is judged on the REAL path, not the lexical
    // one — a symlink inside the slug dir pointing at another project's slug dir
    // under the same home must refuse. Both the bound and the picked file go
    // through realpath; a path that cannot be realpath'd falls back to its
    // lexical form (same as the pre-Rule-5 guard).
    let bound = r.bound
    try { bound = await realpath(r.bound) } catch { /* lexical fallback */ }
    // Per-root layout (gen1 arbitration: the REAL home is one level — the
    // project slug dir IS the sessions root; the repo tree stays two levels —
    // `sessions/<slug>/<sessionDir>/file`. A root's own first-level dir is
    // ALSO tried as a session dir, so a shallow tree (`sessions/<dir>/file`)
    // still counts: an over-deep demand re-creates the empty-room defect the
    // other way around (KI-055 family).
    const sessionDirs: Array<{ bucket: string; dir: string; path: string }> = []
    try {
      for (const e of await readdir(r.sessRoot, { withFileTypes: true })) {
        if (!(await isDirEntry(r.sessRoot, e))) continue
        const childPath = join(r.sessRoot, e.name)
        if (r.layout === 'dir') {
          sessionDirs.push({ bucket: e.name, dir: e.name, path: childPath })
          continue
        }
        // Repo layout: the child is a potential session dir AND a slug level.
        sessionDirs.push({ bucket: e.name, dir: e.name, path: childPath })
        let subs: string[] = []
        try {
          for (const s of await readdir(childPath, { withFileTypes: true })) {
            if (await isDirEntry(childPath, s)) subs.push(s.name)
          }
        } catch (err: any) {
          reasons.push(`${r.tag}: slug ${e.name} unreadable: ${String(err?.message ?? err)}`)
          continue
        }
        for (const s of subs) sessionDirs.push({ bucket: e.name, dir: s, path: join(childPath, s) })
      }
    } catch (err: any) {
      reasons.push(`${r.tag}: sessions directory unreadable: ${r.sessRoot} (${String(err?.message ?? err)})`)
      continue
    }
    for (const sd of sessionDirs) {
      if (!keep(sd.dir)) continue
      // Readability first: an unreadable session dir is a NAMED degrade, never a
      // silent skip (the silent skip was the gen1 empty-room defect in disguise).
      try { await readdir(sd.path) } catch (err: any) {
        reasons.push(`${r.tag}: session dir ${sd.dir} unreadable: ${String(err?.message ?? err)}`)
        continue
      }
      // Bound guard at DIRECTORY level (real path): a symlinked session dir
      // pointing out of (or across slugs inside) the home is refused BY NAME
      // and skipped — path-scoped, per the gen1 gate (an honest sibling keeps
      // counting; the escaped content is never read).
      let realDir = resolve(sd.path)
      try { realDir = await realpath(sd.path) } catch { /* lexical fallback */ }
      if (!(realDir === bound || realDir.startsWith(bound + sep))) {
        reasons.push(`session path outside the workspace root (refused to read): ${sd.path}`)
        continue
      }
      const picked = await pickNewestSessionFileLoose(sd.path)
      if (picked === null) continue
      // Double guard: the REAL landing spot must stay inside ITS OWN root's
      // bound (path-traversal hard rule, same as resolveAllSessionFiles).
      let real = resolve(picked)
      try { real = await realpath(picked) } catch { /* lexical fallback */ }
      if (!(real === bound || real.startsWith(bound + sep))) {
        reasons.push(`session path outside the workspace root (refused to read): ${picked}`)
        continue
      }
      entries.push({ root: r, slug: sd.bucket, dir: sd.dir, picked })
    }
  }
  return { entries, reasons }
}

/**
 * Discover sessions under the two DECLARED roots (repo `.dsh/sessions` + the DSH
 * session home for the project, metrics-token-face-delta.md Rule 5) that carry no
 * ticket id (metrics contract v2). Read-only, bounded to the project slug under
 * the home, one newest session file per session dir, same file cap as before.
 * Same traversal and refusal discipline as resolveAllSessionFiles: a final
 * resolved path escaping its root's bound refuses the whole discovery
 * (refused=true + reason, same vocabulary) and the consumer degrades the block
 * to null + reason. Parsing is NOT done here — the caller feeds the paths into
 * aggregateTicketUsage (same parser as the per-ticket path). Malformed input
 * (missing dir, unreadable subdir, non-directory entries) degrades with a reason
 * and never throws.
 */
export async function resolveProjectSessionFiles(
  repoRoot: string,
  listedTicketIds: readonly string[] = [],
): Promise<ProjectSessionRef> {
  const out: ProjectSessionRef = { buckets: {}, paths: [] }
  const roots = declaredSessionRoots(repoRoot)
  out.searched = roots[0].sessRoot
  out.searchedRoots = roots.map(r => r.sessRoot)
  const scanned = await scanDeclaredRoots(roots, (s) => !isTicketSessionName(s, listedTicketIds))
  if (scanned.refusedReason !== undefined) {
    return { buckets: {}, paths: [], searched: out.searched, searchedRoots: out.searchedRoots, refused: true, reason: scanned.refusedReason }
  }
  for (const e of scanned.entries) {
    ;(out.buckets[e.slug] ??= []).push(e.picked)
    out.paths.push(e.picked)
  }
  const searchedNames = roots.map(r => r.sessRoot).join(' or ')
  if (out.paths.length === 0) {
    out.reason = `no ticket-free project session files under ${searchedNames}`
      + (scanned.reasons.length > 0 ? `; ${scanned.reasons.join('; ')}` : '')
  } else if (scanned.reasons.length > 0) {
    out.reason = scanned.reasons.join('; ')
  }
  return out
}

/* ------------------------------------------------ per-role ticket sessions (metrics v2 additive, t261026-02) */

/**
 * The role suffix of a lane session directory named `<ticket>-<role>` (e.g.
 * 't261025-12-developer' -> 'developer'). Returns null for any other shape.
 * Note the boundary against isTicketSessionName: `/^t\d+-\d+-(.+)$/` is
 * stricter than `/^t\d+-\d+/` — a dir like 't1-2x-old' is ticket-shaped (kept
 * out of project sessions) but carries no parseable role, and the caller must
 * name that skip rather than fold it into 'no sessions'.
 */
export function ticketRoleOf(name: string): string | null {
  const m = /^t\d+-\d+-(.+)$/.exec(name)
  return m ? m[1] : null
}

/**
 * Discovery result for per-role ticket sessions (metrics additive block
 * `role_aggregate`, t261026-02). `roles` maps the role suffix (verbatim) to
 * its discovered session-file paths and the distinct ticket ids they belong
 * to; `skips` names the ticket-shaped dirs from which no role could be parsed
 * (never silently folded into an empty role).
 */
export interface RoleSessionRef {
  roles: Record<string, { tickets: string[]; paths: string[] }>
  paths: string[]
  /** The sessions root this discovery searched (shape (b): the face names where it looked). */
  searched?: string
  /** Both declared roots this discovery searched (Rule 5, t261026-05): repo root first, DSH home second. */
  searchedRoots?: string[]
  /** Human-readable degrade reason; present when nothing was found or a slug dir was unreadable. */
  reason?: string
  /** Ticket-shaped dirs with no parseable role (named skips, review carried item). */
  skips: string[]
  /** A resolved path escaped the workspace root: refuse the whole block (same discipline as resolveProjectSessionFiles). */
  refused?: boolean
}

/**
 * Discover TICKET-SHAPED session dirs (`<ticket>-<role>`) under the two DECLARED
 * roots (repo `.dsh/sessions` + the DSH session home for the project,
 * metrics-token-face-delta.md Rule 5) — exactly the names
 * resolveProjectSessionFiles excludes, same trees, same traversal and refusal
 * discipline (a final resolved path escaping its root's bound refuses the whole
 * discovery; never throws; missing or unreadable dirs degrade with a named
 * reason). Read-only, bounded to the project slug under the home, one newest
 * session file per session dir. Parsing is NOT done here — the caller feeds the
 * paths into aggregateTicketUsage (same parser as everywhere).
 */
export async function resolveTicketRoleSessionFiles(repoRoot: string): Promise<RoleSessionRef> {
  const out: RoleSessionRef = { roles: {}, paths: [], skips: [] }
  const roots = declaredSessionRoots(repoRoot)
  out.searched = roots[0].sessRoot
  out.searchedRoots = roots.map(r => r.sessRoot)
  const scanned = await scanDeclaredRoots(roots, (s) => {
    const role = ticketRoleOf(s)
    if (role !== null) return true
    // Ticket-shaped but role-less dirs are named, never folded into an
    // empty role; non-ticket-shaped dirs belong to project sessions and
    // are out of scope here.
    if (/^t\d+-\d+/.test(s)) out.skips.push(`${s} (ticket-shaped, no role parsed)`)
    return false
  })
  if (scanned.refusedReason !== undefined) {
    return { roles: {}, paths: [], skips: out.skips, searched: out.searched, searchedRoots: out.searchedRoots, refused: true, reason: scanned.refusedReason }
  }
  for (const e of scanned.entries) {
    const role = ticketRoleOf(e.dir) ?? 'unknown'
    const ticketId = /^t\d+-\d+/.exec(e.dir)?.[0] ?? e.dir
    const bucket = (out.roles[role] ??= { tickets: [], paths: [] })
    if (!bucket.tickets.includes(ticketId)) bucket.tickets.push(ticketId)
    bucket.paths.push(e.picked)
    out.paths.push(e.picked)
  }
  const searchedNames = roots.map(r => r.sessRoot).join(' or ')
  if (out.paths.length === 0) {
    out.reason = `no ticket-shaped per-role session files under ${searchedNames}`
      + (scanned.reasons.length > 0 ? `; ${scanned.reasons.join('; ')}` : '')
  } else if (scanned.reasons.length > 0) {
    out.reason = scanned.reasons.join('; ')
  }
  return out
}
