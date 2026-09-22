/**
 * agent-live.ts —— 工单「agent 实时动态」面板的宿主半（只读，t260825-03）。
 *
 * 数据源：泳道/隔离目录的 dsh 会话落盘文件（headless agent 全部消息/工具调用实时落盘，
 * agent_activities.py spawn 时 DSH_HOME=<cwd>/.dsh、DSH_HEADLESS_SESSION=<工单id>-<角色>）：
 *
 *   <工作空间根>/.dsh/sessions/<projectKey(cwd)>/<工单id>-<角色>/{session.jsonl.zstd,session.v3.jsonl.zstd}
 *
 * 多帧拼接 zstd，整文件 `zstd -dc` 直接解（行式 JSONL 事件流；只读，严禁整文件重写）。
 * cwd-slug（projectKey）规则与 dsh 侧一致——逐行移植自
 * dsh-session-persistence-jsonl/lib/index.js 的 projectKey()/encodeSegment()（真源在 dsh 侧，
 * 这边只读消费，漂移风险见文件尾注）。
 *
 * 降级契约仿 agent-logs.ts：目录/文件不存在、zstd 不可用、解压失败、文件超大 →
 * { exists:false, reason 人话 }，不抛错；工单字段（worktree/workspace）越界 →
 * refused=true，由路由层回 4xx（验收硬性要求：../ 逃逸必须 4xx 而不是静默降级）。
 */

import { execFile } from 'node:child_process'
import { readdir, stat } from 'node:fs/promises'
import { basename, dirname, join, resolve, sep } from 'node:path'
import { promisify } from 'node:util'
import { resolveAgentBaseDir, _describeAction, _parseArgs } from './agent-logs.ts'
import { SESSION_FILE_NAMES, type SessionFileName } from './session-discovery.ts'

const execFileP = promisify(execFile)

/** 事件条数上限（query 参数 n 钳制区间 [1, MAX_EVENTS]，默认 30）。 */
export const MAX_EVENTS = 200
export const DEFAULT_EVENTS = 30
/** zstd 整解的输出封顶（会话文件随 agent 干活单调增长，封顶防爆内存；超出走 reason 降级）。 */
const ZSTD_MAX_BUFFER = 64 * 1024 * 1024
const ZSTD_TIMEOUT_MS = 10_000

/**
 * dsh 的 cwd-slug（projectKey）规则逐行移植：
 * 分隔符 / \ : 的连续串坍缩成一个 '-'；安全字符 [A-Za-z0-9._-] 原样；其余按 UTF-16
 * code unit 转义 ~XXXX（大写 4 位）；去掉前导 '-'；截断 251 字符；包成 `--<可读串>--`；
 * 全空则为 `root`。与 dsh-session-persistence-jsonl projectKey() 对齐（260825 已用
 * 本泳道真实目录名 --Users-user-Documents-suyou-.worktrees-t260825-03-- 对拍）。
 */
export function projectDirKey(cwd: string): string {
  if (cwd.length === 0) throw new Error('cannot encode an empty project path')
  let readable = ''
  let separatorRun = false
  for (let i = 0; i < cwd.length; i++) {
    const code = cwd.charCodeAt(i)
    const ch = String.fromCharCode(code)
    if (ch === '/' || ch === '\\' || ch === ':') {
      if (!separatorRun) readable += '-'
      separatorRun = true
    } else if (ch !== '~' && /^[A-Za-z0-9._-]$/.test(ch)) {
      readable += ch
      separatorRun = false
    } else {
      readable += '~' + code.toString(16).toUpperCase().padStart(4, '0')
      separatorRun = false
    }
  }
  return `--${(readable.replace(/^-+/, '') || 'root').slice(0, 251)}--`
}

export interface SessionFileRef {
  /** 定位到的会话文件绝对路径（未定位到则无）。 */
  path?: string
  /** 人话降级原因（目录不存在/无本工单会话等），非错误。 */
  reason?: string
  /** 工单字段越界（防穿拒绝）→ true，路由层回 4xx；其余降级都是 200+reason。 */
  refused?: boolean
  /** 定位到的工作空间根（诊断展示用）。 */
  wsRoot?: string
  /** 发现集空但目录内存在未入统计的会话样文件时的相对路径清单（t260917-05 S3）。 */
  suspectFiles?: string[]
}

function isWithin(root: string, target: string): boolean {
  const abs = resolve(root)
  const t = resolve(target)
  return t === abs || t.startsWith(abs + sep)
}

// ---- 会话记录解析面判据（t260917-05 会话发现面「零静默降级」；t260922-02 双代词表）----
// 真源分层：会话档格式真源在 dsh 侧（dsh-session-persistence-jsonl，仓外）；
// 事件词表的权威底册=各代 dsh 自带 GENERATED 目录 dsh-session/lib/types/
// known-event-types.js（"the event vocabulary this build understands"，t260922-02
// 实算：0.1.1=48 型 / 0.1.5=56 型 / 并集 59 / 0.1.5 独有 11 / 0.1.1 独有 3）；
// usage 键名/判据的消费面真源 = engine server/engine/agent_activities.py 的
// SESSION_USAGE_KEYS 与本组常量（两侧同构、注释互指，改动必须同步）——本组
// 定义是只读消费方的冻结镜像（KI-046 外部调用形状纪律）。两张类型集合与 engine
// SESSION_KNOWN_TYPES/SESSION_TWO_GEN_TYPES 逐项互指，双向源码锁分驻
// workbench tests/t260922-02-session-type-face.mjs（TS←py）与 engine
// tests/test_t260922_02_session_type_face.py（py←TS），防只改一边。
//
// SESSION_KNOWN_TYPES（S1 判据词表）= t260917-05 原 6 项 + 0.1.5 独有 11 项。
// 0.1.1 计数不变的可证明口径：11 项均不在 0.1.1 目录（48 型实测），0.1.1 持久化
// 面拒释目录外类型，本泳道真 0.1.1 会话直方图亦零命中——0.1.1 会话的 knownTypes
// 计数逐字不变。agent/inbox/spliced、session/title-llm-request 等 0.1.1 已识型
// **不进**本集（两代目录都在列、真会话在产，加了会改 0.1.1 计数）；它们经并集
// 进 SESSION_TWO_GEN_TYPES。
export const SESSION_KNOWN_TYPES: ReadonlySet<string> = new Set([
  // -- 现行核心（t260917-05 原集，0.1.1 行为逐字不变）--
  'request/context', 'request/header', 'assistant/message',
  'assistant/chunk', 'session', 'tool/call',
  // -- 0.1.5 独有 11 项（两代 known-event-types.js comm -13 实算）--
  'assistant/attempt', 'system/message',
  'deliverables/presented', 'feedback/message-delete', 'feedback/message-put',
  'model/selection', 'session-log-deepseek/delivery-accepted',
  'subagent/catalog', 'subagent/model-selection-policy',
  'tool/ptc-dispatch', 'tool/ptc-dispatch-start',
])

// 双代抑制超集（t260922-02「禁静默」注记的判别集，engine SESSION_TWO_GEN_TYPES
// 镜像）：解析成功、type 落在集外 → uncoveredTypes 点名（疑似更新代 dsh，内容
// 可能缺失）；集内 = 本消费面认识，不注记。机械导出公式 = 两代目录并集(59) ∪
// {session 头行标签（两代目录都不含，实测 0/0）} ∪ 0.1.1 chunk 存储行(3) =
// 63 项。只作抑制集，不进 S1 判据、不改任何既有计数；对现网健康 0.1.1 会话
// 注记恒空（真会话直方图 ⊆ 本集）。与 py 侧逐项互锁。
export const SESSION_TWO_GEN_TYPES: ReadonlySet<string> = new Set([
  // -- 0.1.1 目录全 48 项 --
  'agent-preset/selected', 'agent/inbox/spliced', 'approval/asked',
  'approval/decided', 'approval/policy', 'assistant/chunk',
  'assistant/message', 'command/done', 'command/run', 'compaction/end',
  'compaction/prune', 'compaction/start', 'compaction/summary',
  'feedback/record', 'goal/change', 'hook/invoked', 'hook/result',
  'llm/retry', 'llm/retry-started', 'permission/preset', 'plan/mode',
  'request/context', 'request/header', 'sandbox/mode', 'schedule/change',
  'session/end-seed', 'session/title', 'session/title-llm-request',
  'step/end', 'step/start', 'subagent/descriptor', 'team/member',
  'team/message/delivered', 'team/message/queued', 'team/task', 'todo/write',
  'tool-workflow/agent-end', 'tool-workflow/agent-start',
  'tool-workflow/run-end', 'tool-workflow/run-start', 'tool/call',
  'tool/code-dispatch', 'tool/code-dispatch-start', 'tool/result',
  'turn/end', 'turn/start', 'user/message', 'web/deepseek-search-llm-request',
  // -- 0.1.5 独有 11 项 --
  'assistant/attempt', 'deliverables/presented', 'feedback/message-delete',
  'feedback/message-put', 'model/selection',
  'session-log-deepseek/delivery-accepted', 'subagent/catalog',
  'subagent/model-selection-policy', 'system/message', 'tool/ptc-dispatch',
  'tool/ptc-dispatch-start',
  // -- 头行标签（两代目录外）--
  'session',
  // -- 0.1.1 chunk 存储行（目录外，chunk-rows.d.ts）--
  'text-chunks', 'reasoning-chunks', 'tool-call-chunks',
])
export const SESSION_USAGE_KEYS = ['inputTokens', 'outputTokens', 'cacheReadTokens'] as const
/** 点名清单封顶（对齐 engine SESSION_NOTE_CAP / MERGE_FILES_CAP 先例）。 */
export const SESSION_NOTE_CAP = 20

/** 类型清单 → 人话（engine _format_capped 同构：前 SESSION_NOTE_CAP 条 + 「等共 N 个」）。 */
export function formatCappedTypes(items: readonly string[]): string {
  const clean = items.filter(x => x !== '')
  if (clean.length === 0) return ''
  const tail = clean.length <= SESSION_NOTE_CAP ? '' : `（等共 ${clean.length} 个）`
  return clean.slice(0, SESSION_NOTE_CAP).join('、') + tail
}

/** 一份会话解压文本的解析面判定（engine _judge_session_lines 的 TS 同构）。 */
export interface SessionLineVerdict {
  /** 全部行皆空白（合法非 S1，与引擎检疫 blank-skip 同立场）。 */
  blank: boolean
  /** JSON 可解析且为映射对象的行数（畸形行只计数不抛）。 */
  parsed: number
  /** 命中已知事件词表的行数。 */
  knownTypes: number
  /** assistant/message 且 data.usage 为对象的条数——assistant/chunk 同名 usage 不数（防翻倍）。 */
  usageRecords: number
  /** usage 对象存在但三个已知键全缺的条数（新版本改字段名的形态）。 */
  usageWithoutKnownKeys: number
  /** 解析成功、type 为串且不在 SESSION_TWO_GEN_TYPES 的类型全集（排序去重；
   *  t260922-02 加性键——疑似更新代 dsh 的「禁静默」点名面，显示面 formatCappedTypes 封顶）。 */
  uncoveredTypes: string[]
  /** uncoveredTypes 的个数。 */
  uncoveredCount: number
  /** 可解析的映射行对象（保持原序）——聚合面金额累加复用，避免二次解析。 */
  objs: any[]
}

export function judgeSessionLines(lines: readonly unknown[]): SessionLineVerdict {
  const out: SessionLineVerdict = {
    blank: true, parsed: 0, knownTypes: 0, usageRecords: 0, usageWithoutKnownKeys: 0,
    uncoveredTypes: [], uncoveredCount: 0, objs: [],
  }
  if (!Array.isArray(lines)) return out
  const uncovered = new Set<string>()
  for (const ln of lines) {
    if (typeof ln !== 'string') continue
    const line = ln.trim()
    if (line === '') continue
    out.blank = false
    let obj: any
    try { obj = JSON.parse(line) } catch { continue }
    if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) continue
    out.parsed += 1
    out.objs.push(obj)
    const t = obj.type
    if (typeof t === 'string' && SESSION_KNOWN_TYPES.has(t)) out.knownTypes += 1
    // t260922-02：type 非串不入任何词表计数（known/uncovered 都不数），畸形不抛
    if (typeof t === 'string' && !SESSION_TWO_GEN_TYPES.has(t)) uncovered.add(t)
    if (t === 'assistant/message') {
      const u = (obj.data ?? {}).usage
      if (u !== null && typeof u === 'object' && !Array.isArray(u)) {
        out.usageRecords += 1
        if (!SESSION_USAGE_KEYS.some(k => k in u)) out.usageWithoutKnownKeys += 1
      }
    }
  }
  out.uncoveredTypes = [...uncovered].sort()
  out.uncoveredCount = out.uncoveredTypes.length
  return out
}

/**
 * 判据结果 → S1「格式不认识」响亮文案；null=非 S1（engine _session_face_s1_text 同构）。
 * 真值表三段互斥：①解压失败不入本函数（调用方既有解压失败注记路径）；②blank→null；
 * ③非 blank 且 parsed==0 / knownTypes==0 / usageWithoutKnownKeys>0 → 响亮。
 */
export function sessionFaceS1Text(name: string, j: SessionLineVerdict): string | null {
  if (j.blank) return null
  if (j.parsed === 0 || j.knownTypes === 0 || j.usageWithoutKnownKeys > 0) {
    return `会话记录格式不认识（疑似 dsh 版本不匹配），统计值不可信（文件：${name}）`
  }
  return null
}

/** S3 疑似文件分类（engine _session_suspect_unmatched 同构；review 意见3 文案分流）。 */
export type SuspectKind = 'unknown' | 'other_ticket' | 'legacy_flat'

export interface SuspectFile {
  /** 相对 sessions 根的路径。 */
  rel: string
  kind: SuspectKind
}

/** 分类标签（与 engine _SESSION_SUSPECT_KIND_LABELS 同构；序=人话呈现序）。 */
const SUSPECT_KIND_LABELS: ReadonlyArray<readonly [SuspectKind, string]> = [
  ['unknown', '名字/布局不认识（疑似 dsh 版本不匹配）'],
  ['other_ticket', '他票会话'],
  ['legacy_flat', '旧代布局'],
]

/** 分类清单 → 人话（封顶：前 SESSION_NOTE_CAP 条 + 「等共 N 个」）。 */
export function formatSuspectGroups(items: readonly SuspectFile[]): string {
  const lines: string[] = []
  for (const [kind, label] of SUSPECT_KIND_LABELS) {
    for (const it of items) {
      if (it.kind === kind) lines.push(`${label}: ${it.rel}`)
    }
  }
  if (lines.length === 0) return ''
  const tail = lines.length <= SESSION_NOTE_CAP ? '' : `（等共 ${lines.length} 个）`
  return lines.slice(0, SESSION_NOTE_CAP).join('、') + tail
}

/**
 * S3 扫描（发现集为空时调用）：sessions 树下「会话样文件但未入统计」的分类清单
 * （engine _session_suspect_unmatched 的 TS 同构，review 意见3 分类一致）：
 * - other_ticket：三层布局 <slug>/<sub>/ 会话档（session.jsonl.zstd / session.v3.jsonl.zstd 双名）且 sub 不匹配本票 tie 规则；
 * - legacy_flat：<slug>/session-*.zstd 旧扁平布局（已知旧代，不误诊）；
 * - unknown：其余「名字含 session 或后缀 .zst/.zstd」——名/布局双不识，疑似 dsh 版本不匹配。
 * 目录读取失败 → 空清单（不放大环境故障）。
 */
export async function scanSuspectSessionFiles(sessRoot: string, ticketId: string): Promise<SuspectFile[]> {
  const out: SuspectFile[] = []
  const consider = (rel: string, name: string): void => {
    const parts = rel.split('/')
    if (parts.length === 3 && SESSION_FILE_NAMES.includes(name as SessionFileName)) {
      const sub = parts[1]
      if (sub === ticketId || sub.startsWith(ticketId + '-')) return // 本票会话（正常入集路径）
      out.push({ rel, kind: 'other_ticket' })
      return
    }
    if (parts.length === 2 && name.startsWith('session-') && name.endsWith('.zstd')) {
      out.push({ rel, kind: 'legacy_flat' })
      return
    }
    const low = name.toLowerCase()
    if (low.includes('session') || low.endsWith('.zst') || low.endsWith('.zstd')) {
      out.push({ rel, kind: 'unknown' })
    }
  }
  let slugs: { name: string; isDir: boolean }[] = []
  try {
    slugs = (await readdir(sessRoot, { withFileTypes: true }))
      .map(e => ({ name: e.name, isDir: e.isDirectory() }))
  } catch {
    return out
  }
  for (const slug of slugs) {
    if (!slug.isDir) {
      consider(slug.name, slug.name) // sessions 根下散文件
      continue
    }
    let subs: { name: string; isDir: boolean }[] = []
    try {
      subs = (await readdir(join(sessRoot, slug.name), { withFileTypes: true }))
        .map(e => ({ name: e.name, isDir: e.isDirectory() }))
    } catch { continue /* 子目录读失败跳过 */ }
    for (const s of subs) {
      if (!s.isDir) {
        consider(`${slug.name}/${s.name}`, s.name)
        continue
      }
      let files: string[] = []
      try { files = await readdir(join(sessRoot, slug.name, s.name)) } catch { continue }
      for (const fn of files) consider(`${slug.name}/${s.name}/${fn}`, fn)
    }
  }
  return out
}

/**
 * 按工单定会话文件（只读，防穿仿 resolveAgentBaseDir）：
 *  1. resolveAgentBaseDir 定工作空间根（泳道必须在 repo 内；越界 → refused）；
 *  2. sessRoot = <wsRoot>/.dsh/sessions，遍历其下 slug 目录，收集目录名以
 *     `<工单id>-` 开头（或恰等于工单 id）的会话目录里的会话文件（两代名，session-discovery 单点）；
 *  3. ticket.role 非空时优先精确匹配 `<工单id>-<角色>`，否则取 mtime 最新
 *     （角色接力场景：同一工单的 developer/integration 各有一个会话目录）。
 * 目录不存在/无候选 → reason 人话降级，不抛错。
 */
export async function resolveSessionFile(
  repo: string,
  ticketId: string,
  ticket: { worktree?: string; workspace?: { type?: string; path?: string } | null; role?: string } | null,
  extraRoots: readonly string[] = [],
): Promise<SessionFileRef> {
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
  const role = typeof ticket?.role === 'string' ? ticket.role : ''
  interface Cand { path: string; mtime: number; exact: boolean }
  const cands: Cand[] = []
  for (const slug of slugDirs) {
    const slugDir = join(sessRoot, slug)
    let subs: string[] = []
    try {
      subs = (await readdir(slugDir, { withFileTypes: true }))
        .filter(e => e.isDirectory()).map(e => e.name)
    } catch { continue /* 子目录读失败跳过 */ }
    for (const s of subs) {
      if (s !== ticketId && !s.startsWith(ticketId + '-')) continue
      // 双名发现（t260916-23 session-name-compat）：两代文件名都进候选池；既有
      // exact/mtime 排序不动，同 mtime 平局旧名优先（与 py 侧 _pick_newest_session 口径一致）
      for (const name of SESSION_FILE_NAMES) {
        const fp = join(slugDir, s, name)
        // 双保险：最终落点必须在工作空间内（ticketId 上游已过白名单，正常到不了这里）
        if (!isWithin(wsRoot, fp)) {
          return { refused: true, wsRoot, reason: `会话路径越界（拒绝读取）: ${fp}` }
        }
        try {
          const st = await stat(fp)
          cands.push({ path: fp, mtime: st.mtimeMs, exact: role !== '' && s === `${ticketId}-${role}` })
        } catch { /* 无此代文件，跳过 */ }
      }
    }
  }
  if (cands.length === 0) {
    // S3（t260917-05）：发现集空 ≠ 目录空——树里有会话样文件却一个都不匹配本票
    // 名，按类点名（他票会话/旧代布局/名布局双不识=疑似 dsh 版本不匹配），不静默。
    const base = `无本工单会话文件（${sessRoot} 下无 ${ticketId}-*/ 的会话文件 session.jsonl.zstd / session.v3.jsonl.zstd；agent 尚未启动或角色目录未落盘）`
    const suspects = await scanSuspectSessionFiles(sessRoot, ticketId)
    if (suspects.length > 0) {
      return {
        wsRoot,
        suspectFiles: suspects.map(s => s.rel),
        reason: `${base}；发现未入统计的会话样文件：${formatSuspectGroups(suspects)}`,
      }
    }
    return { wsRoot, reason: base }
  }
  // 平局第三键：同 mtime 时旧代名排前（genIdx 小者在前；未知名字排最后）
  const genIdx = (p: string): number => {
    const i = SESSION_FILE_NAMES.indexOf(basename(p) as SessionFileName)
    return i < 0 ? SESSION_FILE_NAMES.length : i
  }
  cands.sort((a, b) => (Number(b.exact) - Number(a.exact)) || (b.mtime - a.mtime) || (genIdx(a.path) - genIdx(b.path)))
  return { path: cands[0].path, wsRoot }
}

/** 「实时动态」一条事件：时间（epoch 秒）、类型（user/assistant/tool/result）、摘要。 */
export interface LiveEvent {
  ts: number
  type: string
  summary: string
}

export interface AgentLiveResult {
  exists: boolean
  path?: string
  /** 会话文件大小（KB）与最近修改时间（epoch 秒）——增速/存活信号。 */
  sizeKb?: number
  mtime?: number
  events: LiveEvent[]
  /** 感兴趣事件总数超出返回条数（只回了尾部）。 */
  truncated: boolean
  /** 人话降级原因（文件不存在/解压失败/无可展示事件），非错误。 */
  reason?: string
  /** t260922-02 加性：解析成功但不在 SESSION_TWO_GEN_TYPES 的类型（排序去重，
   *  显示面 formatCappedTypes 封顶）——疑似更新代 dsh，「内容可能缺失」的显式点名，绝不静默。 */
  uncoveredTypes?: string[]
}

/** 递归挖第一段文本（content 可能是 string / 块数组 / 嵌套 tool-result 块）。
 *  t260922-02 起导出：agent-logs 的 attempt 回扫复用同一提取实现（单一真源）。 */
export function firstText(x: unknown): string {
  if (typeof x === 'string') return x
  if (Array.isArray(x)) {
    for (const b of x) {
      const s = b !== null && typeof b === 'object'
        ? firstText((b as Record<string, unknown>).text ?? (b as Record<string, unknown>).content)
        : ''
      if (s !== '') return s
    }
  }
  return ''
}

/** assistant/user 消息的整段文本（拼接所有 text 块）。 */
function allText(content: unknown): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content
      .map(b => (b !== null && typeof b === 'object' && (b as any).type === 'text')
        ? String((b as any).text ?? '')
        : '')
      .join('')
  }
  return ''
}

function cut(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

/**
 * 单条 jsonl 事件 → 面板行（不感兴趣的类型返回 null 过滤；t260922-02 起导出为
 * 测试缝——直测 0.1.5/0.1.1 分派面，端到端另有 smoke C/D/E 段兜底）：
 * 流式增量（assistant/chunk、text-chunks、reasoning-chunks——0.1.1 代独有，
 * 0.1.5 已由 assistant/message{stream} 取代）与大部分会话元信息（session、
 * request/*、permission/*、system/message 等）不上屏。
 *
 * KI-024（t260903-04）轮级新鲜度：step/start（每个执行轮的轮界）与 llm/retry
 * （上游限流/超时自动重试）上屏各一行——spawn 引导与首轮叙述之间的静默窗里，
 * 这两类是唯一规律的「还在干活」信号（t260903-01 实案：7 分钟空窗被误读为停摆，
 * 同期会话文件持续写入）。收敷新鲜度即可，不追求完整：step/end、
 * llm/retry-started（与 llm/retry 重复）、turn/* 等仍不上屏。
 *
 * t260922-02 双代处置（词表见 SESSION_KNOWN_TYPES/SESSION_TWO_GEN_TYPES）：
 * - assistant/attempt（0.1.5 独有=未转正的模型尝试：失败/重试/取消/流错误）上屏
 *   一行 attempt——0.1.5 重试/中断窗的新鲜度行（KI-024 同族收口），stream 防御性
 *   提取短预览（真样本形状 {type:'chunk',chunk:{type:'text',text}}，畸形不抛）；
 * - system/message（0.1.5 独有=渲染后的系统提示词）**有意不上屏**：元信息同
 *   request/*，词表进、分派面注释点名，测试钉死；
 * - 其余 0.1.5 独有型（deliverables/presented 等 9 项）认知级：词表进、无内容
 *   消费需求，落 default 过滤；未来未知型由 readAgentLiveTail 的 uncoveredTypes 显式点名。
 */
export function summarizeEvent(obj: any): LiveEvent | null {
  const t = obj?.type
  const tsMs = typeof obj?.time === 'number' ? obj.time
    : typeof obj?.time0 === 'number' ? obj.time0 : 0
  const ts = Math.floor(tsMs / 1000)
  const d = obj?.data ?? {}
  switch (t) {
    case 'user/message': {
      const s = allText(d.content).replace(/\s+/g, ' ').trim()
      if (s === '') return null
      return { ts, type: 'user', summary: '用户：' + cut(s, 100) }
    }
    case 'assistant/message': {
      const s = allText(d.message?.content).replace(/\s+/g, ' ').trim()
      // 纯思考/纯工具调用中转消息不上屏（工具调用本身有 tool/call 行）
      if (s === '') return null
      return { ts, type: 'assistant', summary: cut(s, 120) }
    }
    case 'assistant/attempt': {
      // t260922-02：未转正尝试行（0.1.5 独有）。data={turn,step,stream[]}；
      // stream 记录真样本形状 {type:'chunk',chunk:{type:'text',text}}——四级防御
      // 提取：chunk.text 直取（chunk 是单块对象）→ firstText(chunk)（chunk 是块
      // 数组）→ 记录本体 .text（记录自身即 text 块）→ firstText(记录本体)；畸形
      // （非数组/缺字段/非串）一律得空串只出定位文案。
      const turn = typeof d.turn === 'number' ? d.turn : null
      const step = typeof d.step === 'number' ? d.step : null
      const loc = turn !== null && step !== null ? `第 ${turn} 轮 · 第 ${step} 步 · ` : ''
      let preview = ''
      if (Array.isArray(d.stream)) {
        for (const r of d.stream) {
          const s = firstText(r?.chunk?.text) || firstText(r?.chunk)
            || firstText(r?.text) || firstText(r)
          if (s !== '') { preview = s.replace(/\s+/g, ' ').trim(); break }
        }
      }
      const body = preview !== '' ? `，输出片段：${cut(preview, 60)}` : ''
      return { ts, type: 'attempt', summary: `${loc}模型尝试未转正（重试/失败/中断）${body}` }
    }
    case 'tool/call': {
      const name = typeof d.name === 'string' ? d.name : ''
      return { ts, type: 'tool', summary: _describeAction(name, _parseArgs(d.arguments)) }
    }
    case 'tool/result': {
      const s = firstText(d.message?.content).replace(/\s+/g, ' ').trim()
      if (s === '') return null
      return { ts, type: 'result', summary: '结果：' + cut(s, 80) }
    }
    case 'step/start': {
      // 轮界行：data={turn,step}（会话第 turn 轮第 step 步）；缺字段软降级为通用文案
      const turn = typeof d.turn === 'number' ? d.turn : null
      const step = typeof d.step === 'number' ? d.step : null
      const loc = turn !== null && step !== null ? `第 ${turn} 轮 · 第 ${step} 步` : '新一轮'
      return { ts, type: 'step', summary: `${loc}开始` }
    }
    case 'llm/retry': {
      // 重试行：data.provider 给出来源（zai/deepseek…），人话点明「仍在干活」
      const provider = typeof d.provider === 'string' && d.provider !== ''
        ? `（${d.provider}）` : ''
      return { ts, type: 'retry', summary: `LLM 重试中${provider}，仍在干活` }
    }
    default:
      return null
  }
}

/** 解压/定位类失败（可降级的人话错误，区别于编程错误）。 */
export class SessionError extends Error {}

/**
 * zstd 整解会话文件（只读）。agent-live 与 agent-usage（t260828-07）共用——
 * 「同一通路两个端点」的代码级保证：定位/解压/提炼不许有第二份实现。
 * 文件不存在/zstd 不可用/解压失败/超封顶 → 抛 SessionError（message 人话，调用方降级）。
 */
export async function decompressSession(path: string): Promise<string> {
  try {
    await stat(path)
  } catch {
    throw new SessionError(`会话文件不存在: ${path}`)
  }
  try {
    const r = await execFileP('zstd', ['-d', '-c', path], {
      maxBuffer: ZSTD_MAX_BUFFER, timeout: ZSTD_TIMEOUT_MS,
    })
    return r.stdout
  } catch (err: any) {
    throw new SessionError(`会话文件解压失败（zstd 不在 PATH 或文件损坏/超 ${Math.floor(ZSTD_MAX_BUFFER / 1024 / 1024)}MB 封顶）: ${String(err?.message ?? err).slice(0, 200)}`)
  }
}

/**
 * 整解会话文件取尾部 N 条事件（只读）。n 钳制 [1, MAX_EVENTS]，缺省 DEFAULT_EVENTS。
 * 文件不存在/zstd 不可用/解压失败/超封顶 → {exists:false, reason 人话} 降级，不抛错。
 */
export async function readAgentLiveTail(path: string, n: number): Promise<AgentLiveResult> {
  const limit = Math.max(1, Math.min(MAX_EVENTS, Math.floor(n) || DEFAULT_EVENTS))
  const out: AgentLiveResult = { exists: false, events: [], truncated: false }
  let text: string
  try {
    text = await decompressSession(path)
  } catch (err: any) {
    out.reason = String(err instanceof SessionError ? err.message : err)
    return out
  }
  try {
    const st = await stat(path)
    out.sizeKb = Math.floor(st.size / 1024)
    out.mtime = Math.floor(st.mtimeMs / 1000)
  } catch { /* 解压成功后 stat 才失败：极罕见，只有事件没有大小元信息 */ }
  out.exists = true
  const ring: LiveEvent[] = []
  let interesting = 0
  const uncovered = new Set<string>()
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (line === '') continue
    let obj: any
    try { obj = JSON.parse(line) } catch { continue /* 坏行跳过（文件尾可能正在写） */ }
    // t260922-02 禁静默：词表外类型（疑似更新代 dsh）点名——与上屏分派解耦，
    // 无论是否上屏都记；健康双代会话恒空（超集覆盖两代全型），不噪声。
    const t = obj?.type
    if (typeof t === 'string' && !SESSION_TWO_GEN_TYPES.has(t)) uncovered.add(t)
    const ev = summarizeEvent(obj)
    if (ev === null) continue
    interesting++
    ring.push(ev)
    if (ring.length > limit) ring.shift()
  }
  out.events = ring
  out.truncated = interesting > limit
  if (uncovered.size > 0) {
    // 真样本/未来代守恒：有事件也点名（UI 显式提示行），零事件则并进 reason——
    // 「空白」必须带人话原因，绝不静默（t260922-02 本票存在的理由）。
    out.uncoveredTypes = [...uncovered].sort()
    if (ring.length === 0) {
      out.reason = `会话文件无可展示事件；含本版本未覆盖的记录类型（${formatCappedTypes(out.uncoveredTypes)}）——内容可能缺失，疑似更新代 dsh`
    }
  } else if (ring.length === 0) {
    out.reason = '会话文件无可展示事件（agent 可能刚启动，还在读上下文）'
  }
  return out
}

/*
 * 注（漂移风险）：cwd-slug 规则与事件 schema 的真源都在 dsh 侧
 * （dsh-session-persistence-jsonl / dsh-session），本文件是只读消费方。
 * dsh 升级若改布局/schema，这里的后果是「面板降级显示 reason」而不是报错——
 * 验收口径内的软降级路径；根治靠给定位逻辑配布局探针自测（见工单交付总结）。
 */
