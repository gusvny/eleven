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
 * viewBox, labels on rows at baseline-4 / baseline-13 (further rows step up by
 * LM_LABEL.STEP when captions would collide, growing the height), the caption
 * BOX clamped into [20, W+RPAD-20]. */
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

/** Partner caption baseline: below the partner track (its own row, never clamped
 *  into the main label band; extra partner rows step down from here). Exported
 *  so the placement battery can re-derive every caption row it asserts on. */
export const LM_PARTNER_LABEL_Y = LM_SCENE.BY + LM_SCENE.BH + 9

/* -- Label placement (t261028-22; host report 261028: the lane map's captions
 * overlapped and became unreadable) -------------------------------------------
 * The old placement put caption `i` on level `i % 2` and never compared label
 * BOXES, so two segments close together (several short steps, or several steps
 * that ran quickly) drew their captions on top of each other and two levels
 * could not separate them.
 *
 * laneMapScene must stay a PURE function of the model (no DOM, no
 * getBoundingClientRect, no timers), so the caption box is ESTIMATED from the
 * caption text and the label font size with conservative per-character
 * advances (see LM_LABEL). Placement then asks, for level 0, 1, 2, ... up to
 * LM_LABEL.MAX_LEVEL, whether that row still has room for the whole box (the
 * canvas band minus every box already placed on an overlapping row, minus
 * LM_LABEL.MIN_GAP) and takes the LOWEST row that does. When no row has room,
 * the caption is shortened to the roomiest row and the FULL caption rides in
 * the label's hover title, so no data is dropped. The scene height follows the
 * rows actually used, so a tall stack still fits the viewBox. */

export const LM_LABEL = {
  /** Main caption font size in px. MUST equal `.wb-lm-label{font-size}` in
   *  src/client/index.tsx - the CSS is the truth and this constant mirrors it. */
  FONT_MAIN: 8,
  /** Partner caption font size in px; mirrors `.wb-lm-plabel{font-size}`. */
  FONT_PARTNER: 7.5,
  /** Advance of one wide glyph (CJK / fullwidth / the ellipsis) in em: 1.00 em
   *  = the font size, because those glyphs are one square. */
  WIDE_EM: 1,
  /** Advance of every other glyph in em: 0.58. A sans-serif mean at 8px sits
   *  near 0.50 em; 0.58 is the conservative bound, and over-estimating only
   *  buys an extra level - never an overlap. */
  NARROW_EM: 0.58,
  /** Caption box height above the baseline (cap height + ascender), in em. */
  ASCENT_EM: 0.78,
  /** Caption box depth below the baseline (descender), in em. */
  DESCENT_EM: 0.26,
  /** Vertical distance between two caption rows in px: 9 keeps adjacent rows'
   *  boxes disjoint (a row is 8.32px tall at the 8px caption size). */
  STEP: 9,
  /** Highest level a caption may climb: levels 0..5 = six stacked rows. Six
   *  rows absorb a fully packed map of ~4.5-caption-wide steps, so a crowded
   *  map costs vertical space (the scene grows) instead of an unreadable
   *  overlap; beyond that a caption is shortened, never dropped. */
  MAX_LEVEL: 5,
  /** Smallest horizontal gap kept between two captions on the same row, in px. */
  MIN_GAP: 6,
  /** Padding a caption row keeps from the canvas edge, in px. */
  EDGE_PAD: 2,
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

/** Scene coordinates round to 2 decimals (t261009-79): the mock's own laneMap
 *  emits clean short numbers; percentage-width math otherwise leaks float
 *  tails (e.g. `601.4399999999999`) into every rendered attribute — a
 *  downstream scenario's 60-char path slice cut the diamond's closing `Z` out
 *  of its probe window (the T5 red). Rounding at the scene source fixes the
 *  family; no assertion or weight formula changes. */
const r2 = (n: number): number => Math.round(n * 100) / 100

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
  /** The caption as painted: unchanged copy, or (see ellipsized) the shortened
   *  caption. */
  text: string
  x: number
  y: number
  track: 'main' | 'partner'
  /** The lowest caption row the box fitted on (t261028-22). Main rows climb
   *  from LM_SCENE.LABEL_LO by LM_LABEL.STEP per level (level 0 = baseline-4,
   *  level 1 = baseline-13); partner rows step DOWN from the partner track.
   *  The renderer draws this y as handed over - it keeps no layout opinion. */
  level: number
  anchor: 'middle' | 'start'
  now: boolean
  /** Conditional-stage note (tspan.wb-lm-opt). */
  opt?: string
  /** Rounds badge xN (tspan.wb-lm-round). */
  roundBadge?: string
  /** Ever-blocked badge story (the title of tspan.wb-lm-ever). */
  everTitle?: string
  /** True = the caption was shortened to fit its row; the full caption is in
   *  `title` (and in the segment's hover title), so nothing is dropped. */
  ellipsized?: boolean
  /** Hover title of the caption element: the FULL caption, only when shortened. */
  title?: string
}

/** The parts one caption is drawn from (the tspans ride inside
 *  text.wb-lm-label, so the box estimate must count them too). */
interface LmCaptionParts {
  text: string
  opt?: string
  roundBadge?: string
  everTitle?: string
}

/** A claimed caption box in scene coordinates (the collision truth). */
interface LmPlacedBox {
  x0: number
  x1: number
  y0: number
  y1: number
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
    x: r2(x),
    y: r2(y),
    w: r2(w),
    h: r2(h),
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

/** Main caption: name + `duration · ×N` in the same caption (criterion 4/7);
 *  done/running stages print their duration, unstarted prints the name only,
 *  the current stage appends `now` (the mock's wording). The caption copy is
 *  unchanged by t261028-22 - only its level and, when squeezed, its truncation
 *  are new. */
function mainCaptionOf(nv: LaneNodeView, now: boolean): LmCaptionParts {
  const ever = everOf(nv)
  return {
    text: `${stageDisplayLabel(nv.node.id, nv.node.label)}${now ? ' now' : labelBit(nv)}`,
    opt: nv.node.optional || undefined,
    roundBadge: nv.badge || undefined,
    everTitle: ever ? everBlockedTitle(ever) : undefined,
  }
}

/** Partner caption: same parts vocabulary, its own `now` wording. */
function partnerCaptionOf(nv: LaneNodeView): LmCaptionParts {
  const ever = everOf(nv)
  return {
    text: `${stageDisplayLabel(nv.node.id, nv.node.label)}${nv.vis === 'running' ? ' now' : labelBit(nv)}`,
    opt: nv.node.optional || undefined,
    roundBadge: nv.badge || undefined,
    everTitle: ever ? everBlockedTitle(ever) : undefined,
  }
}

/* ── Caption boxes and multi-row placement (t261028-22) ── */

/** Glyphs whose advance is a full em: CJK ideographs, Hangul, kana, fullwidth
 *  forms, and the typographic marks the captions actually use (`…`, `·`, `—`). */
const LM_WIDE_GLYPH = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6\u2014\u2022\u2026\u00b7]/u

/** Caption width estimate in px at `fontPx`: one em per wide glyph, NARROW_EM
 *  per other glyph. Deterministic and conservative - the model has no DOM to
 *  measure with (the unit battery re-derives every box from this estimate). */
export function lmTextWidth(text: string, fontPx: number): number {
  let em = 0
  for (const ch of text) em += LM_WIDE_GLYPH.test(ch) ? LM_LABEL.WIDE_EM : LM_LABEL.NARROW_EM
  return em * fontPx
}

/** The string a label really paints: its text plus the tspan suffixes the
 *  renderer appends (optional note, ×N badge, ever-blocked badge). */
export function lmCaptionText(l: LmCaptionParts): string {
  let s = l.text
  if (l.opt) s += ` ${l.opt}`
  if (l.roundBadge) s += ` · ${l.roundBadge}`
  if (l.everTitle) s += ' was blocked'
  return s
}

/** Caption font size per track (the CSS font sizes, mirrored). */
export function lmCaptionFont(track: 'main' | 'partner'): number {
  return track === 'main' ? LM_LABEL.FONT_MAIN : LM_LABEL.FONT_PARTNER
}

/** Caption row baseline for a level: main rows climb above the bar, partner
 *  rows step down below the partner track. */
function lmLevelY(track: 'main' | 'partner', level: number): number {
  return track === 'main'
    ? LM_SCENE.LABEL_LO - level * LM_LABEL.STEP
    : LM_PARTNER_LABEL_Y + level * LM_LABEL.STEP
}

/** Shorten `text` to at most `room` px, marking the cut with an ellipsis.
 *  Returns '' when not even the ellipsis fits (the caller then keeps the full
 *  caption in the hover title, so nothing is dropped). */
function lmEllipsizeTo(text: string, room: number, fontPx: number): string {
  if (room <= 0) return ''
  if (lmTextWidth(text, fontPx) <= room) return text
  const chars = Array.from(text)
  for (let n = chars.length - 1; n > 0; n--) {
    const head = chars.slice(0, n).join('').replace(/[\s·]+$/u, '')
    const candidate = `${head}…`
    if (lmTextWidth(candidate, fontPx) <= room) return candidate
  }
  return lmTextWidth('…', fontPx) <= room ? '…' : ''
}

/** Fit a caption into `room` px: keep the badges (optional note / ×N / ever
 *  blocked) when at least one name glyph still fits beside them, else shorten
 *  the whole caption and let the badges ride in the hover title. */
function lmShrinkCaption(parts: LmCaptionParts, room: number, fontPx: number): { parts: LmCaptionParts; cut: boolean } {
  const full = lmCaptionText(parts)
  if (lmTextWidth(full, fontPx) <= room) return { parts, cut: false }
  const suffix = full.slice(parts.text.length)
  const suffixW = lmTextWidth(suffix, fontPx)
  if (suffixW > 0 && lmTextWidth('a…', fontPx) + suffixW <= room) {
    const text = lmEllipsizeTo(parts.text, room - suffixW, fontPx)
    if (text) return { parts: { ...parts, text }, cut: text !== parts.text }
  }
  return { parts: { text: lmEllipsizeTo(full, room, fontPx) }, cut: true }
}

/** One caption request: its parts, its track, and where it wants to sit. */
interface LmCaptionRequest {
  parts: LmCaptionParts
  track: 'main' | 'partner'
  anchor: 'middle' | 'start'
  /** Middle anchor: the preferred box centre (the bar centre). Start anchor:
   *  the preferred box left edge (the partner window head). */
  at: number
  now: boolean
}

/** Place one caption (t261028-22): the LOWEST level whose row has room for the
 *  whole estimated box, keeping the middle anchor on the bar and clamping the
 *  box into the canvas band; when no row has room, the roomiest row takes the
 *  shortened caption (full caption -> hover title). Every placed box is pushed
 *  into `boxes`, so the next caption sees it. */
function placeLmCaption(req: LmCaptionRequest, boxes: LmPlacedBox[]): LaneSceneLabel {
  const font = lmCaptionFont(req.track)
  const full = lmCaptionText(req.parts)
  const fullW = lmTextWidth(full, font)
  const bandW = LM_SCENE.CLAMP_MAX - LM_SCENE.CLAMP_MIN
  /** Room this caption may use on `level`: the canvas band minus every placed
   *  box on an overlapping row, minus MIN_GAP. */
  const roomOf = (level: number): LmPlacedBox => {
    const y = lmLevelY(req.track, level)
    const row = { x0: LM_SCENE.CLAMP_MIN, x1: LM_SCENE.CLAMP_MAX, y0: y - font * LM_LABEL.ASCENT_EM, y1: y + font * LM_LABEL.DESCENT_EM }
    for (const b of boxes) {
      if (!(b.y0 < row.y1 && row.y0 < b.y1)) continue
      if (b.x1 + LM_LABEL.MIN_GAP <= req.at) row.x0 = Math.max(row.x0, b.x1 + LM_LABEL.MIN_GAP)
      else if (b.x0 - LM_LABEL.MIN_GAP >= req.at) row.x1 = Math.min(row.x1, b.x0 - LM_LABEL.MIN_GAP)
      else return { x0: req.at, x1: req.at, y0: row.y0, y1: row.y1 } // the anchor itself is covered
    }
    return row
  }
  const xOf = (row: LmPlacedBox, w: number): number =>
    req.anchor === 'middle'
      ? Math.max(row.x0 + w / 2, Math.min(req.at, row.x1 - w / 2))
      : Math.max(row.x0, Math.min(req.at, row.x1 - w))
  const commit = (level: number, parts: LmCaptionParts, cut: boolean): LaneSceneLabel => {
    const y = lmLevelY(req.track, level)
    const visible = lmCaptionText(parts)
    const w = lmTextWidth(visible, font)
    const row = roomOf(level) // recompute: the box this caption claims
    const x = xOf(row, w)
    if (w > 0) {
      boxes.push({
        x0: req.anchor === 'middle' ? x - w / 2 : x,
        x1: req.anchor === 'middle' ? x + w / 2 : x + w,
        y0: y - font * LM_LABEL.ASCENT_EM,
        y1: y + font * LM_LABEL.DESCENT_EM,
      })
    }
    const out: LaneSceneLabel = {
      text: parts.text,
      x: r2(x),
      y,
      track: req.track,
      level,
      anchor: req.anchor,
      now: req.now,
    }
    if (parts.opt) out.opt = parts.opt
    if (parts.roundBadge) out.roundBadge = parts.roundBadge
    if (parts.everTitle) out.everTitle = parts.everTitle
    if (cut) {
      out.ellipsized = true
      out.title = full
    }
    return out
  }
  // Lowest row that holds the whole caption.
  if (fullW <= bandW) {
    for (let level = 0; level <= LM_LABEL.MAX_LEVEL; level++) {
      const row = roomOf(level)
      if (row.x1 - row.x0 < fullW) continue
      return commit(level, req.parts, false)
    }
  }
  // No row holds it whole: the roomiest row takes the shortened caption.
  let best = 0
  let bestRoom = roomOf(0)
  for (let level = 1; level <= LM_LABEL.MAX_LEVEL; level++) {
    const row = roomOf(level)
    if (row.x1 - row.x0 > bestRoom.x1 - bestRoom.x0) {
      best = level
      bestRoom = row
    }
  }
  const room = Math.min(bestRoom.x1 - bestRoom.x0, bandW)
  return commit(best, lmShrinkCaption(req.parts, room, font).parts, true)
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
 * baseline, floating captions (middle anchor, clamped into
 * [20, W+RPAD-20] by their BOX), dotted leaders, the diamond at the bar head,
 * the partner on a second track (one dashed window around both tracks + the
 * parallel mark), the now cursor spanning both tracks.
 *
 * Caption rows (t261028-22): level 0 and level 1 are the mock's own two rows;
 * further rows exist only when two captions would otherwise collide, and the
 * scene height grows with the rows used. Placement is the pure estimate in
 * placeLmCaption - no DOM measurement anywhere.
 */
export function laneMapScene(model: LaneMapModel): LaneScene {
  const { W, PAD, RPAD, AY, AH, BY, BH, GAP, MINW } = LM_SCENE
  const usable = W - PAD - RPAD
  const pctOf = new Map(lmWidths(model).map(w => [w.id, w.pct]))
  const bars: LaneSceneBar[] = []
  const labels: LaneSceneLabel[] = []
  const leaders: LaneScene['leaders'] = []
  const windows: LaneSceneWindow[] = []
  const parMarks: LaneScene['parMarks'] = []
  const diamonds: LaneScene['diamonds'] = []
  /** Caption boxes already claimed in this scene (t261028-22 collision truth). */
  const boxes: LmPlacedBox[] = []
  let cursor: LaneScene['cursor'] = null
  let x = PAD
  model.items.forEach(item => {
    const w = Math.max(0, (usable * (pctOf.get(item.id) ?? 0)) / 100)
    const now = model.nowItem === item.id
    const cx = r2(x + w / 2)
    if (item.kind === 'group') {
      const g = model.groups[item.id]
      windows.push({
        x: r2(x - 4),
        y: AY - 4,
        w: r2(w + 8),
        h: (BY + BH) - AY + 8,
        groupId: g.def.id,
        active: g.active,
        allDone: g.allDone,
        windowMs: g.windowMs,
      })
      parMarks.push({ x: r2(x + 5), y: BY + BH - 1 })
      const head = g.members[0]
      const partner = g.members[1]
      bars.push(barOf(head, x, AY, w, AH, 'main', now))
      // The head caption wants the bar centre (middle anchor, clamped by the
      // placement); the partner caption sits at the window head (start anchor).
      const headLabel = placeLmCaption({ parts: mainCaptionOf(head, now), track: 'main', anchor: 'middle', at: cx, now }, boxes)
      labels.push(headLabel)
      leaders.push({ x: cx, y1: r2(headLabel.y + 2.5), y2: AY - 1 })
      const pw = Math.max(MINW, (w * lmBandPct(partner.weightMs, g.windowMs)) / 100)
      const partnerNow = partner.vis === 'running'
      bars.push(barOf(partner, x, BY, pw, BH, 'partner', partnerNow))
      labels.push(placeLmCaption({ parts: partnerCaptionOf(partner), track: 'partner', anchor: 'start', at: r2(x + 6), now: partnerNow }, boxes))
    } else {
      const nv = model.nodes[item.id]
      bars.push(barOf(nv, x, AY, w, AH, 'main', now))
      const label = placeLmCaption({ parts: mainCaptionOf(nv, now), track: 'main', anchor: 'middle', at: cx, now }, boxes)
      labels.push(label)
      leaders.push({ x: cx, y1: r2(label.y + 2.5), y2: AY - 1 })
      if (nv.node.kind === 'human') diamonds.push({ x: r2(x + 5), y: AY + AH / 2 })
    }
    if (now) cursor = { x: r2(x + w), y1: AY - 8, y2: BY + BH + 3 }
    x += w + GAP
  })
  // Vertical frame (t261028-22): levels 0 and 1 are the mock's own two rows;
  // every further caption row pushes the whole scene down by one STEP, so the
  // top row keeps its canvas padding, and the height grows with the rows the
  // model actually used - a tall stack still fits the viewBox instead of
  // spilling out of it.
  const mainLevel = labels.reduce((m, l) => (l.track === 'main' ? Math.max(m, l.level) : m), 0)
  const partnerLevel = labels.reduce((m, l) => (l.track === 'partner' ? Math.max(m, l.level) : m), 0)
  const dy = Math.max(0, mainLevel - 1) * LM_LABEL.STEP
  const bottomNeed = LM_PARTNER_LABEL_Y + partnerLevel * LM_LABEL.STEP + LM_LABEL.FONT_PARTNER * LM_LABEL.DESCENT_EM
  const height = Math.max(LM_SCENE.H + dy, Math.ceil(bottomNeed + dy + LM_LABEL.EDGE_PAD))
  if (dy !== 0) {
    for (const l of labels) l.y = r2(l.y + dy)
    for (const b of bars) b.y = r2(b.y + dy)
    for (const l of leaders) { l.y1 = r2(l.y1 + dy); l.y2 = r2(l.y2 + dy) }
    for (const wn of windows) wn.y = r2(wn.y + dy)
    for (const p of parMarks) p.y = r2(p.y + dy)
    for (const d of diamonds) d.y = r2(d.y + dy)
    if (cursor) { cursor.y1 = r2(cursor.y1 + dy); cursor.y2 = r2(cursor.y2 + dy) }
  }
  return { width: W + RPAD, height, bars, labels, leaders, windows, parMarks, diamonds, cursor }
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

/**
 * One Check-details row. The engine writes TWO receipt shapes into
 * `gate_runs[*].checks[*]` (measured on live ticket faces, t261028-46):
 *
 *   - SCRIPT gates (cs-machine-qc / verify_lane code / release ledger):
 *     `{check, level: 'green'|'red', count}` — no `item`, no `green`;
 *   - AGENT and HUMAN gates: `{item, by, done, green, id, detail, reason_code,
 *     files, next_action}` — no `level`.
 *
 * Both land in this one row shape: name = `item` || `check` || `id`,
 * green = `green === true` || `level === 'green'`. A script row is never
 * judged by its missing `green` field, and an agent row keeps its rendering.
 */
export interface CheckRowView {
  green: boolean
  item: string
  detail?: string
  note?: string
  count?: number
  checkId?: string
  reasonCode?: string
  files?: string[]
  nextAction?: string
}

/** Receipt field behind a run's verdict. `rows` = the run wrote no verdict
 *  field, so the row evidence decides (never an invented green). */
export type GateVerdictSource = 'green' | 'level' | 'verdict' | 'rows'

export interface GateRunView {
  stage: string
  label: string
  green: boolean
  redCount: number
  /** Which receipt field the run-level verdict came from (t261028-46). */
  verdictSource: GateVerdictSource
  /** Every row green: the evidence the stage header must not contradict. */
  rowsGreen: boolean
  /** The written verdict and the receipt's own red evidence genuinely
   *  disagree. Both are shown verbatim; the reader reconciles nothing. */
  disagreement: boolean
  gen?: number
  conflict?: boolean
  rows: CheckRowView[]
}

/** Name shown when a row carries data but no identity field. */
const UNNAMED_CHECK = 'unnamed check'

/**
 * Boolean from one receipt verdict field. Accepts the booleans the agent
 * gates write and the `green`/`red` strings the script gates write. Any other
 * value (missing, null, another word) stays undefined: the reader degrades,
 * it never invents a verdict.
 */
export function receiptBool(v: unknown): boolean | undefined {
  if (v === true) return true
  if (v === false) return false
  if (typeof v === 'string') {
    const s = v.trim().toLowerCase()
    if (s === 'green') return true
    if (s === 'red') return false
  }
  return undefined
}

/**
 * Row verdict across both shapes, in receipt-field order: `green` (agent and
 * human gates) -> `level` (script gates) -> `verdict` -> `done`. Conflicting
 * signals resolve red: a reader never upgrades a row. No signal -> undefined
 * (the caller shows the row red, still named and still visible).
 */
function rowVerdict(co: Record<string, unknown>): boolean | undefined {
  const signals = [receiptBool(co.green), receiptBool(co.level), receiptBool(co.verdict), receiptBool(co.done)]
    .filter((s): s is boolean => s !== undefined)
  if (signals.length === 0) return undefined
  return signals.every(s => s === true)
}

/**
 * THE receipt-row accessor (t261028-48). This is the only place that decides
 * what a `gate_runs[*].checks[*]` row is called and whether it is green; every
 * reader of the receipt face goes through it, so the faces cannot disagree
 * about the same engine data (host methodology 260907: one reported symptom is
 * a sample of a family).
 *
 * Reads BOTH engine shapes (measured on live faces, t261028-46):
 *   - SCRIPT gates: `{check, level: 'green'|'red', count}` — no `item`,
 *     no `green`;
 *   - AGENT/HUMAN gates: `{item, by, done, green, id, detail, note, …}`.
 * Name = `item` || `check` || `id`; verdict = green || level || verdict ||
 * done (conflicting signals resolve red). Detail/note/count/reason_code/
 * files/next_action are carried verbatim.
 *
 * Returns null only for a row that carries nothing: a malformed value, a blank
 * scalar, or a green row with neither a name nor a payload. A red row is
 * always returned — an unproven receipt is shown, never hidden.
 */
export function receiptRowView(raw: unknown): CheckRowView | null {
  // A bare string/number row still names something: keep it as a named row
  // instead of dropping the information.
  if (typeof raw === 'string' || typeof raw === 'number') {
    const text = String(raw).trim()
    return text ? { green: false, item: text } : null
  }
  if (raw === null || typeof raw !== 'object') return null
  const co = raw as Record<string, unknown>
  const green = rowVerdict(co) === true
  const checkId = asString(co.id) || undefined
  // item (agent/human) || check (script) || id (id-only green item,
  // agent_activities D4 shape) — every real row gets a readable name.
  const name = asString(co.item) || asString(co.check) || checkId || ''
  const detail = asString(co.detail) || undefined
  const note = asString(co.note) || undefined
  const count = typeof co.count === 'number' && Number.isFinite(co.count) ? co.count : undefined
  // A green row with no name and no payload adds nothing to the face.
  // A red row, or any row carrying detail/note/count, is always shown.
  if (green && !name && !detail && !note && count === undefined) return null
  return {
    green,
    item: name || UNNAMED_CHECK,
    detail,
    note,
    count,
    checkId,
    reasonCode: asString(co.reason_code) || undefined,
    files: asStringArray(co.files),
    nextAction: asString(co.next_action) || undefined,
  }
}

/** Every informative row of one `checks` array, through the one accessor. */
export function receiptRowViews(checks: unknown): CheckRowView[] {
  if (!Array.isArray(checks)) return []
  const out: CheckRowView[] = []
  for (const c of checks) {
    const v = receiptRowView(c)
    if (v !== null) out.push(v)
  }
  return out
}

/** One run's written verdict, and which receipt field it came from. */
export interface GateRunVerdict {
  /** undefined = the run wrote no verdict field (the rows decide). */
  green: boolean | undefined
  source: GateVerdictSource
}

/**
 * Run-level verdict through the same field reader the rows use (script-gate
 * run rows may write `level`/`verdict`; agent runs write `green`). No written
 * verdict -> {green: undefined, source: 'rows'}, never an invented green.
 */
export function readGateRunVerdict(run: Record<string, unknown>): GateRunVerdict {
  const wroteGreen = receiptBool(run.green)
  const wroteLevel = receiptBool(run.level)
  const wroteVerdict = receiptBool(run.verdict)
  if (wroteGreen !== undefined) return { green: wroteGreen, source: 'green' }
  if (wroteLevel !== undefined) return { green: wroteLevel, source: 'level' }
  if (wroteVerdict !== undefined) return { green: wroteVerdict, source: 'verdict' }
  return { green: undefined, source: 'rows' }
}

/**
 * gate_runs → Check-details row model (newest run first). Reads both receipt
 * shapes through the one accessor (receiptRowView / readGateRunVerdict).
 * Malformed entries degrade row by row and never throw; a row that carries
 * information is never dropped.
 */
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
    const rows: CheckRowView[] = receiptRowViews(o.checks)
    const rowsGreen = rows.every(r => r.green)
    // Run-level verdict: whatever the engine writes, else the rows decide.
    const verdict = readGateRunVerdict(o)
    const written = verdict.green
    const redCount = typeof o.red_count === 'number' && Number.isFinite(o.red_count) ? o.red_count : rows.filter(r => !r.green).length
    // Header and rows may only agree when the receipt agrees: a green verdict
    // with red rows (or a non-zero red count) is a genuine engine disagreement
    // and is surfaced, not smoothed over.
    const contradiction = (rows.length > 0 && written !== rowsGreen) || (written === true && redCount > 0)
    out.push({
      stage,
      label: asString(o.label) || stage,
      green: written !== undefined ? written : rowsGreen,
      redCount,
      verdictSource: verdict.source,
      rowsGreen,
      disagreement: written !== undefined && contradiction,
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
