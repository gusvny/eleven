/**
 * ticket-time-file.ts —— 「本票时刻只读文件」宿主半计算核（t260915-17，260904
 * 详情 mock 标注 D 落地：给定票面 meta + 路径 + 时刻口径 → 返回该时刻的版本内容）。
 *
 * 只读刚性（源码锁，tests 直断）：本模块对 git 的子命令字面量只允许
 * show / rev-parse / log / rev-list 四个只读动词；对 node:fs 只允许 readFile。
 * 不提供任何写路径（无 add/commit/checkout/…，fs 侧只有读原语），端点层另有
 * 非 GET 一律 405 的通道锁（node.ts file op）。
 *
 * fail-closed 铁律：settle / base 两口径的任何失败路径都**不读工作树**——
 * 回落工作树=把当前内容冒充「本票时刻」（撒谎）。唯一读工作树的是 current
 * 口径（「跳到当前版」专用，语义就是「现在」，mock D 小链）。
 *
 * 归档快照取舍（review C3）：引擎 settle 快照（_freeze_settle_snapshot）只存
 * squash_commit 指针与账目、工单归档（archive_ticket intake）只收 stage 报告/
 * 截图/会话——两者都不存文件版本内容，归档不是时刻版的内容源。本票时刻的
 * 内容唯一真源=git 对象库（main 收口提交 / 泳道分支 tip / base_ref blob），
 * 本模块直接 git show 读取，不经归档快照（快照 squash_commit 仅是指针，读了
 * 也是同一提交，不构成第二真源）。
 *
 * 收口提交定位（review C2 必改）：匹配面=**完整 commit message**（git log
 * --format=%H%x00%B%x1e），不是 subject——squash 收口 msg（agent_activities
 * _squash_merge 模板）的 lane/<id> 只在 body「来源 lane/<id>」行，subject 不含；
 * merge commit 形态 subject 才含。只取 %s 会漏掉 KI-006 之后默认形态的全部
 * squash 票（假 fail-closed）。撞库防线：branch 名整串出现+两侧边界（后随字符
 * 不得是 [0-9A-Za-z_/-]）——短 id 不命中长 id 票（lane/t260901-2 ✗
 * lane/t260901-24）、单仓 branch 不命中多仓 branch 后缀（lane/t260901-08 ✗
 * lane/t260901-08-root）。
 *
 * 口径钉死（review C1/C4/C5/N1）：
 *   - C1：settle 梯子把「在飞判定」前置——status∈{dispatched,rework} 一律人话
 *     拒绝（在飞票的泳道分支必然在场，分支存在性不可反证已收口）；分支 tip 检查
 *     仅对 settled/verified/closed 生效（真实对应面=teardown `branch -D` 失败
 *     残留分支的已收口票）。
 *   - C4：base 口径不做 path→repo 归属（背景引用开票闸只对根仓校验）——一律按
 *     根仓票面 base_ref 读；成员仓路径先显式判归属并 fail-closed「成员仓路径
 *     未登记开票基点」（逐仓基点不回写票面，诚实降级不是 bug，不修成回落）。
 *     settle 口径才走逐仓归属（成员仓路径带 <repo>/ 前缀，与 diff 面定位口径归一）。
 *   - C5：current 口径一律读项目根仓布局工作树（join(root, path)，成员仓路径
 *     天然落在 root/<repo>/…），**不依赖泳道树**——已收口票泳道已拆，在飞票的
 *     泳道树是中间产物也不承诺；读不到人话。二进制/非 UTF8（含 NUL 或解码出
 *     U+FFFD）→ 人话拒渲染——乱码冒充时刻版内容是温和版撒谎。
 *   - N1：主树道工单（lane≠worktree，branch/base_ref 恒空）的 settle 给专门
 *     人话「主树道工单无泳道提交」，不落「泳道已拆除…」的误导文案。
 *
 * 安全：git 以 argv 单参传入不加 shell；ref 先过 ref 字符校验再进 argv（防
 * `--` 选项注入）；路径过 shared 白名单（isSafeTicketFilePath）；输出字符封顶。
 * 资源终态：execFile 带 timeout 自回收，无定时器/监听/长驻句柄，任何路径
 * （正常/fail-closed/git 异常）都无遗留资源。
 */

import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { promisify } from 'node:util'
import {
  isInFlightStatus, isSafeTicketFilePath, isSettleCapableStatus,
  ticketTimeFailReason, type RefSource, type TicketTimeMode,
} from '../shared/ticket-time-model.ts'

const execFileP = promisify(execFile)

/** 单文件内容字符封顶（与 docs 读面 DOC_MAX_CHARS 同口径 2MB；超限截断+标记）。 */
export const TICKET_TIME_MAX_CHARS = 2_000_000

/** git 子进程超时与输出兜底（与 changes.ts 同口径 16MB）。 */
const GIT_TIMEOUT_MS = 10_000
const MAX_BUFFER_BYTES = 16 * 1024 * 1024

/** 收口提交定位的容器分支（与 changes.ts mergedTicketDiff 同源假设）。 */
const MAIN_BRANCH = 'main'

/** ref 字符白名单：branch/base_ref 只许 ref 形 token（防 `--` 选项与注入面）。 */
const REF_TOKEN_RE = /^[0-9A-Za-z][0-9A-Za-z._/-]*$/

function isSafeRefToken(v: unknown): v is string {
  return typeof v === 'string' && v !== '' && REF_TOKEN_RE.test(v)
}

async function gitBuf(cwd: string, args: string[]): Promise<Buffer> {
  const { stdout } = await execFileP('git', ['-C', cwd, ...args], {
    timeout: GIT_TIMEOUT_MS, maxBuffer: MAX_BUFFER_BYTES, encoding: 'buffer',
  })
  return stdout as unknown as Buffer
}

/* ---------------------------------------------------------------- 多仓条目 */

export interface RepoWorktreeEntry {
  repo: string
  name: string
  branch: string
}

/**
 * 票面 repo_worktrees 消毒（与 changes.ts sanitizeRepoWorktrees 同口径的三键
 * 子集——base_ref 键不属于本读取面，C4③：逐仓基点不回写票面，base 口径不认它）。
 * 畸形形状 → undefined（视同单仓退化，不 500）。
 */
export function sanitizeRepoWorktrees(entries: unknown): RepoWorktreeEntry[] | undefined {
  if (!Array.isArray(entries) || entries.length === 0) return undefined
  for (const e of entries) {
    if (typeof e !== 'object' || e === null) return undefined
    const it = e as Record<string, unknown>
    if (typeof it.repo !== 'string' || typeof it.name !== 'string' || typeof it.branch !== 'string') return undefined
    if (it.name === '' || it.branch === '') return undefined
    if (it.repo.includes('..') || it.repo.startsWith('/') || it.repo.startsWith('~')) return undefined
  }
  return entries as RepoWorktreeEntry[]
}

/** path 的成员仓归属（repo!=='' 的条目前缀匹配；与 diff 面顶层 files 前缀口径一致）。 */
function memberRepoOf(path: string, entries: RepoWorktreeEntry[]): RepoWorktreeEntry | undefined {
  return entries.find((e) => e.repo !== '' && (path === e.repo || path.startsWith(e.repo + '/')))
}

/* ---------------------------------------------------------------- 定位 */

/**
 * 在完整 message 文本里找 branch 名的整串出现（两侧边界：后随字符不得是
 * [0-9A-Za-z_/-]——数字防短 id 撞长 id，连字符防单仓 branch 撞多仓后缀）。
 * 返回是否命中。
 */
export function messageContainsBranch(message: string, branch: string): boolean {
  if (branch === '') return false
  let from = 0
  for (;;) {
    const at = message.indexOf(branch, from)
    if (at < 0) return false
    const before = at > 0 ? message[at - 1] : ''
    const after = message[at + branch.length] ?? ''
    const beforeOk = before === '' || !/[0-9A-Za-z_/-]/.test(before)
    const afterOk = after === '' || !/[0-9A-Za-z_/-]/.test(after)
    if (beforeOk && afterOk) return true
    from = at + 1
  }
}

/**
 * git log 记录分隔符：字段间 SOH（\x01）、记录间 RS（\x1e）——不能学 `git cat-file`
 * 用 NUL：POSIX execve 的 argv 串本身以 NUL 结尾，参数值携 NUL 会被截断（本模块
 * 全部 git 调用走 argv 单参无 shell，format 参数同样受限）。两个控制字符都不出现
 * 在正常 commit message 语义里。
 */
const LOG_FIELD_SEP = '\x01'
const LOG_REC_SEP = '\x1e'

/**
 * main 上定位本票收口提交（C2：完整 message 匹配；merge 优先、squash 兜底，
 * 与 changes.ts mergedTicketDiff 同序但换精确匹配面）。找不到返回 ''。
 * git 异常（非仓/分支缺失）同返回 ''——由调用方落 fail-closed 文案。
 */
async function findSettleCommit(cwd: string, branch: string): Promise<string> {
  for (const extra of ['--merges', '--no-merges']) {
    try {
      const out = (await gitBuf(cwd, [
        'log', '--first-parent', extra, `--format=%H${LOG_FIELD_SEP}%B${LOG_REC_SEP}`, MAIN_BRANCH,
      ])).toString('utf8')
      for (const rec of out.split(LOG_REC_SEP)) {
        const trimmed = rec.replace(/^\n+/, '')
        if (trimmed === '') continue
        const sepAt = trimmed.indexOf(LOG_FIELD_SEP)
        if (sepAt <= 0) continue
        const hash = trimmed.slice(0, sepAt)
        const message = trimmed.slice(sepAt + 1)
        if (/^[0-9a-f]{40}$/.test(hash) && messageContainsBranch(message, branch)) return hash
      }
    } catch { /* 本形态无提交/非仓——落下一形态或空 */ }
  }
  return ''
}

/* ---------------------------------------------------------------- 读取 */

export interface TicketTimeMetaInput {
  id: string
  /** 票面 status（在飞谓词与收口态判定唯一锚，C1/N2）。 */
  status: unknown
  /** 票面 lane（worktree|main|dir…；主树道专门文案，N1）。 */
  lane?: unknown
  /** 票面泳道分支（单仓定位分支；多仓走 repoWorktrees 条目）。 */
  branch?: unknown
  /** 票面开票基点（base 口径唯一 ref 源，C4①）。 */
  baseRef?: unknown
  /** 票面多仓逐仓明细（settle 归属用；base 口径不用，C4①）。 */
  repoWorktrees?: unknown
}

export interface TicketTimeReadResult {
  ok: boolean
  /** fail-closed 人话（shared 构表单源）；ok=true 时缺省。 */
  reason?: string
  content?: string
  path: string
  mode: TicketTimeMode
  /** 实际读取的 ref（branch 名 / 40 位收口提交 / base_ref）。 */
  ref?: string
  /** 短哈希展示形（横幅副文案；branch 名原样）。 */
  refShort?: string
  refSource?: RefSource
  /** 超 TICKET_TIME_MAX_CHARS 截断标记（截断不冒充完整，UI 显「已截断」）。 */
  truncated?: boolean
}

function fail(path: string, mode: TicketTimeMode, reason: string): TicketTimeReadResult {
  return { ok: false, reason, path, mode }
}

/** blob 二进制/封顶判定（C5②：NUL 或解码出 U+FFFD → 拒渲染，不冒充文本）。 */
function decodeText(buf: Buffer): { ok: true; text: string } | { ok: false; reason: string } {
  if (buf.includes(0)) return { ok: false, reason: ticketTimeFailReason('binary') }
  const text = buf.toString('utf8')
  if (text.includes('\uFFFD')) return { ok: false, reason: ticketTimeFailReason('binary') }
  return { ok: true, text }
}

/** git show <ref>:<path> 读 blob；ref 已过校验，失败按 stderr 分「路径不在/仓库异常」。
 *  kind=path 时 reason 以调用方传入的 path 生成——多仓成员仓读取用剥前缀后的
 *  仓内路径，但人话要报用户视角的原始路径，故调用方按 kind 重新构文案。 */
async function readBlobAt(cwd: string, ref: string, path: string): Promise<{ ok: true; buf: Buffer } | { ok: false; kind: 'path' | 'repo'; reason: string }> {
  try {
    return { ok: true, buf: await gitBuf(cwd, ['show', `${ref}:${path}`]) }
  } catch (err: any) {
    const stderr = String(err?.stderr ?? '')
    if (/does not exist|exists on disk, but not in|path .* does not exist/i.test(stderr)) {
      return { ok: false, kind: 'path', reason: ticketTimeFailReason('path-not-in-version', path) }
    }
    return { ok: false, kind: 'repo', reason: ticketTimeFailReason('repo-error', stderr.trim().slice(0, 160) || String(err?.message ?? err)) }
  }
}

/**
 * 「本票时刻」只读文件读取（唯一入口）。纯只读；settle/base 失败一律人话 reason，
 * 绝不回落工作树；current 是唯一读工作树的口径。
 */
export async function readTicketTimeFile(
  repoRoot: string,
  meta: TicketTimeMetaInput,
  mode: TicketTimeMode,
  path: string,
): Promise<TicketTimeReadResult> {
  if (!isSafeTicketFilePath(path)) {
    return fail(path, mode, ticketTimeFailReason('repo-error', `路径不合法（仅仓内相对路径）：${String(path).slice(0, 80)}`))
  }

  /* ── current：唯一读工作树的口径（C5① 主树布局，不依赖泳道树） ── */
  if (mode === 'current') {
    let buf: Buffer
    try {
      buf = await readFile(join(repoRoot, path)) as unknown as Buffer
    } catch {
      return fail(path, mode, ticketTimeFailReason('current-missing', path))
    }
    const dec = decodeText(buf)
    if (!dec.ok) return fail(path, mode, dec.reason)
    const truncated = dec.text.length > TICKET_TIME_MAX_CHARS
    // current 无「本票时刻」ref 语义：ref/refSource 缺省（不塞占位值冒充来源）；
    // 横幅对 current 恒 null（buildTicketTimeBanner），UI 不消费这些字段。
    return {
      ok: true, path, mode,
      content: truncated ? dec.text.slice(0, TICKET_TIME_MAX_CHARS) : dec.text,
      ...(truncated ? { truncated: true } : {}),
    }
  }

  /* ── base：开票基线版（C4①：不做归属，一律根仓票面 base_ref） ── */
  if (mode === 'base') {
    const entries = sanitizeRepoWorktrees(meta.repoWorktrees)
    if (entries !== undefined && memberRepoOf(path, entries) !== undefined) {
      return fail(path, mode, ticketTimeFailReason('member-repo-no-base'))
    }
    if (!isSafeRefToken(meta.baseRef)) {
      return fail(path, mode, ticketTimeFailReason('no-base'))
    }
    const base = meta.baseRef
    try {
      await gitBuf(repoRoot, ['rev-parse', '--verify', `${base}^{commit}`])
    } catch {
      return fail(path, mode, ticketTimeFailReason('invalid-base', base))
    }
    const r = await readBlobAt(repoRoot, base, path)
    if (!r.ok) return fail(path, mode, r.reason)
    const dec = decodeText(r.buf)
    if (!dec.ok) return fail(path, mode, dec.reason)
    const truncated = dec.text.length > TICKET_TIME_MAX_CHARS
    return {
      ok: true, path, mode, ref: base, refShort: base.slice(0, 12), refSource: 'base-ref',
      content: truncated ? dec.text.slice(0, TICKET_TIME_MAX_CHARS) : dec.text,
      ...(truncated ? { truncated: true } : {}),
    }
  }

  /* ── settle：收口版（该票的提交版本） ── */

  // C1：在飞判定前置——在飞票的泳道分支必然在场，分支存在与否不影响拒绝。
  if (isInFlightStatus(meta.status)) {
    return fail(path, mode, ticketTimeFailReason('in-flight'))
  }
  if (!isSettleCapableStatus(meta.status)) {
    return fail(path, mode, ticketTimeFailReason('bad-status', JSON.stringify(meta.status ?? null)))
  }
  // N1：主树道专门文案（lane≠worktree；branch 缺省的老票按同面处理，不误导成「泳道已拆」）。
  const laneOk = meta.lane === 'worktree' || (typeof meta.lane !== 'string' && isSafeRefToken(meta.branch))
  if (!laneOk) {
    return fail(path, mode, ticketTimeFailReason('main-lane'))
  }

  // 定位仓与分支：多仓按 path 归属成员仓（条目 branch）；根仓/单仓用票面 branch。
  // 成员仓命中时读取路径要剥掉 <repo>/ 前缀——git -C <成员仓> show 的对象路径是
  // 仓内相对路径（与 changes.ts 逐仓 files 口径一致：顶层 files 才拼前缀）。
  const entries = sanitizeRepoWorktrees(meta.repoWorktrees)
  let cwd = repoRoot
  let innerPath = path
  let branch: unknown = meta.branch
  if (entries !== undefined) {
    const member = memberRepoOf(path, entries)
    if (member !== undefined) {
      cwd = join(repoRoot, member.repo)
      innerPath = path.slice(member.repo.length + 1)
      branch = member.branch
    } else {
      const rootEntry = entries.find((e) => e.repo === '')
      if (rootEntry !== undefined) branch = rootEntry.branch
    }
  }
  if (!isSafeRefToken(branch)) {
    // 泳道分支不可得（缺登记/畸形）→ 与「拆且无收口提交」同面 fail-closed。
    return fail(path, mode, ticketTimeFailReason('lane-gone', meta.id))
  }
  const branchName = branch

  // 梯子 leg①：泳道分支仍在（settled 未合并形态；teardown branch -D 失败的残留同理）。
  let ref = ''
  let refSource: RefSource = 'branch-tip'
  try {
    await gitBuf(cwd, ['rev-parse', '--verify', `${branchName}^{commit}`])
    ref = branchName
  } catch { /* 分支不在场 → leg② */ }

  // 梯子 leg②：main 收口提交（merge 优先、squash 兜底；完整 message 精确匹配）。
  if (ref === '') {
    const commit = await findSettleCommit(cwd, branchName)
    if (commit !== '') {
      ref = commit
      // 形态标签：rev-list --parents 父数（2=merge，1=squash）——与 mergedTicketDiff 同判。
      try {
        const parents = (await gitBuf(cwd, ['rev-list', '--parents', '-1', commit])).toString('utf8').trim().split(/\s+/)
        refSource = parents.length - 1 >= 2 ? 'merge-commit' : 'squash-commit'
      } catch {
        refSource = 'squash-commit'
      }
    }
  }
  if (ref === '') {
    return fail(path, mode, ticketTimeFailReason('lane-gone', meta.id))
  }

  const r = await readBlobAt(cwd, ref, innerPath)
  if (!r.ok) {
    if (r.kind === 'path') return fail(path, mode, ticketTimeFailReason('path-not-in-version', path))
    return fail(path, mode, r.reason)
  }
  const dec = decodeText(r.buf)
  if (!dec.ok) return fail(path, mode, dec.reason)
  const truncated = dec.text.length > TICKET_TIME_MAX_CHARS
  return {
    ok: true, path, mode, ref,
    refShort: refSource === 'branch-tip' ? ref : ref.slice(0, 12),
    refSource,
    content: truncated ? dec.text.slice(0, TICKET_TIME_MAX_CHARS) : dec.text,
    ...(truncated ? { truncated: true } : {}),
  }
}
