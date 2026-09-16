/**
 * lane-states —— 工单台泳道图/步骤条的「活跃步数组」推导（t260901-05）。
 *
 * 纯函数模块：零 react / 平台依赖，node 可直接 import（行为测试
 * integration/baselines/lane-parallel-states.mjs 黑盒消费本模块）。
 * index.tsx 只做消费不做推导。
 *
 * 背景：dev-lane 的 parallel_impl_design 段用 asyncio.gather 真并行跑
 * implement ∥ design_integration_tests，timeline 里两步各有一条 running；
 * 但工单快照只有单值 stage 指针，UI 按单点高亮会漏掉另一并行步。
 * 本模块把「单值指针」推导为「活跃步数组」（多步同显 running）。
 *
 * 推导优先级（真值表每条锚定 dev_lane.py 源码行，方案 v3 已过审；t260901-08
 * 起引擎 _finish 落 done 终态条目（旧票无该
 * 条目自然回落下述启发式，存量数据不追改）：
 *  1. status==='closed' → 全部 done（短路）。
 *  2. timeline 最新一条显式态 ∈ {blocked, awaiting-human, done} → 直采该态
 *     （✗/✋/✓），不进活跃数组（_blocked/merge 签字/_finish 的 mark 都是追加在
 *     _enter 的 running 之后的独立条目，最新态即真相；merge 签字期据此显 ✋
 *     而非 ▶；done 终态条目优先于 inRun 计数——t260901-07 实锤：仲裁内部重跑
 *     复用结果文件不增 gen、merge_check 等脚本门重复进段只落 checks 不落
 *     results，计数启发式在重验循环后必误亮，终态留痕才是根治）。
 *  3.（t260910-14 退役注记：原「预跑段永不进活跃数组」规则随该段退役失效——
 *     order 来自 STAGES，已不含该 id；老票 timeline 残留条目不进推导。）
 *  4. inRun = running 条数 > attempts（区分「完成停在 running」vs「重跑中」）：
 *     attempts = results[s] 存在则 gen+1（ui_evidence 软失败 failed 亦计次）；
 *     无 results 而 checks[s] 全 done（merge/merge_check 纯脚本门）记 1。
 *     走到这步最新态必是 running → ▶ 入活跃数组。
 *  5. done = results[s].status==='ok' ∨ checks[s] 全 done（≥1 项）∨ 下标 ≤
 *     maxDoneIdx（兜底：ui_evidence 软失败被后续步推过、acceptance_walkthrough
 *     的 checks 键曾错位等 done 信号缺口）。
 *  6. 其余 todo。
 * 回退：活跃数组空 ∨ timeline 缺/空 → states 等于现行单值指针口径
 * （逐字节保持 t260901-05 之前的行为，软降级不回归）。
 *
 * 畸形输入（外部快照不可信）：timeline 缺字段（stage/state 非字符串）的
 * 条目跳过；模板外 stage id（phase 域如 acceptance/workspace/
 * parallel_impl_design）忽略——不建状态、不进活跃数组、不泄漏进返回键。
 *
 * t260903-04（KI-024）并行真源入列：引擎并行分叉期把活跃边列表写进
 * detail.meta.parallel_stages（snapshot 附 meta 全文；engine 侧
 * set_parallel_stages 保证只含 STAGES id、离开并行期删键）。本模块消费口径：
 *  - 列表缺失/空/清洗后为空 → 既有推导逐字节保持（旧票与旧快照零回归）；
 *  - 列表合法非空 → 真值优先：列表内的步若已被显式终态（done/blocked/
 *    awaiting-human，来自 timeline 最新态）钉住则保持终态（先完成边的收口窗，
 *    引擎汇合前不把已完成边重亮成 ▶），否则强制 running 并入活跃数组
 *    （fork 瞬间 timeline 轮询滞后/启发式误判面，
 *    acceptance_walkthrough 相邻边尤其受益）；
 *  - 畸形条目（非字符串/模板外 id）丢弃，与 timeline 畸形输入同纪律。
 *
 * t260916-04（图面受阻着色语义）：blocked 的「当前性」按后续证据判定，不再按
 * 「该段最后一条流水」永久钉红（t260916-02 实证：implement 同刻 done+blocked，
 * 解除证据记在相邻后段，该段红永久挂着，读图人误读「实现失败」）。口径：
 *  - 解除证据（条目位置必须在最后一次 blocked 之后；数组序=追加序=时序——与规则 2
 *    的 latest 覆盖序是同一契约，本推导不新增乱序暴露面；KI-019 扁平时间线结构性
 *    失真族同图面，其根修（引擎因果序号+真泳道呈现）不随本票）：
 *      E1 本段重跑完成：同段其后有 done → rerun；
 *      E2 工作流已推进：后段（idx 更大）其后有条目且该段非并行兄弟 → advanced
 *        （后段证据任意条目型均可——引擎在任何后段落条目=工作流已过汇合）；
 *      E3 工单已收口：status==='closed' → closed（历史受阻随收口解除，工单④）。
 *  - 同段证据只认 done：authorized/retry-requested（t260912-03 授权通道/请求重验
 *    留痕）不作解除证据——人放了话≠活干成了（保守③：宁可吓人，不许漏报）。
 *  - 就地段信号显示口径：authorized/retry-requested 由引擎 raw append 落在当前段、
 *    不重进段（retry_qc 只是唤醒令牌，真重跑以随后的 running 为准）——最后一次
 *    受阻之后本段没有再 running/done/awaiting-human 时按 blocked 显示（旧启发式在
 *    该窗口会误显 ▶「重跑中」），真重跑进段后照常走 ▶/done。
 *  - 并行兄弟判定（兄弟段干完≠推进；并行 gather 里本段受阻等重试时兄弟可继续跑完）：
 *    opts.groups 在场（泳道图面，buildLaneMap 透传拓扑 groups）按同组判定；缺省
 *    （降级步骤条/裸 import 直跑）按相位判定——两条目 phase 均非空且相等=兄弟，
 *    一空一非空=不同相位=非兄弟，均空（老票无相位标注）按兄弟保守处理（宁红不漏）。
 *  - 显示态换算：最新显式态=blocked 且已解除 → vis='done'（完成色）；受阻史以
 *    blockedHistory 正交数据随行（不进 D2Visual 五态词表，零回归锚），渲染层
 *    （lane-map）据此出「曾受阻」角标+hover 经过。未解除 → 保持 blocked。
 *  - 同机制面排查（实报即全族）：awaiting-human 豁免——sign 批准路径同段落
 *    running + _finish('merge') 落 done，无滞留面；awaiting（adopt）不在规则 2
 *    钉住集 {blocked, awaiting-human, done}；failed/cancelled 终态票的历史受阻
 *    保持红=诚实留痕（工单④只定 closed，死票观感如需另裁，另立票不扩本票 scope）。
 */

/** 阶段视觉态：done✓ / running▶ / blocked✗ / awaiting-human✋ / todo○。 */
export type D2Visual = 'done' | 'running' | 'blocked' | 'awaiting-human' | 'todo'

/** 推导函数消费的 detail 最小结构（与 TicketDetail 的对应字段同构；
 *  独立声明是为了让本模块零类型依赖、node 裸 import 可用）。 */
export interface LaneDetailLike {
  status?: string
  stage?: string | null
  stage_state?: string
  timeline?: { at?: string; stage?: string; state?: string; reason?: string; gen?: number; phase?: string }[] | null
  results?: Record<string, { status?: string; gen?: number }>
  checks?: Record<string, { item: string; done: boolean; by?: string }[]>
  /** KI-024 并行真源：引擎快照放在 meta 全文里（meta.parallel_stages）；顶层
   *  同名字段留作直读兼容。两处都看，清洗口径一致（合法 id、去重保序）。 */
  parallel_stages?: string[]
  meta?: { parallel_stages?: string[] } | null
}

/** 推导结果：states 恒覆盖 order 每一步（含回退口径）；active=活跃步数组；
 *  fallback=true 表示本次走了单值指针回退（调用方如需区分新旧口径可用）；
 *  blockedHistory=受阻史与当前性判定（t260916-04 增键，形状向后兼容）。 */
export interface LaneStatesResult {
  states: Record<string, D2Visual>
  active: string[]
  fallback: boolean
  blockedHistory: Record<string, LaneBlockedHistory>
}

/** 一轮受阻（图面「曾受阻」经过的数据源，t260916-04）。 */
export interface LaneBlockedPass {
  at?: string
  reason?: string
  gen?: number
  phase?: string
}

/** 一段的受阻史与当前性判定（t260916-04）：resolved=true（vis 已换算 done）→
 *  渲染层出「曾受阻」角标+hover 经过；resolved=false → 保持当前受阻实心红。 */
export interface LaneBlockedHistory {
  /** 全部受阻轮（角标计数；逐轮红格留痕归轮次带，这里只做计数+最近一次）。 */
  passes: LaneBlockedPass[]
  /** 最近一次受阻（hover 经过主行：何时受阻、何因）。 */
  last: LaneBlockedPass
  /** 当前语义：受阻是否已被后续证据解除（口径见模块头注）。 */
  resolved: boolean
  /** 解除方式：rerun=本段重跑完成 / advanced=工作流已推进至后续段 / closed=工单已收口。 */
  resolvedBy?: 'rerun' | 'advanced' | 'closed'
  /** 解除证据条目时刻（closed 无对应条目=缺省）。 */
  resolvedAt?: string
}

/** deriveStageStates/deriveBlockedHistory 可选项：拓扑并行组成员数组（泳道图由
 *  buildLaneMap 透传 topology.groups；缺省=降级面，按相位保守判定）。 */
export interface LaneStatesOpts {
  groups?: string[][]
}

/** 就地段信号（t260912-03 授权通道 authorized / retry_qc 信号 retry-requested）：
 *  引擎 raw append 落当前段、不重进段——显示口径见规则 2 的受阻期判定。 */
const IN_PLACE_MARKS = new Set(['authorized', 'retry-requested'])

/** 单值指针口径（回退用，逐字节为 t260901-05 之前的现行行为，勿改）。 */
function pointerStates(detail: LaneDetailLike, order: string[]): Record<string, D2Visual> {
  const states: Record<string, D2Visual> = {}
  const curIdx = order.indexOf(detail.stage ?? '')
  for (const stageId of order) {
    const idx = order.indexOf(stageId)
    if (idx >= 0 && curIdx >= 0) {
      if (idx < curIdx) { states[stageId] = 'done'; continue }
      if (idx > curIdx) { states[stageId] = 'todo'; continue }
      if (detail.stage_state === 'blocked') { states[stageId] = 'blocked'; continue }
      if (detail.stage_state === 'awaiting-human') { states[stageId] = 'awaiting-human'; continue }
      states[stageId] = 'running'
      continue
    }
    if (stageId === detail.stage) {
      if (detail.stage_state === 'blocked') { states[stageId] = 'blocked'; continue }
      if (detail.stage_state === 'awaiting-human') { states[stageId] = 'awaiting-human'; continue }
      states[stageId] = 'running'
      continue
    }
    const r = detail.results?.[stageId]
    states[stageId] = r && r.status === 'ok' ? 'done' : 'todo'
  }
  return states
}

/** KI-024 并行真源提取：meta.parallel_stages（优先）∨ 顶层 parallel_stages，
 *  清洗为 order 内的合法 id 列表（去重保序）。缺失/非数组/全非法 → 空数组
 *  （=「当前无并行」，调用方走既有推导，零回归）。 */
function parallelIdsOf(detail: LaneDetailLike, order: string[]): string[] {
  const metaRaw = (detail.meta as { parallel_stages?: unknown } | null | undefined)
    ?.parallel_stages
  const raw = metaRaw !== undefined ? metaRaw : detail.parallel_stages
  if (!Array.isArray(raw)) return []
  const known = new Set(order)
  const out: string[] = []
  for (const x of raw) {
    if (typeof x === 'string' && known.has(x) && !out.includes(x)) out.push(x)
  }
  return out
}

/** 兄弟段判定（兄弟段干完≠本段推进）：groups 在场（已知拓扑）按同组；缺省按
 *  相位——两条目 phase 均非空且相等=兄弟，一空一非空=不同相位=非兄弟，均空
 *  （老票无相位标注，无法判兄弟）按兄弟保守处理——宁红不漏（t260916-04 ③）。 */
function siblingOf(s: string, t: string, groups: string[][] | undefined,
  phaseB?: string, phaseE?: string): boolean {
  if (Array.isArray(groups)) {
    return groups.some(g => Array.isArray(g) && g.includes(s) && g.includes(t))
  }
  if (phaseB && phaseE) return phaseB === phaseE
  if (!phaseB && !phaseE) return true
  return false
}

/** 受阻史与当前性判定（t260916-04）：对每段取最后一次 blocked，按其后的证据判
 *  「是否已解除」（E1 rerun / E2 advanced / E3 closed，口径见模块头注）。纯函数、
 *  全程不抛；只对 order 内的段产出键，模板外 id 不泄漏。 */
export function deriveBlockedHistory(detail: LaneDetailLike, order: string[],
  opts?: LaneStatesOpts): Record<string, LaneBlockedHistory> {
  const out: Record<string, LaneBlockedHistory> = {}
  if (!Array.isArray(detail.timeline)) return out
  // 清洗一次（与规则 2 同纪律：缺字段条目跳过）；位置=清洗后数组下标=追加时序。
  const clean: Array<{ stage: string; state: string; at?: string; reason?: string; gen?: number; phase?: string }> = []
  for (const t of detail.timeline) {
    if (!t || typeof t.stage !== 'string' || typeof t.state !== 'string') continue
    if (t.stage === '' || t.state === '') continue
    clean.push({
      stage: t.stage,
      state: t.state,
      at: typeof t.at === 'string' && t.at ? t.at : undefined,
      reason: typeof t.reason === 'string' && t.reason ? t.reason : undefined,
      gen: typeof t.gen === 'number' && Number.isFinite(t.gen) ? t.gen : undefined,
      phase: typeof t.phase === 'string' && t.phase ? t.phase : undefined,
    })
  }
  const byStage: Record<string, number[]> = {}
  clean.forEach((e, pos) => { (byStage[e.stage] ??= []).push(pos) })
  const idxOf = new Map(order.map((id, i) => [id, i]))
  const closed = detail.status === 'closed'
  for (const id of order) {
    const positions = byStage[id]
    if (!positions || positions.length === 0) continue
    const passes = positions.map(pos => ({ e: clean[pos], pos })).filter(x => x.e.state === 'blocked')
    if (passes.length === 0) continue
    const lastB = passes[passes.length - 1]
    let resolved = false
    let resolvedBy: LaneBlockedHistory['resolvedBy']
    let resolvedAt: string | undefined
    if (closed) {
      // E3：收口=历史受阻随收口解除（工单④；收口时刻不对应单条 timeline 条目）。
      resolved = true
      resolvedBy = 'closed'
    } else {
      // E1：同段证据只认 done（authorized/retry-requested 不算——人放话≠干成）。
      const donePos = positions.find(p => p > lastB.pos && clean[p].state === 'done')
      if (donePos !== undefined) {
        resolved = true
        resolvedBy = 'rerun'
        resolvedAt = clean[donePos].at
      } else {
        // E2：后段（idx 更大）其后任意条目型=工作流已过汇合；并行兄弟段不算。
        const sIdx = idxOf.get(id)
        if (sIdx !== undefined) {
          for (let p = lastB.pos + 1; p < clean.length && !resolved; p++) {
            const e = clean[p]
            const tIdx = idxOf.get(e.stage)
            if (tIdx === undefined || tIdx <= sIdx) continue
            if (siblingOf(id, e.stage, opts?.groups, lastB.e.phase, e.phase)) continue
            resolved = true
            resolvedBy = 'advanced'
            resolvedAt = e.at
          }
        }
      }
    }
    out[id] = {
      passes: passes.map(x => ({ at: x.e.at, reason: x.e.reason, gen: x.e.gen, phase: x.e.phase })),
      last: { at: lastB.e.at, reason: lastB.e.reason, gen: lastB.e.gen, phase: lastB.e.phase },
      resolved,
      ...(resolvedBy !== undefined ? { resolvedBy } : {}),
      ...(resolvedAt !== undefined ? { resolvedAt } : {}),
    }
  }
  return out
}

export function deriveStageStates(detail: LaneDetailLike, order: string[], opts?: LaneStatesOpts): LaneStatesResult {
  const blockedHistory = deriveBlockedHistory(detail, order, opts)
  if (detail.status === 'closed') {
    const states: Record<string, D2Visual> = {}
    for (const id of order) states[id] = 'done'
    return { states, active: [], fallback: false, blockedHistory }
  }
  const tl = detail.timeline
  if (!tl || tl.length === 0) {
    return { states: pointerStates(detail, order), active: [], fallback: true, blockedHistory }
  }
  // 畸形输入：缺字段的条目跳过；模板外 id 不入统计（不建状态、不进活跃数组）。
  const runningCount: Record<string, number> = {}
  const latest: Record<string, string> = {}
  const lastPosOf: Record<string, Record<string, number>> = {} // stage→state→最后位置（清洗后序）
  let pos = 0
  for (const t of tl) {
    if (!t || typeof t.stage !== 'string' || typeof t.state !== 'string') continue
    if (t.stage === '' || t.state === '') continue
    if (t.state === 'running') runningCount[t.stage] = (runningCount[t.stage] ?? 0) + 1
    latest[t.stage] = t.state
    ;(lastPosOf[t.stage] ??= {})[t.state] = pos
    pos++
  }
  // attempts：完整跑过的轮数。results 存在 = gen+1（软失败 failed 也计次）；
  // 无 results 而 checks 全 done = 1（merge/merge_check 纯脚本门）；其余 0。
  const checks = detail.checks ?? {}
  const results = detail.results ?? {}
  const attemptsOf = (id: string): number => {
    const r = results[id]
    if (r) return typeof r.gen === 'number' ? r.gen + 1 : 1
    const cs = checks[id]
    if (cs && cs.length > 0 && cs.every(c => c.done)) return 1
    return 0
  }
  // done 信号（先于逐态判定求 maxDoneIdx，供规则 5 兜底）。
  const doneIdx: number[] = []
  order.forEach((id, idx) => {
    const r = results[id]
    const cs = checks[id]
    if ((r && r.status === 'ok') || (cs && cs.length > 0 && cs.every(c => c.done))) doneIdx.push(idx)
  })
  const maxDoneIdx = doneIdx.length > 0 ? Math.max(...doneIdx) : -1
  const states: Record<string, D2Visual> = {}
  const active: string[] = []
  order.forEach((id, idx) => {
    // 规则 2：timeline 最新显式态优先。blocked 的「当前性」按解除证据判定
    //（t260916-04：已解除 → 完成色，受阻史走 blockedHistory 出角标；未解除保守红）。
    const last = latest[id]
    if (last === 'blocked') {
      const h = blockedHistory[id]
      if (h && h.resolved) { states[id] = 'done'; return }
      states[id] = 'blocked'
      return
    }
    if (last === 'awaiting-human' || last === 'done') {
      states[id] = last
      return
    }
    // 就地段信号（authorized/retry-requested）不重进段：最后一次受阻之后本段没有
    // 再 running/done/awaiting-human → 仍在受阻期内，按 blocked 显示（保守③）。
    if (last !== undefined && IN_PLACE_MARKS.has(last)) {
      const bp = lastPosOf[id]?.blocked
      if (bp !== undefined) {
        const rejoined = ['running', 'done', 'awaiting-human'].some(st => {
          const p = lastPosOf[id]?.[st]
          return p !== undefined && p > bp
        })
        if (!rejoined) { states[id] = 'blocked'; return }
      }
    }
    // 规则 4：inRun 计数（走到这里最新态必是 running 或无条目）。
    // （t260910-14：原预跑段排除条件随该段退役删除。）
    if ((runningCount[id] ?? 0) > attemptsOf(id)) {
      states[id] = 'running'
      active.push(id)
      return
    }
    // 规则 5：done 信号。
    const r = results[id]
    const cs = checks[id]
    if ((r && r.status === 'ok') || (cs && cs.length > 0 && cs.every(c => c.done)) || idx <= maxDoneIdx) {
      states[id] = 'done'
      return
    }
    states[id] = 'todo'
  })
  // KI-024 并行真值优先：列表内的步，未钉显式终态的一律 ▶ 入活跃数组。
  // （显式终态=规则 2 已落的 done/blocked/awaiting-human，先完成边的收口窗不重亮。）
  const parallelIds = parallelIdsOf(detail, order)
  for (const id of parallelIds) {
    const cur = states[id]
    if (cur === 'done' || cur === 'blocked' || cur === 'awaiting-human') continue
    states[id] = 'running'
    if (!active.includes(id)) active.push(id)
  }
  // 回退：活跃数组空 → 单值指针口径（逐字节保持现行为）。
  if (active.length === 0) {
    return { states: pointerStates(detail, order), active: [], fallback: true, blockedHistory }
  }
  return { states, active, fallback: false, blockedHistory }
}
