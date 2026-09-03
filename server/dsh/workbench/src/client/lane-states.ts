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
 * 推导优先级（真值表每条锚定 dev_lane.py 源码行，方案 v3 经 review_plan
 * 第 4 轮通过；t260901-08 追加范围起引擎 _finish 落 done 终态条目（旧票无该
 * 条目自然回落下述启发式，存量数据不追改）：
 *  1. status==='closed' → 全部 done（短路）。
 *  2. timeline 最新一条显式态 ∈ {blocked, awaiting-human, done} → 直采该态
 *     （✗/✋/✓），不进活跃数组（_blocked/merge 签字/_finish 的 mark 都是追加在
 *     _enter 的 running 之后的独立条目，最新态即真相；merge 签字期据此显 ✋
 *     而非 ▶；done 终态条目优先于 inRun 计数——t260901-07 实锤：仲裁内部重跑
 *     复用结果文件不增 gen、merge_check 等脚本门重复进段只落 checks 不落
 *     results，计数启发式在重验循环后必误亮，终态留痕才是根治）。
 *  3. suggest_next 永不进活跃数组（merge 分支内联步，软失败留 running 无
 *     results，计数推导必误亮；全量 _mark 复核内联 running mark 仅此一例）。
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
 *    （fork 瞬间 timeline 轮询滞后/启发式误判面， arbitrate∥acceptance_walkthrough
 *    相邻边尤其受益）；
 *  - 畸形条目（非字符串/模板外 id）丢弃，与 timeline 畸形输入同纪律。
 */

/** 阶段视觉态：done✓ / running▶ / blocked✗ / awaiting-human✋ / todo○。 */
export type D2Visual = 'done' | 'running' | 'blocked' | 'awaiting-human' | 'todo'

/** 推导函数消费的 detail 最小结构（与 TicketDetail 的对应字段同构；
 *  独立声明是为了让本模块零类型依赖、node 裸 import 可用）。 */
export interface LaneDetailLike {
  status?: string
  stage?: string | null
  stage_state?: string
  timeline?: { at?: string; stage?: string; state?: string; reason?: string }[] | null
  results?: Record<string, { status?: string; gen?: number }>
  checks?: Record<string, { item: string; done: boolean; by?: string }[]>
  /** KI-024 并行真源：引擎快照放在 meta 全文里（meta.parallel_stages）；顶层
   *  同名字段留作直读兼容。两处都看，清洗口径一致（合法 id、去重保序）。 */
  parallel_stages?: string[]
  meta?: { parallel_stages?: string[] } | null
}

/** 推导结果：states 恒覆盖 order 每一步（含回退口径）；active=活跃步数组；
 *  fallback=true 表示本次走了单值指针回退（调用方如需区分新旧口径可用）。 */
export interface LaneStatesResult {
  states: Record<string, D2Visual>
  active: string[]
  fallback: boolean
}

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

export function deriveStageStates(detail: LaneDetailLike, order: string[]): LaneStatesResult {
  if (detail.status === 'closed') {
    const states: Record<string, D2Visual> = {}
    for (const id of order) states[id] = 'done'
    return { states, active: [], fallback: false }
  }
  const tl = detail.timeline
  if (!tl || tl.length === 0) {
    return { states: pointerStates(detail, order), active: [], fallback: true }
  }
  // 畸形输入：缺字段的条目跳过；模板外 id 不入统计（不建状态、不进活跃数组）。
  const runningCount: Record<string, number> = {}
  const latest: Record<string, string> = {}
  for (const t of tl) {
    if (!t || typeof t.stage !== 'string' || typeof t.state !== 'string') continue
    if (t.stage === '' || t.state === '') continue
    if (t.state === 'running') runningCount[t.stage] = (runningCount[t.stage] ?? 0) + 1
    latest[t.stage] = t.state
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
    // 规则 2：timeline 最新显式态优先。
    const last = latest[id]
    if (last === 'blocked' || last === 'awaiting-human' || last === 'done') {
      states[id] = last
      return
    }
    // 规则 3+4：suggest_next 内联步排除；inRun 计数（走到这里最新态必是 running 或无条目）。
    if (id !== 'suggest_next' && (runningCount[id] ?? 0) > attemptsOf(id)) {
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
    return { states: pointerStates(detail, order), active: [], fallback: true }
  }
  return { states, active, fallback: false }
}
