/**
 * question-bridge.ts —— 问题桥（t261001-23，KI-181）：把会话级 ask_user_question
 * 镜像进面板请求账，让「问」有一条人到得了的交付面。
 *
 * 根因（KI-181 活体实证，261001 夜）：执行器会话调 ask_user_question 后自锁——
 * dsh 的问答面（dsh-user-questions 瀑布）把请求投给 Agent 作用域的应答者瀑布，
 * 本部署没有连任何 UI 应答者 ⇒ 问题无处可去：面板 Requests 0 行、会话静默 13+ 分钟。
 * 而面板本来就有通道：POST /sandbar-executor-panel/api/requests → requests.ts::appendRequest。
 * 缺的是线：本模块在宿主侧挂一只 `user-questions/request` 瀑布监听者——
 *   ① 先镜像：问题原样追加进请求账（kind='question'，raised_by=发起会话 id），
 *     人立刻能在 Requests tab 看见并经 POST /api/requests/answer 应答；
 *   ② 再并行等两路答案：账上有 answer 行（人答了）→ 映射回 AskUserQuestionAnswer
 *     返回，会话解锁；下游瀑布（真 UI）先答 → 原样透传并补一条 answer 行（账是审计真源）；
 *   ③ 下游显式 NO_PROVIDER（无 UI 应答者）→ 不再抛错砸会话，继续等账上应答
 *     （这正是修复点：等一个答得了的人，而不是等一个不存在的人）；
 *   ④ abort（会话被取消/超时）→ 立即收口，所有定时器/监听全终态回收。
 *
 * 纪律：io 全注入（测试零真实 ~/.sandbar）；不冒充答案、不自动应答——应答只能
 * 由人经应答面追加；镜像失败显式点名（onEvent 留痕）并降级为透传下游，绝不静默。
 */

import { appendRequest, answerRequest, readRequests, fsLedgerIo, type LedgerIo } from './requests.ts'
import { PROJECT_KEY_RE } from './project-key.ts'
import { projectsRoot } from '../../../watchdog/src/host/config.ts'

/** 与 dsh-user-questions 请求形状一致的最小结构面（UT 直接造字面量，不 import 宿主包）。 */
export interface AskQuestionLike {
  readonly id?: unknown
  readonly question?: unknown
  readonly detail?: unknown
  readonly options?: unknown
  readonly multiSelect?: unknown
}

export interface AskRequestLike {
  readonly questions?: unknown
  readonly agent?: { readonly id?: unknown; readonly cwd?: unknown } | null
  readonly signal?: AbortSignal | null
}

export type AskAnswerItem = { id: string; selected: string[]; custom?: string }
export type AskAnswer = { answers: AskAnswerItem[] }

export type NextFn = () => Promise<AskAnswer>

export interface BridgeEvent {
  at: number
  kind: 'mirrored' | 'mirror-refused' | 'mirror-failed' | 'answered-by-ledger' | 'answered-downstream' | 'downstream-refused' | 'aborted' | 'malformed-request'
  detail: string
}

export interface BridgeDeps {
  io?: LedgerIo
  env?: NodeJS.ProcessEnv
  now?: () => number
  /** 项目解析面（node.ts 传注册表反查版；测试注入桩）。null/报错 = 解析不出 ⇒ 降级透传。 */
  resolveProject?: (request: AskRequestLike) => { ok: true; project: string } | { ok: false; error: string }
  /** 账上应答轮询间隔（ms；测试调小）。 */
  pollMs?: number
  /** 轮询兜底上限（ms；防孤儿等待，默认 24h）。 */
  deadlineMs?: number
  /** 事件留痕（node.ts 接 ctx.logger；测试收集观测）。 */
  onEvent?: (ev: BridgeEvent) => void
}

// ── 请求校验与镜像 ─────────────────────────────────────────────────────────────

/** 请求形状校验（fail-closed）：questions 必须是非空数组，每问 question 非空字符串。 */
export function validateAskRequest(request: AskRequestLike): { ok: true } | { ok: false; error: string } {
  const qs = (request as { questions?: unknown }).questions
  if (!Array.isArray(qs) || qs.length === 0) {
    return { ok: false, error: 'request.questions 必须是非空数组——不是本桥的形状，透传下游' }
  }
  for (let i = 0; i < qs.length; i++) {
    const q = qs[i] as AskQuestionLike
    if (typeof q?.question !== 'string' || q.question.trim() === '') {
      return { ok: false, error: `questions[${i}].question 必须是非空字符串` }
    }
  }
  return { ok: true }
}

/** 镜像文本：question=第一问；detail=逐问编号拼装（含各问 detail）。 */
export function askRequestText(request: AskRequestLike): { question: string; detail: string } {
  const qs = request.questions as AskQuestionLike[]
  const detail = qs
    .map((q, i) => `${i + 1}. ${q.question}${typeof q.detail === 'string' && q.detail !== '' ? ` —— ${q.detail}` : ''}`)
    .join('\n')
  return { question: String(qs[0].question), detail }
}

/** 镜像一次：追加一条请求账行（kind='question'，raised_by=发起会话 id）。
 *  形状校验不过 = ok:false（调用方透传下游并留痕）；绝不写畸形行进账。 */
export function mirrorToLedger(
  io: LedgerIo, env: NodeJS.ProcessEnv, project: string, request: AskRequestLike, nowMs: number,
): { ok: true; row: { id: string } } | { ok: false; error: string } {
  const v = validateAskRequest(request)
  if (!v.ok) return v
  const raised = request.agent && typeof request.agent.id === 'string' ? request.agent.id : ''
  if (raised !== '' && (typeof raised !== 'string' || raised.trim() === '' || raised.length > 120)) {
    return { ok: false, error: `agent.id 形状不合法（须 ≤120 字符非空）：${JSON.stringify(raised).slice(0, 60)}` } // LIST-CAP-OK: error-message preview truncation, not a list cap
  }
  const text = askRequestText(request)
  const res = appendRequest(io, env, project, {
    kind: 'question', question: text.question, detail: text.detail, raised_by: raised || undefined,
  }, nowMs)
  if (!res.ok) return res
  return { ok: true, row: { id: res.row.id } }
}

// ── 应答映射 ──────────────────────────────────────────────────────────────────

/** 账上的自由文本应答 → AskUserQuestionAnswer：
 *  按行拆；整行恰等于某问某 option.label 的行进 selected；其余文本（custom）落在
 *  第一问「没有命中任何 option」的问上（没有则落在第一问）——一份自由文本只归属一处，
 *  不往每问都复制。UI 侧约定：answer 写 option 原文=选它；写别的=自定义答复。 */
export function mapLedgerAnswer(request: AskRequestLike, answerText: string): AskAnswer {
  const qs = (request.questions ?? []) as AskQuestionLike[]
  const lines = answerText.split('\n').map(l => l.trim()).filter(l => l !== '')
  const per = qs.map((q, i) => {
    const id = typeof q.id === 'string' ? q.id : `q${i}`
    const labels: string[] = Array.isArray(q.options)
      ? (q.options as Array<{ label?: unknown }>).map(o => (typeof o?.label === 'string' ? o.label : '')).filter(Boolean)
      : []
    return { id, labels, selected: lines.filter(l => labels.includes(l)) }
  })
  const customLines = lines.filter(l => !per.some(p => p.labels.includes(l)))
  const customJoined = customLines.join('\n')
  if (customJoined !== '') {
    let target = per.findIndex(p => p.selected.length === 0)
    if (target < 0) target = 0
    per[target].custom = customJoined
  }
  return { answers: per.map(({ id, selected, custom }) => (custom === undefined ? { id, selected } : { id, selected, custom })) }
}

// ── 账上应答等待 ───────────────────────────────────────────────────────────────

export type LedgerWaitOutcome =
  | { state: 'answered'; answer: string }
  | { state: 'aborted' }
  | { state: 'deadline'; error: string }

/** 等账上出现对 requestId 的 answer 行。全终态：应答/abort/deadline 三条路都清掉
 *  定时器与 abort 监听，绝不悬挂。坏账行=显式计数（readRequests 内建），不崩轮询。 */
export function waitForLedgerAnswer(deps: {
  io: LedgerIo
  env: NodeJS.ProcessEnv
  project: string
  requestId: string
  signal?: AbortSignal | null
  pollMs: number
  deadlineMs: number
  now: () => number
}): Promise<LedgerWaitOutcome> {
  const { io, env, project, requestId, signal, pollMs, deadlineMs, now } = deps
  let cancelExternal: (() => void) | null = null
  const promise = new Promise<LedgerWaitOutcome>((resolve) => {
    let timer: NodeJS.Timeout | null = null
    let settled = false
    const onAbort = () => finish({ state: 'aborted' })
    const deadlineAt = now() + deadlineMs
    function finish(out: LedgerWaitOutcome): void {
      if (settled) return
      settled = true
      if (timer !== null) { clearTimeout(timer); timer = null }
      signal?.removeEventListener('abort', onAbort)
      cancelExternal = null
      resolve(out)
    }
    if (signal?.aborted) { finish({ state: 'aborted' }); return }
    signal?.addEventListener('abort', onAbort, { once: true })
    const poll = (): void => {
      if (settled) return
      if (now() >= deadlineAt) { finish({ state: 'deadline', error: `等待账上应答超过 ${Math.round(deadlineMs / 1000)}s（请求 ${requestId}）——收口，不悬挂` }); return }
      let read
      try {
        read = readRequests(io, env, project)
      } catch {
        // 读账瞬断（io 抛错）：按未应答继续轮询，绝不把 io 错误冒充成 abort 或应答。
        timer = setTimeout(poll, pollMs)
        return
      }
      const row = read.rows.find(r => r.id === requestId)
      if (row && row.status === 'answered') { finish({ state: 'answered', answer: row.answer ?? '' }); return }
      timer = setTimeout(poll, pollMs)
    }
    poll()
    // 显式取消把手：持有方（question-bridge）在另一路先定胜负时立刻收掉等待面
    // （定时器 + abort 监听），不等 deadline——全终态不靠进程退出兜底。
    cancelExternal = () => finish({ state: 'aborted' })
  })
  ;(promise as Promise<LedgerWaitOutcome> & { cancel?: () => void }).cancel = () => cancelExternal?.()
  return promise as Promise<LedgerWaitOutcome> & { cancel?: () => void }
}

// ── 项目反查（cwd → project key）────────────────────────────────────────────

/** 注册表反查纯核：projects 键清单 + 每键 dirs 读面 + 会话 cwd → 命中键。
 *  cwd 恰等于某 dir 或在其前缀下都算命中（执行器可能在子目录里）。 */
export function projectKeyForCwd(
  projects: readonly string[],
  readDirs: (key: string) => readonly string[] | null,
  cwd: string,
): { ok: true; project: string } | { ok: false; error: string } {
  if (typeof cwd !== 'string' || cwd === '') return { ok: false, error: 'agent.cwd 缺席——解析不出项目' }
  for (const key of projects) {
    if (!PROJECT_KEY_RE.test(key)) continue
    const dirs = readDirs(key)
    if (dirs === null) continue
    for (const d of dirs) {
      if (d !== '' && (cwd === d || cwd.startsWith(d.endsWith('/') ? d : d + '/'))) {
        return { ok: true, project: key }
      }
    }
  }
  return { ok: false, error: `注册表里没有项目声明目录覆盖 cwd：${cwd}` }
}

// ── 瀑布监听者 ────────────────────────────────────────────────────────────────

/** 造一只 `user-questions/request` 瀑布监听者（node.ts 用 ctx.on 挂宿主根）。
 *  返回的函数签名与 dsh api-remotes 转发者同款：(request, next) => answer。
 *  路径全收口：镜像成功前任何失败都降级为透传 next()（绝不把会话砸在我们手里）。 */
export function createQuestionBridge(deps: BridgeDeps = {}): (request: AskRequestLike, next: NextFn) => Promise<AskAnswer> {
  const io = deps.io ?? fsLedgerIo
  const env = deps.env ?? process.env
  const now = deps.now ?? Date.now
  const pollMs = deps.pollMs ?? 2_000
  const deadlineMs = deps.deadlineMs ?? 24 * 3600_000
  const onEvent = deps.onEvent ?? (() => {})
  const resolveProject = deps.resolveProject ?? null

  return async function questionBridge(request: AskRequestLike, next: NextFn): Promise<AskAnswer> {
    const at = now()
    if (!validateAskRequest(request).ok) {
      onEvent({ at, kind: 'malformed-request', detail: 'request.questions 形状不合法——透传下游，不镜像' })
      return next()
    }
    if (!resolveProject) {
      onEvent({ at, kind: 'mirror-refused', detail: '未提供项目解析面——透传下游，不镜像' })
      return next()
    }
    const pr = resolveProject(request)
    if (!pr.ok) {
      onEvent({ at, kind: 'mirror-refused', detail: `项目解析失败：${pr.error}——透传下游，不镜像` })
      return next()
    }
    const mirrored = mirrorToLedger(io, env, pr.project, request, at)
    if (!mirrored.ok) {
      onEvent({ at, kind: 'mirror-failed', detail: `镜像被拒：${mirrored.error}——透传下游，不镜像` })
      return next()
    }
    onEvent({ at, kind: 'mirrored', detail: `请求 ${mirrored.row.id} 已镜像进 ${pr.project} 的请求账（人在 Requests tab 可见可答）` })

    // 两路并行：账上应答 vs 下游（真 UI）应答。先到先得；全终态收口见 waitForLedgerAnswer。
    const downstream = next().then(
      (a) => ({ ok: true as const, a }),
      (e) => ({ ok: false as const, e }),
    )
    const ledgerWait = waitForLedgerAnswer({
      io, env, project: pr.project, requestId: mirrored.row.id,
      signal: request.signal ?? null, pollMs, deadlineMs, now,
    })

    const ledgerOutcome = await Promise.race([
      ledgerWait,
      downstream.then(() => ({ state: 'downstream-first' }) as const, () => ({ state: 'downstream-first' }) as const),
    ])

    if (ledgerOutcome.state === 'answered') {
      onEvent({ at: now(), kind: 'answered-by-ledger', detail: `请求 ${mirrored.row.id} 由人经应答面答复——映射回会话，解锁` })
      // 下游可能还挂着：吞掉它的终局（答案不再采信——先到先得），但绝不留 unhandled rejection。
      downstream.then(() => {}, () => {})
      return mapLedgerAnswer(request, ledgerOutcome.answer)
    }
    if (ledgerOutcome.state === 'aborted') {
      onEvent({ at: now(), kind: 'aborted', detail: `请求 ${mirrored.row.id} 的调用方信号已 abort——立即收口，不等下游` })
      // 下游可能永不返回（无 UI 形态）：不 await——挂空终局，绝不留 unhandled rejection。
      downstream.then(() => {}, () => {})
      throw new Error('ask_user_question was aborted before the user answered (question-bridge)')
    }
    if (ledgerOutcome.state === 'deadline') {
      // 账上始终没人答、下游也没答（或下游永不返回）：立即显式失败——会话收到明确错误，不再无限等。
      onEvent({ at: now(), kind: 'mirror-failed', detail: ledgerOutcome.error })
      downstream.then(() => {}, () => {})
      ledgerWait.cancel?.()
      throw new Error(ledgerOutcome.error)
    }
    // downstream-first：真 UI 答了（或显式拒绝）。答案补一条 answer 行（审计留痕）；
    // 补账失败只留痕（应答本身已送达会话，不能因为它回滚会话侧结果）。
    const r = await downstream
    if (r.ok) {
      const text = (r.a.answers ?? [])
        .map(x => [ ...(x.selected ?? []), x.custom ?? '' ].filter(Boolean).join('\n'))
        .filter(Boolean).join('\n')
      if (text !== '') {
        const ans = answerRequest(io, env, pr.project, mirrored.row.id, text, 'downstream-ui', now())
        onEvent({ at: now(), kind: ans.ok ? 'answered-downstream' : 'mirror-failed',
          detail: ans.ok ? `下游 UI 应答请求 ${mirrored.row.id}，已补 answer 行留痕` : `下游应答了但补账被拒：${ans.error}` })
      }
      // 等待面立即显式收口（定时器+abort 监听），不等 deadline——全终态不靠进程退出兜底。
      ledgerWait.cancel?.()
      return r.a
    }
    // 下游显式拒绝（NO_PROVIDER：本部署没有 UI 应答者——正是 KI-181 的形态）：
    // 不把会话砸在这里，继续等账上应答（人经面板答了解锁）。
    onEvent({ at: now(), kind: 'downstream-refused', detail: `下游无应答者接受（${r.e instanceof Error ? r.e.message : String(r.e)}）——继续等账上应答` })
    const out = await ledgerWait
    if (out.state === 'answered') {
      onEvent({ at: now(), kind: 'answered-by-ledger', detail: `请求 ${mirrored.row.id} 由人经应答面答复——映射回会话，解锁` })
      return mapLedgerAnswer(request, out.answer)
    }
    if (out.state === 'aborted') throw new Error('ask_user_question was aborted before the user answered (question-bridge)')
    throw new Error(out.error)
  }
}

// ── node.ts 用的注册表反查版项目解析面 ────────────────────────────────────────

/** project.yaml 的 dirs 列表读面（形状同 session-create.ts projectMainDir：首个 dirs: 下的 `- x` 项）。 */
export function readProjectDirsFromYaml(raw: string): readonly string[] {
  const idx = raw.search(/^(\s*)dirs:\s*$/m)
  if (idx < 0) return []
  const rest = raw.slice(idx)
  const out: string[] = []
  for (const m of rest.matchAll(/^[ \t]*-[ \t]+(\S[^\n]*)$/gm)) {
    out.push(m[1].trim().replace(/^['"]|['"]$/g, ''))
  }
  return out
}

/** 生产版项目解析面：注册表根目录清单 + 逐 project.yaml 的 dirs 反查 cwd。
 *  任何一层读不到都显式报错（调用方降级透传并留痕），绝不猜项目。 */
export function makeRegistryProjectResolver(env: NodeJS.ProcessEnv, listProjects: (env: NodeJS.ProcessEnv) => string[], readFile: (path: string) => string): (request: AskRequestLike) => { ok: true; project: string } | { ok: false; error: string } {
  const root = projectsRoot(env)
  return (request) => {
    const cwd = request.agent && typeof request.agent.cwd === 'string' ? request.agent.cwd : ''
    const projects = listProjects(env).filter(k => PROJECT_KEY_RE.test(k))
    return projectKeyForCwd(projects, (key) => {
      try { return readProjectDirsFromYaml(readFile(`${root}/${key}/project.yaml`)) } catch { return null }
    }, cwd)
  }
}
