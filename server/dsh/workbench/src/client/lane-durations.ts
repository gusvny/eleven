/**
 * lane-durations —— 泳道图节点直显耗时的推导（t260901-12，metrics M1b）。
 *
 * 纯函数模块：零 react / 平台依赖，node 可直接 import（行为测试
 * integration/baselines/lane-stage-durations.mjs 黑盒消费本模块）。
 * index.tsx 只做消费不做推导。
 *
 * 数据源（工单详情 API 已透出，TicketDetail 接口见 index.tsx）：
 *  - timeline: {at(ISO), stage, state, reason}[]（base.py _mark 落 running/
 *    blocked/rework/awaiting-human…；引擎无 done 态——_finish 只翻 checks
 *    不 _mark，完成步的最新 timeline 态永远停在 running）。
 *  - handoffs: {stage, ts(epoch 秒), ...}[]（base.py:336-341 _handoff 每步
 *    完成落一条；dev_lane 全链 17 处调用点覆盖）。
 *  - opts.closedTs: epoch 秒（TicketDetail.updated；closed 单的兜底收口）。
 *  单位纪律：timeline.at 解析为 **毫秒**；handoff.ts 与 closedTs 是
 *  epoch **秒**，参与比较前必须 ×1000——漏乘会让轮长差 1000 倍
 *  （integration 测试用真实 epoch 值锚定，单位错会在测试期暴露）。
 *
 * 轮（round）的真实口径（评审 v4 拍板，头注级文档按此写；禁止把轮描述成
 * 「只算执行时间、不含等待」这类与真实语义不符的说法）：
 *  第 n 轮 = [该 stage 第 n 条 running mark 的 at, 关窗事件)。
 *  关窗事件 = 下面收口链命中的第一个。**awaiting-human / blocked /
 *  rework mark 不关窗**——落在轮内的签字等待、阻塞时长**计入所在轮**。
 *  总耗时 = Σ各轮 = 节点墙钟占用；人等时段另以 humanWaits 逐段单列
 *  （tooltip 同时给轮列表与人等段列表，消费方自行拆看）。
 *  merge 签字场景为例：merge running（进入）→ awaiting-human → running
 *  （人审通过），第 1 轮=进入→人审通过 running，**含签字等待**。
 *
 * 收口链（每个 stage 第 n 轮，开窗 fromMs=第 n 条 running mark，
 *  非末轮窗上界=下一条本 stage running mark，末轮=+∞）：
 *  1. 本 stage handoff ts：窗内最大（epoch 秒 ×1000；冲突消解中途额外
 *     handoff 的错位由取最大消解，dev_lane.py:1259）。
 *  2. {stage:'merge', state:'closed'} mark（dev_lane.py:1342 引擎完成时落）：
 *     收一切**末轮**开放窗——其他 stage 的开放窗与 merge 末轮在口径 1
 *     落空时的兜底（merge 自己的末轮优先用窗内 handoff，dev_lane.py:1331
 *     先于 :1342 毫秒级，handoff 更贴真）。
 *  3. 末轮回退：下一条其他 stage 的 running mark（近似级；无 handoff
 *     的 ui_evidence 内联步等场景）。
 *  4. closedTs（updated 秒 ×1000）：一切收口皆无时的兜底。**不做
 *     closedTs>fromMs 的防护**——时钟回拨产生的负差窗原样保留，
 *     由 fmtDur/windowMs 显「—」（负差是数据事实，不静默吞掉）。
 *  5. 仍开放 → toMs=null：running/awaiting-human 视觉态由 UI 用 nowMs
 *     实时走秒；done/todo 视觉态不显耗时。
 *  非末轮在以上皆落空时以本 stage 下一条 running mark 关窗。
 *
 * handoff ts 语义声明：ts = agent 交报告时刻，含 worker 代落盘前尾巴，
 * 轮耗时会略大于纯执行时长——口径如此，不修正。
 *
 * 口径分叉表（同一 timeline 的两个窗口消费方，禁止互相对齐时单方改
 * 口径；改谁都要过工单）：
 *  | 维度 | lane-durations（本模块，耗时轮窗） | agent-usage（token 切窗） |
 *  | 收口真源 | 本 stage handoff ts 优先（收口链） | 只认下一条 running mark |
 *  | 并行段 | 各 stage 独立计时 | 跨度归并（后 mark 才切窗） |
 *  | 人等/阻塞跨度 | 计入所在轮 | 计入所在窗（两者一致，无差异） |
 *
 * 畸形输入（外部快照不可信，与 lane-states.ts 同纪律）：
 *  - timeline 条目 stage/state 非字符串或空串 → 跳过；at 非法 ISO → 跳过；
 *    模板外 stage id（phase 域如 acceptance/workspace/parallel_impl_design）
 *    不建窗、不泄漏进返回键（marks 仅收 order 内的 stage）。
 *  - handoff 条目 ts 非有限数、stage 非字符串/空串 → 跳过（映射之前过滤）。
 *  - handoffs 整体缺省/非数组 → 按 [] 处理（全链退化口径 2/3/4/5）。
 *  - 乱序时间戳：全量 mark 按 ms 升序稳定排序后再推导（与 agent-usage
 *    一致，两消费方不因乱序分叉）。
 *
 * 非 dev-lane 模板（proofread/content-pipeline）无 merge/closed mark：
 * 口径 2 自然跳过，模块靠 order + handoff 键自然适配，错位/缺失键回退
 * 口径 3/4/5 兜底，不发明映射。
 */

/** 一段时间窗：fromMs 起 toMs 止；toMs=null 表示开放式（实时走秒）。 */
export interface DurationWindow {
  fromMs: number
  toMs: number | null
}

/** 一个 stage 的耗时推导结果。 */
export interface StageDuration {
  stage: string
  /** 各轮（相邻 running mark 墙钟段，含人等/阻塞跨度）。 */
  rounds: DurationWindow[]
  /** 人等（awaiting-human）段，逐段单列。 */
  humanWaits: DurationWindow[]
}

/** handoff 的 stage 键与 lane id 不同词表的显式映射（其余错位键不发明映射，
 *  该步回退口径 3/4/5）。acceptance_walkthrough 步的 handoff 键是 "acceptance"
 *  （dev_lane.py:1104 vs :1102 _finish 用 "acceptance_walkthrough"）。 */
export const HANDOFF_KEY_ALIAS: Record<string, string> = { acceptance: 'acceptance_walkthrough' }

export interface DeriveDurationsOpts {
  /** 实时走秒的 now（ms）；推导本身不落 now（开放窗保持 null，由 UI 决定）。 */
  nowMs?: number
  /** closed 单收口兜底：TicketDetail.updated（epoch 秒，内部 ×1000）。 */
  closedTs?: number | null
}

interface TimelineLike {
  at?: string
  stage?: string
  state?: string
}

interface HandoffLike {
  stage?: string
  ts?: number
}

interface Mark {
  stage: string
  state: string
  ms: number
}

function msOfIso(at: unknown): number | null {
  if (typeof at !== 'string' || at === '') return null
  const ms = new Date(at).getTime()
  return Number.isFinite(ms) ? ms : null
}

/** 收集 order 内的合法 marks 并升序排序（乱序快照不炸、不分叉）。 */
function collectMarks(timeline: TimelineLike[] | undefined | null, order: string[]): Mark[] {
  const inOrder = new Set(order)
  const marks: Mark[] = []
  for (const t of Array.isArray(timeline) ? timeline : []) {
    if (!t || typeof t.stage !== 'string' || typeof t.state !== 'string') continue
    if (t.stage === '' || t.state === '') continue
    if (!inOrder.has(t.stage)) continue // 模板外 id 不建窗、不泄漏
    const ms = msOfIso(t.at)
    if (ms === null) continue
    marks.push({ stage: t.stage, state: t.state, ms })
  }
  return marks.sort((a, b) => a.ms - b.ms)
}

/** 收集合法 handoff（epoch 秒 → ms；畸形条目映射前跳过）。 */
function collectHandoffs(handoffs: HandoffLike[] | undefined | null): { stage: string; ms: number }[] {
  const out: { stage: string; ms: number }[] = []
  for (const h of Array.isArray(handoffs) ? handoffs : []) {
    if (!h || typeof h.stage !== 'string' || h.stage === '') continue
    if (typeof h.ts !== 'number' || !Number.isFinite(h.ts)) continue
    out.push({ stage: HANDOFF_KEY_ALIAS[h.stage] ?? h.stage, ms: h.ts * 1000 })
  }
  return out
}

/**
 * 推导每个 order stage 的轮窗与人等段。
 * 返回 Record 只含 timeline 里出现过 running mark 的 stage（键 ⊆ order）。
 */
export function deriveStageDurations(
  timeline: TimelineLike[] | undefined | null,
  order: string[],
  handoffs?: HandoffLike[] | undefined | null,
  opts?: DeriveDurationsOpts,
): Record<string, StageDuration> {
  const marks = collectMarks(timeline, order)
  const handoffList = collectHandoffs(handoffs)
  const closedMs =
    typeof opts?.closedTs === 'number' && Number.isFinite(opts.closedTs) ? opts.closedTs * 1000 : null
  // merge/closed mark：一切末轮开放窗的第二收口真源（口径 2）。
  const closedMarkMs = marks.find(m => m.stage === 'merge' && m.state === 'closed')?.ms ?? null

  const out: Record<string, StageDuration> = {}
  for (const stage of order) {
    const runningMs = marks.filter(m => m.stage === stage && m.state === 'running').map(m => m.ms)
    const ahMarks = marks.filter(m => m.stage === stage && m.state === 'awaiting-human')
    if (runningMs.length === 0 && ahMarks.length === 0) continue
    const rounds: DurationWindow[] = []
    for (let i = 0; i < runningMs.length; i++) {
      const fromMs = runningMs[i]!
      const ownNext = i + 1 < runningMs.length ? runningMs[i + 1]! : null
      const upper = ownNext ?? Number.POSITIVE_INFINITY // 末轮上界 +∞
      // 口径 1：窗内本 stage handoff 最大 ts。
      let handoffBest: number | null = null
      for (const h of handoffList) {
        if (h.stage !== stage) continue
        if (h.ms <= fromMs || h.ms > upper) continue
        handoffBest = handoffBest === null ? h.ms : Math.max(handoffBest, h.ms)
      }
      let toMs: number | null
      if (handoffBest !== null) {
        toMs = handoffBest
      } else if (ownNext !== null) {
        // 非末轮：口径 2（closed mark 在窗内）→ 口径 3 字面（下一条任意
        // stage running mark，可能早于 ownNext）→ ownNext 关窗。
        const cm = closedMarkMs !== null && closedMarkMs > fromMs && closedMarkMs <= upper ? closedMarkMs : null
        const nextOther = marks.find(m => m.stage !== stage && m.state === 'running' && m.ms > fromMs)
        if (cm !== null && (nextOther === undefined || cm <= nextOther.ms)) toMs = cm
        else if (nextOther !== undefined && nextOther.ms <= upper) toMs = nextOther.ms
        else toMs = ownNext
      } else {
        // 末轮：closed mark → 下一条其他 stage running mark → closedTs → 开放。
        if (closedMarkMs !== null && closedMarkMs > fromMs) {
          toMs = closedMarkMs
        } else {
          const nextOther = marks.find(m => m.stage !== stage && m.state === 'running' && m.ms > fromMs)
          if (nextOther !== undefined) toMs = nextOther.ms
          else if (closedMs !== null) toMs = closedMs // 不做 >fromMs 防护（S11 时钟回拨）
          else toMs = null
        }
      }
      rounds.push({ fromMs, toMs })
    }
    // 人等段：awaiting-human mark 至其后第一条 mark（任意 stage 任意态）。
    const humanWaits: DurationWindow[] = []
    for (const m of ahMarks) {
      const next = marks.find(x => x.ms > m.ms)
      let toMs: number | null = next ? next.ms : null
      // 无后继时按 closed 收口链收口（优先 closed mark，退 closedTs），皆无→保持 null。
      if (toMs === null) {
        if (closedMarkMs !== null && closedMarkMs > m.ms) toMs = closedMarkMs
        else if (closedMs !== null) toMs = closedMs
      }
      humanWaits.push({ fromMs: m.ms, toMs })
    }
    out[stage] = { stage, rounds, humanWaits }
  }
  return out
}

/** 一段窗的墙钟时长（ms）；开放窗用 nowMs 实时差；负差（时钟回拨）→ null。 */
export function windowMs(w: DurationWindow, nowMs?: number): number | null {
  const to = w.toMs ?? (nowMs ?? Date.now())
  const d = to - w.fromMs
  return Number.isFinite(d) && d >= 0 ? d : null
}

/** 一个 stage 的总耗时 = Σ各轮（开放轮用 nowMs）；任一轮非法 → null。 */
export function stageTotalMs(d: StageDuration, nowMs?: number): number | null {
  if (d.rounds.length === 0) return null
  let total = 0
  for (const r of d.rounds) {
    const ms = windowMs(r, nowMs)
    if (ms === null) return null
    total += ms
  }
  return total
}

/** 人等总时长（各段求和，开放段用 nowMs）；无人等段 → 0。 */
export function humanWaitTotalMs(d: StageDuration, nowMs?: number): number {
  let total = 0
  for (const w of d.humanWaits) {
    const ms = windowMs(w, nowMs)
    if (ms !== null) total += ms
  }
  return total
}

/** 时长格式化：<60s「Xs」；<60m「Xm Ys」（0 秒段省略）；≥1h「Xh Ym」（分段恒显，
 *  含 0——「1h 0m」比「1h」更不易误读为分钟）；null/undefined/负/NaN → 「—」。 */
export function fmtDur(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return '—'
  const totalSec = Math.floor(ms / 1000)
  const s = totalSec % 60
  const m = Math.floor(totalSec / 60) % 60
  const h = Math.floor(totalSec / 3600)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return s > 0 ? `${m}m ${s}s` : `${m}m`
  return `${s}s`
}

/** 节点 tooltip 文案：耗时 + 逐轮 + 人等段单列（人等已计入所在轮的总耗时
 *  ——见头注真实口径；此处的「人等」是拆看视图，不是从轮里扣减）。 */
export function stageDurationTitle(d: StageDuration, nowMs?: number): string {
  const parts: string[] = []
  const total = stageTotalMs(d, nowMs)
  if (total !== null) parts.push(`耗时 ${fmtDur(total)}`)
  d.rounds.forEach((r, i) => {
    parts.push(`第${i + 1}轮 ${fmtDur(windowMs(r, nowMs))}`)
  })
  if (d.humanWaits.length > 0) {
    const seg = d.humanWaits.map(w => fmtDur(windowMs(w, nowMs))).join(' + ')
    parts.push(`人等 ${fmtDur(humanWaitTotalMs(d, nowMs))}（${seg}）`)
  }
  return parts.join(' · ')
}
