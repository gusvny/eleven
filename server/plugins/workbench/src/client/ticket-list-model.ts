/**
 * ticket-list-model —— 工单列表行卡（t260904-17，mock v5 屏⑤⑥）纯函数层。
 *
 * 零 react / 平台依赖，node 可裸 import 黑盒单测（tests/t260904-17-ticket-list-model.mjs，
 * lane-states.ts 同款分层先例——只借形态不借语义（复用取舍见票 t260904-17 方案）：
 * 不带入合并分支内联步排除、并行活跃数组等 dev-lane 专属启发式）。
 *
 * 通用口径（一套 UI 裁定，260904 宿主令）：
 *  - 状态走引擎通用四态枚举 active/done/waiting/blocked（映射单点在本文件）；
 *  - epic 色 = 代号稳定哈希（FNV-1a+murmur3 finalizer → 10 色板），零配置零漂移——
 *    哈希函数直接复用 shared/project-color.ts 的 fnv1a（已导出，不抽不复制；
 *    F2 教训=纯 FNV 短 key 低位雪崩不足会真实撞槽，finalizer 必须带走）；
 *  - 阶段短名走拓扑声明 short 字段，缺省截断——UI 不内置任何业务词表；
 *  - 本文件（及 ticket-row-card.tsx）不得出现 dev-lane 段名常量串（守卫测试看住）；
 *    引擎通用状态词（running/awaiting-human/blocked/closed…）不属禁列。
 */

import { fnv1a } from '../shared/project-color.ts'

/* ------------------------------------------------------------- 四态枚举 */

/** 引擎通用四态：在飞/收口/等你/受阻（短名沿 mock ⑥ chips 词表）。 */
export type TicketState4 = 'active' | 'done' | 'waiting' | 'blocked'

/** 四态人话短名（状态圆点旁文字，不占块）。 */
export const STATE4_LABEL: Record<TicketState4, string> = {
  active: '在飞',
  done: '收口',
  waiting: '等你',
  blocked: '受阻',
}

/**
 * 引擎现值 → 四态。closed 优先（迁移把 closed 票 stage_state 置成了 awaiting，
 * 语义上已完成，沿用台面 ticketState 既有口径）；未知/未来新增 stage_state →
 * active（宁显活跃勿假警报——不作受阻/等你误报，UT 真值表钉此缺省行）。
 */
export function deriveTicketState(status?: string, stageState?: string): TicketState4 {
  if (status === 'closed') return 'done'
  switch (stageState) {
    case 'blocked': return 'blocked'
    case 'awaiting-human': return 'waiting'
    case 'running':
    case 'awaiting':
      return 'active'
    default:
      return 'active'
  }
}

/* ------------------------------------------------------------- epic 哈希色 */

/**
 * epic 色板：10 色。与项目色板（shared/project-color.ts PROJECT_PALETTE）色相同构
 * 但独立声明——两板语义不同（项目 tag vs epic 彩条/chip），互指防漂移不共用实例。
 * 撞色口径同 project-color：碰撞无害（chip 有名可辨），不作通过/失败断言。
 */
export const EPIC_PALETTE: readonly string[] = [
  '#d6604f', // 0° 红
  '#e08214', // 36° 橙
  '#b8a021', // 72° 金
  '#66a61e', // 108° 绿
  '#35988c', // 144° 青
  '#4393c3', // 180° 蓝
  '#6b6ecf', // 252° 靛
  '#9e5db5', // 288° 紫
  '#c05b9c', // 324° 粉
  '#7f7f7f', // 中性灰档
]

/** 畸形 epic 代号兜底色（中性灰，一眼「未定色」）。 */
export const EPIC_FALLBACK_COLOR = '#9ca3af'

/** 代号长度上限（超长按畸形处理）。 */
const EPIC_CODE_MAX_LEN = 64

/**
 * epic 代号 → 稳定色。纯函数无状态：同代号跨刷新/会话恒同色，与其它 epic
 * 增删无关（验收②）。空/非字符串/超长 → 兜底灰。
 */
export function epicColorOf(code?: string | null): string {
  if (typeof code !== 'string') return EPIC_FALLBACK_COLOR
  const c = code.trim()
  if (c === '' || c.length > EPIC_CODE_MAX_LEN) return EPIC_FALLBACK_COLOR
  // 域分离盐「epic:」：与项目 tag 哈希空间隔离（语义上不同命名域不该同色），且
  // 实测让真实 epic 名册（doc-lifecycle/engine-hardening/project-lifecycle/session-entry）
  // mod 10 两两异槽——纯 FNV 直取时 engine-hardening 与 project-lifecycle 同槽 3
  // （F2 事故同款面，UT「名册两两异槽」回归看住，改盐须跑该测试=有意识行为）。
  return EPIC_PALETTE[fnv1a(`epic:${c}`) % EPIC_PALETTE.length]
}

/* ------------------------------------------------------------- 阶段短名 */

/** 拓扑阶段的最小消费面（对齐 WfStage，多字段不关心）。 */
export interface StageLike {
  id?: string
  name?: string
  /** 模板声明短名（缺省截断路径的让位字段；本票不改引擎模板，此路径为前置票预留）。 */
  short?: string
}

const SHORT_MAX = 4

/**
 * 阶段短名：拓扑声明 short 非空用之；否则 name 超 4 字符截断＋…。
 * 畸形输入（非对象/无名）→ ''。消费点：行卡悬停 title 与进展行阶段语境（C2）。
 */
export function stageShortOf(stage?: StageLike | null): string {
  if (stage === null || stage === undefined || typeof stage !== 'object') return ''
  const short = typeof stage.short === 'string' ? stage.short.trim() : ''
  if (short !== '') return short
  const name = typeof stage.name === 'string' ? stage.name.trim() : ''
  if (name === '') return ''
  return [...name].length > SHORT_MAX ? [...name].slice(0, SHORT_MAX).join('') + '…' : name
}

/* ------------------------------------------------------------- 进展行 */

/** 进展行的最小结构（引擎词 state + 人话 text；state 供行卡配色语境）。 */
export interface ProgressLine {
  /** 引擎状态词（未知值已过滤——引擎词不漏进 UI 文案，验收④同理）。 */
  state: string
  /** 一句进展人话。 */
  text: string
}

/** 引擎状态词 → 动词短语（表驱动；未知词不在表=不产出文案）。 */
const PROGRESS_PHRASES: Record<string, string> = {
  running: '执行中',
  'awaiting-human': '等你签字',
  blocked: '受阻 · 原因见详情',
  done: '本步已完成',
}

/** timeline 条目的最小形状校验（外部快照不可信）。 */
function timelineEntryLike(e: unknown): { state: string; stage: string } | null {
  if (e === null || typeof e !== 'object') return null
  const o = e as Record<string, unknown>
  if (typeof o.state !== 'string' || o.state === '') return null
  return { state: o.state, stage: typeof o.stage === 'string' ? o.stage : '' }
}

/**
 * 时间线末条 → 一句进展。畸形条目（缺 state/非对象）向前跳过找最近合法条；
 * timeline 缺失/空/非数组/全畸形/末条 state 未知 → undefined（行卡降级只显相对时间）。
 * 只读末段，不做任何 dev-lane 启发式推导。
 */
export function progressLineOf(timeline?: unknown): ProgressLine | undefined {
  if (!Array.isArray(timeline)) return undefined
  for (let i = timeline.length - 1; i >= 0; i--) {
    const e = timelineEntryLike(timeline[i])
    if (e === null) continue
    const text = PROGRESS_PHRASES[e.state]
    if (text === undefined) return undefined
    return { state: e.state, text }
  }
  return undefined
}

/* ------------------------------------------------------------- 迷你站道 */

/** 站道点视觉态：已过=绿 / 当前=状态色 / 未来=灰。颜色由行卡按 state 渲，模型只定形状。 */
export type LaneDotVisual = 'done' | 'current' | 'todo'

/** 拓扑的最小消费面（对齐 Wf）。 */
export interface WfLike {
  id?: string
  stages?: StageLike[]
}

/** 工单的最小消费面（对齐 TicketRow）。 */
export interface LaneTicketLike {
  status?: string
  stage?: string | null
}

/**
 * 迷你站道点数组：点数=模板阶段数；已过（下标<当前下标）=done、当前=current、未来=todo。
 * 边缘钉死（UT 真值表）：status=closed → 全 done；stage=null（未开跑/迁移 legacy）或
 * 指针不在拓扑内 → 全 todo（不得误渲「已过」）；wf 缺失/stages 空 → []（行卡不渲染站道）。
 */
export function laneDots(wf?: WfLike | null, ticket?: LaneTicketLike | null): LaneDotVisual[] {
  const stages = wf?.stages
  if (!Array.isArray(stages) || stages.length === 0) return []
  if (ticket?.status === 'closed') return stages.map(() => 'done' as const)
  const idx = typeof ticket?.stage === 'string' && ticket.stage !== ''
    ? stages.findIndex(s => s?.id === ticket.stage) : -1
  if (idx < 0) return stages.map(() => 'todo' as const)
  return stages.map((_, i) => (i < idx ? 'done' : i === idx ? 'current' : 'todo') as LaneDotVisual)
}

/* ------------------------------------------------------------- 筛选 / 时间 */

/** 行卡过滤输入的最小字段面。 */
export interface FilterableRow {
  id: string
  title?: string
  epic?: string
  status?: string
  stage_state?: string
}

/** 筛选 chips 输入：四态（''=不过滤）、epic 代号（''=不过滤）、搜索词（''=不过滤）。 */
export interface FilterInput {
  state?: string
  epic?: string
  q?: string
}

/**
 * chips=过滤非分组：四态按 deriveTicketState 归并后比对（与行卡同源，不按
 * status/stage_state 原词各筛各的）；epic 精确匹配；q 大小写不敏感匹配 id+标题。
 */
export function filterRows<T extends FilterableRow>(rows: T[], f: FilterInput): T[] {
  const q = (f.q ?? '').trim().toLowerCase()
  return rows.filter(r => {
    if (f.state && deriveTicketState(r.status, r.stage_state) !== f.state) return false
    if (f.epic && (r.epic ?? '') !== f.epic) return false
    if (q !== '') {
      const hay = `${r.id} ${r.title ?? ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}

/** 四态 chips 计数（含 done——收口折叠计数行的数字来源；'' 全部计数由调用方取 rows.length）。 */
export function countByState(rows: FilterableRow[]): Record<TicketState4, number> {
  const out: Record<TicketState4, number> = { active: 0, done: 0, waiting: 0, blocked: 0 }
  for (const r of rows) out[deriveTicketState(r.status, r.stage_state)] += 1
  return out
}

/** 消费点接线的单位归一（F2 回归点）：引擎 updated_ts=**秒**（base.py _now_epoch），
 * 而部分调用方（侧栏 created/close_ts×1000）已持毫秒——按量级判别：数值 < 1e11
 * 视为秒×1000，≥1e11 视为毫秒原样（1e11ms≈1973 年，两域在可预见时间内无重叠）。
 * 畸形输入透传给 relativeTime 自行兜底（null/undefined/非数 → 返 undefined 外原样）。
 */
export function toMillis(ts?: number | null): number | null | undefined {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return ts as number | null | undefined
  return ts < 1e11 ? ts * 1000 : ts
}

/**
 * 相对时间：nowMs 注入可测，入参=毫秒（秒级时间戳须经 toMillis 归一）。<1min=「刚刚」、
 * <1h=N 分钟前、<24h=N 小时前、其余=N 天前。畸形/缺失/负数/未来超过 1min 容差 →
 * null（行卡回落绝对时间）。
 */
export function relativeTime(ts?: number | null, nowMs: number = Date.now()): string | null {
  if (typeof ts !== 'number' || !Number.isFinite(ts) || ts <= 0) return null
  const diff = nowMs - ts
  if (diff < -60_000) return null
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${Math.floor(diff / 86_400_000)} 天前`
}

/* ------------------------------------------------------------- 首句标题（t260905-07） */

/** 首句展示截断上限（字符）：超过即截断加省略号——行卡单行放不下长句。 */
const FIRST_SENTENCE_MAX = 48

/**
 * 正文 → 首句话（t260903-10 裸编号现场根治：老票无标题显示首句，不裸编号）。
 * 口径：取正文第一个非空行，在第一个句读符（。！？!?；）处截断；无句读取整行；
 * 超长截断加「…」。markdown 标记（#/-/>/空白）剥头。畸形输入（非字符串/空白/
 * 全是标记）→ null（调用方回退展示选择函数）。host 侧 enrichment（node.ts）与
 * 详情头部共用本函数（ticket show 的 body 同源裁剪——两条通道一个口径）。
 */
export function firstSentenceOf(body?: unknown): string | null {
  if (typeof body !== 'string') return null
  const lines = body.split(/\r?\n/)
  let line = ''
  for (const raw of lines) {
    const t = raw.replace(/^[#>\-*\s]+/, '').trim()
    if (t !== '') { line = t; break }
  }
  if (line === '') return null
  const m = line.match(/^[^。！？!?；]+[。！？!?；]?/)
  let sentence = m !== null ? m[0] : line
  if ([...sentence].length > FIRST_SENTENCE_MAX) {
    sentence = [...sentence].slice(0, FIRST_SENTENCE_MAX).join('') + '…'
  }
  return sentence
}

/** 行卡/详情头部标题展示选择（收窄口径）：title → title_or_first
 *  （host enrichment 派生字段，仅 title 为空的票下发）→ 回退工单号（裸编号是
 *  最后兜底——enrichment 失败/老数据缺字段时，宁显编号不显「（无标题）」）。 */
export function ticketDisplayTitle(t: { id: string; title?: string; title_or_first?: string }): string {
  const title = typeof t.title === 'string' ? t.title.trim() : ''
  if (title !== '') return title
  const first = typeof t.title_or_first === 'string' ? t.title_or_first.trim() : ''
  if (first !== '') return first
  return t.id
}

/* ------------------------------------------------------------- 快照要点（t260905-07） */

/** 快照要点：阶段时间线条目（排序后）。 */
export interface DigestTimelineEntry {
  stage: string
  state: string
  at: string | null
  /** KI-019 呈现口径：at 缺失/畸形条目沉底并标注（数据模型缺轮次维度的失真面显性化）。 */
  untime: boolean
}

/** 快照要点：交接条目。 */
export interface DigestHandoff {
  from: string
  to: string
  at: string | null
}

/** 快照要点：门运行/签字记录条目。 */
export interface DigestGate {
  kind: 'gate' | 'signature'
  stage: string
  who: string
  decision: string
  note: string
  at: string | null
}

/** 快照要点聚合（纯裁剪，零派生语义——数据全部来自 ticket show 直读）。 */
export interface SnapshotDigest {
  workflow: { id: string; stage: string; stageState: string; status: string; revisions: number | null; worktree: string }
  timeline: DigestTimelineEntry[]
  handoffs: DigestHandoff[]
  gates: DigestGate[]
}

/**
 * ticket show 详情 → 快照要点（阶段时间线/最近交接/门与签字记录/工作流快照要点）。
 * 畸形输入纪律（消费外部快照=不可信输入，单测必带畸形用例）：
 *   - 非对象/全空 → 各字段空形状，不抛；
 *   - timeline 按 at 升序排序后裁尾 20 条（KI-019 呈现口径钉死：乱序到达被归位；
 *     缺 at/畸形 at 条目沉底并带 untime 标注——排序失真面显性化，不静默混排）；
 *   - handoffs 取尾部 5 条（最近交接）；gate_runs + signatures 合并为记录表
 *     （按 at 降序=最近在前；条目畸形逐条跳过）。
 */
export function snapshotDigest(detail: unknown): SnapshotDigest {
  const empty: SnapshotDigest = {
    workflow: { id: '', stage: '', stageState: '', status: '', revisions: null, worktree: '' },
    timeline: [],
    handoffs: [],
    gates: [],
  }
  if (detail === null || typeof detail !== 'object') return empty
  const d = detail as Record<string, unknown>
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')

  const workflow = {
    id: str(d.id),
    stage: str(d.stage),
    stageState: str(d.stage_state),
    status: str(d.status),
    revisions: typeof d.revision_count === 'number' && Number.isFinite(d.revision_count) ? d.revision_count : null,
    worktree: str(d.worktree),
  }

  // 阶段时间线：合法条目 → {stage,state,at}；at 合法（可转数值）参与排序，否则沉底。
  const rawTl = Array.isArray(d.timeline) ? d.timeline : []
  const timed: { stage: string; state: string; at: string; ms: number }[] = []
  const untimed: DigestTimelineEntry[] = []
  for (const e of rawTl) {
    if (e === null || typeof e !== 'object') continue
    const o = e as Record<string, unknown>
    const stage = str(o.stage)
    const state = str(o.state)
    if (stage === '' && state === '') continue
    const at = o.at
    const ms = typeof at === 'number' && Number.isFinite(at) ? at
      : typeof at === 'string' && at.trim() !== '' && Number.isFinite(Number(at)) ? Number(at) : null
    if (ms === null) {
      untimed.push({ stage, state, at: null, untime: true })
    } else {
      timed.push({ stage, state, at: String(at), ms })
    }
  }
  timed.sort((a, b) => a.ms - b.ms)
  const timeline: DigestTimelineEntry[] = [
    ...timed.slice(-20).map(e => ({ stage: e.stage, state: e.state, at: e.at, untime: false })),
    ...untimed,
  ]

  // 最近交接：尾部 5 条；条目畸形（非对象）跳过。
  const rawHo = Array.isArray(d.handoffs) ? d.handoffs : []
  const handoffs: DigestHandoff[] = []
  for (let i = rawHo.length - 1; i >= 0 && handoffs.length < 5; i--) {
    const o = rawHo[i]
    if (o === null || typeof o !== 'object') continue
    const h = o as Record<string, unknown>
    handoffs.push({ from: str(h.from), to: str(h.to), at: typeof h.at === 'string' ? h.at : null })
  }

  // 门与签字记录：gate_runs（程序化门）+ signatures（人门签字）合并，at 降序最近在前。
  const gates: DigestGate[] = []
  const gateMs = (v: unknown): number => {
    const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
    return Number.isFinite(n) ? n : NaN
  }
  const rawGateRuns = Array.isArray(d.gate_runs) ? d.gate_runs : []
  for (const g of rawGateRuns) {
    if (g === null || typeof g !== 'object') continue
    const o = g as Record<string, unknown>
    gates.push({
      kind: 'gate',
      stage: str(o.stage),
      who: str(o.kind) || 'script',
      decision: str(o.status) || str(o.result),
      note: str(o.note),
      at: typeof o.at === 'string' ? o.at : null,
    })
  }
  const sigs = d.signatures
  if (sigs !== null && typeof sigs === 'object') {
    for (const [stage, v] of Object.entries(sigs as Record<string, unknown>)) {
      if (v === null || typeof v !== 'object') continue
      const o = v as Record<string, unknown>
      gates.push({
        kind: 'signature',
        stage,
        who: str(o.who),
        decision: str(o.decision),
        note: str(o.note),
        at: typeof o.at === 'string' ? o.at : null,
      })
    }
  }
  gates.sort((a, b) => {
    const am = gateMs(a.at)
    const bm = gateMs(b.at)
    if (Number.isNaN(am) && Number.isNaN(bm)) return 0
    if (Number.isNaN(am)) return 1
    if (Number.isNaN(bm)) return -1
    return bm - am
  })

  return { workflow, timeline, handoffs, gates }
}
