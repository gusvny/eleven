/**
 * agent-live.ts —— 工单「agent 实时动态」面板的宿主半（只读，t260825-03）。
 *
 * 数据源：泳道/隔离目录的 dsh 会话落盘文件（headless agent 全部消息/工具调用实时落盘，
 * agent_activities.py spawn 时 DSH_HOME=<cwd>/.dsh、DSH_HEADLESS_SESSION=<工单id>-<角色>）：
 *
 *   <工作空间根>/.dsh/sessions/<projectKey(cwd)>/<工单id>-<角色>/session.jsonl.zstd
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
import { dirname, join, resolve, sep } from 'node:path'
import { promisify } from 'node:util'
import { resolveSuyouBaseDir, _describeAction, _parseArgs } from './agent-logs.ts'

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
}

function isWithin(root: string, target: string): boolean {
  const abs = resolve(root)
  const t = resolve(target)
  return t === abs || t.startsWith(abs + sep)
}

/**
 * 按工单定会话文件（只读，防穿仿 resolveSuyouBaseDir）：
 *  1. resolveSuyouBaseDir 定工作空间根（泳道必须在 repo 内；越界 → refused）；
 *  2. sessRoot = <wsRoot>/.dsh/sessions，遍历其下 slug 目录，收集目录名以
 *     `<工单id>-` 开头（或恰等于工单 id）的会话目录里的 session.jsonl.zstd；
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
  const { base, reason } = resolveSuyouBaseDir(repo, ticketId, ticket, extraRoots)
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
      const fp = join(slugDir, s, 'session.jsonl.zstd')
      // 双保险：最终落点必须在工作空间内（ticketId 上游已过白名单，正常到不了这里）
      if (!isWithin(wsRoot, fp)) {
        return { refused: true, wsRoot, reason: `会话路径越界（拒绝读取）: ${fp}` }
      }
      try {
        const st = await stat(fp)
        cands.push({ path: fp, mtime: st.mtimeMs, exact: role !== '' && s === `${ticketId}-${role}` })
      } catch { /* 无 session.jsonl.zstd，跳过 */ }
    }
  }
  if (cands.length === 0) {
    return {
      wsRoot,
      reason: `无本工单会话文件（${sessRoot} 下无 ${ticketId}-*/session.jsonl.zstd；agent 尚未启动或角色目录未落盘）`,
    }
  }
  cands.sort((a, b) => (Number(b.exact) - Number(a.exact)) || (b.mtime - a.mtime))
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
}

/** 递归挖第一段文本（content 可能是 string / 块数组 / 嵌套 tool-result 块）。 */
function firstText(x: unknown): string {
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
 * 单条 jsonl 事件 → 面板行（不感兴趣的类型返回 null 过滤）：
 * 流式增量（assistant/chunk、text-chunks、reasoning-chunks）与大部分会话元信息
 * （session、request/*、permission/* 等）不上屏。
 *
 * KI-024（t260903-04）轮级新鲜度：step/start（每个执行轮的轮界）与 llm/retry
 * （上游限流/超时自动重试）上屏各一行——spawn 引导与首轮叙述之间的静默窗里，
 * 这两类是唯一规律的「还在干活」信号（t260903-01 实案：7 分钟空窗被误读为停摆，
 * 同期会话文件持续写入）。收敷新鲜度即可，不追求完整：step/end、
 * llm/retry-started（与 llm/retry 重复）、turn/* 等仍不上屏。
 */
function summarizeEvent(obj: any): LiveEvent | null {
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
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (line === '') continue
    let obj: any
    try { obj = JSON.parse(line) } catch { continue /* 坏行跳过（文件尾可能正在写） */ }
    const ev = summarizeEvent(obj)
    if (ev === null) continue
    interesting++
    ring.push(ev)
    if (ring.length > limit) ring.shift()
  }
  out.events = ring
  out.truncated = interesting > limit
  if (ring.length === 0) {
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
