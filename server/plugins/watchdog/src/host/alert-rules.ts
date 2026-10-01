/**
 * alert 判级与节流（t260928-28，纯函数核）。
 *
 * 纪律（工单 scope 7 / 设计稿决策 6、9）：
 *  - 同一件事（同一 dedupe key）冷却内绝不重响；**去重状态可从 alerts.jsonl 重放重建**
 *    ——重启不重播过去 12 小时（replayDedupe）。
 *  - 夜间口径是配置不是硬规则（silent / redline-only / normal），红线级是夜里仍发声的例外。
 *  - 跨午夜窗（23:00–07:30）正确判定：start > end 视为跨午夜。
 *  - 未答复的 alert 永不自动变成决定——本模块只判「响不响」，不产任何动作。
 */

import type { WatchdogConfig } from './config.ts'

export type AlertLevel = 'info' | 'warn' | 'redline'

/** 一条 alert 的规则面（rule=规则名，target=对象如票号/会话 id）。 */
export interface AlertSpec {
  rule: string
  target: string
  level: AlertLevel
  title: string
  detail?: string
  /** 实例隔离域（t261001-19）：同一台机器上不同 DSH_HOME（如临时 home 的场景实例）
   *  与真宿主必须各自独立节流——临时 home 的一次报警不得静音真宿主 12 小时。
   *  缺省/空串 = 不隔离（保持历史 key 形状，旧账重放兼容）。 */
  scope?: string
}

export interface AlertRecord extends AlertSpec {
  key: string
  at: number
  night_muted: boolean
}

/** dedupe key：规则名 + 对象（+ 可选实例隔离域）。不同对象/不同隔离域各自独立节流。
 *  隔离域缺省时保持历史形状 `rule:target`（旧账重放兼容）；有隔离域为 `rule:target@scope`。 */
export function makeKey(rule: string, target: string, scope?: string): string {
  return scope === undefined || scope === '' ? `${rule}:${target}` : `${rule}:${target}@${scope}`
}

/** "HH:MM" → 当日分钟数。 */
function minutesOf(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

/** 是否处于夜间窗（跨午夜正确；窗边界只算一次——start 含、end 不含，读写共用同一定义）。 */
export function isNight(night: WatchdogConfig['alerts']['night'], atMs: number): boolean {
  const d = new Date(atMs)
  const cur = d.getHours() * 60 + d.getMinutes()
  const s = minutesOf(night.start)
  const e = minutesOf(night.end)
  if (s === e) return false // 零长窗 = 永远不在夜间（显式，不做"24h"猜谜）
  return s < e ? (cur >= s && cur < e) : (cur >= s || cur < e)
}

/** 夜间该级 alert 是否被静音（红线例外策略在配置的 policy + redline 名单）。 */
export function nightMuted(cfg: WatchdogConfig, spec: AlertSpec, atMs: number): boolean {
  if (!isNight(cfg.alerts.night, atMs)) return false
  if (cfg.alerts.night.policy === 'normal') return false
  if (cfg.alerts.night.policy === 'redline-only') return spec.level !== 'redline' || !cfg.alerts.redline.includes(spec.rule)
  return true // silent：全静音（记录照落，只是不发声）
}

/**
 * 冷却节流：key → { lastAt, count }。冷却窗默认 12h（重启不重播同一时间量级的依据）
 * ——可由 cooldownMs 覆盖（测试注入短窗）。N 不变不重响即由此承载。
 */
export type DedupeState = Map<string, { lastAt: number; count: number }>

export function cooldownExpired(state: DedupeState, key: string, nowMs: number, cooldownMs = 12 * 3600 * 1000): boolean {
  const hit = state.get(key)
  if (!hit) return true
  return nowMs - hit.lastAt >= cooldownMs
}

/** 从 alerts.jsonl 行重放去重状态（重启即弃内存；事实从账里读不从记忆里读）。 */
export function replayDedupe(rows: Array<Record<string, unknown>>, keepDays: number, nowMs: number): DedupeState {
  const state: DedupeState = new Map()
  const cutoff = keepDays > 0 ? nowMs - keepDays * 86400_000 : -Infinity
  for (const r of rows) {
    const at = typeof r.at === 'number' ? r.at : NaN
    const key = typeof r.key === 'string' ? r.key : ''
    if (!Number.isFinite(at) || at < cutoff || key === '') continue // 畸形行/过保留窗的行不进状态
    const hit = state.get(key)
    if (hit) { hit.count += 1; hit.lastAt = Math.max(hit.lastAt, at) }
    else state.set(key, { lastAt: at, count: 1 })
  }
  return state
}

/** 判定一条 alert 该不该落账/发声。返回 night_muted 只影响「发声」，记录永远落账。 */
export function judgeAlert(
  cfg: WatchdogConfig,
  spec: AlertSpec,
  state: DedupeState,
  nowMs: number,
  cooldownMs?: number,
): { record: boolean; key: string; night_muted: boolean } {
  const key = makeKey(spec.rule, spec.target, spec.scope)
  const record = cooldownExpired(state, key, nowMs, cooldownMs)
  return { record, key, night_muted: nightMuted(cfg, spec, nowMs) }
}

/** 记录落账后更新去重状态（与写 alerts.jsonl 同一事务面调用，先写后更）。 */
export function applyDedupe(state: DedupeState, key: string, nowMs: number): void {
  const hit = state.get(key)
  if (hit) { hit.count += 1; hit.lastAt = nowMs }
  else state.set(key, { lastAt: nowMs, count: 1 })
}
