/**
 * ticket-list-model —— 工单列表行卡（t260904-17，mock v5 屏⑤⑥）纯函数层。
 *
 * 零 react / 平台依赖，node 可裸 import 黑盒单测（tests/t260904-17-ticket-list-model.mjs，
 * lane-states.ts 同款分层先例——只借形态不借语义，取舍清单见工单方案 gen1「复用取舍清单②」：
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
