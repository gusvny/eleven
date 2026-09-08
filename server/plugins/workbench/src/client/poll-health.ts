/**
 * poll-health.ts —— 工单台轮询健康度状态机（KI-003③ UI 优雅降级，t260903-06）。
 *
 * 用户诉求：轮询失败不弹窗打断——静默重试 + 保持上次成功快照 + 角标提示数据
 * 可能滞后，只在连续 N 次失败后才显示错误态。本模块是纯函数状态机（无 React、
 * 无 IO），供 tests/ 单测直跑；index.tsx 的轮询 tick 消费它。
 *
 * 判据纪律（对齐 KI-025）：分类只认 body 的 kind 机器字段（apiGet 不透 HTTP
 * 状态码）；kind 缺失/未知值一律按可重试（retryable）降级处理——「不存在/
 * 终态」只能由明确 kind 触发，网络抖动绝不允许冒充不存在。
 */

/** 一次轮询的分类结果。 */
export type PollOutcome = 'ok' | 'retryable' | 'not_found' | 'terminal'

/** 连续可重试失败达到该次数才升错误态（3 次 ≈ 15s @5s 节拍）。 */
export const POLL_FAIL_THRESHOLD = 3

export interface PollHealthState {
  /** 连续可重试失败次数；成功即清零。 */
  failStreak: number
  /** true = 已达阈值，进入错误态（红条 + 慢轮询）。 */
  degraded: boolean
}

/**
 * API 回执 → 轮询分类。ok:true → ok；kind=not_found/terminal → 对应致命类；
 * 其余（transient/internal/kind 缺失/非对象/网络异常路径传 null）→ retryable。
 */
export function classifyPollBody(body: { ok?: unknown; kind?: unknown } | null | undefined): PollOutcome {
  if (body && body.ok === true) return 'ok'
  const kind = typeof body?.kind === 'string' ? body.kind : ''
  if (kind === 'not_found') return 'not_found'
  if (kind === 'terminal') return 'terminal'
  return 'retryable'
}

const _RANK: Record<PollOutcome, number> = { ok: 0, retryable: 1, not_found: 2, terminal: 2 }

/** 同一 tick 内多路请求（列表+详情）取最坏分类，作为本拍的健康度输入。 */
export function worstOutcome(a: PollOutcome, b: PollOutcome): PollOutcome {
  return _RANK[a] >= _RANK[b] ? a : b
}

/** 状态机转移：ok 清零；致命类立即错误态（不诱导重试）；可重试累加，达阈值升错误态。 */
export function nextPollState(prev: PollHealthState, outcome: PollOutcome): PollHealthState {
  if (outcome === 'ok') return { failStreak: 0, degraded: false }
  if (outcome === 'not_found' || outcome === 'terminal') {
    return { failStreak: prev.failStreak, degraded: true }
  }
  const n = prev.failStreak + 1
  return { failStreak: n, degraded: n >= POLL_FAIL_THRESHOLD }
}

export const INITIAL_POLL_STATE: PollHealthState = { failStreak: 0, degraded: false }
