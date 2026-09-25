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

/* ------------------------------------------------------------- 五态枚举 */

/** 引擎通用五态：在飞/收口/等你/受阻/已失败（t260919-02 增 failed；短名沿 mock ⑥
 *  chips 词表 + 本票「已失败」）。 */
export type TicketState4 = 'active' | 'done' | 'waiting' | 'blocked' | 'failed'

/** 五态人话短名（状态圆点旁文字，不占块）。 */
export const STATE4_LABEL: Record<TicketState4, string> = {
  active: 'Active',
  done: 'Closed',
  waiting: 'Waiting',
  blocked: 'Blocked',
  failed: 'Failed',
}

/**
 * 终态「成功收口」与「在飞」执行状态词表（t260921-03 从 t260919-02 的活/成混称
 * 拆出——COMPLETED 是终态对账的正源：已结束的票绝不再显示在跑/阻塞，快照遗留
 * 词面不得胜出；CONTINUED_AS_NEW 是换代继续的转场态，沿用词面推导）。
 * 与引擎 client.py _EXEC_DONE_OK/_EXEC_ALIVE_OK 同一词表的 UI 侧镜像，改任一侧
 * 必须同步另一侧并跑两侧 UT。在飞词表外的一切非空字符串（FAILED/CANCELED/
 * TIMED_OUT/未知新终态）→ failed（补集口径：终态非成功即失败类，未知新终态宁可
 * 显失败不显在跑；TERMINATED 不上板故板面不可达）。畸形/缺失 exec_status 不参与
 * 判别（不 throw）。
 */
const EXEC_STATUS_DONE_OK = new Set(['COMPLETED'])
const EXEC_STATUS_ALIVE = new Set(['RUNNING', 'CONTINUED_AS_NEW'])

/**
 * 引擎现值 → 五态（t260919-02 增第三参 execStatus 与 failed 态；t260921-03 终态对账）。
 *
 * 判别顺序：
 *  1. exec_status=COMPLETED → done（终态对账：exec 在手即权威，先于一切词面——
 *     快照遗留的 blocked/running 词面永不胜出，t260920-02/t260921-01 实案「工作流
 *     已完成却显阻塞」的直接根治点）；
 *  2. exec_status 非空且不在在飞词表 → failed（失败类终态优先：死票绝不显在飞，
 *     也不得被快照遗留的 closed 词面误归收口；t260919-02 口径零回归）；
 *  3. status/stage_state 词面 'failed' → failed（断链防御，review①：引擎失败行已
 *     带 failed 词面而 exec_status 键在 host 透传丢键/旧行缓存时仍失败可见，不落
 *     default active 复发病灶）；
 *  4. 沿用既有四态推导：closed 优先（迁移把 closed 票 stage_state 置成了 awaiting，
 *     语义上已完成，沿用台面 ticketState 既有口径）；未知/未来 stage_state →
 *     active（宁显活跃勿假警报——不作受阻/等你误报，UT 真值表钉此缺省行）。
 */
export function deriveTicketState(status?: unknown, stageState?: unknown, execStatus?: unknown): TicketState4 {
  if (typeof execStatus === 'string' && execStatus !== '') {
    if (EXEC_STATUS_DONE_OK.has(execStatus)) return 'done'
    if (!EXEC_STATUS_ALIVE.has(execStatus)) return 'failed'
  }
  if (status === 'failed' || stageState === 'failed') return 'failed'
  const st = typeof status === 'string' ? status : undefined
  const ss = typeof stageState === 'string' ? stageState : undefined
  if (st === 'closed') return 'done'
  switch (ss) {
    case 'blocked': return 'blocked'
    case 'awaiting-human': return 'waiting'
    case 'running':
    case 'awaiting':
      return 'active'
    default:
      return 'active'
  }
}

/* ------------------------------------------------------------- 收口健康度（t260921-03） */

/**
 * 收口健康度（行可判定字段：「已结束的票必须同时表达结束了与怎么结束的」）：
 *   ok=正常收口 / failed=失败终态 / abnormal=异常收口（已完成但没跑成实质工作，
 *   巡检=面快照 blocked——无论 report_path 是否在，blocked 收口也落账同名文件，
 *   路径在场≠报告在；或面无受阻但报告缺失） / unreadable=已结束·待核（面读取
 *   失败，显式存疑不冒充 ok——review 意见⑥裁定接受第 5 值） / ''=未收口（在飞
 *   无健康度可言）。
 * 与引擎 client.py _close_health_of 同一判定语义的双侧镜像（引擎是正源，本层是
 * UI 单点+部署窗旧行的兜底推导），改任一侧必须同步另一侧并跑两侧 UT。
 */
export type CloseHealth = 'ok' | 'failed' | 'abnormal' | 'unreadable' | ''

const CLOSE_HEALTH_ENUM = new Set<string>(['ok', 'failed', 'abnormal', 'unreadable'])

/** 收口健康度消费的最小行字段面（全键可缺=引擎行是不可信外部输入）。 */
export interface CloseHealthRowLike {
  status?: unknown
  stage_state?: unknown
  exec_status?: unknown
  /** 引擎标记/类别标记：巡检行识别用（缺产物判定只属巡检，不泛化到 dev-lane）。 */
  engine?: unknown
  kind?: unknown
  report_path?: unknown
  /** 受阻事实（实案 t260920-02 形：面快照 blocked——受阻面=没跑成实质工作）。 */
  blocked_reason?: unknown
  /** 引擎下发的收口健康度（t260921-03 起随行）；缺省=本地兜底推导。 */
  close_health?: unknown
}

/** 巡检行识别（引擎行自报家门，两标记任一命中；畸形值按非巡检处理）。 */
function isInspectionRowLike(row: CloseHealthRowLike | null | undefined): boolean {
  if (row === null || typeof row !== 'object') return false
  return row.kind === 'inspection' || row.engine === 'inspection'
}

/**
 * 行收口健康度：行键合法 → 透传（引擎单点判定的结果）；键缺/畸形 → 本地兜底推导。
 *
 * 兜底口径（引擎 _close_health_of 镜像）：只对「已知终态」下结论——
 *  - exec=COMPLETED：巡检行受阻词面优先（blocked_reason 在=面快照 blocked=没跑成
 *    实质工作 → abnormal；无论 report_path 是否在——t260917-02 起 blocked 收口也
 *    落账，落账走 report 同名约定，路径在场≠报告在，实案「报告」即受阻面镜像）；
 *    无受阻再按 report_path 判 ok/abnormal（无报告=异常收口）；dev-lane 无产物
 *    契约恒 ok；
 *  - exec 非空不在在飞词表 → failed（t260919-02 补集口径）；
 *  - exec 断链（host 丢键）：词面防御 failed 词→failed、closed 词→ok（无 exec
 *    无法核产物，绝不给 abnormal——在跑巡检面本来就没报告，宁可少标不撒谎）。
 * 已知偏差（review 意见②，UT 夹具钉死）：部署窗老 degraded 行（引擎尚未带
 * unreadable 键、面读取失败）在兜底下判 abnormal——徽标「已结束·异常（无报告）」
 * 而非「待核」；仍在异常收口族、不撒谎终态，可接受。
 */
export function closeHealthOf(row: CloseHealthRowLike | null | undefined): CloseHealth {
  const carried = row === null || typeof row !== 'object' ? undefined : row.close_health
  if (typeof carried === 'string' && CLOSE_HEALTH_ENUM.has(carried)) return carried as CloseHealth
  const exec = row !== null && typeof row === 'object' && typeof row.exec_status === 'string'
    ? row.exec_status : ''
  if (exec !== '') {
    if (EXEC_STATUS_DONE_OK.has(exec)) {
      if (isInspectionRowLike(row)) {
        const r = row as CloseHealthRowLike
        const blocked = r.blocked_reason
        if (typeof blocked === 'string' && blocked.trim() !== '') return 'abnormal'
        const rp = r.report_path
        return typeof rp === 'string' && rp.trim() !== '' ? 'ok' : 'abnormal'
      }
      return 'ok'
    }
    if (!EXEC_STATUS_ALIVE.has(exec)) return 'failed'
    return ''
  }
  const status = row !== null && typeof row === 'object' ? row.status : undefined
  const stageState = row !== null && typeof row === 'object' ? row.stage_state : undefined
  if (status === 'failed' || stageState === 'failed') return 'failed'
  if (status === 'closed') return 'ok'
  return ''
}

/**
 * 收口健康度徽标文案（''=不渲染——正常收口不贴徽标=既有收口行零变化，failed 行
 * 已有「已失败」态字不重复贴）。abnormal 文案带「无报告」：当前 abnormal 只从
 * 巡检缺报告产生（引擎判定同源），未来新产物域接入时随词表一起扩。
 */
export function closeHealthBadgeOf(row: CloseHealthRowLike | null | undefined): string {
  const h = closeHealthOf(row)
  if (h === 'abnormal') return 'Closed·Abnormal (no report)'
  if (h === 'unreadable') return 'Closed·Unverified'
  return ''
}

/**
 * 段间暂停操作键推导（t260908-01）：未暂停 → 'pause'，已暂停 → 'resume'。
 * closed 票由调用方（availableOps）早退不进此函数；畸形输入（undefined/非布尔真值）
 * 按真值性归 resume/pause，不 throw。推导住纯函数层（index.tsx 只消费），UT 直测。
 */
export function pauseOpOf(paused: unknown): 'pause' | 'resume' {
  return paused ? 'resume' : 'pause'
}

/**
 * 段间暂停徽标二态文案（t260908-01）：pending=已受理待段间生效（当前段还在跑），
 * at_gate=已停在段间门口；未知/空相位按 pending 文案兜底（宁可保守提示不可静默）。
 */
export function pausedBadgeText(phase?: unknown): string {
  return phase === 'at_gate' ? '⏸ Paused at the stage gate' : '⏸ Pausing (takes effect between stages)'
}

/* ------------------------------------------------------------- 左栏合并排序（t260916-15） */

/** 排序层消费的行最小字段面：dev-lane 行与巡检行同形（多字段不关心），全键可缺
 *  （行=引擎不可信外部输入，缺键/畸形由下方函数防御，绝不抛）。 */
export interface TicketSortRowLike {
  status?: unknown
  stage_state?: unknown
  /** Temporal 执行状态（t260919-02：失败类终态行置顶可 attention 的数据源）。 */
  exec_status?: unknown
  /** 收口健康度判定面（t260921-03：done 档拆异常/正常两层的数据源，全可缺）。 */
  engine?: unknown
  kind?: unknown
  report_path?: unknown
  close_health?: unknown
  updated_ts?: unknown
  created?: unknown
  close_ts?: unknown
}

/**
 * 排序层（t260916-15；t260919-02 增第三参 execStatus 与 failed 档；t260921-03 done
 * 拆两层成四档）：等你/受阻/已失败 → 在跑 → **已结束·异常** → 已结束·正常。
 * tier 是 deriveTicketState 五态+收口健康度的**纯投影**——状态→五态映射单点仍在
 * deriveTicketState（全台唯一归并点），健康度单点在 closeHealthOf，本函数不另起
 * 第二套词表；异常收口行 tier2（在跑之上？否——在跑之下、正常收口之上）：不沉底、
 * 不被并入「看起来正常」的收口组，既有四类相对序不变（t260916-15 口径零回归）；
 * 未知/未来 stage_state 继承「宁显活跃勿假警报」缺省 → tier1；失败票 tier0。
 * 第四参 row 供健康度判定（缺省=旧三参形态，done 一律按正常收口 tier3 兜底——
 * 老调用点/无行面语境不下异常结论）。
 */
export function ticketMergeTierOf(status?: unknown, stageState?: unknown, execStatus?: unknown,
                                  row?: CloseHealthRowLike | null): 0 | 1 | 2 | 3 {
  const s4 = deriveTicketState(status, stageState, execStatus)
  switch (s4) {
    case 'waiting':
    case 'blocked':
    case 'failed':
      return 0
    case 'done': {
      const h = closeHealthOf(row ?? { status, stage_state: stageState, exec_status: execStatus })
      return h === 'abnormal' || h === 'unreadable' ? 2 : 3
    }
    default:
      return 1
  }
}

/**
 * 排序时间源：updated_ts 优先，缺/畸形逐级回落 created → close_ts，全缺 → 0。
 * 单位口径（review 意见钉死）：引擎 updated_ts/created/close_ts 全是**秒**
 * （base.py _now_epoch 系；toMillis 是消费点显示归一单点，与本排序无关）——
 * dev-lane 行与巡检行两数据源同单位，直接比原始值安全；若未来单源换单位，
 * 必须先归一再进本函数，否则会以另一形态复刻「沉底」式静默错序。
 * 非有限数/≤0（字符串/null/NaN/0/负）不抛不参与、逐级回落；行非对象 → 0。
 */
export function ticketSortTsOf(row: TicketSortRowLike | null | undefined): number {
  if (row === null || typeof row !== 'object') return 0
  for (const v of [row.updated_ts, row.created, row.close_ts]) {
    if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v
  }
  return 0
}

/**
 * 左栏项目组合并排序（t260916-15 宿主实报「巡检票恒沉底」）：dev-lane 行与巡检行
 * 合并后统一口径——tier 升序（等你/受阻→在跑→已完成）、级内时间源倒序、同 ts 保
 * 输入序（显式 index 兜底，不依赖引擎 sort 稳定性）。浅拷贝排序不改输入数组；
 * null/非对象元素不抛（tier 走缺省、ts=0，沉底不崩）。中列板面列表不消费本函数
 * （排序是左栏项目组的组内呈现口径，工单正文验收①边界）。
 */
export function sortMergedTickets<T extends TicketSortRowLike>(rows: readonly T[]): T[] {
  const keyed = rows.map((row, idx) => ({ row, idx }))
  keyed.sort((a, b) => {
    const ra = a.row as TicketSortRowLike | null
    const rb = b.row as TicketSortRowLike | null
    // t260919-02：exec_status 进 tier 投影（失败类终态行 tier0 置顶，左栏不再
    // 把死票混在在跑档里隐形）。t260921-03：整行进 tier 投影（异常收口行 tier2，
    // 不沉底不并入正常收口档）。
    const ta = ticketMergeTierOf(ra?.status, ra?.stage_state, ra?.exec_status, ra ?? undefined)
    const tb = ticketMergeTierOf(rb?.status, rb?.stage_state, rb?.exec_status, rb ?? undefined)
    if (ta !== tb) return ta - tb
    const dts = ticketSortTsOf(rb) - ticketSortTsOf(ra)
    return dts !== 0 ? dts : a.idx - b.idx
  })
  return keyed.map(k => k.row)
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
  running: 'Running',
  'awaiting-human': 'Awaiting your signature',
  blocked: 'Blocked · see detail',
  done: 'Stage done',
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
  /** Temporal 执行状态（t260919-02：五态推导第三参的数据源，缺省=四态旧行为）。 */
  exec_status?: string
  /** 收口健康度判定面（t260921-03：异常收口筛选与徽标数据源，全可缺）。 */
  engine?: string
  kind?: string
  report_path?: string
  close_health?: string
}

/** 筛选 chips 输入：四态（''=不过滤）、epic 代号（''=不过滤）、搜索词（''=不过滤）、
 *  异常收口（t260921-03：'abnormal'=只看异常收口族〔abnormal+unreadable〕）。 */
export interface FilterInput {
  state?: string
  epic?: string
  q?: string
  health?: string
}

/**
 * chips=过滤非分组：五态按 deriveTicketState 归并后比对（与行卡同源，不按
 * status/stage_state 原词各筛各的）；epic 精确匹配；q 大小写不敏感匹配 id+标题；
 * health='abnormal' 筛异常收口族（closeHealthOf 单点，failed 行有自己的「已失败」
 * chip 不混入；与 state/epic/q 全部 AND 叠加）。
 */
export function filterRows<T extends FilterableRow>(rows: T[], f: FilterInput): T[] {
  const q = (f.q ?? '').trim().toLowerCase()
  return rows.filter(r => {
    if (f.state && deriveTicketState(r.status, r.stage_state, r.exec_status) !== f.state) return false
    if (f.health === 'abnormal') {
      const h = closeHealthOf(r)
      if (h !== 'abnormal' && h !== 'unreadable') return false
    }
    if (f.epic && (r.epic ?? '') !== f.epic) return false
    if (q !== '') {
      const hay = `${r.id} ${r.title ?? ''}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}

/** 五态 chips 计数（含 done——收口折叠计数行的数字来源；'' 全部计数由调用方取 rows.length）。 */
export function countByState(rows: FilterableRow[]): Record<TicketState4, number> {
  const out: Record<TicketState4, number> = { active: 0, done: 0, waiting: 0, blocked: 0, failed: 0 }
  for (const r of rows) out[deriveTicketState(r.status, r.stage_state, r.exec_status)] += 1
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
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
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
