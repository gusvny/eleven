/**
 * lane-map-model —— 真泳道图（拓扑驱动）视图模型（t260915-05，mock ③/④）。
 *
 * 设计样张：notes/discussions/260904-ticket-detail-ui-mock.html 屏③/④
 * （并行双道虚线框＋轮次徽章逐轮格 hover 证据＋人门虚线圈＋不画返工弧；
 * callout F/G：渲染器只认「节点+边+kind」，标签全部来自拓扑，零业务词）。
 *
 * 数据源：
 *   - topology：模板拓扑导出契约（引擎 template_topology.py topology-v1，经
 *     workflow.py list / ticket show 投影面透传）。null/畸形 → buildLaneMap 返回
 *     null = 调用方回落现行线性步骤条（零回归降级锚）。
 *   - detail：工单详情（ticket show 投影面）。消费 timeline（gen/phase 键，
 *     t260915-01 ③）、gens、handoffs（gen 键）、results、checks、gate_runs、
 *     meta.parallel_stages/parallel_phase、status/stage/stage_state；
 *     t260916-04 起并消费受阻史（blockedHistory：解除判定住 lane-states 推导层，
 *     拓扑并行组透传给它做兄弟段判定；节点视图携史供渲染层出「曾受阻」角标）。
 *
 * 轮次口径（与 lane-durations 的轮窗同族，此处取「轮格」语义）：
 *   - 引擎 timeline 条目带 gen（门开的新票）→ 按 gen 分组，一轮一格；
 *   - 老票无 gen → 回退「每条 running mark 开新轮」的计数口径
 *     （lane-durations 同款真值表），轮内证据无 gen 标注=如实缺省；
 *   - 轮结局=该轮内最后一条显式态（done/blocked/awaiting-human/rework），
 *     无显式态=running；hover title=该轮 at/结局/reason/phase/handoff 摘要。
 *
 * 畸形输入纪律（外部快照不可信，与 lane-states/lane-durations 同款）：
 *   非串 id/state 的条目跳过；拓扑外 stage id 不建视图不泄漏；全程不抛。
 *   消费本模块的渲染器不得出现任何 dev-lane 专属词（fixture-two-step 对拍锚）。
 */
import { deriveStageStates } from './lane-states.ts'
import type { D2Visual, LaneDetailLike, LaneBlockedHistory } from './lane-states.ts'
import { HANDOFF_KEY_ALIAS } from './lane-durations.ts'

/* ── 拓扑契约（引擎 template_topology.py topology-v1） ── */

export type LaneNodeKind = 'agent' | 'gate' | 'human'

export interface LaneTopologyNode {
  id: string
  label: string
  role: string
  kind: LaneNodeKind
  parts: string[]
  /** 条件段注记（值=给人读的短条件说明，如「仅 UI 票」）；缺省=必经段。 */
  optional?: string
}

export interface LaneTopologyGroup {
  id: string
  members: string[]
  /** 并行相位名（与 meta.parallel_phase / timeline phase 键同词表）。 */
  phase: string
}

export interface LaneTopology {
  version?: string
  template: string
  name?: string
  nodes: LaneTopologyNode[]
  edges: string[][]
  groups: LaneTopologyGroup[]
}

/** kind 图标（渲染器唯一认识的视觉词，零业务语义）。 */
export const LANE_KIND_ICON: Record<LaneNodeKind, string> = {
  agent: '🤖',
  gate: '✓',
  human: '👤',
}

/* ── 视图模型 ── */

/** 一个轮格（同段第 n 次进入）。 */
export interface LaneRound {
  /** 展示轮次（1 起）。引擎 gen 直接用；老票回退=进入序号。 */
  gen: number
  /** 轮结局：显式态（done/blocked/awaiting-human/rework）或 running。 */
  state: D2Visual | 'rework'
  /** 进入时刻（timeline running 条目 at，原样）。 */
  at?: string
  /** 轮结局 reason（打回原因/证据行，原样不翻译）。 */
  reason?: string
  /** 并行相位（分叉期轮才有）。 */
  phase?: string
  /** 同轮 handoff 摘要（完成交报告）。 */
  handoffSummary?: string
}

/** 一个拓扑节点的视图。 */
export interface LaneNodeView {
  node: LaneTopologyNode
  vis: D2Visual
  rounds: LaneRound[]
  /** 轮次徽章文案（rounds>1 → ×N；单轮空串）。 */
  badge: string
  /** 受阻史与当前性判定（t260916-04）：resolved=true 且 vis='done' → 渲染层出
   *  「曾受阻」角标+hover 经过；无受阻史的段缺省（键不存在）。 */
  blockedHistory?: LaneBlockedHistory
}

export interface LaneGroupView {
  def: LaneTopologyGroup
  members: LaneNodeView[]
  /** 任一成员 running=并行进行中（虚线框高亮）。 */
  active: boolean
  allDone: boolean
}

export interface LaneMapModel {
  topology: LaneTopology
  /** 主道渲染序：节点与并行组交替（组在声明序首个成员处展开）。 */
  items: Array<{ kind: 'node'; id: string } | { kind: 'group'; id: string }>
  nodes: Record<string, LaneNodeView>
  groups: Record<string, LaneGroupView>
  /** 到站人门节点 id（kind=human 且 awaiting-human）；无=null。 */
  humanGateActive: string | null
  closed: boolean
}

/* ── 输入校形（畸形防御的最小结构） ── */

interface DetailLike {
  status?: string
  stage?: string | null
  stage_state?: string
  timeline?: unknown
  results?: unknown
  checks?: unknown
  handoffs?: unknown
  gens?: unknown
  parallel_stages?: unknown
  meta?: { parallel_stages?: unknown; parallel_phase?: unknown } | null
}

function asString(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '') : []
}

const EXPLICIT_STATES = new Set(['done', 'blocked', 'awaiting-human', 'rework'])

/* ── 拓扑清洗 ── */

/** 清洗原始拓扑；不可救（非对象/无合法节点）→ null=调用方回落线性步骤条。 */
export function parseTopology(raw: unknown): LaneTopology | null {
  if (raw === null || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  if (!Array.isArray(r.nodes)) return null
  const nodes: LaneTopologyNode[] = []
  const ids = new Set<string>()
  for (const n of r.nodes) {
    if (n === null || typeof n !== 'object') continue
    const o = n as Record<string, unknown>
    const id = asString(o.id)
    const label = asString(o.label)
    const kind = asString(o.kind)
    if (!id || !label) continue
    if (kind !== 'agent' && kind !== 'gate' && kind !== 'human') continue
    if (ids.has(id)) continue
    ids.add(id)
    nodes.push({
      id, label, kind,
      role: asString(o.role),
      parts: asStringArray(o.parts),
      ...(asString(o.optional) ? { optional: asString(o.optional) } : {}),
    })
  }
  if (nodes.length === 0) return null
  const edges: string[][] = []
  if (Array.isArray(r.edges)) {
    for (const e of r.edges) {
      if (!Array.isArray(e) || e.length !== 2) continue
      const [a, b] = e
      if (typeof a === 'string' && typeof b === 'string' && ids.has(a) && ids.has(b)) {
        edges.push([a, b])
      }
    }
  }
  const groups: LaneTopologyGroup[] = []
  if (Array.isArray(r.groups)) {
    for (const g of r.groups) {
      if (g === null || typeof g !== 'object') continue
      const o = g as Record<string, unknown>
      const id = asString(o.id)
      const members = asStringArray(o.members).filter(m => ids.has(m))
      if (id && members.length >= 2) {
        groups.push({ id, members, phase: asString(o.phase) })
      }
    }
  }
  return {
    version: asString(r.version) || undefined,
    template: asString(r.template) || 'unknown',
    name: asString(r.name) || undefined,
    nodes,
    edges,
    groups,
  }
}

/* ── 轮次带推导 ── */

interface TimelineEntryLike { at?: string; stage?: string; state?: string; reason?: string; gen?: number; phase?: string }

function timelineOf(detail: DetailLike): TimelineEntryLike[] {
  if (!Array.isArray(detail.timeline)) return []
  const out: TimelineEntryLike[] = []
  for (const e of detail.timeline) {
    if (e === null || typeof e !== 'object') continue
    const o = e as Record<string, unknown>
    const stage = asString(o.stage)
    const state = asString(o.state)
    if (!stage || !state) continue
    out.push({
      stage, state,
      at: asString(o.at) || undefined,
      reason: asString(o.reason) || undefined,
      gen: typeof o.gen === 'number' && Number.isFinite(o.gen) ? o.gen : undefined,
      phase: asString(o.phase) || undefined,
    })
  }
  return out
}

function handoffsOf(detail: DetailLike): Array<{ stage: string; summary?: string; gen?: number }> {
  if (!Array.isArray(detail.handoffs)) return []
  const out: Array<{ stage: string; summary?: string; gen?: number }> = []
  for (const h of detail.handoffs) {
    if (h === null || typeof h !== 'object') continue
    const o = h as Record<string, unknown>
    const stage = asString(o.stage)
    if (!stage) continue
    out.push({
      stage,
      summary: asString(o.summary) || undefined,
      gen: typeof o.gen === 'number' && Number.isFinite(o.gen) ? o.gen : undefined,
    })
  }
  return out
}

/** 段→轮次带。gen 键在场按 gen 分组；缺省回退「running mark 切轮」计数口径。 */
export function deriveRounds(stageId: string, detail: DetailLike): LaneRound[] {
  const entries = timelineOf(detail).filter(e => e.stage === stageId)
  if (entries.length === 0) return []
  const hasGen = entries.some(e => typeof e.gen === 'number')
  const buckets: TimelineEntryLike[][] = []
  if (hasGen) {
    const byGen = new Map<number, TimelineEntryLike[]>()
    for (const e of entries) {
      const g = typeof e.gen === 'number' ? e.gen : 1
      if (!byGen.has(g)) byGen.set(g, [])
      byGen.get(g)!.push(e)
    }
    for (const g of [...byGen.keys()].sort((a, b) => a - b)) buckets.push(byGen.get(g)!)
  } else {
    let cur: TimelineEntryLike[] = []
    for (const e of entries) {
      if (e.state === 'running' && cur.length > 0) {
        buckets.push(cur)
        cur = []
      }
      cur.push(e)
    }
    if (cur.length > 0) buckets.push(cur)
  }
  const handoffs = handoffsOf(detail).filter(h => (HANDOFF_KEY_ALIAS[h.stage] || h.stage) === stageId)
  let handoffCursor = 0 // 同段 handoff 按序消费：一轮一条（无 gen 的老票不重复匹配第一条）
  const rounds: LaneRound[] = []
  buckets.forEach((bucket, i) => {
    let state: LaneRound['state'] = 'running'
    let reason: string | undefined
    for (const e of bucket) {
      if (EXPLICIT_STATES.has(e.state)) {
        state = e.state as LaneRound['state']
        reason = e.reason
      }
    }
    const first = bucket[0]
    const gen = typeof first.gen === 'number' ? first.gen : i + 1
    let handoffSummary: string | undefined
    while (handoffCursor < handoffs.length) {
      const h = handoffs[handoffCursor]
      if (typeof h.gen === 'number' && h.gen !== gen) break // 带 gen：只匹配同轮
      handoffSummary = h.summary
      handoffCursor += 1
      break
    }
    rounds.push({
      gen,
      state,
      at: first.at,
      reason,
      phase: bucket.find(e => e.phase)?.phase,
      handoffSummary,
    })
  })
  return rounds
}

/* ── 检查明细区（mock ① ck-rows：gate_runs 逐条渲染） ── */

export interface CheckRowView {
  green: boolean
  item: string
  detail?: string
  checkId?: string
  reasonCode?: string
  files?: string[]
  nextAction?: string
}

export interface GateRunView {
  stage: string
  label: string
  green: boolean
  redCount: number
  gen?: number
  conflict?: boolean
  rows: CheckRowView[]
}

/** gate_runs → 检查明细区行模型（最新在前）。畸形条目逐条跳过不抛。 */
export function buildChecksDetail(detail: unknown): GateRunView[] {
  if (detail === null || typeof detail !== 'object') return []
  const runs = (detail as Record<string, unknown>).gate_runs
  if (!Array.isArray(runs)) return []
  const out: GateRunView[] = []
  for (const run of [...runs].reverse()) {
    if (run === null || typeof run !== 'object') continue
    const o = run as Record<string, unknown>
    const stage = asString(o.stage)
    if (!stage) continue
    const rows: CheckRowView[] = []
    if (Array.isArray(o.checks)) {
      for (const c of o.checks) {
        if (c === null || typeof c !== 'object') continue
        const co = c as Record<string, unknown>
        const item = asString(co.item)
        const green = co.green === true
        const checkId = asString(co.id) || undefined
        if (green && !item && !checkId) continue // 无字绿项无信息量
        rows.push({
          green,
          item: item || checkId || '', // 绿项常只带 id（agent_activities D4 口径）——id 即可读锚
          detail: asString(co.detail) || undefined,
          checkId,
          reasonCode: asString(co.reason_code) || undefined,
          files: asStringArray(co.files),
          nextAction: asString(co.next_action) || undefined,
        })
      }
    }
    out.push({
      stage,
      label: asString(o.label) || stage,
      green: o.green === true,
      redCount: typeof o.red_count === 'number' && Number.isFinite(o.red_count) ? o.red_count : rows.filter(r => !r.green).length,
      gen: typeof o.gen === 'number' && Number.isFinite(o.gen) ? o.gen : undefined,
      conflict: o.conflict === true,
      rows,
    })
  }
  return out
}

/* ── 主模型 ── */

/**
 * 构建泳道图视图模型。返回 null = 拓扑不可用，调用方回落现行线性步骤条
 * （零回归降级锚：老 host / 未声明拓扑的模板 / 畸形契约面）。
 */
export function buildLaneMap(topologyRaw: unknown, detailRaw: unknown): LaneMapModel | null {
  const topology = parseTopology(topologyRaw)
  if (!topology) return null
  const detail: DetailLike = (detailRaw !== null && typeof detailRaw === 'object')
    ? detailRaw as DetailLike
    : {}

  const order = topology.nodes.map(n => n.id)
  // 复用既有活跃步/视觉态推导（并行真源 meta.parallel_stages 双显语义不另起炉灶）；
  // timeline/results/checks 原样透传（数组形态合法性由 lane-states 自身纪律兜底）。
  const laneDetail = {
    status: detail.status,
    stage: detail.stage,
    stage_state: detail.stage_state,
    timeline: Array.isArray(detail.timeline) ? detail.timeline : null,
    results: (detail.results !== null && typeof detail.results === 'object')
      ? detail.results as Record<string, { status?: string; gen?: number }>
      : undefined,
    checks: (detail.checks !== null && typeof detail.checks === 'object')
      ? detail.checks as Record<string, Array<{ item: string; done: boolean; by?: string }>>
      : undefined,
    parallel_stages: Array.isArray(detail.parallel_stages) ? detail.parallel_stages as string[] : undefined,
    meta: detail.meta as LaneDetailLike['meta'],
  }
  // t260916-04：拓扑并行组透传给受阻解除判定（泳道图面全语义；兄弟段干完≠推进）。
  const derived = deriveStageStates(laneDetail, order, { groups: topology.groups.map(g => g.members) })

  const nodes: Record<string, LaneNodeView> = {}
  for (const n of topology.nodes) {
    const rounds = deriveRounds(n.id, detail)
    const bh = derived.blockedHistory[n.id]
    nodes[n.id] = {
      node: n,
      vis: derived.states[n.id] ?? 'todo',
      rounds,
      badge: rounds.length > 1 ? `×${rounds.length}` : '',
      ...(bh ? { blockedHistory: bh } : {}),
    }
  }

  // 组视图 + 主道渲染序（组在声明序首个成员处展开为虚线框，其余成员跳过）
  const groups: Record<string, LaneGroupView> = {}
  for (const g of topology.groups) {
    const members = g.members.map(id => nodes[id]).filter(Boolean)
    if (members.length < 2) continue
    groups[g.id] = {
      def: g,
      members,
      active: members.some(m => m.vis === 'running'),
      allDone: members.every(m => m.vis === 'done'),
    }
  }
  const groupOf: Record<string, string> = {}
  for (const g of Object.values(groups)) {
    for (const m of g.members) groupOf[m.node.id] = g.def.id
  }
  const emitted = new Set<string>()
  const items: LaneMapModel['items'] = []
  for (const n of topology.nodes) {
    const gid = groupOf[n.id]
    if (gid) {
      if (!emitted.has(gid)) {
        emitted.add(gid)
        items.push({ kind: 'group', id: gid })
      }
    } else {
      items.push({ kind: 'node', id: n.id })
    }
  }

  const humanGateActive = topology.nodes.find(n => n.kind === 'human' && nodes[n.id].vis === 'awaiting-human')?.id ?? null
  return {
    topology,
    items,
    nodes,
    groups,
    humanGateActive,
    closed: detail.status === 'closed',
  }
}
