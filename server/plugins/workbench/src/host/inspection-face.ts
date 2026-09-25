/**
 * inspection-face —— 巡检票板面纯函数层（t260915-08，方案 v2 R4/R5/R6）。
 *
 * 零 react / 零平台依赖，node 可裸 import 黑盒单测
 * （tests/t260915-08-inspection-face.mjs，ticket-list-model.ts 同款分层先例）。
 *
 * 为什么住 host/：巡检段的**短名排版映射**住这里（行卡/时间线的 ≤4 字压缩，
 * 宿主 UI 职责）；阶段词表本身自 t260916-05 起真源在引擎（inspection_flow.py
 * STAGES 声明 + template_topology 导出），泳道图吃快照 topology 键（通用渲染器），
 * 本表的词表一致性由同步锁源级锚定（tests/t260916-05-inspection-topology-lock.mjs
 * ——「STAGES 改了不改本表，锁必红」）。client 侧 context-fold.ts 已有 import
 * host 模块的先例（session-charter）。
 *
 * 行数据源=引擎 client.py ticket-list {kind:"inspection"} 行（_row_from_inspection_face）：
 *   {id, title, kind:"inspection", instance_id, period, stage, stage_state, status,
 *    findings:{high,med,low,total}, heartbeat, report_path, awaiting_gate,
 *    human_gate, blocked_reason, gate_error, engine:"inspection", ...}
 * 引擎行是**不可信外部输入**：本层所有函数对畸形输入降级（不抛、不编造）。
 */

/**
 * 巡检段短名映射（t260916-05 定性收窄）：**宿主排版职责**，不是阶段词表真源。
 * 段词表的编码真源=引擎 inspection_flow.py `InspectionPeriodicWorkflow.STAGES`
 * （机器可读阶段声明）；泳道图面消费引擎拓扑导出（快照 topology 键→lane-map
 * 通用渲染器，本常量零参与）。本表只剩 ≤4 字短名的行卡/时间线排版压缩，与引擎
 * STAGES 的 id 序/name 一致性由同步锁钉死（tests/t260916-05-inspection-topology
 * -lock.mjs 源级锚：STAGES 改了不改本表，锁必红）。
 */
export const INSPECTION_TOPOLOGY: {
  id: string
  name: string
  short: string
}[] = [
  { id: 'setup', name: '泳道准备', short: 'Setup' },
  { id: 'suite', name: '巡检泳道套件', short: 'Suite' },
  // t260916-22：scan 段退役、inspect 段（只读 agent 审查）接位——本表随引擎
  // STAGES 同步改（一致性锁=t260916-05-inspection-topology-lock.mjs）。
  { id: 'inspect', name: '巡检审查', short: 'Inspect' },
  { id: 'report', name: '落账', short: 'Report' },
  { id: 'close', name: '人审收口', short: 'Close' },
]

/** 行卡/详情消费的巡检行最小字段面（对齐引擎行，多字段不关心）。 */
export interface InspectionRowLike {
  id?: string
  kind?: unknown
  engine?: unknown
  title?: unknown
  /** 项目身份（t260915-20 起=ProjectKey SA 直读；20 之前老票为空串/缺键）。 */
  project?: unknown
  stage?: unknown
  stage_state?: unknown
  status?: unknown
  findings?: unknown
  awaiting_gate?: unknown
  blocked_reason?: unknown
}

/** 消费外部行=不可信输入的取串助手（非串→''）。 */
function strOf(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

/** 是否巡检行：kind 或 engine 标记任一命中（引擎行带 kind=inspection）。 */
export function isInspectionRow(t: { kind?: unknown; engine?: unknown }): boolean {
  return t !== null && typeof t === 'object'
    && (t.kind === 'inspection' || t.engine === 'inspection')
}

/** 发现数计数的最小形状守卫（引擎 summary/findings 畸形时全 0，不编造）。 */
export function findingsCountOf(row: InspectionRowLike): { high: number; med: number; low: number; total: number } {
  const f = row?.findings
  if (f !== null && typeof f === 'object') {
    const o = f as Record<string, unknown>
    const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
    return { high: num(o.high), med: num(o.med), low: num(o.low), total: num(o.total) }
  }
  return { high: 0, med: 0, low: 0, total: 0 }
}

/**
 * 详情面发现数计数（t260915-08 实证补）：行（ticket-list）与详情（ticket-query）
 * 的发现数据形状不同——行 findings={high,med,low,total} 计数字典；详情 face.summary=
 * {high,med,low} 计数字典、face.findings=发现清单（列表）。本函数吃详情形状：
 * summary 字典优先（引擎真值），缺/畸形时按 findings 清单逐条 severity 重计，
 * 两者皆缺=全 0（不编造）。行形状请用 findingsCountOf。
 */
export function inspectionSummaryOf(face: { summary?: unknown; findings?: unknown }): { high: number; med: number; low: number; total: number } {
  const src = face !== null && typeof face === 'object' ? face as Record<string, unknown> : {}
  const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
  const s = src.summary
  if (s !== null && typeof s === 'object') {
    const o = s as Record<string, unknown>
    const high = num(o.high); const med = num(o.med); const low = num(o.low)
    const total = num(o.total) || (high + med + low)
    if (high || med || low || total) return { high, med, low, total }
  }
  const list = Array.isArray(src.findings) ? src.findings : []
  const high = list.filter((f) => (f as { severity?: unknown })?.severity === 'high').length
  const med = list.filter((f) => (f as { severity?: unknown })?.severity === 'med').length
  const low = list.filter((f) => (f as { severity?: unknown })?.severity === 'low').length
  return { high, med, low, total: high + med + low }
}

/** 阶段短名：拓扑命中用短名，未命中截断原词（stageShortOf 同口径），畸形→''。 */
export function inspectionStageShort(stage: unknown): string {
  const s = strOf(stage)
  if (s === '') return ''
  const hit = INSPECTION_TOPOLOGY.find(st => st.id === s)
  if (hit) return hit.short
  return [...s].length > 4 ? [...s].slice(0, 4).join('') + '…' : s
}

/**
 * 巡检行的一句进展（行卡 progress prop 数据源，t260904-17 同构）。
 * 待签判定**只读 stage_state/awaiting_gate**（引擎 R4：face.human_gate 签字前常态缺键，
 * 不得依赖）；发现数来自 findings 字段（引擎已并好）。畸形行 → undefined
 * （行卡降级只显相对时间）。闭合一律 {state:'done'}（收口折叠吃掉，正常语义）。
 */
export function inspectionProgressOf(row: InspectionRowLike): { state: string; text: string } | undefined {
  if (row === null || typeof row !== 'object') return undefined
  const stageState = strOf(row.stage_state)
  const status = strOf(row.status)
  const c = findingsCountOf(row)
  const findingsTxt = `findings H${c.high}/M${c.med}/L${c.low}`
  if (status === 'closed') return { state: 'done', text: `Closed · ${findingsTxt}` }
  if (stageState === 'awaiting-human' || row.awaiting_gate === true) {
    return { state: 'awaiting-human', text: `Awaiting your signature · ${findingsTxt}` }
  }
  if (stageState === 'blocked') {
    const reason = strOf(row.blocked_reason)
    return { state: 'blocked', text: `Blocked${reason ? ': ' + reason : ' · see detail'}` }
  }
  if (stageState === 'running' || stageState === 'awaiting' || stageState === '') {
    const stage = inspectionStageShort(row.stage)
    return { state: 'running', text: `${stage ? stage + ' · ' : ''}${findingsTxt}` }
  }
  return { state: stageState, text: findingsTxt }
}

/** 行卡展示标题兜底（引擎 title 缺失时用；宁显编号不显空）。 */
export function inspectionTitleOf(row: InspectionRowLike): string {
  const title = strOf(row?.title).trim()
  if (title !== '') return title
  const id = strOf(row?.id)
  return id !== '' ? id : ''
}

/* ---------------------------------------------------------------- 左栏分拣（t260915-19） */

/**
 * 左栏巡检行类别徽标词（t260916-15）：行1 小 chip 文本单点——sidebar 项目组行徽标
 * 与兜底组头共用本常量，防「巡检」字面两处漂移；词面=组头既有叫法（宿主口语）。
 */
export const INSPECTION_ROW_BADGE = 'Inspection'

/**
 * 巡检板面端点（t260915-08 建的引擎 ticket-list{kind:inspection} 薄壳）。左栏
 * 分拣制（t260915-19 方案 v2）与中列合流同吃此端点——URL 串收本单点，防两处
 * 字面量漂移（node.ts 注册路径与本串一致性由 UT 源级锚看守）。
 */
export const INSPECTION_TICKETS_URL = '/sandbar-workbench/api/wf/inspection/tickets'

/**
 * 左栏分拣的行防御过滤（端点行=不可信外部输入，与引擎行同纪律）：非数组→[]、
 * 元素非对象或非巡检行（kind/engine 都不标）剔除，其余保序。绝不抛、绝不编造。
 */
export function inspectionSidebarRows(rows: unknown): InspectionRowLike[] {
  if (!Array.isArray(rows)) return []
  return rows.filter((r) => isInspectionRow(r as { kind?: unknown; engine?: unknown }))
}

/**
 * 左栏分拣（t260915-19 方案 v2）：巡检行按行 project（t260915-20 起=ProjectKey
 * SA 直读）归位——命中在册项目 key → byProject[key]；project 空/非串/不在册
 * （20 之前老票、注册表隔离 key、摘除项目）→ unowned（兜底组显式呈现，绝不
 * 静默丢失）。registeredKeys 畸形（非数组）按空集处理；行序输入输出保持端点原序。
 */
export function inspectionSplitByProject(
  rows: unknown,
  registeredKeys: readonly unknown[],
): { byProject: Record<string, InspectionRowLike[]>; unowned: InspectionRowLike[] } {
  const keySet = new Set(
    (Array.isArray(registeredKeys) ? registeredKeys : [])
      .filter((k): k is string => typeof k === 'string' && k !== ''),
  )
  const byProject: Record<string, InspectionRowLike[]> = {}
  const unowned: InspectionRowLike[] = []
  for (const row of inspectionSidebarRows(rows)) {
    const p = strOf((row as { project?: unknown }).project)
    if (p !== '' && keySet.has(p)) (byProject[p] ??= []).push(row)
    else unowned.push(row)
  }
  return { byProject, unowned }
}

/**
 * 左栏巡检降级文案单点：失败=保上次成功快照 + 显式原文提示，绝不吞成空列表
 * （KI-008/t260910-04 R3 同纪律；KI-018① 合规面——错误文案进横幅，不进数据字段）。
 * 词表与中列同源（index.tsx「巡检板面拉取失败，显示上次快照（自动重试中）」同族），
 * 非串 err 走 String() 兜底不抛。
 */
export function inspectionDegradedNote(err: unknown): string {
  const msg = typeof err === 'string' ? err : String(err ?? '')
  return `Inspection panel fetch failed (showing last snapshot, auto-retrying): ${msg}`
}
