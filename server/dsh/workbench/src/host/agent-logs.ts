/**
 * agent-logs.ts —— 工单 agent 日志查看（M12，t260822-m12 模型路由UI+agent log）的
 * 宿主半纯函数。
 *
 * 数据源：工单泳道/隔离目录下的 `.suyou/`（agent 段活动产物，路径约定真源 =
 * temporal-poc/shared.py result_file_for / agent_log_for）：
 *   agent_<stage>_gen<n>.log   —— 子 agent 的 stdout/stderr 流（agent_activities.py
 *                                追加写，含 dsh 引导期错误如 EPERM/MISSING_CREDENTIAL）；
 *   stage_<stage>_gen<n>.json  —— 段结算结果文件（{status, summary, deliverables,
 *                                files_changed, evidence}，幂等锚点）。
 *
 * 本模块做两件事（纯函数/只读，可被 smoke 直测）：
 *   A. resolveSuyouBaseDir —— 从工单字段（worktree / workspace）定 agent 日志目录：
 *      泳道工单 → <repo>/<worktree>/.suyou（路径必须在 repo 内，防穿）；
 *      主树道工单（无泳道）→ /tmp/suyou-ws/<id>/.suyou（agent 隔离目录，M4 契约）。
 *   B. listAgentLogs —— 列目录内 agent_*.log / stage_*.json（按 (stage, gen) 序），
 *      逐文件带尺寸/时间 + 内容（log 取尾部、result 解析 JSON；封顶防大文件拖垮面板）。
 *      目录不存在/无文件 → exists=false + 人话 reason（降级不抛错）。
 */

import { readFile, readdir, stat } from 'node:fs/promises'
import { join, resolve, sep, dirname } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const execFileP = promisify(execFile)

/** agent 流日志文件名：agent_<stage>_gen<整数>.log（shared.py agent_log_for）。 */
export const AGENT_LOG_RE = /^agent_([A-Za-z0-9_-]+)_gen(\d+)\.log$/
/** 段结算结果文件名：stage_<stage>_gen<整数>.json（shared.py result_file_for）。 */
export const STAGE_RESULT_RE = /^stage_([A-Za-z0-9_-]+)_gen(\d+)\.json$/

/** 单文件内容封顶（字符数）：日志取尾、结果取前，防大文件拖垮面板。 */
const MAX_LOG_CHARS = 60_000
const MAX_RESULT_CHARS = 200_000
/** 文件数封顶（每工单最多展示的 .suyou 文件数）。 */
const MAX_FILES = 60

export interface AgentLogFile {
  name: string
  kind: 'log' | 'result'
  stage: string
  gen: number
  size: number
  mtime: number
  /** log：尾部内容（超限截断，truncated=true）；result：原始 JSON 文本（超限截断）。 */
  content?: string
  contentTruncated?: boolean
  /** result 文件的解析结果（JSON 可解析时）。 */
  result?: unknown
  /** result 文件 JSON 解析失败时的原始文本首部。 */
  parseError?: string
}

export interface AgentLogsResult {
  /** 实际探测的 .suyou 目录绝对路径。 */
  base: string
  /** 目录是否存在（不存在 → files=[] + reason）。 */
  exists: boolean
  files: AgentLogFile[]
  /** 超出 MAX_FILES 的文件被略过。 */
  truncated: boolean
  /** 人话降级原因（目录不存在/无文件等），非错误。 */
  reason?: string
  /** agent 当前 session 文件大小（KB），0=尚未开始或已完成。 */
  sessionKb: number
  /** agent 当前进程是否存活（粗略判断：session 文件 mtime 在近 60s 内）。 */
  agentAlive: boolean
  /** agent 最近一次操作的人话描述（如 "读取 server/dsh/providers/.../index.tsx"）。 */
  lastActivity: string
}

function isWithin(root: string, target: string): boolean {
  const abs = resolve(root)
  const t = resolve(target)
  return t === abs || t.startsWith(abs + sep)
}

/**
 * 从工单字段定 agent 日志目录（纯函数）。返回 {base, reason?}：
 *  - worktree 非空 → <repo>/<worktree>/.suyou（必须在 repo 内，越界 → reason 拒绝）；
 *  - workspace.type=worktree 且 path 在 repo 内 → 同上（worktree 字段缺失时兜底）；
 *  - workspace.type=dir 且 path 是 /tmp/suyou-ws/ 前缀（agent 隔离目录，M4）→ path/.suyou；
 *  - 全无 → /tmp/suyou-ws/<id>/.suyou 兜底（主树道 v2 工单的默认隔离目录），附 reason 说明。
 */
export function resolveSuyouBaseDir(
  repo: string,
  ticketId: string,
  ticket: { worktree?: string; workspace?: { type?: string; path?: string } | null } | null,
): { base: string; reason?: string } {
  const ws = ticket?.workspace
  if (typeof ticket?.worktree === 'string' && ticket.worktree !== '') {
    const abs = resolve(repo, ticket.worktree)
    if (!isWithin(repo, abs)) {
      return { base: '', reason: `工单 worktree 越界（拒绝读取）: ${ticket.worktree}` }
    }
    return { base: join(abs, '.suyou') }
  }
  if (ws !== null && ws !== undefined && typeof ws?.path === 'string' && ws.path !== '') {
    if (ws.type === 'worktree' && isWithin(repo, ws.path)) {
      return { base: join(resolve(repo, ws.path), '.suyou') }
    }
    if (ws.type === 'dir' && ws.path.startsWith('/tmp/suyou-ws/')) {
      return { base: join(ws.path, '.suyou') }
    }
  }
  // 主树道工单（无泳道/无显式 workspace）：agent 默认隔离目录（shared.py WS_DIR_BASE）。
  return {
    base: join('/tmp/suyou-ws', ticketId, '.suyou'),
    reason: '主树道工单无泳道——agent 日志在 /tmp/suyou-ws/<工单id>/.suyou（若存在）',
  }
}

/** 列 .suyou 目录里的 agent 日志/段结果（只读，纯函数）。 */
export async function listAgentLogs(base: string): Promise<AgentLogsResult> {
  const result: AgentLogsResult = { base, exists: false, files: [], truncated: false, sessionKb: 0, agentAlive: false, lastActivity: '' }
  if (base === '') return result
  // session 进度探测（agent 读上下文阶段的可观测信号）
  const sessDir = join(dirname(base), '.dsh', 'sessions')
  try {
    const sessInfo = await _readSessionKb(sessDir)
    result.sessionKb = sessInfo.kb
    result.agentAlive = sessInfo.alive
    result.lastActivity = sessInfo.lastActivity
  } catch { /* .dsh 不存在=agent 尚未启动，静默 */ }
  let names: string[]
  try {
    names = await readdir(base)
  } catch (err: any) {
    if (err?.code === 'ENOENT') {
      result.reason = `目录不存在: ${base}（agent 尚未跑过，或工作空间未落 .suyou）`
      return result
    }
    result.reason = `目录读取失败: ${String(err?.message ?? err)}`
    return result
  }
  result.exists = true
  const files: AgentLogFile[] = []
  for (const name of names) {
    let m: RegExpExecArray | null
    let kind: 'log' | 'result' | null = null
    let stage = ''
    let gen = 0
    if ((m = AGENT_LOG_RE.exec(name)) !== null) {
      kind = 'log'; stage = m[1]; gen = Number(m[2])
    } else if ((m = STAGE_RESULT_RE.exec(name)) !== null) {
      kind = 'result'; stage = m[1]; gen = Number(m[2])
    }
    if (kind === null) continue
    let size = 0
    let mtime = 0
    try {
      const s = await stat(join(base, name))
      size = s.size
      mtime = Math.floor(s.mtimeMs / 1000)
    } catch { /* 读不到的跳过 */ }
    files.push({ name, kind, stage, gen, size, mtime })
  }
  // 排序：(stage, gen, kind)——同段按 gen 序、log 流在前 result 结算在后（先读现场后看结论）。
  files.sort((a, b) => {
    if (a.stage !== b.stage) return a.stage < b.stage ? -1 : 1
    if (a.gen !== b.gen) return a.gen - b.gen
    return a.kind === b.kind ? 0 : (a.kind === 'log' ? -1 : 1)
  })
  if (files.length > MAX_FILES) {
    result.truncated = true
    files.length = MAX_FILES
  }
  // 逐文件带内容（log 取尾部 / result 解析 JSON；单文件独立失败不拖垮整体）。
  const withContent: AgentLogFile[] = []
  for (const f of files) {
    const p = join(base, f.name)
    try {
      const text = await readFile(p, 'utf8')
      if (f.kind === 'log') {
        if (text.length > MAX_LOG_CHARS) {
          withContent.push({ ...f, content: text.slice(-MAX_LOG_CHARS), contentTruncated: true })
        } else {
          withContent.push({ ...f, content: text })
        }
      } else {
        if (text.length > MAX_RESULT_CHARS) {
          withContent.push({ ...f, content: text.slice(0, MAX_RESULT_CHARS), contentTruncated: true })
        } else {
          withContent.push({ ...f, content: text })
        }
        try {
          withContent[withContent.length - 1].result = JSON.parse(text)
        } catch {
          withContent[withContent.length - 1].parseError = 'JSON 解析失败（非标准结算文件？）'
        }
      }
    } catch { /* 读失败的文件只保留元信息 */ }
  }
  result.files = withContent
  if (result.files.length === 0) {
    result.reason = result.reason ?? `目录为空或无 agent 日志/段结果文件: ${base}`
  }
  return result
}

/** 扫描 .dsh/sessions/ 下最新的 session 文件，返回 KB 数、存活判定与最近操作。 */
async function _readSessionKb(sessDir: string): Promise<{ kb: number; alive: boolean; lastActivity: string }> {
  const info = await _sessionKbFast(sessDir)
  if (info.kb === 0) return { kb: 0, alive: false, lastActivity: '' }
  let lastActivity = ''
  try {
    const { stdout } = await execFileP('zstd', ['-d', '-c', info.path], { maxBuffer: 16 * 1024 * 1024, timeout: 5000 })
    const lines = stdout.split('\n')
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim()
      if (!line) continue
      try {
        const obj = JSON.parse(line)
        if (obj.type === 'tool/call') {
          const d = obj.data || {}
          lastActivity = _describeAction(d.name || '', _parseArgs(d.arguments))
          break
        }
        if (obj.type === 'assistant/message' || obj.type === 'assistant/chunk') {
          const content = typeof (obj.data || {}).content === 'string' ? (obj.data || {}).content : ''
          if (content.length > 0) {
            lastActivity = '输出中: ' + content.slice(0, 80).replace(/\n/g, ' ')
            break
          }
        }
      } catch { /* 解析失败跳过 */ }
    }
  } catch { /* zstd 解压失败 */ }
  return { ...info, lastActivity }
}

/** 轻量版：只 stat 不解压，供工单列表批量查询（每票 ~0.1ms）。
 *  布局兼容（t260825-03 修复）：dsh 现行三层布局 sessions/<cwd-slug>/<session-id>/
 *  session.jsonl.zstd（dsh-session-persistence-jsonl），旧扁平布局 sessions/<slug>/
 *  session-*.zstd 兜底——旧版扫描只认后者，dsh 升级后静默恒 0（260825 实测）。
 *  选中语义（t260825-03 返工）：按 **mtime 最新** 选中「当前活跃会话」——多角色
 *  接力泳道里旧角色会话 size 更大但已死，按 size 选会显示死会话 KB 并误报停涨
 *  （integration_review 实测：developer 1472KB 死会话挤掉 integration 457KB 活会话）。 */
export async function _sessionKbFast(sessDir: string): Promise<{ kb: number; alive: boolean; path: string }> {
  let bestKb = 0
  let bestMtime = 0
  let bestPath = ''
  const consider = async (fp: string): Promise<void> => {
    try {
      const s = await stat(fp)
      const mt = Math.floor(s.mtimeMs / 1000)
      if (mt > bestMtime) {
        bestMtime = mt
        bestKb = s.size
        bestPath = fp
      }
    } catch { /* 读不到的跳过 */ }
  }
  try {
    const ents = await readdir(sessDir, { withFileTypes: true })
    for (const e of ents) {
      if (!e.isDirectory()) continue
      const slugDir = join(sessDir, e.name)
      let subs
      try {
        subs = await readdir(slugDir, { withFileTypes: true })
      } catch { continue /* 子目录读失败跳过 */ }
      for (const f of subs) {
        // node-shims.d.ts 的 Dirent 最小面只有 isDirectory()——用 !isDirectory() 判文件
        if (!f.isDirectory() && f.name.startsWith('session-') && f.name.endsWith('.zstd')) {
          await consider(join(slugDir, f.name))  // 旧扁平布局
        } else if (f.isDirectory()) {
          await consider(join(slugDir, f.name, 'session.jsonl.zstd'))  // 现行三层布局
        }
      }
    }
  } catch { /* 目录不存在 */ }
  const now = Math.floor(Date.now() / 1000)
  return { kb: Math.floor(bestKb / 1024), alive: bestKb > 0 && (now - bestMtime) < 60, path: bestPath }
}

/** 安全解析 tool call arguments（JSON 字符串）。 */
function _parseArgs(args: string | undefined): Record<string, unknown> {
  if (typeof args !== 'string' || args === '') return {}
  try { return JSON.parse(args) as Record<string, unknown> } catch { return {} }
}

/** 将 tool call 翻译为人话（给 UI 看）。 */
function _describeAction(name: string, args: Record<string, unknown>): string {
  const fp = typeof args.file_path === 'string' ? args.file_path.split('/').slice(-3).join('/') : ''
  const desc = typeof args.description === 'string' ? args.description : ''
  switch (name) {
    case 'read': return '读取 ' + (fp || '文件')
    case 'write': return '写入 ' + (fp || '文件')
    case 'edit': return '编辑 ' + (fp || '文件')
    case 'bash': return '执行: ' + (desc || '命令')
    case 'grep': return '搜索: ' + (typeof args.pattern === 'string' ? args.pattern : '')
    case 'glob': return '查找: ' + (typeof args.pattern === 'string' ? args.pattern : '')
    case 'web_search': return '搜索网络'
    default: return name + (fp ? ' ' + fp : '')
  }
}

// t260825-03：导出给 agent-live.ts（实时动态面板）复用，函数体不动、面板行为不变。
export { _parseArgs, _describeAction }
