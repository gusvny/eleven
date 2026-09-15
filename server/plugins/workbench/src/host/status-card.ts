/**
 * status-card.ts —— 工单详情「人话状态卡」视图模型（KI-048 件④，t260911-05；
 * t260915-05 扩展：文案迁 red-light-lexicon 词条表 + 新增人门蓝卡腿）。
 *
 * 设计样张：notes/discussions/260904-ticket-detail-ui-mock.html A 块状态卡
 * （四件构成：人话主文案 ＋ 挡事文件点名 ＋ 下一步安排 ＋ 原始日志折叠；
 * mock C 原则：翻译层表驱动——引擎术语→人话词条，UI 不翻译它没拿到的信息）
 * ＋ 屏③ callout E（到人门时状态卡变蓝列出「签什么」）。
 *
 * 数据源优先级：
 *   1. detail.meta.blocked_detail（引擎 dev_lane 落的结构化面：
 *      {reason_code, files, next_action}）——文件点名/下一步直接取；
 *   2. detail.blocked_reason（blocked 文案，同一 _classify_main_dirty 真源派生
 *      的人话句）——主文案取它；文件名从文本抽路径 token 兜底（老票 KI-048
 *      降级锚，仅当结构化面缺席时启用，不冒充结构化数据）；
 *   3. 人门蓝卡：stage_state==='awaiting-human' → 「签什么」三源
 *      （human_context[gate].context_text 摘要 + stage_acceptance 清单 +
 *      最近一次 gate_runs 绿结论）；
 *   4. 都缺 → 卡不渲染（返回 null，老票零侵入）。
 *
 * 纯函数无 IO；畸形输入（非对象/字段类型错/列表超长）全部软降级不抛。
 */
import { translateReason } from '../client/red-light-lexicon.ts'

/** 文件名兜底抽取：blocked_reason 文本里的路径形 token（含 / 或 . 且非句读）。 */
const PATH_TOKEN_RE = /[A-Za-z0-9_][A-Za-z0-9_./-]*[/.][A-Za-z0-9_.-]+/g

/** 原始日志折叠条数上限（时间线尾部 N 条；全量在时间线区，卡面只留尾窗）。 */
export const STATUS_CARD_LOG_TAIL = 8

/** 文件点名条数上限（与引擎 MERGE_FILES_CAP 同口径，超出并入计数注记）。 */
export const STATUS_CARD_FILES_CAP = 20

/** 「签什么」清单条数上限（context_text 行 + 验收清单 + 门结论，防卡面爆长）。 */
export const STATUS_CARD_SIGN_WHAT_CAP = 8

function asStringArray(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.filter((x): x is string => typeof x === 'string' && x.trim() !== '')
}

function extractPathTokens(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const tok of text.match(PATH_TOKEN_RE) ?? []) {
    // 排除纯版本号/哈希样噪声：至少带一个路径分隔符才算「路径形」
    if (!tok.includes('/')) continue
    if (!seen.has(tok)) { seen.add(tok); out.push(tok) }
  }
  return out
}

export interface StatusCardView {
  /** 人话主文案（答：出了什么事 / 等你做什么）。 */
  headline: string
  /** 主文案是否命中词条表（false=回落原文/原因码裸展示的降级锚）。 */
  headlineFromTable: boolean
  /** 挡事文件点名（答：哪个文件；可为空=引擎没给、文本也抽不出）。 */
  files: string[]
  /** 文件封顶溢出计数（>0 时 UI 追加「+N more」。） */
  filesMore: number
  /** 下一步安排（答：接下来谁做什么）。 */
  next: string
  /** 原始日志折叠（timeline 尾部 N 条，已格式化为一行一条）。 */
  rawLog: string[]
  /** 红调（blocked）｜黄调（挂着受阻面的中间态）｜蓝调（人门等你签）。 */
  severity: 'red' | 'amber' | 'blue'
  /** 蓝卡专属：「签什么」清单（人门上下文摘要/验收清单/门结论）；红/黄卡为空。 */
  signWhat: string[]
}

/** 「签什么」三源汇聚（畸形输入逐条跳过，封顶防爆长）。 */
function buildSignWhat(detail: Record<string, unknown>): string[] {
  const out: string[] = []
  const humanContext = (detail.human_context !== null && typeof detail.human_context === 'object')
    ? detail.human_context as Record<string, unknown> : {}
  for (const v of Object.values(humanContext)) {
    if (v === null || typeof v !== 'object') continue
    const ctx = (v as Record<string, unknown>).context_text
    if (typeof ctx === 'string' && ctx.trim()) {
      // context_text 是多行人门上下文（diff 要点/验收口径）；逐行收，空行跳过
      for (const line of ctx.split('\n')) {
        const t = line.trim()
        if (t) out.push(t)
      }
    }
  }
  const acceptance = asStringArray(detail.stage_acceptance)
  for (const a of acceptance) {
    if (out.length >= STATUS_CARD_SIGN_WHAT_CAP) break
    if (!out.includes(a)) out.push(`验收口径：${a}`)
  }
  const gateRuns = Array.isArray(detail.gate_runs) ? detail.gate_runs as unknown[] : []
  for (let i = gateRuns.length - 1; i >= 0; i--) {
    const g = gateRuns[i]
    if (g === null || typeof g !== 'object') continue
    const go = g as Record<string, unknown>
    if (go.green !== true) continue
    const stage = typeof go.stage === 'string' ? go.stage : ''
    out.push(`前置门已全绿：${stage || '程序化检查'}（可签字）`)
    break
  }
  return out.slice(0, STATUS_CARD_SIGN_WHAT_CAP)
}

/**
 * 构建状态卡视图模型。返回 null = 整卡不渲染（非受阻票/非人门/既无结构化面
 * 也无 blocked 文案——老票零侵入）。
 */
export function buildStatusCard(detail: unknown): StatusCardView | null {
  if (detail === null || typeof detail !== 'object') return null
  const d = detail as Record<string, unknown>
  const stageState = typeof d.stage_state === 'string' ? d.stage_state : ''
  const blockedReason = typeof d.blocked_reason === 'string' ? d.blocked_reason.trim() : ''

  const meta = (d.meta !== null && typeof d.meta === 'object') ? d.meta as Record<string, unknown> : {}
  // 结构化面：show 顶层 blocked_detail（v2 snapshot 透传，KI-048 契约面）优先，
  // meta.blocked_detail 兜底（旧快照只带 meta 全文）。
  const rawBd = (d.blocked_detail !== null && typeof d.blocked_detail === 'object')
    ? d.blocked_detail : meta.blocked_detail
  const bd = (rawBd !== null && typeof rawBd === 'object')
    ? rawBd as Record<string, unknown> : {}

  const reasonCode = typeof bd.reason_code === 'string' ? bd.reason_code : ''
  const structFiles = asStringArray(bd.files)
  const structNext = typeof bd.next_action === 'string' ? bd.next_action.trim() : ''

  // ── 蓝卡腿：人门等你签（mock 屏③ callout E）──
  if (stageState === 'awaiting-human' && !reasonCode) {
    const tr = translateReason('awaiting-human', blockedReason)
    const signWhat = buildSignWhat(d)
    const rawLog = formatLogTail(d)
    return {
      headline: tr.headline,
      headlineFromTable: tr.fromTable,
      files: [],
      filesMore: 0,
      next: '人工审批：通过=批准签字；有意见=打回并附原因。引擎在你签字前不会动。',
      rawLog,
      severity: 'blue',
      signWhat,
    }
  }

  // 卡的触发面：blocked 态，或引擎给了结构化受阻面 / 受阻文案（含刚从 merge
  // blocked 恢复、仍挂着 detail 的中间态——黄调呈现）。
  if (stageState !== 'blocked' && !reasonCode && !blockedReason) return null

  // 主文案：词条表翻译 reason_code（t260915-05 表驱动），退回 blocked_reason 原文
  //（同一真源的人话句），再退回原因码裸展示（宁显码不显空白）。
  const tr = translateReason(reasonCode || null, blockedReason)
  const headline = tr.headline || (reasonCode ? `Merge blocked (${reasonCode})` : 'Ticket is blocked')

  // 文件点名：结构化 files → 文本抽路径 token 兜底（老票降级锚）；封顶 + 溢出计数。
  const filesAll = structFiles.length > 0 ? structFiles : extractPathTokens(blockedReason)
  const files = filesAll.slice(0, STATUS_CARD_FILES_CAP)
  const filesMore = Math.max(0, filesAll.length - files.length)

  // 下一步：引擎结构化 next_action → 词条表 next → blocked 态缺省话术。
  const next = structNext || tr.next || (stageState === 'blocked'
    ? 'Waiting for you: resolve the files above, then trigger retry-qc (or rework). The engine never stashes or commits on its own.'
    : 'Follow the reason above; the lane is preserved.')

  return {
    headline,
    headlineFromTable: tr.fromTable,
    files,
    filesMore,
    next,
    rawLog: [
      // 结构化受阻面的证据指针（=worker 回执原文锚，mock ①「原始日志可查证」）：
      // 引擎给了 evidence 就置顶一行原样透传，不美化不截断（截断只见于 timeline 尾窗）。
      ...(typeof bd.evidence === 'string' && bd.evidence.trim()
        ? [`[evidence] ${bd.evidence.trim()}`] : []),
      ...formatLogTail(d),
    ],
    severity: stageState === 'blocked' ? 'red' : 'amber',
    signWhat: [],
  }
}

/** 原始日志折叠：timeline 尾部 N 条（畸形条目逐条跳过；时间线缺省=一行说明）。 */
function formatLogTail(d: Record<string, unknown>): string[] {
  const timeline = Array.isArray(d.timeline) ? d.timeline : []
  const rawLog: string[] = []
  for (const ent of timeline.slice(-STATUS_CARD_LOG_TAIL)) {
    if (ent === null || typeof ent !== 'object') continue
    const e = ent as Record<string, unknown>
    const at = typeof e.at === 'string' ? e.at : '?'
    const stage = typeof e.stage === 'string' ? e.stage : '?'
    const state = typeof e.state === 'string' ? e.state : '?'
    const reason = typeof e.reason === 'string' ? e.reason : ''
    rawLog.push(`${at} [${stage}/${state}] ${reason}`.trimEnd())
  }
  if (rawLog.length === 0) rawLog.push('(no engine timeline entries)')
  return rawLog
}
