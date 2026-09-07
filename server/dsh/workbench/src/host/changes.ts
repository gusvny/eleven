/**
 * changes.ts —— 工单「变更」（PR 式 change review）的宿主半计算核。
 *
 * 设计依据：docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md
 * 「审批与 change review（PR 式）」一节 + 实施波次 M9 行：
 *   - 文档变更：复用 knowledge 的渲染态 markdown block diff（diffBlocks，
 *     src/shared/blocks.ts 切块+对齐原样 import，只读复用不改 knowledge）；
 *   - 代码变更：泳道 worktree vs 工单登记的 base_ref 的文件级 diff（unified diff）；
 *   - 数据变更（app/public/data/*.json）：前后值对账（递归 JSON diff）；
 *   - 无 worktree 的主树道工单：按 write_set + git log（base..HEAD 限 write_set
 *     pathspec）给变更集，给不出就显「无变更记录」，不硬造。
 *
 * 安全：base ref 只许 ref 字符（防命令注入，git 以 argv 单参传入不加 shell）；
 * 所有 git/readFile 都锚在解析后的 worktree/仓库根内；输出量全部封顶
 * （文件数/单文件 unified 长度/对账条目数），超限带 truncated 标记。
 *
 * 本文件只在宿主半跑（node:child_process / node:fs），浏览器半不 import。
 */

import { execFile } from 'node:child_process'
import { readFile, stat } from 'node:fs/promises'
import { join, resolve, sep } from 'node:path'
import { promisify } from 'node:util'
import { diffBlocks, type BlockDiff } from '../../../knowledge/src/shared/blocks.ts'

const execFileP = promisify(execFile)

/* ---------------------------------------------------------------- 类型 */

export type FileKind = 'doc' | 'code' | 'data'
export type FileStatus = 'added' | 'removed' | 'modified'

/** 数据对账条目：一个 JSON 指针路径的前后值。 */
export interface ReconEntry {
  path: string
  kind: 'added' | 'removed' | 'changed'
  before?: string
  after?: string
}

export interface FileDiffEntry {
  path: string
  kind: FileKind
  status: FileStatus
  /** doc：block 级 diff（渲染态，增/删/改/未变 + 稳定 key）。 */
  blocks?: BlockDiff[]
  /** code：unified diff 文本（新文件为全 + 行的合成形态）。 */
  unified?: string
  unifiedTruncated?: boolean
  /** data：前后值对账。 */
  recon?: ReconEntry[]
  reconTruncated?: boolean
  /** 截断/降级标记（人话文案，UI 可见；配套 unifiedTruncated）。 */
  note?: string
  /** 新内容短哈希（file 级审批意见的 key 成分；内容变→旧意见「已过期」）。 */
  newHash: string
}

export interface TicketDiffResult {
  id: string
  base: string
  hasBase: boolean
  /** worktree=泳道道 / main=主树道（write_set+git log）/ merged=收口工单 merge commit 回放 / none=给不出变更集。 */
  source: 'worktree' | 'main' | 'merged' | 'none'
  worktree?: string
  changed: boolean
  emptyReason?: string
  files: FileDiffEntry[]
  filesTruncated: boolean
  /** 泳道道被排除的引擎运行时文件数（.dsh/ .suyou/）；主树道/无变更集时为 undefined。 */
  excludedEngineFiles?: number
}

/** 工单 JSON 里参与 diff 的字段（show 结果的子集）。 */
export interface TicketForDiff {
  id: string
  worktree?: string
  base_ref?: string
  write_set?: string[]
  /** 票所属项目 key（t260907-11 KI-057）：本函数不消费它——「判界用哪个仓根」由调用方
   *  解析（project-anchor）后作为 repo 参数传入；字段收进来只为票面形状自描述。 */
  project?: string
}

/* ---------------------------------------------------------------- 常量（输出封顶） */

const MAX_FILES = 60
const MAX_UNIFIED_CHARS = 48 * 1024
const MAX_NEW_FILE_LINES = 300
const MAX_SYNTH_CHARS = 48 * 1024
/** buildFileEntry 入口对 oldText/newText 的统一字符封顶（罩住 doc 道 diffBlocks
 *  整块全文、data 道 synthUnified、code 道、泳道道 readFile 的无界文件输入）。 */
const MAX_TEXT_CHARS = 256 * 1024
const MAX_RECON = 300
const MAX_VALUE_CHARS = 200
const GIT_TIMEOUT_MS = 30_000
/** execFile 输出兜底上限（与 metrics.ts / agent-logs.ts 同口径 16MB）：
 *  只防极端逃逸把进程打成 500，真正的界在 git 侧输出封顶与上面的字符封顶。 */
const MAX_BUFFER_BYTES = 16 * 1024 * 1024

/** base ref 白名单（同 knowledge /diff 口径；拒绝 `-` 开头防 option 注入）。 */
const BASE_RE = /^(?!-)[A-Za-z0-9._~^/-]+$/

/* ---------------------------------------------------------------- 小工具 */

/** FNV-1a 32bit 短哈希（与 blocks.ts 同款算法；knowledge 只读复用不增导出，这里自留一份）。 */
function fnv1a(s: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** 文件归类：docs 下 .md = doc；app/public/data 下 .json = data；其余 = code。 */
export function classifyPath(p: string): FileKind {
  if (/^docs\/.+\.md$/.test(p)) return 'doc'
  if (/^app\/public\/data\/.+\.json$/.test(p)) return 'data'
  return 'code'
}

/** write_set 条目 → git pathspec（剥掉尾巴上的人话备注，如「（只读复用…」）。 */
function writeSetPaths(writeSet: string[] | undefined): string[] {
  return (writeSet ?? [])
    .map(w => w.split(/[\s（(]/)[0].trim())
    .filter(w => w !== '' && !w.includes('..'))
}

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileP('git', ['-C', cwd, ...args], { timeout: GIT_TIMEOUT_MS, maxBuffer: MAX_BUFFER_BYTES })
  return stdout
}

/** git show <base>:<path>；读不到（不存在/超兜底缓冲/仓库异常）返回 null，
 *  由调用方按「base 侧 / <C> 侧」打显式降级标记——不许静默当空串。 */
async function gitShow(cwd: string, base: string, path: string): Promise<string | null> {
  try {
    return await git(cwd, ['show', `${base}:${path}`])
  } catch {
    return null
  }
}

/** 校验 base 是合法 ref 且指向一个 commit。 */
async function validBase(cwd: string, base: string): Promise<boolean> {
  if (!BASE_RE.test(base)) return false
  try {
    await git(cwd, ['rev-parse', '--verify', `${base}^{commit}`])
    return true
  } catch {
    return false
  }
}

/** git diff --name-status 解析（支持 R 行的 旧→新）。 */
function parseNameStatus(text: string): Array<{ status: 'A' | 'M' | 'D'; path: string; oldPath?: string }> {
  const out: Array<{ status: 'A' | 'M' | 'D'; path: string; oldPath?: string }> = []
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    const parts = line.split('\t')
    const code = parts[0] ?? ''
    if (code.startsWith('R') && parts.length >= 3) {
      out.push({ status: 'M', path: parts[2], oldPath: parts[1] })
    } else if ((code === 'A' || code === 'M' || code === 'D') && parts.length >= 2) {
      out.push({ status: code, path: parts[1] })
    }
  }
  return out
}

/** 引擎运行时目录前缀（与 merge_check agent_activities.py 同口径：
 *  git status --porcelain -- :!.dsh :!.suyou；changes.ts 在 committed diff 侧
 *  用 git pathspec 排除，untracked 侧用 JS 等价过滤并计数，注释互相指引）。 */
const ENGINE_EXCLUDE_PATHS = [':!.dsh', ':!.suyou']
function isEngineFile(p: string): boolean {
  return p.startsWith('.dsh/') || p.startsWith('.suyou/')
}

/* ---------------------------------------------------------------- 数据对账（JSON 递归 diff） */

function fmtValue(v: unknown): string {
  let s: string
  try {
    s = typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v)
  } catch {
    s = String(v)
  }
  if (s === undefined) s = 'undefined'
  return s.length > MAX_VALUE_CHARS ? s.slice(0, MAX_VALUE_CHARS) + '…' : s
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** 数组元素有稳定 id 就按 id 对齐（books 的 章节/书 等），否则按下标。 */
function arrayKeys(arr: unknown[]): string[] {
  const byId = arr.every(it => isPlainObject(it) && typeof it.id === 'string')
  return arr.map((it, i) => (byId ? `[${(it as Record<string, unknown>).id as string}]` : `[${i}]`))
}

function reconInto(before: unknown, after: unknown, path: string, out: ReconEntry[], state: { truncated: boolean }): void {
  if (out.length >= MAX_RECON) { state.truncated = true; return }
  if (JSON.stringify(before) === JSON.stringify(after)) return
  if (isPlainObject(before) && isPlainObject(after)) {
    const keys = new Set([...Object.keys(before), ...Object.keys(after)])
    for (const k of keys) {
      const p = path === '' ? k : `${path}.${k}`
      if (!(k in before)) out.push({ path: p, kind: 'added', after: fmtValue(after[k]) })
      else if (!(k in after)) out.push({ path: p, kind: 'removed', before: fmtValue(before[k]) })
      else reconInto(before[k], after[k], p, out, state)
      if (out.length >= MAX_RECON) { state.truncated = true; return }
    }
    return
  }
  if (Array.isArray(before) && Array.isArray(after)) {
    const bk = arrayKeys(before)
    const ak = arrayKeys(after)
    // id 对齐下两数组 key 集合可比；下标对齐直接逐位
    const keySet = new Set([...bk, ...ak])
    for (const k of keySet) {
      const bi = bk.indexOf(k)
      const ai = ak.indexOf(k)
      const p = `${path}${k}`
      if (ai < 0) out.push({ path: p, kind: 'removed', before: fmtValue(before[bi]) })
      else if (bi < 0) out.push({ path: p, kind: 'added', after: fmtValue(after[ai]) })
      else reconInto(before[bi], after[ai], p, out, state)
      if (out.length >= MAX_RECON) { state.truncated = true; return }
    }
    return
  }
  out.push({ path: path === '' ? '(root)' : path, kind: 'changed', before: fmtValue(before), after: fmtValue(after) })
}

function reconJson(oldText: string, newText: string): { recon: ReconEntry[]; truncated: boolean; parseError?: string } {
  let before: unknown
  let after: unknown
  try {
    before = JSON.parse(oldText)
  } catch (err) {
    return { recon: [], truncated: false, parseError: `旧值不是合法 JSON：${String(err instanceof Error ? err.message : err)}` }
  }
  try {
    after = JSON.parse(newText)
  } catch (err) {
    return { recon: [], truncated: false, parseError: `新值不是合法 JSON：${String(err instanceof Error ? err.message : err)}` }
  }
  const out: ReconEntry[] = []
  const state = { truncated: false }
  reconInto(before, after, '', out, state)
  return { recon: out, truncated: state.truncated }
}

/* ---------------------------------------------------------------- 单文件 diff 装配 */

async function buildFileEntry(
  gitCwd: string,
  fsRoot: string,
  base: string,
  path: string,
  status: FileStatus,
  oldPath?: string,
  /** merge 回放模式：新内容从该 ref 的 blob 读（而非工作树）——收口工单泳道已拆，
   *  且后续 merge 可能改过同文件，工作树读到的是「现在」不是「当时合入的」。 */
  newRef?: string,
): Promise<FileDiffEntry | null> {
  const kind = classifyPath(path)
  // base 侧读不到（超大 blob / 仓库异常）→ 显式标记，不静默当空串
  let oldText = ''
  let oldNote: string | undefined
  if (status !== 'added') {
    const raw = await gitShow(gitCwd, base, oldPath ?? path)
    if (raw === null) oldNote = '（base 侧内容读取失败，按空基线降级显示）'
    else oldText = raw
  }
  let newText = ''
  let newNote: string | undefined
  if (status !== 'removed') {
    if (newRef !== undefined) {
      const raw = await gitShow(gitCwd, newRef, path)
      if (raw === null) newNote = '（<C> 侧内容读取失败，diff 已降级）'
      else newText = raw
    } else {
      try {
        newText = await readFile(join(fsRoot, path), 'utf8')
      } catch {
        return null // base 后有、工作树没了（或反之竞态）→ 跳过该文件
      }
    }
  }
  // newHash 必须对全文（截断前）计算：截断后「只在尾部有差异」的两次截断会判成
  // 同哈希，file 级审批意见的「已过期」判断会漏（integration/t260902-04 case G 锁定）。
  const entry: FileDiffEntry = { path, kind, status, newHash: fnv1a(newText) }
  const notes = new Set<string>()
  if (oldNote !== undefined) notes.add(oldNote)
  if (newNote !== undefined) notes.add(newNote)
  // 输入统一字符封顶（doc/data/code/泳道 readFile 四道全罩），截断发生在哈希之后。
  if (oldText.length > MAX_TEXT_CHARS) {
    oldText = oldText.slice(0, MAX_TEXT_CHARS)
    entry.unifiedTruncated = true
    notes.add('（内容超过 256KB，已截断显示）')
  }
  if (newText.length > MAX_TEXT_CHARS) {
    newText = newText.slice(0, MAX_TEXT_CHARS)
    entry.unifiedTruncated = true
    notes.add('（内容超过 256KB，已截断显示）')
  }
  if (notes.size > 0) entry.note = [...notes].join('')
  if (kind === 'doc') {
    entry.blocks = diffBlocks(oldText, newText)
    return entry
  }
  if (kind === 'data') {
    const r = reconJson(oldText, newText)
    entry.recon = r.recon
    entry.reconTruncated = r.truncated
    if (r.parseError !== undefined) {
      // 有一侧不是合法 JSON：退化成 unified 视图，不让对账静默空。
      let text = `（JSON 解析失败，退化行级视图：${r.parseError}）\n` + synthUnified(oldText, newText)
      if (text.length > MAX_UNIFIED_CHARS) {
        text = text.slice(0, MAX_UNIFIED_CHARS)
        entry.unifiedTruncated = true
      }
      entry.kind = 'code'
      entry.unified = text
    }
    return entry
  }
  // code：tracked 走 git diff；untracked 新文件合成全 + 行
  if (status === 'added' && oldText === '') {
    const lines = newText.split('\n')
    const capped = lines.slice(0, MAX_NEW_FILE_LINES)
    let text = capped.map(l => '+' + l).join('\n')
    if (lines.length > MAX_NEW_FILE_LINES) {
      entry.unifiedTruncated = true
      notes.add('（新增文件超过 300 行，已截断显示）')
    }
    if (text.length > MAX_SYNTH_CHARS) {
      text = text.slice(0, MAX_SYNTH_CHARS)
      entry.unifiedTruncated = true
      notes.add('（内容超过 48KB，已截断显示）')
    }
    if (notes.size > 0) entry.note = [...notes].join('')
    entry.unified = text
  } else {
    let text: string
    try {
      text = await git(gitCwd, ['diff', base, ...(newRef !== undefined ? [newRef] : []), '--', path])
    } catch (err) {
      // 一级降级：--stat 摘要（输出极小不再设界）；--stat 再失败 → 二级降级只打标记。
      // 触发面=per-file diff 超 16MB 兜底缓冲/仓库异常，绝不整单 500。
      void err
      let stat: string
      try {
        stat = await git(gitCwd, ['diff', '--stat', base, ...(newRef !== undefined ? [newRef] : []), '--', path])
        text = `（diff 输出超限，已降级为 --stat 摘要）\n${stat}`
      } catch (err2) {
        const msg = String(err2 instanceof Error ? err2.message : err2).slice(0, 120)
        text = `（diff 与 --stat 均失败，内容读取失败：${msg}）`
      }
      entry.unifiedTruncated = true
      if (text.length > MAX_UNIFIED_CHARS) text = text.slice(0, MAX_UNIFIED_CHARS)
      entry.unified = text
      return entry
    }
    if (text.length > MAX_UNIFIED_CHARS) {
      text = text.slice(0, MAX_UNIFIED_CHARS)
      entry.unifiedTruncated = true
    }
    entry.unified = text
  }
  return entry
}

/** 退化行级视图（data 一侧非法 JSON 时）：简单的全删全增，不假装精细。 */
function synthUnified(oldText: string, newText: string): string {
  const oldLines = oldText === '' ? [] : oldText.split('\n').slice(0, 80)
  const newLines = newText === '' ? [] : newText.split('\n').slice(0, 80)
  return [...oldLines.map(l => '-' + l), ...newLines.map(l => '+' + l)].join('\n')
}

/* ---------------------------------------------------------------- 主入口 */

/**
 * 收口工单的变更集回放：泳道 worktree/分支在 merge 收口时已清理，但 main 上留有
 * 收口痕迹，两种形态并存（KI-006）：
 *   - 存量：merge commit（Merge branch 'lane/<id>'）；
 *   - 新形态（squash 收口）：单提交，message 含 lane/<id>。
 * 定位后 diff base..<C>（限 write_set pathspec，没有 write_set 就全量），新内容从
 * <C> 的 blob 读而不是工作树——后续合并可能已改过同文件，工作树读到的是「现在」
 * 不是「当时合入的」。base 按父提交数判别：2 父 = merge commit 取 ^1，1 父 =
 * squash 提交取 ~1。
 * 已知缺陷（存量，留档不修）：--grep 是子串匹配，短 id 会命中长 id 的 message。
 */
async function mergedTicketDiff(repo: string, ticket: TicketForDiff): Promise<TicketDiffResult> {
  const id = ticket.id
  const worktree = (ticket.worktree ?? '').trim()
  const none = (reason: string): TicketDiffResult => ({
    id, base: (ticket.base_ref ?? '').trim(), hasBase: false, source: 'none',
    worktree: worktree !== '' ? worktree : undefined,
    changed: false, files: [], filesTruncated: false, emptyReason: reason,
  })
  // 两段定位互斥：存量 merge commit；否则新 squash 单提交（--no-merges 语义更纯）
  let commit = ''
  let parents = 0
  try {
    const out = await git(repo, ['log', '--first-parent', '--merges', '--grep', `lane/${id}`, '--format=%H', 'main'])
    commit = out.split('\n').map(l => l.trim()).filter(l => l !== '')[0] ?? ''
    if (commit === '') {
      const out2 = await git(repo, ['log', '--first-parent', '--no-merges', '--grep', `lane/${id}`, '--format=%H', 'main'])
      commit = out2.split('\n').map(l => l.trim()).filter(l => l !== '')[0] ?? ''
    }
    if (commit !== '') {
      // rev-list --parents -1 输出：第 1 段=commit 自身，其后=父提交；段数-1=父数
      parents = (await git(repo, ['rev-list', '--parents', '-1', commit])).trim().split(/\s+/).length - 1
    }
  } catch { /* git 失败落 none */ }
  if (commit === '' || !(await validBase(repo, commit))) {
    return none(`泳道 worktree 已拆除，且 main 上找不到 lane/${id} 的 merge commit 或 squash 收口提交（未合并？）：${worktree}`)
  }
  const base = parents === 2 ? `${commit}^1` : `${commit}~1`
  const paths = writeSetPaths(ticket.write_set)
  const ns = parseNameStatus(await git(repo, ['diff', '--name-status', '-M', `${base}..${commit}`, '--', ...paths]))
  const capped = ns.slice(0, MAX_FILES)
  const files: FileDiffEntry[] = []
  for (const f of capped) {
    const e = await buildFileEntry(repo, repo, base, f.path,
      f.status === 'A' ? 'added' : f.status === 'D' ? 'removed' : 'modified', f.oldPath, commit)
    if (e !== null) files.push(e)
  }
  return {
    id, base: commit, hasBase: true, source: 'merged',
    worktree: worktree !== '' ? worktree : undefined,
    changed: files.length > 0,
    emptyReason: files.length === 0 ? '收口提交在 write_set 范围内无文件差异（write_set 与实合入不符？）' : undefined,
    files, filesTruncated: ns.length > MAX_FILES,
  }
}

/**
 * 算一张工单的变更集。纯只读（git diff/show/status + readFile）。
 * 泳道道：worktree 工作树（含未提交）vs base_ref；untracked 新文件并入。
 * 主树道：base_ref..HEAD 限 write_set pathspec。两头都给不出 → source=none。
 */
export async function computeTicketDiff(repo: string, ticket: TicketForDiff): Promise<TicketDiffResult> {
  const id = ticket.id
  const base0 = (ticket.base_ref ?? '').trim()
  const worktree = (ticket.worktree ?? '').trim()

  if (worktree !== '') {
    const wtAbs = resolve(repo, worktree)
    if (wtAbs !== repo && !wtAbs.startsWith(repo + sep)) {
      return { id, base: base0, hasBase: false, source: 'none', changed: false, files: [], filesTruncated: false, emptyReason: `worktree 越出仓库根：${worktree}` }
    }
    try {
      const st = await stat(wtAbs)
      if (!st.isDirectory()) throw new Error('not dir')
    } catch {
      // 泳道已拆（merge 收口清理会删 worktree + 分支）——回放 main 上的收口痕迹（merge commit / squash 提交）
      return mergedTicketDiff(repo, ticket)
    }
    // base 缺省回退 merge-base(HEAD, main)；都没有就老实报「定不了基线」。
    let base = base0
    if (base === '') {
      try {
        base = (await git(wtAbs, ['merge-base', 'HEAD', 'main'])).trim()
      } catch {
        base = ''
      }
    }
    if (base === '' || !(await validBase(wtAbs, base))) {
      return { id, base, hasBase: false, source: 'worktree', worktree, changed: false, files: [], filesTruncated: false, emptyReason: `base ref 无效或定不了基线：${base0 || '（工单未登记 base_ref，merge-base 也失败）'}` }
    }
    // committed diff：git pathspec 排除引擎运行时目录（与 merge_check 同口径）
    const committedRaw = parseNameStatus(await git(wtAbs, ['diff', '--name-status', '-M', base, '--', ...ENGINE_EXCLUDE_PATHS]))
    // JS 双保险：再滤一遍 .dsh/ .suyou/（防止 git pathspec 在极端情况漏过）
    const committed = committedRaw.filter(c => !isEngineFile(c.path))

    // untracked：全量枚举后 JS 过滤并计数排除量（等价于 git ls-files --others -- :!.dsh :!.suyou）
    const untrackedRaw = await git(wtAbs, ['ls-files', '--others', '--exclude-standard'])
    const untrackedAll = untrackedRaw.split('\n').map(s => s.trim()).filter(s => s !== '')
    const engineFiles = untrackedAll.filter(p => isEngineFile(p))
    const excludedEngineFiles = engineFiles.length
    const seen = new Set(committed.map(c => c.path))
    const untracked = untrackedAll.filter(s => !seen.has(s) && !isEngineFile(s))
    const all = [
      ...committed.map(c => ({ status: (c.status === 'A' ? 'added' : c.status === 'D' ? 'removed' : 'modified') as FileStatus, path: c.path, oldPath: c.oldPath })),
      ...untracked.map(p => ({ status: 'added' as FileStatus, path: p, oldPath: undefined })),
    ]
    const capped = all.slice(0, MAX_FILES)
    const files: FileDiffEntry[] = []
    for (const f of capped) {
      const e = await buildFileEntry(wtAbs, wtAbs, base, f.path, f.status, f.oldPath)
      if (e !== null) files.push(e)
    }
    return {
      id, base, hasBase: true, source: 'worktree', worktree,
      changed: files.length > 0,
      emptyReason: files.length === 0 ? `泳道相对 base ${base.slice(0, 12)} 无变更` : undefined,
      files, filesTruncated: all.length > MAX_FILES,
      excludedEngineFiles: excludedEngineFiles > 0 ? excludedEngineFiles : undefined,
    }
  }

  // 主树道：write_set + git log（base..HEAD 限 pathspec）
  const paths = writeSetPaths(ticket.write_set)
  if (base0 === '' || paths.length === 0) {
    return {
      id, base: base0, hasBase: base0 !== '', source: 'none', changed: false, files: [], filesTruncated: false,
      emptyReason: '无变更记录（工单无泳道 worktree，且缺 base_ref 或 write_set 可对账）',
    }
  }
  if (!(await validBase(repo, base0))) {
    return { id, base: base0, hasBase: false, source: 'main', changed: false, files: [], filesTruncated: false, emptyReason: `base ref 无效：${base0}` }
  }
  const ns = parseNameStatus(await git(repo, ['diff', '--name-status', '-M', `${base0}..HEAD`, '--', ...paths]))
  const capped = ns.slice(0, MAX_FILES)
  const files: FileDiffEntry[] = []
  for (const f of capped) {
    const e = await buildFileEntry(repo, repo, base0, f.path,
      f.status === 'A' ? 'added' : f.status === 'D' ? 'removed' : 'modified', f.oldPath)
    if (e !== null) files.push(e)
  }
  return {
    id, base: base0, hasBase: true, source: 'main',
    changed: files.length > 0,
    emptyReason: files.length === 0 ? '无变更记录（write_set 范围内相对 base 无 git 变更）' : undefined,
    files, filesTruncated: ns.length > MAX_FILES,
  }
}
