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
 *   - 认领行（建票时的 `adopt …` / state=awaiting，带 gen=0 或不带 gen）**不是**
 *     该段的一次入场 → 不进轮次带（否则首段凭空多一格 + 徽章 ×N 撒谎，实报
 *     t260930-09：轻道首段 implement 被画成两轮）；真实重入（rework/retry_qc）
 *     照旧逐轮成格，只剔认领行、不剔「同段首次出现」；
 *   - 轮结局=该轮内最后一条显式态（done/blocked/awaiting-human/rework），
 *     无显式态=running；hover title=该轮 at/结局/reason/phase/handoff 摘要。
 *
 * 畸形输入纪律（外部快照不可信，与 lane-states/lane-durations 同款）：
 *   非串 id/state 的条目跳过；拓扑外 stage id 不建视图不泄漏；全程不抛。
 *   消费本模块的渲染器不得出现任何 dev-lane 专属词（fixture-two-step 对拍锚）。
 */
import { deriveStageStates } from './lane-states.ts'
import type { D2Visual, LaneDetailLike, LaneBlockedHistory } from './lane-states.ts'
import { HANDOFF_KEY_ALIAS, deriveStageDurations, stageTotalMs, fmtDur } from './lane-durations.ts'
import { stageDisplayLabel } from './ui-labels.ts'

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

/** Lane map v5 (t261008-23, mock 261004 612-690): where the time-share width
 *  weight comes from. measured=closed round windows, real wall clock;
 *  running=open round window ticking with nowMs; nominal=not started (the mock
 *  gives unstarted stages a nominal width). Single duration source =
 *  lane-durations (deriveStageDurations + stageTotalMs, the same truth the
 *  stepper / duration badges consume). */
export type LaneDurSource = 'measured' | 'running' | 'nominal'

/** Nominal weight (ms) for an unstarted stage: the mock's NOMINAL constant,
 *  so the first stage cannot swallow the row. */
export const LANE_NOMINAL_MS = 10 * 60_000

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
  /** v5 time-share weight (ms, always present; unstarted = LANE_NOMINAL_MS;
 *  source named by durSource). */
  weightMs: number
  /** Weight source (the renderer only maps weight to width, no policy here). */
  durSource: LaneDurSource
  /** t261009-22 (mock 261004 criterion 4/8): the formatted duration printed
 *  under the label and inside the hover title. Same fmtDur vocabulary as the
 *  stepper's duration badges - no second formatter anywhere. */
  durationText: string
  /** t261009-22 (criterion 3): a bypassed optional stage - still todo while a
 *  topologically later node already ran. Renders as a dashed empty box. */
  skipped?: boolean
}

/** t261009-22 (mock 261004 header, criteria 2/3/5/6): the map's header line -
 *  elapsed total (the same weight sum the widths use, so header and geometry
 *  agree), the current label (`now at …`, parallel members joined with ∥),
 *  `waiting for you` when the arrival human gate is the current segment, and
 *  the axis clocks (start = first parseable timeline `at`, end = start +
 *  elapsed). Malformed/missing timestamps degrade to null clocks - the axis
 *  renders its line without fabricated times. */
export interface LaneMapHeader {
  elapsedMs: number
  elapsedText: string
  nowLabel: string
  waitingForYou: boolean
  startClock: string | null
  endClock: string | null
}

export interface LaneGroupView {
  def: LaneTopologyGroup
  members: LaneNodeView[]
  /** 任一成员 running=并行进行中（虚线框高亮）。 */
  active: boolean
  allDone: boolean
  /** v5 parallel window weight (ms) = max of member weights (mock: window time
 *  = max of the par pair's own durations). */
  windowMs: number
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
  /** t261009-22: the header row (numbers/wording truth lives here; the
   * renderer only draws the legend and copy). */
  header: LaneMapHeader
  /** Current item id (detail.stage pointer first, live state then last item
   * as fallbacks) - the renderer draws the now cursor from this, the same
   * decision that produces nowLabel, so the two can never split. */
  nowItem: string | null
}


/* -- Scene geometry (t261009-53, a value-for-value copy of the mock's
 * laneMap(t); a pure function LaneMap draws). Lives in the model layer: no
 * JSX, node runs it directly in unit tests; the renderer (lane-map.tsx) only
 * draws it. The generic-renderer promise is unchanged: no dev-lane business
 * words here, labels all come from the topology/model. */

/* Scene canvas, the mock's own numbers (laneMap(t)): W=700 PAD=8 RPAD=30,
 * main baseline AY=30 bar h=12, partner track BY=46 h=12, 4px gap, 96 tall
 * viewBox, labels two levels at baseline-4 / baseline-13, x clamped into
 * [20, W+RPAD-20]. */
export const LM_SCENE = {
  W: 700,
  PAD: 8,
  RPAD: 30,
  H: 96,
  AY: 30,
  AH: 12,
  BY: 46,
  BH: 12,
  GAP: 4,
  MINW: 12,
  LABEL_LO: 26,
  LABEL_HI: 17,
  CLAMP_MIN: 20,
  CLAMP_MAX: 710,
} as const

/** Segment fills by kind (criterion 2: agent green / gate blue / human amber). */
const LM_KIND_FILL: Record<LaneNodeKind, string> = {
  agent: 'var(--dsw-derive-success,#4ac26b)',
  gate: 'var(--dsw-derive-accent,#0969da)',
  human: 'var(--dsw-derive-warn,#bf8700)',
}
const LM_TODO_FILL = 'var(--dsw-derive-border,#d0d7de)'
const LM_BLOCKED_FILL = 'var(--dsw-derive-danger,#cf222e)'

/** Human words for the resolution step of the ever-blocked story (vocabulary = lane-states resolvedBy). */
const RESOLVED_HOW: Record<string, string> = {
  rerun: 'stage rerun completed',
  advanced: 'workflow advanced to later stages',
  closed: 'ticket closed',
}

/** The ever-blocked story (when / why / how resolved): shared by the badge and the segment hover title. */
function everBlockedTitle(h: LaneBlockedHistory): string {
  const bits = [`Blocked ${h.passes.length}× before`]
  if (h.last.at) bits.push(h.last.at)
  if (h.last.reason) bits.push(h.last.reason)
  if (h.last.gen !== undefined) bits.push(`Round ${h.last.gen}`)
  if (h.resolved) {
    bits.push(`Resolved (${RESOLVED_HOW[h.resolvedBy ?? ''] || 'resolved'}${h.resolvedAt ? `: ${h.resolvedAt}` : ''})`)
  }
  return bits.join(' · ')
}

/** Only a resolved blocked history earns the ever-blocked badge (t260916-04: a currently blocked stage carries none). */
function everOf(nv: LaneNodeView): LaneBlockedHistory | undefined {
  const h = nv.blockedHistory
  return h && h.resolved === true && h.passes.length > 0 && nv.vis === 'done' ? h : undefined
}

/** Segment hover title (criterion 8): name · who · duration · rounds · blocked
 *  history. The per-round evidence (each round's reason) rides here too - the
 *  round chips are retired (design criterion 7: rework is carried by ×N). */
function segmentTitle(nv: LaneNodeView): string {
  const bits = [`${stageDisplayLabel(nv.node.id, nv.node.label)} · ${nv.node.role} · ${nv.node.kind}`]
  if (nv.node.optional) bits.push(nv.node.optional)
  bits.push(nv.durationText)
  bits.push(`${nv.rounds.length} round${nv.rounds.length === 1 ? '' : 's'}`)
  if (nv.rounds.length > 1) {
    bits.push(nv.rounds.map(r => `R${r.gen} ${r.state}${r.reason ? `: ${r.reason}` : ''}`).join(' / '))
  }
  const ever = everOf(nv)
  if (ever) bits.push(everBlockedTitle(ever))
  return bits.join(' · ')
}

/* -- Scene (pure geometry; unit tests run it directly, no DOM). -- */

export interface LaneSceneBar {
  /** Unique key inside the scene (stage id; the main and the partner bar of one stage each get one). */
  id: string
  stageId: string
  track: 'main' | 'partner'
  x: number
  y: number
  w: number
  h: number
  fill: string
  fillOpacity: number
  /** skipped = dashed empty box (fill none + dashed stroke). */
  dashed: boolean
  kind: LaneNodeKind | null
  vis: D2Visual | null
  skipped: boolean
  now: boolean
  /** Human gate: a diamond at the bar head (criterion 5). */
  diamond: boolean
  /** Resolved blocked history (the t260916-04 badge contract). */
  ever: boolean
  /** v5 weight (the data-weight-ms semantic anchor; t261008-23 does not regress). */
  weightMs: number
  title: string
}

export interface LaneSceneLabel {
  text: string
  x: number
  y: number
  track: 'main' | 'partner'
  /** Two alternating levels (0 = baseline-4, 1 = baseline-13); partner labels are always 0. */
  level: 0 | 1
  anchor: 'middle' | 'start'
  now: boolean
  /** Conditional-stage note (tspan.wb-lm-opt). */
  opt?: string
  /** Rounds badge xN (tspan.wb-lm-round). */
  roundBadge?: string
  /** Ever-blocked badge story (the title of tspan.wb-lm-ever). */
  everTitle?: string
}

export interface LaneSceneWindow {
  x: number
  y: number
  w: number
  h: number
  groupId: string
  active: boolean
  allDone: boolean
  windowMs: number
}

export interface LaneScene {
  width: number
  height: number
  bars: LaneSceneBar[]
  labels: LaneSceneLabel[]
  /** Dotted leaders: a label drops to its bar top. */
  leaders: Array<{ x: number; y1: number; y2: number }>
  windows: LaneSceneWindow[]
  /** Parallel mark positions. */
  parMarks: Array<{ x: number; y: number }>
  diamonds: Array<{ x: number; y: number }>
  /** Now cursor: a dashed vertical line spanning both tracks (null = no current segment). */
  cursor: { x: number; y1: number; y2: number } | null
}

function fillOf(nv: LaneNodeView): { fill: string; fillOpacity: number; dashed: boolean } {
  if (nv.skipped) return { fill: 'none', fillOpacity: 1, dashed: true }
  if (nv.vis === 'blocked') return { fill: LM_BLOCKED_FILL, fillOpacity: 1, dashed: false }
  if (nv.vis === 'todo') return { fill: LM_TODO_FILL, fillOpacity: 0.35, dashed: false }
  return { fill: LM_KIND_FILL[nv.node.kind], fillOpacity: nv.vis === 'done' ? 0.22 : 1, dashed: false }
}

function barOf(nv: LaneNodeView, x: number, y: number, w: number, h: number, track: 'main' | 'partner', now: boolean): LaneSceneBar {
  const f = fillOf(nv)
  const ever = everOf(nv)
  return {
    id: track === 'main' ? nv.node.id : `${nv.node.id}#partner`,
    stageId: nv.node.id,
    track,
    x,
    y,
    w,
    h,
    fill: f.fill,
    fillOpacity: f.fillOpacity,
    dashed: f.dashed,
    kind: nv.node.kind,
    vis: nv.vis,
    skipped: Boolean(nv.skipped),
    now,
    diamond: nv.node.kind === 'human',
    /** The t260916-04 face stays: an ever-blocked stage carries data-ever-blocked=true on its node. */
    ever: Boolean(ever),
    weightMs: nv.weightMs,
    title: segmentTitle(nv),
  }
}

function labelBit(nv: LaneNodeView): string {
  const durBit = nv.durSource === 'nominal' ? '' : nv.durationText
  return durBit ? ` ${durBit}${nv.badge ? ` · ${nv.badge}` : ''}` : ''
}

/** Main label: name + `duration · ×N` in the same caption (criterion 4/7);
 *  done/running stages print their duration, unstarted prints the name only,
 *  the current stage appends `now` (the mock's wording). */
function mainLabelOf(nv: LaneNodeView, i: number, now: boolean): LaneSceneLabel {
  const ever = everOf(nv)
  return {
    text: `${stageDisplayLabel(nv.node.id, nv.node.label)}${now ? ' now' : labelBit(nv)}`,
    x: 0,
    y: i % 2 === 0 ? LM_SCENE.LABEL_LO : LM_SCENE.LABEL_HI,
    track: 'main',
    level: i % 2 === 0 ? 0 : 1,
    anchor: 'middle',
    now,
    opt: nv.node.optional || undefined,
    roundBadge: nv.badge || undefined,
    everTitle: ever ? everBlockedTitle(ever) : undefined,
  }
}

/** Partner band width (%): min(1, partner/window) x 100 (the mock line ~677 clamp). */
function lmBandPct(partnerMs: number, windowMs: number): number {
  if (!(windowMs > 0)) return 100
  return Math.min(1, partnerMs / windowMs) * 100
}

/* v5 time-share geometry (t261008-23, mock 261004 612-690): the fixed floor
 * keeps narrow stages readable; the renderer only maps weight to width. */
const LM_MIN_PCT = 6

/** v5 time-share main lane: band width = MIN_PCT + flex x (weight/totalWeight)
 *  (the mock's own formula; t261008-23, unchanged). */
function lmWidths(model: LaneMapModel): Array<{ id: string; weightMs: number; pct: number }> {
  const weights = model.items.map(it => ({
    id: it.id,
    weightMs: it.kind === 'group' ? (model.groups[it.id]?.windowMs ?? 0) : (model.nodes[it.id]?.weightMs ?? 0),
  }))
  const total = weights.reduce((a, r) => a + r.weightMs, 0)
  const flex = 100 - LM_MIN_PCT * weights.length
  return weights.map(w => ({
    ...w,
    pct: LM_MIN_PCT + (total > 0 ? flex * (w.weightMs / total) : flex / Math.max(1, weights.length)),
  }))
}

/**
 * Model -> SVG scene (a pure function; LaneMap only draws it). The geometry
 * copies the mock's laneMap(t) value for value: 12-tall slim bars on one
 * baseline, two floating label levels (middle anchor, clamped into
 * [20, W+RPAD-20]), dotted leaders, the diamond at the bar head, the partner
 * on a second track (one dashed window around both tracks + the parallel
 * mark), the now cursor spanning both tracks.
 */
export function laneMapScene(model: LaneMapModel): LaneScene {
  const { W, PAD, RPAD, AY, AH, BY, BH, GAP, MINW, CLAMP_MIN, CLAMP_MAX } = LM_SCENE
  const usable = W - PAD - RPAD
  const pctOf = new Map(lmWidths(model).map(w => [w.id, w.pct]))
  const bars: LaneSceneBar[] = []
  const labels: LaneSceneLabel[] = []
  const leaders: LaneScene['leaders'] = []
  const windows: LaneSceneWindow[] = []
  const parMarks: LaneScene['parMarks'] = []
  const diamonds: LaneScene['diamonds'] = []
  let cursor: LaneScene['cursor'] = null
  let x = PAD
  model.items.forEach((item, i) => {
    const w = Math.max(0, (usable * (pctOf.get(item.id) ?? 0)) / 100)
    const now = model.nowItem === item.id
    if (item.kind === 'group') {
      const g = model.groups[item.id]
      windows.push({
        x: x - 4,
        y: AY - 4,
        w: w + 8,
        h: (BY + BH) - AY + 8,
        groupId: g.def.id,
        active: g.active,
        allDone: g.allDone,
        windowMs: g.windowMs,
      })
      parMarks.push({ x: x + 5, y: BY + BH - 1 })
      const head = g.members[0]
      const partner = g.members[1]
      bars.push(barOf(head, x, AY, w, AH, 'main', now))
      labels.push(mainLabelOf(head, i, now))
      const pw = Math.max(MINW, (w * lmBandPct(partner.weightMs, g.windowMs)) / 100)
      bars.push(barOf(partner, x, BY, pw, BH, 'partner', partner.vis === 'running'))
      const pever = everOf(partner)
      labels.push({
        text: `${stageDisplayLabel(partner.node.id, partner.node.label)}${partner.vis === 'running' ? ' now' : labelBit(partner)}`,
        x: x + 6,
        y: BY + BH + 9,
        track: 'partner',
        level: 0,
        anchor: 'start',
        now: partner.vis === 'running',
        opt: partner.node.optional || undefined,
        roundBadge: partner.badge || undefined,
        everTitle: pever ? everBlockedTitle(pever) : undefined,
      })
    } else {
      const nv = model.nodes[item.id]
      bars.push(barOf(nv, x, AY, w, AH, 'main', now))
      labels.push(mainLabelOf(nv, i, now))
      if (nv.node.kind === 'human') diamonds.push({ x: x + 5, y: AY + AH / 2 })
    }
    const cx = x + w / 2
    // Clamp + leader for the main (head) label; the partner label sits at the
    // window head with its own anchor (the mock never clamps it).
    const headLabel = item.kind === 'group' ? labels[labels.length - 2] : labels[labels.length - 1]
    headLabel.x = Math.max(CLAMP_MIN, Math.min(cx, CLAMP_MAX))
    leaders.push({ x: cx, y1: headLabel.y + 2.5, y2: AY - 1 })
    if (now) cursor = { x: x + w, y1: AY - 8, y2: BY + BH + 3 }
    x += w + GAP
  })
  return { width: W + RPAD, height: LM_SCENE.H, bars, labels, leaders, windows, parMarks, diamonds, cursor }
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
  /** Closed-ticket settle fallback (epoch seconds; same source as lane-durations
 *  closedTs, same shape useStageDurations already feeds). */
  updated?: unknown
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

/** t261009-22 axis clock: first parseable `at` in timeline order (ISO strings
 *  per the lane-durations contract); malformed entries are skipped, none
 *  parseable -> null (the axis renders without times, never a made-up clock). */
function firstClockMs(detail: DetailLike): number | null {
  if (!Array.isArray(detail.timeline)) return null
  for (const e of detail.timeline) {
    if (e === null || typeof e !== 'object') continue
    const at = asString((e as Record<string, unknown>).at)
    if (!at) continue
    const ms = Date.parse(at)
    if (Number.isFinite(ms)) return ms
  }
  return null
}

/** Local hh:mm (the mock's own minute-of-day rendering, epoch flavour). */
function hhmm(ms: number): string {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

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

/**
 * 认领行（adopt）识别：建票时引擎在实例初始化里写的第一条条目
 * （base.py:761 / dev_lane.py:980 的 `_mark(first.id, "awaiting", "adopt …")`）
 * 把票面初段指向本道首段，**不是**该段的入场，不得计成一轮。
 *
 * 识别只认形状，不认位置（「第几个出现的」不是判据）：
 *   state === 'awaiting' 且 reason 以词 'adopt' 起（引擎英文标识，两种模板同词
 *   ——dev-lane「adopt dev-lane（步=…）」/ 基类「adopt v2（模版=…）」）。
 * 形状不认识（awaiting 但 reason 不是 adopt 起头、或 reason 缺省）→ **保留现行口径**
 * （如实成轮）：宁可多一格可见的疑点，也不静默丢行（畸形输入纪律）。
 * 真实重入（rework 回打 / retry_qc 重跑）落的是 running/rework/done，形状不撞。
 */
function isAdoptionEntry(e: TimelineEntryLike): boolean {
  return e.state === 'awaiting' && /^adopt\b/.test(e.reason ?? '')
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

/** 段→轮次带。gen 键在场按 gen 分组；缺省回退「running mark 切轮」计数口径。
 *  认领行（adopt）先剔除——它既会自成 gen=0 的一桶（新票），也会在无 gen 的
 *  老票上被当成「首轮」，两种形态都会给首段凭空多出一格（实报 t260930-09）。 */
export function deriveRounds(stageId: string, detail: DetailLike): LaneRound[] {
  const entries = timelineOf(detail).filter(e => e.stage === stageId && !isAdoptionEntry(e))
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
 *
 * opts.nowMs: determinism anchor for the v5 weights (open running windows
 * tick against it). Defaults to Date.now(); tests inject a fixed value so the
 * proportionality assertion is checked against the very weights the model
 * used (review comment 5).
 */
export function buildLaneMap(
  topologyRaw: unknown,
  detailRaw: unknown,
  opts?: { nowMs?: number },
): LaneMapModel | null {
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
  // v5 time-share weights (t261008-23): single source = lane-durations. Fault
 // modes inherited from the borrowed implementation (review comment 3):
 // missing handoffs / alias keys / open window without now are already covered
 // by its settle chain; this layer only adds malformed timeline -> nominal
 // weight without throwing. No second duration policy.
  const nowMs = opts?.nowMs ?? Date.now()
  const durs = deriveStageDurations(
    detail.timeline as Parameters<typeof deriveStageDurations>[0],
    order,
    Array.isArray(detail.handoffs) ? (detail.handoffs as Parameters<typeof deriveStageDurations>[2]) : null,
    {
      nowMs,
      closedTs: detail.status === 'closed' && typeof detail.updated === 'number' && Number.isFinite(detail.updated)
        ? detail.updated
        : null,
    },
  )
  for (const n of topology.nodes) {
    const rounds = deriveRounds(n.id, detail)
    const bh = derived.blockedHistory[n.id]
    const d = durs[n.id]
    let weightMs = LANE_NOMINAL_MS
    let durSource: LaneDurSource = 'nominal'
    if (d !== undefined) {
      const total = stageTotalMs(d, nowMs)
      if (total !== null) {
        weightMs = total
        durSource = d.rounds.some(r => r.toMs === null) ? 'running' : 'measured'
      }
    }
    nodes[n.id] = {
      node: n,
      vis: derived.states[n.id] ?? 'todo',
      rounds,
      badge: rounds.length > 1 ? `×${rounds.length}` : '',
      weightMs,
      durSource,
      durationText: fmtDur(weightMs),
      ...((n.optional !== undefined
        && (derived.states[n.id] ?? 'todo') === 'todo'
        && order.slice(order.indexOf(n.id) + 1)
          .some(id => (derived.states[id] ?? 'todo') === 'done' || (derived.states[id] ?? 'todo') === 'running'))
        ? { skipped: true } : {}),
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
      windowMs: Math.max(...members.map(m => m.weightMs)),
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

  // t261009-22 header: elapsed = the very weight sum the widths are drawn
  // from (header and geometry cannot disagree); the current item is the one
  // carrying a live node (running / awaiting-human / blocked), else the last
  // item (the mock's own fallback). Clocks: first parseable timeline `at`,
  // end = start + elapsed; nothing parseable -> null clocks (no made-up time).
  const itemWeight = (id: string): number => {
    const g = groups[id]
    return g ? g.windowMs : (nodes[id]?.weightMs ?? 0)
  }
  const elapsedMs = items.reduce((a, it) => a + itemWeight(it.id), 0)
  const itemMembers = (id: string): LaneNodeView[] => {
    const g = groups[id]
    return g ? g.members : [nodes[id]].filter(Boolean)
  }
  const isLive = (m: LaneNodeView): boolean =>
    m.vis === 'running' || m.vis === 'awaiting-human' || m.vis === 'blocked'
  // Current item: the one carrying the engine's stage pointer first (detail.stage
  // is the truth for "now at"); the states derivation can keep earlier stages
  // conservatively "running" when a ticket has no explicit done marks, so the
  // live-state scan is only the fallback; last item is the terminal fallback.
  const ptr = asString(detail.stage)
  const curItem = (ptr ? items.find(it => itemMembers(it.id).some(m => m.node.id === ptr)) : undefined)
    ?? items.find(it => itemMembers(it.id).some(isLive))
    ?? items[items.length - 1]
  const nowLabel = curItem
    ? itemMembers(curItem.id).map(m => stageDisplayLabel(m.node.id, m.node.label)).join(' ∥ ')
    : ''
  const nowItem = curItem?.id ?? null
  const startMs = firstClockMs(detail)
  const header: LaneMapHeader = {
    elapsedMs,
    elapsedText: fmtDur(elapsedMs),
    nowLabel,
    waitingForYou: humanGateActive !== null,
    startClock: startMs === null ? null : hhmm(startMs),
    endClock: startMs === null ? null : hhmm(startMs + elapsedMs),
  }
  return {
    topology,
    items,
    nodes,
    groups,
    humanGateActive,
    closed: detail.status === 'closed',
    header,
    nowItem,
  }
}
